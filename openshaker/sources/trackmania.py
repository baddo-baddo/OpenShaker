"""Trackmania, through the Openplanet "Data Sender" plugin.

Trackmania has no telemetry output of its own. Data Sender runs a local TCP server
(127.0.0.1:28765 by default) and streams the viewed car's vehicle state as newline-delimited JSON,
one snapshot per frame. This source connects as a client, subscribes to `vehicle_state` only, and
turns each snapshot into a Telemetry frame. The whole JSON line is kept as `tele.raw`, so a `--log`
run records every field the plugin sends, not just the ones mapped below.

Data Sender writes most things twice: a flat layout (per-wheel `FL`/`FR`/`RL`/`RR` objects with keys
`slip`, `damper`; car keys such as `engineOn`, `isTurbo`, `waterImmersionCoef`) and a nested
`vehicleState` layout (wheels under `wheels.frontLeft` with `slipCoef`, `damperLen`; car values
grouped under `engine`, `reactor`, `contact`, `water`, `inputs`, `dynamics`). Both are read.

Mapping (Trackmania uses metres, m/s and a left/up/dir basis; world up is +y):
  speed           |worldVel|
  accel_*         change in worldVel over at least `accel_window_ms`, in the car's own axes (+lat = right).
                  Effects run once per 10 ms audio block and see only the latest frame, so a per-frame
                  difference would be both noisy and mostly unseen; velocity is a running state, so a
                  windowed difference still carries all of a crash even when frames are skipped.
  slip_angle[i]   the wheel's SlipCoef (0 while gripping, ~1 once sliding) x how fast the car moves
                  sideways, |side speed| / SLIDE_FULL_MPS capped at 1
  slip_ratio[i]   wheelspin (+) or lock (-): wheel rotation x learned rolling radius vs road speed,
                  divided by `slip_ratio_full` so that 1.0 is a clear spin. The radius is learned while
                  the car rolls straight with no slip, so it adapts to each car type.
  susp_travel[i]  damper length / damper_range_m, held still while the wheel is in the air and while
                  it settles after a jump (see `settle_suspension`): the landing effect owns touchdowns
  engine_running  engineOn
  extra           car type, body_slip_deg, side/forward/vertical speed, slip_coef (raw), steer, ground
                  contact and distance, per-wheel contact / settled / damper_len (m), surfaces, icing,
                  turbo, reactor level, water, wetness, roof contact, burnout
A wheel in the air or still settling reports no slide (slip_angle) and no spin (slip_ratio): wheels
spin up freely in the air, and that is not wheelspin when they touch down.
max_rpm, idle_rpm and damper_range_m come per car from the profile's "cars" block (see `load_cars`).
"""
from __future__ import annotations

import json
import logging
import math
import socket
import time
from pathlib import Path
from typing import Optional

from ..telemetry import Telemetry
from .base import Source

WHEEL_KEYS = (("FL", "frontLeft"), ("FR", "frontRight"), ("RL", "rearLeft"), ("RR", "rearRight"))
GROUPS = ("engine", "reactor", "contact", "water", "inputs", "dynamics")
DEFAULT_PORT = 28765
# Data Sender 2.0 ships with its service stopped and its TCP broadcast interval at 100 ms (10 snapshots/s).
# Its TCP server listens and takes commands either way, so the source fixes both on connect.
PLUGIN_DEFAULT_BROADCAST_MS = 100

log = logging.getLogger(__name__)

# Rev range and damper travel are constants of each Trackmania car, the same for every player, so they
# ship in the profile's "cars" block keyed by vehicle type (CarSport, CarSnow, CarRally, CarDesert) and
# win over the sources.trackmania config keys, which stay as the fallback for a car the profile lacks.
PROFILE = Path("profiles") / "trackmania" / "profile.json"
CAR_KEYS = ("max_rpm", "idle_rpm", "damper_range_m")


def load_cars(path=None) -> dict:
    """{vehicle type: {max_rpm, idle_rpm, damper_range_m}} from the shipped Trackmania profile."""
    if path is None:
        from ..paths import RESOURCE_DIR
        path = RESOURCE_DIR / PROFILE
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cars = data.get("cars") if isinstance(data, dict) else None
    out = {}
    for name, values in (cars.items() if isinstance(cars, dict) else ()):
        if not isinstance(values, dict):
            continue
        clean = {k: float(v) for k, v in values.items()
                 if k in CAR_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}
        if clean:
            out[str(name)] = clean
    return out


def car_name(data: dict) -> str:
    """The car type, e.g. "CarSport"; top-level `vehicleTypeName` or vehicleState.engine.vehicleType."""
    value = _find(data, "vehicleTypeName", "vehicleType")
    return value.strip() if isinstance(value, str) else ""


def setup_commands(status) -> tuple[list, list]:
    """What to send after Data Sender's first service_status message, and what each one changes.

    Starts a stopped service, and lifts the shipped 100 ms broadcast interval to every plugin update.
    Any other interval was chosen by someone and is left alone; nothing else is touched.
    """
    if not isinstance(status, dict):
        return [], []
    commands, changes = [], []
    if status.get("running") is False:
        commands.append({"type": "service.start"})
        changes.append("started its service")
    tcp = status.get("tcp") if isinstance(status.get("tcp"), dict) else {}
    if tcp.get("broadcastIntervalMs") == PLUGIN_DEFAULT_BROADCAST_MS:
        commands.append({"type": "tcp.set_broadcast_interval", "intervalMs": 0})
        changes.append(f"set its broadcast interval {PLUGIN_DEFAULT_BROADCAST_MS} -> 0 ms")
    return commands, changes

# EPlugSurfaceMaterialId, verified against the enum in Openplanet's own header
# (OpenplanetNext/Openplanet.h, `enum class EPlugSurfaceMaterialId`): list index == material id.
SURFACES = [
    "Concrete", "Pavement", "Grass", "Ice", "Metal", "Sand", "Dirt", "Turbo_Deprecated",              # 0-7
    "DirtRoad", "Rubber", "SlidingRubber", "Test", "Rock", "Water", "Wood", "Danger",                  # 8-15
    "Asphalt", "WetDirtRoad", "WetAsphalt", "WetPavement", "WetGrass", "Snow", "ResonantMetal",       # 16-22
    "GolfBall", "GolfWall", "GolfGround", "Turbo2_Deprecated", "Bumper_Deprecated", "NotCollidable",  # 23-28
    "FreeWheeling_Deprecated", "TurboRoulette_Deprecated", "WallJump", "MetalTrans", "Stone",        # 29-33
    "Player", "Trunk", "TechLaser", "SlidingWood", "PlayerOnly", "Tech", "TechArmor", "TechSafe",     # 34-41
    "OffZone", "Bullet", "TechHook", "TechGround", "TechWall", "TechArrow", "TechHook2", "Forest",     # 42-49
    "Wheat", "TechTarget", "PavementStair", "TechTeleport", "Energy", "TechMagnetic",                 # 50-55
    "TurboTechMagnetic_Deprecated", "Turbo2TechMagnetic_Deprecated", "TurboWood_Deprecated",         # 56-58
    "Turbo2Wood_Deprecated", "FreeWheelingTechMagnetic_Deprecated", "FreeWheelingWood_Deprecated",   # 59-61
    "TechSuperMagnetic", "TechNucleus", "TechMagneticAccel", "MetalFence", "TechGravityChange",      # 62-66
    "TechGravityReset", "RubberBand", "Gravel", "Hack_NoGrip_Deprecated", "Bumper2_Deprecated",      # 67-71
    "NoSteering_Deprecated", "NoBrakes_Deprecated", "RoadIce", "RoadSynthetic", "Green", "Plastic",  # 72-77
    "DevDebug", "Free3", "XXX_Null",                                                                  # 78-80
]


NULL_MATERIAL = SURFACES.index("XXX_Null")        # 80: what a wheel off the ground reports

# A Trackmania damper stretches to full length within ~80 ms of a wheel leaving the ground - and the
# stretch starts ~20 ms BEFORE the wheel's `falling` state flips - so the travel the effects see runs
# LOOKAHEAD_S behind the live value: a wheel about to leave the ground is already treated as airborne,
# and its travel is held where it was (the stretch is not a bump). A real landing - the whole car in the
# air for at least SETTLE_AIR_S and falling at LANDING_MIN_FALL or faster, which is when the landing
# effect plays its thump - owns the touchdown: each wheel's travel stays held for SETTLE_S, also for
# bounces within LANDING_QUIET_S, then creeps to the live value at SETTLE_RATE (travel per second, below
# the suspension effect's bump threshold of 1.0). After any other touchdown (a hop, a wheel dropping back
# after the car rocked onto two, a slow drop) the travel stays held while the damper shortens back to
# where it was before it left - the stretch undoing itself - and goes live from there, so only the
# compression beyond it is felt (after SETTLE_S without getting back there, it creeps over instead).
# Longer damperLen = more extended, as the real data shows (~0.005 m resting, ~0.195 m in the air).
LOOKAHEAD_S = 0.025
SETTLE_AIR_S = 0.12
LANDING_MIN_FALL = 1.5            # m/s, the landing effect's default v_min
SETTLE_S = 0.25
SETTLE_RATE = 0.8
LANDING_QUIET_S = 0.8
# Respawns and restarts teleport the car; Data Sender bumps discontinuityCount when they happen. For
# TELEPORT_QUIET_MS after one, frames are inactive (effects skip them) and no velocity history is kept,
# so a teleport never reads as a crash, a gear-shift thump or a bump. A jump in position far beyond what
# the speed allows is taken as a teleport too.
TELEPORT_QUIET_MS = 60.0
# For TOUCHDOWN_ACCEL_MS after the car comes down from a jump, the ground's push (world-vertical, and along
# the car's own up axis for a slope) is left out of accel_long / accel_lat, then let back in over
# TOUCHDOWN_BLEND_MS: a nose-first or slope landing otherwise reads as a crash on top of the landing thump,
# and letting it back in at once is a jolt of its own. Only then - on loops and wall rides the car's own
# axes point up and those forces are real.
TOUCHDOWN_ACCEL_MS = 150.0
TOUCHDOWN_BLEND_MS = 100.0
# SlipCoef is all but on/off (0, then 1 within ~50 ms), so a slide's strength comes from how fast the
# car is actually moving sideways: slip_angle = SlipCoef x |side speed| / SLIDE_FULL_MPS (capped at 1),
# so a gentle drift reads low and a skid after a crash reads full.
SLIDE_FULL_MPS = 12.0


def surface_name(material: int) -> str:
    return SURFACES[material] if 0 <= material < len(SURFACES) else f"id {material}"


def wheel_contact(wheel: dict, grounded: bool) -> bool:
    """Is this wheel on something? Data Sender's per-wheel `falling` state says so in Trackmania
    (RestingGround / GlidingGround / RestingWater vs FallingAir / FallingWater); older games send
    `groundContact`; otherwise a wheel on material XXX_Null is in the air."""
    falling = wheel.get("falling") if isinstance(wheel, dict) else None
    if isinstance(falling, str) and falling.strip():
        return not falling.strip().lower().startswith("falling")
    if isinstance(wheel, dict) and isinstance(wheel.get("groundContact"), bool):
        return wheel["groundContact"]
    material = _num(wheel, "groundContactMaterial", "mat", default=-1.0)
    if int(material) == NULL_MATERIAL:
        return False
    return grounded


def settle_suspension(state: dict, now_s: float, raw: list, contact: list,
                      fall_speed: float = 0.0) -> tuple[list, list]:
    """Per-wheel suspension travel as the effects should see it, and which wheels are settled.

    Runs LOOKAHEAD_S behind the live frames (see the constants above): a wheel in the air, or about to
    leave the ground, reports the travel it had before it left; after a real landing it keeps that for
    SETTLE_S and then creeps to the live value at SETTLE_RATE; after any other touchdown it stays there
    until the damper is back to that length and then follows the live value. `settled[i]` is False while a wheel is airborne or settling (and
    while it is in the air right now), so wheelspin from a wheel that spun up in the air is not reported.
    `fall_speed` is the car's downward speed in m/s.
    """
    buf = state.setdefault("susp_buf", [])
    if buf and not 0.0 <= now_s - buf[-1][0] < 1.0:
        buf.clear()                                         # clock jumped: start over, never replay old frames
        state.pop("susp_m", None)
    buf.append((now_s, list(raw), list(contact), float(fall_speed)))
    m = state.get("susp_m")
    if m is None:
        m = state["susp_m"] = {"wheels": [{"rep": raw[i], "mode": None, "until": None, "air_since": None,
                                           "t": None} for i in range(4)],
                               "car_air_since": None, "car_fall": 0.0, "landed": -1e9,
                               "out": list(raw), "settled": [True] * 4}
    while buf and buf[0][0] <= now_s - LOOKAHEAD_S:
        t, r, c, fall = buf.pop(0)
        leaving = [any(not later[2][i] for later in buf if later[0] <= t + LOOKAHEAD_S) for i in range(4)]
        _settle_step(m, t, r, [c[i] and not leaving[i] for i in range(4)], fall)
    return list(m["out"]), [s and live for s, live in zip(m["settled"], contact)]


def _settle_step(m: dict, t: float, raw: list, contact: list, fall: float) -> None:
    """One (delayed) frame of settle_suspension's per-wheel state machine."""
    if not any(contact):
        if m["car_air_since"] is None:
            m["car_air_since"], m["car_fall"] = t, 0.0
        m["car_fall"] = max(m["car_fall"], fall)
    elif m["car_air_since"] is not None:                    # the car comes back down
        if t - m["car_air_since"] >= SETTLE_AIR_S and max(m["car_fall"], fall) >= LANDING_MIN_FALL:
            m["landed"] = t                                 # the landing effect plays this one
        m["car_air_since"] = None
    out, settled = [], []
    for i, w in enumerate(m["wheels"]):
        dt = 0.0 if w["t"] is None else min(max(t - w["t"], 0.0), 0.1)
        w["t"] = t
        step = SETTLE_RATE * dt
        if not contact[i]:
            if w["air_since"] is None:
                w["air_since"] = t
            out.append(w["rep"])
            settled.append(False)
            continue
        if w["air_since"] is not None:                      # this wheel touches down
            if t - m["landed"] < LANDING_QUIET_S:
                w["mode"], w["until"] = "settle", t + SETTLE_S       # a landing, or bouncing off one
            elif w["mode"] is None:
                w["mode"], w["until"] = "unstretch", t + SETTLE_S    # anything else
            w["air_since"] = None
        if w["mode"] == "unstretch":
            # the damper first shortens back to where it was before it left the ground - that is the
            # stretch undoing itself, not a bump; only compression beyond it is felt
            if raw[i] <= w["rep"]:
                w["mode"] = None
            elif t >= w["until"]:
                w["mode"] = "settle"                        # never got back there: creep over
            else:
                out.append(w["rep"])
                settled.append(False)
                continue
        if w["mode"] == "settle":
            if t >= w["until"]:
                gap = raw[i] - w["rep"]
                if abs(gap) <= step:
                    w["mode"] = None                        # caught up: live again from here
                else:
                    w["rep"] += step if gap > 0.0 else -step
            if w["mode"] == "settle":
                out.append(w["rep"])
                settled.append(False)
                continue
        w["rep"] = raw[i]
        out.append(w["rep"])
        settled.append(True)
    m["out"], m["settled"] = out, settled


def _without_landing_push(acc: tuple, up: Optional[tuple]) -> tuple:
    """`acc` without the push of the ground on landing: without its world-vertical part (the fall
    stopping) and without its part along the car's own up axis (the push of a slope, whose normal the
    car lines up with as it lands). On a level car that leaves the horizontal plane; on a pitched one,
    its sideways axis - where a real side-on hit still shows."""
    out = (acc[0], 0.0, acc[2])
    if up:
        e = (up[0], 0.0, up[2])                             # the car's up with world-up taken out
        n = math.sqrt(e[0] * e[0] + e[2] * e[2])
        if n > 0.1:                                         # pitched or rolled by more than ~6 degrees
            e = (e[0] / n, 0.0, e[2] / n)
            k = out[0] * e[0] + out[2] * e[2]
            out = (out[0] - k * e[0], 0.0, out[2] - k * e[2])
    return out


def _touchdown_window(state: dict, now_ms: float, grounded: bool, body_contact: bool) -> float:
    """How much of the landing push to leave out: 1 for TOUCHDOWN_ACCEL_MS after the car comes down from
    at least SETTLE_AIR_S in the air, then falling to 0 over TOUCHDOWN_BLEND_MS.

    The car's body can meet a slope a few ms before any wheel reports ground; the car-level contact
    flag says so, so it opens the window too (it also flickers in the air, where the window is harmless:
    the vertical change there is only gravity)."""
    flown = state.get("air_since_ms") is not None and now_ms - state["air_since_ms"] >= SETTLE_AIR_S * 1000.0
    if flown and (grounded or body_contact):
        state["touchdown_until"] = max(state.get("touchdown_until", -1e18), now_ms + TOUCHDOWN_ACCEL_MS)
    if not grounded:
        if state.get("air_since_ms") is None:
            state["air_since_ms"] = now_ms
    else:
        state["air_since_ms"] = None
    left = state.get("touchdown_until", -1e18) - now_ms
    return 1.0 if left > 0.0 else max(0.0, 1.0 + left / TOUCHDOWN_BLEND_MS)


def _teleported(data: dict, state: dict, now_ms: float, speed: float) -> bool:
    """Did the car respawn or restart since the last frame? Data Sender's discontinuityCount changes
    when it does; a position jump far beyond what the speed allows says the same without it."""
    dc = _find(data, "discontinuityCount")
    pos = _vec(data.get("pos"))
    last_dc, last_pos, last_t = state.get("dc"), state.get("pos"), state.get("pos_t")
    state["dc"] = dc if isinstance(dc, (int, float)) and not isinstance(dc, bool) else last_dc
    state["pos"], state["pos_t"] = pos, now_ms
    if last_dc is not None and state["dc"] is not None and state["dc"] != last_dc:
        return True
    if pos is not None and last_pos is not None and last_t is not None:
        dt = max(now_ms - last_t, 0.0) / 1000.0
        jump = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos, last_pos)))
        if jump > 20.0 + 3.0 * max(speed, 100.0) * dt:
            return True
    return False


def _vec(value) -> Optional[tuple]:
    """Data Sender encodes vectors as {"x","y","z"}; accept a 3-list too."""
    try:
        if isinstance(value, dict):
            return float(value["x"]), float(value["y"]), float(value["z"])
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return float(value[0]), float(value[1]), float(value[2])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _dot(a: tuple, b: tuple) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _num(obj, *keys, default: float = 0.0) -> float:
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if value is None or isinstance(value, bool):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return default


def _scopes(data: dict) -> list:
    """Where a car value may live: the flat layout, then vehicleState and its groups."""
    vs = data.get("vehicleState") if isinstance(data.get("vehicleState"), dict) else {}
    scopes = [data, vs]
    scopes += [vs[g] for g in GROUPS if isinstance(vs.get(g), dict)]
    scopes += [data[g] for g in GROUPS if isinstance(data.get(g), dict)]
    return scopes


def _find(data: dict, *names):
    for scope in _scopes(data):
        for name in names:
            if name in scope and scope[name] is not None:
                return scope[name]
    return None


def _flag(data: dict, *names, default: bool = False) -> bool:
    value = _find(data, *names)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "none", "no")
    return bool(value)


def _float(data: dict, *names, default: float = 0.0) -> float:
    value = _find(data, *names)
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _level(data: dict, *names) -> int:
    """Reactor boost level: an int, or a name such as "None" / "Lvl1" / "Lvl2"."""
    value = _find(data, *names)
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        text = str(value).strip().lower()
        if text in ("", "none", "0"):
            return 0
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else 1


def _wheels(data: dict) -> list:
    """The four wheel objects in FL, FR, RL, RR order, from whichever layout is present."""
    vs = data.get("vehicleState") if isinstance(data.get("vehicleState"), dict) else {}
    nested = vs.get("wheels") or data.get("wheels") or {}
    out = []
    for flat, long in WHEEL_KEYS:
        wheel = data.get(flat)
        if not isinstance(wheel, dict) and isinstance(nested, dict):
            wheel = nested.get(long)
        out.append(wheel if isinstance(wheel, dict) else {})
    return out


def parse_snapshot(msg: dict, state: dict, damper_range_m: float = 0.2, accel_window_ms: float = 20.0,
                   slip_ratio_full: float = 0.15, max_rpm: float = 11000.0, idle_rpm: float = 1000.0,
                   cars: Optional[dict] = None) -> Optional[Telemetry]:
    """One vehicle_state snapshot -> Telemetry. `state` carries velocity history and learned wheel radii.

    `cars` ({vehicle type: constants}, see `load_cars`) overrides max_rpm / idle_rpm / damper_range_m
    for the car being driven; the analysis tools pass none so they see raw values.
    """
    if not isinstance(msg, dict) or msg.get("type") != "snapshot" or msg.get("source") != "vehicle_state":
        return None
    data = msg.get("data")
    if not isinstance(data, dict) or not data.get("available", True):
        radius = state.get("radius")
        state.clear()                      # in a menu or spectating nothing: no stale velocity next time
        if radius and any(radius):
            state["radius"] = radius       # the car's wheels did not change size
        return None
    car = car_name(data)
    const = (cars or {}).get(car) or {}
    max_rpm = const.get("max_rpm", max_rpm)
    idle_rpm = const.get("idle_rpm", idle_rpm)
    damper_range_m = const.get("damper_range_m", damper_range_m)
    vel = _vec(data.get("worldVel"))
    left, up, fwd = _vec(data.get("left")), _vec(data.get("up")), _vec(data.get("dir"))
    wheels = _wheels(data)

    t = Telemetry(active=True)
    t.engine_running = _flag(data, "engineOn", default=True)
    t.rpm = _num(data, "rpm")
    t.max_rpm, t.idle_rpm = float(max_rpm), float(idle_rpm)
    t.gear = int(_num(data, "gear"))
    t.throttle = min(max(_num(data, "throttle"), 0.0), 1.0)
    t.brake = min(max(_num(data, "brake"), 0.0), 1.0)
    t.speed = math.sqrt(_dot(vel, vel)) if vel else abs(_num(data, "spd"))
    steer = _num(data, "steer")

    forward = _dot(vel, fwd) if (vel and fwd) else _num(data, "frontSpeed")
    side = -_dot(vel, left) if (vel and left) else 0.0          # + = sliding to the car's right
    body_slip = math.degrees(math.atan2(side, abs(forward))) if t.speed > 3.0 else 0.0

    grounded_flag = _flag(data, "isGroundContact", "groundContact", default=True)
    contact = [wheel_contact(w, grounded_flag) for w in wheels]
    # the car is on the ground when any wheel is (per-wheel `falling`); the car-level flag flickers in the air
    per_wheel = any(isinstance(w.get("falling"), str) or isinstance(w.get("groundContact"), bool) for w in wheels)
    grounded = any(contact) if per_wheel else grounded_flag

    # accelerations over a window of the plugin's own clock, in the car's frame
    now_ms = _num(msg, "t", default=_num(data, "t", default=time.perf_counter() * 1000.0))
    hist = state.setdefault("hist", [])
    if hist and not 0.0 < now_ms - hist[-1][0] < 250.0:
        hist.clear()                       # paused or out of order: never invent an impact
    if _teleported(data, state, now_ms, t.speed):
        state["teleport_until"] = now_ms + TELEPORT_QUIET_MS
    if now_ms < state.get("teleport_until", -1e18):
        t.active = False                   # respawn / restart: effects skip these frames
        hist.clear()
        state.pop("susp_buf", None)        # and the suspension starts afresh from the new spot
        state.pop("susp_m", None)
    touchdown = _touchdown_window(state, now_ms, grounded, grounded_flag)
    ref = next((h for h in reversed(hist) if now_ms - h[0] >= accel_window_ms), None)
    if vel and ref is not None:
        dt = (now_ms - ref[0]) / 1000.0
        acc = tuple((vel[i] - ref[1][i]) / dt for i in range(3))
        # coming down from a jump, the ground's push is the landing's thump; projected onto a pitched
        # car's own axes it would also read as braking or cornering - a crash on top of the landing
        if touchdown > 0.0:
            pushless = _without_landing_push(acc, up)
            flat = tuple(a + (b - a) * touchdown for a, b in zip(acc, pushless))
        else:
            flat = acc
        if left:
            t.accel_lat = -_dot(flat, left)
        if fwd:
            t.accel_long = _dot(flat, fwd)
        if up:
            t.accel_vert = _dot(acc, up)
    if vel and t.active:
        hist.append((now_ms, vel))
        while hist and now_ms - hist[0][0] > 250.0:
            hist.pop(0)

    slip = [_num(w, "slipCoef", "slip") for w in wheels]
    raw_travel = [_num(w, "damperLen", "damper") / max(damper_range_m, 1e-6) for w in wheels]
    t.susp_travel, settled = settle_suspension(state, now_ms / 1000.0, raw_travel, contact,
                                               fall_speed=-vel[1] if vel else 0.0)
    # a wheel in the air, or settling after a jump, is neither sliding nor spinning as far as effects know
    sliding = min(abs(side) / SLIDE_FULL_MPS, 1.0)
    t.slip_angle = [s * sliding if ok else 0.0 for s, ok in zip(slip, settled)]
    t.combined_slip = list(t.slip_angle)

    # wheelspin / lock from wheel rotation against road speed, with the rolling radius learned on the go
    rot = [abs(_num(w, "wheelRotSpeed")) for w in wheels]
    radius = state.setdefault("radius", [0.0, 0.0, 0.0, 0.0])
    fwd_abs = abs(forward)
    rolling_straight = (grounded and all(settled) and fwd_abs > 8.0 and abs(steer) < 0.15 and t.brake < 0.05
                        and all(c <= 0.0 for c in slip))
    ratio = []
    for i in range(4):
        if rolling_straight and rot[i] > 1.0:
            r = fwd_abs / rot[i]
            radius[i] = r if radius[i] <= 0.0 else radius[i] + (r - radius[i]) * 0.02
        if radius[i] > 0.0 and grounded and settled[i]:
            ratio.append((rot[i] * radius[i] - fwd_abs) / max(fwd_abs, 3.0) / max(slip_ratio_full, 1e-6))
        else:
            ratio.append(0.0)
    t.slip_ratio = ratio

    materials = [int(_num(w, "groundContactMaterial", default=-1)) for w in wheels]
    t.extra = {
        "car": car,
        "body_slip_deg": body_slip,
        "side_speed": side,
        "forward_speed": forward,
        "vert_speed": vel[1] if vel else 0.0,
        "slip_coef": slip,
        "steer": steer,
        "ground_contact": grounded,
        "ground_dist": _float(data, "groundDist"),
        "wheel_contact": contact,
        "wheel_settled": settled,
        "damper_len": [_num(w, "damperLen", "damper") for w in wheels],       # metres, as sent
        "materials": materials,
        "surfaces": [surface_name(m) if m >= 0 else "" for m in materials],
        "icing": [_num(w, "icing01") for w in wheels],
        "wheel_rot_speed": rot,
        "turbo": _flag(data, "isTurbo"),
        "turbo_time": _float(data, "turboTime"),
        "reactor_level": _level(data, "boostLvlValue", "reactorBoostLvl", "boostLvl"),
        "water": _float(data, "immersionCoef", "waterImmersionCoef"),
        "wetness": _float(data, "wetnessValue01"),
        "top_contact": _flag(data, "isTopContact", "topContact"),
        "up_y": up[1] if up else 1.0,          # 1 level, 0 on a wall, < 0 upside down (loops, wall rides)
        "teleports": state.get("dc"),          # Data Sender's discontinuityCount (respawns and restarts)
        "wheels_burning": _flag(data, "isWheelsBurning", "wheelsBurning"),
    }
    return t


class TrackmaniaSource(Source):
    """TCP client for Data Sender. Waits quietly until the plugin is running, and reconnects.

    On connect it subscribes to vehicle_state and turns off the plugin's per-update service-status
    messages for this connection (they would share the per-client message budget with the snapshots).
    Then, from the status message the plugin sends every new client, it starts the plugin's service if
    it is stopped and lifts the shipped 100 ms broadcast interval (see `setup_commands`).
    """

    name = "trackmania"

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, max_rate: int = 200,
                 damper_range_m: float = 0.2, accel_window_ms: float = 20.0, slip_ratio_full: float = 0.15,
                 max_rpm: float = 11000.0, idle_rpm: float = 1000.0, cars: Optional[dict] = None) -> None:
        super().__init__()
        self.host = host
        self.port = int(port)
        self.max_rate = int(max_rate)      # no longer sent: the plugin's own cap (120/s) is above its sampling
        self.params = {"damper_range_m": float(damper_range_m), "accel_window_ms": float(accel_window_ms),
                       "slip_ratio_full": float(slip_ratio_full), "max_rpm": float(max_rpm),
                       "idle_rpm": float(idle_rpm), "cars": load_cars() if cars is None else dict(cars)}
        self.status = f"waiting for Openplanet Data Sender on {host}:{self.port}"
        self.malformed = 0
        self.setup_note = ""               # what the source changed in the plugin, if anything
        self.full = False                  # the plugin turned us away: all its client slots are taken

    def _send(self, sock: socket.socket, message: dict) -> None:
        sock.sendall((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))

    def _control(self, sock: socket.socket, msg: dict, configured: bool) -> bool:
        """Handle the plugin's own messages; returns whether this connection is configured."""
        kind = msg.get("type")
        if kind == "service_status" and not configured:
            commands, changes = setup_commands(msg.get("data"))
            for command in commands:
                self._send(sock, command)
            if changes:
                self.setup_note = "OpenShaker " + " and ".join(changes)
                log.info("Data Sender: %s", self.setup_note)
                self.status = f"connected to Data Sender on {self.host}:{self.port}; {self.setup_note}"
            return True
        if kind == "error" and msg.get("code") == "control_commands_disabled":
            self.status = (f"connected to Data Sender on {self.host}:{self.port}, but it refuses control "
                           f"commands: tick Allow external control commands (TCP Server tab), or press Start "
                           f"and tick Start service on plugin load (General tab)")
        if kind == "error" and msg.get("code") == "max_clients":
            self.full = True
        return configured

    def run(self) -> None:
        state: dict = {}                                        # kept across reconnects: learned radii
        while not self.stopping():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=1.0)
            except OSError:
                self.status = (f"waiting for Openplanet Data Sender on {self.host}:{self.port} "
                               f"(start Trackmania with Openplanet and the Data Sender plugin)")
                self._stop.wait(2.0)
                continue
            self.status = f"connected to Data Sender on {self.host}:{self.port}"
            configured = False
            self.full = False
            try:
                sock.settimeout(0.5)
                self._send(sock, {"type": "subscribe", "sources": ["vehicle_state"]})
                self._send(sock, {"type": "client.set_service_status_telemetry", "enabled": False})
                buf = b""
                while not self.stopping():
                    try:
                        chunk = sock.recv(65536)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break                                   # plugin closed or game exited
                    buf += chunk
                    if len(buf) > 4_000_000 and b"\n" not in buf:
                        buf = b""                               # never let a broken stream grow forever
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            msg = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(msg, dict) and msg.get("type") in ("service_status", "error"):
                            configured = self._control(sock, msg, configured)
                            continue
                        try:
                            tele = parse_snapshot(msg, state, **self.params)
                        except Exception:       # an unexpected message shape is skipped, not fatal
                            self.malformed += 1
                            continue
                        if tele is not None:
                            tele.raw = bytes(line)
                            self.publish(tele)
            except OSError:
                pass
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
            if not self.stopping():
                self.status = ("Data Sender is full: raise TCP max clients in its settings (TCP Server tab)"
                               if self.full else "Data Sender disconnected; reconnecting")
                self._stop.wait(1.0)
