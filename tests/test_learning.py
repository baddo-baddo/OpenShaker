"""Regression tests for the calibration pipeline: synthesize a known session, learn it back."""
from __future__ import annotations

import csv
import json
import math
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from openshaker import config
from openshaker.analyze import analyze
from openshaker.effects.racing import EngineEffect, GearShiftEffect
from openshaker.record import CSV_FIELDS, tele_row, write_wav
from openshaker.telemetry import Telemetry

SR = 48000


def true_freq(rpm: float) -> float:
    return 20.0 + 0.008 * rpm          # 28 Hz at 1000 rpm ... 76 Hz at 7000 rpm


def make_session(folder: Path, seconds: float = 30.0) -> None:
    """Engine tone following a known rpm curve + one 40 Hz thump per gear change."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    rpm_t = 1000.0 + 6000.0 * (0.5 - 0.5 * np.cos(2 * math.pi * t / 10.0))     # sweeps 1000..7000 every 10 s
    phase = np.cumsum(2 * math.pi * true_freq(rpm_t) / SR)
    audio = 0.25 * np.sin(phase)
    rows = []
    gear, last_shift = 1, -1.0
    shift_times = []
    for k in range(int(seconds * 60)):          # 60 Hz telemetry
        tt = k / 60.0
        rpm = float(1000.0 + 6000.0 * (0.5 - 0.5 * math.cos(2 * math.pi * tt / 10.0)))
        if tt - last_shift > 1.0 and 4.0 < (tt % 10.0) < 6.0 and rpm > 6500:
            gear += 1
            last_shift = tt
            shift_times.append(tt)
        tele = Telemetry(active=True, engine_running=True, rpm=rpm, max_rpm=7000.0, idle_rpm=1000.0, gear=gear,
                         speed=20.0, throttle=0.5)
        tele.t = tt
        tele.source = "test"
        tele.seq = k
        rows.append(tele)
    for ts in shift_times:                    # thump 20 ms after the packet, 0.6 peak, 60 ms decay
        i0 = int((ts + 0.02) * SR)
        tau = 0.06
        seg_t = np.arange(int(0.4 * SR)) / SR
        thump = 0.6 * np.exp(-seg_t / tau) * np.sin(2 * math.pi * 40.0 * seg_t)
        audio[i0:i0 + len(thump)] += thump[: max(0, min(len(thump), n - i0))]
    write_wav(folder / "audio.wav", audio[:, None].astype(np.float32), SR)
    with (folder / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        for tele in rows:
            w.writerow(tele_row(tele, 0.0))
    (folder / "meta.json").write_text(json.dumps({"note": "synthetic"}), encoding="utf-8")


class LearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.session = Path(cls.tmp.name) / "session"
        cls.session.mkdir()
        make_session(cls.session)
        cls.out = Path(cls.tmp.name) / "profile"
        cls.profile = analyze(cls.session, cls.out, plots=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_engine_curve_recovered(self):
        eng = self.profile["effects"]["engine"]
        errors = [abs(freq - true_freq(rpm)) for rpm, freq, _amp in eng["curve"]]
        self.assertGreaterEqual(len(eng["curve"]), 8)
        self.assertLess(max(errors), 2.0, f"frequency errors too large: {errors}")
        amps = [amp for _rpm, _freq, amp in eng["curve"]]
        self.assertTrue(all(0.18 < a < 0.32 for a in amps), amps)   # true peak amplitude 0.25

    def test_gear_shift_template_recovered(self):
        gs = self.profile["effects"]["gear_shift"]
        self.assertTrue((self.out / gs["sample"]).exists())
        info = self.profile["analysis"]["gear_shift"]
        self.assertGreaterEqual(info["count"], 3)
        self.assertGreater(info["peak"], 0.5)
        self.assertLess(info["duration"], 0.3)

    def test_profile_drives_effects(self):
        cfg = config.load(None)
        config.apply_profile(cfg, self.out / "profile.json")
        eng = EngineEffect(cfg["effects"]["engine"], SR)
        self.assertIsNotNone(eng.curve)
        tele = Telemetry(active=True, engine_running=True, rpm=4000.0, max_rpm=7000.0, throttle=0.0)
        y = np.concatenate([eng.render(4800, tele) for _ in range(3)])
        spec = np.abs(np.fft.rfft(y[4800:] * np.hanning(len(y) - 4800)))
        f_peak = np.fft.rfftfreq(len(y) - 4800, 1 / SR)[np.argmax(spec)]
        self.assertAlmostEqual(f_peak, true_freq(4000.0), delta=2.5)

        gs = GearShiftEffect(cfg["effects"]["gear_shift"], SR)
        self.assertIsNotNone(gs.sample)
        prev = Telemetry(active=True, gear=2)
        prev.t = time.perf_counter()
        cur = Telemetry(active=True, gear=3)
        cur.t = prev.t + 0.016
        gs.on_frame(cur, prev, 0.016)
        out = gs.render(2400, cur)
        self.assertIsNotNone(out)
        self.assertGreater(float(np.max(np.abs(out))), 0.2)


if __name__ == "__main__":
    unittest.main()
