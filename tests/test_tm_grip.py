"""Learning grip limits from a recorded Trackmania drive: finding the moments the car let go."""
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from openshaker import tm_grip                                     # noqa: E402
from openshaker.record import CSV_FIELDS, tele_row                  # noqa: E402
from openshaker.sources.trackmania import parse_snapshot            # noqa: E402

DT = 0.01                                                          # a 100 Hz recording


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


def row(t, lat, slip=0.0, side=0.0, grounded=True, material=16, speed=30.0):
    """One logged frame: sideways accel `lat`, SlipCoef `slip` on the front wheels, sideways speed `side`."""
    msg = {"type": "snapshot", "source": "vehicle_state", "t": t * 1000.0,
           "data": {"available": True, "worldVel": vec(side, 0.0, speed), "left": vec(-1.0, 0.0, 0.0),
                    "up": vec(0.0, 1.0, 0.0), "dir": vec(0.0, 0.0, 1.0), "groundContact": grounded,
                    "FL": {"slip": slip, "groundContactMaterial": material},
                    "FR": {"slip": slip, "groundContactMaterial": material},
                    "RL": {"slip": 0.0, "groundContactMaterial": material},
                    "RR": {"slip": 0.0, "groundContactMaterial": material}}}
    tele = parse_snapshot(msg, {})
    tele.t, tele.source, tele.accel_lat = t, "trackmania", lat
    tele.raw = json.dumps(msg).encode("utf-8")
    return tele_row(tele, 0.0)


def corner(t, peak_lat, peak_side=0.0, build_s=1.0, slide_s=0.3, grip_after_s=1.0, material=16, jolt=0.0):
    """Straight, load builds to `peak_lat` over `build_s`, the fronts let go, then grip returns.
    `jolt` adds a sudden sideways kick at the moment it lets go, as a wall hit does."""
    rows = []
    for i in range(int(build_s / DT)):
        k = (i + 1) / int(build_s / DT)
        rows.append(row(t, peak_lat * k, side=peak_side * k, material=material))
        t += DT
    for i in range(int(slide_s / DT)):
        rows.append(row(t, peak_lat + (jolt if i == 0 else 0.0), slip=0.3, side=peak_side, material=material))
        t += DT
    for _ in range(int(grip_after_s / DT)):
        rows.append(row(t, 0.0, material=material))
        t += DT
    return rows, t


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rows):
        with (self.dir / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
            import csv
            w = csv.writer(f)
            w.writerow(CSV_FIELDS)
            w.writerows(rows)

    def test_finds_each_moment_the_car_let_go(self):
        rows, t = [row(0.0, 0.0)], DT
        first, t = corner(t, peak_lat=16.0, peak_side=2.0)
        second, t = corner(t, peak_lat=20.0, peak_side=4.0)
        self.write(rows + first + second)
        frames = tm_grip.load_frames(self.dir)
        events = tm_grip.find_onsets(frames, min_speed=8.0, lookback_s=0.3, smooth=1.0)
        self.assertEqual(len(events), 2)
        self.assertAlmostEqual(events[0]["lat"], 16.0, delta=0.2)            # the load just before letting go
        self.assertAlmostEqual(events[1]["lat"], 20.0, delta=0.2)
        self.assertAlmostEqual(events[1]["body"], math.degrees(math.atan2(4.0, 30.0)), delta=0.3)
        self.assertEqual(events[0]["surface"], "Asphalt")

    def test_a_slide_that_did_not_follow_real_grip_is_not_counted(self):
        rows, t = corner(0.0, peak_lat=18.0, grip_after_s=0.1)              # regrips for only 0.1 s ...
        again = []
        for _ in range(20):                                                  # ... then slides again
            again.append(row(t, 18.0, slip=0.3))
            t += DT
        self.write(rows + again)
        events = tm_grip.find_onsets(tm_grip.load_frames(self.dir), 8.0, 0.3, 1.0)
        self.assertEqual(len(events), 1, "a second slide 0.1 s after the first says nothing new about the limit")

    def test_airborne_frames_break_the_run_up(self):
        rows, t = [], 0.0
        for i in range(100):
            rows.append(row(t, 15.0, grounded=(i < 60 or i > 95)))          # a jump in the middle of the run-up
            t += DT
        rows.append(row(t, 15.0, slip=0.3))                                  # lands and slides at once
        self.write(rows)
        self.assertEqual(tm_grip.find_onsets(tm_grip.load_frames(self.dir), 8.0, 0.3, 1.0), [])

    def apply(self, rows):
        self.write(rows)
        profile = self.dir / "profile.json"
        shutil.copy(PROJECT / "profiles" / "trackmania" / "profile.json", profile)
        real = tm_grip.PROFILE
        tm_grip.PROFILE = profile                                            # never touch the real one
        self.addCleanup(setattr, tm_grip, "PROFILE", real)
        self.assertEqual(tm_grip.main([str(self.dir), "--apply", "--smooth", "1.0"]), 0)
        return json.loads(profile.read_text(encoding="utf-8"))["effects"]["grip_margin"]

    def test_apply_writes_each_loose_surface_median_into_the_profile(self):
        rows, t = [row(0.0, 0.0, material=6)], DT
        for peak in (14.0, 18.0, 22.0):                                      # three slides on Dirt
            more, t = corner(t, peak_lat=peak, material=6)
            rows += more
        grip = self.apply(rows)
        self.assertAlmostEqual(grip["surfaces"]["Dirt"][0], 18.0, delta=0.2)
        self.assertTrue(grip["enabled"])
        self.assertNotIn("lat_limit", grip, "tarmac has no single limit any more")

    def test_tarmac_slides_are_reported_but_never_written(self):
        rows, t = [row(0.0, 0.0)], DT
        for peak in (40.0, 60.0, 80.0):                                      # three slides on Asphalt
            more, t = corner(t, peak_lat=peak)
            rows += more
        self.assertNotIn("Asphalt", self.apply(rows).get("surfaces", {}))

    def test_a_surface_needs_three_slides(self):
        rows, t = [row(0.0, 0.0, material=2)], DT
        for peak in (12.0, 14.0):                                            # only two on Grass
            more, t = corner(t, peak_lat=peak, material=2)
            rows += more
        self.assertNotIn("Grass", self.apply(rows).get("surfaces", {}))

    def dirt_slides(self, material=6):
        rows, t = [row(0.0, 0.0, material=material)], DT
        for peak in (14.0, 18.0, 22.0):
            more, t = corner(t, peak_lat=peak, material=material)
            rows += more
        return rows

    def test_a_surface_switched_off_stays_off(self):
        self.write(self.dirt_slides())
        profile = self.dir / "profile.json"
        data = json.loads((PROJECT / "profiles" / "trackmania" / "profile.json").read_text(encoding="utf-8"))
        data["effects"]["grip_margin"]["surfaces"] = {"Dirt": [0, 0]}
        data["meta"]["grip_margin"] = "the user's own note"
        profile.write_text(json.dumps(data), encoding="utf-8")
        real = tm_grip.PROFILE
        tm_grip.PROFILE = profile
        self.addCleanup(setattr, tm_grip, "PROFILE", real)
        tm_grip.main([str(self.dir), "--apply", "--smooth", "1.0"])
        after = json.loads(profile.read_text(encoding="utf-8"))
        self.assertEqual(after["effects"]["grip_margin"]["surfaces"]["Dirt"], [0, 0])
        self.assertEqual(after["meta"]["grip_margin"], "the user's own note")

    def test_renamed_materials_are_learned_under_their_name(self):
        """A map whose dirt reports an id the table does not know, named Dirt in the profile."""
        grip = self.apply_with({"materials": {"99": "Dirt"}}, self.dirt_slides(material=99))
        self.assertAlmostEqual(grip["surfaces"]["Dirt"][0], 18.0, delta=0.2)

    def apply_with(self, grip_extra, rows):
        self.write(rows)
        profile = self.dir / "profile.json"
        data = json.loads((PROJECT / "profiles" / "trackmania" / "profile.json").read_text(encoding="utf-8"))
        data["effects"]["grip_margin"].update(grip_extra)
        profile.write_text(json.dumps(data), encoding="utf-8")
        real = tm_grip.PROFILE
        tm_grip.PROFILE = profile
        self.addCleanup(setattr, tm_grip, "PROFILE", real)
        self.assertEqual(tm_grip.main([str(self.dir), "--apply", "--smooth", "1.0"]), 0)
        return json.loads(profile.read_text(encoding="utf-8"))["effects"]["grip_margin"]

    def test_crashes_are_left_out(self):
        rows, t = [row(0.0, 0.0, material=6)], DT
        for peak in (14.0, 18.0, 22.0):
            more, t = corner(t, peak_lat=peak, material=6)
            rows += more
        for _ in range(3):                                                   # three wall hits on the same dirt
            more, t = corner(t, peak_lat=5.0, material=6, jolt=400.0)
            rows += more
        self.write(rows)
        frames = tm_grip.load_frames(self.dir)
        self.assertEqual(len(tm_grip.find_onsets(frames, 8.0, 0.3, 1.0, max_jolt=150.0)), 3)
        self.assertEqual(len(tm_grip.find_onsets(frames, 8.0, 0.3, 1.0)), 6)
        self.assertAlmostEqual(self.apply(rows)["surfaces"]["Dirt"][0], 18.0, delta=0.2)

    def test_non_trackmania_sessions_are_rejected(self):
        self.write([])
        self.assertEqual(tm_grip.main([str(self.dir)]), 1)


if __name__ == "__main__":
    unittest.main()
