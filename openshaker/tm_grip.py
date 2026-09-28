"""Where does Trackmania's grip actually run out? Learn the grip warning's limits from a recorded drive.

  python -m openshaker --source trackmania --log sessions/tm_drive_1 --duration 300     (drive)
  python -m openshaker.tm_grip sessions/tm_drive_1                                     (report)
  python -m openshaker.tm_grip sessions/tm_drive_1 --apply                             (write the profile)

SlipCoef is 0 while the tyres grip and turns positive once they let go, so every 0 -> >0 change on a
grounded car is a moment it hit the limit. This reads the sideways acceleration and body slip angle
in the fraction of a second before each of those moments, per surface. Moments that were not a
corner running out of grip are left out: a wheel in the air during the run-up (a landing), or a jolt
bigger than --max-jolt m/s^2 between two frames around the moment (a crash).

The warning only runs on loose surfaces (dirt, grass, sand, snow, ice, wet roads - the table in
effects.trackmania.GripMarginEffect.LOOSE): on tarmac the Stadium car turns as tight as its steering
allows without letting go. --apply writes [lat_limit, slip_limit_deg] per loose surface with at least
--min-slides clean slides into grip_margin.surfaces; with the default onset of 0.6 the warning then
starts at 60 % of where the car typically lets go on that surface. Tarmac slides are reported only,
and a surface the profile switched off ([0, 0]) is never switched back on.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .effects.trackmania import GripMarginEffect
from .sources.trackmania import SURFACES, parse_snapshot, surface_name  # noqa: F401

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROFILE = PROJECT_DIR / "profiles" / "trackmania" / "profile.json"


def load_frames(session: Path) -> list[dict]:
    """Trackmania rows of a --log session, with the full plugin snapshot decoded from raw_hex."""
    csv.field_size_limit(2 ** 31 - 1)
    frames = []
    with (session / "telemetry.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("source") != "trackmania" or not row.get("raw_hex"):
                continue
            try:
                msg = json.loads(bytes.fromhex(row["raw_hex"]))
            except ValueError:
                continue
            tele = parse_snapshot(msg, {})                  # for the per-frame extras; accel comes from the log
            if tele is None:
                continue
            frames.append({"t": float(row["t"]), "speed": float(row["speed"]),
                           "lat": float(row["accel_lat"]), "long": float(row.get("accel_long") or 0.0),
                           "extra": tele.extra})
    return frames


def _jolt(frames: list[dict], i: int, span: int = 5) -> float:
    """Largest change in body acceleration between neighbouring frames around frame i (m/s^2)."""
    lo, hi = max(i - span, 1), min(i + span, len(frames) - 1)
    return max((abs(frames[k]["lat"] - frames[k - 1]["lat"]) + abs(frames[k]["long"] - frames[k - 1]["long"])
                for k in range(lo, hi + 1)), default=0.0)


def find_onsets(frames: list[dict], min_speed: float, lookback_s: float, smooth: float,
                max_jolt: float = float("inf"), renames: dict | None = None) -> list[dict]:
    """Every moment a grounded, gripping car starts to slide, with what led up to it.
    `renames` {material id: surface name} relabels surfaces as the profile does."""
    events, lat_s, grip_since = [], 0.0, None
    history: list[tuple] = []
    for i, f in enumerate(frames):
        ex = f["extra"]
        sliding = any(c > 0.0 for c in ex.get("slip_coef", ()))
        grounded = ex.get("ground_contact", True) and all(ex.get("wheel_contact") or [True])
        lat_s += (abs(f["lat"]) - lat_s) * smooth                      # the same smoothing the effect uses
        if not grounded:
            grip_since, history = None, []
            continue
        if not sliding:
            if grip_since is None:
                grip_since = f["t"]
            history.append((f["t"], lat_s, abs(ex.get("body_slip_deg", 0.0))))
            history = [h for h in history if f["t"] - h[0] <= lookback_s]
            continue
        # sliding now: count it only if the car had been gripping for the whole look-back window
        if grip_since is not None and f["t"] - grip_since >= lookback_s and f["speed"] > min_speed and history \
                and _jolt(frames, i) <= max_jolt:
            labels = [(renames or {}).get(m, n) for m, n in zip(ex.get("materials") or [], ex.get("surfaces") or [])]
            names = [n for n, c in zip(labels, ex.get("wheel_contact") or [True] * 4) if c and n]
            if not names:
                names = [(renames or {}).get(m, surface_name(m)) for m in ex.get("materials", ()) if m >= 0]
            events.append({"t": f["t"], "speed": f["speed"],
                           "lat": max(h[1] for h in history), "body": max(h[2] for h in history),
                           "surface": Counter(names).most_common(1)[0][0] if names else "unknown"})
        grip_since, history = None, []
    return events


def summarise(values: list[float]) -> str:
    if not values:
        return "-"
    q = statistics.quantiles(values, n=4) if len(values) >= 4 else [min(values), statistics.median(values), max(values)]
    return f"median {statistics.median(values):6.2f}  (25% {q[0]:6.2f}, 75% {q[-1]:6.2f})"


def profile_surfaces(grip: dict) -> tuple[set, set, dict]:
    """(loose surfaces, surfaces the user switched off, material renames) from a grip_margin block."""
    table = grip.get("surfaces") or {}
    off = set()
    for name, spec in table.items():
        try:
            if min(float(x) for x in spec) <= 0.0:
                off.add(name)
        except (TypeError, ValueError):
            off.add(name)
    renames = {}
    for key, name in (grip.get("materials") or {}).items():
        try:
            renames[int(key)] = str(name)
        except (TypeError, ValueError):
            continue
    return (set(GripMarginEffect.LOOSE) | set(table)) - off, off, renames


def surface_limits(events: list[dict], loose, min_slides: int) -> dict:
    """{surface: [lat_limit, slip_limit_deg]} for loose surfaces with enough slides (medians)."""
    by_surface = defaultdict(list)
    for e in events:
        by_surface[e["surface"]].append(e)
    out = {}
    for name, evs in by_surface.items():
        if name in loose and len(evs) >= min_slides:
            out[name] = [round(statistics.median(e["lat"] for e in evs), 2),
                         round(max(statistics.median(e["body"] for e in evs), 0.5), 2)]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.tm_grip", description=__doc__.split("\n")[0])
    ap.add_argument("session", help="folder from a --log run with --source trackmania")
    ap.add_argument("--min-speed", type=float, default=8.0, help="ignore slides below this speed (m/s)")
    ap.add_argument("--lookback", type=float, default=0.3, help="seconds of gripping before a slide to inspect")
    ap.add_argument("--smooth", type=float, default=0.15, help="sideways-accel smoothing, as in the effect")
    ap.add_argument("--max-jolt", type=float, default=150.0,
                    help="leave out slides with a bigger acceleration jump around them (crashes), m/s^2")
    ap.add_argument("--min-slides", type=int, default=3, help="slides a surface needs before --apply writes it")
    ap.add_argument("--apply", action="store_true", help="write the learned loose-surface limits into the profile")
    args = ap.parse_args(argv)

    frames = load_frames(Path(args.session))
    if not frames:
        print(f"no Trackmania frames in {args.session} - was it recorded with --source trackmania?")
        return 1
    data = json.loads(PROFILE.read_text(encoding="utf-8"))
    grip = data.setdefault("effects", {}).setdefault("grip_margin", {"gain": 0.3, "enabled": True})
    loose, off, renames = profile_surfaces(grip)
    events = find_onsets(frames, args.min_speed, args.lookback, args.smooth, args.max_jolt, renames)
    crashes = len(find_onsets(frames, args.min_speed, args.lookback, args.smooth, renames=renames)) - len(events)
    print(f"{len(frames)} frames, {frames[-1]['t'] - frames[0]['t']:.0f} s, {len(events)} moments the car let go"
          f" ({crashes} more left out as crashes)\n")
    if not events:
        print("no slides found - drive harder into a few corners on dirt or grass, or lower --min-speed")
        return 1

    by_surface = defaultdict(list)
    for e in events:
        by_surface[e["surface"]].append(e)
    for name, evs in sorted(by_surface.items(), key=lambda kv: -len(kv[1])):
        kind = "loose" if name in loose else ("switched off in the profile" if name in off
                                              else "grippy - no warning here")
        print(f"{name} ({kind}; {len(evs)} slides, {min(e['speed'] for e in evs) * 3.6:.0f}-"
              f"{max(e['speed'] for e in evs) * 3.6:.0f} km/h)")
        print(f"   sideways accel before letting go (m/s^2): {summarise([e['lat'] for e in evs])}")
        print(f"   body slip before letting go (degrees)   : {summarise([e['body'] for e in evs])}")

    learned = surface_limits(events, loose, args.min_slides)
    if learned:
        print("\nproposed grip_margin.surfaces (the median of where the car let go; the warning starts at 60 %):")
        for name, (lat, slip) in sorted(learned.items()):
            print(f"  {name}: lat_limit {lat} m/s^2, slip_limit_deg {slip}")
    else:
        print(f"\nno loose surface has {args.min_slides}+ clean slides yet - nothing to write")

    if args.apply and learned:
        grip.setdefault("surfaces", {}).update(learned)
        data.setdefault("meta", {})["grip_margin_learned"] = (
            f"{', '.join(sorted(learned))} learned from {Path(args.session).name}: median of the clean slide "
            f"onsets per surface (sideways accel and body slip in the {args.lookback} s before SlipCoef turned "
            f"positive)")
        PROFILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"written to {PROFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
