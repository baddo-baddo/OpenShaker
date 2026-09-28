"""Tuning the Trackmania preset from a recorded drive: engine range, jumps, crashes, surfaces, --apply."""
import csv
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from openshaker import tm_tune                                      # noqa: E402
from openshaker.record import CSV_FIELDS, tele_row                  # noqa: E402
from openshaker.sources.trackmania import parse_snapshot            # noqa: E402


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


def message(t, fwd, vy, rpm, damper, material, grounded, car="CarSport"):
    data = {"available": True, "worldVel": vec(0.0, vy, fwd), "left": vec(-1.0, 0.0, 0.0),
            "up": vec(0.0, 1.0, 0.0), "dir": vec(0.0, 0.0, 1.0), "rpm": rpm, "gear": 4, "throttle": 1.0,
            "brake": 0.0, "steer": 0.0, "groundContact": grounded}
    if car:
        data["vehicleTypeName"] = car
    for name in ("FL", "FR", "RL", "RR"):
        data[name] = {"slip": 0.0, "damper": damper, "groundContactMaterial": material, "wheelRotSpeed": fwd / 0.3}
    return {"type": "snapshot", "source": "vehicle_state", "t": t * 1000.0, "data": data}


def recorded_drive(car="CarSport"):
    """6 s at 100 Hz: asphalt with the revs climbing, dirt, a jump, a landing, then into a wall."""
    rows, state, clock = [], {}, [0.0]

    def add(**kw):
        t = clock[0]
        msg = message(t, car=car, **kw)
        tele = parse_snapshot(msg, state)
        tele.t, tele.source, tele.raw = t, "trackmania", json.dumps(msg).encode("utf-8")
        rows.append(tele_row(tele, 0.0))
        clock[0] = round(t + 0.01, 6)

    for i in range(200):
        add(fwd=30.0, vy=0.0, rpm=2000.0 + 8500.0 * i / 199, damper=0.10, material=16, grounded=True)
    for i in range(200):
        add(fwd=30.0, vy=0.0, rpm=9000.0, damper=0.10 + 0.02 * math.sin(i * 1.3), material=6, grounded=True)
    for i in range(50):
        add(fwd=30.0, vy=-8.0 * (i + 1) / 50, rpm=9000.0, damper=0.10, material=16, grounded=False)
    for i in range(50):
        add(fwd=30.0, vy=0.0, rpm=9000.0, damper=0.10, material=16, grounded=True)
    for i in range(80):
        add(fwd=0.0, vy=0.0, rpm=1000.0, damper=0.10, material=16, grounded=True)
    return rows


class TuneTests(unittest.TestCase):
    car = "CarSport"

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        with (self.dir / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_FIELDS)
            writer.writerows(recorded_drive(self.car))
        self.frames = tm_tune.load_frames(self.dir)

    def apply(self, *extra):
        """Run --apply against a copy of the shipped profile; returns the written profile."""
        profile = self.dir / "profile.json"
        shutil.copy(PROJECT / "profiles" / "trackmania" / "profile.json", profile)
        real = tm_tune.PROFILE
        tm_tune.PROFILE = profile                                         # never touch the real file
        self.addCleanup(setattr, tm_tune, "PROFILE", real)
        self.assertEqual(tm_tune.main([str(self.dir), "--apply", *extra]), 0)
        return json.loads(profile.read_text(encoding="utf-8"))

    def test_engine_range(self):
        eng = tm_tune.engine_range(self.frames)
        self.assertEqual(eng["idle_rpm"], 1000.0)
        self.assertTrue(10400.0 <= eng["max_rpm"] <= 10600.0, eng)

    def test_finds_the_jump(self):
        land = tm_tune.landings(self.frames)
        self.assertEqual(land["count"], 1)
        self.assertAlmostEqual(land["falls"][2], 8.0, places=3)
        self.assertAlmostEqual(land["airtime_max"], 0.5, delta=0.02)

    def test_the_biggest_jolt_is_the_crash(self):
        imp = tm_tune.impacts(self.frames)
        self.assertAlmostEqual(imp["biggest"][0][1], 5.0, delta=0.05)

    def test_dirt_is_rougher_than_asphalt(self):
        stats = tm_tune.surfaces(self.frames)
        rough = {m: (sorted(s["rough"])[len(s["rough"]) // 2] if s["rough"] else 0.0) for m, s in stats.items()}
        self.assertGreater(rough[6], rough[16])

    def test_apply_writes_the_profile(self):
        shipped = json.loads((PROJECT / "profiles" / "trackmania" / "profile.json").read_text(encoding="utf-8"))
        written = self.apply("--name", "6=Dirt")
        effects = written["effects"]
        self.assertEqual(effects["surface"]["materials"], {"6": "Dirt"})
        self.assertEqual(effects["grip_margin"]["materials"], {"6": "Dirt"}, "the warning names surfaces the same way")
        self.assertAlmostEqual(effects["landing"]["v_min"], 8.0, places=2)
        self.assertEqual(effects["engine"], shipped["effects"]["engine"], "other effect settings must survive")

    def test_a_standing_rpm_near_zero_is_no_idle(self):
        """Trackmania's rpm falls to ~0 standing still; writing that as idle_rpm would be dropped anyway."""
        frames = [{"rpm": 80.0, "speed": 0.0, "gear": 0, "extra": {}} for _ in range(40)]
        frames += [{"rpm": 3000.0 + 50 * i, "speed": 30.0, "gear": 2, "extra": {}} for i in range(60)]
        self.assertIsNone(tm_tune.engine_range(frames)["idle_rpm"])

    def test_car_constants_go_into_the_profile_by_car_type(self):
        car = self.apply()["cars"]["CarSport"]
        self.assertEqual(car["idle_rpm"], 1000.0)
        self.assertTrue(10400.0 <= car["max_rpm"] <= 10600.0, car)
        self.assertAlmostEqual(car["damper_range_m"], 0.04, delta=0.002)   # 0.10 +- 0.02 m on dirt

    def test_apply_never_writes_a_config_file(self):
        self.assertFalse(hasattr(tm_tune, "CONFIG"), "car constants ship in the profile, not config.json")
        before = set(self.dir.iterdir())
        self.apply()
        self.assertEqual(set(self.dir.iterdir()) - before, {self.dir / "profile.json"})

    def test_bad_name_argument_is_rejected(self):
        self.assertEqual(tm_tune.main([str(self.dir), "--name", "dirt"]), 2)

    def test_only_writes_the_named_parts(self):
        shipped = json.loads((PROJECT / "profiles" / "trackmania" / "profile.json").read_text(encoding="utf-8"))
        written = self.apply("--only", "landings")
        self.assertAlmostEqual(written["effects"]["landing"]["v_min"], 8.0, places=2)
        self.assertEqual(written["effects"]["suspension"], shipped["effects"]["suspension"])
        self.assertEqual(written["effects"]["impact"], shipped["effects"]["impact"])
        self.assertEqual(written.get("cars"), shipped.get("cars"))

    def test_an_unknown_part_is_rejected(self):
        self.assertEqual(tm_tune.main([str(self.dir), "--apply", "--only", "landings,wings"]), 2)

    def test_analyse_and_apply_to_match_the_command(self):
        """drive_report proposes through analyse/apply_to; they must write what --apply writes."""
        profile = json.loads((PROJECT / "profiles" / "trackmania" / "profile.json").read_text(encoding="utf-8"))
        res = tm_tune.analyse(self.frames, profile)
        by_hand = json.loads(json.dumps(profile))
        tm_tune.apply_to(by_hand, res, tm_tune.PARTS, {}, self.dir.name)
        by_command = self.apply()
        by_hand["meta"].pop("tuned_from"), by_command["meta"].pop("tuned_from")
        self.assertEqual(by_hand, by_command)


class RoughnessTests(unittest.TestCase):
    def test_a_surface_that_is_mostly_still_frames_still_shows_its_bumps(self):
        """Frames repeat and damperLen comes in 1 mm steps, so most per-frame speeds are exactly 0."""
        self.assertEqual(tm_tune.roughness([0.0] * 60 + [0.5] * 40), 0.5)
        self.assertEqual(tm_tune.roughness([]), 0.0)


class UnknownCarTests(TuneTests):
    """A log without vehicleType still tunes the effects, but writes no car constants."""
    car = ""

    def test_car_constants_go_into_the_profile_by_car_type(self):
        written = self.apply()
        self.assertNotIn("", written.get("cars", {}))
        self.assertEqual(written.get("cars", {}), json.loads(
            (PROJECT / "profiles" / "trackmania" / "profile.json").read_text(encoding="utf-8")).get("cars", {}))

    def test_engine_range_is_still_reported(self):
        self.assertIn("", tm_tune.engines(self.frames))


class BumpSpeedTests(unittest.TestCase):
    """Bump thresholds come from how fast settled wheels move - not from a wheel that is flying or
    settling after a landing, whose parsed travel is held and creeps."""

    def frame(self, t, damper, settled=True):
        return {"t": t, "speed": 30.0, "damper": [0.0] * 4,
                "extra": {"car": "CarSport", "ground_contact": True, "damper_len": [damper] * 4,
                          "wheel_settled": [settled] * 4}}

    def test_only_settled_wheels_count(self):
        frames = [self.frame(0.01 * i, 0.02 + 0.01 * (i % 2)) for i in range(300)]       # a steady buzz
        calm = tm_tune.suspension(frames)
        frames += [self.frame(3.0 + 0.01 * i, 0.19 * (i % 2), settled=False) for i in range(300)]
        self.assertEqual(tm_tune.suspension(frames)["threshold"], calm["threshold"])

    def test_it_reads_the_raw_damper_not_the_held_travel(self):
        frames = [self.frame(0.01 * i, 0.02 + 0.01 * (i % 2)) for i in range(300)]
        for f in frames:
            f["damper"] = [0.05] * 4                                        # what the effects saw: held still
        self.assertGreater(tm_tune.suspension(frames)["threshold"], 0.2)


class MixedCarTests(unittest.TestCase):
    def test_each_car_gets_its_own_constants(self):
        frames = [{"rpm": 5000.0 + i, "speed": 20.0, "gear": 3, "extra": {"car": "CarSport"}} for i in range(60)]
        frames += [{"rpm": 3000.0 + i, "speed": 20.0, "gear": 3, "extra": {"car": "CarSnow"}} for i in range(60)]
        engs = tm_tune.engines(frames)
        self.assertEqual(set(engs), {"CarSport", "CarSnow"})
        self.assertGreater(engs["CarSport"]["max_rpm"], engs["CarSnow"]["max_rpm"])


if __name__ == "__main__":
    unittest.main()
