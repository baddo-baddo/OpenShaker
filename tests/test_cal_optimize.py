"""The calibration scorer's safety nets: render-cache keys, seeded renders, bound refusal, --apply backups."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openshaker import config, optimize as O                   # noqa: E402
from openshaker.compare import render_offline                   # noqa: E402
from openshaker.telemetry import Telemetry                      # noqa: E402


class CacheKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_code_version_follows_the_rendering_code_but_not_line_endings(self):
        (self.tmp / "effects").mkdir()
        (self.tmp / "engine.py").write_bytes(b"a = 1\nb = 2\n")
        (self.tmp / "effects" / "racing.py").write_bytes(b"x = 1\n")
        v1 = O.code_version(self.tmp)
        (self.tmp / "engine.py").write_bytes(b"a = 1\r\nb = 2\r\n")
        self.assertEqual(O.code_version(self.tmp), v1)
        (self.tmp / "effects" / "racing.py").write_bytes(b"x = 2\n")
        self.assertNotEqual(O.code_version(self.tmp), v1)
        self.assertEqual(O.code_version(), O.code_version())        # the real package, cached

    def test_the_render_cache_lives_outside_the_project_unless_overridden(self):
        from unittest import mock
        with mock.patch.dict("os.environ", {O.CACHE_ENV: ""}):
            d = O.default_cache_dir()
            self.assertNotIn(ROOT.resolve(), d.resolve().parents)
            self.assertEqual(d.parts[-2:], ("openshaker", "renders"))
        with mock.patch.dict("os.environ", {O.CACHE_ENV: str(self.tmp / "renders")}):
            self.assertEqual(O.default_cache_dir(), self.tmp / "renders")

    def test_seed_and_code_are_part_of_the_key(self):
        prof = self.tmp / "p.json"
        prof.write_text("{}", encoding="utf-8")
        keys = {O.cache_key(self.tmp, prof, "gear_shift", None, s) for s in (None, 1, 2)}
        self.assertEqual(len(keys), 3)
        self.assertEqual(O.cache_key(self.tmp, prof, "gear_shift", None, 1),
                         O.cache_key(self.tmp, prof, "gear_shift", None, 1))


class SeededRenderTests(unittest.TestCase):
    def test_same_seed_same_render(self):
        frames = []
        for i in range(300):                                        # 3 s, a gear change every 0.25 s
            t = Telemetry(active=True, rpm=4000.0, gear=1 + (i // 25) % 4, speed=20.0)
            t.t = i * 0.01
            frames.append(t)

        def render(seed):
            cfg = config.load(None)                  # a randomly pitched shift, whatever the shipped profile uses
            cfg["effects"]["gear_shift"].update({
                "template": {"shape": "square", "freq": 34.0, "duration": 0.085, "attack": 0.002, "release": 0.003},
                "pitch_jitter": [0.8, 2.3], "gain": 0.6, "cooldown": 0.05})
            cfg["effects"]["gear_shift"].pop("pitch_hz_per_rpm", None)
            return render_offline(frames, 3.0, cfg, ["gear_shift"], seed=seed)
        a, b, c = render(3), render(3), render(4)
        self.assertGreater(float(np.abs(a).max()), 0.05)
        self.assertTrue(np.array_equal(a, b))
        self.assertFalse(np.array_equal(a, c))


class UnitRenderTests(unittest.TestCase):
    def test_unit_renders_skip_the_output_limiter(self):
        """An effect whose unit-gain output would pass the limiter knee is rendered at its real gain and scaled back."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        prof = tmp / "p.json"
        prof.write_text(json.dumps({"effects": {"engine": {"gain": 0.2, "harmonic": 0.0,
                                                           "curve": [[500, 50.0, 1.5], [9000, 50.0, 1.5]]}}}),
                        encoding="utf-8")
        frames = []
        for i in range(200):
            t = Telemetry(active=True, engine_running=True, rpm=3000.0, speed=10.0)
            t.t = i * 0.01
            frames.append(t)
        old = O.CACHE
        O.CACHE = tmp / "cache"
        try:
            y = O.cached_render(tmp, prof, "engine", 48000, 2.0, frames, None)
        finally:
            O.CACHE = old
        self.assertGreater(float(np.abs(y[48000:]).max()), 1.4)     # 1.5 amplitude intact (the limiter caps near 1.0)

    def test_an_effect_that_reaches_the_limiter_at_its_own_gain_is_still_rendered_linearly(self):
        """A one-shot loud enough to hit the knee alone: the cached render must not carry the limiter's bend."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        curve = [[500, 50.0, 1.3], [9000, 50.0, 1.3]]
        loud, quiet = tmp / "loud.json", tmp / "quiet.json"
        loud.write_text(json.dumps({"effects": {"engine": {"gain": 1.0, "harmonic": 0.0, "curve": curve}}}), encoding="utf-8")
        quiet.write_text(json.dumps({"effects": {"engine": {"gain": 0.1, "harmonic": 0.0, "curve": curve}}}), encoding="utf-8")
        frames = []
        for i in range(200):
            t = Telemetry(active=True, engine_running=True, rpm=3000.0, speed=10.0)
            t.t = i * 0.01
            frames.append(t)
        old = O.CACHE
        O.CACHE = tmp / "cache"
        try:
            hot = O.cached_render(tmp, loud, "engine", 48000, 2.0, frames, None)      # 1.3 > the 0.9 knee
            cold = O.cached_render(tmp, quiet, "engine", 48000, 2.0, frames, None)    # 0.13, never limited
        finally:
            O.CACHE = old
        self.assertAlmostEqual(float(np.abs(hot[48000:]).max()), 1.3, delta=0.02)
        self.assertAlmostEqual(float(np.abs(hot[48000:]).max()), float(np.abs(cold[48000:]).max()), delta=0.02)


class FullMixReportTests(unittest.TestCase):
    """report_full scores the profile as the app plays it (one engine, output limiter included)."""

    def session(self, tmp: Path, engine_amp: float, pulse_s: float = 0.0, hc_delay_s: float = 0.0,
                hc_gap=None) -> "O.Session":
        """A 3 s pair: our engine tone from telemetry, HaptiConnect's the same 50 Hz tone at 0.3. With pulse_s the
        engine switches on and off every pulse_s on both sides, HaptiConnect's copy hc_delay_s later."""
        import csv
        from openshaker.drivelog import CSV_FIELDS
        from openshaker.record import write_wav
        pair = tmp / f"pair_{engine_amp}_{pulse_s}_{hc_delay_s}_{hc_gap}"
        pair.mkdir()
        sr, secs = 48000, 3.0
        t = np.arange(int(sr * secs)) / sr
        on = lambda tt: np.ones_like(tt, bool) if not pulse_s else (np.floor(tt / pulse_s) % 2 == 0)
        hc = 0.3 * np.sin(2 * np.pi * 50.0 * t) * on(t - hc_delay_s) * (t >= hc_delay_s)
        if hc_gap:                                                        # a HaptiConnect dropout: exact zeros
            hc[int(hc_gap[0] * sr):int(hc_gap[1] * sr)] = 0.0
        write_wav(pair / "audio.wav", np.stack([hc, np.zeros_like(hc)], 1).astype(np.float32), sr)
        with (pair / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for i in range(int(secs * 100)):
                row = {k: 0 for k in CSV_FIELDS}
                running = int(bool(on(np.array([i * 0.01]))[0]))
                row.update(t=i * 0.01, source="forza", active=1, engine_running=running, rpm=3000, max_rpm=8000,
                           idle_rpm=800, gear=3, speed=20.0, raw_hex="")
                w.writerow(row)
        prof = tmp / f"p_{engine_amp}.json"
        prof.write_text(json.dumps({"effects": {"engine": {"gain": 1.0, "harmonic": 0.0, "amp_throttle": 0.0,
                                                           "curve": [[500, 50.0, engine_amp], [9000, 50.0, engine_amp]]}}}),
                        encoding="utf-8")
        s = O.Session(pair, prof, ["engine"], None, seed=1)
        s.set_lag({"engine": 1.0})
        return s

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old_cache, O.CACHE = O.CACHE, self.tmp / "cache"
        self.addCleanup(setattr, O, "CACHE", self.old_cache)

    def test_it_equals_the_per_effect_report_while_the_limiter_is_idle(self):
        s = self.session(self.tmp, 0.3)
        a, b = s.report({"engine": 1.0}), s.report_full()
        self.assertAlmostEqual(a["level_db"], b["level_db"], delta=0.1)
        self.assertAlmostEqual(a["dist_db"], b["dist_db"], delta=0.1)

    def test_the_lag_search_resolves_haptic_connects_delay_to_a_few_ms(self):
        """HaptiConnect answers ~87 ms late; a 50 ms frame grid could only say 50 or 100."""
        s = self.session(self.tmp, 0.3, pulse_s=0.3, hc_delay_s=0.087)
        self.assertAlmostEqual(s.lag_ms, 87.0, delta=7.5)
        self.assertEqual(s.lag, 0)                                          # the shift is inside the renders
        again = s.lag_ms
        s.set_lag({"engine": 1.0})                                          # calling it twice does not shift twice
        self.assertEqual(s.lag_ms, again)

    def test_haptic_connects_own_dropouts_are_not_scored(self):
        """Frames where HaptiConnect's recording sits on exact zeros are its faults, not a quiet effect."""
        clean = self.session(self.tmp, 0.3)
        gap = self.session(self.tmp, 0.3, hc_gap=(1.0, 2.0))
        self.assertEqual(clean.hc_silent_share, 0.0)
        self.assertGreater(gap.hc_silent_share, 0.3)
        self.assertAlmostEqual(gap.report({"engine": 1.0})["level_db"], clean.report({"engine": 1.0})["level_db"], delta=0.3)
        self.assertAlmostEqual(gap.report_full()["level_db"], 0.0, delta=0.3)

    def test_it_shows_the_limiter_the_per_effect_sum_cannot(self):
        s = self.session(self.tmp, 2.0)                                     # far past the 0.985 ceiling
        linear, full = s.report({"engine": 1.0}), s.report_full()
        self.assertGreater(linear["level_db"] - full["level_db"], 3.0)     # the limiter holds the real mix down
        self.assertAlmostEqual(full["level_db"], 20 * np.log10(0.985 / 0.3), delta=0.6)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_gains_on_the_bound_are_named(self):
        start = {"abs": 0.25, "engine": 0.175, "road": 1.0}
        self.assertEqual(O.on_bound(start, {"abs": 2.5, "engine": 0.16, "road": 1.0}, set()), ["abs"])
        self.assertEqual(O.on_bound(start, {"abs": 0.025, "engine": 0.16, "road": 1.0}, set()), ["abs"])
        self.assertEqual(O.on_bound(start, {"abs": 2.5, "engine": 0.16, "road": 1.0}, {"abs"}), [])
        self.assertEqual(O.on_bound(start, {"abs": 1.0, "engine": 0.5, "road": 3.0}, set()), [])

    def test_apply_keeps_a_backup_and_writes_portable_paths(self):
        prof = self.tmp / "cand" / "profile_x.json"
        prof.parent.mkdir()
        old = {"effects": {"engine": {"gain": 0.175}}, "meta": {}}
        prof.write_text(json.dumps(old), encoding="utf-8")
        data = json.loads(prof.read_text(encoding="utf-8"))
        backup = O.apply_gains(prof, data, {"engine": 0.1646}, [ROOT / "sessions" / "fm_drive_1_hc",
                                                                  Path("D:/archive/old_runs/fm_drive_9_hc")],
                               2.0, backups=self.tmp / "bk")
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), old)
        new = json.loads(prof.read_text(encoding="utf-8"))
        self.assertEqual(new["effects"]["engine"]["gain"], 0.1646)
        self.assertEqual(new["meta"]["optimized_on"], ["sessions/fm_drive_1_hc", "old_runs/fm_drive_9_hc"])
        self.assertNotIn(":", json.dumps(new["meta"]["optimized_on"]))


class AceScaleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def pair(self, name, drive_meta):
        drive = self.tmp / name
        drive.mkdir()
        if drive_meta is not None:
            (drive / "meta.json").write_text(json.dumps(drive_meta), encoding="utf-8")
        hc = self.tmp / f"{name}_hc"
        hc.mkdir()
        (hc / "meta.json").write_text(json.dumps({"replayed_from": str(drive)}), encoding="utf-8")
        return hc

    def test_the_scale_comes_from_the_drive_meta_for_ace_only(self):
        self.assertEqual(O.logged_susp_scale(self.pair("ace_drive_7", {"frames_by_source": {"ace": 900},
                                                                       "ace_susp_scale_m": 0.08})), 0.08)
        self.assertIsNone(O.logged_susp_scale(self.pair("fm_drive_7", {"frames_by_source": {"forza": 900},
                                                                       "ace_susp_scale_m": 0.08})))
        self.assertEqual(O.logged_susp_scale(self.pair("ace_drive_2", {"note": "old log"})), 0.05)
        self.assertIsNone(O.logged_susp_scale(self.pair("fm_drive_3", None)))


if __name__ == "__main__":
    unittest.main()
