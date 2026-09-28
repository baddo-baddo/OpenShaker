"""Check a recorded BeamNG drive: which protocols arrived, how Motion Sim's axes map onto the car, and
how big the bumps, hits and lock-ups were - the numbers BeamNG's effect levels are set from.

    python -m openshaker --source beamng --log sessions/beamng_drive_2 --duration 300
    python -m openshaker.beamng_check sessions/beamng_drive_2

The telemetry log keeps every packet's raw bytes, so the drive is replayed through the real source in
arrival order and the checks never depend on how a previous version of the parser read it.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import numpy as np

from .sources.beamng import AXES, MOTION_MAGIC, MOTION_SIZE, STOCK_SIZES, BeamNGSource, parse_motion

AXIS_NAMES = ("x", "y", "z")
HC_LOCK_RATIO = 0.475            # the BeamNG profile's wheel_lock threshold 3.5 as wheel / ground speed


def load_rows(session: str | Path) -> list[tuple[float, bytes]]:
    rows = []
    with (Path(session) / "telemetry.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            if r.get("raw_hex"):
                rows.append((float(r["t"]), bytes.fromhex(r["raw_hex"])))
    return rows


def replay(rows) -> list[tuple]:
    """(t, raw) in arrival order -> (t, kind, merged Telemetry, Motion Sim fields or None)."""
    src = BeamNGSource(port=0)
    frames = []
    for t, raw in rows:
        if len(raw) == MOTION_SIZE and raw[:4] == MOTION_MAGIC:
            kind = "motion"
        elif len(raw) in STOCK_SIZES:
            kind = "outgauge"
        else:
            kind = "other"
        tele = src.parse(raw, now=t)
        if tele is not None:
            frames.append((t, kind, tele, parse_motion(raw) if kind == "motion" else None))
    return frames


def _corr(a, b) -> float:
    if len(a) < 3 or np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def axis_check(frames, min_speed: float = 3.0, window_s: float = 0.25) -> dict | None:
    """Correlate each Motion Sim acceleration component with what the car visibly did.

    Longitudinal: the rate of change of ground speed. Lateral: speed x yaw rate (its sign depends on
    BeamNG's yaw convention, so only the axis is trusted; the effects use |lat| anyway).
    """
    m = [(t, fr) for t, _, _, fr in frames if fr is not None]
    if len(m) < 20:
        return None
    t = np.array([x[0] for x in m])
    vel = np.array([x[1]["vel"] for x in m], dtype=np.float64)
    acc = np.array([x[1]["acc"] for x in m], dtype=np.float64)
    rate = np.array([x[1]["rate"] for x in m], dtype=np.float64)
    speed = np.linalg.norm(vel, axis=1)
    i = np.arange(len(t))
    j = np.searchsorted(t, t + window_s)
    keep = j < len(t)
    i, j = i[keep], j[keep]
    dt = t[j] - t[i]
    keep = (dt > 0.5 * window_s) & (np.minimum(speed[i], speed[j]) > min_speed)
    i, j, dt = i[keep], j[keep], dt[keep]
    if len(i) < 10:
        return None
    zero = np.zeros((1, 3))
    ca = np.vstack([zero, np.cumsum(acc, axis=0)])
    cr = np.vstack([zero, np.cumsum(rate, axis=0)])
    n = (j - i)[:, None]
    acc_mean, rate_mean = (ca[j] - ca[i]) / n, (cr[j] - cr[i]) / n
    dspeed = (speed[j] - speed[i]) / dt
    lat_expect = 0.5 * (speed[i] + speed[j]) * rate_mean[:, 2]
    long_c = [_corr(acc_mean[:, k], dspeed) for k in range(3)]
    lat_c = [_corr(acc_mean[:, k], lat_expect) for k in range(3)]
    long_axis = int(np.argmax(np.abs(long_c)))
    lat_axis = int(np.argmax([abs(c) if k != long_axis else -1.0 for k, c in enumerate(lat_c)]))
    return {"samples": int(len(i)), "long": long_c, "lat": lat_c, "long_axis": long_axis,
            "long_sign": 1.0 if long_c[long_axis] >= 0 else -1.0, "lat_axis": lat_axis}


def blocks(frames, step: float = 0.01) -> list[tuple[float, object]]:
    """The latest merged frame at every 10 ms audio block, which is all the effects ever see."""
    out, k = [], 0
    if not frames:
        return out
    tb, end = frames[0][0], frames[-1][0]
    while tb <= end + 1e-9:
        while k + 1 < len(frames) and frames[k + 1][0] <= tb + 1e-6:
            k += 1
        out.append((tb, frames[k][2]))
        tb += step
    return out


def pct(values) -> dict | None:
    a = np.asarray(values, dtype=np.float64)
    if a.size == 0:
        return None
    return {"p50": float(np.percentile(a, 50)), "p90": float(np.percentile(a, 90)),
            "p99": float(np.percentile(a, 99)), "p99.8": float(np.percentile(a, 99.8)), "max": float(a.max())}


def top(times, values, n: int = 8, gap_s: float = 0.5) -> list[tuple[float, float]]:
    order = np.argsort(values)[::-1]
    picked: list[tuple[float, float]] = []
    for idx in order:
        if len(picked) >= n:
            break
        if all(abs(times[idx] - t) > gap_s for t, _ in picked):
            picked.append((float(times[idx]), float(values[idx])))
    return picked


def report(frames) -> dict:
    kinds = Counter(k for _, k, _, _ in frames)
    dur = frames[-1][0] - frames[0][0] if len(frames) > 1 else 0.0
    bl = blocks(frames)
    res = {"duration": dur, "rates": {k: v / dur for k, v in kinds.items()} if dur > 0 else dict(kinds),
           "axes": axis_check(frames)}
    mb = [(t, x) for t, x in bl if x.extra.get("motion")]
    res["motion_share"] = len(mb) / max(len(bl), 1)
    ogb = [x for _, x in bl if x.extra.get("wheel_speed") is not None]
    res["outgauge_share"] = len(ogb) / max(len(bl), 1)
    if ogb:
        res["throttle_share"] = sum(1 for x in ogb if x.throttle > 0.05) / len(ogb)
        res["brake_share"] = sum(1 for x in ogb if x.brake > 0.05) / len(ogb)
        res["abs_s"] = sum(1 for x in ogb if x.abs_active) * 0.01
        res["handbrake_s"] = sum(1 for x in ogb if x.handbrake > 0.5) * 0.01
    if len(mb) > 2:
        tt = np.array([t for t, _ in mb])
        lat = np.array([x.accel_lat for _, x in mb])
        lon = np.array([x.accel_long for _, x in mb])
        vert = np.array([x.accel_vert for _, x in mb])
        res["accel"] = {"|lat|": pct(np.abs(lat)), "|long|": pct(np.abs(lon)), "|vert|": pct(np.abs(vert)),
                        "long +": pct(lon[lon > 0]), "long -": pct(-lon[lon < 0])}
        horiz = np.hypot(np.diff(lat), np.diff(lon))
        vjump = np.abs(np.diff(vert))
        res["jumps"] = {"lat+long": pct(horiz), "vert": pct(vjump)}
        res["biggest_hits"] = top(tt[1:], horiz)
        res["biggest_bumps"] = top(tt[1:], vjump)
        braking = [x for _, x in mb if x.brake > 0.3 and x.speed > 5.0 and x.extra.get("wheel_speed") is not None]
        ratios = np.array([x.extra["wheel_speed"] / x.speed for x in braking])
        res["braking_s"] = len(braking) * 0.01
        res["wheel_ratio_braking"] = pct(ratios)
        res["lock_s"] = float(np.sum(ratios < HC_LOCK_RATIO)) * 0.01 if ratios.size else 0.0
    return res


def _fmt(p: dict | None, unit: str = "") -> str:
    if not p:
        return "-"
    return "  ".join(f"{k} {v:6.2f}{unit}" for k, v in p.items())


def format_report(r: dict) -> str:
    lines = [f"duration {r['duration']:.1f} s; packets per second: "
             + ", ".join(f"{k} {v:.0f}" for k, v in sorted(r["rates"].items())),
             f"blocks with OutGauge {100 * r['outgauge_share']:.0f} %, with Motion Sim {100 * r['motion_share']:.0f} %"]
    if r["motion_share"] == 0:
        lines.append("NO MOTION SIM: tick Motion Sim in BeamNG (Options > Other); crashes, bumps and wheel lock need it")
    if r["outgauge_share"] == 0:
        lines.append("NO OUTGAUGE: tick OutGauge in BeamNG (Options > Other); engine, gears and pedals need it")
    if "throttle_share" in r:
        lines.append(f"pedals: throttle {100 * r['throttle_share']:.0f} % of the time, brake "
                     f"{100 * r['brake_share']:.0f} %, ABS lit {r['abs_s']:.1f} s, handbrake {r['handbrake_s']:.1f} s")
    ax = r.get("axes")
    lines.append("")
    if ax:
        used = AXIS_NAMES[AXES[1][0]]
        found = AXIS_NAMES[ax["long_axis"]]
        lines.append("AXES  correlation with d(ground speed)/dt: "
                     + "  ".join(f"{AXIS_NAMES[k]} {c:+.2f}" for k, c in enumerate(ax["long"])))
        lines.append("      correlation with speed x yaw rate:    "
                     + "  ".join(f"{AXIS_NAMES[k]} {c:+.2f}" for k, c in enumerate(ax["lat"])))
        verdict = "matches" if (found == used and ax["long_sign"] == AXES[1][1]) else "DOES NOT MATCH"
        lines.append(f"      longitudinal = {'+' if ax['long_sign'] > 0 else '-'}{found}, lateral = "
                     f"{AXIS_NAMES[ax['lat_axis']]} ({ax['samples']} windows); sources.beamng.AXES {verdict}")
    else:
        lines.append("AXES  not enough Motion Sim data while moving to check")
    if "accel" in r:
        lines.append("")
        lines.append("ACCELERATION (m/s^2, per 10 ms block)")
        for k, p in r["accel"].items():
            lines.append(f"  {k:7s} {_fmt(p)}")
        lines.append("JUMPS between blocks (impact threshold and suspension vert_threshold are compared with these)")
        for k, p in r["jumps"].items():
            lines.append(f"  {k:8s} {_fmt(p)}")
        lines.append("  biggest hits : " + ", ".join(f"{v:.0f} @ {t:.1f}s" for t, v in r["biggest_hits"]))
        lines.append("  biggest bumps: " + ", ".join(f"{v:.0f} @ {t:.1f}s" for t, v in r["biggest_bumps"]))
        lines.append("")
        lines.append(f"BRAKING above 5 m/s: {r['braking_s']:.1f} s; wheel / ground speed: {_fmt(r['wheel_ratio_braking'])}")
        lines.append(f"  below {HC_LOCK_RATIO} (where wheel_lock fires): {r['lock_s']:.1f} s")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.beamng_check", description="Check a recorded BeamNG drive.")
    ap.add_argument("session", help="folder written by --log (holds telemetry.csv)")
    args = ap.parse_args(argv)
    rows = load_rows(args.session)
    if not rows:
        print(f"no packets in {args.session}")
        return 1
    print(format_report(report(replay(rows))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
