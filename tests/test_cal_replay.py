"""openshaker.replay without HaptiConnect: the overwrite guard, raw-packet loading and trimming."""
import contextlib
import csv
import io
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker import replay                                   # noqa: E402
from openshaker.drivelog import CSV_FIELDS, tele_row            # noqa: E402
from openshaker.forward import pack                             # noqa: E402
from openshaker.telemetry import Telemetry                      # noqa: E402


def write_drive(folder: Path, n: int = 50, raw: str | None = "motorsport", active_from: int = 10) -> None:
    folder.mkdir(parents=True)
    with (folder / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        for i in range(n):
            t = Telemetry(active=i >= active_from, rpm=3000.0 + 10 * i, gear=0 if i % 10 == 5 else 2,
                          speed=10.0, surface_rumble=[2.2, 0.0, 0.0, 0.0])
            t.t = 100.0 + i * 0.1
            t.source = "forza"
            if raw:
                t.raw = pack(t, raw)
            w.writerow(tele_row(t, 100.0))


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_an_existing_output_folder_is_never_written(self):
        write_drive(self.tmp / "fm_drive_9")
        out = self.tmp / "fm_drive_9_hc"
        out.mkdir()
        (out / "audio.wav").write_bytes(b"precious")
        from unittest import mock
        boom = mock.Mock(side_effect=AssertionError("a replay started although the output folder exists"))
        with contextlib.redirect_stdout(io.StringIO()) as said, \
                mock.patch.object(replay, "game_process_running", boom), \
                mock.patch.object(replay, "LoopbackRecorder", boom), \
                mock.patch.object(replay, "TelemetryForwarder", boom), \
                mock.patch.object(replay, "raw_frames", boom), \
                mock.patch.object(replay, "SharedPages", boom):
            self.assertEqual(replay.main([str(self.tmp / "fm_drive_9"), "--plugin", "fm"]), 1)      # default out
            self.assertEqual(replay.main([str(self.tmp / "fm_drive_9"), "--out", str(out)]), 1)
            self.assertEqual(replay.main([str(self.tmp / "fm_drive_9"), "--plugin", "ace", "--out", str(out)]), 1)
        boom.assert_not_called()
        self.assertIn("already exists", said.getvalue())
        self.assertEqual((out / "audio.wav").read_bytes(), b"precious")
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["audio.wav"])

    def test_raw_frames_keep_the_packet_and_the_true_values(self):
        write_drive(self.tmp / "d")
        frames = replay.raw_frames(self.tmp / "d")
        self.assertEqual(len(frames), 50)
        self.assertTrue(all(len(f.raw) == 324 for f in frames))
        self.assertEqual(frames[5].gear, 0)                          # neutral stays neutral
        self.assertAlmostEqual(frames[20].surface_rumble[0], 2.2, places=5)
        self.assertAlmostEqual(frames[3].t, 0.3, places=3)          # the logged time, not the parse time

    def test_logs_without_raw_packets_fall_back_to_the_columns(self):
        write_drive(self.tmp / "ace", raw=None)
        self.assertIsNone(replay.raw_frames(self.tmp / "ace"))
        write_drive(self.tmp / "sled", raw="sled")
        self.assertIsNone(replay.raw_frames(self.tmp / "sled"))

    def test_trim_keeps_two_seconds_around_the_driving(self):
        write_drive(self.tmp / "d", n=100, active_from=40)
        frames = replay.raw_frames(self.tmp / "d")
        kept = replay.trim(frames)
        self.assertAlmostEqual(kept[0].t, 2.0, places=3)             # first active 4.0 s minus 2 s
        self.assertEqual(len(replay.trim(frames, keep_all=True)), 100)


class AceSharedMemoryPageTests(unittest.TestCase):
    """The pages replay --plugin ace writes into HaptiConnect's Assetto maps (pure functions, no real memory)."""

    ROW = {"t": "1.0", "active": "1", "engine_running": "1", "rpm": "6100.0", "max_rpm": "7000", "gear": "3",
           "speed": "40.000", "throttle": "0.800", "brake": "0.100", "clutch": "1.000", "accel_lat": "-9.810",
           "accel_long": "4.905", "accel_vert": "0.981", "slip_ratio_0": "0.5000", "slip_ratio_1": "-2.0000",
           "slip_ratio_2": "0.0000", "slip_ratio_3": "1.0000", "slip_angle_0": "0.5000", "slip_angle_1": "-0.2500",
           "slip_angle_2": "0.0000", "slip_angle_3": "1.0000", "susp_travel_0": "0.5000", "susp_travel_1": "0.4000",
           "susp_travel_2": "0.6000", "susp_travel_3": "0.7000", "abs_active": "1", "tc_active": "0",
           "kerb_vib": "0.300", "slip_vib": "0.100", "road_vib": "0.050", "abs_vib": "0.200"}

    def test_a_rebuilt_page_parses_back_to_the_logged_frame(self):
        from openshaker.sources.ace import parse_physics
        page = replay.ace_physics_page(self.ROW, 7, logged_scale_m=0.05)
        self.assertEqual(len(page), 800)
        t = parse_physics(page, True, 0.05, 8000.0)
        self.assertEqual(t.gear, 3)
        self.assertAlmostEqual(t.rpm, 6100.0)
        self.assertAlmostEqual(t.speed, 40.0, places=4)
        self.assertAlmostEqual(t.throttle, 0.8, places=5)
        self.assertAlmostEqual(t.accel_lat, -9.81, places=3)
        self.assertAlmostEqual(t.accel_long, 4.905, places=3)
        self.assertEqual(t.max_rpm, 7000.0)
        for i, v in enumerate((0.5, -2.0, 0.0, 1.0)):
            self.assertAlmostEqual(t.slip_ratio[i], v, places=5)
        for i, v in enumerate((0.5, -0.25, 0.0, 1.0)):
            self.assertAlmostEqual(t.slip_angle[i], v, places=5)
        for i, v in enumerate((0.5, 0.4, 0.6, 0.7)):
            self.assertAlmostEqual(t.susp_travel[i], v, places=5)
        self.assertTrue(t.abs_active)
        self.assertFalse(t.tc_active)
        self.assertAlmostEqual(t.kerb_vib, 0.3, places=5)
        self.assertEqual(struct.unpack_from("<i", page, 0)[0], 7)

    def test_the_travel_is_written_in_metres_at_the_logged_scale(self):
        page = replay.ace_physics_page(self.ROW, 1, logged_scale_m=0.08)
        self.assertAlmostEqual(struct.unpack_from("<f", page, 184)[0], -0.04, places=6)    # 0.5 x 8 cm, ACE's sign

    def test_an_ace_log_with_raw_pages_replays_them_byte_for_byte(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        d = tmp / "ace_drive_9"
        d.mkdir()
        pages = [replay.ace_physics_page(dict(self.ROW, rpm=str(5000 + i)), i + 1, 0.08) for i in range(30)]
        with (d / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_FIELDS)
            for i, p in enumerate(pages):
                t = Telemetry(active=True, rpm=5000.0 + i, speed=40.0)
                t.t, t.source, t.raw = 10.0 + i * 0.005, "ace", p
                w.writerow(tele_row(t, 0.0))
        for packets in ("auto", "raw"):
            timeline, max_rpm, mode = replay.ace_timeline(d, packets, True)
            self.assertEqual(mode, "raw log")
            self.assertEqual([p for _, p, _ in timeline], pages)
            self.assertEqual(max_rpm, 7000)
        rebuilt, _, mode = replay.ace_timeline(d, "columns", True)      # --packets columns must really rebuild
        self.assertEqual(mode, "rebuilt")
        self.assertEqual(len(rebuilt), len(pages))
        self.assertNotEqual([p for _, p, _ in rebuilt], pages)

    def test_raw_is_refused_when_an_ace_log_has_no_raw_pages(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        d = tmp / "ace_drive_8"
        d.mkdir()
        with (d / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_FIELDS)
            for i in range(10):
                t = Telemetry(active=True, rpm=5000.0, speed=40.0)
                t.t, t.source = i * 0.005, "ace"
                w.writerow(tele_row(t, 0.0))
        self.assertEqual(replay.ace_timeline(d, "raw", True), ([], 0, None))
        self.assertEqual(replay.ace_timeline(d, "auto", True)[2], "rebuilt")
        with contextlib.redirect_stdout(io.StringIO()) as said:
            code = replay.main([str(d), "--plugin", "ace", "--packets", "raw", "--out", str(tmp / "x_hc_ace")])
        self.assertEqual(code, 1)
        self.assertIn("no raw ACE pages", said.getvalue())
        self.assertFalse((tmp / "x_hc_ace").exists())

    def test_the_static_page_version_can_be_changed_to_leave_the_competizione_plugin_out(self):
        default = replay.ace_static_page(7000, 0.16)
        other = replay.ace_static_page(7000, 0.16, sm_version="evo")
        for page, want in ((default, "1.9"), (other, "evo")):
            for key in ("smVersion", "acVersion"):
                off = replay.STATIC_OFF[key]
                self.assertEqual(page[off:off + 2 * len(want)].decode("utf-16-le"), want)
                self.assertEqual(page[off + 2 * len(want):off + 30], bytes(30 - 2 * len(want)))
        self.assertEqual(default[replay.STATIC_OFF["maxRpm"]:], other[replay.STATIC_OFF["maxRpm"]:])

    def test_static_and_graphics_pages(self):
        s = replay.ace_static_page(7000, 0.16)
        self.assertEqual(s[:6].decode("utf-16-le"), "1.9")
        self.assertEqual(struct.unpack_from("<i", s, replay.STATIC_OFF["maxRpm"])[0], 7000)
        self.assertEqual(struct.unpack_from("<4f", s, replay.STATIC_OFF["suspensionMaxTravel"]),
                         struct.unpack("<4f", struct.pack("<4f", *[0.16] * 4)))
        g = replay.ace_graphics_page(5, True)
        self.assertEqual(struct.unpack_from("<2i", g, 0), (5, 2))
        self.assertEqual(struct.unpack_from("<i", replay.ace_graphics_page(6, False), 4)[0], 0)


if __name__ == "__main__":
    unittest.main()
