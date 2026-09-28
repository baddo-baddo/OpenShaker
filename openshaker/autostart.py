"""Start with Windows: one HKCU Run entry that starts OpenShaker in the notification area.

Deliberately the registry rather than a shortcut in the Startup folder: no .lnk to keep in sync, it is
easy to inspect (`python -m openshaker.autostart status`), and the uninstaller removes it by name.
The installed app registers OpenShaker.exe; a copy run from source registers pythonw.exe + app.pyw.

Also the Start menu entry of a copy run from source (the installer makes the installed copy's), so
typing "OpenShaker" in Start finds it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import APP_NAME, paths

try:
    import winreg
except ImportError:                                  # not Windows; the app is Windows-only
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = APP_NAME
LEGACY_VALUE_NAMES = ("ButtKicker Haptics",)         # names earlier versions registered under
LAUNCHER = paths.RESOURCE_DIR / "openshaker" / "app.pyw"


def pythonw() -> Path:
    """The window-less interpreter beside the running one, so booting shows no console."""
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            return pyw
    return exe


def command() -> str:
    """What gets written to the Run key: tray only, no window. Haptics start by themselves."""
    if paths.is_frozen():
        return f'"{Path(sys.executable).resolve()}" --hidden'
    return f'"{pythonw()}" "{LAUNCHER}" --hidden'


def venv_pythonw() -> Path:
    """Where the window-less interpreter of the active environment lives."""
    return Path(sys.prefix) / "Scripts" / "pythonw.exe"


def base_pythonw() -> Path:
    """The real GUI interpreter of the Python this environment was built from."""
    return Path(getattr(sys, "base_prefix", sys.prefix)) / "pythonw.exe"


def launcher_is_stub() -> bool:
    """True when the venv's pythonw.exe is venv's launcher stub rather than a real interpreter.

    The stub is a GUI binary, so it looks right, but all it does is re-run whatever `pyvenv.cfg`
    records as `executable` - and `python -m venv` records the CONSOLE python.exe there. Launching
    it therefore still pops a terminal window, which is the whole thing the tray app avoids.
    Sizes differ by well over 100 kB, so comparing them is enough to tell them apart.
    Never applies to the installed app, which is not a venv.
    """
    if paths.is_frozen():
        return False
    venv, base = venv_pythonw(), base_pythonw()
    if not venv.exists() or not base.exists() or venv.samefile(base):
        return False
    return venv.stat().st_size != base.stat().st_size


def repair_launcher() -> str | None:
    """Replace the stub with a copy of the base pythonw.exe (what `venv --copies` would give).

    `pyvenv.cfg` sits one directory above `Scripts`, so the copied interpreter still resolves the
    environment. Returns a message when something was done, None when there was nothing to do.
    """
    if not launcher_is_stub():
        return None
    venv, base = venv_pythonw(), base_pythonw()
    try:
        shutil.copyfile(base, venv)
    except OSError as exc:                      # locked because the app is running: already fine
        return f"could not replace {venv}: {exc}"
    return f"replaced the venv launcher stub at {venv} (it opened a console window)"


def _open(write: bool = False):
    if winreg is None:
        raise OSError("the Windows registry is not available on this platform")
    access = winreg.KEY_READ | (winreg.KEY_WRITE if write else 0)
    if write:
        return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def value(name: str) -> str | None:
    """The command registered under `name`, or None."""
    if winreg is None:
        return None
    try:
        with _open() as key:
            data, _kind = winreg.QueryValueEx(key, name)
            return str(data)
    except OSError:
        return None


def current() -> str | None:
    """The command currently registered for this app, or None."""
    return value(VALUE_NAME)


def is_enabled() -> bool:
    return current() is not None


def is_current() -> bool:
    """True when the registered command still matches this copy of the app."""
    return current() == command()


def enable() -> str:
    cmd = command()
    with _open(write=True) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, cmd)
    return cmd


def disable(name: str | None = None) -> None:
    try:
        with _open(write=True) as key:
            winreg.DeleteValue(key, name or VALUE_NAME)
    except FileNotFoundError:
        pass


def migrate_legacy() -> bool:
    """Replace an entry left under an older app name with this app's own, so Windows never starts two
    copies. True when an old entry was found."""
    found = [name for name in LEGACY_VALUE_NAMES if value(name) is not None]
    for name in found:
        disable(name)
    if found and not is_enabled():
        enable()
    return bool(found)


# -- Start menu -----------------------------------------------------------------------------------------
SHORTCUT_NAME = f"{APP_NAME}.lnk"             # the same name the installer gives the installed copy's entry
_MAKE_SHORTCUT = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:OS_LNK); "
                  "$s.TargetPath = $env:OS_TARGET; $s.Arguments = $env:OS_ARGS; "
                  "$s.WorkingDirectory = $env:OS_DIR; $s.IconLocation = $env:OS_ICON; "
                  "$s.Description = $env:OS_DESC; $s.Save()")


def programs_folder() -> Path:
    """The user's Start menu Programs folder, where a per-user install puts its entry too."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 2, None, 0, buf) == 0 and buf.value:   # CSIDL_PROGRAMS
            return Path(buf.value)
    except (AttributeError, OSError):
        pass
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def make_shortcut(lnk: Path, target: Path, arguments: str = "", workdir: Path | None = None,
                  icon: Path | None = None, description: str = "") -> None:
    """Write a Windows shortcut through the shell's own COM object, with no console window."""
    lnk.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OS_LNK=str(lnk), OS_TARGET=str(target), OS_ARGS=arguments,
               OS_DIR=str(workdir or target.parent), OS_ICON=f"{icon},0" if icon else "", OS_DESC=description)
    shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                    _MAKE_SHORTCUT], env=env, capture_output=True, timeout=60, check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not lnk.exists():
        raise OSError(f"the shortcut was not written: {lnk}")


def ensure_start_menu_entry(folder: Path | None = None) -> Path | None:
    """From source: add the Start menu entry the installer gives an installed copy. Returns what it
    wrote, or None. An entry that is already there - an installed OpenShaker's, or one made on an
    earlier start - is left alone, so a source copy never takes over an installed one's entry.
    """
    if paths.is_frozen():
        return None                              # the installer owns the installed copy's entry
    lnk = Path(folder or programs_folder()) / SHORTCUT_NAME
    if lnk.exists():
        return None
    make_shortcut(lnk, pythonw(), f'"{LAUNCHER}"', workdir=LAUNCHER.parent.parent,
                  icon=paths.RESOURCE_DIR / "openshaker.ico",
                  description=f"{APP_NAME} - game haptics for bass shakers (run from source)")
    return lnk


def main(argv=None) -> int:
    """python -m openshaker.autostart [on|off|status|repair|startmenu]"""
    args = list(sys.argv[1:] if argv is None else argv)
    action = (args[0].lower() if args else "status")
    if action in ("on", "enable", "1", "true"):
        print(f"{APP_NAME} will start with Windows:\n  {enable()}")
    elif action in ("off", "disable", "0", "false"):
        disable()
        print(f"{APP_NAME} will no longer start with Windows.")
    elif action in ("repair", "fix"):
        print(repair_launcher() or "launcher is fine (no console window on launch)")
    elif action in ("startmenu", "start-menu"):
        made = ensure_start_menu_entry()
        print(f"Start menu entry added: {made}" if made else
              f"Start menu entry already there: {programs_folder() / SHORTCUT_NAME}")
    elif action in ("status", ""):
        if launcher_is_stub():
            print("WARNING: the venv's pythonw.exe is a launcher stub - launching it opens a\n"
                  "         console window. Fix it with: python -m openshaker.autostart repair")
        cmd = current()
        if cmd is None:
            print("Start with Windows: off")
        else:
            print(f"Start with Windows: on\n  {cmd}")
            if cmd != command():
                print(f"  (points somewhere else; 'autostart on' would set it to)\n  {command()}")
        for name in LEGACY_VALUE_NAMES:
            if value(name) is not None:
                print(f"  an old entry '{name}' is still registered; the app replaces it on its next start")
    else:
        print(f"usage: autostart [on|off|status|repair|startmenu]   (got {action!r})")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
