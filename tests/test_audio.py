"""Device picking and the test tone.

Both regressions here had the same shape: the app quietly took the ButtKicker on WDM-KS - an
exclusive kernel stream - so a second stream for the test tone could not open at all
("WdmSyncIoCtl: DeviceIoControl GLE = 0x490"), while the haptics themselves kept working.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.audio import AudioOutput           # noqa: E402
from openshaker.engine import TestTone             # noqa: E402

SR = 48000


def devices(*apis):
    name = "Speakers (2- ButtKicker PRO)"
    return [{"index": 10 + i, "name": name, "api": api, "channels": 2, "samplerate": 48000.0}
            for i, api in enumerate(apis)]


class FindDeviceTests(unittest.TestCase):
    def pick(self, available, api_pref="WASAPI"):
        real = AudioOutput.output_devices
        AudioOutput.output_devices = staticmethod(lambda: available)
        self.addCleanup(setattr, AudioOutput, "output_devices", real)
        return AudioOutput.find_device("ButtKicker", api_pref)

    def test_prefers_wasapi(self):
        found = self.pick(devices("MME", "Windows DirectSound", "Windows WASAPI", "Windows WDM-KS"))
        self.assertEqual(found, 12)                       # the WASAPI entry, not the first match

    def test_falls_back_to_another_shared_api_not_to_wdm_ks(self):
        """A device list snapshotted at boot can lack the WASAPI endpoint entirely."""
        found = self.pick(devices("MME", "Windows DirectSound", "Windows WDM-KS"))
        self.assertEqual(found, 11)                       # DirectSound, never the exclusive one

    def test_only_exclusive_available_means_wait(self):
        self.assertIsNone(self.pick(devices("Windows WDM-KS")),
                          "taking an exclusive stream locks out HaptiConnect and our own test tone")

    def test_explicit_preference_is_still_honoured(self):
        self.assertEqual(self.pick(devices("Windows WASAPI", "Windows WDM-KS"), api_pref="WDM-KS"), 11)

    def test_no_match_at_all(self):
        self.assertIsNone(self.pick([]))


class TestToneTests(unittest.TestCase):
    def test_sweeps_and_then_stops(self):
        tone = TestTone(SR, seconds=0.5, low=25.0, high=70.0, amp=0.8)
        blocks = [tone.block(480) for _ in range(60)]      # 0.6 s: the 0.5 s sweep, then past its end
        out = np.concatenate(blocks)
        self.assertTrue(tone.done)
        self.assertLessEqual(float(np.max(np.abs(out))), 0.8 + 1e-6)
        self.assertGreater(float(np.max(np.abs(out[:SR // 2]))), 0.5, "the sweep should be audible")
        self.assertLess(float(np.max(np.abs(out[int(SR * 0.55):]))), 1e-6, "silent once finished")

    def test_starts_and_ends_without_a_click(self):
        tone = TestTone(SR, seconds=0.5, low=25.0, high=70.0, amp=0.8)
        first = tone.block(64)
        self.assertLess(abs(float(first[0])), 0.05, "must fade in, not click")

    def test_frequency_climbs(self):
        tone = TestTone(SR, seconds=1.0, low=25.0, high=70.0, amp=1.0)
        out = np.concatenate([tone.block(4800) for _ in range(10)])

        def dominant(chunk):
            spec = np.abs(np.fft.rfft(chunk * np.hanning(len(chunk))))
            return float(np.fft.rfftfreq(len(chunk), 1 / SR)[np.argmax(spec)])

        low = dominant(out[:SR // 5])
        high = dominant(out[int(SR * 0.7):int(SR * 0.95)])
        self.assertLess(low, 40.0, low)
        self.assertGreater(high, 55.0, high)


class EngineToneTests(unittest.TestCase):
    def test_engine_mixes_the_tone_into_the_live_output(self):
        from openshaker import config
        from openshaker.engine import HapticEngine
        engine = HapticEngine(config.load(None), SR, [])
        silent = engine.render(480)
        self.assertEqual(float(np.max(np.abs(silent))), 0.0)   # no telemetry, no sources

        engine.tone = TestTone(SR, seconds=0.2, low=25.0, high=70.0, amp=0.8)
        loud = np.concatenate([engine.render(480) for _ in range(20)])
        self.assertGreater(float(np.max(np.abs(loud))), 0.5, "the tone must reach the output")
        self.assertIsNone(engine.tone, "the engine drops the tone once it has finished")
        self.assertLessEqual(float(np.max(np.abs(loud))), 1.0, "still inside the limiter")


if __name__ == "__main__":
    unittest.main()
