"""Tune the Trackmania preset from one recorded drive: engine, bumps, crashes, landings, grip, surfaces.

  python -m openshaker --source trackmania --log sessions/tm_drive_1 --duration 300     (drive, vary it)
  python -m openshaker.tm_tune sessions/tm_drive_1                                     (report)
  python -m openshaker.tm_tune sessions/tm_drive_1 --apply --name 6=Dirt --name 2=Grass (write)

Trackmania has no HaptiConnect reference, so every Trackmania default starts as a guess. This reads
what the recording shows and proposes replacements:
  engine       rpm range per car type -> max_rpm / idle_rpm                    (profile "cars" block)
  suspension   damper travel per car type -> damper_range_m                    (profile "cars" block);
               wheel movement speeds -> bump threshold / full
  impact       acceleration jumps between 10 ms audio blocks -> impact threshold / full; the biggest are
               listed with timestamps so you can check they really were crashes
  landing      airtime and fall speed of every jump -> landing v_min / v_full
  grip_margin  load and body slip just before each slide on a loose surface -> per-surface limits
               (as tm_grip)
  surfaces     time, speed and roughness per surface, named from Openplanet's material table;
               --name ID=Surface overrides a name, which --apply writes into the surface and grip effects
A few minutes covering straights, hard corners, jumps, dirt or grass and a crash or two tunes it all.
--apply rewrites only profiles/trackmania/profile.json - rev range and damper travel are constants of
each car, the same for every player, so they ship with the profile rather than living in anyone's
config.json. The app reads the profile when its haptics start: restart it afterwards.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import tm_grip
from .sources.trackmania import parse_snapshot, surface_name

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROFILE = PROJECT_DIR / "profiles" / "trackmania" / "profile.json"
BLOCK_S = 0.01                     # effects see one frame per 10 ms audio block
PARTS = ("cars", "bumps", "impacts", "landings", "grip", "names")    # what --apply can write


def load_frames(session: Path) -> list[dict]:
    """Trackmania rows of a --log session, re-parsed in order (dampers in metres)."""
    csv.field_size_limit(2 ** 31 - 1)
    state, frames = {}, []
    with (session / "telemetry.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("source") != "trackmania" or not row.get("raw_hex"):
                continue
            try:
                msg = json.loads(bytes.fromhex(row["raw_hex"]))
            except ValueError:
                continue
            tele = parse_snapshot(msg, state, damper_range_m=1.0)
            if tele is None:
                continue
            frames.append({"t": float(row["t"]), "speed": tele.speed, "rpm": tele.rpm, "gear": tele.gear,
                           "lat": tele.accel_lat, "long": tele.accel_long, "damper": list(tele.susp_travel),
                           "extra": tele.extra})
    return frames


def blocks(frames: list[dict]) -> list[dict]:
    """What the effects would have seen: one frame per audio block."""
    out, next_t = [], None
    for f in frames:
        if next_t is None or f["t"] >= next_t - 1e-6:          # CSV times are rounded to 0.1 ms
            out.append(f)
            next_t = f["t"] + BLOCK_S
    return out


def pct(values, q: float, default: float = 0.0) -> float:
    return float(np.percentile(values, q)) if len(values) else default


def by_car(frames) -> dict:
    """Frames grouped by car type ("" when the plugin did not say)."""
    out = defaultdict(list)
    for f in frames:
        out[f["extra"].get("car", "")].append(f)
    return dict(out)


MIN_IDLE_RPM = 300.0              # Trackmania's rpm falls to ~0 standing still; that is no idle to tune to


def engine_range(frames):
    """max_rpm, and idle_rpm when the standing rpm is a real idle (None when it drops to ~0)."""
    rpm = [f["rpm"] for f in frames if f["rpm"] > 50.0]
    if len(rpm) < 50:
        return None
    idle = [f["rpm"] for f in frames if f["speed"] < 2.0 and f["rpm"] > 50.0]
    idle_rpm = math.floor((statistics.median(idle) if idle else pct(rpm, 1)) / 100.0) * 100.0
    return {"max_rpm": math.ceil(pct(rpm, 99.9) / 100.0) * 100.0,
            "idle_rpm": idle_rpm if idle_rpm >= MIN_IDLE_RPM else None,
            "seen": (min(rpm), max(rpm)), "gears": sorted({f["gear"] for f in frames})}


def engines(frames) -> dict:
    """engine_range for every car type with enough data."""
    return {car: eng for car, fs in by_car(frames).items() if (eng := engine_range(fs))}


def damper_travel(frames):
    """Metres between the 0.5 % and 99.5 % damper lengths of settled wheels on the ground (the only
    movement the suspension effect feels), or None with too little data."""
    dampers = [d for f in frames if f["extra"].get("ground_contact", True)
               for i, d in enumerate(_raw(f)) if _settled(f, i)]
    if len(dampers) < 200:
        return None
    return round(max(pct(dampers, 99.5) - pct(dampers, 0.5), 0.01), 4)


def _raw(f) -> list:
    """Damper lengths in metres as sent (the parsed travel is held while wheels fly or settle)."""
    return f["extra"].get("damper_len") or f["damper"]


def _settled(f, i: int) -> bool:
    """Is wheel i on the ground and done settling? Only then is its movement a bump the effect feels."""
    flags = f["extra"].get("wheel_settled")
    return bool(flags[i]) if flags else True


def suspension(frames):
    """Damper travel per car, and bump thresholds in fractions of that car's travel per second."""
    travel = {car: t for car, fs in by_car(frames).items() if (t := damper_travel(fs))}
    if not travel:
        return None
    speeds = []
    bs = blocks(frames)
    for a, b in zip(bs, bs[1:]):
        dt = b["t"] - a["t"]
        span = travel.get(b["extra"].get("car", ""))
        if span and 0.0 < dt < 0.1 and b["speed"] > 5.0 and b["extra"].get("ground_contact", True):
            speeds += [abs(db - da) / span / dt for i, (da, db) in enumerate(zip(_raw(a), _raw(b)))
                       if _settled(a, i) and _settled(b, i)]
    if len(speeds) < 100:
        return None
    return {"travel": travel, "threshold": round(max(pct(speeds, 97), 0.2), 3),
            "full": round(max(pct(speeds, 99.8), 1.0), 3)}


def impacts(frames):
    bs, jumps = blocks(frames), []
    for a, b in zip(bs, bs[1:]):
        if 0.0 < b["t"] - a["t"] < 0.1:
            jumps.append((math.hypot(b["lat"] - a["lat"], b["long"] - a["long"]), b["t"]))
    if len(jumps) < 100:
        return None
    mags = [j[0] for j in jumps]
    threshold = max(40.0, pct(mags, 99.8))
    biggest, last = [], -1e9
    for mag, t in sorted(jumps, reverse=True):
        if all(abs(t - bt) > 0.5 for _, bt in biggest):           # one entry per crash
            biggest.append((mag, t))
        if len(biggest) == 8:
            break
    return {"threshold": round(threshold, 1), "full": round(max(threshold * 4.0, pct(mags, 99.99)), 1),
            "biggest": biggest}


def landings(frames):
    events, air_since, fall = [], None, 0.0
    for f in blocks(frames):
        ex = f["extra"]
        if not ex.get("ground_contact", True):
            if air_since is None:
                air_since, fall = f["t"], 0.0
            fall = max(fall, -float(ex.get("vert_speed", 0.0)))
            continue
        if air_since is not None:
            if f["t"] - air_since >= 0.12:
                events.append({"t": f["t"], "airtime": f["t"] - air_since, "fall": fall})
            air_since = None
    if not events:
        return None
    falls = [e["fall"] for e in events]
    return {"count": len(events), "v_min": round(max(pct(falls, 10), 1.0), 2),
            "v_full": round(max(pct(falls, 90), 3.0), 2), "airtime_max": max(e["airtime"] for e in events),
            "falls": (min(falls), statistics.median(falls), max(falls))}


def surfaces(frames):
    stats = defaultdict(lambda: {"time": 0.0, "speed": [], "rough": []})
    for a, b in zip(frames, frames[1:]):
        dt = b["t"] - a["t"]
        ex = b["extra"]
        if not 0.0 < dt < 0.1 or not ex.get("ground_contact", True):
            continue
        contact = ex.get("wheel_contact") or [True] * 4
        for i, m in enumerate(ex.get("materials", ())):
            if m < 0 or (i < len(contact) and not contact[i]):
                continue
            s = stats[m]
            s["time"] += dt / 4.0
            s["speed"].append(b["speed"])
            if b["speed"] > 5.0 and _settled(a, i) and _settled(b, i):
                s["rough"].append(abs(_raw(b)[i] - _raw(a)[i]) / dt)
    return stats


def roughness(speeds) -> float:
    """How rough a surface is: the 90th percentile of settled wheels' damper speed (m/s). Not the median:
    most frame-to-frame changes are exactly 0 (frames repeat and damperLen comes in 1 mm steps)."""
    return pct(speeds, 90) if len(speeds) else 0.0


def boosts(frames):
    out = {"turbo pads": 0, "reactor boosts": 0, "water s": 0.0, "roof contact s": 0.0}
    was_turbo, was_reactor = False, 0
    for a, b in zip(frames, frames[1:]):
        dt = b["t"] - a["t"] if 0.0 < b["t"] - a["t"] < 0.1 else 0.0
        ex = b["extra"]
        turbo, reactor = bool(ex.get("turbo")), int(ex.get("reactor_level", 0))
        out["turbo pads"] += int(turbo and not was_turbo)
        out["reactor boosts"] += int(reactor > was_reactor)
        was_turbo, was_reactor = turbo, reactor
        out["water s"] += dt if ex.get("water", 0.0) > 0.05 else 0.0
        out["roof contact s"] += dt if ex.get("top_contact") else 0.0
    return out


def analyse(frames: list[dict], profile: dict, names: dict | None = None) -> dict:
    """Everything tm_tune learns from a drive, as data (what main prints and --apply writes)."""
    names = names or {}
    grip_cfg = dict(profile.get("effects", {}).get("grip_margin") or {})
    grip_cfg["materials"] = {**(grip_cfg.get("materials") or {}), **names}
    loose, off, renames = tm_grip.profile_surfaces(grip_cfg)
    events = tm_grip.find_onsets(frames, 8.0, 0.3, 0.15, max_jolt=150.0, renames=renames)
    return {"engines": engines(frames), "susp": suspension(frames), "imp": impacts(frames),
            "land": landings(frames), "grip": tm_grip.surface_limits(events, loose, min_slides=3),
            "grip_events": events, "surfaces": surfaces(frames), "boosts": boosts(frames)}


def apply_to(profile: dict, res: dict, only=PARTS, names: dict | None = None, session_name: str = "") -> list:
    """Write analyse()'s proposals into a profile dict (in place); returns what was applied."""
    names = names or {}
    effects = profile.setdefault("effects", {})
    applied = []
    cars = profile.setdefault("cars", {})
    measured = {car: {k: eng[k] for k in ("max_rpm", "idle_rpm") if eng[k] is not None}
                for car, eng in res["engines"].items()}
    susp, imp, land, grip = res["susp"], res["imp"], res["land"], res["grip"]
    for car, travel in (susp["travel"] if susp else {}).items():
        measured.setdefault(car, {})["damper_range_m"] = travel
    for car, values in (measured.items() if "cars" in only else ()):
        if not car:
            print("  car type unknown (no vehicleType in the log): engine range and damper travel not written")
            continue
        cars.setdefault(car, {}).update(values)
        applied.append(f"{car} constants")
    if not cars:
        profile.pop("cars")
    if susp and "bumps" in only:
        effects.setdefault("suspension", {}).update(threshold=susp["threshold"], full=susp["full"])
        applied.append("bumps")
    if imp and "impacts" in only:
        effects.setdefault("impact", {}).update(threshold=imp["threshold"], full=imp["full"])
        applied.append("impacts")
    if land and "landings" in only:
        effects.setdefault("landing", {}).update(v_min=land["v_min"], v_full=land["v_full"])
        applied.append("landings")
    if grip and "grip" in only:
        effects.setdefault("grip_margin", {}).setdefault("surfaces", {}).update(grip)
        applied.append("grip limits")
    if names and "names" in only:         # both effects name surfaces the same way
        effects.setdefault("surface", {}).setdefault("materials", {}).update(names)
        effects.setdefault("grip_margin", {}).setdefault("materials", {}).update(names)
        applied.append("surface names")
    meta = profile.setdefault("meta", {})
    meta["tuned_from"] = f"{session_name}: {', '.join(applied) or 'nothing'}"
    if "cars" in profile:
        meta["cars"] = ("rev range and damper travel per vehicle type, measured by tm_tune; they override "
                        "the sources.trackmania config keys, which stay as the fallback for other cars")
    return applied


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.tm_tune", description=__doc__.split("\n")[0])
    ap.add_argument("session", help="folder from a --log run with --source trackmania")
    ap.add_argument("--apply", action="store_true", help="write the proposals into the profile")
    ap.add_argument("--only", default=",".join(PARTS), metavar="PARTS",
                    help=f"with --apply, write only these (comma-separated): {', '.join(PARTS)}")
    ap.add_argument("--name", action="append", default=[], metavar="ID=SURFACE",
                    help="name a surface material id, e.g. 6=Dirt (repeatable)")
    args = ap.parse_args(argv)
    session = Path(args.session)
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    if only - set(PARTS):
        print(f"--only takes {', '.join(PARTS)}; got {', '.join(sorted(only - set(PARTS)))}")
        return 2

    names = {}
    for item in args.name:
        key, _, value = item.partition("=")
        if not key.strip().isdigit() or not value.strip():
            print(f"--name expects ID=Surface, got {item!r}")
            return 2
        names[str(int(key))] = value.strip()

    frames = load_frames(session)
    if not frames:
        print(f"no Trackmania frames in {session} - was it recorded with --source trackmania?")
        return 1
    print(f"{len(frames)} frames over {frames[-1]['t'] - frames[0]['t']:.0f} s\n")
    res = analyse(frames, json.loads(PROFILE.read_text(encoding="utf-8")), names)

    print("ENGINE  (per car type)")
    for car, eng in res["engines"].items():
        idle = (f"idle_rpm {eng['idle_rpm']:.0f}" if eng["idle_rpm"] is not None
                else f"no idle to learn (rpm drops below {MIN_IDLE_RPM:.0f} standing still)")
        print(f"  {car or 'car type unknown'}: rpm seen {eng['seen'][0]:.0f}-{eng['seen'][1]:.0f}, gears "
              f"{eng['gears']}  -> max_rpm {eng['max_rpm']:.0f}, {idle}")
    if not res["engines"]:
        print("  not enough rpm data")

    susp = res["susp"]
    print("BUMPS")
    if susp:
        for car, travel in susp["travel"].items():
            print(f"  {car or 'car type unknown'}: damper travel {travel} m")
        print(f"  -> bumps from {susp['threshold']} to {susp['full']} (fraction of travel per second)")
    else:
        print("  not enough suspension data")

    imp = res["imp"]
    print("IMPACTS")
    if imp:
        print(f"  threshold {imp['threshold']} m/s^2, full {imp['full']} m/s^2; biggest (check these were crashes):")
        for mag, t in imp["biggest"]:
            print(f"    {t:7.1f} s  {mag:8.0f} m/s^2")
    else:
        print("  not enough data")

    land = res["land"]
    print("LANDINGS")
    if land:
        print(f"  {land['count']} jumps, longest {land['airtime_max']:.1f} s; fall speed min/median/max "
              f"{land['falls'][0]:.1f}/{land['falls'][1]:.1f}/{land['falls'][2]:.1f} m/s"
              f" -> v_min {land['v_min']}, v_full {land['v_full']}")
    else:
        print("  no jumps found")

    print("GRIP  (loose surfaces only; see tm_grip for the detail)")
    for name, (lat, slip) in sorted(res["grip"].items()):
        print(f"  {name}: lat_limit {lat} m/s^2, slip_limit_deg {slip}")
    if not res["grip"]:
        print(f"  {len(res['grip_events'])} clean slides, none on a loose surface 3+ times - nothing to learn")

    print("SURFACES  (roughest first)")
    ranked = sorted(res["surfaces"].items(), key=lambda kv: -roughness(kv[1]["rough"]))
    for material, s in ranked:
        label = names.get(str(material), surface_name(material))
        print(f"  id {material:3d}  {s['time']:6.1f} s  avg {statistics.mean(s['speed']) * 3.6:5.0f} km/h  "
              f"roughness {roughness(s['rough']):6.3f} m/s  ({label})")

    print("EXTRAS")
    print("  " + ", ".join(f"{k} {v:.1f}" if isinstance(v, float) else f"{k} {v}" for k, v in res["boosts"].items()))

    if not args.apply:
        print(f"\nadd --apply to write these into {PROFILE.name} (then restart the tray app)")
        return 0

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    applied = apply_to(profile, res, only, names, session.name)
    PROFILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(f"\napplied: {', '.join(applied) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
