"""Visualize a recorded session: what we sent HaptiConnect (telemetry) versus what came out (audio).

  python -m openshaker.viz sessions/<session> [--out file.png] [--channels rpm,throttle,gear]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

from .analyze import read_wav

CANDIDATES = ["rpm", "throttle", "brake", "gear", "speed", "accel_long", "accel_lat", "accel_vert",
              "slip_ratio_0", "slip_ratio_2", "slip_angle_0", "susp_travel_0", "susp_travel_2",
              "rumble_strip_1", "surface_rumble_0", "abs_active"]
LABELS = {"rpm": "engine rpm", "throttle": "throttle 0..1", "brake": "brake 0..1", "gear": "gear",
          "speed": "speed m/s", "accel_long": "g long m/s²", "accel_lat": "g lat m/s²", "accel_vert": "g vert m/s²",
          "slip_ratio_0": "slip FL (norm)", "slip_ratio_2": "slip RL (norm)", "slip_angle_0": "slip angle FL",
          "susp_travel_0": "susp FL", "susp_travel_2": "susp RL", "rumble_strip_1": "rumble strip FR",
          "surface_rumble_0": "surface FL", "abs_active": "ABS"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.viz")
    ap.add_argument("session")
    ap.add_argument("--out")
    ap.add_argument("--channels", help="comma-separated telemetry columns to plot (default: the ones that vary)")
    ap.add_argument("--fmax", type=float, default=160.0)
    args = ap.parse_args(argv)
    session = Path(args.session)
    meta = json.loads((session / "meta.json").read_text(encoding="utf-8")) if (session / "meta.json").exists() else {}
    x, sr = read_wav(session / "audio.wav")
    with (session / "telemetry.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    t = np.array([float(r["t"]) for r in rows])
    cols = args.channels.split(",") if args.channels else None
    if cols is None:
        cols = []
        for c in CANDIDATES:
            v = np.array([float(r[c]) for r in rows])
            if np.std(v) > 1e-6:
                cols.append(c)
            if len(cols) >= 5:
                break
        if not cols:
            cols = ["rpm", "speed"]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n_in = len(cols)
    fig, axes = plt.subplots(n_in + 2, 1, figsize=(12, 1.4 * n_in + 6), sharex=True,
                             gridspec_kw={"height_ratios": [1] * n_in + [1.6, 3.2]}, constrained_layout=True)
    fig.suptitle(f"{session.name}\n{meta.get('note', '')}", fontsize=10)
    for ax, c in zip(axes[:n_in], cols):
        v = np.array([float(r[c]) for r in rows])
        ax.step(t, v, where="post", lw=0.9, color="tab:blue")
        ax.set_ylabel(LABELS.get(c, c), fontsize=8)
        ax.grid(alpha=0.3)
    axes[0].set_title("IN  ->  telemetry values sent to HaptiConnect (60 packets / s)", fontsize=9, loc="left")

    ax = axes[n_in]
    win = int(0.01 * sr)
    env = np.sqrt(np.convolve(x.astype(np.float64) ** 2, np.ones(win) / win, mode="same"))
    ta = np.arange(len(x)) / sr
    step = max(len(x) // 20000, 1)
    ax.plot(ta[::step], x[::step], lw=0.3, color="0.6", label="waveform")
    ax.plot(ta[::step], env[::step], lw=1.0, color="tab:red", label="envelope (RMS)")
    ax.set_ylabel("OUT level", fontsize=8)
    ax.set_ylim(-1.05, 1.05)
    ax.legend(loc="upper right", fontsize=7)
    ax.set_title("OUT  ->  what HaptiConnect sent to the ButtKicker", fontsize=9, loc="left")

    ax = axes[n_in + 1]
    with np.errstate(divide="ignore"):
        ax.specgram(x + 1e-7 * np.random.default_rng(0).standard_normal(len(x)), NFFT=4096, Fs=sr,
                    noverlap=3584, cmap="magma", vmin=-100)
    ax.set_ylim(0, args.fmax)
    ax.set_ylabel("OUT spectrogram Hz", fontsize=8)
    ax.set_xlabel("seconds")
    out = Path(args.out) if args.out else session / "session.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
