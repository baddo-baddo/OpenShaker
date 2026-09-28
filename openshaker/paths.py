"""Where OpenShaker finds its bundled files and where it keeps the user's own.

Bundled, read-only: the profiles and the icon - inside the PyInstaller bundle (`sys._MEIPASS`) for the
installed app, the project folder when run from source.
User data: config.json and logs, always in %APPDATA%\\OpenShaker (OPENSHAKER_HOME overrides it), so an
install under Program Files or %LOCALAPPDATA%\\Programs never needs to write next to the exe.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

APP_FOLDER = "OpenShaker"


def is_frozen() -> bool:
    """True inside the PyInstaller build (OpenShaker.exe)."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


RESOURCE_DIR = resource_dir()
ICON = RESOURCE_DIR / "openshaker" / "openshaker.ico"     # window, tray, a source copy's Start menu entry


def user_dir(create: bool = True) -> Path:
    override = os.environ.get("OPENSHAKER_HOME")
    if override:
        folder = Path(override)
    elif os.environ.get("APPDATA"):
        folder = Path(os.environ["APPDATA"]) / APP_FOLDER
    else:
        folder = Path.home() / f".{APP_FOLDER.lower()}"
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def config_path() -> Path:
    return user_dir() / "config.json"


def log_dir() -> Path:
    folder = user_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def legacy_configs() -> list[Path]:
    """Where earlier versions kept config.json: next to the code when run from source, and next to
    whatever script an old "Start with Windows" entry launches."""
    found: list[Path] = []
    if not is_frozen():
        found.append(RESOURCE_DIR / "config.json")
    try:
        from . import autostart
        for name in autostart.LEGACY_VALUE_NAMES:
            cmd = autostart.value(name) or ""
            for part in re.findall(r'"([^"]+)"', cmd):
                target = Path(part)
                if target.suffix.lower() in (".pyw", ".py"):
                    found.append(target.parent / "config.json")
    except Exception:
        pass
    return list(dict.fromkeys(found))


def migrate_config(target: Path | None = None, candidates: list[Path] | None = None) -> Path | None:
    """Copy the first existing old config.json into the settings folder, once.

    Does nothing when the settings folder already has a config. The old file is left where it is.
    Returns the file that was copied, or None.
    """
    target = Path(target) if target is not None else config_path()
    if target.exists():
        return None
    for old in (candidates if candidates is not None else legacy_configs()):
        try:
            if Path(old).is_file() and Path(old).resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, target)
                return Path(old)
        except OSError:
            continue
    return None
