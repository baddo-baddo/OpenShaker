"""Update check and one-click update.

The app asks GitHub for the latest release about 30 s after it starts and every 24 h after that (sooner
again after a network failure), unless the Advanced setting "Check for updates" is off (updates.check).
The request carries nothing but a User-Agent naming the version; no notification pops up: the tray
icon gets a "!" badge and the window a bar (gui.App). Nothing is downloaded until the user clicks
Update now or, with updates.auto on, until no game is running and the window is closed (gui.App._auto_tick).

Update now (an installed copy only; a source copy opens the Releases page instead):
- asks GitHub again, then downloads exactly OpenShaker-Setup-<version>.exe from that release (the URL
  must be REPO_URL/releases/download/<tag>/<name>), over HTTPS from GitHub's hosts only (every redirect
  is checked), into a fresh folder under %TEMP%, within a total deadline;
- checks the size against the API's and the SHA-256 against the one GitHub lists for that asset in the
  same API answer ("digest": "sha256:<hex>"; since 1.0.2 - no .sha256 file). A release without a usable
  digest is refused before anything is downloaded. On any mismatch or error it deletes what it
  downloaded - an unverified file is never run, and the file is hashed once more right before it runs;
- starts the installer with an argument list (no shell): /VERYSILENT; the installer's own --quit /
  AppMutex / RelaunchAfterSilentUpdate close the app and bring it back (/SHOWWINDOW=1 brings the window
  back when the click came from it), and bring the old version back if the update fails.

Testing against a local fake release: set OPENSHAKER_UPDATE_TEST=1 and OPENSHAKER_UPDATE_API to the fake
API URL. Only then are that URL and http://127.0.0.1 accepted, and the window says "[update test mode]";
normal use never reads them. OPENSHAKER_OFFLINE=1 blocks every request (the test suite sets it).
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from . import REPO_URL, __version__, paths

CHECK_DELAY_S = 30.0
CHECK_EVERY_S = 24 * 3600.0
RETRY_AFTER_S = (600.0, 3600.0, 4 * 3600.0)   # after a network failure: 10 min, 1 h, 4 h, then daily
TIMEOUT_S = 15.0                                # per connect and per read
SMALL_DEADLINE_S = 60.0                         # the API answer, in total
MIN_DOWNLOAD_S, MIN_RATE = 120.0, 50_000        # the installer: at least 2 min, or 50 kB/s
MAX_API_BYTES = 1_000_000
MAX_INSTALLER_BYTES = 200_000_000
GITHUB_HOSTS = ("github.com", "api.github.com", "objects.githubusercontent.com",
                "release-assets.githubusercontent.com", "github-releases.githubusercontent.com")
TEST_HOST = "127.0.0.1"
TEST_FLAG, TEST_API = "OPENSHAKER_UPDATE_TEST", "OPENSHAKER_UPDATE_API"
INSTALLER_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
TEMP_PREFIX = "OpenShaker-update-"
OLD_DOWNLOAD_S = 3600.0
LOG_NAME, LOG_KEEP = "update.log", 50

VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
DIGEST = re.compile(r"sha256:([0-9a-fA-F]{64})")      # GitHub's "digest" of a release asset


class UpdateError(Exception):
    """Anything that stops a check or an update; its text is shown in the window's update bar."""


class NetworkError(UpdateError):
    """The network itself failed (offline, a timeout, a broken connection): worth trying again soon."""


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    url: str


@dataclass(frozen=True)
class Release:
    version: str                  # "1.0.2"
    page_url: str                 # the release page ("What's new")
    installer: Asset
    sha256: str                   # GitHub's digest of the installer, lower-case hex; "" when it lists none usable


@dataclass(frozen=True)
class Verified:
    """A downloaded installer whose size and SHA-256 matched the release."""
    path: Path
    size: int
    sha256: str


# -- versions and addresses ------------------------------------------------------------------------
def parse_version(text) -> Optional[tuple]:
    """(major, minor, patch) for "1.2.3" or "v1.2.3"; None for anything else, pre-releases included."""
    m = VERSION.fullmatch(str(text or "").strip())
    return tuple(int(g) for g in m.groups()) if m else None


def is_newer(candidate, current=__version__) -> bool:
    new, cur = parse_version(candidate), parse_version(current)
    return new is not None and cur is not None and new > cur


def test_mode() -> bool:
    return os.environ.get(TEST_FLAG) == "1"


def offline() -> bool:
    """OPENSHAKER_OFFLINE=1: no network at all (the test suite sets it; a user may too)."""
    return os.environ.get("OPENSHAKER_OFFLINE") == "1"


def api_url() -> str:
    """GitHub's "latest release" address for REPO_URL; the fake one only while testing."""
    if test_mode() and os.environ.get(TEST_API):
        return os.environ[TEST_API]
    owner_repo = urlsplit(REPO_URL).path.strip("/")
    return f"https://api.github.com/repos/{owner_repo}/releases/latest"


def url_allowed(url: str) -> bool:
    """HTTPS on one of GitHub's hosts, the address exactly as it will be connected to (no user info, no
    other port); in test mode also http(s) on 127.0.0.1."""
    try:
        parts = urlsplit(str(url))
        host, port = (parts.hostname or "").lower(), parts.port
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            return False
    except ValueError:                               # a bad port or a broken address
        return False
    netloc = parts.netloc.lower()
    if parts.scheme == "https" and host in GITHUB_HOSTS and netloc in (host, f"{host}:443") and port in (None, 443):
        return True
    return test_mode() and parts.scheme in ("http", "https") and host == TEST_HOST and netloc.startswith(TEST_HOST)


def host_of(url) -> str:
    """For messages: the host of `url`, never raising."""
    try:
        return urlsplit(str(url)).hostname or repr(str(url))[:80]
    except ValueError:
        return repr(str(url))[:80]


# -- HTTP ------------------------------------------------------------------------------------------
def _opener():
    import urllib.request

    class Redirects(urllib.request.HTTPRedirectHandler):
        """Every hop must stay on an allowed host; GitHub sends assets to its release-asset hosts."""

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not url_allowed(newurl):
                raise UpdateError(f"refused a redirect to {host_of(newurl)}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return urllib.request.build_opener(Redirects)


def _open(url: str, accept: str):
    import urllib.error
    import urllib.request
    if offline():
        raise UpdateError("network use is switched off (OPENSHAKER_OFFLINE)")
    if not url_allowed(url):
        raise UpdateError(f"refused to contact {host_of(url)}")
    req = urllib.request.Request(url, headers={"User-Agent": f"OpenShaker/{__version__}", "Accept": accept})
    try:
        resp = _opener().open(req, timeout=TIMEOUT_S)
    except urllib.error.HTTPError as exc:            # GitHub answered: rate limit, gone, ...
        raise UpdateError(f"GitHub answered {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise NetworkError(f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}") from exc
    if not url_allowed(resp.geturl()):
        resp.close()
        raise UpdateError(f"refused to read from {host_of(resp.geturl())}")
    return resp


def _read(resp, deadline: float, size: int):
    """One block from `resp`; network errors and the deadline become NetworkError. read1() returns what
    one receive brings, so a server trickling a byte at a time cannot keep a block (and the deadline
    check) waiting; read() would wait for the whole block."""
    if time.monotonic() > deadline:
        raise NetworkError("the download took too long")
    try:
        return (getattr(resp, "read1", None) or resp.read)(size)
    except (OSError, http.client.HTTPException) as exc:
        raise NetworkError(f"{type(exc).__name__}: {exc}") from exc


def fetch_bytes(url: str, limit: int, accept: str = "application/octet-stream") -> bytes:
    """The body of `url`, at most `limit` bytes (more is an error), within SMALL_DEADLINE_S."""
    deadline, chunks, total = time.monotonic() + SMALL_DEADLINE_S, [], 0
    with _open(url, accept) as resp:
        while True:
            block = _read(resp, deadline, 1 << 16)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise UpdateError("the server sent more than expected")
            chunks.append(block)
    return b"".join(chunks)


def fetch_to(url: str, dest: Path, limit: int) -> tuple[int, str]:
    """Stream `url` into `dest`; (bytes written, SHA-256 hex). More than `limit` bytes is an error, and so
    is taking longer than max(MIN_DOWNLOAD_S, limit / MIN_RATE)."""
    deadline = time.monotonic() + max(MIN_DOWNLOAD_S, limit / MIN_RATE)
    digest, size = hashlib.sha256(), 0
    with _open(url, "application/octet-stream") as resp, open(dest, "wb") as out:
        while True:
            block = _read(resp, deadline, 1 << 16)
            if not block:
                break
            size += len(block)
            if size > limit:
                raise UpdateError("the download is larger than the release says")
            digest.update(block)
            out.write(block)
    return size, digest.hexdigest()


# -- the release -----------------------------------------------------------------------------------
def _asset_url_ok(url: str, tag: str, name: str) -> bool:
    """Exactly this repository's download address for this tag and file (or, in test mode, 127.0.0.1).
    GitHub treats owner and repository names case-insensitively, so they may differ in case; the tag and
    the file name must match exactly."""
    if not url_allowed(url):
        return False
    if test_mode() and host_of(url) == TEST_HOST:
        return True
    repo, rest = url[:len(REPO_URL)], url[len(REPO_URL):]
    return repo.lower() == REPO_URL.lower() and rest == f"/releases/download/{tag}/{name}"


def release_from(data, current: str = __version__) -> Optional[Release]:
    """The newer release described by GitHub's API answer, or None when there is none (a draft, a
    pre-release, a tag that is no X.Y.Z, or not newer). A newer release whose installer is missing or not
    where it must be is an UpdateError, so the reason can be logged. One whose installer has no usable
    "digest" is still offered, with sha256 "": download() then refuses it, so the bar points to the
    release page instead."""
    if not isinstance(data, dict):
        raise UpdateError("unexpected answer from GitHub")
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name")
    version = parse_version(tag) if isinstance(tag, str) else None
    if version is None or not is_newer(tag, current):
        return None
    text = ".".join(str(v) for v in version)
    name = f"OpenShaker-Setup-{text}.exe"
    installer, sha = None, ""
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise UpdateError(f"release {tag} lists no assets")
    for a in assets:                              # other assets (a .sha256, say) are ignored
        if not isinstance(a, dict) or a.get("name") != name:
            continue
        size, url = a.get("size"), a.get("browser_download_url")
        if installer is not None or not isinstance(size, int) or isinstance(size, bool) or not isinstance(url, str):
            raise UpdateError(f"release {tag} has an odd or doubled {name}")
        installer = Asset(name, size, url)
        digest = a.get("digest")
        match = DIGEST.fullmatch(digest) if isinstance(digest, str) else None
        sha = match.group(1).lower() if match else ""
    if installer is None:
        raise UpdateError(f"release {tag} has no {name}")
    if not 0 < installer.size <= MAX_INSTALLER_BYTES:
        raise UpdateError(f"release {tag}: the installer's size {installer.size} is not plausible")
    if not _asset_url_ok(installer.url, tag, name):
        raise UpdateError(f"release {tag}: {name} is not where it should be ({host_of(installer.url)})")
    page = data.get("html_url") if isinstance(data.get("html_url"), str) else ""
    if not (page == f"{REPO_URL}/releases/tag/{tag}" or (test_mode() and url_allowed(page))):
        page = f"{REPO_URL}/releases/tag/{tag}"
    return Release(text, page, installer, sha)


def check(current: str = __version__, fetch: Callable = fetch_bytes) -> Optional[Release]:
    """Ask GitHub once. The newer Release, or None; UpdateError (NetworkError for the network itself)
    when it could not tell."""
    raw = fetch(api_url(), MAX_API_BYTES, "application/vnd.github+json")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise UpdateError(f"unreadable answer from GitHub: {type(exc).__name__}") from exc
    return release_from(data, current)


def download(release: Release, temp_root: Optional[Path] = None, fetch_file: Callable = fetch_to) -> Verified:
    """The verified installer in a fresh folder under %TEMP%: its size and SHA-256 must be the ones
    GitHub lists for it. Without a usable digest nothing is downloaded. On any error the folder is
    deleted."""
    if not release.sha256:
        raise UpdateError(f"GitHub lists no SHA-256 for {release.installer.name}, so it cannot be checked; "
                          f"get it from the release page (What's new)")
    folder = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=temp_root))
    try:
        dest = folder / release.installer.name
        size, got = fetch_file(release.installer.url, dest, release.installer.size)
        if size != release.installer.size:
            raise UpdateError(f"the download has {size} bytes, the release says {release.installer.size}")
        if got.lower() != release.sha256:
            raise UpdateError("the download does not match its SHA-256")
        return Verified(dest, size, release.sha256)
    except BaseException as exc:
        shutil.rmtree(folder, ignore_errors=True)
        if isinstance(exc, (UpdateError, KeyboardInterrupt, SystemExit)):
            raise
        raise UpdateError(f"{type(exc).__name__}: {exc}") from exc


def _update_folder(path: Path, temp_root: Optional[Path] = None) -> Optional[Path]:
    """The OpenShaker-update-* folder `path` sits in, if it is one directly in the temp folder."""
    parent = Path(path).parent
    root = Path(temp_root or tempfile.gettempdir())
    try:
        if parent.name.startswith(TEMP_PREFIX) and parent.parent.resolve() == root.resolve():
            return parent
    except OSError:
        pass
    return None


def discard(path: Path, temp_root: Optional[Path] = None) -> None:
    """Delete a download's folder - only an OpenShaker-update-* folder in the temp folder, nothing else."""
    folder = _update_folder(path, temp_root)
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)


def clean_old_downloads(temp_root: Optional[Path] = None, older_than_s: float = OLD_DOWNLOAD_S) -> None:
    """Remove update folders left in %TEMP% by earlier updates (the installer ran from them). Local only:
    runs at every start, whatever the setting."""
    root = Path(temp_root or tempfile.gettempdir())
    now = time.time()
    for folder in root.glob(TEMP_PREFIX + "*"):
        try:
            if folder.is_dir() and now - folder.stat().st_mtime > older_than_s:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


def log(message: str, folder: Optional[Path] = None) -> None:
    """One timestamped line in logs/update.log (the last LOG_KEEP lines are kept); never raises."""
    try:
        path = Path(folder or paths.log_dir()) / LOG_NAME
        lines = path.read_text(encoding="utf-8").splitlines()[-(LOG_KEEP - 1):] if path.exists() else []
        lines.append(f"{datetime.now().isoformat(timespec='seconds')} {message}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


# -- installing ------------------------------------------------------------------------------------
def is_installed_copy() -> bool:
    """The installed app: the frozen exe with the installer's uninstaller next to it."""
    return paths.is_frozen() and (Path(sys.executable).resolve().parent / "unins000.exe").exists()


def installer_command(installer: Path, show_window: bool) -> list:
    """The installer and its arguments, as a list (never a shell command line)."""
    return [str(installer), *INSTALLER_ARGS, *(["/SHOWWINDOW=1"] if show_window else [])]


def _sha256_of(path: Path) -> tuple[int, str]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def run_installer(verified: Verified, show_window: bool, popen: Callable = subprocess.Popen,
                  installed: Callable = is_installed_copy, temp_root: Optional[Path] = None):
    """Start the verified installer, detached, once its file still matches. It quits this app, installs,
    and starts it again. Returns the process, so the app can notice an installer that ends early."""
    if not installed():
        raise UpdateError("only an installed copy can update itself")
    path = Path(verified.path)
    if _update_folder(path, temp_root) is None:
        raise UpdateError("that is not a downloaded update")
    if not path.is_file():
        raise UpdateError("the downloaded installer is gone (an antivirus may have removed it)")
    if _sha256_of(path) != (verified.size, verified.sha256):
        raise UpdateError("the downloaded installer changed after it was checked")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return popen(installer_command(path, show_window), shell=False, close_fds=True, creationflags=flags,
                 cwd=str(path.parent))
