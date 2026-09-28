"""Stand-ins for the parts of Windows the tests must never touch for real (standing rule: no real
registry, processes or user files in tests), and Tk windows that never keep the foreground."""
from __future__ import annotations

import os
import unittest


def _foreground_is_ours() -> bool:
    try:
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        return pid.value == os.getpid()
    except (AttributeError, OSError):
        return False


def _foreground():
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except (AttributeError, OSError):
        return None


def give_back_foreground(previous) -> None:
    """Windows may hand a test process's first Tk window the foreground (when whatever launched the
    tests had it). Return it at once to the window that had it."""
    if previous and _foreground_is_ours():
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(previous)
        except (AttributeError, OSError):
            pass


def close_window(root) -> None:
    """Cancel a test window's timers (so no stray poll() fires in a later test), then destroy it once.

    The timers are cancelled in Tcl, not with root.after_cancel(): that also deletes each callback's
    command, and a timer a child widget set (the wheel row's poll) is still registered on that child,
    whose destroy then fails half-way - leaving this root alive as tkinter's default root, which
    captures every master-less Variable of the next test's window."""
    import tkinter as tk
    try:
        for job in root.tk.splitlist(root.tk.call("after", "info")):
            root.tk.call("after", "cancel", job)
        root.destroy()
    except tk.TclError:
        pass


def no_optional_outputs(test: unittest.TestCase) -> None:
    """The window as the public build has it: no optional output package loaded (outputs.py), whether
    or not one exists in this working copy. tests/test_outputs.py covers outputs with fakes."""
    from openshaker import gui
    test.addCleanup(setattr, gui, "load_optional_outputs", gui.load_optional_outputs)
    gui.load_optional_outputs = lambda: ([], [])


def tk_root(offscreen: bool = False):
    """A Tk root for tests: withdrawn, or (offscreen=True) mapped where nobody sees it, invisible and
    disabled - click positions need real widget sizes. Either way the foreground goes straight back."""
    import tkinter as tk
    from openshaker import gui
    previous = _foreground()
    gui.ensure_tcl()
    root = tk.Tk()
    if offscreen:
        root.overrideredirect(True)                      # no taskbar button, no title bar
        root.geometry("+-6000+-6000")
        root.attributes("-alpha", 0.0)
        root.attributes("-disabled", True)
    else:
        root.withdraw()
    root.update()
    give_back_foreground(previous)
    return root


class FakeWinreg:
    """The slice of `winreg` that openshaker.autostart uses, kept in a dict."""

    HKEY_CURRENT_USER = "HKEY_CURRENT_USER"
    KEY_READ = 0x20019
    KEY_WRITE = 0x20006
    REG_SZ = 1

    class Key:
        def __init__(self, values: dict) -> None:
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> bool:
            return False

        def Close(self) -> None:
            pass

    def __init__(self) -> None:
        self.keys: dict[tuple, dict] = {}

    @staticmethod
    def _missing():
        return FileNotFoundError(2, "The system cannot find the file specified")

    def CreateKeyEx(self, root, sub_key, reserved=0, access=0):
        return self.Key(self.keys.setdefault((root, sub_key.lower()), {}))

    def OpenKey(self, root, sub_key, reserved=0, access=0):
        values = self.keys.get((root, sub_key.lower()))
        if values is None:
            raise self._missing()
        return self.Key(values)

    def QueryValueEx(self, key, name):
        for stored, data in key.values.items():
            if stored.lower() == name.lower():         # value names are case-insensitive, like Windows'
                return data, self.REG_SZ
        raise self._missing()

    def SetValueEx(self, key, name, reserved, kind, data) -> None:
        for stored in [s for s in key.values if s.lower() == name.lower()]:
            del key.values[stored]
        key.values[name] = data

    def DeleteValue(self, key, name) -> None:
        stored = next((s for s in key.values if s.lower() == name.lower()), None)
        if stored is None:
            raise self._missing()
        del key.values[stored]

    def values(self, root=HKEY_CURRENT_USER, sub_key=None) -> dict:
        """What a test wrote, for assertions."""
        from openshaker import autostart
        return dict(self.keys.get((root, (sub_key or autostart.RUN_KEY).lower()), {}))


def fake_registry(test: unittest.TestCase) -> FakeWinreg:
    """Give openshaker.autostart an empty in-memory registry for the length of `test`."""
    from openshaker import autostart
    reg = FakeWinreg()
    test.addCleanup(setattr, autostart, "winreg", autostart.winreg)
    autostart.winreg = reg
    return reg
