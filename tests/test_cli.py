"""The console runner and --quit: one copy at a time, logged drives that survive, a clean scripted stop."""
import contextlib
import csv
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker import __main__ as cli                                    # noqa: E402
from openshaker import __version__, single_instance                       # noqa: E402
from openshaker.drivelog import CSV_FIELDS                                # noqa: E402


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue()


class IsolatedInstance(unittest.TestCase):
    """Never the live app's port or mutex: the maintainer's OpenShaker may well be running."""

    def setUp(self):
        for name, value in (("PORT", free_port()), ("MUTEX_NAME", f"OpenShakerTest-{os.getpid()}-{id(self)}")):
            self.addCleanup(setattr, single_instance, name, getattr(single_instance, name))
            setattr(single_instance, name, value)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.config = self.dir / "config.json"

    def demo(self, *extra):
        return ("--config", self.config, "--demo", "--no-audio") + extra


class ConsoleRunnerTests(IsolatedInstance):
    def test_refuses_to_run_while_the_app_owns_the_ports(self):
        app = single_instance.acquire()                       # the tray app
        self.addCleanup(app.close)
        drive = self.dir / "drive"
        code, out = run_cli(*self.demo("--duration", "0.2", "--log", drive))
        self.assertEqual(code, 1)
        self.assertIn("already running", out)
        self.assertFalse(drive.exists(), "nothing is logged by a run that cannot hear the game")

    def test_a_logged_drive_is_complete_and_says_what_it_was(self):
        drive = self.dir / "drive"
        code, out = run_cli(*self.demo("--duration", "0.8", "--log", drive))
        self.assertEqual(code, 0, out)
        meta = json.loads((drive / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["version"], __version__)
        self.assertEqual(meta["sources"], ["demo"], "the sources used to be cleared before meta.json was written")
        self.assertGreater(meta["frames"], 0)
        self.assertEqual(meta["frames_by_source"], {"demo": meta["frames"]})
        for key in ("game", "profile", "master_gain", "effects", "ace_susp_scale_m", "forza_kind"):
            self.assertIn(key, meta)
        self.assertIn("trim", meta["effects"]["engine"])
        with open(drive / "telemetry.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], CSV_FIELDS)
        self.assertEqual(len(rows) - 1, meta["frames"])
        with wave.open(str(drive / "ours.wav")) as w:
            self.assertGreater(w.getnframes(), 0)
        self.assertIn("(Demo drive)", out)
        self.assertFalse(single_instance.is_running(), "the lock goes with the run")

    def test_an_existing_drive_is_not_overwritten_by_accident(self):
        drive = self.dir / "drive"
        self.assertEqual(run_cli(*self.demo("--duration", "0.2", "--log", drive))[0], 0)
        code, out = run_cli(*self.demo("--duration", "0.2", "--log", drive))
        self.assertEqual(code, 1)
        self.assertIn("already holds a logged drive", out)
        self.assertEqual(run_cli(*self.demo("--duration", "0.2", "--log", drive, "--overwrite"))[0], 0)

    def test_a_stop_file_stops_the_run_and_is_cleaned_up(self):
        stop = self.dir / "stop"
        stop.write_text("")                                   # left over from an earlier run
        timer = threading.Timer(1.2, stop.touch)
        self.addCleanup(timer.cancel)
        timer.start()
        started = time.monotonic()
        code, out = run_cli(*self.demo("--duration", "15", "--stop-file", stop))
        took = time.monotonic() - started
        self.assertEqual(code, 0)
        self.assertIn("removed an old stop file", out)
        self.assertGreater(took, 1.0, "the old stop file must not stop the new run at once")
        self.assertLess(took, 8.0, "the new stop file stops it")
        self.assertFalse(stop.exists(), "and is removed, so the next run does not stop at once")

    def test_quit_stops_a_console_run_cleanly(self):
        from openshaker import gui
        drive = self.dir / "drive"
        result = {}
        run = threading.Thread(target=lambda: result.update(code=run_cli(*self.demo(
            "--duration", "30", "--log", drive))[0]))
        run.start()
        deadline = time.monotonic() + 10
        while not single_instance.is_running() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(gui.quit_running(timeout=10.0))
        run.join(10)
        self.assertEqual(result.get("code"), 0)
        self.assertTrue(json.loads((drive / "meta.json").read_text(encoding="utf-8"))["complete"])


class QuitTests(IsolatedInstance):
    def test_quit_with_nothing_running_is_quick_and_quiet(self):
        from openshaker import gui
        started = time.monotonic()
        self.assertIsNone(gui.quit_running(timeout=2.0))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(gui.main(["--quit"]), 0)
        self.assertIn("not running", out.getvalue())
        self.assertLess(time.monotonic() - started, 5.0)

    def test_the_listener_passes_quit_on(self):
        listener = single_instance.acquire()
        self.addCleanup(listener.close)
        asked = threading.Event()
        listener.on_quit = asked.set
        self.assertTrue(single_instance.signal_existing(single_instance.QUIT))
        self.assertTrue(asked.wait(3.0))

    def test_quit_waits_until_the_app_has_gone(self):
        from openshaker import gui
        listener = single_instance.acquire()
        listener.on_quit = lambda: threading.Timer(0.5, listener.close).start()   # the app takes a moment
        started = time.monotonic()
        self.assertTrue(gui.quit_running(timeout=5.0))
        self.assertGreaterEqual(time.monotonic() - started, 0.4)
        self.assertFalse(single_instance.is_running())


class ReplayHintTests(unittest.TestCase):
    def hint(self, meta):
        return cli.replay_hint(meta, "sessions/x")

    def test_the_plugin_follows_the_game(self):
        self.assertIn("--plugin fh5", self.hint({"frames_by_source": {"forza": 9}, "forza_kind": "horizon"}))
        self.assertIn("--plugin fm", self.hint({"frames_by_source": {"forza": 9}, "forza_kind": "motorsport"}))
        self.assertIn("--plugin ace", self.hint({"frames_by_source": {"ace": 9}}))
        self.assertIn("--plugin beamng", self.hint({"frames_by_source": {"beamng": 9, "forza": 1}}))

    def test_games_without_a_haptic_connect_plugin(self):
        self.assertIn("tm_tune", self.hint({"frames_by_source": {"trackmania": 9}}))
        self.assertIn("no telemetry arrived", self.hint({"frames_by_source": {}}))
        self.assertIn("no telemetry arrived", self.hint(None))


if __name__ == "__main__":
    unittest.main()
