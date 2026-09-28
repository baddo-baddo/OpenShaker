"""No recordings ship: one-shot templates and the kerb cycle are generated from a few numbers. Plus the
renamed profile folders and the level a stranger gets from Demo on a fresh install."""
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openshaker import config                                            # noqa: E402
from openshaker.effects import build_effects                              # noqa: E402
from openshaker.effects.base import synth_cycle, synth_template           # noqa: E402

SR = 48000
SHIPPED = ("forza_motorsport", "forza_horizon", "ace", "beamng", "trackmania")
OLD = "hapti" + "connect_"             # folder prefix before 1.0.0, spelled apart so renames cannot touch it
DEMO_PEAK_MAX_DBFS = -6.0              # Demo on a fresh install must stay well below full scale


def crest(y):
    mid = y[len(y) // 4: 3 * len(y) // 4].astype(np.float64)
    return float(np.max(np.abs(mid)) / np.sqrt(np.mean(mid ** 2)))


class SynthTemplateTests(unittest.TestCase):
    def test_length_peak_and_fades(self):
        y = synth_template(SR, freq=34.0, duration=0.085, shape="square", level=0.8)
        self.assertEqual(len(y), round(0.085 * SR))
        self.assertAlmostEqual(float(np.max(np.abs(y))), 0.8, places=4)
        self.assertLess(abs(float(y[0])), 0.05)
        self.assertLess(abs(float(y[-1])), 0.05)

    def test_each_shape_has_its_character(self):
        sine = synth_template(SR, 40.0, 0.5, "sine", attack=0.001, release=0.001)
        square = synth_template(SR, 40.0, 0.5, "square", attack=0.001, release=0.001)
        saw = synth_template(SR, 40.0, 0.5, "saw", attack=0.001, release=0.001)
        self.assertAlmostEqual(crest(sine), math.sqrt(2.0), delta=0.05)
        self.assertLess(crest(square), 1.2)
        freqs = np.fft.rfftfreq(len(sine), 1.0 / SR)

        def ratio(y, hz):
            spec = np.abs(np.fft.rfft(y))
            return spec[np.argmin(np.abs(freqs - hz))] / spec[np.argmin(np.abs(freqs - 40.0))]
        self.assertGreater(ratio(saw, 80.0), 0.3)          # a saw has even harmonics
        self.assertLess(ratio(square, 80.0), 0.05)         # a square does not
        self.assertGreater(ratio(square, 120.0), 0.25)

    def test_decay_and_harmonics(self):
        y = synth_template(SR, 45.0, 0.1, "sine", decay=0.014, harmonics=[0.4, 0.45])
        self.assertLess(np.max(np.abs(y[-2400:])), 0.1 * np.max(np.abs(y[:2400])))

    def test_an_unknown_shape_is_refused(self):
        with self.assertRaises(ValueError):
            synth_template(SR, 40.0, 0.1, "triangle")

    def test_cycle_from_harmonic_weights(self):
        cycle = synth_cycle([1.0, 0.2, 0.45])
        self.assertEqual(len(cycle), 256)
        spec = np.abs(np.fft.rfft(cycle))
        self.assertAlmostEqual(spec[3] / spec[1], 0.45, places=2)


class ShippedProfileTests(unittest.TestCase):
    def test_no_recordings_are_referenced_or_shipped(self):
        for name in SHIPPED:
            folder = ROOT / "profiles" / name
            data = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
            for effect, params in data["effects"].items():
                self.assertNotIn("sample", params, f"{name}/{effect}")
                self.assertNotIn("wavetable", params, f"{name}/{effect}")
            self.assertEqual([p.name for p in folder.iterdir() if p.suffix.lower() in (".wav", ".npy")], [], name)

    def test_every_template_builds(self):
        for name in SHIPPED:
            cfg = config.load(None)
            config.apply_profile(cfg, ROOT / "profiles" / name / "profile.json", keep_user={})
            effects = {e.name: e for e in build_effects(cfg["effects"], SR)}
            for e in effects.values():
                self.assertFalse(hasattr(e, "sample_error"), f"{name}/{e.name}: {getattr(e, 'sample_error', '')}")
                self.assertFalse(hasattr(e, "wave_error"), f"{name}/{e.name}: {getattr(e, 'wave_error', '')}")
            for effect in ("gear_shift", "impact", "suspension"):
                if cfg["effects"].get(effect, {}).get("template") and effect in effects:
                    self.assertIsNotNone(effects[effect].sample, f"{name}/{effect}")
            if name.startswith("forza"):
                self.assertIsNotNone(effects["road"].wave, f"{name}: kerb cycle")


class ProfileRenameTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = self.dir / "config.json"

    def test_old_folder_names_in_paths_are_migrated(self):
        self.path.write_text(json.dumps({
            "profile": f"profiles/{OLD}fm/profile.json",
            "profiles": {"forza": f"profiles/{OLD}fm/profile.json",
                         "forza_horizon5": f"profiles/{OLD}fh5/profile.json",
                         "beamng": f"C:\\old\\profiles\\{OLD}beamng\\profile.json"},
            "presets": {"forza": {"effects": {"engine": {"trim": 0.5, "enabled": True}}}}}), encoding="utf-8")
        cfg = config.load(self.path)
        self.assertEqual(cfg["profiles"]["forza"], "profiles/forza_motorsport/profile.json")
        self.assertEqual(cfg["profiles"]["forza_horizon5"], "profiles/forza_horizon/profile.json")
        self.assertEqual(cfg["profiles"]["beamng"], "C:\\old\\profiles\\beamng\\profile.json")
        self.assertEqual(Path(cfg["profile"]).parent.name, "forza_motorsport")
        self.assertEqual(cfg["effects"]["engine"]["trim"], 0.5, "the preset's strengths survive")
        saved = config.save_user(cfg, self.path)
        self.assertNotIn(OLD, json.dumps(saved))

    def test_presets_keyed_by_an_old_folder_name_reach_their_games(self):
        self.path.write_text(json.dumps({
            "profiles": {"forza": f"profiles/{OLD}fm/profile.json", "ace": f"profiles/{OLD}fm/profile.json"},
            "presets": {f"{OLD}fm": {"effects": {"engine": {"trim": 0.7, "enabled": True}}}}}), encoding="utf-8")
        cfg = config.load(self.path)
        for game in ("forza", "ace"):
            self.assertEqual(cfg["presets"][game]["effects"]["engine"]["trim"], 0.7, game)
        self.assertNotIn(f"{OLD}fm", cfg["presets"])


class SafeLevelTests(unittest.TestCase):
    """The Demo is a preview, not a parity feature: whatever preset is active it must stay well below
    full scale - also for BeamNG, which plays a game at HaptiConnect's (loud) BeamNG level."""

    @staticmethod
    def demo_peak_dbfs(cfg, seed: int, ceiling=None) -> float:
        from openshaker.compare import OfflineSource
        from openshaker.demo import DemoSource
        from openshaker.runtime import demo_engine
        demo, feed = DemoSource(), OfflineSource()
        engine = demo_engine(cfg, SR, [feed], stale_after=float("inf"), seed=seed)   # what Demo mode plays
        if ceiling is not None:
            engine.limiter.ceiling = ceiling
        peak = 0.0
        for block in range(24 * 100):                    # the whole 24 s script in 10 ms blocks
            t = block / 100.0
            frame = demo.frame(t)
            frame.t = t
            feed.feed(frame, block + 1)
            peak = max(peak, float(np.max(np.abs(engine.render(480)))))
        return 20 * math.log10(peak + 1e-12)

    @staticmethod
    def profile_cfg(game):
        cfg = config.load(None)
        config.apply_profile(cfg, ROOT / "profiles" / game / "profile.json", keep_user={})
        return cfg

    def test_demo_on_a_fresh_install_stays_well_below_full_scale(self):
        from openshaker.runtime import DEMO_OUTPUT_SCALE, demo_output_scale
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = config.load(tmp / "config.json")
        self.assertEqual(Path(cfg["profile"]).parent.name, "forza_motorsport", "a calibrated profile, not the defaults")
        self.assertGreater(demo_output_scale(cfg, SR), DEMO_OUTPUT_SCALE * 10 ** (-1 / 20), "at most a small trim")
        # The gear-shift pitch is random live, and the peak can move with it. Since the Demo's collision
        # fires (demo.IMPACT_SPIKE_S), the hit sets the peak: about -7.8 dBFS on this profile. Fixed seeds
        # keep this deterministic; the loudest of them must still pass.
        peaks = {seed: round(self.demo_peak_dbfs(cfg, seed), 2) for seed in range(8)}
        self.assertLess(max(peaks.values()), DEMO_PEAK_MAX_DBFS, f"Demo peak per seed: {peaks}")

    def test_the_demo_is_safe_with_every_shipped_profile(self):
        from openshaker.runtime import DEMO_OUTPUT_SCALE, demo_output_scale
        scales = {}
        for game in SHIPPED:
            cfg = self.profile_cfg(game)
            scales[game] = demo_output_scale(cfg, SR)
            peaks = [round(self.demo_peak_dbfs(cfg, seed), 2) for seed in range(3)]
            self.assertLess(max(peaks), DEMO_PEAK_MAX_DBFS, f"{game}: Demo peaks {peaks}")
            # scaled, not squashed: without the Demo's ceiling it still peaks near the target
            open_peak = self.demo_peak_dbfs(cfg, 0, ceiling=float("inf"))
            self.assertLess(open_peak, DEMO_PEAK_MAX_DBFS + 1.5, f"{game}: {open_peak:.2f} dBFS before the ceiling")
        self.assertLess(scales["beamng"], 0.5 * DEMO_OUTPUT_SCALE, f"BeamNG's Demo is turned down: {scales}")
        self.assertGreater(scales["forza_motorsport"], DEMO_OUTPUT_SCALE * 10 ** (-1 / 20), scales)
        self.assertLessEqual(max(scales.values()), DEMO_OUTPUT_SCALE, "never louder than before")

    def test_raising_the_strengths_during_the_demo_cannot_push_it_past_the_limit(self):
        from openshaker.runtime import DEMO_MAX_DBFS
        cfg = self.profile_cfg("beamng")
        from openshaker.compare import OfflineSource
        from openshaker.demo import DemoSource
        from openshaker.runtime import demo_engine
        demo, feed = DemoSource(), OfflineSource()
        engine = demo_engine(cfg, SR, [feed], stale_after=float("inf"), seed=0)
        engine.master *= 4.0                                  # Master (or every strength) turned right up
        peak = 0.0
        for block in range(24 * 100):
            frame = demo.frame(block / 100.0)
            frame.t = block / 100.0
            feed.feed(frame, block + 1)
            peak = max(peak, float(np.max(np.abs(engine.render(480)))))
        self.assertLessEqual(20 * math.log10(peak), DEMO_MAX_DBFS + 1e-6)

    def test_the_demo_plays_the_collision_in_every_shipped_profile(self):
        """It used to hold the -60 m/s^2 spike for 20 ms, under every profile's 30 ms min_hold_s: silence."""
        from openshaker.compare import OfflineSource
        from openshaker.demo import DemoSource
        from openshaker.engine import HapticEngine
        for game in SHIPPED:
            cfg = config.load(None)
            config.apply_profile(cfg, ROOT / "profiles" / game / "profile.json", keep_user={})
            for name, e in cfg["effects"].items():
                e["enabled"] = name == "impact"
            demo, feed = DemoSource(), OfflineSource()
            engine = HapticEngine(cfg, SR, [feed], stale_after=float("inf"), seed=0)
            peak, seq = 0.0, 0
            for block in range(1500, 1650):                  # 15.0-16.5 s: the Demo's impact phase
                t = block / 100.0
                if int(t * 60) != int((t - 0.01) * 60):      # the live Demo's 60 frames a second
                    frame = demo.frame(t)
                    frame.t = t
                    seq += 1
                    feed.feed(frame, seq)
                peak = max(peak, float(np.max(np.abs(engine.render(480)))))
            self.assertGreater(peak, 0.1, game)


if __name__ == "__main__":
    unittest.main()
