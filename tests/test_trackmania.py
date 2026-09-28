"""Trackmania through Openplanet's Data Sender: both JSON layouts, the maths, and the live TCP client."""
import json
import math
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openshaker.sources.trackmania import (LANDING_QUIET_S, SETTLE_RATE, SETTLE_S,  # noqa: E402
                                         SLIDE_FULL_MPS, TELEPORT_QUIET_MS, TOUCHDOWN_ACCEL_MS,
                                         TrackmaniaSource, load_cars,
                                         parse_snapshot,
                                         setup_commands, wheel_contact)

LONG = ("frontLeft", "frontRight", "rearLeft", "rearRight")


def vec(x, y, z):
    return {"x": x, "y": y, "z": z}


def snapshot(t_ms, vel, slip=(0.0, 0.0, 0.0, 0.0), nested=False, available=True):
    """A car whose left axis is -x and forward axis is +z, so +x velocity is sliding to its right."""
    data = {"available": available, "t": t_ms, "worldVel": vec(*vel),
            "left": vec(-1.0, 0.0, 0.0), "up": vec(0.0, 1.0, 0.0), "dir": vec(0.0, 0.0, 1.0),
            "frontSpeed": vel[2], "rpm": 9000.0, "gear": 3, "throttle": 1.0, "brake": 0.0,
            "steer": 0.4, "groundContact": True}
    if nested:
        data["vehicleState"] = {"wheels": {name: {"slipCoef": s, "damperLen": 0.1, "groundContactMaterial": 16}
                                           for name, s in zip(LONG, slip)}}
    else:
        for name, s in zip(("FL", "FR", "RL", "RR"), slip):
            data[name] = {"slip": s, "damper": 0.1, "groundContactMaterial": 16, "wheelRotSpeed": 40.0}
    return {"type": "snapshot", "source": "vehicle_state", "t": t_ms, "data": data}


class ParseTests(unittest.TestCase):
    def test_flat_layout(self):
        t = parse_snapshot(snapshot(1000, (5.0, 0.0, 20.0), slip=(0.1, 0.2, 0.3, 0.4)), {})
        self.assertAlmostEqual(t.speed, math.hypot(5.0, 20.0), places=5)
        self.assertEqual(t.extra["slip_coef"], [0.1, 0.2, 0.3, 0.4])     # flat objects use "slip"
        self.assertAlmostEqual(t.susp_travel[0], 0.5)                     # damper 0.1 m / 0.2 m range
        self.assertEqual((t.rpm, t.gear, t.throttle), (9000.0, 3, 1.0))
        self.assertTrue(t.active)

    def test_nested_layout(self):
        t = parse_snapshot(snapshot(1000, (0.0, 0.0, 20.0), slip=(0.5, 0.6, 0.7, 0.8), nested=True), {})
        self.assertEqual(t.extra["slip_coef"], [0.5, 0.6, 0.7, 0.8])     # nested objects use "slipCoef"
        self.assertEqual(t.extra["materials"], [16, 16, 16, 16])

    def test_a_slide_is_as_strong_as_the_car_moves_sideways(self):
        """SlipCoef is all but on/off, so the slide's strength comes from the sideways speed."""
        gentle = parse_snapshot(snapshot(1000, (3.0, 0.0, 60.0), slip=(1.0, 1.0, 1.0, 1.0)), {})
        big = parse_snapshot(snapshot(1000, (20.0, 0.0, 30.0), slip=(1.0, 1.0, 1.0, 1.0)), {})
        gripping = parse_snapshot(snapshot(1000, (3.0, 0.0, 60.0)), {})
        self.assertAlmostEqual(gentle.slip_angle[0], 3.0 / SLIDE_FULL_MPS)
        self.assertEqual(big.slip_angle, [1.0] * 4)
        self.assertEqual(gripping.slip_angle, [0.0] * 4)

    def test_body_slip_angle_and_side(self):
        t = parse_snapshot(snapshot(1000, (5.0, 0.0, 20.0)), {})
        self.assertAlmostEqual(t.extra["side_speed"], 5.0)                # sliding to the car's right
        self.assertAlmostEqual(t.extra["body_slip_deg"], math.degrees(math.atan2(5.0, 20.0)), places=4)
        straight = parse_snapshot(snapshot(1000, (0.0, 0.0, 20.0)), {})
        self.assertAlmostEqual(straight.extra["body_slip_deg"], 0.0)

    def test_accelerations_are_in_the_car_frame(self):
        state = {}
        parse_snapshot(snapshot(1000, (0.0, 0.0, 20.0)), state)
        t = parse_snapshot(snapshot(1100, (1.0, 0.0, 21.0)), state)      # +1 m/s right, +1 forward in 0.1 s
        self.assertAlmostEqual(t.accel_long, 10.0, places=4)
        self.assertAlmostEqual(t.accel_lat, 10.0, places=4)               # +lat = right
        self.assertAlmostEqual(t.accel_vert, 0.0, places=4)

    def test_a_long_gap_does_not_fake_an_impact(self):
        state = {}
        parse_snapshot(snapshot(1000, (0.0, 0.0, 40.0)), state)
        t = parse_snapshot(snapshot(9000, (0.0, 0.0, 0.0)), state)       # paused 8 s, then stopped
        self.assertEqual(t.accel_long, 0.0)

    def test_unavailable_snapshots_are_skipped_and_reset_state(self):
        state = {"vel": (0.0, 0.0, 30.0), "t_ms": 900.0}
        self.assertIsNone(parse_snapshot(snapshot(1000, (0.0, 0.0, 0.0), available=False), state))
        self.assertEqual(state, {})

    def test_other_messages_are_ignored(self):
        self.assertIsNone(parse_snapshot({"type": "ack"}, {}))
        self.assertIsNone(parse_snapshot({"type": "snapshot", "source": "camera", "data": {}}, {}))

    def test_service_status_is_not_a_frame(self):
        self.assertIsNone(parse_snapshot(service_status(), {}))


def wheel_frame(t_ms, dampers, air=(False, False, False, False), slip=(0.0, 0.0, 0.0, 0.0), rot=66.7,
                vy=0.0, dc=None, pos=None):
    """A Trackmania 2020 frame the way Data Sender 2.0 sends it: per-wheel `falling` state, material
    XXX_Null (80) for a wheel in the air, dampers in metres. The car rolls straight at 20 m/s
    (falling at -vy); `dc` is vehicleState.dynamics.discontinuityCount, `pos` the car's position."""
    msg = snapshot(t_ms, (0.0, vy, 20.0))
    data = msg["data"]
    data["steer"] = 0.0
    data["groundContact"] = not all(air)
    if dc is not None:
        data["vehicleState"] = {"dynamics": {"discontinuityCount": dc}}
    if pos is not None:
        data["pos"] = vec(*pos)
    for name, d, a, s in zip(("FL", "FR", "RL", "RR"), dampers, air, slip):
        data[name] = {"slip": s, "damper": d, "groundContactMaterial": 80 if a else 16, "wheelRotSpeed": rot,
                      "falling": "FallingAir" if a else "RestingGround"}
    return msg


def fly(state, t_ms, seconds, stretched=0.19, step_ms=5, vy=-6.0):
    """Take off, stretch the dampers in the air for `seconds` falling at -vy m/s, return the time of touchdown."""
    for _ in range(int(seconds * 1000 / step_ms)):
        parse_snapshot(wheel_frame(t_ms, [stretched] * 4, air=(True,) * 4, rot=150.0, vy=vy), state)
        t_ms += step_ms
    return t_ms


def drive(state, t_ms, frames, step_ms=5):
    """Feed (dampers, air) pairs; return (travel of wheel 0 after each, time after the last)."""
    out = []
    for dampers, air in frames:
        out.append(parse_snapshot(wheel_frame(t_ms, dampers, air=air), state).susp_travel[0])
        t_ms += step_ms
    return out, t_ms


class WheelContactTests(unittest.TestCase):
    def test_trackmania_falling_state(self):
        self.assertTrue(wheel_contact({"falling": "RestingGround"}, grounded=False))
        self.assertTrue(wheel_contact({"falling": "GlidingGround"}, grounded=False))
        self.assertTrue(wheel_contact({"falling": "RestingWater"}, grounded=False))
        self.assertFalse(wheel_contact({"falling": "FallingAir"}, grounded=True))
        self.assertFalse(wheel_contact({"falling": "FallingWater"}, grounded=True))

    def test_older_layouts(self):
        self.assertFalse(wheel_contact({"groundContact": False}, grounded=True))    # Maniaplanet / Turbo
        self.assertFalse(wheel_contact({"groundContactMaterial": 80}, grounded=True))   # XXX_Null
        self.assertTrue(wheel_contact({"groundContactMaterial": 16}, grounded=True))
        self.assertFalse(wheel_contact({}, grounded=False))

    def test_reported_per_wheel(self):
        t = parse_snapshot(wheel_frame(1000, [0.02] * 4, air=(True, False, True, False)), {})
        self.assertEqual(t.extra["wheel_contact"], [False, True, False, True])


class AirborneSuspensionTests(unittest.TestCase):
    """The damper stretching in the air is not a bump, and after a real jump the landing effect owns
    the touchdown: the travel the effects see stays still and then creeps back below the bump threshold."""

    def test_stretching_in_the_air_is_not_reported(self):
        state = {}
        before = parse_snapshot(wheel_frame(1000, [0.02] * 4), state).susp_travel
        t = 1005
        for d in (0.05, 0.12, 0.19):
            now = parse_snapshot(wheel_frame(t, [d] * 4, air=(True,) * 4), state)
            t += 5
            self.assertEqual(now.susp_travel, before)
            self.assertEqual(now.slip_ratio, [0.0] * 4)

    def test_after_a_jump_the_travel_settles_slowly(self):
        state = {}
        parse_snapshot(wheel_frame(1000, [0.02] * 4), state)
        t = fly(state, 1005, 0.5)
        seen, prev = [], None
        for i in range(200):                                              # 1 s after touchdown
            d = 0.15 if i < 20 else 0.05                                  # compressed hard, then settles lower
            tele = parse_snapshot(wheel_frame(t, [d] * 4, slip=(1.0,) * 4), state)
            if prev is not None:
                speed = abs(tele.susp_travel[0] - prev.susp_travel[0]) / 0.005
                self.assertLessEqual(speed, SETTLE_RATE + 1e-6, f"a bump-sized move {i * 5} ms after landing")
            if i * 5 < SETTLE_S * 1000:
                self.assertAlmostEqual(tele.susp_travel[0], 0.1)          # held where it left the ground
                self.assertEqual(tele.slip_angle, [0.0] * 4)              # and no slide while settling
            seen.append(tele.extra["wheel_settled"][0])
            prev, t = tele, t + 5
        self.assertAlmostEqual(prev.susp_travel[0], 0.25)                 # caught up with the live 0.05 m
        self.assertTrue(seen[-1])
        self.assertFalse(seen[0])

    def test_a_lone_hop_is_felt_only_beyond_where_it_started(self):
        """A wheel skipping off a bump: the damper shortening back from its stretch is not a bump, but
        compression beyond where it was before the hop is, and it passes through at full speed."""
        ground, fl_air = (False,) * 4, (True, False, False, False)
        other = [0.02, 0.02, 0.02]
        frames = [([0.02] + other, ground)] * 10                          # resting at 0.1 of the travel
        frames += [([0.12] + other, fl_air)] * 12                          # 60 ms in the air, front left
        frames += [([d] + other, ground) for d in (0.12, 0.08, 0.04, 0.02, 0.012, 0.008, 0.008)]
        frames += [([0.008] + other, ground)] * 10                          # let the look-ahead catch up
        out, _ = drive({}, 1000, frames)
        self.assertLessEqual(max(out), 0.1 + 1e-9, "the stretch never shows")
        self.assertAlmostEqual(out[-1], 0.04, msg="the compression beyond the start is felt")
        drop = max(a - b for a, b in zip(out, out[1:]))
        self.assertGreater(drop / 0.005, 5.0, "at full speed - a bump")

    def test_a_slow_drop_is_felt_only_beyond_where_it_started(self):
        """A whole-car hop too slow for the landing effect: same rule, so it is felt, not silenced."""
        state = {}
        parse_snapshot(wheel_frame(1000, [0.02] * 4), state)
        t = fly(state, 1005, 0.3, vy=-0.5)                                # 0.3 s in the air, falling slowly
        frames = [([d] * 4, (False,) * 4) for d in (0.19, 0.12, 0.05, 0.02, 0.01, 0.005)]
        frames += [([0.005] * 4, (False,) * 4)] * 10
        out, _ = drive(state, t, frames)
        self.assertLessEqual(max(out), 0.1 + 1e-9)
        self.assertAlmostEqual(out[-1], 0.025)

    def test_the_stretch_before_the_wheel_flips_to_the_air_is_not_felt(self):
        """The damper starts stretching ~20 ms before `falling` flips; the look-ahead catches it."""
        ground, air = (False,) * 4, (True,) * 4
        frames = [([0.005] * 4, ground)] * 20
        frames += [([d] * 4, ground) for d in (0.008, 0.011, 0.014, 0.017)]   # stretching, still "on the ground"
        frames += [([d] * 4, air) for d in (0.03, 0.06, 0.1, 0.15, 0.19)]
        frames += [([0.19] * 4, air)] * 10
        out, _ = drive({}, 1000, frames)
        self.assertLessEqual(max(out) - 0.025, 0.004, "at most one creep step of the stretch gets out")

    def test_a_bounce_right_after_a_landing_is_part_of_the_landing(self):
        state = {}
        parse_snapshot(wheel_frame(1000, [0.02] * 4), state)
        t = fly(state, 1005, 0.5)
        for _ in range(20):
            parse_snapshot(wheel_frame(t, [0.02] * 4), state)
            t += 5
        held = parse_snapshot(wheel_frame(t, [0.02] * 4), state).susp_travel[0]
        t += 5
        self.assertLess((t - 1005 - 500) / 1000.0, LANDING_QUIET_S)
        for _ in range(10):                                               # a 50 ms bounce
            parse_snapshot(wheel_frame(t, [0.19] * 4, air=(True,) * 4), state)
            t += 5
        back = parse_snapshot(wheel_frame(t, [0.16] * 4), state)
        self.assertAlmostEqual(back.susp_travel[0], held, msg="no hit from a bounce off the landing")
        self.assertFalse(back.extra["wheel_settled"][0])

    def test_wheels_spun_up_in_the_air_are_not_wheelspin(self):
        state = {}
        for i in range(40):                                               # learn the rolling radius
            parse_snapshot(wheel_frame(1000 + 5 * i, [0.02] * 4), state)
        t = fly(state, 1200, 0.5)
        landed = parse_snapshot(wheel_frame(t, [0.1] * 4, rot=150.0), state)
        self.assertEqual(landed.slip_ratio, [0.0] * 4)


def _moving(t_ms, speed, dc=None, pos=None):
    """A car on the ground doing `speed` m/s straight ahead; `dc` = discontinuityCount, `pos` = position."""
    msg = snapshot(t_ms, (0.0, 0.0, speed))
    if dc is not None:
        msg["data"]["vehicleState"] = {"dynamics": {"discontinuityCount": dc}}
    if pos is not None:
        msg["data"]["pos"] = vec(*pos)
    return msg


class TeleportTests(unittest.TestCase):
    """Respawns and restarts teleport the car. They must never read as a crash or a gear change."""

    def test_a_restart_is_not_a_crash(self):
        state, worst = {}, 0.0
        for i in range(20):
            parse_snapshot(_moving(1000 + 5 * i, 32.0, dc=4), state)
        for i in range(40):                                               # back on the start line, standing
            t = parse_snapshot(_moving(1100 + 5 * i, 0.0, dc=6), state)
            if t.active:
                worst = max(worst, abs(t.accel_long), abs(t.accel_lat))
        self.assertLess(worst, 1.0)

    def test_frames_right_after_a_teleport_are_inactive(self):
        state = {}
        for i in range(10):
            parse_snapshot(_moving(1000 + 5 * i, 30.0, dc=3), state)
        first = parse_snapshot(_moving(1050, 0.0, dc=4), state)
        later = parse_snapshot(_moving(1050 + TELEPORT_QUIET_MS + 5, 0.0, dc=4), state)
        self.assertFalse(first.active)
        self.assertTrue(later.active)

    def test_a_respawn_whose_speed_arrives_a_frame_later_is_not_a_crash(self):
        """At 55.9 s in the first real drive the counter changed on a frame still at 0 m/s, and the car's
        55 m/s only showed up 14 ms later."""
        state, worst = {}, 0.0
        for i in range(20):
            parse_snapshot(_moving(1000 + 5 * i, 0.0, dc=3), state)
        parse_snapshot(_moving(1100, 0.0, dc=4), state)
        for i in range(40):
            t = parse_snapshot(_moving(1114 + 5 * i, 55.0, dc=4), state)
            if t.active:
                worst = max(worst, abs(t.accel_long))
        self.assertLess(worst, 1.0)

    def test_a_position_jump_is_a_teleport_even_without_the_counter(self):
        state = {}
        for i in range(10):
            parse_snapshot(_moving(1000 + 5 * i, 30.0, pos=(0.0, 10.0, 0.15 * i)), state)
        jumped = parse_snapshot(_moving(1050, 0.0, pos=(400.0, 10.0, 0.0)), state)
        self.assertFalse(jumped.active)

    def test_the_counter_is_reported_for_the_tools(self):
        self.assertEqual(parse_snapshot(_moving(1000, 30.0, dc=7), {}).extra["teleports"], 7)

    def test_normal_driving_is_never_a_teleport(self):
        state = {}
        for i in range(200):                                              # 1 s at 110 m/s
            t = parse_snapshot(_moving(1000 + 5 * i, 110.0, dc=7, pos=(0.0, 10.0, 0.55 * i)), state)
            self.assertTrue(t.active, i)


def pitched(t_ms, vel, air, body_contact=None, pitch_deg=40.0):
    """A car pitched nose-down by `pitch_deg` (its forward axis points down the slope), moving at `vel`."""
    p = math.radians(pitch_deg)
    msg = snapshot(t_ms, vel)
    data = msg["data"]
    data["dir"] = vec(0.0, -math.sin(p), math.cos(p))
    data["up"] = vec(0.0, math.cos(p), math.sin(p))
    data["groundContact"] = (not air) if body_contact is None else body_contact
    for name in ("FL", "FR", "RL", "RR"):
        data[name] = {"slip": 0.0, "damper": 0.19 if air else 0.02, "groundContactMaterial": 80 if air else 16,
                      "wheelRotSpeed": 100.0, "falling": "FallingAir" if air else "RestingGround"}
    return msg


class TouchdownAccelTests(unittest.TestCase):
    """A nose-first landing must not read as a frontal crash; a real crash right after one still must."""

    def land(self, after, body_first=False, pitch_deg=40.0, falling=(0.0, -18.0, 60.0)):
        """Fly 0.3 s at `falling`, touch down, then feed `after(i)` -> (vx, vy, vz) velocities."""
        state, t = {}, 1000
        for _ in range(60):
            parse_snapshot(pitched(t, falling, air=True, pitch_deg=pitch_deg), state)
            t += 5
        if body_first:                                                    # the body meets the slope first
            parse_snapshot(pitched(t, falling, air=True, body_contact=True, pitch_deg=pitch_deg), state)
            t += 5
        out = []
        for i in range(20):
            out.append(parse_snapshot(pitched(t, after(i), air=body_first and i < 2, body_contact=True,
                                              pitch_deg=pitch_deg), state))
            t += 5
        return out

    def stop_falling(self, i):
        return (0.0, min(-18.0 + 6.0 * i, 0.0), 60.0)                     # the fall stops in 15 ms

    def test_a_nose_first_landing_is_not_braking(self):
        worst = max(abs(t.accel_long) for t in self.land(self.stop_falling))
        self.assertLess(worst, 5.0)

    def test_the_body_touching_first_opens_the_window_too(self):
        worst = max(abs(t.accel_long) for t in self.land(self.stop_falling, body_first=True))
        self.assertLess(worst, 5.0)

    def test_a_slope_landing_is_not_a_crash(self):
        """At 24.9 s in the second real drive the car fell at 46 m/s onto a 37-degree down slope, level
        with it: the ground's push along the slope's normal turned the fall into speed down the slope."""
        slope = math.radians(37.0)
        n = (0.0, math.cos(slope), math.sin(slope))                       # the slope's normal = the car's up
        before = (0.0, -46.0, 25.5)
        into = sum(a * b for a, b in zip(before, n))                      # < 0: moving into the slope
        def slide_on(i):
            k = min(i / 3.0, 1.0)                                         # the push takes 15 ms
            return tuple(v - k * into * c for v, c in zip(before, n))
        out = self.land(slide_on, pitch_deg=37.0, falling=before)
        self.assertLess(max(max(abs(t.accel_long), abs(t.accel_lat)) for t in out), 5.0)

    def test_a_head_on_wall_right_after_a_level_landing_still_hits(self):
        def into_wall(i):
            return (0.0, min(-18.0 + 6.0 * i, 0.0), max(60.0 - 10.0 * i, 10.0))
        worst = max(-t.accel_long for t in self.land(into_wall, pitch_deg=0.0))
        self.assertGreater(worst, 300.0)

    def test_a_side_hit_right_after_a_pitched_landing_still_hits(self):
        def into_wall(i):
            return (min(4.0 * i, 20.0), min(-18.0 + 6.0 * i, 0.0), 60.0)  # knocked sideways at 20 m/s
        worst = max(abs(t.accel_lat) for t in self.land(into_wall))
        self.assertGreater(worst, 300.0)

    def test_the_correction_fades_out_instead_of_stopping(self):
        """Switching it off at once lets the whole push back in one step - itself a jolt (74.8 s, drive 2)."""
        from openshaker.sources.trackmania import TOUCHDOWN_BLEND_MS, _touchdown_window
        state = {}
        _touchdown_window(state, 0.0, grounded=False, body_contact=False)
        self.assertEqual(_touchdown_window(state, 500.0, grounded=True, body_contact=True), 1.0)
        end = 500.0 + TOUCHDOWN_ACCEL_MS
        self.assertAlmostEqual(_touchdown_window(state, end + TOUCHDOWN_BLEND_MS / 2, True, True), 0.5)
        self.assertEqual(_touchdown_window(state, end + TOUCHDOWN_BLEND_MS, True, True), 0.0)

    def test_the_car_tilt_is_reported(self):
        """up_y: 1 level, about 0 on a wall ride, negative upside down in a loop."""
        level = parse_snapshot(snapshot(1000, (0.0, 0.0, 30.0)), {})
        wall = snapshot(1000, (0.0, 0.0, 30.0))
        wall["data"]["up"] = vec(1.0, 0.0, 0.0)
        self.assertAlmostEqual(level.extra["up_y"], 1.0)
        self.assertAlmostEqual(parse_snapshot(wall, {}).extra["up_y"], 0.0)

    def test_vertical_forces_count_when_there_was_no_jump(self):
        """On a loop the car's forward axis points up; its speed change there is real acceleration."""
        state, worst = {}, 0.0
        for i in range(40):
            msg = snapshot(1000 + 5 * i, (0.0, 30.0 - 0.5 * i, 0.0))      # climbing the loop, slowing
            msg["data"].update(dir=vec(0.0, 1.0, 0.0), up=vec(0.0, 0.0, -1.0))
            worst = min(worst, parse_snapshot(msg, state).accel_long)
        self.assertLess(worst, -50.0)


class CarContactTests(unittest.TestCase):
    def test_the_car_is_in_the_air_when_every_wheel_is(self):
        msg = wheel_frame(1000, [0.19] * 4, air=(True,) * 4)
        msg["data"]["groundContact"] = True                               # the car-level flag flickers
        self.assertFalse(parse_snapshot(msg, {}).extra["ground_contact"])

    def test_one_wheel_down_is_on_the_ground(self):
        t = parse_snapshot(wheel_frame(1000, [0.05] * 4, air=(True, True, True, False)), {})
        self.assertTrue(t.extra["ground_contact"])


class CarConstantTests(unittest.TestCase):
    """Rev range and damper travel ship per car type in the profile and win over the config keys."""
    CARS = {"CarSport": {"max_rpm": 12000.0, "idle_rpm": 1500.0, "damper_range_m": 0.05}}

    def car_snapshot(self, car, nested=False):
        msg = snapshot(1000, (0.0, 0.0, 20.0))                         # every damper at 0.1 m
        if nested:
            msg["data"]["vehicleState"] = {"engine": {"vehicleType": car, "vehicleTypeValue": 1}}
        else:
            msg["data"]["vehicleTypeName"] = car
        return msg

    def test_the_driven_car_uses_its_own_constants(self):
        t = parse_snapshot(self.car_snapshot("CarSport"), {}, cars=self.CARS)
        self.assertEqual((t.max_rpm, t.idle_rpm), (12000.0, 1500.0))
        self.assertAlmostEqual(t.susp_travel[0], 2.0)                    # 0.1 m / 0.05 m
        self.assertEqual(t.extra["car"], "CarSport")

    def test_the_car_type_is_read_from_the_nested_engine_group(self):
        t = parse_snapshot(self.car_snapshot("CarSport", nested=True), {}, cars=self.CARS)
        self.assertEqual(t.max_rpm, 12000.0)

    def test_other_cars_fall_back_to_the_config_values(self):
        t = parse_snapshot(self.car_snapshot("CarSnow"), {}, max_rpm=9000.0, damper_range_m=0.2, cars=self.CARS)
        self.assertEqual(t.max_rpm, 9000.0)
        self.assertAlmostEqual(t.susp_travel[0], 0.5)
        self.assertEqual(parse_snapshot(snapshot(1000, (0.0, 0.0, 20.0)), {}, cars=self.CARS).extra["car"], "")

    def test_load_cars_keeps_only_sane_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps({"effects": {}, "cars": {
                "CarSport": {"max_rpm": 11000, "idle_rpm": -5, "damper_range_m": "x", "colour": 3},
                "CarSnow": {"max_rpm": True}, "CarRally": "fast"}}), encoding="utf-8")
            self.assertEqual(load_cars(path), {"CarSport": {"max_rpm": 11000.0}})
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_cars(path), {})
            self.assertEqual(load_cars(Path(tmp) / "missing.json"), {})

    def test_the_shipped_profile_loads(self):
        cars = load_cars()
        self.assertIsInstance(cars, dict)
        for name, values in cars.items():
            self.assertTrue(name.startswith("Car"), name)
            self.assertLessEqual(set(values), {"max_rpm", "idle_rpm", "damper_range_m"})

    def test_the_source_reads_the_profile_unless_given_cars(self):
        self.assertEqual(TrackmaniaSource().params["cars"], load_cars())
        self.assertEqual(TrackmaniaSource(cars=self.CARS).params["cars"], self.CARS)


def service_status(running=True, interval_ms=100):
    """The message Data Sender 2.0 sends every client as soon as it connects."""
    return {"type": "service_status", "version": 1, "t": 900, "source": "service",
            "data": {"running": running, "clients": 1,
                     "tcp": {"broadcastIntervalMs": interval_ms, "maxTelemetryMessagesPerSecond": 120}}}


class FakeDataSender(threading.Thread):
    """Accepts one client, greets it with a service status like the real plugin, records every command
    it sends, and streams a few snapshots."""

    def __init__(self, status=None, error_on_control=False):
        super().__init__(daemon=True)
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.status = status
        self.error_on_control = error_on_control
        self.commands = []

    @property
    def first_command(self):
        return self.commands[0] if self.commands else None

    def run(self):
        try:
            self._serve()
        except OSError:
            pass                                    # the client hung up first, which is fine here
        finally:
            self.server.close()

    def _read_commands(self, conn, buf, seconds):
        conn.settimeout(0.05)
        end = time.time() + seconds
        while time.time() < end:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = json.loads(line)
                self.commands.append(cmd)
                if self.error_on_control and cmd.get("type", "").startswith(("service.", "tcp.")):
                    conn.sendall(b'{"type":"error","code":"control_commands_disabled","message":"no"}\n')
        return buf

    def _serve(self):
        conn, _ = self.server.accept()
        with conn:
            if self.status is not None:
                conn.sendall(json.dumps(self.status).encode("utf-8") + b"\n")
            buf = self._read_commands(conn, b"", 0.3)
            conn.sendall(b'{"type":"ack"}\n')
            for i in range(20):
                line = json.dumps(snapshot(1000 + 10 * i, (0.0, 0.0, 20.0), slip=(0.2, 0.2, 0.0, 0.0)))
                conn.sendall(line.encode("utf-8") + b"\n")
                time.sleep(0.01)
            self._read_commands(conn, buf, 0.5)
        self.server.close()


class SetupCommandTests(unittest.TestCase):
    """Data Sender ships stopped and at a 100 ms broadcast interval; only those two things get changed."""

    def test_a_fresh_install_is_started_and_sped_up(self):
        commands, changes = setup_commands(service_status(running=False, interval_ms=100)["data"])
        self.assertEqual(commands, [{"type": "service.start"},
                                    {"type": "tcp.set_broadcast_interval", "intervalMs": 0}])
        self.assertEqual(len(changes), 2)

    def test_a_running_service_is_not_restarted(self):
        commands, _ = setup_commands(service_status(running=True, interval_ms=100)["data"])
        self.assertEqual(commands, [{"type": "tcp.set_broadcast_interval", "intervalMs": 0}])

    def test_an_interval_someone_chose_is_left_alone(self):
        for interval in (0, 16, 50, 250):
            commands, changes = setup_commands(service_status(running=True, interval_ms=interval)["data"])
            self.assertEqual((commands, changes), ([], []), interval)

    def test_odd_status_changes_nothing(self):
        for status in (None, "running", {}, {"tcp": "x"}, {"running": None}):
            self.assertEqual(setup_commands(status), ([], []), status)


class ClientTests(unittest.TestCase):
    def test_subscribes_and_publishes_frames(self):
        server = FakeDataSender()
        server.start()
        src = TrackmaniaSource(port=server.port)
        src.start()
        deadline = time.time() + 5.0
        while src.latest() is None and time.time() < deadline:
            time.sleep(0.05)
        tele = src.latest()
        src.stop()
        self.assertEqual(server.first_command, {"type": "subscribe", "sources": ["vehicle_state"]})
        self.assertIsNotNone(tele, "no frame was published")
        self.assertEqual(tele.source, "trackmania")
        self.assertAlmostEqual(tele.speed, 20.0)
        self.assertTrue(tele.raw.startswith(b'{"type": "snapshot"'))     # the whole line is kept for logs
        self.assertIsNone(src.error)

    def run_against(self, server):
        server.start()
        src = TrackmaniaSource(port=server.port)
        src.start()
        deadline = time.time() + 5.0
        while src.latest() is None and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.2)
        src.stop()
        server.join(timeout=3.0)
        return src

    def test_starts_a_fresh_plugin_and_lifts_its_default_interval(self):
        server = FakeDataSender(status=service_status(running=False, interval_ms=100))
        src = self.run_against(server)
        self.assertIsNotNone(src.latest(), "no frame was published")
        types = [c["type"] for c in server.commands]
        self.assertEqual(types, ["subscribe", "client.set_service_status_telemetry", "service.start",
                                 "tcp.set_broadcast_interval"])
        self.assertEqual(server.commands[1]["enabled"], False)            # this connection only
        self.assertEqual(server.commands[3]["intervalMs"], 0)
        self.assertIn("started its service", src.setup_note)
        self.assertIn("100 -> 0 ms", src.setup_note)

    def test_changes_no_setting_on_a_configured_plugin(self):
        server = FakeDataSender(status=service_status(running=True, interval_ms=16))
        src = self.run_against(server)
        self.assertIsNotNone(src.latest())
        types = [c["type"] for c in server.commands]
        self.assertEqual(types, ["subscribe", "client.set_service_status_telemetry"])
        self.assertEqual(src.setup_note, "")

    def test_never_sends_a_global_rate_cap(self):
        server = FakeDataSender(status=service_status(running=False, interval_ms=100))
        self.run_against(server)
        self.assertNotIn("tcp.set_max_telemetry_messages_per_second", [c["type"] for c in server.commands])

    def test_says_so_when_the_plugin_is_full(self):
        """Data Sender answers an extra client with a max_clients error and hangs up."""
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        port = server.getsockname()[1]
        stop = threading.Event()

        def turn_away():
            server.settimeout(0.2)
            while not stop.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return                                  # the test closed the server
                conn.sendall(b'{"type":"error","message":"no free client slot","code":"max_clients"}\n')
                conn.settimeout(0.2)
                try:
                    while conn.recv(4096):                  # take ALL the client's commands first, so
                        pass                                # Windows closes with a FIN, not a reset that
                except OSError:                             # could drop the error line before the client
                    pass                                    # reads it
                conn.close()

        threading.Thread(target=turn_away, daemon=True).start()
        src = TrackmaniaSource(port=port)
        src.start()
        deadline = time.time() + 3.0
        while "full" not in src.status and time.time() < deadline:
            time.sleep(0.05)
        status = src.status
        src.stop()
        stop.set()
        server.close()
        self.assertIn("raise TCP max clients", status)

    def test_says_so_when_the_plugin_refuses_control_commands(self):
        server = FakeDataSender(status=service_status(running=False, interval_ms=100), error_on_control=True)
        server.start()
        src = TrackmaniaSource(port=server.port)
        src.start()
        deadline = time.time() + 3.0
        while "refuses control" not in src.status and time.time() < deadline:
            time.sleep(0.05)
        status = src.status
        src.stop()
        self.assertIn("refuses control commands", status)

    def test_waits_quietly_when_the_plugin_is_not_running(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()                                                     # nothing listens here now
        src = TrackmaniaSource(port=port)
        src.start()
        time.sleep(0.4)
        status, error = src.status, src.error
        src.stop()
        self.assertIn("waiting for Openplanet Data Sender", status)
        self.assertIsNone(error, "a missing plugin is a normal state, not an error")


if __name__ == "__main__":
    unittest.main()
