"""The update check and one-click update (openshaker/updater.py and its window/tray side). All faked: no
network (tests/fakes.py sets OPENSHAKER_OFFLINE), no real installer, no real registry, no user files."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import close_window, fake_registry, no_optional_outputs, tk_root    # noqa: E402
from openshaker import REPO_URL, config, gui, tray, updater                  # noqa: E402
from test_haptics_switch import FakeRuntime                                  # noqa: E402

PAYLOAD = b"MZ fake installer " * 1000
SHA = hashlib.sha256(PAYLOAD).hexdigest()
NAME = "OpenShaker-Setup-1.0.2.exe"
AT = "@"                        # user-info URLs are spelled with this, so the file holds no e-mail-like text
REAL_DOWNLOAD = updater.download  # the window tests fake it; one of them needs the real refusal


def api_answer(tag="v1.0.2", **over):
    v = tag.lstrip("v")
    data = {"tag_name": tag, "draft": False, "prerelease": False, "html_url": f"{REPO_URL}/releases/tag/{tag}",
            "assets": [{"name": f"OpenShaker-Setup-{v}.exe", "size": len(PAYLOAD), "digest": f"sha256:{SHA}",
                        "browser_download_url": f"{REPO_URL}/releases/download/{tag}/OpenShaker-Setup-{v}.exe"},
                       {"name": f"OpenShaker-Setup-{v}.exe.sha256", "size": 100,
                        "browser_download_url": f"{REPO_URL}/releases/download/{tag}/OpenShaker-Setup-{v}.exe.sha256"}]}
    data.update(over)
    return data


def with_assets(fn, **over):
    """api_answer() with every asset passed through fn."""
    return api_answer(assets=[fn(dict(a)) for a in api_answer()["assets"]], **over)


def env(test, **values):
    """Set environment variables for this test only (None removes one)."""
    for key, value in values.items():
        test.addCleanup(lambda k=key, old=os.environ.get(key): os.environ.__setitem__(k, old) if old is not None
                        else os.environ.pop(k, None))
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def patch(test, obj, name, value):
    test.addCleanup(setattr, obj, name, getattr(obj, name))
    setattr(obj, name, value)


class VersionTests(unittest.TestCase):
    def test_versions_compare_as_numbers_and_only_newer_counts(self):
        self.assertEqual(updater.parse_version("v1.0.2"), (1, 0, 2))
        self.assertEqual(updater.parse_version("1.10.0"), (1, 10, 0))
        for bad in ("1.0.2-beta", "1.0", "v", "", None, "latest"):
            self.assertIsNone(updater.parse_version(bad), bad)
        self.assertTrue(updater.is_newer("1.0.1", "1.0.0"))
        self.assertTrue(updater.is_newer("v1.10.0", "1.9.9"))
        self.assertFalse(updater.is_newer("1.0.0", "1.0.0"), "the same version is not an update")
        self.assertFalse(updater.is_newer("0.9.9", "1.0.0"), "never downgrade")
        self.assertFalse(updater.is_newer("1.0.2-rc1", "1.0.0"), "pre-release tags are ignored")


class AddressTests(unittest.TestCase):
    def setUp(self):
        env(self, OPENSHAKER_UPDATE_TEST=None)

    def test_only_https_on_githubs_hosts_exactly_as_connected(self):
        for good in ("https://api.github.com/repos/x/y/releases/latest", f"{REPO_URL}/releases/download/v1.0.2/{NAME}",
                     "https://objects.githubusercontent.com/a", "https://release-assets.githubusercontent.com/a",
                     "https://github.com:443/x"):
            self.assertTrue(updater.url_allowed(good), good)
        for bad in ("http://github.com/x", "https://github.com:444/x", "https://evil.example/x",
                    "https://github.com.evil.example/x", f"https://github.com{AT}example.com/x",
                    f"https://example.com{AT}github.com/x", f"https://evil.example\\{AT}github.com/x",
                    f"https://user:pw{AT}github.com/x", "https://github.com:abc/x", "https://github.com:99999/x",
                    "https://[::1/x", "http://127.0.0.1:8000/x", "file:///C:/x.exe", "not a url", None):
            self.assertFalse(updater.url_allowed(bad), bad)

    def test_the_api_address_comes_from_repo_url_and_the_override_only_in_test_mode(self):
        env(self, OPENSHAKER_UPDATE_API="http://127.0.0.1:8000/latest")
        self.assertEqual(updater.api_url(), "https://api.github.com/repos/baddo-baddo/OpenShaker/releases/latest")
        self.assertFalse(updater.url_allowed("http://127.0.0.1:8000/latest"), "no local server outside test mode")
        env(self, OPENSHAKER_UPDATE_TEST="1")
        self.assertEqual(updater.api_url(), "http://127.0.0.1:8000/latest")
        self.assertTrue(updater.url_allowed("http://127.0.0.1:8000/latest"))
        self.assertFalse(updater.url_allowed("http://localhost:8000/latest"), "127.0.0.1 only")
        self.assertFalse(updater.url_allowed(f"http://x{AT}127.0.0.1:8000/latest"))

    def test_every_redirect_is_checked_and_a_bad_one_cannot_crash_the_check(self):
        opener = updater._opener()
        handler = next(h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
        req = urllib.request.Request(f"{REPO_URL}/releases/download/v1.0.2/{NAME}")
        for bad in ("https://evil.example/x.exe", "https://[::1/x", "https://github.com:x/y"):
            with self.subTest(bad), self.assertRaises(updater.UpdateError):
                handler.redirect_request(req, None, 302, "Found", {}, bad)
        ok = handler.redirect_request(req, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/a")
        self.assertEqual(ok.full_url, "https://release-assets.githubusercontent.com/a")

    def test_a_refused_host_is_never_contacted(self):
        env(self, OPENSHAKER_OFFLINE=None)                  # past the offline guard: the host check stops it
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.fetch_bytes("https://evil.example/latest", 100)
        self.assertIn("refused", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, updater.NetworkError)

    def test_the_test_suite_is_offline(self):
        self.assertTrue(updater.offline())
        with self.assertRaises(updater.UpdateError):
            updater.fetch_bytes(updater.api_url(), 100)


class FakeResponse:
    """What _open returns: read1() gives what one receive brings (`trickle` bytes at most), optionally
    slowly or failing; read(n) waits for n bytes, as http.client's does."""

    def __init__(self, body=b"", delay=0.0, error=None, trickle=None):
        self.body, self.delay, self.error, self.trickle = body, delay, error, trickle

    def read1(self, n):
        if self.error:
            raise self.error
        time.sleep(self.delay)
        n = min(n, self.trickle or n)
        block, self.body = self.body[:n], self.body[n:]
        return block

    def read(self, n):
        out = b""
        while len(out) < n:
            block = self.read1(n - len(out))
            if not block:
                break
            out += block
        return out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def serve(self, response):
        patch(self, updater, "_open", lambda url, accept: response)

    def test_a_download_has_a_total_deadline(self):
        self.serve(FakeResponse(b"x" * (1 << 20), delay=0.02))
        patch(self, updater, "MIN_DOWNLOAD_S", 0.05)
        patch(self, updater, "MIN_RATE", 10 ** 12)          # the deadline is then the 0.05 s floor
        with self.assertRaises(updater.NetworkError) as ctx:
            updater.fetch_to("https://github.com/x", self.dir / "f", 1 << 20)
        self.assertIn("too long", str(ctx.exception))

    def test_a_trickling_server_cannot_hold_the_deadline_off(self):
        # a byte per receive, each well inside the socket timeout: a whole-block read() would wait ~2 s
        self.serve(FakeResponse(b"x" * 400, delay=0.005, trickle=1))
        patch(self, updater, "MIN_DOWNLOAD_S", 0.1)
        patch(self, updater, "MIN_RATE", 10 ** 12)
        started = time.monotonic()
        with self.assertRaises(updater.NetworkError) as ctx:
            updater.fetch_to("https://github.com/x", self.dir / "f", 1 << 20)
        self.assertIn("too long", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 1.0, "stopped at the deadline, not after a whole block")

    def test_a_response_without_read1_still_reads(self):
        class Plain(FakeResponse):
            read1 = None
            read = FakeResponse.read1                       # a read(n) that returns what it has
        self.serve(Plain(b"abc"))
        self.assertEqual(updater.fetch_bytes("https://github.com/x", 100), b"abc")

    def test_a_broken_connection_is_a_network_error(self):
        import http.client
        for error in (OSError("reset"), http.client.IncompleteRead(b"x")):
            with self.subTest(type(error).__name__):
                self.serve(FakeResponse(error=error))
                with self.assertRaises(updater.NetworkError):
                    updater.fetch_bytes("https://github.com/x", 100)

    def test_more_than_the_limit_is_refused(self):
        self.serve(FakeResponse(b"x" * 500))
        with self.assertRaises(updater.UpdateError):
            updater.fetch_bytes("https://github.com/x", 100)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        env(self, OPENSHAKER_UPDATE_TEST=None)

    def test_a_newer_release_with_both_assets(self):
        r = updater.release_from(api_answer(), current="1.0.1")
        self.assertEqual((r.version, r.installer.size), ("1.0.2", len(PAYLOAD)))
        self.assertEqual(r.installer.url, f"{REPO_URL}/releases/download/v1.0.2/{NAME}")
        self.assertEqual(r.page_url, f"{REPO_URL}/releases/tag/v1.0.2")

    def test_drafts_prereleases_odd_tags_and_older_releases_are_no_update(self):
        for name, data in {"draft": api_answer(draft=True), "prerelease": api_answer(prerelease=True),
                           "same": api_answer("v1.0.1"), "older": api_answer("v1.0.0"),
                           "odd tag": api_answer(tag_name="nightly"), "tag not text": api_answer(tag_name=[1])}.items():
            with self.subTest(name):
                self.assertIsNone(updater.release_from(data, current="1.0.1"))

    def test_a_newer_release_with_unusable_assets_says_why(self):
        other_tag = lambda a: dict(a, browser_download_url=a["browser_download_url"].replace("/v1.0.2/", "/v0.0.1/"))
        cases = {
            "not a dict": ["x"],
            "no assets list": api_answer(assets=5),
            "twice": api_answer(assets=api_answer()["assets"] + api_answer()["assets"][:1]),
            "other repo": with_assets(lambda a: dict(a, browser_download_url=a["browser_download_url"].replace(
                "baddo-baddo/OpenShaker", "someone/else"))),
            "other tag": with_assets(other_tag),
            "dot segments": with_assets(lambda a: dict(a, browser_download_url=(
                f"{REPO_URL}/releases/download/../../../../evil/repo/releases/download/v1.0.2/{a['name']}"))),
            "query": with_assets(lambda a: dict(a, browser_download_url=a["browser_download_url"] + "?x=1")),
            "other host": with_assets(lambda a: dict(a, browser_download_url="https://evil.example/" + a["name"])),
            "plain http": with_assets(lambda a: dict(a, browser_download_url=a["browser_download_url"].replace(
                "https://", "http://"))),
            "bad port": with_assets(lambda a: dict(a, browser_download_url="https://github.com:x/y")),
            "no size": with_assets(lambda a: dict(a, size=0) if a["name"] == NAME else a),
            "size is text": with_assets(lambda a: dict(a, size="21")),
            "size is a bool": with_assets(lambda a: dict(a, size=True)),
            "size is huge": with_assets(lambda a: dict(a, size=10 ** 400) if a["name"] == NAME else a),
            "url not text": with_assets(lambda a: dict(a, browser_download_url=None)),
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(updater.UpdateError):
                updater.release_from(data, current="1.0.1")
        odd_names = api_answer(assets=[{"name": [1]}, {"name": None}] + api_answer()["assets"])
        self.assertEqual(updater.release_from(odd_names, current="1.0.1").version, "1.0.2", "odd entries are skipped")

    def test_owner_and_repo_may_differ_in_case_but_tag_and_file_may_not(self):
        other_case = with_assets(lambda a: dict(a, browser_download_url=a["browser_download_url"].replace(
            "baddo-baddo/OpenShaker", "Baddo-Baddo/openshaker")))
        self.assertEqual(updater.release_from(other_case, current="1.0.1").version, "1.0.2")
        for name, old, new in (("tag", "/v1.0.2/", "/V1.0.2/"), ("file", "/OpenShaker-Setup", "/openshaker-setup")):
            data = with_assets(lambda a: dict(a, browser_download_url=a["browser_download_url"].replace(old, new)))
            with self.subTest(name), self.assertRaises(updater.UpdateError):
                updater.release_from(data, current="1.0.1")

    def test_the_sha256_is_githubs_digest_of_the_installer(self):
        self.assertEqual(updater.release_from(api_answer(), current="1.0.1").sha256, SHA)
        no_file = api_answer(assets=api_answer()["assets"][:1])
        self.assertEqual(updater.release_from(no_file, current="1.0.1").sha256, SHA, "no .sha256 file needed")
        upper = with_assets(lambda a: dict(a, digest="sha256:" + SHA.upper()) if a["name"] == NAME else a)
        self.assertEqual(updater.release_from(upper, current="1.0.1").sha256, SHA, "upper-case hex: the same hash")
        bad = {"missing": None, "not text": 5, "another algorithm": "sha512:" + SHA, "upper-case prefix": "SHA256:" + SHA,
               "short": "sha256:" + SHA[:-1], "long": "sha256:" + SHA + "0", "not hex": "sha256:" + "g" * 64,
               "bare hash": SHA, "padded": " sha256:" + SHA, "empty": ""}
        for name, digest in bad.items():
            with self.subTest(name):
                def change(a, d=digest):
                    if a["name"] != NAME:
                        return a
                    return {k: v for k, v in a.items() if k != "digest"} if d is None else dict(a, digest=d)
                r = updater.release_from(with_assets(change), current="1.0.1")
                self.assertEqual((r.version, r.sha256), ("1.0.2", ""), "still offered; download() refuses it")

    def test_a_foreign_release_page_falls_back_to_ours(self):
        r = updater.release_from(api_answer(html_url="https://evil.example/notes"), current="1.0.1")
        self.assertEqual(r.page_url, f"{REPO_URL}/releases/tag/v1.0.2")

    def test_check_asks_the_api_once_and_bad_json_is_an_update_error(self):
        asked = []

        def fetch(url, limit, accept):
            asked.append((url, accept))
            return json.dumps(api_answer()).encode()
        self.assertEqual(updater.check("1.0.1", fetch=fetch).version, "1.0.2")
        self.assertEqual(asked, [(updater.api_url(), "application/vnd.github+json")])
        for raw in (b"<html>rate limited</html>", b"[" * 100_000, b"\xff\xfe{}"):
            with self.subTest(raw[:10]), self.assertRaises(updater.UpdateError):
                updater.check("1.0.1", fetch=lambda *_a, r=raw: r)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        env(self, OPENSHAKER_UPDATE_TEST=None)
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.release = updater.release_from(api_answer(), current="1.0.1")

    def fetcher(self, payload=PAYLOAD, error=None):
        def fetch_file(url, dest, limit):
            if error:
                raise error
            self.assertEqual(url, self.release.installer.url, "the installer only: there is no .sha256 to fetch")
            Path(dest).write_bytes(payload)
            return len(payload), hashlib.sha256(payload).hexdigest()
        return fetch_file

    def leftovers(self):
        return list(self.temp.glob(updater.TEMP_PREFIX + "*"))

    def test_a_verified_download(self):
        v = updater.download(self.release, self.temp, self.fetcher())
        self.assertEqual((v.path.read_bytes(), v.size, v.sha256), (PAYLOAD, len(PAYLOAD), SHA))
        self.assertTrue(v.path.parent.name.startswith(updater.TEMP_PREFIX))
        self.assertEqual(v.path.parent.parent, self.temp)

    def test_every_mismatch_aborts_and_deletes(self):
        cases = {
            "size": self.fetcher(payload=PAYLOAD + b"x"),
            "hash": self.fetcher(payload=PAYLOAD[:-1] + b"?"),
            "network": self.fetcher(error=OSError("timed out")),
        }
        for name, fetch_file in cases.items():
            with self.subTest(name):
                with self.assertRaises(updater.UpdateError):
                    updater.download(self.release, self.temp, fetch_file)
                self.assertEqual(self.leftovers(), [], "nothing is left behind")

    def test_a_digest_that_does_not_match_the_file_aborts_and_deletes(self):
        other = updater.Release("1.0.2", REPO_URL, self.release.installer, "0" * 64)
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.download(other, self.temp, self.fetcher())
        self.assertIn("does not match its SHA-256", str(ctx.exception))
        self.assertEqual(self.leftovers(), [])

    def test_without_a_usable_digest_nothing_is_downloaded(self):
        release = updater.Release("1.0.2", REPO_URL, self.release.installer, "")
        fetched = []
        with self.assertRaises(updater.UpdateError) as ctx:
            updater.download(release, self.temp, lambda *a: fetched.append(a))
        self.assertIn("GitHub lists no SHA-256", str(ctx.exception))
        self.assertIn("release page", str(ctx.exception))
        self.assertEqual((fetched, self.leftovers()), ([], []))

    def test_a_wrong_host_aborts_and_deletes(self):
        env(self, OPENSHAKER_OFFLINE=None)                  # the real fetchers: the host check stops them
        bad = updater.Asset(NAME, len(PAYLOAD), "https://evil.example/" + NAME)
        release = updater.Release("1.0.2", REPO_URL, bad, SHA)
        with self.assertRaises(updater.UpdateError):
            updater.download(release, self.temp)
        self.assertEqual(self.leftovers(), [])

    def test_old_update_folders_are_cleaned_up_and_discard_touches_only_update_folders(self):
        old, fresh = self.temp / (updater.TEMP_PREFIX + "old"), self.temp / (updater.TEMP_PREFIX + "new")
        old.mkdir(), fresh.mkdir()
        os.utime(old, (time.time() - 2 * updater.OLD_DOWNLOAD_S,) * 2)
        updater.clean_old_downloads(self.temp)
        self.assertEqual(self.leftovers(), [fresh])
        other = self.temp / "keep"
        other.mkdir()
        (other / NAME).write_bytes(b"x")
        updater.discard(other / NAME, self.temp)
        self.assertTrue(other.exists(), "a folder that is no update folder is never deleted")
        updater.discard(fresh / NAME, self.temp)
        self.assertEqual(self.leftovers(), [])

    def test_the_log_keeps_its_last_lines(self):
        for i in range(updater.LOG_KEEP + 10):
            updater.log(f"line {i}", self.temp)
        lines = (self.temp / updater.LOG_NAME).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), updater.LOG_KEEP)
        self.assertTrue(lines[-1].endswith(f"line {updater.LOG_KEEP + 9}"))
        updater.log("never raises", self.temp / "missing" / "folder")


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.exe = self.temp / (updater.TEMP_PREFIX + "x") / NAME
        self.exe.parent.mkdir()
        self.exe.write_bytes(PAYLOAD)
        self.verified = updater.Verified(self.exe, len(PAYLOAD), SHA)
        self.runs = []

    def popen(self, args, **kw):
        self.runs.append((args, kw))
        return "process"

    def run_it(self, verified=None, show=True):
        return updater.run_installer(verified or self.verified, show, popen=self.popen, installed=lambda: True,
                                     temp_root=self.temp)

    def test_an_argument_list_no_shell_and_the_window_flag_only_when_asked(self):
        self.assertEqual(self.run_it(show=True), "process", "the app keeps the process to watch it")
        self.run_it(show=False)
        (with_window, kw), (tray_only, _kw) = self.runs
        self.assertEqual(with_window, [str(self.exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SHOWWINDOW=1"])
        self.assertEqual(tray_only, [str(self.exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        self.assertIs(kw["shell"], False)

    def test_the_file_is_hashed_again_right_before_it_runs(self):
        self.exe.write_bytes(PAYLOAD[:-1] + b"!")                                # swapped after the check
        with self.assertRaises(updater.UpdateError) as ctx:
            self.run_it()
        self.assertIn("changed", str(ctx.exception))
        self.exe.unlink()
        with self.assertRaises(updater.UpdateError) as ctx:
            self.run_it()
        self.assertIn("gone", str(ctx.exception))
        self.assertEqual(self.runs, [])

    def test_a_source_copy_or_a_stray_file_never_runs(self):
        with self.assertRaises(updater.UpdateError):
            updater.run_installer(self.verified, True, popen=self.popen, installed=lambda: False, temp_root=self.temp)
        stray = self.temp / NAME
        stray.write_bytes(PAYLOAD)
        with self.assertRaises(updater.UpdateError):
            self.run_it(updater.Verified(stray, len(PAYLOAD), SHA))
        self.assertEqual(self.runs, [])
        self.assertFalse(updater.is_installed_copy(), "the test run is not an installed copy")


class FakeProcess:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


@unittest.skipUnless(tray.AVAILABLE, f"pystray/Pillow not installed ({tray.IMPORT_ERROR})")
class WindowTests(unittest.TestCase):
    """The badge and the bar, Skip, Update now, failures, automatic updates; never a notification."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        env(self, OPENSHAKER_UPDATE_TEST=None, OPENSHAKER_HOME=str(self.dir))   # update.log lands here
        fake_registry(self)
        no_optional_outputs(self)
        self.path = self.dir / "config.json"
        patch(self, gui, "Runtime", FakeRuntime)
        FakeRuntime.made, FakeRuntime.fail = [], False
        from test_tray import FakeIcon
        patch(self, tray.pystray, "Icon", FakeIcon)
        self.asked, self.downloads, self.installs, self.opened, self.questions = [], [], [], [], []
        self.games = set()                                  # the running executables procs.py reports
        patch(self, gui.procs, "running", lambda force=False: frozenset(self.games))
        patch(self, updater, "check", self.fake_check)
        patch(self, updater, "download", self.fake_download)
        patch(self, updater, "run_installer", self.fake_run)
        patch(self, updater, "is_installed_copy", lambda: True)
        patch(self, gui.webbrowser, "open", lambda url: self.opened.append(url) or True)
        patch(self, gui.messagebox, "askyesno", self.fake_ask)
        self.answer = updater.release_from(api_answer(), current="1.0.1")
        self.check_error = self.download_error = self.install_error = None
        self.yes, self.process, self.during_question = True, FakeProcess(), None

    def fake_check(self):
        self.asked.append(1)
        if self.check_error:
            raise self.check_error
        return self.answer

    def fake_download(self, release):
        self.downloads.append(release.version)
        if isinstance(self.download_error, Exception):
            raise self.download_error
        if self.download_error:
            raise updater.UpdateError(self.download_error)
        return updater.Verified(self.dir / NAME, len(PAYLOAD), SHA)

    def fake_run(self, verified, show):
        if self.install_error:
            raise updater.UpdateError(self.install_error)
        self.installs.append((verified.path, show))
        return self.process

    def fake_ask(self, *a, **k):
        self.questions.append(a)
        if self.during_question:
            self.during_question()
        return self.yes

    def app(self, check=True, no_start=False, **kw):
        if not check:
            self.path.write_text(json.dumps({"updates": {"check": False}}), encoding="utf-8")
        root = tk_root()
        self.addCleanup(close_window, root)
        app = gui.App(root, config.load(self.path), str(self.path), start_haptics=False, use_tray=True,
                      ask_startup=False, **kw)
        app._no_start = no_start          # a normal launch unless asked (these tests just never start haptics)
        self.assertTrue(app.tray.active)
        return app

    def checked(self, app):
        app._update_worker()                              # the worker thread's body, run here
        app._drain_ui_queue()

    def wait_for(self, app, name):
        for t in [t for t in threading.enumerate() if t.name == name]:
            t.join(5)
        app._drain_ui_queue()

    def game_running(self, app):
        status = FakeRuntime(app.cfg).status()               # a whole status, as the running app has one
        status["tele"] = type("Tele", (), {"active": True, "source": "forza"})()
        app._last_status = status

    def tray_item(self, app):
        return next(i for i in app.tray.icon.menu if str(i).startswith(("Update ", "Updating ")))

    def test_an_update_shows_a_badge_and_a_bar_and_no_notification(self):
        app = self.app()
        self.assertIsNotNone(app._update_job, "a check is scheduled for ~30 s after start")
        self.assertEqual(app.update_bar.winfo_manager(), "", "no bar before a check")
        self.checked(app)
        self.assertEqual(app.update_version(), "1.0.2")
        self.assertEqual(app.update_bar.winfo_manager(), "pack")
        self.assertIn("1.0.2 is available", app.update_var.get())
        self.assertNotIn("test mode", app.update_var.get())
        self.assertNotEqual(app.tray.icon.icon.tobytes(), app.tray._stopped_img.tobytes(), "the tray icon has a badge")
        self.assertEqual(app.tray.icon.notified, [], "no pop-up")
        app.open_whats_new()
        self.assertEqual(self.opened, [f"{REPO_URL}/releases/tag/v1.0.2"])

    def test_a_pulled_release_is_no_longer_offered(self):
        app = self.app()
        self.checked(app)
        self.answer = None                                # GitHub answers: nothing newer after all
        self.checked(app)
        self.assertEqual((app.update_version(), app.update_bar.winfo_manager()), ("", ""))
        self.assertEqual(app.tray.icon.icon.tobytes(), app.tray._stopped_img.tobytes(), "the badge went too")

    def test_update_now_asks_again_first_and_installs_nothing_that_was_pulled(self):
        app = self.app()
        self.checked(app)
        self.answer = None
        app.update_now()
        self.wait_for(app, "update")
        self.assertEqual((self.downloads, self.installs), ([], []))
        self.assertEqual(app.update_version(), "")
        self.assertIn("no longer offered", app.msg_var.get())

    def test_update_now_installs_only_the_version_clicked(self):
        app = self.app()
        self.checked(app)                                 # 1.0.2 shown
        self.answer = updater.release_from(api_answer("v1.0.3"), current="1.0.1")    # replaced meanwhile
        app.update_now()
        self.wait_for(app, "update")
        self.assertEqual((self.downloads, self.installs), ([], []))
        self.assertIn("1.0.2 is no longer offered", app.msg_var.get())
        self.assertEqual(app.update_version(), "1.0.3", "the bar offers the new one instead")
        self.assertIn("1.0.3 is available", app.update_var.get())
        self.assertFalse(app._update_busy)
        app.cfg.setdefault("updates", {})["skip"] = "1.0.2"
        self.answer = updater.release_from(api_answer(), current="1.0.1")   # 1.0.3 pulled: the skipped 1.0.2
        app.update_now()
        self.wait_for(app, "update")
        self.assertEqual((self.downloads, self.installs), ([], []), "a skipped version is never installed")
        self.assertEqual((app.update_version(), app.update_bar.winfo_manager()), ("", ""))

    def test_a_skipped_release_coming_back_hides_the_one_shown(self):
        app = self.app()
        self.checked(app)
        app.skip_update()                                 # 1.0.2 skipped
        self.answer = updater.release_from(api_answer("v1.0.3"), current="1.0.1")
        self.checked(app)
        self.assertEqual(app.update_version(), "1.0.3")
        self.answer = updater.release_from(api_answer(), current="1.0.1")   # 1.0.3 pulled: 1.0.2 is latest again
        self.checked(app)
        self.assertEqual((app.update_version(), app.update_bar.winfo_manager()), ("", ""))

    def test_skip_is_saved_a_newer_version_shows_again_and_a_bad_skip_is_ignored(self):
        app = self.app()
        self.checked(app)
        app.skip_update()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["updates"],
                         {"skip": "1.0.2", "auto_asked": True}, "skipping answers the automatic-updates question too")
        self.assertEqual((app.update_version(), app.update_bar.winfo_manager()), ("", ""))
        self.checked(app)
        self.assertEqual(app.update_version(), "", "the skipped version stays hidden")
        self.answer = updater.release_from(api_answer("v1.0.3"), current="1.0.1")
        self.checked(app)
        self.assertEqual(app.update_version(), "1.0.3", "a newer one shows again")
        app.cfg["updates"]["skip"] = "latest"             # a hand-edit that is no version
        self.checked(app)
        self.assertEqual(app.update_version(), "1.0.3", "hides nothing")

    def test_the_setting_off_means_no_request_at_all(self):
        app = self.app(check=False)
        self.assertIsNone(app._update_job)
        app._start_update_check()
        self.assertEqual(self.asked, [], "nothing asked GitHub")
        app.cfg["updates"]["check"] = True
        app._apply_advanced([])
        self.assertIsNotNone(app._update_job, "switched back on: a check is scheduled")
        self.checked(app)
        app._apply_advanced([((app.cfg["updates"], "check"), False)])
        self.assertIsNone(app._update_job)
        self.assertEqual(app.update_version(), "", "switching it off hides a shown update")
        self.assertIs(json.loads(self.path.read_text(encoding="utf-8"))["updates"]["check"], False)

    def test_a_network_failure_retries_sooner_and_anything_else_waits_a_day(self):
        app = self.app()
        delays = []
        patch(self, app, "_schedule_update_check", lambda s: delays.append(s))
        self.check_error = updater.NetworkError("URLError: no network")
        for _ in range(4):
            self.checked(app)
        self.check_error = updater.UpdateError("GitHub answered 403 rate limit exceeded")
        self.checked(app)
        self.check_error = None
        self.checked(app)
        self.assertEqual(delays, [*updater.RETRY_AFTER_S, updater.CHECK_EVERY_S, updater.CHECK_EVERY_S,
                                  updater.CHECK_EVERY_S])
        self.assertEqual(app.update_version(), "1.0.2")
        log = (self.dir / "logs" / updater.LOG_NAME).read_text(encoding="utf-8")
        self.assertIn("check failed: NetworkError: URLError: no network", log)
        self.assertIn("403", log)
        self.assertEqual(app.tray.icon.notified, [])

    def test_update_now_downloads_then_runs_the_installer_bringing_the_window_back(self):
        app = self.app()
        self.checked(app)
        app.update_now()
        self.assertEqual(app.update_status(), "busy")
        self.assertEqual(str(self.tray_item(app)), "Updating to 1.0.2...")
        self.assertFalse(self.tray_item(app).enabled)
        self.wait_for(app, "update")
        self.assertEqual(self.downloads, ["1.0.2"])
        self.assertEqual(self.installs, [(self.dir / NAME, True)])
        self.assertIn("Installing", app.update_var.get())
        self.assertEqual(self.questions, [], "no game running: no question")

    def test_an_installer_that_ends_early_or_hangs_frees_update_now_again(self):
        app = self.app()
        self.checked(app)
        app.update_now()
        self.wait_for(app, "update")
        self.process.code = 2                              # setup gave up while this app still runs
        app._watch_installer()
        self.assertFalse(app._update_busy)
        self.assertIn("ended without updating (exit code 2)", app.update_var.get())
        self.assertEqual(app.update_status(), "failed")
        self.assertEqual(str(self.tray_item(app)), "Update to 1.0.2 failed - open OpenShaker")
        self.assertIn("update to 1.0.2 failed", (self.dir / "logs" / updater.LOG_NAME).read_text(encoding="utf-8"))
        self.process = FakeProcess()
        app.update_now()                                   # tries again
        self.wait_for(app, "update")
        app._installer_watch = (self.process, time.monotonic() - gui.INSTALLER_WAIT_S - 1)
        app._watch_installer()
        self.assertIn("did not finish", app.update_var.get())
        self.assertEqual(app.tray.icon.notified, [])

    def test_from_the_tray_it_comes_back_in_the_tray_and_a_failure_opens_the_window(self):
        app = self.app()
        self.checked(app)
        app.update_from_tray()
        self.wait_for(app, "update")
        self.assertEqual(self.installs, [(self.dir / NAME, False)])
        app._update_failed("the installer ended without updating (exit code 1)")
        shown = []
        patch(self, app, "show_window", lambda: shown.append(1))
        app.update_from_tray()
        self.assertEqual(shown, [1], "a failure's tray item opens the window, where the bar says why")

    def test_a_failed_download_or_installer_start_says_so_and_installs_nothing(self):
        for field, text in (("download_error", "the download does not match its SHA-256"),
                            ("install_error", "the downloaded installer changed after it was checked")):
            with self.subTest(field):
                setattr(self, field, text)
                app = self.app()
                self.checked(app)
                app.update_now()
                self.wait_for(app, "update")
                self.assertEqual(self.installs, [])
                self.assertIn(f"failed: {text}", app.update_var.get())
                self.assertFalse(app._update_busy, "Update now can be tried again")
                setattr(self, field, None)

    def test_a_game_running_asks_first_in_the_window_and_blocks_a_second_click(self):
        app = self.app()
        self.checked(app)
        self.game_running(app)
        shown = []
        patch(self, app, "show_window", lambda: shown.append(1))
        self.during_question = lambda: app.update_from_tray()   # a second click while the question is open
        self.yes = False
        app.update_now()
        self.assertEqual([q[1] for q in self.questions], [gui.UPDATE_CONFIRM], "asked once, not twice")
        self.assertEqual(shown, [1], "the window comes up so the question is not hidden behind the game")
        self.assertEqual(self.downloads, [], "no means no")
        self.assertFalse(app._update_busy)
        self.during_question, self.yes = None, True
        app.update_now()
        self.wait_for(app, "update")
        self.assertEqual(self.downloads, ["1.0.2"])

    def test_a_release_without_a_usable_digest_points_to_the_release_page(self):
        patch(self, updater, "download", REAL_DOWNLOAD)     # the real refusal, before any network
        self.answer = updater.release_from(with_assets(
            lambda a: {k: v for k, v in a.items() if k != "digest"}), current="1.0.1")
        app = self.app()
        self.checked(app)
        self.assertIn("1.0.2 is available", app.update_var.get(), "still offered")
        app.update_now()
        self.wait_for(app, "update")
        self.assertEqual(self.installs, [])
        self.assertIn("GitHub lists no SHA-256 for OpenShaker-Setup-1.0.2.exe", app.update_var.get())
        self.assertIn("release page (What's new)", app.update_var.get())
        self.assertTrue(app.update_buttons["news"].instate(["!disabled"]), "the manual way stays one click away")
        self.assertEqual(list(self.dir.glob(updater.TEMP_PREFIX + "*")), [])

    def test_a_source_copy_opens_the_release_page_and_never_runs_the_installer(self):
        patch(self, updater, "is_installed_copy", lambda: False)
        app = self.app()
        self.checked(app)
        app.update_now()
        self.assertEqual((self.downloads, self.installs), ([], []))
        self.assertEqual(self.opened, [f"{REPO_URL}/releases/tag/v1.0.2"])
        self.assertIn("runs from source", app.update_var.get())

    def test_a_failed_check_stays_quiet(self):
        self.check_error = OSError("no network")
        app = self.app()
        self.checked(app)
        self.assertEqual((app.update_version(), app.update_bar.winfo_manager()), ("", ""))
        self.assertIn("no network", app.update_error)
        self.assertEqual(app.tray.icon.notified, [])

    def test_a_failed_silent_update_says_so_in_the_bar_the_tray_and_the_log(self):
        app = self.app(update_result=("failed", "1.0.2"))
        self.assertEqual(app.update_bar.winfo_manager(), "pack")
        self.assertIn("The update to 1.0.2 did not install", app.update_var.get())
        self.assertEqual(str(self.tray_item(app)), "Update to 1.0.2 failed - open OpenShaker")
        self.assertIn("update to 1.0.2 failed; setup started", (self.dir / "logs" / updater.LOG_NAME).read_text(
            encoding="utf-8"))
        self.checked(app)
        self.assertIn("1.0.2 is available", app.update_var.get(), "the next check offers it again")
        self.assertEqual(app.update_status(), "")
        app = self.app(update_result=("failed", "1.0.2"))
        self.answer = None                                # pulled meanwhile: nothing to say any more
        self.checked(app)
        self.assertEqual((app.update_version(), app.update_bar.winfo_manager()), ("", ""))

    def test_an_update_that_stopped_partway_asks_for_the_installer_until_one_is_offered(self):
        app = self.app(update_result=("incomplete", "1.0.2"))
        self.assertIn("stopped partway", app.update_var.get())
        self.assertEqual(str(self.tray_item(app)), "Update to 1.0.2 failed - open OpenShaker")
        self.assertEqual({name: button.instate(["!disabled"]) for name, button in app.update_buttons.items()},
                         {"skip": False, "news": True, "now": False})
        app.open_whats_new()
        self.assertEqual(self.opened, [f"{REPO_URL}/releases/tag/v1.0.2"])
        self.assertIn("update to 1.0.2 stopped partway through its files", (self.dir / "logs" / updater.LOG_NAME)
                      .read_text(encoding="utf-8"))
        self.answer = None                                # this copy may be 1.0.2 already: nothing newer
        self.checked(app)
        self.assertIn("stopped partway", app.update_var.get(), "the note stays")
        self.answer = updater.release_from(api_answer(), current="1.0.1")
        self.checked(app)
        self.assertIn("1.0.2 is available", app.update_var.get(), "Update now installs it again, which repairs it")

    # -- automatic updates (updates.auto) ------------------------------------------------------
    def saved(self):
        return json.loads(self.path.read_text(encoding="utf-8")).get("updates", {})

    def asking(self, app):
        return app.update_ask.winfo_manager() == "pack"

    def auto_app(self, **updates):
        self.path.write_text(json.dumps({"updates": {"auto": True, "auto_asked": True, **updates}}), encoding="utf-8")
        return self.app()

    def quiet_tick(self, app):
        """A look for a quiet moment (_auto_tick), with no game data for longer than AUTO_IDLE_S."""
        app._tele_seen_at = time.monotonic() - gui.AUTO_IDLE_S - 1
        app._cancel_auto()
        app._auto_tick()

    def test_automatic_updates_are_off_by_default_even_in_an_old_config(self):
        for name, saved in (("new", {}), ("from 1.0.1", {"updates": {"skip": "1.0.2"}}),
                            ("hand-edited", {"updates": {"auto": "yes", "auto_asked": 1, "auto_done": 5}})):
            with self.subTest(name):
                self.path.write_text(json.dumps(saved), encoding="utf-8")
                upd = config.load(str(self.path))["updates"]
                self.assertEqual((upd["auto"], upd["auto_asked"], upd["auto_done"], upd["auto_failed"]),
                                 (False, False, "", ""))
        for bad in (5, "latest", "1.0", "v1.0.4", ["1.0.4"]):
            with self.subTest(auto_failed=bad):
                self.path.write_text(json.dumps({"updates": {"auto_failed": bad}}), encoding="utf-8")
                self.assertEqual(config.load(str(self.path))["updates"]["auto_failed"], "", "nothing held back")
        self.path.write_text(json.dumps({"updates": {"auto_failed": "1.0.4"}}), encoding="utf-8")
        self.assertEqual(config.load(str(self.path))["updates"]["auto_failed"], "1.0.4")
        app = self.app()
        self.checked(app)
        self.assertFalse(app.updates_auto())
        self.assertIsNone(app._auto_job, "nothing waits to install by itself")

    def test_the_bar_asks_once_and_yes_turns_automatic_updates_on(self):
        app = self.app()
        self.assertFalse(self.asking(app), "no question before an update is found")
        self.checked(app)
        self.assertTrue(self.asking(app))
        self.assertEqual(app.tray.icon.notified, [], "a line in the bar, never a pop-up")
        app.answer_auto_update(True)
        self.assertEqual((self.saved()["auto"], self.saved()["auto_asked"]), (True, True))
        self.assertFalse(self.asking(app))
        self.assertIsNotNone(app._auto_job, "this update now waits for a quiet moment")
        self.answer = updater.release_from(api_answer("v1.0.3"), current="1.0.1")
        self.checked(app)
        self.assertFalse(self.asking(app), "asked once only")

    def test_no_leaves_them_off_and_the_question_never_returns(self):
        app = self.app()
        self.checked(app)
        app.answer_auto_update(False)
        self.assertEqual(self.saved(), {"auto_asked": True})
        self.assertFalse(self.asking(app))
        self.assertIsNone(app._auto_job)
        app = self.app()                                  # a later start, a later update
        self.checked(app)
        self.assertFalse(self.asking(app))
        self.assertIn("1.0.2 is available", app.update_var.get())

    def test_installing_or_skipping_counts_as_an_answer(self):
        for action in ("update_now", "skip_update"):
            with self.subTest(action):
                self.path.write_text("{}", encoding="utf-8")
                app = self.app()
                self.checked(app)
                self.assertTrue(self.asking(app))
                getattr(app, action)()
                self.wait_for(app, "update")
                self.assertFalse(self.asking(app))
                self.assertIs(self.saved()["auto_asked"], True)
                self.assertFalse(app.updates_auto(), "and automatic updates stay off")

    def test_the_advanced_switch_counts_as_the_answer(self):
        self.assertIn(("Install updates automatically (when no game is running)", ("updates", "auto"), bool),
                      gui.App.ADVANCED_FIELDS)
        app = self.app()
        self.checked(app)
        app._apply_advanced([((app.cfg["updates"], "auto"), True)])
        self.assertFalse(self.asking(app))
        self.assertEqual((self.saved()["auto"], self.saved()["auto_asked"]), (True, True))
        self.assertIsNotNone(app._auto_job)
        app._apply_advanced([((app.cfg["updates"], "auto"), False)])
        self.assertIsNone(app._auto_job, "switched off: nothing waits")

    def test_an_automatic_update_waits_for_no_game_then_installs_in_the_tray(self):
        app = self.auto_app()
        self.checked(app)
        self.assertFalse(self.asking(app))
        self.assertIsNotNone(app._auto_job)
        self.games = {"forzahorizon5.exe"}
        self.quiet_tick(app)
        self.assertEqual(self.downloads, [], "a game is running")
        self.assertIsNotNone(app._auto_job, "it looks again later")
        self.games = set()
        app._tele_seen_at = time.monotonic()              # a game sent data a moment ago
        app._cancel_auto()
        app._auto_tick()
        self.assertEqual(self.downloads, [], "game data lately")
        self.game_running(app)                            # game data right now
        self.quiet_tick(app)
        self.assertEqual(self.downloads, [], "game data now")
        app._last_status = None
        self.quiet_tick(app)
        self.wait_for(app, "update")
        self.assertEqual(self.downloads, ["1.0.2"])
        self.assertEqual(self.installs, [(self.dir / NAME, False)], "back in the tray, never a window")
        self.assertEqual(self.questions, [], "nothing asked")
        self.assertEqual(self.saved()["auto_done"], "1.0.2", "the new version will say so")
        self.assertIn("installing 1.0.2 automatically", (self.dir / "logs" / updater.LOG_NAME).read_text(encoding="utf-8"))
        self.assertEqual(app.tray.icon.notified, [])

    def test_a_game_starting_during_the_download_puts_it_back_to_waiting(self):
        app = self.auto_app()
        self.checked(app)
        self.quiet_tick(app)                              # the download starts
        self.games = {"trackmania.exe"}                   # ... and a game starts before it is installed
        self.wait_for(app, "update")
        self.assertEqual((self.downloads, self.installs), (["1.0.2"], []))
        self.assertFalse(app._update_busy)
        self.assertIn("1.0.2 is available", app.update_var.get())
        self.assertIsNotNone(app._auto_job, "waits for the next quiet moment")
        self.assertNotIn("auto_done", self.saved())

    def test_an_interrupted_automatic_update_keeps_its_download(self):
        (self.dir / NAME).write_bytes(PAYLOAD)            # the checked installer the fake download returns
        app = self.auto_app()
        self.checked(app)
        self.quiet_tick(app)
        self.games = {"trackmania.exe"}                   # a game starts during the download
        self.wait_for(app, "update")
        self.assertEqual(app._auto_kept[:2], ("1.0.2", SHA), "kept, not thrown away")
        self.games = set()
        self.quiet_tick(app)                              # the next quiet moment
        self.wait_for(app, "update")
        self.assertEqual(self.downloads, ["1.0.2"], "no second download")
        self.assertEqual(self.installs, [(self.dir / NAME, False)])
        self.assertEqual(len(self.asked), 3, "GitHub was still asked first each time")
        self.assertIsNone(app._auto_kept)

    def test_a_kept_download_is_not_used_once_github_lists_something_else(self):
        (self.dir / NAME).write_bytes(PAYLOAD)
        for name, change in (("another hash", lambda: with_assets(
                                  lambda a: dict(a, digest="sha256:" + "0" * 64) if a["name"] == NAME else a)),
                             ("another version", lambda: api_answer("v1.0.9"))):
            with self.subTest(name):
                self.downloads.clear()
                app = self.auto_app()
                self.answer = updater.release_from(api_answer(), current="1.0.1")
                self.checked(app)
                self.quiet_tick(app)
                self.games = {"trackmania.exe"}
                self.wait_for(app, "update")
                self.games = set()
                self.answer = updater.release_from(change(), current="1.0.1")
                self.checked(app)
                self.quiet_tick(app)
                self.wait_for(app, "update")
                self.assertEqual(len(self.downloads), 2, "downloaded again")

    def test_switching_automatic_updates_off_drops_a_kept_download(self):
        (self.dir / NAME).write_bytes(PAYLOAD)
        app = self.auto_app()
        self.checked(app)
        self.quiet_tick(app)
        self.games = {"trackmania.exe"}
        self.wait_for(app, "update")
        self.assertIsNotNone(app._auto_kept)
        app._apply_advanced([((app.cfg["updates"], "auto"), False)])
        self.assertIsNone(app._auto_kept)

    def test_an_automatic_update_that_fails_leaves_it_to_the_bar(self):
        for field, text in (("download_error", "the download does not match its SHA-256"),
                            ("install_error", "the downloaded installer changed after it was checked")):
            with self.subTest(field):
                setattr(self, field, text)
                app = self.auto_app()
                self.checked(app)
                self.quiet_tick(app)
                self.wait_for(app, "update")
                self.assertEqual(self.installs, [])
                self.assertIn(f"Automatic update to 1.0.2 failed: {text}", app.update_var.get())
                self.assertIn("Update now tries again", app.update_var.get())
                self.assertNotIn("auto_done", self.saved())
                self.assertIsNone(app._auto_job, "no automatic retry of this version")
                self.checked(app)                         # the daily check offers it again: by hand only
                self.assertIsNone(app._auto_job)
                self.assertIn("automatic update to 1.0.2 failed",
                              (self.dir / "logs" / updater.LOG_NAME).read_text(encoding="utf-8"))
                setattr(self, field, None)
                app.update_now()                          # Update now still works
                self.wait_for(app, "update")
                self.assertEqual(len(self.installs), 1)
                self.installs.clear()

    def test_a_skipped_version_is_never_installed_automatically(self):
        app = self.auto_app(skip="1.0.2")
        self.checked(app)
        self.assertEqual((app.update_version(), app._auto_job), ("", None))
        app.update_release = self.answer                  # even if it were on offer somehow
        self.quiet_tick(app)
        self.assertEqual(self.downloads, [])

    def test_a_source_copy_is_never_asked_and_never_updates_itself(self):
        patch(self, updater, "is_installed_copy", lambda: False)
        app = self.app()
        self.checked(app)
        self.assertFalse(self.asking(app))
        app = self.auto_app()
        self.checked(app)
        self.assertIsNone(app._auto_job)
        self.quiet_tick(app)
        self.assertEqual(self.downloads, [])

    def test_after_an_automatic_update_the_bar_says_so_until_an_update_is_offered(self):
        app = self.auto_app(auto_done=gui.__version__)
        self.assertIn(f"updated itself to {gui.__version__}", app.update_var.get())
        self.assertEqual({name: button.instate(["!disabled"]) for name, button in app.update_buttons.items()},
                         {"skip": False, "news": True, "now": False})
        self.assertEqual(app.update_version(), "", "no tray item for it")
        app.open_whats_new()
        self.assertEqual(self.opened, [f"{REPO_URL}/releases/tag/v{gui.__version__}"])
        self.assertNotIn("auto_done", self.saved(), "said once")
        self.answer = None
        self.checked(app)
        self.assertIn("updated itself", app.update_var.get(), "a check with nothing newer keeps it")
        self.assertEqual(self.app().update_bar.winfo_manager(), "", "the next start says nothing")
        app = self.auto_app(auto_done="1.0.0")            # an older version: it was installed some other way
        self.assertNotIn("updated itself", app.update_var.get())
        self.assertNotIn("auto_done", self.saved())
        self.assertNotIn("auto_failed", self.saved())

    # -- 1.0.3: a failed automatic update is remembered (review S1, S2, N2, N8) -------------------
    def offer(self, version="9.9.9"):
        self.answer = updater.release_from(api_answer(f"v{version}"), current="1.0.1")

    def test_an_automatic_update_setup_brought_back_is_not_tried_again_automatically(self):
        for how in ("failed", "incomplete"):
            with self.subTest(how):
                self.path.write_text(json.dumps({"updates": {"auto": True, "auto_asked": True, "auto_done": "9.9.9"}}),
                                     encoding="utf-8")
                app = self.app(update_result=(how, "9.9.9"))     # ONE start, as setup's relaunch makes it
                self.assertNotIn("updated itself", app.update_var.get())
                if how == "failed":
                    self.assertIn("will not be installed automatically again", app.update_var.get())
                self.assertEqual(self.saved().get("auto_failed"), "9.9.9")
                self.assertNotIn("auto_done", self.saved())
                self.offer()
                self.checked(app)
                self.assertIsNone(app._auto_job, "not armed again")
                self.assertIn("waits for Update now", app.update_var.get())
                self.quiet_tick(app)
                self.assertEqual(self.downloads, [], "and a quiet moment installs nothing")

    def test_a_failed_automatic_update_is_not_retried_after_a_restart(self):
        self.download_error = "the downloaded installer is gone"      # an antivirus took it, say
        app = self.auto_app()
        self.offer()
        self.checked(app)
        self.quiet_tick(app)
        self.wait_for(app, "update")
        self.assertEqual(self.saved().get("auto_failed"), "9.9.9")
        self.download_error = None
        app = self.app()                                  # the next start (Windows, or the user)
        self.checked(app)
        self.assertIsNone(app._auto_job)
        self.quiet_tick(app)
        self.assertEqual(self.downloads, ["9.9.9"], "downloaded once, in the first session only")
        self.offer("9.9.10")                              # a newer version gets a fresh chance
        self.checked(app)
        self.assertIsNotNone(app._auto_job)
        self.assertNotIn("auto_failed", self.saved())

    def test_update_now_still_installs_a_held_back_version(self):
        app = self.auto_app(auto_failed="9.9.9")
        self.offer()
        self.checked(app)
        self.assertIsNone(app._auto_job)
        app.update_now()
        self.wait_for(app, "update")
        self.assertEqual(len(self.installs), 1)
        self.assertEqual(self.saved().get("auto_failed"), "9.9.9",
                         "kept until that version runs, so a manual attempt that fails cannot start a loop")

    def test_a_version_reached_some_other_way_clears_the_failure(self):
        for held in (gui.__version__, "1.0.0"):
            with self.subTest(held):
                self.auto_app(auto_failed=held)
                self.assertNotIn("auto_failed", self.saved())

    def test_a_network_error_during_an_automatic_update_only_postpones_it(self):
        self.download_error = updater.NetworkError("URLError: getaddrinfo failed")   # just after a wake from sleep
        app = self.auto_app()
        self.offer()
        self.checked(app)
        delays, arm = [], app._arm_auto
        app._arm_auto = lambda delay_s=gui.AUTO_TICK_S: (delays.append(delay_s), arm(delay_s))
        self.quiet_tick(app)
        self.wait_for(app, "update")
        self.assertNotIn("auto_failed", self.saved())
        self.assertIn("9.9.9 is available", app.update_var.get())
        self.assertEqual(app.update_status(), "")
        self.assertIsNotNone(app._auto_job)
        self.assertEqual(delays[-1], updater.RETRY_AFTER_S[0], "tried again later, not every 30 s")
        self.assertIn("postponed", (self.dir / "logs" / updater.LOG_NAME).read_text(encoding="utf-8"))

    # -- 1.0.3: consent and the user's presence (review N1, N3, N4, N5, N6) -------------------------
    def test_switching_off_during_the_download_installs_nothing(self):
        for key in ("auto", "check"):
            with self.subTest(key):
                app = self.auto_app()
                self.offer()
                self.checked(app)
                self.quiet_tick(app)                      # the download starts
                app._apply_advanced([((app.cfg["updates"], key), False)])      # ... and the user says no
                self.wait_for(app, "update")
                self.assertEqual(self.installs, [])
                self.assertNotIn("auto_done", self.saved())
                self.assertIsNone(app._auto_job)
                if key == "auto":
                    self.assertIn("9.9.9 is available", app.update_var.get(), "Update now is still there")
                else:
                    self.assertEqual(app.update_bar.winfo_manager(), "", "no check: no bar")

    def test_an_automatic_update_waits_while_openshaker_is_in_use(self):
        app = self.auto_app()
        self.offer()
        self.checked(app)
        for name, busy, idle in (("window open", lambda: setattr(app, "window_visible", lambda: True),
                                  lambda: setattr(app, "window_visible", lambda: False)),
                                 ("test tone", lambda: setattr(app, "_tone_thread", type("T", (), {"is_alive": lambda s: True})()),
                                  lambda: setattr(app, "_tone_thread", None))):
            with self.subTest(name):
                busy()
                self.quiet_tick(app)
                self.assertEqual(self.downloads, [])
                self.assertIsNotNone(app._auto_job, "it looks again later")
                idle()
        self.quiet_tick(app)
        self.wait_for(app, "update")
        self.assertEqual(len(self.installs), 1, "once nobody is at OpenShaker")

    def test_no_to_the_update_now_question_keeps_the_automatic_update_waiting(self):
        app = self.auto_app()
        self.offer()
        self.checked(app)
        self.game_running(app)
        self.during_question = app._auto_tick             # the 30 s tick fires while the question is open
        self.yes = False
        app.update_now()
        self.assertIsNotNone(app._auto_job, "still waiting for a quiet moment")

    def test_no_automatic_updates_after_no_start_or_without_a_tray_icon(self):
        for name, setup in (("--no-start", lambda a: setattr(a, "_no_start", True)),
                            ("no tray", lambda a: setattr(a.tray, "active", False))):
            with self.subTest(name):
                app = self.auto_app()
                setup(app)                                # setup's relaunch would drop that flag
                self.offer()
                self.checked(app)
                self.assertIsNone(app._auto_job)
                self.quiet_tick(app)
                self.assertEqual(self.downloads, [])

    def test_the_start_after_an_automatic_update_shows_no_toast(self):
        plain = self.app()
        plain._notify_device_missing()                    # what a launch with the shaker off does
        self.assertEqual(len(plain.tray.icon.notified), 1)
        for done, kw in ((gui.__version__, {}), ("9.9.9", {"update_result": ("failed", "9.9.9")})):
            with self.subTest(done):
                self.path.write_text(json.dumps({"updates": {"auto": True, "auto_asked": True, "auto_done": done}}),
                                     encoding="utf-8")
                app = self.app(**kw)
                app._notify_device_missing()
                self.assertEqual(app.tray.icon.notified, [], "nobody started it: no toast")

    def test_test_mode_is_visible(self):
        env(self, OPENSHAKER_UPDATE_TEST="1")
        app = self.app()
        self.checked(app)
        self.assertIn("[update test mode]", app.update_var.get())


class InstallerFlagTests(unittest.TestCase):
    def test_setups_flags_are_read_strictly(self):
        read = gui.installer_result
        self.assertEqual(read(["--hidden", "--update-failed=1.0.2"]), ("failed", "1.0.2"))
        self.assertEqual(read(["--update-incomplete=v1.0.2"]), ("incomplete", "1.0.2"))
        self.assertEqual(read(["--update-failed"]), ("failed", ""))
        self.assertEqual(read(["--update-failed=1.0.2/../x"]), ("failed", ""), "no version: dropped")
        self.assertIsNone(read(["--hidden", "--update-failedX"]))
        self.assertIsNone(read([]))


if __name__ == "__main__":
    unittest.main()
