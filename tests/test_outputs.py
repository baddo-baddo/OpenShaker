"""The optional-output hook (outputs.py): with no package present the app is exactly today's app; with
one present it gets one row, one tray line and a stop item, and can never be harmed. Every package here
is a fake ("extra"); a real optional package in this working copy is never loaded."""
import importlib
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import close_window, fake_registry, tk_root                     # noqa: E402
from openshaker import config, gui, outputs, tray                           # noqa: E402
from openshaker.audio import DeviceNotFound                                 # noqa: E402
from openshaker.runtime import Runtime                                      # noqa: E402

NAME = "extra"
PACKAGE = f"openshaker.{NAME}"
REAL_PACKAGES = outputs.OPTIONAL_PACKAGES          # what the loader looks for outside these tests
_MISSING = object()


def only_package(test, name):
    """Point the loader at `name` alone for this test, so a real optional package is never loaded."""
    test.addCleanup(setattr, outputs, "OPTIONAL_PACKAGES", outputs.OPTIONAL_PACKAGES)
    outputs.OPTIONAL_PACKAGES = (name,)


def set_package(test, module):
    """Make the loader's one package openshaker.extra and `import openshaker.extra` see `module`
    (None = the package is absent), for this test only."""
    only_package(test, NAME)
    saved = sys.modules.get(PACKAGE, _MISSING)
    test.addCleanup(lambda: sys.modules.pop(PACKAGE, None) if saved is _MISSING
                    else sys.modules.__setitem__(PACKAGE, saved))
    sys.modules[PACKAGE] = module


def fake_package(output):
    module = types.ModuleType(PACKAGE)
    module.make_output = lambda: output
    return module


BROKEN = "_broken_output_for_tests"


def broken_package(test, source):
    """A real package on disk, openshaker._broken_output_for_tests, whose __init__.py is `source`, and the
    loader pointed at it for this test only. Real files, so a half-written one fails the way Python's own
    import fails; a real optional package is never imported (it may be half-written right now)."""
    import openshaker
    folder = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, folder, True)
    (folder / BROKEN).mkdir()
    (folder / BROKEN / "__init__.py").write_text(source, encoding="utf-8")

    def undo():
        openshaker.__path__.remove(str(folder))
        for key in [k for k in sys.modules if k.split(".")[:2] == ["openshaker", BROKEN]]:
            del sys.modules[key]
        importlib.invalidate_caches()
    openshaker.__path__.insert(0, str(folder))
    importlib.invalidate_caches()
    test.addCleanup(undo)
    only_package(test, BROKEN)


HALF_WRITTEN = "from .engine import Engine\n\ndef make_output(:\n"
IMPORT_RAISES = "raise RuntimeError('a library it needs is missing')\n"


class FakeOutput:
    """Duck-typed, as an optional package's output may be (it need not subclass outputs.Output)."""

    name = NAME
    label = "extra output"

    def __init__(self, fail=()):
        self.calls, self.fail, self.ctx = [], set(fail), None
        self.alive_at_start = self.alive_at_stop = None
        self.line = "Extra output: waiting"

    def _maybe_fail(self, what):
        self.calls.append(what)
        if what in self.fail:
            raise RuntimeError(f"{what} broke")

    def start(self, ctx):
        self.ctx = ctx
        self.alive_at_start = [not s.stopping() for s in ctx.sources]
        self._maybe_fail("start")

    def stop(self):
        self.alive_at_stop = [not s.stopping() for s in self.ctx.sources] if self.ctx else None
        self._maybe_fail("stop")

    def on_preset(self, preset, profile):
        self.calls.append(("preset", preset, profile))

    def status(self):
        return {"state": "waiting", "summary": "waiting", "problem": ""}

    def close(self):
        self._maybe_fail("close")

    def build_row(self, parent):
        self._maybe_fail("build_row")
        from tkinter import ttk
        row = ttk.Frame(parent)
        ttk.Label(row, text="Extra output (test)").pack(side="left")
        return row

    def tray_line(self):
        self._maybe_fail("tray_line")
        return self.line

    def stop_now(self):
        self._maybe_fail("stop_now")


class LoadTests(unittest.TestCase):
    def test_an_absent_package_is_no_output_and_no_message(self):
        set_package(self, None)
        self.assertEqual(outputs.load_optional_outputs(), ([], []))

    def test_a_present_package_gives_its_output(self):
        out = FakeOutput()
        set_package(self, fake_package(out))
        self.assertEqual(outputs.load_optional_outputs(), ([out], []))

    def test_a_package_that_offers_nothing_or_breaks_is_reported_not_raised(self):
        set_package(self, fake_package(None))
        self.assertEqual(outputs.load_optional_outputs(), ([], []))
        broken = types.ModuleType(PACKAGE)
        broken.make_output = lambda: (_ for _ in ()).throw(RuntimeError("nothing to drive"))
        set_package(self, broken)
        found, problems = outputs.load_optional_outputs()
        self.assertEqual(found, [])
        self.assertIn("nothing to drive", problems[0])

    def test_a_package_that_cannot_be_imported_is_simply_not_there(self):
        def import_module(name):
            raise ModuleNotFoundError("No module named 'hidapi'", name="hidapi")
        only_package(self, NAME)
        real = outputs.importlib.import_module
        self.addCleanup(setattr, outputs.importlib, "import_module", real)
        outputs.importlib.import_module = import_module
        self.assertEqual(outputs.load_optional_outputs(), ([], []), "as agreed: no row, no tray item, no error")
        outputs.importlib.import_module = real
        set_package(self, types.ModuleType(PACKAGE))            # a package without make_output()
        self.assertEqual(outputs.load_optional_outputs(), ([], []))

    def test_a_package_that_is_there_but_breaks_on_import_is_one_message(self):
        cases = {
            "SyntaxError": HALF_WRITTEN,                          # a file caught mid-write
            "RuntimeError": IMPORT_RAISES,
            "NameError": "make_output = ExtraOutput\n",
            "OSError": "raise OSError(126, 'The specified module could not be found')\n",
            "AttributeError": "import os\nos.no_such_thing\n",   # raised by its code, not a missing make_output
            "SystemExit": "import sys\nsys.exit(3)\n",
        }
        for kind, source in cases.items():
            with self.subTest(kind):
                broken_package(self, source)
                found, problems = outputs.load_optional_outputs()
                self.assertEqual(found, [])
                self.assertEqual(len(problems), 1, problems)
                self.assertTrue(problems[0].startswith(f"{BROKEN}: {kind}"), problems[0])
                self.doCleanups()

    def test_an_import_error_inside_the_package_stays_silent_as_agreed(self):
        broken_package(self, "import hidapi_not_installed_here\n")
        self.assertEqual(outputs.load_optional_outputs(), ([], []))

    def test_a_long_message_is_cut(self):
        broken_package(self, f"raise RuntimeError({'x' * 5000!r})\n")
        _found, problems = outputs.load_optional_outputs()
        self.assertLessEqual(len(problems[0]), 200)


class PublicBuildTests(unittest.TestCase):
    """An optional package must never be followed into the installer."""

    def test_no_code_imports_an_optional_package_by_name(self):
        for name in REAL_PACKAGES:
            for path in (ROOT / "openshaker").rglob("*.py"):
                if name in path.relative_to(ROOT / "openshaker").parts:
                    continue                               # the optional package itself, if present
                text = path.read_text(encoding="utf-8")
                n = re.escape(name)
                self.assertIsNone(re.search(rf"^\s*(from|import)\s+(openshaker\.{n}|\.{n})\b", text, re.M), path.name)
                self.assertIsNone(re.search(rf"import_module\(\s*['\"]openshaker\.{n}", text), path.name)

    def test_the_installer_excludes_each_one_and_the_build_checks_for_it(self):
        spec = (ROOT / "installer" / "OpenShaker.spec").read_text(encoding="utf-8")
        private = re.search(r"^PRIVATE = \((.*)\)$", spec, re.M)
        self.assertIsNotNone(private)
        self.assertIn("list(PRIVATE)", spec)
        build = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn('"PYZ-00.toc"', build)
        for name in REAL_PACKAGES:
            with self.subTest(name):
                self.assertIn(f'"openshaker.{name}"', private.group(1))
                self.assertIn(rf"openshaker[\\/.]{name}", build)     # PowerShell regex: backslash, slash or dot
                self.assertIn(rf"openshaker[\\/]{name}", build)


class StopLabelTests(unittest.TestCase):
    def test_the_tray_item_says_what_it_stops(self):
        class Bare:
            name = "extra"
        own = FakeOutput()
        own.stop_label = "Stop the extra output now"
        self.assertEqual(outputs.stop_label(Bare()), "Stop extra")
        self.assertEqual(outputs.stop_label(FakeOutput()), "Stop extra output")
        self.assertEqual(outputs.stop_label(own), "Stop the extra output now")
        self.assertEqual(outputs.stop_label(outputs.Output()), "Stop output", "the contract's own defaults")
        self.assertEqual(outputs.stop_label(object()), "Stop output")


class RuntimeHookTests(unittest.TestCase):
    def make(self, out, **kw):
        rt = Runtime(config.load(None), demo=True, no_audio=True, outputs=[out], **kw)
        self.addCleanup(rt.stop)
        rt.start()
        return rt

    def test_a_runtime_without_outputs_has_none(self):
        self.assertEqual(Runtime(config.load(None)).outputs, ())

    def test_outputs_start_after_the_sources_and_stop_before_them(self):
        out = FakeOutput()
        rt = self.make(out)
        self.assertEqual(out.calls[0], "start")
        self.assertEqual(out.ctx.sources, rt.sources)
        self.assertTrue(out.ctx.demo)
        self.assertEqual(out.alive_at_start, [True] * len(rt.sources), "the sources were already running")
        self.assertEqual(out.ctx.preset(), rt.cfg.get("_preset"))
        st = rt.status()["outputs"]
        self.assertEqual((st[0]["name"], st[0]["summary"]), (NAME, "waiting"))
        profile = str(config.resolve_profile(rt.cfg, "profiles/forza_motorsport/profile.json"))
        rt.switch_profile(profile, preset="forza")
        self.assertIn(("preset", "forza", profile), out.calls)
        rt.stop()
        self.assertIn("stop", out.calls)
        self.assertEqual(out.alive_at_stop, [True] * len(out.ctx.sources), "stopped while its sources still ran")

    def test_a_failing_output_never_stops_the_haptics(self):
        out = FakeOutput(fail={"start", "stop"})
        rt = self.make(out)
        self.assertTrue(rt.running)
        self.assertIn("start: RuntimeError: start broke", rt.status()["outputs"][0]["problem"])
        rt.stop()
        self.assertFalse(rt.running)


class ConsoleRunnerTests(unittest.TestCase):
    def test_the_console_runner_and_log_never_arm_an_output(self):
        from test_cli import IsolatedInstance, run_cli              # free port and mutex, temp config
        out = FakeOutput()
        set_package(self, fake_package(out))
        iso = IsolatedInstance()
        iso.setUp()
        self.addCleanup(iso.doCleanups)
        code, _ = run_cli(*iso.demo("--duration", "0.2", "--log", iso.dir / "drive"))
        self.assertEqual(code, 0)
        self.assertEqual(out.calls, [])


class GuiHookTests(unittest.TestCase):
    """The window and the tray, with and without the package."""

    def setUp(self):
        fake_registry(self)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.runtime_kwargs = []
        record = self.runtime_kwargs

        class NoAudio:
            running = False

            def __init__(_s, *a, **k):
                record.append(k)

            def start(_s):
                raise DeviceNotFound("output device 'ButtKicker' is not connected")

            def stop(_s):
                pass

        self.addCleanup(setattr, gui, "Runtime", gui.Runtime)
        gui.Runtime = NoAudio

    def app(self):
        root = tk_root()
        self.addCleanup(close_window, root)
        path = self.dir / "config.json"
        return gui.App(root, config.load(path), str(path), use_tray=False, ask_startup=False)

    def tray_texts(self, app):
        from test_tray import FakeIcon
        real_icon, tray.pystray.Icon = tray.pystray.Icon, FakeIcon
        self.addCleanup(setattr, tray.pystray, "Icon", real_icon)
        t = tray.Tray(app, ROOT / "openshaker" / "openshaker.ico")
        self.assertTrue(t.active)
        return t, [i for i in t.icon.menu if str(i).strip("- ")]

    def widget_texts(self, widget):
        texts = []
        for child in widget.winfo_children():
            try:
                texts.append(str(child.cget("text")))
            except Exception:
                pass
            texts += self.widget_texts(child)
        return texts

    def test_without_the_package_the_window_and_tray_are_as_before(self):
        set_package(self, None)
        app = self.app()
        self.assertEqual(app.outputs, [])
        self.assertEqual(app.output_rows, {})
        self.assertFalse([t for t in self.widget_texts(app.root) if "Extra output" in t])
        app.start()
        self.assertEqual(self.runtime_kwargs[-1].get("outputs"), [])
        app._refresh()
        if tray.AVAILABLE:
            _t, items = self.tray_texts(app)
            self.assertFalse([str(i) for i in items if "extra" in str(i).lower() or str(i).startswith("Stop ")])
        app.quit_app()                                   # quitting works with nothing to close

    def test_with_the_package_its_row_its_tray_line_and_a_stop_item(self):
        out = FakeOutput()
        set_package(self, fake_package(out))
        app = self.app()
        self.assertEqual(app.outputs, [out])
        row = app.output_rows[NAME]
        self.assertEqual(row.winfo_manager(), "grid", "the window put the output's own row in place")
        self.assertIn("Extra output (test)", self.widget_texts(app.root))
        app.start()
        self.assertEqual(self.runtime_kwargs[-1].get("outputs"), [out], "the window hands its outputs to the runtime")
        if tray.AVAILABLE:
            _t, items = self.tray_texts(app)
            line = next(i for i in items if str(i) == "Extra output: waiting")
            self.assertFalse(line.enabled)
            self.assertTrue(line.visible)
            out.line = None                                   # nothing to say: the line hides
            self.assertFalse(line.visible)
            stop = next(i for i in items if str(i) == "Stop extra output")
            self.assertTrue(stop.visible, "always there while the package is")
            stop(_t.icon)                                     # pystray's thread: stop_now() directly
            self.assertIn("stop_now", out.calls)
        app.quit_app()
        self.assertIn("close", out.calls)

    def test_a_misbehaving_output_never_breaks_the_window(self):
        out = FakeOutput(fail={"build_row", "tray_line", "stop_now", "close"})
        set_package(self, fake_package(out))
        app = self.app()
        self.assertEqual(app.output_rows, {}, "a row that fails to build is left out")
        app._refresh()
        self.assertIn("building its row failed", app.msg_var.get())
        self.assertEqual(app.output_tray_line(out), f"{NAME}: RuntimeError")
        app.stop_output(out)                                  # raises inside: swallowed
        app.quit_app()                                        # a close() that raises does not stop the quit

    def test_a_make_output_that_fails_is_said_once(self):
        broken = types.ModuleType(PACKAGE)
        broken.make_output = lambda: (_ for _ in ()).throw(RuntimeError("nothing to drive"))
        set_package(self, broken)
        app = self.app()
        app._refresh()
        self.assertIn(f"Could not load {NAME}: RuntimeError: nothing to drive", app.msg_var.get())
        self.assertEqual(app.outputs, [])

    def check_carries_on_with_one_message(self, expected):
        """The window opens, says `expected` once, starts, has the usual tray menu and quits."""
        app = self.app()
        self.assertEqual((app.outputs, app.output_rows), ([], {}))
        app._refresh()
        self.assertIn(expected, app.msg_var.get())
        app.msg_var.set("")
        app._refresh()
        self.assertNotIn(expected, app.msg_var.get(), "said once, not on every refresh")
        app.start()
        self.assertEqual(self.runtime_kwargs[-1].get("outputs"), [])
        if tray.AVAILABLE:
            _t, items = self.tray_texts(app)
            texts = [str(i) for i in items]
            self.assertIn("Quit", texts)
            self.assertIn("Restart haptics", texts)
            self.assertFalse([t for t in texts if BROKEN in t or t.startswith("Stop ")])
        app.quit_app()

    def test_a_half_written_package_does_not_stop_the_app(self):
        broken_package(self, HALF_WRITTEN)
        self.check_carries_on_with_one_message(f"Could not load {BROKEN}: SyntaxError")

    def test_a_package_whose_import_raises_does_not_stop_the_app(self):
        broken_package(self, IMPORT_RAISES)
        self.check_carries_on_with_one_message(f"Could not load {BROKEN}: RuntimeError: a library it needs is missing")

    def test_even_a_loader_that_raises_does_not_stop_the_app(self):
        def explode():
            raise RuntimeError("loader broke")
        self.addCleanup(setattr, gui, "load_optional_outputs", gui.load_optional_outputs)
        gui.load_optional_outputs = explode
        self.check_carries_on_with_one_message("Could not load optional outputs: RuntimeError: loader broke")


if __name__ == "__main__":
    unittest.main()
