"""The output stage is HaptiConnect's peak limiter: nothing above 0.985, no waveshaping, a loud burst ducks the
rest of the mix and it comes back at 0.853 gain units per second, and below the ceiling the output is the input
64 samples late. (Checked sample for sample against the calibration notes' reference emulation when it landed.)"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker import config                                                  # noqa: E402
from openshaker.engine import HapticEngine, PeakLimiter                        # noqa: E402

SR = 48000
T = np.arange(SR * 2) / SR


def run(x, call=480, **kw):
    lim = PeakLimiter(SR, **kw)
    return np.concatenate([lim.process(x[s:s + call]) for s in range(0, len(x), call)]), lim


def engine_and_burst(at=0.5, burst_s=0.16):
    """A 0.9 engine line with a 0.5 gear-shift square on top (BeamNG at HaptiConnect's level)."""
    x = 0.9 * np.sin(2 * np.pi * 45 * T)
    i0 = int(at * SR) + 17
    x[i0:i0 + int(burst_s * SR)] += 0.5 * np.sign(np.sin(2 * np.pi * 30 * T[:int(burst_s * SR)]))
    return x, i0


class LimiterTests(unittest.TestCase):
    def test_below_the_ceiling_it_is_the_input_64_samples_late(self):
        x = 0.9 * np.sin(2 * np.pi * 45 * T)
        y, lim = run(x)
        self.assertEqual(lim.gain, 1.0)
        np.testing.assert_allclose(y[64:], x[:-64].astype(np.float32), atol=1e-7)
        self.assertTrue(np.all(y[:64] == 0.0))

    def test_nothing_passes_the_ceiling(self):
        rng = np.random.default_rng(3)
        for x in (3.0 * rng.standard_normal(len(T)), 1.4 * np.sign(np.sin(2 * np.pi * 33 * T)),
                  np.where(rng.random(len(T)) < 0.001, 5.0, 0.0), 20.0 * np.sin(2 * np.pi * 60 * T)):
            for call in (480, 4800, 97):
                y, _ = run(x, call=call)
                self.assertLessEqual(float(np.max(np.abs(y))), PeakLimiter.CEILING + 1e-6)

    def test_it_scales_it_never_bends(self):
        """Every output sample is the delayed input times one smooth gain: no tanh knee, no clipping."""
        x, _ = engine_and_burst()
        y, _ = run(x)
        d = x[:-64]
        live = np.abs(d) > 1e-3
        g = y[64:][live] / d[live]
        self.assertTrue(np.all((g > 0.0) & (g <= 1.0 + 1e-6)), "one positive gain, never above unity")
        # the gain only creeps up (the release); the few faster rises are the attack's per-sample clamp letting
        # go of a single sample it had to hold under the ceiling
        fast_rises = np.diff(g) > 3 * PeakLimiter.RELEASE / SR
        self.assertLess(float(fast_rises.mean()), 0.005)

    def test_a_burst_ducks_the_engine_and_it_comes_back_slowly(self):
        x, i0 = engine_and_burst()
        y, _ = run(x)
        burst = y[i0 + 64 + 2000:i0 + 64 + 6000]
        self.assertAlmostEqual(float(np.max(np.abs(burst))), PeakLimiter.CEILING, places=3,
                               msg="the burst sits on the ceiling")
        engine_during = float(np.max(np.abs(burst))) - 0.5 * float(np.max(np.abs(burst))) / 1.4
        self.assertLess(engine_during, 0.75, "the engine under the burst is turned down with it")
        end = i0 + int(0.16 * SR) + 64
        after = [float(np.max(np.abs(y[end + int(dt * SR):end + int(dt * SR) + 1100]))) for dt in (0.02, 0.2, 0.9)]
        self.assertLess(after[0], 0.9 * 0.79, "right after the burst the engine is still ducked, > 2 dB "
                                              "(HaptiConnect: -3.2 dB averaged over 0.02-0.19 s after)")
        self.assertLess(after[0], after[1])
        self.assertLess(after[1], after[2])
        self.assertAlmostEqual(after[2], 0.9, delta=0.01, msg="back to the engine's own level within a second")

    def test_the_release_rate(self):
        x = np.zeros(SR)
        x[1000:1100] = 2.0                                    # one hot moment pulls the gain to 0.4925
        _y, lim = run(x[:1600])
        g_low = lim.gain
        _y2 = lim.process(np.zeros(4800))                     # 0.1 s of quiet
        self.assertAlmostEqual(lim.gain - g_low, 0.0853, delta=0.002)

    def test_it_looks_ahead(self):
        """The gain is already falling when the first burst sample leaves the limiter."""
        x = 0.9 * np.sin(2 * np.pi * 45 * T)
        edge = 480 * 10                                      # a burst on a block boundary, like HaptiConnect's
        x[edge:edge + 4800] += 0.5
        y, _ = run(x)
        out_edge = edge + 64
        pre = y[out_edge - 40:out_edge] / np.where(np.abs(x[edge - 104:edge - 64]) > 1e-3,
                                                    x[edge - 104:edge - 64], 1.0)
        self.assertLess(float(np.min(pre)), 0.999, "the gain dropped before the burst arrived")

    def test_call_size_does_not_change_the_output(self):
        x, _ = engine_and_burst(at=0.7)
        a, _ = run(x, call=480)
        b, _ = run(x, call=4800)
        np.testing.assert_allclose(a, b, atol=1e-7)

    def test_empty_blocks(self):
        lim = PeakLimiter(SR)
        self.assertEqual(len(lim.process(np.zeros(0))), 0)


class EngineOutputTests(unittest.TestCase):
    def test_the_engine_ends_in_the_limiter(self):
        cfg = config.load(None)
        eng = HapticEngine(cfg, SR, [])
        eng.tone = type("Tone", (), {"done": False, "block": staticmethod(lambda n: np.full(n, 3.0, np.float32))})()
        peak = max(float(np.max(np.abs(eng.render(480)))) for _ in range(20))
        self.assertLessEqual(peak, PeakLimiter.CEILING + 1e-6)
        self.assertGreater(peak, 0.98, "limited, not muted")
        self.assertEqual(eng.limiter.block, cfg["audio"]["blocksize"])
        self.assertIsNone(eng.mix_limiter, "a game's mix goes straight to the output limiter")


class Loud:
    """An effect far above every ceiling: a 45 Hz sine at 2.0."""

    name, enabled = "loud", True

    def __init__(self):
        self.i = 0

    def render(self, n, tele):
        t = (self.i + np.arange(n)) / SR
        self.i += n
        return (2.0 * np.sin(2 * np.pi * 45 * t)).astype(np.float32)


class DemoToneTests(unittest.TestCase):
    """The Demo's own ceiling (DEMO_MAX_DBFS) caps the Demo's mix, never the test tone: capped there, the
    tone played about 4 dB weaker in Demo than in Games."""

    def peak(self, eng, blocks=150):
        return max(float(np.max(np.abs(eng.render(480)))) for _ in range(blocks))

    def test_the_test_tone_is_as_strong_in_the_demo_as_in_a_game(self):
        from openshaker.engine import TestTone
        from openshaker.gui import TONE_AMP, TONE_HIGH, TONE_LOW
        from openshaker.runtime import DEMO_MAX_DBFS, demo_engine
        cfg = config.load(None)
        peaks = {}
        for mode, eng in (("games", HapticEngine(cfg, SR, [])), ("demo", demo_engine(cfg, SR, []))):
            eng.tone = TestTone(SR, 1.0, TONE_LOW, TONE_HIGH, TONE_AMP)
            peaks[mode] = self.peak(eng)
        self.assertAlmostEqual(peaks["games"], TONE_AMP, delta=0.01)
        self.assertAlmostEqual(peaks["demo"], peaks["games"], delta=0.001)
        self.assertGreater(20 * np.log10(peaks["demo"]), DEMO_MAX_DBFS + 3.0)

    def test_the_demo_mix_stays_capped_and_the_tone_still_never_passes_the_ceiling(self):
        from openshaker.engine import TestTone
        from openshaker.runtime import DEMO_MAX_DBFS, demo_engine
        eng = demo_engine(config.load(None), SR, [])
        eng.effects.append(Loud())
        eng.master *= 4.0                                   # Master turned right up during the Demo
        self.assertLessEqual(20 * np.log10(self.peak(eng)), DEMO_MAX_DBFS + 1e-6)
        eng.tone = TestTone(SR, 1.0, 25.0, 70.0, 0.8)
        both = self.peak(eng, 100)
        self.assertLessEqual(both, PeakLimiter.CEILING + 1e-6)
        self.assertGreater(both, 0.9, "the tone joins the capped mix and the output limiter holds the sum")
        self.assertIsNone(eng.tone, "the tone ended")
        self.assertLessEqual(20 * np.log10(self.peak(eng)), DEMO_MAX_DBFS + 1e-6, "and the cap holds again")


if __name__ == "__main__":
    unittest.main()
