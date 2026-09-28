"""The grip-limit warning: builds before the slide, goes quiet once sliding, off for calibrated games."""
import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from openshaker import config                                  # noqa: E402
from openshaker.effects.racing import GripMarginEffect          # noqa: E402
from openshaker.telemetry import Telemetry                      # noqa: E402

SR = 48000


def tm_frame(lat=0.0, body=0.0, slip=(0.0, 0.0, 0.0, 0.0), speed=30.0):
    """A Trackmania frame: sideways accel in m/s^2, body slip in degrees, SlipCoef per wheel."""
    t = Telemetry(active=True, speed=speed, accel_lat=lat)
    t.extra = {"slip_coef": list(slip), "body_slip_deg": body}
    return t


def effect(**params):
    cfg = dict(config.DEFAULTS["effects"]["grip_margin"])
    cfg.update(enabled=True, smooth=1.0)                       # no smoothing: a frame is its own value
    cfg.update(params)
    return GripMarginEffect(cfg, SR)


def peak(e, frame, blocks=30):
    e.on_frame(frame, None, 0.01)
    out = [e.render(480, frame) for _ in range(blocks)]
    return float(max(np.max(np.abs(y)) if y is not None else 0.0 for y in out))


class TrackmaniaGripTests(unittest.TestCase):
    def test_silent_well_inside_the_limit(self):
        self.assertEqual(peak(effect(), tm_frame(lat=5.0)), 0.0)       # 25 % of the 20 m/s^2 limit

    def test_grows_as_the_limit_approaches(self):
        near = peak(effect(), tm_frame(lat=15.0))                       # 75 %
        nearer = peak(effect(), tm_frame(lat=19.5))                     # 98 %
        self.assertGreater(near, 0.0)
        self.assertGreater(nearer, near * 1.5, "the last stretch should be clearly stronger")

    def test_body_slip_alone_warns(self):
        self.assertGreater(peak(effect(), tm_frame(body=5.5)), 0.0)    # 92 % of 6 degrees

    def test_goes_quiet_the_moment_the_tyres_let_go(self):
        e = effect()
        self.assertGreater(peak(e, tm_frame(lat=19.5)), 0.0)
        e.on_frame(tm_frame(lat=19.5, slip=(0.2, 0.0, 0.0, 0.0)), None, 0.01)
        self.assertEqual(e._margin, 0.0, "once SlipCoef is positive the slide effect takes over")
        tail = [e.render(480, tm_frame()) for _ in range(5)]
        self.assertTrue(all(y is None or float(np.max(np.abs(y))) < 1e-6 for y in tail[1:]))

    def test_slow_cars_do_not_warn(self):
        self.assertEqual(peak(effect(), tm_frame(lat=19.5, speed=3.0)), 0.0)

    def test_pulses_faster_nearer_the_limit(self):
        def pulse_rate(lat):
            e = effect(pulse_depth=1.0, curve_pow=1.0)
            e.on_frame(tm_frame(lat=lat), None, 0.01)
            y = np.concatenate([e.render(480, tm_frame(lat=lat)) for _ in range(100)])   # 1 s
            envelope = np.abs(y).reshape(-1, 480).max(axis=1)
            return int(np.sum(np.diff(np.sign(envelope - envelope.mean())) > 0))
        self.assertGreater(pulse_rate(19.5), pulse_rate(13.0))


def surface_frame(lat=0.0, body=0.0, surfaces=("Asphalt",) * 4, contact=(True,) * 4, slip=(0.0,) * 4):
    """A Trackmania frame as the live source sends it, with a surface name per wheel."""
    t = tm_frame(lat=lat, body=body, slip=slip)
    t.extra.update(surfaces=list(surfaces), wheel_contact=list(contact))
    return t


class LooseSurfaceTests(unittest.TestCase):
    """On tarmac the Stadium car corners at up to 90 m/s^2 without letting go, so the warning is for
    loose surfaces only - where the car does slide out of a corner."""

    def test_silent_on_tarmac_however_hard_the_corner(self):
        for lat, body in ((60.0, 0.5), (90.0, 1.0), (19.5, 5.9)):
            self.assertEqual(peak(effect(), surface_frame(lat=lat, body=body)), 0.0, (lat, body))

    def test_warns_on_dirt_near_its_limit(self):
        dirt_lat = GripMarginEffect.LOOSE["Dirt"][0]
        e = effect()
        self.assertEqual(peak(e, surface_frame(lat=0.3 * dirt_lat, surfaces=("Dirt",) * 4)), 0.0)
        self.assertGreater(peak(effect(), surface_frame(lat=0.95 * dirt_lat, surfaces=("Dirt",) * 4)), 0.0)

    def test_ice_warns_much_earlier_than_dirt(self):
        lat = 0.9 * GripMarginEffect.LOOSE["Ice"][0] * 1.3
        self.assertGreater(peak(effect(), surface_frame(lat=lat, surfaces=("RoadIce",) * 4)), 0.0)
        self.assertEqual(peak(effect(), surface_frame(lat=lat, surfaces=("Dirt",) * 4)), 0.0)

    def test_needs_half_the_wheels_on_the_loose_stuff(self):
        lat = 0.95 * GripMarginEffect.LOOSE["Grass"][0]
        one = surface_frame(lat=lat, surfaces=("Grass", "Asphalt", "Asphalt", "Asphalt"))
        two = surface_frame(lat=lat, surfaces=("Grass", "Asphalt", "Grass", "Asphalt"))
        self.assertEqual(peak(effect(), one), 0.0)
        self.assertGreater(peak(effect(), two), 0.0)

    def test_wheels_in_the_air_do_not_count(self):
        lat = 0.95 * GripMarginEffect.LOOSE["Grass"][0]
        frame = surface_frame(lat=lat, surfaces=("Grass", "Grass", "XXX_Null", "XXX_Null"),
                              contact=(True, True, False, False))
        self.assertGreater(peak(effect(), frame), 0.0)                  # both wheels on the ground are on grass

    def test_the_profile_can_retune_or_switch_off_a_surface(self):
        lat = 0.95 * GripMarginEffect.LOOSE["Dirt"][0]
        dirt = surface_frame(lat=lat, surfaces=("Dirt",) * 4)
        self.assertEqual(peak(effect(surfaces={"Dirt": [40.0, 10.0]}), dirt), 0.0)
        self.assertEqual(peak(effect(surfaces={"Dirt": [0, 0]}), dirt), 0.0)
        self.assertGreater(peak(effect(surfaces={"Asphalt": [20.0, 6.0]}), surface_frame(lat=19.5)), 0.0)

    def test_min_share_zero_is_safe_on_tarmac(self):
        """With min_share 0 an empty loose list used to raise, freezing the last margin on."""
        e = effect(min_share=0.0)
        lat = 0.95 * GripMarginEffect.LOOSE["Dirt"][0]
        self.assertGreater(peak(e, surface_frame(lat=lat, surfaces=("Dirt",) * 4)), 0.0)
        e.on_frame(surface_frame(lat=0.0), None, 0.01)
        self.assertEqual(e._margin, 0.0)

    def test_a_renamed_material_warns_like_its_name(self):
        lat = 0.95 * GripMarginEffect.LOOSE["Dirt"][0]
        frame = surface_frame(lat=lat, surfaces=("id 99",) * 4)
        frame.extra["materials"] = [99] * 4
        self.assertEqual(peak(effect(), frame), 0.0)
        self.assertGreater(peak(effect(materials={"99": "Dirt"}), frame), 0.0)

    def test_still_hands_over_to_the_slide(self):
        lat = 0.95 * GripMarginEffect.LOOSE["Dirt"][0]
        e = effect()
        self.assertGreater(peak(e, surface_frame(lat=lat, surfaces=("Dirt",) * 4)), 0.0)
        e.on_frame(surface_frame(lat=lat, surfaces=("Dirt",) * 4, slip=(1.0, 0.0, 0.0, 0.0)), None, 0.01)
        self.assertEqual(e._margin, 0.0)


class OtherGamesTests(unittest.TestCase):
    def test_uses_normalised_slip_when_there_is_no_slip_coef(self):
        t = Telemetry(active=True, speed=30.0, slip_angle=[0.85, 0.0, 0.0, 0.0])
        self.assertGreater(peak(effect(), t), 0.0)
        sliding = Telemetry(active=True, speed=30.0, slip_angle=[1.3, 0.0, 0.0, 0.0])
        self.assertEqual(peak(effect(), sliding), 0.0)

    def test_off_for_every_calibrated_game(self):
        """HaptiConnect has no such effect, so the matched profiles must not suddenly gain one."""
        for game, folder in (("forza", "forza_motorsport"), ("forza_horizon5", "forza_horizon"),
                             ("beamng", "beamng")):
            cfg = config.load(None)
            config.apply_profile(cfg, PROJECT / "profiles" / folder / "profile.json", preset=game)
            self.assertFalse(cfg["effects"]["grip_margin"]["enabled"], game)

    def test_on_for_trackmania(self):
        cfg = config.load(None)
        config.apply_profile(cfg, PROJECT / "profiles" / "trackmania" / "profile.json", preset="trackmania")
        self.assertTrue(cfg["effects"]["grip_margin"]["enabled"])


if __name__ == "__main__":
    unittest.main()
