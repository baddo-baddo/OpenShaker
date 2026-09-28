"""The tray app's plumbing: the Windows startup entry, the single-instance lock, the menu."""
import shutil
import socket
import sys
import threading
import tkinter as tk
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openshaker import autostart, single_instance, tray   # noqa: E402
from fakes import close_window, fake_registry, no_optional_outputs, tk_root                            # noqa: E402


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.reg = fake_registry(self)                     # never the real registry

    def test_command_launches_the_tray_without_a_console(self):
        cmd = autostart.command()
        self.assertIn("app.pyw", cmd)
        self.assertIn("--hidden", cmd)       # no window at boot
        self.assertNotIn("--no-start", cmd)  # haptics come up by themselves
        self.assertTrue(cmd.startswith('"'), cmd)               # the path is quoted
        self.assertNotIn("run.bat", cmd)                        # run.bat is what opens a console
        self.assertTrue(autostart.pythonw().name.lower().startswith("python"), autostart.pythonw())

    def test_enable_disable_round_trip(self):
        self.assertFalse(autostart.is_enabled())
        self.assertEqual(autostart.enable(), autostart.command())
        self.assertTrue(autostart.is_enabled())
        self.assertTrue(autostart.is_current())
        autostart.disable()
        self.assertFalse(autostart.is_enabled())
        autostart.disable()                                     # idempotent

    def test_stale_entry_is_detected(self):
        with autostart._open(write=True) as key:
            self.reg.SetValueEx(key, autostart.VALUE_NAME, 0, self.reg.REG_SZ, r'"C:\old\python.exe" old.pyw')
        self.assertTrue(autostart.is_enabled())
        self.assertFalse(autostart.is_current())                # the GUI refreshes it on launch


class LauncherStubTests(unittest.TestCase):
    """A venv's pythonw.exe is a stub that re-runs the CONSOLE python, so it still opens a window."""

    def setUp(self):
        import tempfile
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.venv = self.dir / "Scripts" / "pythonw.exe"
        self.venv.parent.mkdir(parents=True)
        self.base = self.dir / "base" / "pythonw.exe"
        self.base.parent.mkdir(parents=True)
        self._real = (autostart.venv_pythonw, autostart.base_pythonw)
        autostart.venv_pythonw = lambda: self.venv
        autostart.base_pythonw = lambda: self.base
        self.addCleanup(self._restore_paths)

    def _restore_paths(self):
        autostart.venv_pythonw, autostart.base_pythonw = self._real

    def write(self, stub_bytes: int, base_bytes: int):
        self.venv.write_bytes(b"S" * stub_bytes)
        self.base.write_bytes(b"B" * base_bytes)

    def test_stub_is_detected_and_replaced(self):
        self.write(247056, 102160)                      # the real sizes seen on this machine
        self.assertTrue(autostart.launcher_is_stub())
        self.assertIn("replaced", autostart.repair_launcher())
        self.assertFalse(autostart.launcher_is_stub())
        self.assertEqual(self.venv.read_bytes(), self.base.read_bytes())

    def test_a_real_interpreter_is_left_alone(self):
        self.write(102160, 102160)
        self.assertFalse(autostart.launcher_is_stub())
        self.assertIsNone(autostart.repair_launcher())

    def test_missing_base_interpreter_is_not_a_crash(self):
        self.venv.write_bytes(b"S" * 247056)
        self.assertFalse(autostart.launcher_is_stub())
        self.assertIsNone(autostart.repair_launcher())


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        self._real_port = single_instance.PORT
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:   # a free port the OS picks,
            probe.bind(("127.0.0.1", 0))                                    # never the live app's
            single_instance.PORT = probe.getsockname()[1]
        self.addCleanup(setattr, single_instance, "PORT", self._real_port)

    def test_second_acquire_is_refused_and_can_signal_the_first(self):
        first = single_instance.acquire()
        self.assertIsNotNone(first)
        self.addCleanup(first.close)
        shown = threading.Event()
        first.on_show = shown.set

        self.assertIsNone(single_instance.acquire())             # a second launch gets nothing
        self.assertTrue(single_instance.signal_existing())
        self.assertTrue(shown.wait(3.0), "the running instance was never asked to show itself")

    def test_port_is_free_again_after_close(self):
        first = single_instance.acquire()
        first.close()
        time.sleep(0.1)
        second = single_instance.acquire()
        self.assertIsNotNone(second, "Quit must release the lock for the next launch")
        second.close()

    def test_signal_without_an_instance_fails_quietly(self):
        self.assertFalse(single_instance.signal_existing(timeout=0.5))


class FakeApp:
    """Just enough App for the menu to build."""

    def __init__(self):
        self.running = False
        self.manual = False
        self.haptics_on = True
        self.update = ""                          # the version an update is available to, if any
        self.calls = []
        self.lines = {"state": "Haptics: stopped", "game": "Game: none detected",
                      "profile": "Profile: forza_motorsport", "output": "Output: silent", "error": ""}

    def update_version(self):
        return self.update

    def update_status(self):
        return ""

    def run_on_ui(self, fn):
        self.calls.append(fn.__name__)

    def tray_line(self, key):
        return self.lines.get(key, "")

    def is_running(self):
        return self.running

    def windows_startup_enabled(self):
        return True

    def show_window(self): pass
    def toggle_haptics(self): pass
    def restart_haptics(self): pass
    def test_tone(self): pass
    def toggle_windows_startup(self): pass
    def open_folder(self): pass
    def open_feedback(self): pass
    def update_from_tray(self): pass
    def open_whats_new(self): pass
    def quit_app(self): pass


class FakeIcon:
    """Stands in for pystray.Icon. The menu is plain Python; only a real icon needs a Win32 window, and
    building one per test in a single process made these tests fail now and then."""

    def __init__(self, name, icon=None, title=None, menu=None):
        self.name, self.icon, self.title, self.menu = name, icon, title, menu
        self.menu_builds = 0
        self.notified = []

    def update_menu(self):
        self.menu_builds += 1
    def notify(self, message, title=None): self.notified.append(message)
    def run(self): pass
    def stop(self): pass


@unittest.skipUnless(tray.AVAILABLE, f"pystray/Pillow not installed ({tray.IMPORT_ERROR})")
class TrayMenuTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        real_icon, tray.pystray.Icon = tray.pystray.Icon, FakeIcon
        self.addCleanup(setattr, tray.pystray, "Icon", real_icon)
        self.tray = tray.Tray(self.app, Path(__file__).resolve().parent.parent / "openshaker" / "openshaker.ico")
        self.assertTrue(self.tray.active, f"the tray icon could not be built: {getattr(self.tray, 'error', '')}")

    def items(self):
        return [i for i in self.tray.icon.menu if str(i).strip("- ")]

    def texts(self):
        return [str(i) for i in self.items()]

    def test_left_click_opens_the_window(self):
        first = self.items()[0]
        self.assertTrue(first.default, "a single left click must open the window")
        first(self.tray.icon)
        self.assertEqual(self.app.calls, ["show_window"])

    def test_status_lines_are_shown_and_not_clickable(self):
        texts = self.texts()
        for line in ("Haptics: stopped", "Game: none detected", "Profile: forza_motorsport"):
            self.assertIn(line, texts)
        for item in self.items():
            if str(item).startswith(("Haptics:", "Game:", "Profile:", "Output:")):
                self.assertFalse(item.enabled)

    def test_one_switch_turns_the_haptics_off_and_on(self):
        """The maintainer asked for a way to switch the haptics off (2026-09-18): one ticked item, next to
        Restart - no separate Start and Stop items to mix up while driving."""
        texts = self.texts()
        self.assertIn("Restart haptics", texts)
        self.assertNotIn("Stop haptics", texts)
        self.assertNotIn("Start haptics", texts)
        switch = next(i for i in self.items() if str(i) == "Haptics on")
        self.assertTrue(switch.checked)
        self.app.haptics_on = False
        self.assertFalse(switch.checked)
        switch(self.tray.icon)
        self.assertEqual(self.app.calls, ["toggle_haptics"], "handed to the Tk thread, never run on pystray's")
        self.assertLess(texts.index("Haptics on"), texts.index("Restart haptics"))

    def test_an_update_puts_two_items_first_and_a_badge_on_the_icon_but_never_a_notification(self):
        self.assertFalse([t for t in self.texts() if t.startswith("Update to") or t == "What's new"])
        plain = self.tray._running_img
        self.tray.refresh("OpenShaker - running", True, ("Haptics: running",))
        self.assertIs(self.tray.icon.icon, plain)
        self.app.update = "1.0.2"
        self.tray.refresh("OpenShaker - running", True, ("Haptics: running",))
        texts = self.texts()
        self.assertEqual(texts[:3], ["Update to 1.0.2", "What's new", "Open OpenShaker"], "the update comes first")
        self.assertTrue(next(i for i in self.items() if str(i) == "Open OpenShaker").default,
                        "a left click still opens the window")
        badged = self.tray.icon.icon
        self.assertIsNot(badged, plain)
        self.assertNotEqual(badged.tobytes(), plain.tobytes(), "the badge changes the picture")
        self.assertEqual(badged.size, plain.size)
        self.tray.refresh("OpenShaker - NOT running", False, ("Haptics: stopped",))
        self.assertNotEqual(self.tray.icon.icon.tobytes(), self.tray._stopped_img.tobytes(), "grey icons get it too")
        self.items()[0](self.tray.icon)
        self.items()[1](self.tray.icon)
        self.assertEqual(self.app.calls, ["update_from_tray", "open_whats_new"], "both on the Tk thread")
        self.assertEqual(self.tray.icon.notified, [], "no pop-up for an update, ever")
        self.app.update = ""
        self.tray.refresh("OpenShaker - running", True, ("Haptics: running",))
        self.assertIs(self.tray.icon.icon, plain, "the badge goes with the update")

    def test_the_menu_can_be_rebuilt_on_demand(self):
        builds = self.tray.icon.menu_builds
        self.tray.update_menu()
        self.assertEqual(self.tray.icon.menu_builds, builds + 1)
        self.tray.icon.update_menu = lambda: 1 / 0          # a failing rebuild is not the window's problem
        self.tray.update_menu()

    def test_error_line_is_hidden_until_there_is_one(self):
        shown = lambda: [str(i) for i in self.items() if i.visible]      # noqa: E731
        self.assertFalse([t for t in shown() if t.startswith("Problem:")])
        self.app.lines["error"] = "Problem: cannot bind UDP 5555"
        self.assertIn("Problem: cannot bind UDP 5555", shown())

    def test_quit_is_offered(self):
        self.assertIn("Quit", self.texts())
        self.assertIn("Start with Windows", self.texts())

    def test_feedback_is_one_click_away(self):
        item = next(i for i in self.items() if str(i) == "Send feedback / report a bug")
        item(self.tray.icon)
        self.assertEqual(self.app.calls, ["open_feedback"], "handed to the Tk thread")


class AlwaysOnTests(unittest.TestCase):
    """With no Start button, a failed start must not leave the app sitting there dead."""

    def setUp(self):
        import tempfile
        from openshaker import config, gui
        self.gui = gui
        fake_registry(self)                                     # never touch the real registry
        no_optional_outputs(self)                               # the public build's window
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "config.json"
        self.root = tk_root()                              # never keeps the foreground
        self.addCleanup(close_window, self.root)
        self.attempts = []

        class Boom:                       # a Runtime whose audio device is not there
            running = False

            def __init__(_s, *a, **k):
                self.attempts.append(1)

            def start(_s):
                raise OSError("no such output device")

            def stop(_s):
                pass

        self._real_runtime, gui.Runtime = gui.Runtime, Boom
        self.addCleanup(setattr, gui, "Runtime", self._real_runtime)
        self.app = gui.App(self.root, config.load(self.path), str(self.path), use_tray=False)

    def test_failed_start_is_reported_and_retried(self):
        self.app.start()
        self.assertEqual(len(self.attempts), 1)
        self.assertIn("no such output device", self.app.start_error)
        self.assertGreater(self.app._retry_at, 0.0)

        self.app.poll()                                  # too early: still waiting
        self.assertEqual(len(self.attempts), 1)

        self.app._retry_at = 0.0
        self.app.poll()                                  # the retry window opened
        self.assertEqual(len(self.attempts), 2)
        self.assertIn("retrying", self.app.status_var.get())

    def test_feedback_opens_the_issue_forms_and_sends_nothing(self):
        """The default browser, on the project's issue forms - a fake opener here, never a real browser."""
        from openshaker import FEEDBACK_URL, REPO_URL
        opened = []
        self.addCleanup(setattr, self.gui.webbrowser, "open", self.gui.webbrowser.open)
        self.gui.webbrowser.open = lambda url, *a, **k: opened.append((url, a, k)) or True
        self.app.open_feedback()
        self.assertEqual(opened, [(FEEDBACK_URL, (), {})], "just the address: no log, no system data")
        self.assertEqual(FEEDBACK_URL, "https://github.com/baddo-baddo/OpenShaker/issues/new/choose")
        self.assertTrue(FEEDBACK_URL.startswith(REPO_URL))

    def test_without_a_browser_the_address_is_shown(self):
        from openshaker import FEEDBACK_URL
        self.addCleanup(setattr, self.gui.webbrowser, "open", self.gui.webbrowser.open)
        self.gui.webbrowser.open = lambda url, *a, **k: False
        self.app.open_feedback()
        self.assertIn(FEEDBACK_URL, self.app.msg_var.get())

    def test_tray_lines_say_it_is_not_running(self):
        self.app.start()
        self.app._tray_tick = 6
        self.app._refresh()
        self.assertIn("Not running", self.app.status_var.get())


if __name__ == "__main__":
    unittest.main()
