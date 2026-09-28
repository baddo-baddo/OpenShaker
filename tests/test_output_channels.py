"""The output stream is as wide as the device, and only the chosen channel carries the signal.

A mono stream on a stereo endpoint is not "left only": WASAPI up-mixes it, so the right channel got the
same signal - up to +6 dB on a shaker that sums both - where HaptiConnect writes left and leaves right
silent. These tests use a fake sounddevice module: PortAudio and the real devices are never touched.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker import audio                                                   # noqa: E402


class FakeStream:
    def __init__(self, sd, **kw):
        self.kw, self.active, self.latency = kw, False, 0.01
        sd.streams.append(self)

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        pass


def fake_sd(channels=2, refuse=()):
    """A sounddevice stand-in with one WASAPI output named like the maintainer's shaker. `refuse`: channel
    counts check_output_settings turns down (a driver that will not open its full width)."""
    sd = SimpleNamespace(streams=[])
    device = {"name": "Speakers (ButtKicker PRO)", "hostapi": 0, "max_output_channels": channels,
              "default_samplerate": 48000.0}
    hostapi = {"name": "Windows WASAPI", "default_output_device": 0}

    def check_output_settings(device=None, samplerate=None, channels=None, dtype=None, extra_settings=None):
        if channels > sd.device["max_output_channels"] or channels in refuse:
            raise ValueError(f"Invalid number of channels: {channels}")

    sd.device = device
    sd.query_devices = lambda idx=None: [device] if idx is None else device
    sd.query_hostapis = lambda idx=None: [hostapi] if idx is None else hostapi
    sd.check_output_settings = check_output_settings
    sd.WasapiSettings = lambda exclusive=False: SimpleNamespace(exclusive=exclusive)
    sd.OutputStream = lambda **kw: FakeStream(sd, **kw)
    sd.default = SimpleNamespace(device=(None, 0))
    return sd


class OutputChannelTests(unittest.TestCase):
    def use(self, sd):
        self.addCleanup(setattr, audio, "sd", audio.sd)
        audio.sd = sd
        self.addCleanup(setattr, audio.AudioOutput, "open_streams", audio.AudioOutput.open_streams)
        return sd

    def block(self, channels, sd):
        """Open the stream the way the runtime does and render one block of a constant 0.5."""
        out = audio.AudioOutput(device_substr="ButtKicker", channels=channels)
        out.resolve()
        out.render = lambda frames: np.full(frames, 0.5, dtype=np.float32)
        out.start()
        self.addCleanup(out.stop)
        stream = sd.streams[-1]
        data = np.full((out.blocksize, stream.kw["channels"]), 9.0, dtype=np.float32)   # garbage to overwrite
        out._cb(data, out.blocksize, None, None)
        return out, stream, data

    def test_left_on_a_stereo_shaker_leaves_the_right_channel_silent(self):
        sd = self.use(fake_sd(channels=2))
        out, stream, data = self.block([0], sd)
        self.assertEqual(stream.kw["channels"], 2, "a stereo endpoint gets a stereo stream, never a mono one")
        self.assertEqual(out.nch, 2)
        self.assertTrue(np.all(data[:, 0] == 0.5))
        self.assertTrue(np.all(data[:, 1] == 0.0), "the right channel carries nothing, like HaptiConnect")

    def test_right_and_both(self):
        sd = self.use(fake_sd(channels=2))
        _out, _stream, data = self.block([1], sd)
        self.assertTrue(np.all(data[:, 0] == 0.0))
        self.assertTrue(np.all(data[:, 1] == 0.5))
        _out, _stream, data = self.block([0, 1], sd)
        self.assertTrue(np.all(data == 0.5))

    def test_a_surround_device_gets_its_full_width_and_one_channel_of_signal(self):
        sd = self.use(fake_sd(channels=8))
        _out, stream, data = self.block([0], sd)
        self.assertEqual(stream.kw["channels"], 8)
        self.assertTrue(np.all(data[:, 0] == 0.5))
        self.assertTrue(np.all(data[:, 1:] == 0.0))

    def test_width_is_capped_at_eight(self):
        sd = self.use(fake_sd(channels=16))
        _out, stream, _data = self.block([0], sd)
        self.assertEqual(stream.kw["channels"], 8)

    def test_a_mono_device(self):
        sd = self.use(fake_sd(channels=1))
        out, stream, data = self.block([1], sd)            # "Right" on a one-channel device: its only channel
        self.assertEqual((stream.kw["channels"], out.channels), (1, [0]))
        self.assertTrue(np.all(data[:, 0] == 0.5))

    def test_a_driver_that_refuses_its_full_width_still_plays(self):
        sd = self.use(fake_sd(channels=2, refuse=(2,)))
        out, stream, data = self.block([0], sd)
        self.assertEqual(stream.kw["channels"], 1, "the narrow stream is the fallback, not the default")
        self.assertTrue(np.all(data[:, 0] == 0.5))

    def test_the_block_handed_on_is_the_mono_signal(self):
        sd = self.use(fake_sd(channels=2))
        seen = []
        out = audio.AudioOutput(device_substr="ButtKicker", channels=[0])
        out.resolve()
        out.render = lambda frames: np.full(frames, 0.25, dtype=np.float32)
        out.on_block = seen.append                        # the --log WAV capture
        out.start()
        self.addCleanup(out.stop)
        out._cb(np.zeros((out.blocksize, 2), dtype=np.float32), out.blocksize, None, None)
        self.assertEqual(seen[0].ndim, 1)
        self.assertTrue(np.all(seen[0] == 0.25))
        self.assertEqual(sd.streams[-1].kw["channels"], 2)


if __name__ == "__main__":
    unittest.main()
