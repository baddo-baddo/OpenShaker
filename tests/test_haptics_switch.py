"""The Haptics on switch, in the window and the tray menu: off stops everything and stays off across
launches, on (or Restart haptics) brings the haptics back, and --no-start is for one launch only."""
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import close_window, fake_registry, no_optional_outputs, tk_root    # noqa: E402
from openshaker import audio, config, gui, runtime, tray                      # noqa: E402
from openshaker.audio import DeviceNotFound                                   # noqa: E402
from openshaker.sources.base import Source                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class PortSource(Source):
    """A real source thread that 'holds' a game port in a table instead of a socket."""

    held: dict = {}

    def __init__(self, name, port):
        super().__init__()
        self.name, self.port = name, port

    def run(self):
        PortSource.held[self.port] = self
        try:
            while not self.stopping():
                self._stop.wait(0.02)
        finally:
            PortSource.held.pop(self.port, None)


class BusyShaker:
    """An AudioOutput whose device is listed but cannot be opened (another program holds it exclusively)."""

    stops = 0

    def __init__(self, **_kw):
        self.render = self.on_block = None
        self.alive, self.device_name = False, "Fake ButtKicker"

    def resolve(self):
        return 48000

    def start(self):
        raise RuntimeError("Error opening OutputStream: Device unavailable [PaErrorCode -9985]")

    def stop(self):
        BusyShaker.stops += 1


def busy_shaker(test):
    """The real Runtime, with the game sources and the shaker faked: no socket, no audio device."""
    PortSource.held, BusyShaker.stops = {}, 0
    test.addCleanup(setattr, runtime, "AudioOutput", runtime.AudioOutput)
    test.addCleanup(setattr, runtime, "build_sources", runtime.build_sources)
    test.addCleanup(setattr, audio, "refresh_devices", audio.refresh_devices)
    PortSource.built = []

    def build_sources(cfg, which="auto"):
        PortSource.built = [PortSource("forza", 5555), PortSource("beamng", 4444)]
        return list(PortSource.built)
    runtime.AudioOutput = BusyShaker
    runtime.build_sources = build_sources
    audio.refresh_devices = lambda: None


class FailedStartTests(unittest.TestCase):
    """A start that fails after the game sources are up must not leave them holding the ports: Haptics
    off promises the ports are free, and on again must be able to bind them."""

    def setUp(self):
        busy_shaker(self)

    def test_a_shaker_that_cannot_open_fails_before_any_source_starts(self):
        """The output opens first, so a busy shaker costs nothing to undo: stopping a started source waits
        out its socket timeout (up to a second, on the Tk thread, at every retry)."""
        rt = runtime.Runtime(config.load(None))
        with self.assertRaises(RuntimeError):
            rt.start()
        self.assertEqual(len(PortSource.built), 2)
        self.assertTrue(all(s._thread is None for s in PortSource.built), "no source thread was started")
        self.assertEqual(PortSource.held, {})
        self.assertEqual(rt.sources, [])
        self.assertFalse(rt.running)
        self.assertEqual(BusyShaker.stops, 1, "the half-opened output was closed too")

    def test_a_start_that_fails_after_the_sources_are_up_lets_them_go(self):
        self.addCleanup(setattr, BusyShaker, "start", BusyShaker.start)
        BusyShaker.start = lambda _s: None                    # the shaker opens this time
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        self.addCleanup(setattr, runtime.Runtime, "_write_log_meta", runtime.Runtime._write_log_meta)

        def disk_full(*_a, **_k):
            raise OSError(28, "No space left on device")
        runtime.Runtime._write_log_meta = disk_full         # the last step of a --log start
        rt = runtime.Runtime(config.load(None), log_dir=str(folder / "drive"))
        with self.assertRaises(OSError):
            rt.start()
        self.assertTrue(all(s._thread is not None for s in PortSource.built), "the sources had started")
        self.assertEqual(PortSource.held, {}, "and were stopped again")
        self.assertFalse(any(s._thread.is_alive() for s in PortSource.built))
        self.assertEqual((rt.sources, rt.running), ([], False))

    def test_failed_launch_retries_and_switching_off_leave_no_port_held(self):
        fake_registry(self)
        no_optional_outputs(self)
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        root = tk_root()
        self.addCleanup(close_window, root)
        app = gui.App(root, config.load(folder / "config.json"), str(folder / "config.json"),
                      start_haptics=True, use_tray=False, ask_startup=False)
        app._start_at_launch()
        self.assertIn("Device unavailable", app.start_error)
        for _ in range(3):
            app._retry_at = 0.0
            app.poll()                                        # the retry, failing the same way
        self.assertEqual(PortSource.held, {})
        app.set_haptics(False)
        self.assertEqual(PortSource.held, {}, "what 'the game ports are free' promises")
        self.assertEqual([t for t in threading.enumerate() if t.name in ("forza", "beamng")], [],
                         "no source thread left running")


class FakeRuntime:
    """A runtime that opens no audio and no ports; `fail` makes start() raise like a missing shaker."""

    made: list = []
    fail = False

    def __init__(self, cfg, demo=False, outputs=()):
        self.demo, self.running, self.stopped, self.profile_changed = demo, False, False, False
        FakeRuntime.made.append(self)

    def start(self):
        if FakeRuntime.fail:
            raise DeviceNotFound("output device 'ButtKicker' is not connected")
        self.running = True

    def stop(self):
        self.running, self.stopped = False, True

    def status(self):
        return {"device": "Fake shaker", "sr": 48000, "latency_ms": 10.0, "xruns": 0, "profile": None,
                "game": None, "preset": None, "audio_error": None, "sources": [], "tele": None,
                "peak_db": -120.0, "levels": {}}

    def audio_lost(self):
        return False

    def set_master(self, *_a):
        pass


class SwitchTests(unittest.TestCase):
    def setUp(self):
        fake_registry(self)                                   # never the real registry
        no_optional_outputs(self)                             # the public build's window
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "config.json"
        FakeRuntime.made, FakeRuntime.fail = [], False
        self.addCleanup(setattr, gui, "Runtime", gui.Runtime)
        gui.Runtime = FakeRuntime

    def saved(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def app(self, start_haptics=True, with_tray=False):
        root = tk_root()
        self.addCleanup(close_window, root)
        if with_tray:
            from test_tray import FakeIcon
            self.addCleanup(setattr, tray.pystray, "Icon", tray.pystray.Icon)
            tray.pystray.Icon = FakeIcon
        app = gui.App(root, config.load(self.path), str(self.path), start_haptics=start_haptics,
                      use_tray=with_tray, ask_startup=False)
        if with_tray:
            self.assertTrue(app.tray.active)
        return app

    def launched(self, **kw):
        """A window as it is a moment after launch (the scheduled first start has run)."""
        app = self.app(**kw)
        app._start_at_launch()
        return app

    def running(self, app):
        return app.rt is not None and app.rt.running

    # -- the window ---------------------------------------------------------------------------------
    def test_the_switch_is_at_the_top_of_the_window_and_on_by_default(self):
        app = self.launched()
        self.assertEqual(str(app.haptics_box.cget("text")), "Haptics on")
        self.assertTrue(app.haptics_var.get())
        self.assertTrue(self.running(app))
        self.assertNotIn("haptics_on", self.saved(), "on is the default: config.json stays slim")

    def test_switching_off_stops_everything_and_nothing_brings_it_back(self):
        app = self.launched()
        rt = app.rt
        app.haptics_box.invoke()                              # a real click on the box (no focus needed)
        self.assertFalse(app.haptics_on)
        self.assertFalse(app.haptics_var.get())
        self.assertTrue(rt.stopped)
        self.assertIsNone(app.rt)
        self.assertEqual(app.status_var.get(), "Haptics off")
        self.assertEqual(app.msg_var.get(), gui.HAPTICS_OFF_MSG)
        self.assertIs(self.saved().get("haptics_on"), False)
        made = len(FakeRuntime.made)
        app._retry_at = 0.0
        for _ in range(3):
            app.poll()                                        # the retry that recovers a failed start
        app._start_at_launch()                                # a launch start still pending
        self.assertEqual(len(FakeRuntime.made), made, "nothing started the haptics again")
        self.assertEqual(app.status_var.get(), "Haptics off")

    def test_switching_on_starts_them_and_forgets_the_off(self):
        app = self.launched()
        app.haptics_box.invoke()
        app.haptics_box.invoke()
        self.assertTrue(app.haptics_on)
        self.assertTrue(self.running(app))
        self.assertTrue(app.status_var.get().startswith("Running"), app.status_var.get())
        self.assertNotIn("haptics_on", self.saved())

    def test_off_is_remembered_at_the_next_launch(self):
        self.path.write_text(json.dumps({"haptics_on": False}), encoding="utf-8")
        app = self.launched()
        self.assertFalse(app.haptics_on)
        self.assertFalse(app.haptics_var.get())
        self.assertEqual(FakeRuntime.made, [], "the launch did not start them")
        app._refresh()
        self.assertEqual(app.status_var.get(), "Haptics off")
        self.assertEqual(app.msg_var.get(), gui.HAPTICS_OFF_MSG)
        app._retry_at = 0.0
        app.poll()
        self.assertEqual(FakeRuntime.made, [])
        app.set_haptics(True)
        self.assertTrue(self.running(app))
        self.assertNotIn("haptics_on", self.saved())

    def test_switched_off_before_the_launch_start_it_stays_off(self):
        app = self.app()                                      # the first start is still scheduled
        app.set_haptics(False)
        app._start_at_launch()
        self.assertEqual(FakeRuntime.made, [])
        self.assertFalse(app.haptics_on)

    def test_no_start_is_for_this_launch_only(self):
        app = self.launched(start_haptics=False)
        self.assertFalse(app.haptics_on)
        self.assertFalse(app.haptics_var.get())
        self.assertEqual(FakeRuntime.made, [])
        app._refresh()
        self.assertIn("--no-start", app.status_var.get())
        self.assertNotIn("haptics_on", self.saved(), "--no-start must not switch them off for good")
        app.haptics_box.invoke()                              # the user turns them on
        self.assertTrue(self.running(app))
        self.assertNotIn("haptics_on", self.saved())
        app.haptics_box.invoke()                              # and off again: now it is the switch's off
        self.assertEqual(app.status_var.get(), "Haptics off")
        self.assertIs(self.saved().get("haptics_on"), False)

    def test_no_start_with_the_switch_saved_off_is_off_until_switched_on(self):
        self.path.write_text(json.dumps({"haptics_on": False}), encoding="utf-8")
        app = self.launched(start_haptics=False)
        self.assertFalse(app.haptics_on)
        app.set_haptics(True)
        self.assertTrue(self.running(app))
        self.assertNotIn("haptics_on", self.saved())

    def test_restart_haptics_turns_switched_off_haptics_on(self):
        app = self.launched()
        app.set_haptics(False)
        app.restart_haptics()                                 # the button and the tray item
        self.assertTrue(app.haptics_on)
        self.assertTrue(app.haptics_var.get())
        self.assertTrue(self.running(app))
        self.assertNotIn("haptics_on", self.saved())

    def test_changes_that_need_a_restart_wait_while_off(self):
        app = self.launched()
        app.set_haptics(False)
        made = len(FakeRuntime.made)
        app.mode.set("demo")
        app._restart_if_on()                                  # the Games / Demo buttons
        app.device_var.set(app.DEFAULT_OUTPUT)
        app._device_picked()                                  # a new output device
        self.assertEqual(len(FakeRuntime.made), made, "switched off means off")
        self.assertEqual(self.saved()["audio"]["device"], "", "the change itself is kept")
        app.set_haptics(True)
        self.assertTrue(app.rt.demo, "and applies when they come back")

    def test_a_failed_start_keeps_the_switch_on_and_retrying_until_switched_off(self):
        app = self.launched()
        app.set_haptics(False)
        FakeRuntime.fail = True
        app.set_haptics(True)
        self.assertTrue(app.haptics_on, "the switch says what the user wants, not whether it worked")
        self.assertIn("Output > Device", app.start_error)
        made = len(FakeRuntime.made)
        app._retry_at = 0.0
        app.poll()
        self.assertEqual(len(FakeRuntime.made), made + 1, "retried")
        app.set_haptics(False)
        self.assertEqual(app.start_error, "")
        self.assertEqual(app.status_var.get(), "Haptics off")
        app._retry_at = 0.0
        app.poll()
        self.assertEqual(len(FakeRuntime.made), made + 1, "and no longer")

    def test_switching_off_clears_what_the_runtime_last_showed(self):
        app = self.launched()
        app.tele_vars["rpm"].set(" 7200/8000")
        app.sources_var.set("Forza (UDP): 60 fps")
        app.level_var.set("-12.0 dB")
        app.set_haptics(False)
        for _ in range(2):
            app.poll()
        self.assertEqual({v.get() for v in app.tele_vars.values()}, {"-"})
        self.assertEqual((app.sources_var.get(), app.level_var.get()), ("", "-inf dB"))

    def test_the_mode_buttons_wait_and_the_restart_button_turns_them_on(self):
        app = self.launched()
        app.set_haptics(False)
        app.mode_buttons["demo"].invoke()
        app.mode_buttons["game"].invoke()
        app.mode_buttons["demo"].invoke()
        self.assertEqual([r for r in FakeRuntime.made if r.running], [])
        self.assertFalse(app.haptics_on)
        app.restart_button.invoke()
        self.assertTrue(app.haptics_on)
        self.assertTrue(app.haptics_var.get())
        self.assertTrue(self.running(app))
        self.assertTrue(app.rt.demo, "the mode picked while off applies")

    def test_advanced_ok_saves_and_waits_while_off_and_restarts_while_on(self):
        app = self.launched()
        forza = app.cfg["sources"]["forza"]
        app.set_haptics(False)
        made = len(FakeRuntime.made)
        app._apply_advanced([((forza, "port"), 5556)])
        self.assertEqual(self.saved()["sources"]["forza"]["port"], 5556)
        self.assertEqual(len(FakeRuntime.made), made)
        self.assertIn("apply when the haptics are switched on", app.msg_var.get())
        app.set_haptics(True)
        made = len(FakeRuntime.made)
        app._apply_advanced([((forza, "port"), 5557)])
        self.assertEqual(len(FakeRuntime.made), made + 1, "a fresh runtime picks the port up")
        self.assertEqual(app.msg_var.get(), "Advanced settings saved and applied.")

    def test_a_switch_that_cannot_be_saved_says_so(self):
        app = self.launched()
        real_save = config.save_user
        self.addCleanup(setattr, config, "save_user", real_save)

        def refuse(*_a, **_k):
            raise PermissionError(13, "Permission denied")
        config.save_user = refuse
        app.set_haptics(False)
        self.assertTrue(app.msg_var.get().startswith(gui.HAPTICS_OFF_MSG), "the switch's own message stays")
        self.assertIn("could not be saved", app.msg_var.get())
        self.assertIn("will be on again", app.msg_var.get())
        app.set_haptics(True)                                 # the file still says on: nothing to warn about
        self.assertNotIn("could not be saved", app.msg_var.get())

        config.save_user = real_save
        app.set_haptics(False)                                # saved: the file says off now
        self.assertIs(self.saved().get("haptics_on"), False)
        config.save_user = refuse
        app.set_haptics(True)
        self.assertIn("will be off again", app.msg_var.get())
        app.set_haptics(False)                                # back to what the file says: no warning
        self.assertNotIn("could not be saved", app.msg_var.get())
        app.restart_haptics()                                 # Restart's way back warns too
        self.assertIn("will be off again", app.msg_var.get())

    @unittest.skipUnless(tray.AVAILABLE, f"pystray/Pillow not installed ({tray.IMPORT_ERROR})")
    def test_an_unsaved_switch_from_the_tray_is_said_in_the_tray(self):
        app = self.launched(with_tray=True)
        notes = []
        app.tray.notify = lambda message, *a, **k: notes.append(message)
        self.addCleanup(setattr, config, "save_user", config.save_user)
        config.save_user = lambda *_a, **_k: (_ for _ in ()).throw(OSError(28, "No space left on device"))
        app.toggle_haptics()                                  # the window is hidden: only the tray can say it
        self.assertEqual(len(notes), 1)
        self.assertIn("will be on again", notes[0])
        app.quit_app()

    def test_the_preset_note_says_loaded_while_off(self):
        app = self.launched()
        self.assertIn("active", app.preset_note.get())
        app.set_haptics(False)
        self.assertIn("loaded", app.preset_note.get())

    # -- the tray -----------------------------------------------------------------------------------
    @unittest.skipUnless(tray.AVAILABLE, f"pystray/Pillow not installed ({tray.IMPORT_ERROR})")
    def test_the_tray_item_and_the_window_box_are_one_switch(self):
        app = self.launched(with_tray=True)
        icon = app.tray.icon
        switch = next(i for i in icon.menu if str(i) == "Haptics on")
        self.assertTrue(switch.checked)
        app._refresh()                                        # what poll() does, window then tray
        app._refresh_tray(force=True)
        self.assertIs(icon.icon, app.tray._running_img)

        builds = icon.menu_builds
        switch(icon)                                          # clicked in the tray: queued for the Tk thread
        self.assertTrue(app.haptics_on, "nothing runs on pystray's thread")
        app._drain_ui_queue()
        self.assertFalse(app.haptics_on)
        self.assertFalse(app.haptics_var.get(), "the window's box follows")
        self.assertFalse(switch.checked)
        self.assertGreater(icon.menu_builds, builds, "the menu is rebuilt, so the tick is not stale")
        self.assertEqual(app.tray_line("state"), "Haptics: off")
        self.assertEqual(app.tray_line("error"), "")
        self.assertEqual(icon.title, "OpenShaker - haptics off")
        self.assertIs(icon.icon, app.tray._stopped_img, "grey while off")

        switch(icon)                                          # clicked again: on
        app._drain_ui_queue()
        self.assertTrue(app.haptics_on)
        self.assertTrue(switch.checked)
        self.assertTrue(app.haptics_var.get())
        self.assertTrue(self.running(app))
        self.assertIs(icon.icon, app.tray._running_img)
        self.assertNotIn("haptics_on", self.saved())

        builds = icon.menu_builds
        app.haptics_box.invoke()                              # and the window's box moves the tray's tick
        self.assertFalse(switch.checked)
        self.assertGreater(icon.menu_builds, builds)
        app.haptics_box.invoke()
        self.assertTrue(switch.checked)
        self.assertTrue(self.running(app))
        app.quit_app()

    @unittest.skipUnless(tray.AVAILABLE, f"pystray/Pillow not installed ({tray.IMPORT_ERROR})")
    def test_the_tray_says_no_start(self):
        app = self.launched(with_tray=True, start_haptics=False)
        app._refresh_tray(force=True)
        self.assertEqual(app.tray_line("state"), "Haptics: off (--no-start)")
        self.assertFalse(next(i for i in app.tray.icon.menu if str(i) == "Haptics on").checked)
        app.quit_app()

    @unittest.skipUnless(tray.AVAILABLE, f"pystray/Pillow not installed ({tray.IMPORT_ERROR})")
    def test_start_with_windows_rebuilds_the_menu_too(self):
        app = self.launched(with_tray=True)
        startup = next(i for i in app.tray.icon.menu if str(i) == "Start with Windows")
        self.assertFalse(startup.checked)
        builds = app.tray.icon.menu_builds
        app.ask_windows_startup(answer=True)                  # the first-run question (fake registry)
        self.assertGreater(app.tray.icon.menu_builds, builds)
        self.assertTrue(startup.checked)
        builds = app.tray.icon.menu_builds
        app.toggle_windows_startup()
        self.assertGreater(app.tray.icon.menu_builds, builds)
        self.assertFalse(startup.checked)
        app.quit_app()


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "config.json"

    def load_with(self, user: dict) -> dict:
        self.path.write_text(json.dumps(user), encoding="utf-8")
        return config.load(self.path)

    def test_on_by_default_and_kept_only_while_off(self):
        cfg = config.load(self.path)
        self.assertIs(cfg["haptics_on"], True)
        cfg["haptics_on"] = False
        self.assertIs(config.save_user(cfg, self.path)["haptics_on"], False)
        cfg = config.load(self.path)
        self.assertIs(cfg["haptics_on"], False)
        cfg["haptics_on"] = True
        self.assertNotIn("haptics_on", config.save_user(cfg, self.path))

    def test_a_hand_edit_that_is_not_true_or_false_leaves_them_on(self):
        for value in ("false", 0, None, "off"):
            with self.subTest(value=value):
                self.assertIs(self.load_with({"haptics_on": value})["haptics_on"], True)

    def test_the_old_autostart_switch_does_not_turn_them_off(self):
        cfg = self.load_with({"autostart": False})
        self.assertIs(cfg["haptics_on"], True)
        self.assertNotIn("autostart", config.save_user(cfg, self.path))


if __name__ == "__main__":
    unittest.main()
