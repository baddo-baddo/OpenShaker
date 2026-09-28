"""Trackmania source features: engine, boost, water, landing data, windowed accel, spin and lock."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.sources.trackmania import parse_snapshot, surface_name   # noqa: E402


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


def snap(t_ms, fwd=30.0, vy=0.0, rot=100.0, steer=0.0, brake=0.0, slip=0.0, extra=None, nested=None,
         material=16):
    """A car pointing +z; `rot` is every wheel's rotation speed, `vy` world vertical speed."""
    data = {"available": True, "worldVel": vec(0.0, vy, fwd), "left": vec(-1.0, 0.0, 0.0),
            "up": vec(0.0, 1.0, 0.0), "dir": vec(0.0, 0.0, 1.0), "frontSpeed": fwd, "rpm": 8000.0,
            "gear": 4, "throttle": 1.0, "brake": brake, "steer": steer, "groundContact": True}
    for name in ("FL", "FR", "RL", "RR"):
        data[name] = {"slip": slip, "damper": 0.1, "groundContactMaterial": material, "wheelRotSpeed": rot}
    if extra:
        data.update(extra)
    if nested:
        data["vehicleState"] = nested
    return {"type": "snapshot", "source": "vehicle_state", "t": t_ms, "data": data}


class CarStateTests(unittest.TestCase):
    def test_engine_off_in_both_layouts(self):
        self.assertFalse(parse_snapshot(snap(1000, extra={"engineOn": False}), {}).engine_running)
        self.assertFalse(parse_snapshot(snap(1000, nested={"engine": {"engineOn": False}}), {}).engine_running)
        self.assertTrue(parse_snapshot(snap(1000), {}).engine_running, "absent means running")

    def test_turbo_and_reactor_in_both_layouts(self):
        flat = parse_snapshot(snap(1000, extra={"isTurbo": True, "reactorBoostLvl": "Lvl2"}), {})
        self.assertTrue(flat.extra["turbo"])
        self.assertEqual(flat.extra["reactor_level"], 2)
        nested = parse_snapshot(snap(1000, nested={"engine": {"isTurbo": True},
                                                    "reactor": {"boostLvl": "Lvl1", "boostLvlValue": 1}}), {})
        self.assertTrue(nested.extra["turbo"])
        self.assertEqual(nested.extra["reactor_level"], 1)
        self.assertEqual(parse_snapshot(snap(1000, extra={"reactorBoostLvl": "None"}), {}).extra["reactor_level"], 0)

    def test_water_roof_and_burnout(self):
        t = parse_snapshot(snap(1000, extra={"waterImmersionCoef": 0.6, "isTopContact": True,
                                             "wheelsBurning": True}), {})
        self.assertAlmostEqual(t.extra["water"], 0.6)
        self.assertTrue(t.extra["top_contact"])
        self.assertTrue(t.extra["wheels_burning"])
        n = parse_snapshot(snap(1000, nested={"water": {"immersionCoef": 0.4}, "contact": {"isTopContact": False}}), {})
        self.assertAlmostEqual(n.extra["water"], 0.4)
        self.assertFalse(n.extra["top_contact"])

    def test_vertical_speed_and_ground_contact(self):
        t = parse_snapshot(snap(1000, vy=-8.0, extra={"groundContact": False, "groundDist": 3.5}), {})
        self.assertEqual(t.extra["vert_speed"], -8.0)
        self.assertFalse(t.extra["ground_contact"])
        self.assertEqual(t.extra["ground_dist"], 3.5)

    def test_surface_names_follow_material_ids(self):
        t = parse_snapshot(snap(1000, material=6), {})
        self.assertEqual(t.extra["materials"], [6, 6, 6, 6])
        self.assertEqual(t.extra["surfaces"], [surface_name(6)] * 4)


class WindowedAccelTests(unittest.TestCase):
    def test_needs_a_full_window_then_measures_across_it(self):
        state, results = {}, []
        for i in range(8):                                           # 5 ms apart, gaining 10 m/s^2
            results.append(parse_snapshot(snap(1000 + 5 * i, fwd=30.0 + 0.05 * i), state).accel_long)
        self.assertEqual(results[1], 0.0, "5 ms of history is not a window")
        self.assertAlmostEqual(results[4], 10.0, places=3)
        self.assertAlmostEqual(results[7], 10.0, places=3)

    def test_a_crash_between_sparse_frames_is_still_seen(self):
        state = {}
        parse_snapshot(snap(1000, fwd=40.0), state)
        self.assertLess(parse_snapshot(snap(1030, fwd=0.0), state).accel_long, -1000.0)


class SpinAndLockTests(unittest.TestCase):
    def learn(self, state):
        for i in range(30):                                          # rolling straight: radius 0.30 m
            parse_snapshot(snap(1000 + 10 * i, fwd=30.0, rot=100.0), state)

    def test_learns_the_rolling_radius_and_reads_no_slip(self):
        state = {}
        self.learn(state)
        self.assertTrue(all(abs(r - 0.3) < 1e-6 for r in state["radius"]))
        t = parse_snapshot(snap(1310, fwd=30.0, rot=100.0), state)
        self.assertTrue(all(abs(s) < 1e-6 for s in t.slip_ratio))

    def test_wheelspin_reads_positive(self):
        state = {}
        self.learn(state)
        self.assertGreater(min(parse_snapshot(snap(1310, fwd=5.0, rot=100.0), state).slip_ratio), 1.0)

    def test_lock_under_braking_reads_negative(self):
        state = {}
        self.learn(state)
        self.assertLess(max(parse_snapshot(snap(1310, fwd=30.0, rot=20.0, brake=1.0), state).slip_ratio), -1.0)

    def test_no_learning_while_steering_or_sliding(self):
        state = {}
        parse_snapshot(snap(1000, fwd=30.0, rot=100.0, steer=0.8), state)
        parse_snapshot(snap(1010, fwd=30.0, rot=100.0, slip=0.3), state)
        self.assertEqual(state["radius"], [0.0, 0.0, 0.0, 0.0])

    def test_the_radius_survives_a_menu(self):
        state = {}
        self.learn(state)
        menu = snap(1400)
        menu["data"]["available"] = False
        parse_snapshot(menu, state)
        self.assertTrue(all(abs(r - 0.3) < 1e-6 for r in state["radius"]))


if __name__ == "__main__":
    unittest.main()
