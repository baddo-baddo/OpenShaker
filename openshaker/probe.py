"""Read out a recorded session.

  python -m openshaker.probe <session>            # probe sessions: per stimulus segment, did HaptiConnect respond
  python -m openshaker.probe <session> --bursts   # any session: every burst HaptiConnect produced + telemetry then
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

from .analyze import read_wav

SNAP = ["gear", "rpm", "throttle", "brake", "speed", "accel_long", "accel_lat", "accel_vert",
        "slip_ratio_0", "slip_ratio_2", "slip_angle_0", "susp_travel_0", "susp_travel_2",
        "rumble_strip_1", "surface_rumble_0"]


def segments_for(stimulus: str):
    from . import calibrate as c
    if stimulus == "collision_probe":
        return [(lbl, 3.0 + 4.0 * k, 1.5) for k, (lbl, *_rest) in enumerate(c.COLLISION_PROBE)]
    if stimulus == "collision":
        return [(lbl, 3.0 + 4.0 * k, 1.5) for k, (lbl, *_rest) in enumerate(c.COLLISION_VARIANTS)]
    if stimulus == "suspension_probe":
        return [(lbl, 3.0 + 3.0 * k, 1.0) for k, (lbl, *_rest) in enumerate(c.SUSP_PROBE)]
    if stimulus == "lock_probe":
        return [(lbl, 3.0 + 5.0 * k, 3.0) for k, (lbl, *_rest) in enumerate(c.LOCK_PROBE)]
    if stimulus == "accel_probe":
        return [(lbl, 3.0 + 4.5 * k, 3.0) for k, (lbl, *_rest) in enumerate(c.ACCEL_PROBE)]
    if stimulus == "rumble_probe":
        return [(lbl, 3.0 + 6.0 * k, 4.5) for k, (lbl, *_rest) in enumerate(c.RUMBLE_PROBE)]
    if stimulus == "slip_probe":
        return [(lbl, 3.0 + 6.0 * k, 4.5) for k, (lbl, *_rest) in enumerate(c.SLIP_PROBE)]
    if stimulus == "shift_indicator_probe":
        return [(lbl, 3.0 + 6.0 * k, 4.5) for k, (lbl, *_rest) in enumerate(c.SHIFTIND_PROBE)]
    if stimulus == "lock_fm_probe":
        return [(lbl, 3.0 + 6.0 * k, 4.5) for k, (lbl, *_rest) in enumerate(c.LOCK_FM_PROBE)]
    if stimulus == "susp_fm_probe":
        return [(lbl, 3.0 + 6.0 * k, 5.5) for k, (lbl, *_rest) in enumerate(c.SUSP_FM_PROBE)]
    if stimulus == "rumble_probe2":
        return [(lbl, 3.0 + 4.5 * k, 3.5) for k, (lbl, *_rest) in enumerate(c.RUMBLE2_PROBE)]
    if stimulus == "shift_probe":
        return [(lbl, 3.0 + 6.0 * k + 1.9, 2.5) for k, (lbl, *_rest) in enumerate(c.SHIFT_PROBE)]
    return None


def dominant_hz(seg: np.ndarray, sr: int) -> float:
    if len(seg) < 64:
        return float("nan")
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    band = (freqs >= 10) & (freqs <= 200)
    return float(freqs[band][np.argmax(spec[band])]) if band.any() else float("nan")


def bursts(x: np.ndarray, sr: int, thr: float = 0.03, merge_s: float = 0.12):
    win = int(0.010 * sr)
    env = np.sqrt(np.convolve(x.astype(np.float64) ** 2, np.ones(win) / win, mode="same"))
    loud = env > thr
    out = []
    i = 0
    n = len(loud)
    while i < n:
        if not loud[i]:
            i += 1
            continue
        j = i
        while j < n and (loud[j] or (j + int(merge_s * sr) < n and loud[j:j + int(merge_s * sr)].any())):
            j += 1
        seg = x[i:j].astype(np.float64)
        out.append((i / sr, (j - i) / sr, float(np.abs(seg).max()), float(np.sqrt((seg ** 2).mean())),
                    dominant_hz(seg, sr)))
        i = j
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.probe")
    ap.add_argument("session")
    ap.add_argument("--bursts", action="store_true", help="list every burst with the telemetry at that moment")
    ap.add_argument("--thr", type=float, default=0.03)
    ap.add_argument("--max", type=int, default=60)
    args = ap.parse_args(argv)
    session = Path(args.session)
    meta = json.loads((session / "meta.json").read_text(encoding="utf-8"))
    stimulus = meta.get("stimulus", meta.get("effect"))
    x, sr = read_wav(session / "audio.wav")
    with (session / "telemetry.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    t_tel = np.array([float(r["t"]) for r in rows])
    first_t = t_tel[0]
    print(meta.get("note", ""))
    print(f"audio {len(x) / sr:.1f} s, peak {np.abs(x).max():.2f}; telemetry {len(rows)} frames from t={first_t:.2f}\n")

    segs = None if args.bursts else segments_for(stimulus)
    if segs is not None:
        win = int(0.010 * sr)
        env = np.sqrt(np.convolve(x.astype(np.float64) ** 2, np.ones(win) / win, mode="same"))
        print(f"{'segment':22s} {'t':>6s} {'fired':>6s} {'peak':>6s} {'rms':>6s} {'len ms':>7s} {'Hz':>6s}")
        for label, t_rel, length in segs:
            i0, i1 = int((first_t + t_rel) * sr), int((first_t + t_rel + length) * sr)
            seg, e = x[i0:i1], env[i0:i1]
            loud = e > args.thr
            if not loud.any():
                print(f"{label:22s} {t_rel:6.1f} {'no':>6s}")
                continue
            a = int(np.argmax(loud))
            b = len(loud) - int(np.argmax(loud[::-1]))
            burst = seg[a:b].astype(np.float64)
            print(f"{label:22s} {t_rel:6.1f} {'YES':>6s} {np.abs(burst).max():6.2f} {np.sqrt((burst ** 2).mean()):6.3f} "
                  f"{(b - a) / sr * 1000:7.0f} {dominant_hz(burst, sr):6.1f}")
        return 0

    bl = bursts(x, sr, args.thr)
    print(f"{len(bl)} bursts (threshold {args.thr}); telemetry at burst start (stimulus time = t - {first_t:.2f}):")
    cols = [c for c in SNAP if c in rows[0]]
    print(f"{'t':>7s} {'len ms':>7s} {'peak':>5s} {'rms':>5s} {'Hz':>6s} | " + " ".join(f"{c[:9]:>9s}" for c in cols))
    for (t, dur, pk, rms, hz) in bl[:args.max]:
        k = min(max(int(np.searchsorted(t_tel, t, side="right") - 1), 0), len(rows) - 1)
        vals = " ".join(f"{float(rows[k][c]):9.2f}" for c in cols)
        print(f"{t:7.2f} {dur * 1000:7.0f} {pk:5.2f} {rms:5.2f} {hz:6.1f} | {vals}")
    if len(bl) > args.max:
        print(f"... {len(bl) - args.max} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
