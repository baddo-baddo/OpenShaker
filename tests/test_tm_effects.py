"""Trackmania effects: surface feel, landings, turbo and reactor boost - and off for calibrated games."""
import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from openshaker import config                                                  # noqa: E402
from openshaker.effects.racing import BoostEffect, LandingEffect, SurfaceEffect  # noqa: E402
from openshaker.telemetry import Telemetry                                      # noqa: E402

SR = 48000


def make(cls, **params):
    cfg = dict(config.DEFAULTS["effects"][cls.name])
    cfg.update(enabled=True, gain=1.0)
    cfg.update(params)
    return cls(cfg, SR)


def frame(t, speed=30.0, **extra):
    tele = Telemetry(active=True, speed=speed)
    tele.t = t
    tele.extra = extra
    return tele


def drive(effect, frames):
    peak, prev = 0.0, None
    for f in frames:
        effect.on_frame(f, prev, 0.01 if prev is not None else 0.0)
        y = effect.render(480, f)
        if y is not None:
            peak = max(peak, float(np.max(np.abs(y))))
        prev = f
    return peak


def on(surface, t, speed=30.0, contact=True, **extra):
    return frame(t, speed=speed, materials=[0, 0, 0, 0], surfaces=[surface] * 4,
                 wheel_contact=[contact] * 4, ground_contact=contact, **extra)


class SurfaceTests(unittest.TestCase):
    def feel(self, surface, speed=30.0, contact=True, **extra):
        e = make(SurfaceEffect)
        return drive(e, [on(surface, i * 0.01, speed, contact, **extra) for i in range(40)])

    def test_dirt_is_rougher_than_asphalt(self):
        self.assertGreater(self.feel("Dirt"), 0.1)
        self.assertLess(self.feel("Asphalt"), 0.02)

    def test_grows_with_speed(self):
        self.assertGreater(self.feel("Dirt", speed=40.0), self.feel("Dirt", speed=10.0) * 1.5)

    def test_silent_in_the_air(self):
        self.assertEqual(self.feel("Dirt", contact=False), 0.0)

    def test_a_profile_can_name_a_material_id(self):
        e = make(SurfaceEffect, materials={"99": "Dirt"})
        frames = [frame(i * 0.01, materials=[99] * 4, surfaces=["id 99"] * 4, wheel_contact=[True] * 4,
                        ground_contact=True) for i in range(40)]
        self.assertGreater(drive(e, frames), 0.1)

    def test_water_and_roof_scrape(self):
        self.assertGreater(self.feel("Asphalt", water=0.8), 0.05)
        self.assertGreater(self.feel("Asphalt", top_contact=True), 0.05)

    def test_other_games_feel_nothing(self):
        self.assertEqual(drive(make(SurfaceEffect), [Telemetry(active=True, speed=30.0)] * 20), 0.0)


class LandingTests(unittest.TestCase):
    def jump(self, airtime, fall_speed):
        frames, t = [], 0.0
        for _ in range(10):
            frames.append(frame(t, ground_contact=True, vert_speed=0.0))
            t += 0.01
        steps = int(round(airtime / 0.01))
        for i in range(steps):
            frames.append(frame(t, ground_contact=False, vert_speed=-fall_speed * (i + 1) / steps))
            t += 0.01
        for _ in range(30):
            frames.append(frame(t, ground_contact=True, vert_speed=0.0))
            t += 0.01
        return drive(make(LandingEffect), frames)

    def test_a_real_landing_hits(self):
        self.assertGreater(self.jump(0.6, 10.0), 0.2)

    def test_harder_landings_hit_harder(self):
        self.assertGreater(self.jump(0.6, 14.0), self.jump(0.6, 4.0) * 1.3)

    def test_tiny_hops_and_soft_touch_downs_do_nothing(self):
        self.assertEqual(self.jump(0.05, 10.0), 0.0)
        self.assertEqual(self.jump(0.6, 1.0), 0.0)

    def test_other_games_never_land(self):
        self.assertEqual(drive(make(LandingEffect), [Telemetry(active=True, speed=30.0)] * 20), 0.0)


class BoostTests(unittest.TestCase):
    def test_a_turbo_pad_surges_once(self):
        e = make(BoostEffect)
        frames = [frame(i * 0.01, turbo=False) for i in range(5)]
        frames += [frame(0.05 + i * 0.01, turbo=True) for i in range(80)]
        self.assertGreater(drive(e, frames), 0.3)
        self.assertLessEqual(len(e.surge.voices), 1, "holding the turbo must not retrigger the surge")

    def test_reactor_boost_hums_while_it_lasts(self):
        e = make(BoostEffect)
        frames = [frame(i * 0.01, reactor_level=2) for i in range(100)]
        drive(e, frames)
        tail = [e.render(480, frames[-1]) for _ in range(10)]
        self.assertGreater(max(float(np.max(np.abs(y))) for y in tail), 0.2)

    def test_nothing_without_a_boost(self):
        self.assertEqual(drive(make(BoostEffect), [frame(i * 0.01) for i in range(30)]), 0.0)


class PresetTests(unittest.TestCase):
    def test_off_for_calibrated_games_and_on_for_trackmania(self):
        for name in ("surface", "landing", "boost"):
            for game, folder in (("forza", "forza_motorsport"), ("forza_horizon5", "forza_horizon"),
                                 ("beamng", "beamng")):
                cfg = config.load(None)
                config.apply_profile(cfg, PROJECT / "profiles" / folder / "profile.json", preset=game)
                self.assertFalse(cfg["effects"][name]["enabled"], f"{name} must stay off for {game}")
            cfg = config.load(None)
            config.apply_profile(cfg, PROJECT / "profiles" / "trackmania" / "profile.json", preset="trackmania")
            self.assertTrue(cfg["effects"][name]["enabled"], f"{name} should be on for Trackmania")


if __name__ == "__main__":
    unittest.main()
