"""Fit our effect gains so that our spectrogram matches HaptiConnect's on a real drive.

  python -m openshaker.fit sessions/fm_drive_1_hc --profile profiles/forza_motorsport/profile.json [--apply]

Method: every effect in the profile is rendered ALONE (gain 1) from the session's telemetry; the
power spectrogram of HaptiConnect's recording is modelled as a non-negative combination of the
effects' power spectrograms (uncorrelated sources add in power), solved with NNLS across all
time-frequency cells between 15 and 150 Hz. sqrt(weight) is the gain each effect should have.
The residual (what HaptiConnect has that no effect explains) is reported per band and plotted.
--apply writes the fitted gains into the profile (previous version kept as profile_prev.json).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

from . import config
from .analyze import read_wav
from .compare import best_lag, envelope, load_frames, render_offline

NFFT, HOP = 4096, 2400            # 50 ms hop at 48 kHz
FMIN, FMAX = 15.0, 150.0


def power_spectrogram(x: np.ndarray, sr: int):
    n = 1 + max(len(x) - NFFT, 0) // HOP
    win = np.hanning(NFFT)
    freqs = np.fft.rfftfreq(NFFT, 1.0 / sr)
    band = (freqs >= FMIN) & (freqs <= FMAX)
    out = np.zeros((n, band.sum()))
    for i in range(n):
        seg = x[i * HOP:i * HOP + NFFT]
        if len(seg) < NFFT:
            seg = np.pad(seg, (0, NFFT - len(seg)))
        spec = np.abs(np.fft.rfft(seg * win)) ** 2
        out[i] = spec[band]
    return out, freqs[band]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.fit")
    ap.add_argument("session", help="session with HaptiConnect's audio.wav + telemetry.csv (from openshaker.replay)")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--apply", action="store_true", help="write the fitted gains into the profile")
    ap.add_argument("--min-gain", type=float, default=0.0)
    ap.add_argument("--effects", help="comma list to fit (default: all in profile + road)")
    ap.add_argument("--weight", type=float, default=0.25, help="row-weight exponent on HaptiConnect power (0 = none)")
    args = ap.parse_args(argv)
    from scipy.optimize import nnls

    session = Path(args.session)
    hc, sr = read_wav(session / "audio.wav")
    frames = load_frames(session / "telemetry.csv")
    secs = len(hc) / sr
    cfg = config.load(None)
    config.apply_profile(cfg, args.profile)
    effects = args.effects.split(",") if args.effects else sorted(set(list(cfg.get("_profile_effects", {})) + ["road"]))
    effects = [e for e in effects if e in cfg["effects"]]

    # render every effect alone at gain 1
    renders = {}
    for name in effects:
        c = config.load(None)
        config.apply_profile(c, args.profile)
        c["effects"][name]["gain"] = 1.0
        renders[name] = render_offline(frames, secs, c, [name], sr=sr)
    # global lag: HaptiConnect reacts later than we do; align our renders to it
    mix = sum(renders.values())
    lag = best_lag(envelope(hc, sr, 0.02), envelope(mix, sr, 0.02), 0.02, 0.4)
    shift = int(lag * 0.02 * sr)
    if shift > 0:
        for k in renders:
            renders[k] = np.concatenate([np.zeros(shift, dtype=np.float32), renders[k]])[:len(hc)]
    print(f"session {session.name}: {secs:.0f} s, HaptiConnect lag {lag * 20:+d} ms applied to our renders")

    P_hc, freqs = power_spectrogram(hc, sr)
    P = {k: power_spectrogram(v[:len(hc)], sr)[0] for k, v in renders.items()}
    act = np.array([f.active for f in frames], float)
    t_frames = np.array([f.t for f in frames])
    tt = np.arange(P_hc.shape[0]) * HOP / sr
    active = np.interp(tt, t_frames, act) > 0.5
    A = np.stack([P[k][active].ravel() for k in effects], axis=1)
    b = P_hc[active].ravel()
    # power domain (uncorrelated sources add in power): b ~ sum_e w_e * P_e with w_e = gain_e^2.
    # Row weights (b+eps)^-weight temper the loudest cells; weight 0 = plain least squares.
    s = (b + np.percentile(b, 50) * 0.01) ** args.weight
    w, rnorm = nnls(A / s[:, None], b / s)
    gains = {k: float(np.sqrt(max(v, 0.0))) for k, v in zip(effects, w)}
    fitted = A @ w
    explained = 1.0 - np.sum((b - fitted) ** 2) / np.sum((b - b.mean()) ** 2)          # plain power-domain R^2
    lb, lf = 10 * np.log10(b + 1e-9), 10 * np.log10(fitted + 1e-9)
    print(f"cell-wise dB error (HaptiConnect - model): median {np.median(lb - lf):+.1f} dB, "
          f"IQR {np.percentile(lb - lf, 25):+.1f}..{np.percentile(lb - lf, 75):+.1f} dB")
    print(f"explained power variance: {explained * 100:.0f}%")
    print(f"{'effect':16s} {'fitted gain':>11s} {'share of HC power':>18s}")
    tot = fitted.sum() + 1e-12
    for k, wi in zip(effects, w):
        share = (P[k][active].ravel() * wi).sum() / tot * 100
        print(f"{k:16s} {gains[k]:11.3f} {share:17.0f}%")

    # residual per band: HC power not explained (positive) or over-modelled (negative)
    resid = (P_hc[active] - (np.stack([P[k][active] for k in effects], 0) * w[:, None, None]).sum(0))
    bands = [(15, 35), (35, 50), (50, 70), (70, 100), (100, 150)]
    print("\nresidual by band (share of HC power in that band; + = HaptiConnect has more, - = we have more):")
    for lo, hi in bands:
        m = (freqs >= lo) & (freqs < hi)
        r = resid[:, m].sum() / (P_hc[active][:, m].sum() + 1e-12) * 100
        print(f"  {lo:3d}-{hi:3d} Hz: {r:+5.0f}%")
    # time profile of residual (where HC has energy we do not)
    r_t = resid.sum(1) / (P_hc[active].sum(1) + 1e-12)
    print(f"cells where HaptiConnect exceeds our model by >50%: {np.mean(r_t > 0.5) * 100:.0f}% of driving time; "
          f"where we exceed it by >50%: {np.mean(r_t < -0.5) * 100:.0f}%")

    out_dir = Path(args.profile).parent
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        model = np.stack([P[k] for k in effects], 0) * w[:, None, None]
        model = model.sum(0)
        fig, ax = plt.subplots(3, 1, figsize=(13, 9), sharex=True, constrained_layout=True)
        vmax = 10 * np.log10(P_hc.max() + 1e-12)
        for a, Pm, name in ((ax[0], P_hc, "HaptiConnect"), (ax[1], model, "our effects, fitted gains")):
            a.imshow(10 * np.log10(Pm.T + 1e-9), origin="lower", aspect="auto", cmap="magma",
                     extent=[tt[0], tt[-1], freqs[0], freqs[-1]], vmin=vmax - 60, vmax=vmax)
            a.set_ylabel(f"{name}\nHz")
        d = 10 * np.log10((P_hc.T + 1e-9) / (model.T + 1e-9))
        im = ax[2].imshow(np.clip(d, -20, 20), origin="lower", aspect="auto", cmap="coolwarm",
                          extent=[tt[0], tt[-1], freqs[0], freqs[-1]], vmin=-20, vmax=20)
        ax[2].set_ylabel("HaptiConnect / ours\ndB (red = they have more)")
        ax[2].set_xlabel("seconds")
        fig.colorbar(im, ax=ax[2], fraction=0.02)
        png = out_dir / f"fit_{session.name}.png"
        fig.savefig(png, dpi=105)
        plt.close(fig)
        print("plot:", png)
    except Exception as exc:
        print("(plot skipped:", exc, ")")

    if args.apply:
        pp = Path(args.profile)
        shutil.copy(pp, pp.with_name("profile_prev.json"))
        data = json.loads(pp.read_text(encoding="utf-8"))
        for k, g in gains.items():
            data["effects"].setdefault(k, {})["gain"] = round(max(g, args.min_gain), 3)
        data.setdefault("meta", {})["fitted_from"] = config.portable_path(session)
        data["meta"]["fit_explained_variance"] = round(float(explained), 3)
        pp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print("applied fitted gains to", pp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
