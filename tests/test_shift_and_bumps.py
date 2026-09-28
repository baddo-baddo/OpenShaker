"""Gear shift pitched from rpm (opt-in) and suspension bumps that never cross an inactive frame."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.effects.racing import GearShiftEffect, RoadEffect, SuspensionEffect   # noqa: E402
from openshaker.telemetry import Telemetry                               # noqa: E402

SR = 48000
TEMPLATE = {"shape": "square", "freq": 34.0, "duration": 0.085, "attack": 0.002, "release": 0.003}


def frame(t, **kw):
    kw.setdefault("active", True)
    return Telemetry(t=t, **kw)


def dominant_hz(y):
    spec = np.abs(np.fft.rfft(y, 1 << 16))
    return float(np.fft.rfftfreq(1 << 16, 1.0 / SR)[int(np.argmax(spec))])


class GearShiftPitchTests(unittest.TestCase):
    def shift(self, cfg, rpm=6000.0, prev_rpm=None):
        gear = GearShiftEffect(dict(cfg, enabled=True, gain=1.0), SR)
        gear.on_frame(frame(1.0, gear=4, rpm=rpm), frame(0.98, gear=3, rpm=prev_rpm or rpm), 0.02)
        return gear

    def test_without_the_key_the_shift_is_unchanged(self):
        gear = self.shift({"template": TEMPLATE})
        self.assertEqual(len(gear.samples.voices), 1)
        self.assertIs(gear.samples.voices[0][0], gear.sample, "the profile's own template, as before")
        self.assertAlmostEqual(gear.samples.voices[0][2], 0.9)
        jittered = self.shift({"template": TEMPLATE, "pitch_jitter": [0.8, 2.3]})
        self.assertIsNotNone(jittered.rng, "pitch_jitter still draws a random pitch")

    def test_the_pitch_follows_the_rpm(self):
        for rpm, hz in ((6000.0, 50.0), (4320.0, 36.0)):
            gear = self.shift({"template": TEMPLATE, "pitch_jitter": [0.8, 2.3], "pitch_hz_per_rpm": 1 / 120}, rpm)
            shot = gear.samples.voices[0][0]
            self.assertEqual(len(shot), round(0.08 * SR), "a fixed 80 ms shot")
            self.assertAlmostEqual(dominant_hz(shot), hz, delta=1.0)
            self.assertIsNone(gear.rng, "no random pitch when it follows the rpm")

    def test_options(self):
        cfg = {"pitch_hz_per_rpm": 1 / 120, "pitched_duration_s": 0.05, "pitch_rpm_from": "prev"}
        gear = self.shift(cfg, rpm=3000.0, prev_rpm=7200.0)
        shot = gear.samples.voices[0][0]
        self.assertEqual(len(shot), round(0.05 * SR))
        self.assertAlmostEqual(dominant_hz(shot), 60.0, delta=1.0)          # 7200 / 120, the rpm before
        clamped = self.shift({"pitch_hz_per_rpm": 1 / 120}, rpm=30000.0)   # 250 Hz is out of range
        self.assertAlmostEqual(dominant_hz(clamped.samples.voices[0][0]), 120.0, delta=1.0)


class SuspensionStartTests(unittest.TestCase):
    def peak(self, effect):
        y = effect.render_shots(480)
        return 0.0 if y is None else float(np.max(np.abs(y)))

    def test_no_bump_on_the_first_active_frame(self):
        susp = SuspensionEffect({"enabled": True, "gain": 1.0}, SR)
        paused = frame(1.0, active=False, susp_travel=[0.0, 0.0, 0.0, 0.0])
        racing = frame(1.016, susp_travel=[0.1, 0.1, 0.1, 0.1])            # ~6 m/s if read as motion
        susp.on_frame(racing, paused, 0.016)
        self.assertEqual(self.peak(susp), 0.0, "unpausing is not a bump")
        bump = frame(1.032, susp_travel=[0.2, 0.1, 0.1, 0.1])
        susp.on_frame(bump, racing, 0.016)
        self.assertGreater(self.peak(susp), 0.0, "a real bump right after still fires")

    def test_no_bump_from_vertical_g_on_the_first_active_frame(self):
        susp = SuspensionEffect({"enabled": True, "gain": 1.0}, SR)          # BeamNG: no suspension travel
        susp.on_frame(frame(1.016, accel_vert=40.0), frame(1.0, active=False, accel_vert=0.0), 0.016)
        self.assertEqual(self.peak(susp), 0.0)



class GearShiftAcrossPausesTests(unittest.TestCase):
    """HaptiConnect plays no shift when a pause, rewind, menu or respawn ends in another gear."""

    def setUp(self):
        self.gear = GearShiftEffect({"enabled": True, "gain": 1.0, "template": TEMPLATE, "neutral_window_s": 0.0,
                                     "cooldown": 0.05}, SR)
        self.prev = None
        self.shots = 0

    def feed(self, t, gear, active=True):
        tele = frame(t, gear=gear, active=active, rpm=5000.0)
        before = len(self.gear.samples.voices)
        dt = tele.t - self.prev.t if self.prev is not None else 0.0
        self.gear.on_frame(tele, self.prev, dt)
        self.shots += len(self.gear.samples.voices) - before
        self.prev = tele

    def drive(self, gears, start=0.0, active=True, step=1 / 60):
        for i, g in enumerate(gears):
            self.feed(start + i * step, g, active)
        return start + len(gears) * step

    def test_a_normal_shift_fires_once(self):
        self.drive([3] * 10 + [4] * 10)
        self.assertEqual(self.shots, 1)

    def test_a_pause_that_ends_in_another_gear_is_silent(self):
        t = self.drive([3] * 10)
        t = self.drive([3] * 30, start=t, active=False)       # paused (or rewinding: inactive frames)
        t = self.drive([5] * 10, start=t)                     # back on track in fifth
        self.assertEqual(self.shots, 0)
        self.drive([6] * 5, start=t)                          # the next real shift still fires
        self.assertEqual(self.shots, 1)

    def test_a_respawn_in_first_is_silent(self):
        t = self.drive([4] * 10)
        t = self.drive([1] * 3, start=t, active=False)        # Trackmania marks respawn frames inactive
        self.drive([1] * 10, start=t)
        self.assertEqual(self.shots, 0)

    def test_a_gap_in_the_stream_is_silent(self):
        t = self.drive([3] * 10)
        self.drive([2] * 10, start=t + 2.0)                   # a menu or loading screen sent nothing
        self.assertEqual(self.shots, 0)

    def test_a_spell_switched_off_is_silent(self):
        t = self.drive([3] * 10)
        self.prev = frame(t + 1.0, gear=5, rpm=5000.0)        # frames the switched-off effect never saw
        self.drive([5] * 10, start=t + 1.0 + 1 / 60)
        self.assertEqual(self.shots, 0)

    def test_a_short_spell_switched_off_is_silent_too(self):
        t = self.drive([3] * 10)
        for i in range(18):                                   # 0.3 s the switched-off effect never sees
            self.prev = frame(t + i / 60, gear=4, rpm=5200.0)
        self.drive([4] * 5, start=t + 18 / 60)
        self.assertEqual(self.shots, 0, "the shift happened while it was off")
        t = self.drive([4] * 10, start=t + 1.0)
        for i in range(12):                                   # a respawn into first, also unseen
            self.prev = frame(t + i / 60, gear=1, active=False)
        self.drive([1] * 5, start=t + 12 / 60)
        self.assertEqual(self.shots, 0)

    def test_fire_into_neutral_off_plays_only_the_engagement(self):
        shift = [3] * 10 + [0] * 15 + [4] * 10               # ACE shows neutral for ~250 ms
        self.drive(shift)
        self.assertEqual(self.shots, 2, "default (Forza): into neutral and into fourth")
        self.gear = GearShiftEffect({"enabled": True, "gain": 1.0, "template": TEMPLATE, "neutral_window_s": 0.0,
                                     "cooldown": 0.05, "fire_into_neutral": False}, SR)
        self.prev, self.shots = None, 0
        self.drive(shift, start=5.0)
        self.assertEqual(self.shots, 1, "HaptiConnect's ACE plugin: only the engagement")

    def test_the_first_frame_ever_starts_from_the_engines_previous_frame(self):
        self.feed(1.0, 3)                                     # e.g. prev supplied by the engine
        self.gear = GearShiftEffect({"enabled": True, "gain": 1.0, "template": TEMPLATE}, SR)
        self.gear.on_frame(frame(1.02, gear=4), frame(1.0, gear=3), 0.02)
        self.assertEqual(len(self.gear.samples.voices), 1)
        fresh = GearShiftEffect({"enabled": True, "gain": 1.0, "template": TEMPLATE}, SR)
        fresh.on_frame(frame(1.02, gear=4), frame(1.0, gear=3, active=False), 0.02)
        self.assertEqual(len(fresh.samples.voices), 0, "an inactive previous frame is no starting point")


KERB = {"enabled": True, "gain": 1.0, "wavetable_harmonics": [1.0], "strip_hz_per_ms": 1.25, "strip_hz_min": 6.0,
        "strip_hz_max": 100.0, "strip_amp_curve": [[0, 0.7071], [60, 0.7071]], "surface_gain": 0.0}


class PerWheelKerbTests(unittest.TestCase):
    def run_road(self, cfg, wheels_per_block, speed=20.0):
        road = RoadEffect(dict(cfg), SR)
        out = []
        prev = None
        for i, wheels in enumerate(wheels_per_block):
            tele = frame(i * 0.01, speed=speed, rumble_strip=list(wheels))
            road.on_frame(tele, prev, 0.01 if prev else 0.0)
            y = road.render(480, tele)
            out.append(np.zeros(480, dtype=np.float32) if y is None else y)
            prev = tele
        return road, np.concatenate(out)

    def test_without_the_key_the_car_has_one_voice(self):
        road, y = self.run_road(KERB, [(True, True, False, False)] * 20)
        self.assertIsNone(road.wheel_waves)
        _, one = self.run_road(KERB, [(True, False, False, False)] * 20)
        np.testing.assert_allclose(y, one, err_msg="any wheel on the strip = the same single voice, as before")

    def test_one_wheel_sounds_like_the_single_voice(self):
        _, single = self.run_road(KERB, [(True, False, False, False)] * 20)
        _, per = self.run_road(dict(KERB, strip_per_wheel=True), [(True, False, False, False)] * 20)
        np.testing.assert_allclose(per, single, atol=1e-6)

    def test_wheels_that_reach_the_strip_apart_add_with_their_own_phases(self):
        per = dict(KERB, strip_per_wheel=True)
        _, together = self.run_road(per, [(True, True, False, False)] * 40)
        _, single = self.run_road(KERB, [(True, False, False, False)] * 40)
        np.testing.assert_allclose(together, 2 * single, atol=1e-5, err_msg="in step: twice one wheel")
        apart_blocks = [(True, False, False, False)] * 3 + [(True, True, False, False)] * 37   # second wheel 30 ms later
        _, apart = self.run_road(per, apart_blocks)
        tail = slice(20 * 480, 40 * 480)
        self.assertLess(np.sqrt(np.mean(apart[tail] ** 2)), 0.99 * np.sqrt(np.mean(together[tail] ** 2)),
                        "out of step, the two voices partly cancel")

    def test_a_wheel_leaving_the_strip_fades_out(self):
        per = dict(KERB, strip_per_wheel=True)
        road, y = self.run_road(per, [(True, False, False, False)] * 10 + [(False,) * 4] * 30)
        self.assertLess(float(np.max(np.abs(y[-480:]))), 1e-4)
        self.assertEqual(road._wheel_amp, [0.0] * 4)

    def test_a_new_kerb_starts_clean_whatever_speed_the_last_one_ended_at(self):
        per = dict(KERB, strip_per_wheel=True)
        staggered = [(True, False, False, False)] * 3 + [(True, True, False, False)] * 20
        road = RoadEffect(dict(per), SR)
        prev = None
        for i, (wheels, speed) in enumerate([((True, False, False, False), 35.0)] * 10 +
                                            [((False,) * 4, 35.0)] * 15):    # an earlier kerb, left fast
            tele = frame(i * 0.01, speed=speed, rumble_strip=list(wheels))
            road.on_frame(tele, prev, 0.01 if prev else 0.0)
            road.render(480, tele)
            prev = tele
        later = []
        for i, wheels in enumerate(staggered):
            tele = frame(1.0 + i * 0.01, speed=20.0, rumble_strip=list(wheels))
            road.on_frame(tele, prev, 0.01)
            later.append(road.render(480, tele))
            prev = tele
        _, fresh = self.run_road(per, staggered)
        np.testing.assert_allclose(np.concatenate(later), fresh, atol=1e-5,
                                   err_msg="no pitch glide carried over from the last kerb")

    def test_wheels_start_afresh_after_the_stream_went_stale(self):
        per = dict(KERB, strip_per_wheel=True)
        road = RoadEffect(dict(per), SR)
        prev = None
        for i in range(10):                                  # FL on a kerb
            tele = frame(i * 0.01, speed=20.0, rumble_strip=[True, False, False, False])
            road.on_frame(tele, prev, 0.01 if prev else 0.0)
            road.render(480, tele)
            prev = tele
        for _ in range(30):                                  # the game stopped sending: stale, no frames
            road.render(480, None)
        back = []
        for i in range(20):                                  # back, with FL and FR on the kerb together
            tele = frame(2.0 + i * 0.01, speed=20.0, rumble_strip=[True, True, False, False])
            road.on_frame(tele, None if i == 0 else prev, 0.01)
            back.append(road.render(480, tele))
            prev = tele
        _, fresh = self.run_road(per, [(True, True, False, False)] * 20)
        np.testing.assert_allclose(np.concatenate(back), fresh, atol=1e-5, err_msg="both wheels in step again")

    def test_a_wheel_scale_of_zero_is_silent(self):
        road, y = self.run_road(dict(KERB, strip_per_wheel=True, strip_wheel_scale=0.0),
                                [(True, True, False, False)] * 10)
        self.assertLess(float(np.max(np.abs(y))), 1e-6)
        self.assertEqual(road.level, 0.0)

    def test_ace_kerb_hints_keep_the_single_voice(self):
        road = RoadEffect(dict(KERB, strip_per_wheel=True), SR)
        tele = frame(0.0, speed=20.0, kerb_vib=0.5, has_vib_hints=True)
        road.on_frame(tele, None, 0.0)
        self.assertEqual(road._wheel_amp, [0.0] * 4)
        self.assertGreater(float(np.max(np.abs(road.render(480, tele)))), 0.0)


if __name__ == "__main__":
    unittest.main()
