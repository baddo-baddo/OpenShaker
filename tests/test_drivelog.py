"""The drive log streams to disk, the log format has one home, and offline renders can be repeated."""
import csv
import shutil
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker import config, drivelog                                  # noqa: E402
from openshaker.drivelog import DriveLogWriter                            # noqa: E402
from openshaker.engine import HapticEngine                                # noqa: E402
from openshaker.runtime import WavCapture                                 # noqa: E402
from openshaker.telemetry import Telemetry                                # noqa: E402


class DriveLogTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def rows(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.reader(f))[1:]

    def test_record_still_offers_the_shared_format(self):
        from openshaker import record
        self.assertIs(record.CSV_FIELDS, drivelog.CSV_FIELDS)
        self.assertIs(record.tele_row, drivelog.tele_row)
        self.assertIs(record.TelemetryLog, drivelog.TelemetryLog)

    def test_frames_reach_the_disk_while_the_drive_runs(self):
        path = self.dir / "telemetry.csv"
        log = DriveLogWriter(path)
        log.FLUSH_S = 0.0
        log(Telemetry(source="forza", t=10.0))
        self.assertEqual(self.rows(path), [], "held until the audio starts")
        log.begin(9.5)
        log(Telemetry(source="forza", t=10.5))
        rows = self.rows(path)                           # read while the writer still has it open
        self.assertEqual([r[0] for r in rows], ["0.5000", "1.0000"])
        self.assertEqual(log.counts(), {"forza": 2})
        self.assertEqual(len(log), 2)
        log.close()
        log(Telemetry(source="forza", t=11.0))           # a late frame after close is dropped
        self.assertEqual(len(self.rows(path)), 2)

    def test_a_drive_stopped_before_the_audio_started_keeps_its_frames(self):
        path = self.dir / "telemetry.csv"
        log = DriveLogWriter(path)
        log(Telemetry(source="ace", t=3.0))
        log(Telemetry(source="ace", t=3.25))
        log.close()
        self.assertEqual([r[0] for r in self.rows(path)], ["0.0000", "0.2500"])

    def test_the_wav_is_valid_before_it_is_closed(self):
        path = self.dir / "ours.wav"
        cap = WavCapture(str(path), 48000)
        cap(np.full(480, 0.5, dtype=np.float32))
        cap(np.zeros(480, dtype=np.float32))
        cap._drain()
        with wave.open(str(path)) as w:                  # what a killed run would leave behind
            self.assertEqual(w.getnframes(), 960)
        cap(np.full(480, -0.5, dtype=np.float32))
        cap._drain()
        with wave.open(str(path)) as w:                  # the header follows every write
            self.assertEqual(w.getnframes(), 1440)
        self.assertAlmostEqual(cap.close(), 1440 / 48000)
        with wave.open(str(path)) as w:
            self.assertEqual(w.getnframes(), 1440)


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(None)
        self.cfg["effects"].setdefault("gear_shift", {}).update({
            "enabled": True, "gain": 1.0, "pitch_jitter": [0.8, 2.3],
            "template": {"shape": "square", "freq": 34.0, "duration": 0.085, "attack": 0.002, "release": 0.003}})

    def shifts(self, seed):
        engine = HapticEngine(self.cfg, 48000, [], seed=seed)
        gear = next(e for e in engine.effects if e.name == "gear_shift")
        out = []
        for _ in range(6):
            gear.fire(40.0, 1.0, 0.05)
            out.append(gear.render_shots(4800))
        return np.concatenate(out)

    def test_the_same_seed_renders_the_same_shifts(self):
        np.testing.assert_array_equal(self.shifts(7), self.shifts(7))
        self.assertFalse(np.array_equal(self.shifts(7), self.shifts(8)))

    def test_live_play_is_not_seeded(self):
        engine = HapticEngine(self.cfg, 48000, [])
        gear = next(e for e in engine.effects if e.name == "gear_shift")
        self.assertIsNone(gear.rng)


if __name__ == "__main__":
    unittest.main()
