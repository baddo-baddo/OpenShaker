"""compare.load_frames: what the offline renders see of a drive log."""
import csv
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.compare import load_frames                      # noqa: E402
from openshaker.drivelog import CSV_FIELDS, tele_row            # noqa: E402
from openshaker.telemetry import Telemetry                      # noqa: E402


class LoadFramesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, source: str) -> Path:
        p = self.tmp / f"{source}.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_FIELDS)
            t = Telemetry(active=True, rpm=4000.0, speed=30.0, kerb_vib=0.4, slip_vib=0.2, road_vib=0.1, abs_vib=0.3)
            t.t, t.source = 1.0, source
            w.writerow(tele_row(t, 0.0))
        return p

    def test_ace_vibration_hints_reach_the_offline_render(self):
        for source in ("ace", "replay_ace"):
            f = load_frames(self.write(source))[0]
            self.assertTrue(f.has_vib_hints, source)
            self.assertAlmostEqual(f.kerb_vib, 0.4)
            self.assertAlmostEqual(f.slip_vib, 0.2)
            self.assertAlmostEqual(f.road_vib, 0.1)
            self.assertAlmostEqual(f.abs_vib, 0.3)

    def test_other_logs_have_no_hints(self):
        for source in ("forza", "replay", "beamng"):
            f = load_frames(self.write(source))[0]
            self.assertFalse(f.has_vib_hints, source)
            self.assertEqual(f.kerb_vib, 0.0)

    def write_rows(self, rows) -> Path:
        """rows: (source, gear, raw bytes or a raw hex string)."""
        p = self.tmp / "rows.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_FIELDS)
            for i, (source, gear, raw) in enumerate(rows):
                t = Telemetry(active=True, rpm=4000.0, speed=30.0, gear=gear)
                t.t, t.source = i * 0.01, source
                row = tele_row(t, 0.0)
                row[-1] = raw.hex() if isinstance(raw, (bytes, bytearray)) else raw
                w.writerow(row)
        return p

    @staticmethod
    def forza_packet(size: int, packet_ms: int, travel_m) -> bytes:
        import struct
        b = bytearray(size)
        struct.pack_into("<iI", b, 0, 1, packet_ms)
        struct.pack_into("<3f", b, 8, 8000.0, 900.0, 4000.0)
        struct.pack_into("<4f", b, 196, *travel_m)                  # SuspensionTravelMeters
        return bytes(b)

    def test_forza_packets_give_the_offline_render_metres_and_the_packet_clock(self):
        """The live source reads SuspensionTravelMeters and TimestampMS from the packet; the CSV has no column."""
        rows = [("forza", 3, self.forza_packet(size, 1000 + 16 * i, [0.01 * (i + 1), -0.02, 0.03, 0.0]))
                for i, size in enumerate((331, 324))]
        frames = load_frames(self.write_rows(rows))
        for i, f in enumerate(frames):
            self.assertEqual(f.packet_ms, 1000 + 16 * i)
            self.assertEqual([round(x, 4) for x in f.susp_travel_m], [round(0.01 * (i + 1), 4), -0.02, 0.03, 0.0])

    def test_ace_pages_give_metres_and_other_raw_data_changes_nothing(self):
        import struct
        page = bytearray(800)
        struct.pack_into("<4f", page, 184, 0.021, -0.034, 0.0, 0.05)  # suspensionTravel, as sources/ace reads it
        rows = [("ace", 2, bytes(page)), ("beamng", 2, bytes(96)), ("forza", 2, "zz" * 331), ("forza", 2, "")]
        ace, beamng, damaged, empty = load_frames(self.write_rows(rows))
        self.assertEqual([round(x, 3) for x in ace.susp_travel_m], [0.021, 0.034, 0.0, 0.05])
        for f in (beamng, damaged, empty):
            self.assertEqual(f.susp_travel_m, [0.0] * 4)
            self.assertIsNone(f.packet_ms)

    def test_the_first_forza_logs_neutral_byte_reads_as_neutral(self):
        frames = load_frames(self.write_rows([("forza", 11, ""), ("replay", 11, ""), ("forza", 4, ""), ("forza", -1, "")]))
        self.assertEqual([f.gear for f in frames], [0, 0, 4, -1])


if __name__ == "__main__":
    unittest.main()
