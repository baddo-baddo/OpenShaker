"""Opt-in profile keys added for HaptiConnect parity (docs/CALIBRATION.md, "Known gaps").
Every key is off unless a profile sets it: without it an effect renders exactly as before."""
import math
import struct
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.effects.base import BandNoise, synth_template                  # noqa: E402
from openshaker.effects.racing import (AccelerationEffect, EngineEffect, ImpactEffect,  # noqa: E402
                                       ShiftIndicatorEffect, SuspensionEffect)
from openshaker.sources.forza import ForzaSource, parse_packet                 # noqa: E402
from openshaker.telemetry import Telemetry                                     # noqa: E402

SR = 48000
BLOCK = 480


def play(effect, frames):
    """Like HapticEngine: a 10 ms block at a time, on_frame once per new frame (60 Hz frames)."""
    out, prev, fi = [], None, 0
    blocks = int(round(len(frames) / 60.0 * 100))
    for b in range(blocks):
        now = b * BLOCK / SR
        while fi < len(frames) and frames[fi].t <= now:
            tele = frames[fi]
            effect.on_frame(tele, prev, tele.t - prev.t if prev is not None else 0.0)
            prev, fi = tele, fi + 1
        y = effect.render(BLOCK, prev)
        out.append(np.zeros(BLOCK, np.float32) if y is None else y)
    return np.concatenate(out)


def road(n=240, travel=None, metres=None, surface=0.0, speed=25.0, packet_step=1):
    """Frames at 60 Hz; `travel`/`metres` are functions of the frame index giving 4 values."""
    frames = []
    for k in range(n):
        t = Telemetry(source="forza", seq=k, t=k / 60.0, active=True, speed=speed)
        t.susp_travel = list(travel(k)) if travel else [0.5] * 4
        t.susp_travel_m = list(metres(k)) if metres else [0.0] * 4
        t.surface_rumble = [surface] * 4
        t.packet_ms = int((k // packet_step) * 1000 / 60 * packet_step)
        frames.append(t)
    return frames


def line_amplitude(y, freq=41.0):
    """Amplitude of the `freq` line over the second half (a sine of amplitude A reads A)."""
    tail = y[len(y) // 2:].astype(np.float64)
    ph = 2 * np.pi * freq * np.arange(len(tail)) / SR
    return 2 * abs(np.mean(tail * np.exp(-1j * ph)))


BED = {"vel_curve": [[0, 0.0], [2, 0.1], [6, 0.3]], "idle_tone_freq": 41.0, "pulse_amp": 0.0,
       "texture_gain": 0.0, "threshold": 1000.0}


def frame(**kw):
    t = Telemetry(active=True, engine_running=True, max_rpm=8000.0, rpm=7600.0, throttle=1.0, gear=3, speed=20.0)
    for k, v in kw.items():
        setattr(t, k, v)
    return t


class ShiftIndicatorMinGearTests(unittest.TestCase):
    CFG = {"rpm_curve": [[0.8, 0.0], [1.0, 0.4]], "pulse_hz": 0.0, "min_throttle": 0.0}

    def level(self, cfg, **kw):
        e = ShiftIndicatorEffect(cfg, SR)
        y = e.render(480, frame(**kw))
        return e.level, float(np.max(np.abs(y)))

    def test_without_the_key_every_gear_plays_as_before(self):
        forward, _ = self.level(self.CFG, gear=3)
        self.assertGreater(forward, 0.25)
        self.assertEqual(self.level(self.CFG, gear=-1)[0], forward)
        self.assertEqual(self.level(self.CFG, gear=0)[0], forward)

    def test_silent_below_the_minimum_gear(self):
        cfg = dict(self.CFG, min_gear=1)
        self.assertEqual(self.level(cfg, gear=-1), (0.0, 0.0), "reverse")
        self.assertEqual(self.level(cfg, gear=0)[0], 0.0, "neutral")
        self.assertGreater(self.level(cfg, gear=1)[0], 0.25)

    def test_a_residual_level_below_it(self):
        """HaptiConnect plays ~0.03-0.04 in reverse against ~0.4 forward."""
        cfg = dict(self.CFG, min_gear=1, below_min_gear_scale=0.1)
        forward, _ = self.level(cfg, gear=4)
        self.assertAlmostEqual(self.level(cfg, gear=-1)[0], 0.1 * forward)


class AccelerationCombineTests(unittest.TestCase):
    CURVES = {"curve_long": [[-12, 0.6], [0, 0.0], [6, 0.5]], "curve_lat": [[0, 0.0], [12, 0.8]]}

    def level(self, long_g, lat_g, **keys):
        e = AccelerationEffect(dict(self.CURVES, **keys), SR)
        e.on_frame(frame(accel_long=long_g, accel_lat=lat_g), None, 0.0)
        return e._level

    def test_the_default_is_the_larger_of_the_two_as_before(self):
        for long_g, lat_g in ((0, 0), (6, 0), (0, 12), (6, 6), (3, 9), (-12, 12), (6, -12)):
            lvl_long = float(np.interp(long_g, [-12, 0, 6], [0.6, 0.0, 0.5]))
            lvl_lat = float(np.interp(abs(lat_g), [0, 12], [0.0, 0.8]))
            want = min(max(lvl_long, lvl_lat, 0.0), 1.0)
            self.assertAlmostEqual(self.level(long_g, lat_g), want, msg=(long_g, lat_g))
            self.assertAlmostEqual(self.level(long_g, lat_g, combine="max"), want)

    def test_sum_adds_the_two_axes(self):
        """HaptiConnect: the levels add (Forza Motorsport sum -0.6 dB, max +3.6 dB, rss +2.1 dB)."""
        self.assertAlmostEqual(self.level(6, 6, combine="sum"), 0.5 + 0.4)
        self.assertAlmostEqual(self.level(6, 0, combine="sum"), 0.5, msg="one axis alone is unchanged")
        self.assertAlmostEqual(self.level(0, -6, combine="sum"), 0.4, msg="left and right alike")

    def test_power_is_a_p_norm(self):
        self.assertAlmostEqual(self.level(6, 6, combine="power", combine_p=2.0), math.hypot(0.5, 0.4))
        self.assertAlmostEqual(self.level(6, 6, combine="power", combine_p=1.0), 0.9)

    def test_the_cap_comes_after_combining(self):
        self.assertEqual(self.level(6, 12, combine="sum"), 1.0, "capped at 1 by default, as before")
        self.assertAlmostEqual(self.level(6, 12, combine="sum", max_level=2.0), 1.3)
        e = AccelerationEffect(dict(self.CURVES, combine="sum", max_level=2.0, freq=58.0), SR)
        e.on_frame(frame(accel_long=6, accel_lat=12), None, 0.0)
        y = np.concatenate([e.render(480, frame()) for _ in range(20)])
        self.assertGreater(float(np.max(np.abs(y))), 1.0 * e.gain, "past the gain when the cap allows it")

    def test_a_cross_term_and_a_braking_mode(self):
        self.assertAlmostEqual(self.level(6, 6, combine="sum", combine_cross=0.5), 0.9 + 0.5 * 0.5 * 0.4)
        self.assertAlmostEqual(self.level(-12, 6, combine="sum", combine_brake="max"), 0.6, msg="braking: max")
        self.assertAlmostEqual(self.level(6, 6, combine="sum", combine_brake="max"), 0.9, msg="on power: sum")

    def test_standing_still_is_silent_whatever_the_combine(self):
        e = AccelerationEffect(dict(self.CURVES, combine="sum"), SR)
        e.on_frame(frame(accel_long=6, accel_lat=12, speed=0.5), None, 0.0)
        self.assertEqual(e._level, 0.0)


def wobble(amplitude, per_frame=True, mpu=1.0, offset=0.0):
    """Travel moving back and forth: every frame (per_frame) or as a slow 2 Hz sine; scaled by mpu."""
    def f(k):
        x = amplitude * ((1 if k % 2 else -1) if per_frame else math.sin(2 * math.pi * 2 * k / 60.0))
        return [offset + mpu * x] * 4
    return f


class RoadBedInputTests(unittest.TestCase):
    """The bed follows suspension velocity: in metres like HaptiConnect, over a span, per packet."""

    def level(self, cfg, frames):
        return line_amplitude(play(SuspensionEffect(dict(BED, **cfg), SR), frames))

    def test_metres_make_two_cars_alike_where_normalized_travel_does_not(self):
        """The same wheel motion in metres; the 9000-rpm car's travel spans fewer metres per unit."""
        motion = wobble(0.01, per_frame=False)                          # +-1 cm at 2 Hz
        old = road(metres=motion, travel=lambda k: [x / 0.116 + 0.5 for x in motion(k)])
        new = road(metres=motion, travel=lambda k: [x / 0.0802 + 0.5 for x in motion(k)])
        curve_m = {"vel_curve_m": [[0, 0.0], [0.1, 0.1], [0.5, 0.3]]}
        self.assertAlmostEqual(self.level(curve_m, old), self.level(curve_m, new), places=6)
        self.assertGreater(self.level({}, new), 1.2 * self.level({}, old), "normalized: the new car reads louder")

    def test_a_game_without_metres_uses_normalized_times_metres_per_unit(self):
        frames = road(travel=wobble(0.02, per_frame=False, offset=0.5))
        curve_m = {"vel_curve_m": [[0, 0.0], [0.1, 0.1], [0.5, 0.3]]}
        a = self.level(dict(curve_m, metres_per_unit=0.15), frames)
        b = self.level(curve_m, road(metres=lambda k: [x * 0.15 for x in wobble(0.02, per_frame=False, offset=0.5)(k)],
                                     travel=wobble(0.02, per_frame=False, offset=0.5)))
        self.assertGreater(a, 0.0)
        self.assertAlmostEqual(a, b, places=6)

    def test_a_span_averages_out_frame_to_frame_jitter(self):
        frames = road(travel=wobble(0.02, offset=0.5))                  # +-0.02 every frame: 2.4 /s frame to frame
        jittery = self.level({"vel_span_s": 0.0, "wheel_combine": "max"}, frames)
        spanned = self.level({"vel_span_s": 0.1}, frames)
        self.assertGreater(jittery, 0.1)
        self.assertLess(spanned, 0.2 * jittery)

    def test_a_repeated_packet_is_not_a_standstill_then_a_jump(self):
        """Forza can send the same packet twice; by frame time that is 0 then twice the speed."""
        move = lambda k: [0.5 + 0.01 * (k // 2)] * 4                  # noqa: E731  moves once per 2 frames
        frames = road(travel=move, packet_step=2)
        by_frame = SuspensionEffect(dict(BED, bed_env="frame"), SR)
        by_packet = SuspensionEffect(dict(BED, bed_env="frame", vel_time_source="packet"), SR)
        seen_frame, seen_packet = [], []
        prev = None
        for t in frames:
            by_frame.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            by_packet.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            seen_frame.append(by_frame._vpeak)
            seen_packet.append(by_packet._vpeak)
            prev = t
        self.assertIn(0.0, seen_frame[5:], "frame clock: every other frame reads a standstill")
        np.testing.assert_allclose(seen_packet[5:], 0.3, rtol=0.05, err_msg="packet clock: a steady 0.3 /s")

    def test_wheel_combine(self):
        frames = road(travel=lambda k: [0.5 + (0.02 if k % 2 else -0.02), 0.5, 0.5, 0.5])   # one wheel moves
        e_max = SuspensionEffect(dict(BED, bed_env="frame"), SR)
        e_mean = SuspensionEffect(dict(BED, bed_env="frame", wheel_combine="mean"), SR)
        e_rear = SuspensionEffect(dict(BED, bed_env="frame", wheel_combine="rear_max"), SR)
        prev = None
        for t in frames[:10]:
            for e in (e_max, e_mean, e_rear):
                e.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            prev = t
        self.assertAlmostEqual(e_mean._vpeak, e_max._vpeak / 4)
        self.assertEqual(e_rear._vpeak, 0.0)

    def test_hold_and_frame_envelopes(self):
        still = lambda k: [0.5 + (0.05 if k == 10 else 0.0)] * 4       # noqa: E731  one jolt at frame 10
        frames = road(n=40, travel=still)
        held = SuspensionEffect(dict(BED, vel_span_s=0.0, wheel_combine="max", vel_hold_s=1.0), SR)
        frame = SuspensionEffect(dict(BED, bed_env="frame"), SR)
        short = SuspensionEffect(dict(BED, wheel_combine="max", vel_span_s=0.0, vel_hold_s=0.01,
                                      vel_hold_floor_s=0.0, bed_env="peak_hold", vel_time_source="packet"), SR)
        prev = None
        for t in frames[:14]:
            for e in (held, frame, short):
                e.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            prev = t
        self.assertGreater(held._vpeak, 2.0, "held a few frames after the jolt")
        self.assertEqual(frame._vpeak, 0.0, "no hold: back to still")
        self.assertLess(short._vpeak, 0.15, "two frames of a 10 ms release, once the 50 ms floor is lifted")
        floored = SuspensionEffect(dict(BED, wheel_combine="max", vel_span_s=0.0, vel_hold_s=0.01,
                                        vel_time_source="packet"), SR)
        prev = None
        for t in frames[:14]:
            floored.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            prev = t
        self.assertGreater(floored._vpeak, 1.0, "the default floor keeps 50 ms")

    def test_a_sampled_poll_differs_from_a_sliding_span(self):
        """vel_poll_hz: the velocity is known only at each poll, from the travel between two polls."""
        frames = road(n=120, travel=lambda k: [0.5 + 0.01 * k] * 4)           # a steady 0.6 /s
        e = SuspensionEffect(dict(BED, bed_env="frame", vel_poll_hz=12.0), SR)
        seen, prev = [], None
        for t in frames:
            e.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            seen.append(e._vpeak)
            prev = t
        np.testing.assert_allclose(seen[10:], 0.6, rtol=1e-6)
        changes = [k for k in range(1, len(seen)) if seen[k] != seen[k - 1]]
        self.assertTrue(all(b - a >= 4 for a, b in zip(changes, changes[1:])), "at most one new value per poll")
        wobbly = road(n=120, travel=lambda k: [0.5 + (0.02 if k % 5 == 0 else 0.0)] * 4)   # a spike every 5 frames
        polled = SuspensionEffect(dict(BED, bed_env="frame", vel_poll_hz=12.0), SR)
        prev = None
        for t in wobbly:
            polled.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            prev = t
        self.assertEqual(polled._vpeak, 0.0, "a poll landing between spikes sees none of them")

    def test_amp_mpu_scales_by_the_learned_metres_per_unit(self):
        motion = wobble(0.01, per_frame=False)
        frames = road(metres=lambda k: [x * 0.08 for x in motion(k)], travel=lambda k: [0.5 + x for x in motion(k)])
        base = self.level({}, frames)
        scaled = SuspensionEffect(dict(BED, amp_mpu_ref=0.116, amp_mpu_exp=2.0), SR)
        y = play(scaled, frames)
        self.assertAlmostEqual(scaled._mpu, 0.08, places=4)
        self.assertAlmostEqual(line_amplitude(y), base * (0.08 / 0.116) ** 2, places=3)
        self.assertAlmostEqual(self.level({"amp_mpu_ref": 0.116}, frames), base, places=7, msg="off without exp")

    def test_update_steps(self):
        e = SuspensionEffect(dict(BED, bed_update_hz=12.0), SR)
        frames = road(n=120, travel=lambda k: [0.5 + 0.0002 * k * k] * 4)  # speeding up: the level keeps rising
        amps, prev = [], None
        for t in frames:
            e.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            e.render(BLOCK, t)
            amps.append(e.idle_tone.amp.value)
            prev = t
        changes = sum(1 for a, b in zip(amps, amps[1:]) if a != b)
        self.assertLessEqual(changes, 2 * 12 + 1, "about 12 steps a second over 2 s, not 60")
        self.assertGreaterEqual(changes, 18)


class RoadBedSurfaceTests(unittest.TestCase):
    def level(self, cfg, surface):
        frames = road(travel=wobble(0.01, per_frame=False, offset=0.5), surface=surface)
        return line_amplitude(play(SuspensionEffect(dict(BED, **cfg), SR), frames))

    def test_off_by_default(self):
        self.assertAlmostEqual(self.level({}, 0.6), self.level({}, 0.0), places=7)

    def test_scale_add_and_max(self):
        base = self.level({}, 0.0)
        gain = {"surface_gain_curve": [[0, 1.0], [0.12, 1.0], [0.6, 2.5]]}
        self.assertAlmostEqual(self.level(gain, 0.6), 2.5 * base, places=4)
        self.assertAlmostEqual(self.level(gain, 0.0), base, places=6)
        add = {"surface_add_curve": [[0, 0.0], [0.6, 0.2]]}
        self.assertAlmostEqual(self.level(add, 0.6), base + 0.2, places=3)
        self.assertAlmostEqual(self.level(dict(add, surface_mode="max"), 0.6), max(base, 0.2), places=3)

    def test_not_capped_at_the_velocity_curve(self):
        """HaptiConnect's 0.230 at SurfaceRumble 0.6 is above anything the velocity curve reaches."""
        self.assertGreater(self.level({"surface_add_curve": [[0, 0.0], [0.6, 0.5]]}, 0.6), 0.45)

    def test_reduce_and_hold(self):
        e = SuspensionEffect(dict(BED, surface_gain_curve=[[0, 1], [2, 2]], surface_reduce="count_nonzero",
                                  surface_hold_s=0.5), SR)
        frames = road(n=4, travel=wobble(0.01, offset=0.5))
        frames[1].surface_rumble = [0.12, 0.12, 0.0, 0.0]
        prev = None
        for t in frames[:2]:
            e.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            prev = t
        self.assertEqual(e._surf, 2.0)
        e.on_frame(frames[2], frames[1], 1 / 60.0)
        self.assertAlmostEqual(e._surf, 2.0 * math.exp(-1 / 60.0 / 0.5), msg="held, then released")


class RoadBedNoiseTests(unittest.TestCase):
    NOISE = {"bed_noise": {"curve": [[0, 0.02], [0.3, 0.05]], "band": [35, 47]}}

    def render(self, cfg, part="all", seconds=4.0):
        frames = road(n=int(60 * seconds), travel=wobble(0.02, per_frame=False, offset=0.5))
        return play(SuspensionEffect(dict(BED, render_part=part, **cfg), SR), frames)

    def test_band_noise_fills_its_band_at_sine_peak_units(self):
        noise = BandNoise(SR, 35, 47)
        noise.render(BLOCK, 0.1)                                        # the level glides in over one block
        y = noise.render(SR * 20, 0.1)[SR:].astype(np.float64)
        self.assertAlmostEqual(float(np.sqrt(np.mean(y ** 2))), 0.1 / math.sqrt(2), delta=0.01)
        def inside(signal):
            spec = np.abs(np.fft.rfft(signal * np.hanning(len(signal)))) ** 2
            f = np.fft.rfftfreq(len(signal), 1 / SR)
            return spec[(f >= 30) & (f <= 52)].sum() / spec.sum()
        self.assertGreater(inside(y), 0.8, "most of it in the band; order 2 leaves soft skirts")
        steep = BandNoise(SR, 35, 47, order=4)
        steep.render(BLOCK, 0.1)
        self.assertGreater(inside(steep.render(SR * 20, 0.1)[SR:].astype(np.float64)), inside(y), "order sharpens it")
        np.testing.assert_array_equal(BandNoise(SR, 35, 47, seed=4).render(4800, 0.1),
                                      BandNoise(SR, 35, 47, seed=4).render(4800, 0.1), "seeded: repeats exactly")

    def test_the_noise_voice_follows_the_line(self):
        line = self.render(self.NOISE, part="line")
        noise = self.render(self.NOISE, part="noise")
        both = self.render(self.NOISE, part="bed")
        np.testing.assert_allclose(both, line + noise, atol=1e-6)
        a = line_amplitude(line)
        want = float(np.interp(a / BED.get("gain", 1.0), [0, 0.3], [0.02, 0.05]))
        rms = float(np.sqrt(np.mean(noise[len(noise) // 2:].astype(np.float64) ** 2)))
        self.assertAlmostEqual(rms * math.sqrt(2), want, delta=0.25 * want)

    def test_parts_add_up_and_the_default_has_no_noise(self):
        plain = self.render({})
        self.assertIsNone(SuspensionEffect(dict(BED), SR)._render_bed_noise(480, None, 0.1, True))
        parts = [self.render(self.NOISE, part=p) for p in ("line", "noise", "shots")]
        np.testing.assert_allclose(self.render(self.NOISE), sum(parts), atol=1e-6)
        np.testing.assert_allclose(parts[0], plain, atol=1e-7, err_msg="the line itself is unchanged")

    def test_silent_when_the_bed_is_off(self):
        frames = road(n=120, travel=wobble(0.02, per_frame=False, offset=0.5), speed=0.2)   # below idle_min_speed
        y = play(SuspensionEffect(dict(BED, render_part="noise", **self.NOISE), SR), frames)
        self.assertEqual(float(np.abs(y).max()), 0.0)

    def test_several_bands_share_the_level(self):
        cfg = {"bed_noise": {"curve": [[0, 0.05], [1, 0.05]], "bands": [[35, 41, -3.0], [41, 47, 0.0]]}}
        y = self.render(cfg, part="noise", seconds=10.0)[SR:].astype(np.float64)
        self.assertAlmostEqual(float(np.sqrt(np.mean(y ** 2))) * math.sqrt(2), 0.05, delta=0.008)
        spec = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
        f = np.fft.rfftfreq(len(y), 1 / SR)
        low, high = spec[(f >= 35) & (f < 41)].sum(), spec[(f >= 41) & (f <= 47)].sum()
        self.assertLess(low, high, "the high shoulder above the low one, as in HaptiConnect")


def crash_frames(n=120, rate=60.0, spike_at=0.5, spike_s=0.08, spike=-60.0, extra=None):
    """Driving at `rate` Hz with one longitudinal spike; extra: per-frame overrides {index: {field: value}}."""
    frames = []
    for k in range(n):
        t = Telemetry(source="forza", seq=k, t=k / rate, active=True, speed=20.0)
        if spike_at <= t.t < spike_at + spike_s:
            t.accel_long = spike
        for field, value in ((extra or {}).get(k) or {}).items():
            setattr(t, field, value)
        frames.append(t)
    return frames


def fires(effect, frames):
    prev = None
    for t in frames:
        effect.on_frame(t, prev, t.t - prev.t if prev else 0.0)
        effect.render(BLOCK, t)
        prev = t
    return list(effect.fire_log)


class ImpactParityTests(unittest.TestCase):
    FM = {"axes": ["long", "lat"], "threshold": 15.0, "min_hold_s": 0.03, "cooldown": 0.3, "fixed_amp": True}

    def test_the_main_rule_is_unchanged_and_says_it_fired(self):
        log = fires(ImpactEffect(self.FM, SR), crash_frames())
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0][1], "main")
        self.assertEqual(fires(ImpactEffect(self.FM, SR), crash_frames(spike_s=0.02)), [], "20 ms is below the hold")

    def test_extra_rules_share_the_cooldown_and_are_named(self):
        cfg = dict(self.FM, triggers=[{"signal": "vert", "mode": "jump", "threshold": 20.0, "name": "vert"},
                                      {"signal": "kerb_onset", "min_wheels": 1}])
        frames = crash_frames(n=180, spike_at=2.5, extra={30: {"accel_vert": 30.0},
                                                          90: {"rumble_strip": [True, False, False, False]}})
        for k in range(91, 180):
            frames[k].rumble_strip = [True, False, False, False]
        log = fires(ImpactEffect(cfg, SR), frames)
        self.assertEqual([r for _t, r in log], ["vert", "rule2:kerb_onset", "main"], "each hit names its rule")
        e = ImpactEffect(dict(cfg, cooldown=5.0), SR)
        self.assertEqual(len(fires(e, frames)), 1, "one cooldown for every rule")

    def test_rule_filters(self):
        vert = {"signal": "vert", "mode": "jump", "threshold": 20.0}
        frames = crash_frames(n=60, spike_at=5.0, extra={30: {"accel_vert": 30.0}})
        self.assertEqual(fires(ImpactEffect(dict(self.FM, triggers=[dict(vert, kerb="required")]), SR), frames), [])
        self.assertEqual(fires(ImpactEffect(dict(self.FM, triggers=[dict(vert, min_speed=30.0)]), SR), frames), [])
        self.assertEqual(len(fires(ImpactEffect(dict(self.FM, triggers=[dict(vert, kerb="excluded")]), SR), frames)), 1)

    def test_suspension_velocity_and_excursion_rules(self):
        frames = crash_frames(n=60, spike_at=5.0)
        for k, t in enumerate(frames):
            t.susp_travel_m = [0.05 + (0.06 if k == 30 else 0.0)] * 4
        log = fires(ImpactEffect(dict(self.FM, triggers=[{"signal": "susp_vel_m", "threshold": 2.0}]), SR), frames)
        self.assertEqual(len(log), 1, "0.06 m in one frame is 3.6 m/s")
        slow = crash_frames(n=180, spike_at=1.0, spike_s=0.5, spike=-18.0)
        rule = {"signal": "long_lat", "mode": "excursion", "threshold": 10.0, "min_hold_s": 0.1}
        self.assertEqual(len(fires(ImpactEffect(dict(self.FM, threshold=1e9, triggers=[rule]), SR), slow)), 1)

    def test_a_jump_window_makes_the_frame_rate_not_matter(self):
        """A 60 m/s^2 step spread over 50 ms: frame to frame it is 20 at 60 Hz but only 6.7 at 180 Hz."""
        def ramp(rate):
            frames = crash_frames(n=int(rate), rate=rate, spike_at=99.0)
            for t in frames:
                t.accel_long = -60.0 * min(max((t.t - 0.5) / 0.05, 0.0), 1.0)
            return frames
        plain = dict(threshold=15.0, axes=["long"], min_hold_s=0.0, cooldown=1.0)
        self.assertEqual(len(fires(ImpactEffect(plain, SR), ramp(60.0))), 1)
        self.assertEqual(len(fires(ImpactEffect(plain, SR), ramp(180.0))), 0, "the replay rate hides it")
        windowed = dict(plain, jump_window_s=0.05)
        self.assertEqual(len(fires(ImpactEffect(windowed, SR), ramp(60.0))), 1)
        self.assertEqual(len(fires(ImpactEffect(windowed, SR), ramp(180.0))), 1)

    def test_a_sampled_detector_misses_a_short_spike_now_and_then(self):
        rule = dict(threshold=15.0, axes=["long"], min_hold_s=0.0, cooldown=0.3, eval_hz=12.0)
        short = [len(fires(self.seeded(rule, s), crash_frames(n=90, spike_s=1 / 60))) for s in range(12)]
        self.assertIn(0, short, "a one-frame spike falls between samples...")
        self.assertIn(1, short, "...or on one")
        long = [len(fires(self.seeded(rule, s), crash_frames(n=90, spike_s=10 / 60))) for s in range(12)]
        self.assertEqual(set(long), {1}, "a 10-frame hit is always seen")

    @staticmethod
    def seeded(cfg, seed):
        e = ImpactEffect(cfg, SR)
        e.rng = np.random.default_rng(seed)
        return e

    def test_the_hit_can_come_late(self):
        e = ImpactEffect(dict(self.FM, fire_delay_s=0.1), SR)
        log = fires(e, crash_frames())
        self.assertEqual(len(log), 1)
        self.assertGreaterEqual(log[0][0], 0.5 + 0.03 + 0.1 - 1e-9)

    def test_a_hard_square_template(self):
        soft = synth_template(SR, 50.0, 0.02, shape="square", attack=0.0, release=0.0)
        hard = synth_template(SR, 50.0, 0.02, shape="square", attack=0.0, release=0.0, bandlimit_hz=0)
        core = np.abs(hard[5:-5])
        self.assertTrue(np.all(core == 1.0), "HaptiConnect's plateau is full scale")
        self.assertLess(float(np.median(np.abs(soft[5:-5]))), 0.95, "the band-limited one is not")
        uneven = synth_template(SR, 50.0, 0.02, shape="square", attack=0.0, release=0.0, bandlimit_hz=0, duty=0.535)
        self.assertAlmostEqual(float(np.mean(uneven > 0)), 0.535, delta=0.01)
        np.testing.assert_array_equal(synth_template(SR, 50.0, 0.02, shape="square"),
                                      synth_template(SR, 50.0, 0.02, shape="square", bandlimit_hz=1000.0))


class RevLimiterVoiceTests(unittest.TestCase):
    ENGINE = {"curve": [[0, 20, 0.5], [9000, 150, 0.5]]}
    VOICE = dict(ENGINE, rev_voice_amp=0.5)

    def render(self, cfg, rpm, max_rpm=8000.0, blocks=200, **kw):
        e = EngineEffect(cfg, SR)
        t = Telemetry(active=True, engine_running=True, rpm=rpm, max_rpm=max_rpm, throttle=1.0, **kw)
        return np.concatenate([e.render(BLOCK, t) for _ in range(blocks)]), e

    @staticmethod
    def line(y, freq):
        return line_amplitude(y, freq)

    def test_off_by_default(self):
        plain, _ = self.render(self.ENGINE, 7900.0)
        zero, _ = self.render(dict(self.ENGINE, rev_voice_amp=0.0), 7900.0)
        np.testing.assert_array_equal(plain, zero)
        self.assertLess(self.line(plain, 66.0), 1e-3)

    def test_above_98_percent_a_66_hz_voice_with_10_hz_sidebands(self):
        """HaptiConnect, probe at max_rpm 8000: carrier 66.00 Hz (0.99 x max / 120), sidebands 10 Hz away
        at 0.33 x the carrier, and no lines 20 Hz away."""
        y, _ = self.render(self.VOICE, 7900.0)
        carrier = self.line(y, 66.0)
        self.assertAlmostEqual(carrier, 0.5, delta=0.01)
        for side in (56.0, 76.0):
            self.assertAlmostEqual(self.line(y, side), 0.5 * 0.65 / 2, delta=0.01)
        for far in (46.0, 86.0):
            self.assertLess(self.line(y, far), 0.01)

    def test_below_the_threshold_it_is_silent(self):
        y, _ = self.render(self.VOICE, 7800.0)                            # 0.975 x max
        self.assertLess(self.line(y, 66.0), 0.005, "only the engine tone's leakage")

    def test_the_carrier_modes(self):
        y, _ = self.render(dict(self.VOICE, rev_voice_freq_mode="rpm"), 7900.0)
        self.assertGreater(self.line(y, 7900 * 0.99 / 120), 0.45)
        y, _ = self.render(dict(self.VOICE, rev_voice_freq_mode="fixed", rev_voice_freq=60.0), 7900.0)
        self.assertGreater(self.line(y, 60.0), 0.45)

    def test_a_held_decision(self):
        e = EngineEffect(dict(self.VOICE, rev_voice_hold_hz=11.72), SR)
        up = Telemetry(active=True, engine_running=True, rpm=7900.0, max_rpm=8000.0)
        down = Telemetry(active=True, engine_running=True, rpm=7000.0, max_rpm=8000.0)
        states = []
        for k in range(40):
            e.render(BLOCK, up if k % 2 == 0 else down)                   # dithering around the threshold
            states.append(e._rev_on)
        switches = sum(1 for a, b in zip(states, states[1:]) if a != b)
        self.assertLessEqual(switches, 5, "decided about 12 times a second, not every 10 ms block")

    def test_min_rpm_guard_and_engine_scale(self):
        y, _ = self.render(dict(self.VOICE, rev_voice_min_rpm=8000.0), 7900.0)
        self.assertLess(self.line(y, 66.0), 1e-3)
        plain, _ = self.render(self.ENGINE, 7900.0)
        ducked, _ = self.render(dict(self.VOICE, rev_voice_engine_scale=0.5), 7900.0)
        f = float(np.interp(7900.0, [0, 9000], [20, 150]))
        self.assertAlmostEqual(self.line(ducked, f), 0.5 * self.line(plain, f), delta=0.01)


class ReviewFixTests(unittest.TestCase):
    """Regressions for the adversarial review of the parity keys (2026-09-20)."""

    @staticmethod
    def feed(effect, frames, blocks_per_frame=0):
        prev = None
        for t in frames:
            effect.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            for _ in range(blocks_per_frame):
                effect.render(BLOCK, t)
            prev = t

    def test_a_landing_reads_its_own_velocity_not_the_flights_average(self):
        """Forza in the air: normalized travel all 0, the metres still reported (they carry an offset)."""
        frames = road(n=120, travel=lambda k: [0.5] * 4, metres=lambda k: [0.116 * 0.5 - 0.066] * 4)
        for k in range(60, 90):                                            # 0.5 s airborne
            frames[k].susp_travel = [0.0] * 4
            frames[k].susp_travel_m = [0.116 * 0.0 - 0.066] * 4
        e = SuspensionEffect(dict(BED, vel_curve_m=[[0, 0], [1, 0.1]], bed_env="frame"), SR)
        self.feed(e, frames[:91])                                          # frame 90: touchdown
        self.assertAlmostEqual(e._vpeak, 0.116 * 0.5 * 60, delta=0.1, msg="one frame's 5.8 cm, at 60 Hz")

    def test_a_12_hz_poll_stays_12_hz_on_real_clocks(self):
        """Drive logs keep t to 4 decimals: five frames read 0.0833 < 1/12, which used to push every poll a frame late."""
        frames = road(n=600, travel=lambda k: [0.5 + 0.001 * k] * 4)
        for t in frames:
            t.t = round(t.t, 4)
        e = SuspensionEffect(dict(BED, vel_poll_hz=12.0), SR)
        polls, prev = 0, None
        for t in frames:
            before = e._bed_t
            e.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            polls += e._bed_t != before
            prev = t
        self.assertAlmostEqual(polls, 12 * 10, delta=2)

    def test_bed_update_steps_stay_on_rate(self):
        frames = road(n=600, travel=lambda k: [0.5 + 0.0002 * k * k] * 4)
        for t in frames:
            t.t = round(t.t, 4)
        e = SuspensionEffect(dict(BED, bed_update_hz=12.0), SR)
        steps, prev, last = 0, None, None
        for t in frames:
            e.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            e.render(BLOCK, t)
            if e._step_next != last:
                steps, last = steps + 1, e._step_next
            prev = t
        self.assertAlmostEqual(steps, 12 * 10, delta=2)

    def test_band_noise_keeps_its_level_at_high_order_and_never_goes_nan(self):
        for order in (8, 12, 40):                                          # 40 is clamped to 12
            n = BandNoise(SR, 35, 47, order=order)
            n.render(SR, 0.1)                                              # settle
            y = n.render(SR * 10, 0.1).astype(np.float64)
            self.assertAlmostEqual(float(np.sqrt(np.mean(y ** 2))) * math.sqrt(2), 0.1, delta=0.02, msg=order)
        wide = BandNoise(SR, 10, 20000, order=6).render(4800, 0.1)
        self.assertTrue(np.all(np.isfinite(wide)))

    def test_a_nan_travel_value_does_not_silence_anything(self):
        frames = road(n=60, travel=wobble(0.02, offset=0.5))
        frames[30].susp_travel = [math.nan, 0.5, 0.5, 0.5]
        e = SuspensionEffect(dict(BED, texture_gain=0.35, threshold=1.0), SR)
        y = play(e, frames)
        self.assertTrue(math.isfinite(e.texture))
        self.assertTrue(np.all(np.isfinite(y)))
        self.assertGreater(float(np.abs(y[-4800:]).max()), 0.0)

    def test_one_effects_nan_leaves_the_rest_of_the_mix(self):
        from openshaker import config
        from openshaker.engine import HapticEngine
        eng = HapticEngine(config.load(None), SR, [])
        broken = type("Broken", (), {"enabled": True, "name": "broken", "level": 0.0,
                                     "on_frame": lambda *a: None,
                                     "render": lambda self, n, tele: np.full(n, np.nan, np.float32)})()
        fine = type("Fine", (), {"enabled": True, "name": "fine", "level": 0.0, "on_frame": lambda *a: None,
                                 "render": lambda self, n, tele: np.full(n, 0.25, np.float32)})()
        eng.effects = [broken, fine]
        out = np.concatenate([eng.render(BLOCK) for _ in range(5)])
        self.assertAlmostEqual(float(out[-1]), 0.25 * eng.master, places=5)

    def test_a_pause_releases_the_holds(self):
        cfg = dict(BED, surface_add_curve=[[0, 0.0], [0.6, 0.2]], surface_hold_s=2.0, wheel_combine="max",
                   vel_hold_s=5.0, vel_span_s=0.0, bed_env="peak_hold", vel_time_source="packet")
        frames = road(n=120, travel=wobble(0.05, offset=0.5), surface=0.6)
        for k in range(60, 120):
            frames[k].active = False
        tail = road(n=10)
        for k, t in enumerate(tail):
            t.t, t.seq, t.packet_ms = 2.0 + k / 60.0, 200 + k, int((2.0 + k / 60.0) * 1000)
        e = SuspensionEffect(cfg, SR)
        self.feed(e, frames + tail)
        self.assertEqual(e._surf, 0.0, "no kerb level carried over the pause")
        self.assertLess(e._vpeak, 0.1)

    def test_a_packet_clock_that_goes_back_does_not_freeze_the_bed(self):
        frames = road(n=120, travel=wobble(0.02, offset=0.5))
        for k, t in enumerate(frames):
            t.packet_ms = (2 ** 32 - 1000 + k * 17) % (2 ** 32)            # TimestampMS wraps at frame ~59
        e = SuspensionEffect(dict(BED, bed_env="frame", vel_time_source="packet"), SR)
        seen, prev = [], None
        for t in frames:
            e.on_frame(t, prev, t.t - prev.t if prev else 0.0)
            seen.append(e._bed_t)
            prev = t
        self.assertGreater(len(set(seen[80:])), 30, "still measuring after the wrap")

    # -- collision ---------------------------------------------------------------------------------
    FM = {"axes": ["long", "lat"], "threshold": 15.0, "min_hold_s": 0.03, "cooldown": 0.3, "fixed_amp": True}

    def test_a_closed_filter_does_not_leave_a_stale_reference(self):
        """kerb 'required': the vertical level changes off the kerb; on the next kerb that is no jump."""
        rule = {"signal": "vert", "mode": "jump", "threshold": 20.0, "kerb": "required"}
        frames = crash_frames(n=90, spike_at=99.0)
        for k, t in enumerate(frames):
            t.rumble_strip = [k < 10 or k >= 60, False, False, False]
            t.accel_vert = 30.0 if k >= 30 else 0.0                        # steps off the kerb, stays
        self.assertEqual(fires(ImpactEffect(dict(self.FM, triggers=[rule]), SR), frames), [])

    def test_one_long_crash_is_one_hit_whatever_the_rules(self):
        rule = {"signal": "long_lat", "mode": "level", "threshold": 40.0, "name": "level"}
        log = fires(ImpactEffect(dict(self.FM, triggers=[rule]), SR), crash_frames(n=150, spike_s=1.0))
        self.assertEqual(len(log), 1, log)

    def test_a_delayed_hit_sounds_on_time_between_frames(self):
        e = ImpactEffect(dict(self.FM, min_hold_s=0.0, threshold=30.0, fire_delay_s=0.05), SR)
        frames = crash_frames(n=20, rate=10.0, spike_at=0.5, spike_s=0.1)   # 10 frames a second
        self.feed(e, frames, blocks_per_frame=10)
        self.assertEqual(len(e.fire_log), 1)
        self.assertAlmostEqual(e.fire_log[0][0], 0.55, delta=0.011, msg="within a block of its due time")

    def test_a_pause_drops_a_pending_hit(self):
        e = ImpactEffect(dict(self.FM, min_hold_s=0.0, threshold=30.0, fire_delay_s=0.2), SR)
        frames = crash_frames(n=40, spike_at=0.5, spike_s=0.02)
        for k in range(32, 40):
            frames[k].active = False
        self.feed(e, frames, blocks_per_frame=0)
        self.assertEqual(list(e.fire_log), [])

    def test_a_slow_sampled_detector_still_fires(self):
        e = ImpactEffect(dict(self.FM, min_hold_s=0.0, threshold=30.0, eval_hz=1.5), SR)
        e.rng = np.random.default_rng(1)
        log = fires(e, crash_frames(n=360, spike_at=2.0, spike_s=1.5))
        self.assertGreaterEqual(len(log), 1, "below 2 Hz every sample used to count as a gap: never a hit")

    # -- rev voice --------------------------------------------------------------------------------------
    def test_the_rev_voice_decides_at_11_72_hz_with_480_sample_blocks(self):
        e = EngineEffect(dict(RevLimiterVoiceTests.VOICE, rev_voice_hold_hz=11.72), SR)
        t = Telemetry(active=True, engine_running=True, rpm=7900.0, max_rpm=8000.0)
        decisions, before = 0, e._rev_clock
        for _ in range(1000):                                              # 10 s
            e.render(BLOCK, t)
            decisions += e._rev_clock < before
            before = e._rev_clock
        self.assertAlmostEqual(decisions, 117, delta=1)

    def test_an_infinite_max_rpm_does_not_break_the_voice(self):
        e = EngineEffect(RevLimiterVoiceTests.VOICE, SR)
        good = Telemetry(active=True, engine_running=True, rpm=7900.0, max_rpm=8000.0)
        bad = Telemetry(active=True, engine_running=True, rpm=7900.0, max_rpm=math.inf)
        ys = [e.render(BLOCK, good) for _ in range(20)] + [e.render(BLOCK, bad)] + \
             [e.render(BLOCK, good) for _ in range(100)]
        y = np.concatenate(ys)
        self.assertTrue(np.all(np.isfinite(y)))
        self.assertGreater(line_amplitude(y, 66.0), 0.4, "still playing afterwards")


class ForzaTravelMetersTests(unittest.TestCase):
    def packet(self, travel_m=(0.0, 0.0, 0.0, 0.0), n=331):
        buf = bytearray(n)
        struct.pack_into("<i", buf, 0, 1)
        struct.pack_into("<3f", buf, 8, 8000.0, 900.0, 3000.0)
        struct.pack_into("<4f", buf, 68, 0.5, 0.5, 0.5, 0.5)
        struct.pack_into("<4f", buf, 196, *travel_m)
        return bytes(buf)

    def test_suspension_travel_in_metres_is_read(self):
        for n in (232, 324, 331):
            t = ForzaSource.__new__(ForzaSource).parse(self.packet((0.051, 0.052, 0.07, 0.071), n=n))
            np.testing.assert_allclose(t.susp_travel_m, [0.051, 0.052, 0.07, 0.071], rtol=1e-6)
            self.assertEqual(t.susp_travel, [0.5] * 4, "the normalized travel is unchanged")

    def test_a_garbled_value_is_not_passed_on(self):
        t = ForzaSource.__new__(ForzaSource).parse(self.packet((math.nan, math.inf, 0.05, 0.05)))
        self.assertEqual(t.susp_travel_m[:2], [0.0, 0.0])

    def test_other_games_report_zeros(self):
        self.assertEqual(Telemetry().susp_travel_m, [0.0] * 4)
        self.assertIsNone(Telemetry().packet_ms)

    def test_the_packet_clock_and_the_tools_parser(self):
        data = bytearray(self.packet((0.05,) * 4))
        struct.pack_into("<I", data, 4, 123456)
        t = parse_packet(bytes(data))
        self.assertEqual(t.packet_ms, 123456)
        self.assertEqual(parse_packet(bytes.fromhex(bytes(data).hex())).susp_travel_m, t.susp_travel_m)
        self.assertIsNone(parse_packet(b"\x00" * 100), "not a Forza packet size")
        src = ForzaSource.__new__(ForzaSource)
        src.kind = "?"
        src.parse(bytes(data))
        self.assertEqual(src.kind, "motorsport")


if __name__ == "__main__":
    unittest.main()
