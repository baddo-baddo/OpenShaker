"""The window keeps a sensible width: long status and source lines wrap instead of widening it (with
Trackmania's "waiting for Openplanet Data Sender ..." line the window used to open about 1480 px wide)."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import close_window, fake_registry, no_optional_outputs, tk_root    # noqa: E402
from openshaker import config, gui                                           # noqa: E402
from test_haptics_switch import FakeRuntime                                  # noqa: E402

LONG_TM = ("waiting for Openplanet Data Sender on 127.0.0.1:28765 (start Trackmania with Openplanet and the "
           "Data Sender plugin)")


def source(name, status):
    return {"name": name, "status": status, "fps": 0.0, "error": False, "phase": ""}


class LongLinesRuntime(FakeRuntime):
    """The longest lines the window shows in everyday use."""

    def status(self):
        st = super().status()
        st.update(device="Speakers (2- ButtKicker PRO) [Windows WASAPI]", latency_ms=20.0, game="Forza Horizon 5",
                  profile="profiles/forza_horizon/profile.json",
                  sources=[source("forza", "listening on UDP 5555"), source("beamng", "listening on UDP 4444"),
                           source("ace", "waiting for Assetto Corsa EVO"), source("trackmania", LONG_TM)])
        return st


class WindowWidthTests(unittest.TestCase):
    def setUp(self):
        fake_registry(self)
        no_optional_outputs(self)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(setattr, gui, "Runtime", gui.Runtime)
        gui.Runtime = LongLinesRuntime
        FakeRuntime.made, FakeRuntime.fail = [], False

    def window(self):
        root = tk_root(offscreen=True)                    # mapped where nobody sees it: real sizes
        self.addCleanup(close_window, root)
        path = self.dir / "config.json"
        app = gui.App(root, config.load(path), str(path), start_haptics=True, use_tray=False, ask_startup=False)
        app._start_at_launch()
        app._refresh()
        for _ in range(5):
            root.update()
        return root, app

    def test_long_lines_wrap_instead_of_widening_the_window(self):
        root, app = self.window()
        self.assertEqual(app.sources_var.get().splitlines(),
                         ["Forza (UDP): listening on UDP 5555", "BeamNG (UDP): listening on UDP 4444",
                          "Assetto Corsa EVO: waiting for Assetto Corsa EVO", f"Trackmania (Openplanet): {LONG_TM}"],
                         "one game per line")
        self.assertIn("Forza Horizon 5", app.status_var.get())
        self.assertLess(root.winfo_reqwidth(), 1000, "the long Trackmania line no longer sets the width")
        for label in (app.status_label, app.sources_label):
            self.assertLessEqual(label.winfo_reqwidth(), root.winfo_reqwidth())

    def test_the_wrap_follows_the_window_width(self):
        root, app = self.window()
        narrow = int(str(app.sources_label.cget("wraplength")))
        self.assertGreaterEqual(narrow, gui.WRAP_MIN)
        root.geometry(f"{root.winfo_reqwidth() + 500}x{root.winfo_reqheight()}")
        for _ in range(5):
            root.update()
        wide = int(str(app.sources_label.cget("wraplength")))
        self.assertGreater(wide, narrow, "a wider window wraps later")
        self.assertEqual(wide, int(str(app.status_label.cget("wraplength"))))


if __name__ == "__main__":
    unittest.main()
