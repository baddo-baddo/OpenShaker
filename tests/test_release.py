"""Release readiness: a fresh clone on someone else's PC, their shaker, safe defaults, bad input."""
import ast
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openshaker import APP_NAME, autostart, config, single_instance              # noqa: E402
from openshaker.audio import (CHANNEL_CHOICES, AudioOutput, DeviceNotFound,       # noqa: E402
                             channel_choice, normalize_name)
from openshaker.runtime import build_sources                                     # noqa: E402
from openshaker.sources.ace import SharedMem                                     # noqa: E402
from openshaker.sources.beamng import BeamNGSource                               # noqa: E402
from openshaker.sources.forza import ForzaSource                                 # noqa: E402
from openshaker.sources.trackmania import TrackmaniaSource                       # noqa: E402
from fakes import close_window, fake_registry, no_optional_outputs, tk_root                                                  # noqa: E402

SHIPPED_PROFILES = ("forza_motorsport", "forza_horizon", "ace", "beamng", "trackmania")


def free_port(kind=socket.SOCK_DGRAM):
    probe = socket.socket(socket.AF_INET, kind)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def fake_outputs(*entries):
    return [{"index": i, "name": name, "api": api, "channels": 2, "samplerate": 48000.0}
            for i, (name, api) in enumerate(entries)]


class PortabilityTests(unittest.TestCase):
    def test_first_run_without_config_json(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "config.json"
        cfg = config.load(path)
        self.assertTrue(path.exists(), "the first run writes a config.json")
        self.assertTrue(cfg.get("_first_run"))
        self.assertFalse(cfg["windows_startup_asked"], "nothing is registered with Windows before asking")
        for game, prof in cfg["profiles"].items():
            self.assertTrue(config.resolve_profile(cfg, prof).exists(), f"{game}: {prof}")
        self.assertNotIn("_first_run", config.load(path))

    def test_shipped_profiles_hold_no_machine_paths_and_all_their_files(self):
        for name in SHIPPED_PROFILES:
            path = ROOT / "profiles" / name / "profile.json"
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"[A-Za-z]:\\\\|\\\\Users\\\\|/Users/|OneDrive", text), name)
            data = json.loads(text)
            for effect, params in data.get("effects", {}).items():
                for key in ("sample", "wavetable"):
                    if params.get(key):
                        self.assertTrue((path.parent / params[key]).exists(), f"{name}/{effect}: {params[key]}")

    def test_portable_path(self):
        self.assertEqual(config.portable_path(ROOT / "profiles" / "trackmania" / "profile.json"),
                         "profiles/trackmania/profile.json")
        outside = config.portable_path(Path(tempfile.gettempdir()) / "somebody" / "session_7")
        self.assertEqual(outside, "somebody/session_7")
        self.assertNotIn(":", outside)

    def test_code_is_not_tied_to_this_pc(self):
        """No user folder, user name or e-mail address of whoever runs the tests may appear in the
        published files. The needles come from this PC's environment, so none is written down here."""
        files = (list((ROOT / "openshaker").rglob("*.py")) + [ROOT / "openshaker" / "app.pyw", ROOT / "installer" / "build.bat"]
                 + list((ROOT / "installer").glob("*.p*")) + [ROOT / "installer" / "OpenShaker.iss"]
                 + list((ROOT / "tests").glob("*.py")) + list((ROOT / "docs").glob("*.md"))
                 + [ROOT / "README.md", ROOT / "requirements.txt", ROOT / "docs" / "requirements-dev.txt"])
        needles = set()
        for var in ("USERPROFILE", "OneDrive", "HOME"):
            value = os.environ.get(var, "").strip().lower()
            if len(value) > 3:
                needles |= {value, value.replace("\\", "/")}
        for user in {os.environ.get("USERNAME", ""), Path.home().name}:
            user = user.strip().lower()
            if len(user) >= 3:                      # a very short name would match ordinary words
                needles |= {f"users\\{user}", f"users/{user}"}
        drive_user_path = re.compile(r"\b[a-z]:[\\/]+users[\\/]+[^\\/\s\"'*<>|]+", re.IGNORECASE)
        email = re.compile(r"\b[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b")
        placeholder = {"example.com", "example.org", "example.net"}
        for f in files:
            text = f.read_text(encoding="utf-8")
            low = text.lower()
            for needle in needles:
                self.assertNotIn(needle, low, f"{f.relative_to(ROOT)} contains this PC's {needle!r}")
            self.assertIsNone(drive_user_path.search(text), f"{f.relative_to(ROOT)} contains a user folder path")
            for match in email.finditer(text):
                self.assertIn(match.group(1).lower(), placeholder,
                              f"{f.relative_to(ROOT)} contains a real-looking e-mail address")

    def test_no_shell_true(self):
        for f in (ROOT / "openshaker").rglob("*.py"):
            self.assertNotIn("shell=True", f.read_text(encoding="utf-8"), f.name)


class DeviceTests(unittest.TestCase):
    def use(self, devices):
        real = AudioOutput.output_devices
        AudioOutput.output_devices = staticmethod(lambda: devices)
        self.addCleanup(setattr, AudioOutput, "output_devices", real)

    def test_windows_renumbering_is_ignored(self):
        self.assertEqual(normalize_name("Speakers (2- ButtKicker PRO)"), normalize_name("Speakers (ButtKicker PRO)"))
        self.use(fake_outputs(("Speakers (3- ButtKicker PRO)", "Windows WASAPI")))
        self.assertEqual(AudioOutput.find_device("Speakers (2- ButtKicker PRO)", "WASAPI"), 0)

    def test_an_exact_name_beats_a_longer_one_containing_it(self):
        self.use(fake_outputs(("Line Out (BST-1 Amp) Monitor", "Windows WASAPI"),
                              ("Line Out (BST-1 Amp)", "Windows WASAPI")))
        self.assertEqual(AudioOutput.find_device("Line Out (BST-1 Amp)", "WASAPI"), 1)
        self.assertEqual(AudioOutput.find_device("BST-1", "WASAPI"), 0)        # a short name still matches

    def test_a_missing_device_is_reported_not_replaced_by_the_speakers(self):
        self.use(fake_outputs(("Speakers (Realtek(R) Audio)", "Windows WASAPI")))
        out = AudioOutput(device_substr="ButtKicker")
        with self.assertRaises(DeviceNotFound):
            out.resolve()

    def test_picker_lists_shared_outputs_once_each(self):
        long_name = "Speakers (Realtek(R) Audio High Definition)"
        self.use(fake_outputs((long_name[:31], "MME"), (long_name, "Windows DirectSound"),
                              (long_name, "Windows WASAPI"), ("Speakers (2- ButtKicker PRO)", "Windows WASAPI"),
                              ("Output (Exclusive Only)", "Windows WDM-KS")))
        names = AudioOutput.shared_outputs()
        self.assertEqual(sorted(names), sorted([long_name, "Speakers (2- ButtKicker PRO)"]))

    def test_channel_choices(self):
        self.assertEqual(CHANNEL_CHOICES["Left"], [0])
        self.assertEqual(channel_choice([0]), "Left")
        self.assertEqual(channel_choice([1, 0]), "Both")
        self.assertEqual(channel_choice([2]), "Custom")


class LocalOnlyTests(unittest.TestCase):
    def test_listeners_and_clients_default_to_this_pc(self):
        self.assertEqual(ForzaSource().host, "127.0.0.1")
        self.assertEqual(BeamNGSource().host, "127.0.0.1")
        self.assertEqual(TrackmaniaSource().host, "127.0.0.1")
        self.assertEqual(single_instance.HOST, "127.0.0.1")
        for src in build_sources(config.load(None)):
            if hasattr(src, "host"):
                self.assertEqual(src.host, "127.0.0.1", src.name)


class MalformedInputTests(unittest.TestCase):
    def test_random_bytes_never_raise_in_the_packet_parsers(self):
        import random
        rng = random.Random(7)
        forza, beamng = ForzaSource(), BeamNGSource()
        for _ in range(300):
            for n in (0, 1, 88, 92, 96, 136, 232, 324, 331, 500):
                data = bytes(rng.getrandbits(8) for _ in range(n))
                forza.parse(data)
                beamng.parse(data)
                beamng.parse(b"BNG1" + data[4:] if n == 88 else data)

    def _survives(self, src, bad, good):
        class Picky(type(src)):
            def parse(self, data, *a, **k):
                if data == b"boom":
                    raise ValueError("malformed")
                return super().parse(data, *a, **k)
        src.__class__ = Picky
        src.start()
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            deadline = time.time() + 3.0
            # until both got through: the socket may bind between the bad packet and the good one
            while time.time() < deadline and (src.latest() is None or src.malformed == 0):
                out.sendto(bad, ("127.0.0.1", src.port))
                out.sendto(good, ("127.0.0.1", src.port))
                time.sleep(0.05)
        finally:
            out.close()
            src.stop()
        self.assertIsNone(src.error)
        self.assertGreater(src.malformed, 0)
        self.assertIsNotNone(src.latest(), "a good packet after a bad one still arrives")

    def test_udp_source_keeps_running_after_a_bad_packet(self):
        good = bytearray(232)
        struct.pack_into("<i3f", good, 0, 1, 8000.0, 900.0, 3000.0)
        self._survives(ForzaSource(port=free_port()), b"boom", bytes(good))

    def test_beamng_source_keeps_running_after_a_bad_packet(self):
        self._survives(BeamNGSource(port=free_port()), b"boom", bytes(96))

    def test_trackmania_source_skips_odd_messages(self):
        from test_trackmania import snapshot
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def serve():
            try:
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(2.0)
                    conn.recv(4096)
                    conn.sendall(b'[1, 2]\nnot json\n{"type": "snapshot", "source": "vehicle_state", "data": 5}\n'
                                 b'{"type": "snapshot", "source": "vehicle_state", "data": {"worldVel": "fast"}}\n')
                    for i in range(20):
                        conn.sendall(json.dumps(snapshot(1000 + 10 * i, (0.0, 0.0, 20.0))).encode() + b"\n")
                        time.sleep(0.01)
                    time.sleep(0.5)
            except OSError:
                pass
            finally:
                server.close()
        threading.Thread(target=serve, daemon=True).start()
        src = TrackmaniaSource(port=port)
        src.start()
        deadline = time.time() + 5.0
        while src.latest() is None and time.time() < deadline:
            time.sleep(0.05)
        src.stop()
        self.assertIsNone(src.error)
        self.assertIsNotNone(src.latest())

    def test_a_small_shared_memory_block_reads_as_zero_padded(self):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileMappingW.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR]
        k32.CreateFileMappingW.restype = wt.HANDLE
        k32.CloseHandle.argtypes = [wt.HANDLE]
        name = f"Local\\openshaker_test_{os.getpid()}"
        handle = k32.CreateFileMappingW(wt.HANDLE(-1), None, 0x04, 0, 64, name)      # PAGE_READWRITE, 64 bytes
        self.assertTrue(handle)
        self.addCleanup(k32.CloseHandle, handle)
        mem = SharedMem((name,), 800)
        self.assertTrue(mem.open())
        self.addCleanup(mem.close)
        data = mem.read()
        self.assertEqual(len(data), 800)
        self.assertLessEqual(mem.readable, 800)


class EngineRobustnessTests(unittest.TestCase):
    def test_garbled_telemetry_never_reaches_the_output(self):
        import numpy as np
        from openshaker.engine import HapticEngine
        from openshaker.telemetry import Telemetry
        nan, inf = float("nan"), float("inf")

        class Garbled:
            name = "forza"
            seq = 0

            def latest(self):
                Garbled.seq += 1
                t = Telemetry(source="forza", seq=Garbled.seq, t=time.perf_counter(), active=True, rpm=nan,
                              max_rpm=8000.0, speed=nan, throttle=nan, brake=inf, gear=3,
                              accel_lat=nan, accel_long=inf, accel_vert=-inf)
                t.slip_ratio, t.slip_angle, t.susp_travel = [nan] * 4, [inf] * 4, [nan] * 4
                return t

        for profile in SHIPPED_PROFILES:
            cfg = config.load(None)
            config.apply_profile(cfg, ROOT / "profiles" / profile / "profile.json", keep_user={})
            engine = HapticEngine(cfg, 48000, [Garbled()])
            out = np.concatenate([engine.render(480) for _ in range(60)])
            self.assertTrue(np.all(np.isfinite(out)), profile)
            self.assertLessEqual(float(np.max(np.abs(out))), 1.0, profile)


class AppTests(unittest.TestCase):
    """The window: asking before starting with Windows, and picking the output device."""

    def setUp(self):
        from openshaker import gui
        self.gui = gui
        fake_registry(self)                                            # never the real registry
        no_optional_outputs(self)                                      # the public build's window
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "config.json"
        self.starts = []

        class NoAudio:
            running = False

            def __init__(_s, *a, **k):
                self.starts.append(1)

            def start(_s):
                raise DeviceNotFound("output device 'ButtKicker' is not connected")

            def stop(_s):
                pass

        self._runtime, gui.Runtime = gui.Runtime, NoAudio
        self.addCleanup(setattr, gui, "Runtime", self._runtime)
        self.root = tk_root()                              # never keeps the foreground
        self.addCleanup(close_window, self.root)
        self.app = gui.App(self.root, config.load(self.path), str(self.path), use_tray=False, ask_startup=False)

    def test_app_name_is_one_constant(self):
        self.assertEqual(autostart.VALUE_NAME, APP_NAME)
        self.assertTrue(self.root.title().startswith(APP_NAME))

    def test_first_launch_registers_nothing_until_asked(self):
        self.assertFalse(autostart.is_enabled())
        self.app.ask_windows_startup(answer=False)
        self.assertFalse(autostart.is_enabled())
        self.assertTrue(json.loads(self.path.read_text(encoding="utf-8"))["windows_startup_asked"])
        self.app.ask_windows_startup(answer=True)                # already answered: not asked again
        self.assertFalse(autostart.is_enabled())

    def test_saying_yes_registers_it(self):
        self.app.ask_windows_startup(answer=True)
        self.assertTrue(autostart.is_enabled())

    def test_missing_device_says_where_to_pick_one(self):
        self.app.start()
        self.assertIn("Output > Device", self.app.start_error)

    def test_picking_a_device_is_saved(self):
        real = AudioOutput.shared_outputs
        AudioOutput.shared_outputs = classmethod(lambda cls: ["Line Out (BST-1 Amp)"])
        self.addCleanup(setattr, AudioOutput, "shared_outputs", real)
        self.app._fill_devices()
        self.assertIn("Line Out (BST-1 Amp)", self.app.device_box["values"])
        self.app.device_var.set("Line Out (BST-1 Amp)")
        self.app._device_picked()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["audio"]["device"], "Line Out (BST-1 Amp)")
        self.app.device_var.set(self.app.DEFAULT_OUTPUT)
        self.app._device_picked()
        self.assertEqual(self.app.cfg["audio"]["device"], "")

    def test_quit_from_another_process_reaches_the_window(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:      # never the live app's port
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.addCleanup(setattr, single_instance, "PORT", single_instance.PORT)
        single_instance.PORT = port
        listener = single_instance.acquire()
        self.addCleanup(listener.close)
        calls = []
        self.app.quit_app = lambda: calls.append("quit")
        self.app.show_window = lambda: calls.append("show")
        self.gui.connect_listener(self.app, listener)
        self.assertTrue(single_instance.signal_existing(single_instance.QUIT))
        deadline = time.monotonic() + 3.0
        while not calls and time.monotonic() < deadline:
            self.app._drain_ui_queue()                   # what poll() does on the Tk thread
            time.sleep(0.02)
        self.assertEqual(calls, ["quit"])

    def test_no_start_leaves_the_haptics_off_until_asked(self):
        # AppTests builds the window with start_haptics=False, which is what --no-start passes
        self.app._retry_at = 0.0
        self.app.poll()
        self.assertEqual(self.starts, [], "--no-start must not be undone by the retry in poll()")
        self.assertIn("--no-start", self.app.status_var.get())
        self.app.restart_haptics()                       # the user asks for haptics
        self.assertEqual(len(self.starts), 1)
        self.app._retry_at = 0.0
        self.app.poll()                                  # from then on a failed start is retried
        self.assertEqual(len(self.starts), 2)

    def test_master_is_saved_so_a_lowered_level_survives_a_restart(self):
        self.app.master_var.set(0.3)
        self.app._master_changed(None)
        self.assertIsNotNone(self.app._save_job, "a master change must be saved")
        self.app._save_now()
        self.assertAlmostEqual(config.load(self.path)["audio"]["master_gain"], 0.3)

    def test_a_device_that_stops_playing_is_noticed_and_retried(self):
        class Silent:
            running = True
            stopped = False
            audio = type("Audio", (), {"device_name": "Speakers (ButtKicker PRO)"})()

            def audio_lost(self):
                return True

            def stop(self):
                self.stopped, self.running = True, False

        rt = Silent()
        self.app.rt = rt
        self.app.poll()
        self.assertTrue(rt.stopped)
        self.assertIsNone(self.app.rt)
        self.assertIn("stopped playing", self.app.start_error)
        self.assertLessEqual(self.app._retry_at - time.monotonic(), 3.5, "retried within seconds")
        self.assertEqual(self.app._retry_interval(), self.gui.LOST_RETRY_SECONDS, "and keeps retrying fast")


class PackagingTests(unittest.TestCase):
    """The installed app: bundled files, the settings folder, the startup entry, the installer."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved_home = os.environ.get("OPENSHAKER_HOME")
        os.environ["OPENSHAKER_HOME"] = str(self.tmp / "home")
        self.addCleanup(lambda: os.environ.__setitem__("OPENSHAKER_HOME", saved_home) if saved_home is not None
                        else os.environ.pop("OPENSHAKER_HOME", None))
        self.reg = fake_registry(self)                                  # never the real registry

    def test_user_data_lives_in_the_settings_folder(self):
        from openshaker import paths
        self.assertEqual(paths.config_path(), self.tmp / "home" / "config.json")
        self.assertTrue(paths.log_dir().is_dir())
        self.assertEqual(paths.RESOURCE_DIR, ROOT)

    def test_an_old_config_is_copied_once_and_never_overwritten(self):
        from openshaker import paths
        old = self.tmp / "old" / "config.json"
        old.parent.mkdir()
        old.write_text('{"audio": {"device": "Line Out"}}', encoding="utf-8")
        self.assertEqual(paths.migrate_config(candidates=[self.tmp / "missing.json", old]), old)
        old.write_text('{"audio": {"device": "changed"}}', encoding="utf-8")
        self.assertIsNone(paths.migrate_config(candidates=[old]))
        self.assertEqual(json.loads(paths.config_path().read_text(encoding="utf-8"))["audio"]["device"], "Line Out")

    def test_the_old_startup_entry_leads_to_the_old_config_and_is_replaced(self):
        from openshaker import paths
        folder = self.tmp / "bk_haptics"
        folder.mkdir()
        with autostart._open(write=True) as key:
            self.reg.SetValueEx(key, "ButtKicker Haptics", 0, self.reg.REG_SZ,
                              '"C:\\env\\pythonw.exe" "' + str(folder / "launch.pyw") + '" --hidden')
        self.assertIn(folder / "config.json", paths.legacy_configs())
        self.assertTrue(autostart.migrate_legacy())
        self.assertIsNone(autostart.value("ButtKicker Haptics"))
        self.assertTrue(autostart.is_current(), "exactly one entry, for this copy of the app")
        self.assertFalse(autostart.migrate_legacy())

    def test_the_frozen_app_uses_its_bundle_and_its_exe(self):
        from openshaker import paths
        bundle = self.tmp / "OpenShaker" / "_internal"
        bundle.mkdir(parents=True)
        had = {k: hasattr(sys, k) for k in ("frozen", "_MEIPASS")}
        saved = {k: getattr(sys, k, None) for k in had}
        sys.frozen, sys._MEIPASS = True, str(bundle)
        try:
            self.assertEqual(paths.resource_dir(), bundle)
            cmd = autostart.command()
            self.assertTrue(cmd.startswith(f'"{Path(sys.executable).resolve()}"'), cmd)
            self.assertTrue(cmd.endswith(" --hidden"), cmd)
            self.assertFalse(autostart.launcher_is_stub())
            self.assertIsNone(autostart.repair_launcher())
        finally:
            for k in had:
                if had[k]:
                    setattr(sys, k, saved[k])
                elif hasattr(sys, k):
                    delattr(sys, k)

    def test_profiles_chosen_from_the_settings_folder_are_saved_relative(self):
        cfg = config.load(self.tmp / "home" / "config.json")
        prof = ROOT / "profiles" / "forza_motorsport" / "profile.json"
        self.assertEqual(config.relative_profile(cfg, prof), "profiles/forza_motorsport/profile.json")

    def test_installer_and_build_match_the_app(self):
        iss = (ROOT / "installer" / "OpenShaker.iss").read_text(encoding="utf-8")
        self.assertEqual(APP_NAME, "OpenShaker")
        self.assertIn(f'#define AppName "{APP_NAME}"', iss)
        self.assertIn(f"AppMutex={single_instance.MUTEX_NAME}", iss)
        self.assertIn("PrivilegesRequired=lowest", iss)
        self.assertIn("\nAppPublisher=baddo & Claude\n", iss.replace("\r\n", "\n"), "published by the maintainer and Claude")
        # one screen, one click (the maintainer: "just a double click away from being set up"): the Tasks page
        # with both boxes ticked and an Install button, then setup closes and starts the app
        for page in ("Welcome", "Dir", "ProgramGroup", "Ready", "Finished"):
            self.assertIn(f"Disable{page}Page=yes", iss)
        self.assertIn("\n[Messages]\n", iss.replace("\r\n", "\n"))
        self.assertIn("\nButtonNext=&Install\n", iss.replace("\r\n", "\n"), "the one page's button says Install")
        self.assertIn("\nSelectTasksLabel2=Select the additional tasks you would like Setup to perform while installing "
                      "[name], then click Install.\n", iss.replace("\r\n", "\n"), "and the text above it agrees")
        tasks = re.search(r"^\[Tasks\]\n(.*?)\n\n", iss.replace("\r\n", "\n"), re.S | re.M).group(1)
        task_lines = [line for line in tasks.splitlines() if line.startswith("Name:")]
        self.assertEqual([re.search(r'Name: "(\w+)"', line).group(1) for line in task_lines], ["startup", "desktopicon"])
        self.assertFalse([line for line in task_lines if "unchecked" in line], "both boxes ticked by default")
        run = re.search(r"^\[Run\]\n(.*?)(\n\n|\Z)", iss.replace("\r\n", "\n"), re.S | re.M).group(1)
        run_line = next(line for line in run.splitlines() if line.startswith("Filename:"))
        self.assertNotIn("postinstall", run_line, "no Finished page to tick: the app starts by itself")
        self.assertIn("skipifsilent", run_line, "an interactive install opens the window")
        relaunch = [line for line in run.splitlines() if "RelaunchAfterSilentUpdate" in line]
        self.assertEqual(len(relaunch), 2, "a silent update puts the app back it stopped")
        tray_back = next(line for line in relaunch if "RelaunchAfterSilentUpdate(False)" in line)
        window_back = next(line for line in relaunch if "RelaunchAfterSilentUpdate(True)" in line)
        self.assertIn('Parameters: "--hidden"', tray_back, "into the tray, not a window")
        self.assertNotIn("--hidden", window_back, "the app's own Update now from the window brings the window back")
        self.assertIn(f"CheckForMutexes('{single_instance.MUTEX_NAME}')", iss, "only if it was running")
        self.assertIn("Result := WizardSilent and WasRunning and ((ExpandConstant('{param:SHOWWINDOW|0}') = '1') "
                      "= WithWindow);", iss)
        from openshaker import updater
        self.assertIn("/SHOWWINDOW=1", updater.installer_command(Path("x.exe"), True), "the app passes what setup reads")
        # the app's Update now: one setup at a time; a silent update keeps the user's current Start with
        # Windows and desktop shortcut; a failed one starts the old version again and says so
        self.assertIn("\nSetupMutex=OpenShakerSetup\n", iss.replace("\r\n", "\n"))
        self.assertIn("Tasks: startup; Check: KeepStartup", iss)
        self.assertIn("Tasks: desktopicon; Check: KeepDesktopIcon", iss)
        self.assertIn("Result := WizardSilent and (InstalledExe() <> '');", iss)
        self.assertIn("UpdateInstalled := True;", iss)
        # setup that quit the app and then stopped (a failed update, a cancelled install) starts it again once
        # it has let go of its mutex; after a silent update it says why, with the flags main() reads
        text = iss.replace("\r\n", "\n")
        deinit = re.search(r"^procedure DeinitializeSetup\(\);\n(.*?)^end;", text, re.S | re.M).group(1)
        self.assertIn(f"while CheckForMutexes('{single_instance.MUTEX_NAME}') and (Waited < 30000) do", deinit)
        self.assertIn("  if CurStep = ssInstall then\n    FilesStarted := True;", text)
        from openshaker import gui
        for flag, how in (("--update-failed", "failed"), ("--update-incomplete", "incomplete")):
            self.assertIn(f"Params := '{flag}={{#AppVersion}}'", deinit)
            self.assertEqual(gui.installer_result([f"{flag}=1.0.2"]), (how, "1.0.2"))
        # an interactive install over an installed copy starts its ticks from what is there now, and an
        # unticked box removes its entry
        self.assertIn("if (CurPageID = wpSelectTasks) and (not TasksFromNow) and (InstalledExe() <> '') then", text)
        for task in ("startup", "desktopicon"):
            self.assertIn(f"WizardSelectTasks('!{task}')", text)
            self.assertIn(f"if not WizardIsTaskSelected('{task}') then", text)
        # the build writes the .sha256 asset the updater verifies against, and bundles what HTTPS needs
        build = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn('[IO.File]::WriteAllText("$setup.sha256", "$hash  OpenShaker-Setup-$version.exe`n", '
                      '[Text.Encoding]::ASCII)', build)
        for part in ("_internal\\_ssl.pyd", "_internal\\libssl-3.dll", "_internal\\libcrypto-3.dll"):
            self.assertIn(part, build)
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2026 baddo\n", license_text.replace("\r\n", "\n"),
                      "the copyright holder is the maintainer alone (an AI cannot hold copyright)")
        for legacy in autostart.LEGACY_VALUE_NAMES:
            self.assertIn(f'ValueName: "{legacy}"', iss)
        spec = (ROOT / "installer" / "OpenShaker.spec").read_text(encoding="utf-8")
        self.assertIn("console=False", spec)
        m = re.search(r"^RUNTIME_PROFILES\s*=\s*(\(.*?\))", spec, re.M)
        self.assertIsNotNone(m, "the spec lists the bundled profiles")
        bundled = ast.literal_eval(m.group(1))
        self.assertEqual(set(bundled), set(SHIPPED_PROFILES))
        for game, prof in config.DEFAULTS["profiles"].items():
            self.assertIn(config.profile_folder(prof), bundled, f"{game}'s profile is not in the installer")
        self.assertTrue((ROOT / "openshaker" / "app.pyw").exists())


class AudioLossTests(unittest.TestCase):
    def test_alive_follows_the_stream(self):
        out = AudioOutput()
        self.assertFalse(out.alive, "no stream yet")

        class Stream:
            active = True

        out.stream = Stream()
        self.addCleanup(setattr, out, "stream", None)
        out.last_callback = time.monotonic()
        self.assertTrue(out.alive)
        out.last_callback -= 5.0
        self.assertFalse(out.alive, "no audio callbacks for seconds: the device went away")
        out.last_callback = time.monotonic()
        out.finished = True
        self.assertFalse(out.alive, "PortAudio finished the stream")
        out.finished, out.stream.active = False, False
        self.assertFalse(out.alive, "the stream is no longer active")

    def test_runtime_reports_a_lost_device_only_while_running(self):
        from openshaker.runtime import Runtime
        rt = Runtime(config.load(None))
        rt.audio = AudioOutput()
        self.assertFalse(rt.audio_lost(), "not running yet")
        rt.running = True
        self.addCleanup(setattr, rt, "running", False)
        self.assertTrue(rt.audio_lost())
        rt.no_audio = True
        self.assertFalse(rt.audio_lost(), "rendering without a device cannot lose one")


class StartupFailureTests(unittest.TestCase):
    def test_a_launch_that_can_neither_start_nor_reach_the_running_copy_says_why(self):
        from openshaker import gui
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        saved_home = os.environ.get("OPENSHAKER_HOME")
        os.environ["OPENSHAKER_HOME"] = str(tmp)
        self.addCleanup(lambda: os.environ.__setitem__("OPENSHAKER_HOME", saved_home) if saved_home is not None
                        else os.environ.pop("OPENSHAKER_HOME", None))
        shown = []
        for obj, name, value in ((single_instance, "acquire", lambda: None),
                                 (single_instance, "signal_existing", lambda timeout=2.0: False),
                                 (gui.messagebox, "showerror", lambda *a, **k: shown.append(a))):
            self.addCleanup(setattr, obj, name, getattr(obj, name))
            setattr(obj, name, value)
        self.assertEqual(gui.main([]), 1)
        log = (tmp / "logs" / "gui_error.log").read_text(encoding="utf-8")
        self.assertIn("does not answer", log)
        self.assertEqual(len(shown), 1, "the reason is shown, not swallowed")


if __name__ == "__main__":
    unittest.main()
