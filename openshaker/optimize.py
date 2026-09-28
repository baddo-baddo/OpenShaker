"""Fit a profile's effect gains to HaptiConnect recordings by minimizing spectrogram distance.

  python -m openshaker.optimize --profile profiles/forza_motorsport/profile.json sessions/fm_drive_1_hc sessions/fm_drive_3_hc ...
      [--apply] [--holdout sessions/fm_drive_6_hc] [--susp-scale 0.08] [--fix abs] [--seed 1]

Every effect is rendered alone at gain 1 from each session's telemetry (cached), turned into a complex
STFT (15-150 Hz, 50 ms hops); since effects add linearly, any gain vector gives the mixed spectrogram
instantly, and the gains are optimized to minimize the mean |dB| difference to HaptiConnect's spectrogram
over the driving portion, after aligning for HaptiConnect's processing lag. Reports per-session level,
band shares, spectral distance and envelope correlation before and after.

--seed N repeats the random draws (gear-shift pitch) exactly, so two profiles compare on identical draws.
Each gain may move at most +-20 dB; a gain that ends on that bound means the recordings do not contain
the effect, so --apply refuses it (pin the effect with --fix, or pass --allow-bound). --apply first copies
the profile to sessions/_backups/ and writes the session list into meta with portable paths.
Renders are cached outside the project (see default_cache_dir; override with $OPENSHAKER_RENDER_CACHE).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config
from .analyze import read_wav
from .compare import envelope, load_frames, render_offline
from .engine import PeakLimiter

NFFT, HOP = 8192, 2400
FMIN, FMAX = 15.0, 150.0
FLOOR_DB = 30.0          # dynamic range below the loudest HaptiConnect cell that counts as audible
LIMITER_KNEE = PeakLimiter.CEILING   # HapticEngine's output limiter leaves a render alone below this (0.985);
                                     # a peak above it ducks the render for up to ~1.2 s, so it is no longer linear
LAG_STEP_S = 0.005       # resolution of HaptiConnect's delay search (Session.set_lag)
BAND_HZ = 10.0           # width of the analysis bands
LEVEL_WEIGHT = 1.0       # weight of the overall level mismatch (dB) added to the spectral distance
BANDS = ((15, 35), (35, 50), (50, 70), (70, 100), (100, 150))
BOUND_DECADES = 1.0      # each gain may move +-1 decade (+-20 dB) from its starting value
PROJECT = Path(__file__).resolve().parent.parent
BACKUPS = PROJECT / "sessions" / "_backups"
CACHE_ENV = "OPENSHAKER_RENDER_CACHE"


def default_cache_dir() -> Path:
    """Where offline renders are cached: $OPENSHAKER_RENDER_CACHE, else ~/.cache/openshaker/renders.
    Outside the project on purpose: the renders are gigabytes of derived data, and a synced folder
    (OneDrive) would upload every one of them."""
    env = os.environ.get(CACHE_ENV, "").strip()
    return Path(env).expanduser() if env else Path.home() / ".cache" / "openshaker" / "renders"


CACHE = default_cache_dir()
LEGACY_ACE_LOG_SCALE = 0.05     # ACE drives logged before the scale went into meta.json used 5 cm

# the code an offline render depends on; a change to any of these must not reuse old renders
RENDER_CODE = ("effects/*.py", "engine.py", "compare.py", "config.py", "telemetry.py")
_code_version: str | None = None


def code_version(pkg: Path | None = None) -> str:
    """Short hash of the rendering code (line endings normalized), part of every render-cache key."""
    global _code_version
    if pkg is None and _code_version is not None:
        return _code_version
    root = Path(__file__).resolve().parent if pkg is None else Path(pkg)
    h = hashlib.md5()
    for pattern in RENDER_CODE:
        for p in sorted(root.glob(pattern)):
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    v = h.hexdigest()[:12]
    if pkg is None:
        _code_version = v
    return v


def cache_key(session: Path, profile: Path, effect: str, susp_scale: float | None, seed: int | None) -> str:
    return hashlib.md5(f"{session.resolve()}|{profile.resolve()}|{profile.stat().st_mtime_ns}|{effect}|"
                       f"{susp_scale}|seed={seed}|code={code_version()}|v6".encode()).hexdigest()


def fine_envelope(x: np.ndarray, sr: int, step: int, win_s: float = 0.05) -> np.ndarray:
    """RMS over win_s taken every `step` samples (the lag search's envelope: smooth, but finely spaced)."""
    n = max(int(win_s * sr), 1)
    c = np.cumsum(np.concatenate([[0.0], np.asarray(x, dtype=np.float64) ** 2]))
    starts = np.arange(0, max(len(x) - n, 0) + 1, step)
    return np.sqrt(np.maximum(c[starts + n] - c[starts], 0.0) / n)


HC_ZERO_RUN = 48         # samples (1 ms at 48 kHz): a run of exact zeros this long means HaptiConnect was silent


def hc_silent_frames(x: np.ndarray, n_frames: int, run: int = HC_ZERO_RUN) -> np.ndarray:
    """STFT frames (NFFT window, HOP step, as stft()) that hold a run of at least `run` exact zeros."""
    z = np.asarray(x) == 0.0
    in_run = np.zeros(len(z), bool)
    if z.any():
        edges = np.flatnonzero(np.diff(np.concatenate([[0], z.astype(np.int8), [0]])))
        for a, b in zip(edges[::2], edges[1::2]):
            if b - a >= run:
                in_run[a:b] = True
    c = np.concatenate([[0], np.cumsum(in_run)])
    starts = np.arange(n_frames) * HOP
    ends = np.minimum(starts + NFFT, len(z))
    starts = np.minimum(starts, len(z))
    return (c[ends] - c[starts]) > 0


def stft(x: np.ndarray, sr: int):
    n = 1 + max(len(x) - NFFT, 0) // HOP
    win = np.hanning(NFFT)
    freqs = np.fft.rfftfreq(NFFT, 1.0 / sr)
    band = (freqs >= FMIN) & (freqs <= FMAX)
    out = np.zeros((n, band.sum()), dtype=np.complex64)
    for i in range(n):
        seg = x[i * HOP:i * HOP + NFFT]
        if len(seg) < NFFT:
            seg = np.pad(seg, (0, NFFT - len(seg)))
        out[i] = np.fft.rfft(seg * win)[band]
    return out, freqs[band]


def cached_render(session: Path, profile: Path, effect: str, sr: int, secs: float, frames, susp_scale: float | None,
                  seed: int | None = None):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{cache_key(session, profile, effect, susp_scale, seed)}.npy"
    if f.exists():
        return np.load(f)
    cfg = config.load(None)
    config.apply_profile(cfg, profile)
    # Render at the profile's own gain and scale back to unit gain. Rendering at gain 1 would push effects whose
    # unit output passes the limiter ceiling (the engine at 0.96 and more, summed voices) into HapticEngine's output
    # limiter, which they never reach live at their real gain; the scaled-back render stays linear in the gain.
    g = float(cfg["effects"][effect].get("gain", 1.0))
    g = g if g > 1e-6 else 1.0
    y = render_offline(frames, secs, cfg, [effect], sr=sr, seed=seed)
    peak = float(np.abs(y).max()) if y.size else 0.0
    # An effect loud enough to reach the limiter alone (one-shots at full scale do) is no longer linear in its gain.
    # Render it below the knee instead and scale that back. The peak of a limited render understates the real one,
    # so this repeats until the render is clean.
    s = 1.0
    for _ in range(6):
        if peak <= LIMITER_KNEE:
            break
        s *= 0.85 * LIMITER_KNEE / peak
        quiet = config.load(None)
        config.apply_profile(quiet, profile)
        quiet["effects"][effect]["gain"] = g * s
        y = render_offline(frames, secs, quiet, [effect], sr=sr, seed=seed)
        peak = float(np.abs(y).max()) if y.size else 0.0
    y = y / (g * s)
    np.save(f, y.astype(np.float32))
    return y


def cached_full_render(session: Path, profile: Path, effects: list[str], sr: int, secs: float, frames,
                       susp_scale: float | None, seed: int | None = None):
    """The whole profile rendered at its own gains through one HapticEngine - the mix the app plays, output
    limiter included - cached like the per-effect renders."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{cache_key(session, profile, 'full:' + ','.join(sorted(effects)), susp_scale, seed)}.npy"
    if f.exists():
        return np.load(f)
    cfg = config.load(None)
    config.apply_profile(cfg, profile)
    y = render_offline(frames, secs, cfg, list(effects), sr=sr, seed=seed)
    np.save(f, y.astype(np.float32))
    return y


def logged_susp_scale(path: Path) -> float | None:
    """The ACE suspension scale (m) a pair's drive was logged with, None for other games.

    Logs since 2026-09-18 say it in the live drive's meta.json (`ace_susp_scale_m`, written for every drive,
    so it only counts when the drive's main source is ACE). Older logs have no source counts; for those a
    folder named "ace" means the 5 cm scale they were logged with."""
    try:
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        src = meta.get("replayed_from")
        drive = (PROJECT / src) if src and not Path(src).is_absolute() else Path(src) if src else path
        dmeta = json.loads((drive / "meta.json").read_text(encoding="utf-8"))
        counts = dmeta.get("frames_by_source") or {}
        if counts:
            if max(counts, key=counts.get) != "ace":
                return None
            if dmeta.get("ace_susp_scale_m"):
                return float(dmeta["ace_susp_scale_m"])
    except (OSError, ValueError, TypeError):
        pass
    return LEGACY_ACE_LOG_SCALE if "ace" in path.name else None


def band_shares(P: np.ndarray, freqs: np.ndarray, mask: np.ndarray):
    tot = P[mask].sum() + 1e-18
    return np.array([P[mask][:, (freqs >= lo) & (freqs < hi)].sum() / tot * 100 for lo, hi in BANDS])


class Session:
    def __init__(self, path: Path, profile: Path, effects: list[str], susp_scale: float | None, active_after_ms: float = 0.0,
                 seed: int | None = None, ref_gain_db: float = 0.0):
        """ref_gain_db scales the HaptiConnect recording before scoring, for references known to be too loud
        (e.g. two HaptiConnect plugins rendering the same drive: about +3 dB on average)."""
        self.path = path
        self.seed = seed
        self.profile, self.effects, self.susp_scale = profile, list(effects), susp_scale
        hc, sr = read_wav(path / "audio.wav")
        if ref_gain_db:
            hc = hc * float(10 ** (ref_gain_db / 20.0))
        frames = load_frames(path / "telemetry.csv")
        if susp_scale:
            logged = logged_susp_scale(path)                  # ACE drives: the scale they were logged with
            if logged:
                for fr in frames:
                    fr.susp_travel = [v * logged / susp_scale for v in fr.susp_travel]
        self.sr, self.secs = sr, len(hc) / sr
        t = np.array([f.t for f in frames])
        act = np.array([(f.active and f.speed > 1.0) for f in frames], float)
        self.S_hc, self.freqs = stft(hc, sr)
        tt = np.arange(self.S_hc.shape[0]) * HOP / sr + NFFT / (2 * sr)
        self.active = np.interp(tt, t, act) > 0.5
        # HaptiConnect's own dropouts: a run of exact zeros is never a quiet effect (a tone crosses zero, it does not
        # sit on it), so frames that contain one are HaptiConnect faults - scoring them against our output counts our
        # sound against its silence (12-24 % of driving frames on several Forza replays; 76 % of beamng_drive_3_hc).
        silent = hc_silent_frames(hc, self.S_hc.shape[0])
        self.hc_silent_share = float(silent[self.active].mean()) if self.active.any() else 0.0
        if (self.active & ~silent).any():                  # a recording silent throughout is left as it is
            self.active &= ~silent
        self.e_hc = envelope(hc, sr, 0.05)
        self.hc = hc
        self.lag, self.lag_samples, self.lag_ms = 0, 0, 0.0
        self.frames = frames
        self.S = {}
        self.y = {}
        for e in effects:
            y = cached_render(path, profile, e, sr, self.secs, frames, susp_scale, seed)[:len(hc)]
            self.y[e] = y
            self.S[e], _ = stft(y, sr)
        self.P_hc = np.abs(self.S_hc) ** 2
        # distance is measured on ~10 Hz bands (robust to exact tone position), 50 ms frames
        edges = np.arange(FMIN, FMAX + 1e-6, BAND_HZ)
        self.bmat = np.stack([((self.freqs >= lo) & (self.freqs < hi)).astype(float) for lo, hi in zip(edges[:-1], edges[1:])], 1)
        self.B_hc = self.P_hc @ self.bmat
        self.floor = self.B_hc[self.active].max() * 10 ** (-FLOOR_DB / 10.0)   # bands below this are "silent"
        self.lag = 0

    def mix_stft(self, gains: dict):
        S = sum(gains[e] * self.S[e] for e in self.S)
        if self.lag:
            S = np.roll(S, self.lag, axis=0)
        return S

    def band_power(self, gains: dict):
        return (np.abs(self.mix_stft(gains)) ** 2) @ self.bmat

    def set_lag(self, gains: dict):
        """HaptiConnect reacts later than we do; find the delay that best aligns the envelopes and shift our renders.

        The search runs on 50 ms RMS envelopes taken every LAG_STEP_S (5 ms) over 0-400 ms, and the winning delay is
        applied to our renders sample by sample, so every STFT frame compares the same moments. Frame-sized steps
        (50 ms) were too coarse: HaptiConnect's ~87 ms fell between 50 and 100, and a profile change could flip the
        choice and move a lap's distance by 0.25 without any change in what it plays. The shift is baked into
        self.y / self.S, so self.lag (a frame roll, kept for callers that apply it) stays 0; self.lag_ms reports it.
        """
        base = getattr(self, "_y_unshifted", None) or dict(self.y)
        self._y_unshifted = base
        y = sum(gains[e] * base[e] for e in base)
        step = max(int(round(LAG_STEP_S * self.sr)), 1)
        e1, e2 = fine_envelope(self.hc, self.sr, step), fine_envelope(y, self.sr, step)
        n = min(len(e1), len(e2))
        a, b = e1[:n] - e1[:n].mean(), e2[:n] - e2[:n].mean()
        best, best_c = 0, -np.inf
        for k in range(0, int(round(0.4 / LAG_STEP_S)) + 1):          # 0..400 ms
            c = float(np.dot(a[k:], b[:n - k]))
            if c > best_c:
                best, best_c = k, c
        shift = best * step
        for e, ye in base.items():
            ys = np.concatenate([np.zeros(shift, dtype=ye.dtype), ye[:len(ye) - shift]]) if shift else ye
            self.y[e] = ys
            self.S[e], _ = stft(ys, self.sr)
        self.lag, self.lag_samples = 0, shift
        self.lag_ms = round(1000.0 * shift / self.sr, 1)

    def distance(self, gains: dict) -> float:
        return self._band_distance(self.band_power(gains))

    def _band_distance(self, B: np.ndarray) -> float:
        L1 = 10 * np.log10(self.B_hc[self.active] + self.floor)
        L2 = 10 * np.log10(B[self.active] + self.floor)
        spectral = float(np.mean(np.abs(L1 - L2)))
        level = 10 * np.log10((B[self.active].sum() + 1e-18) / (self.B_hc[self.active].sum() + 1e-18))
        return spectral + LEVEL_WEIGHT * abs(float(level))

    def report(self, gains: dict) -> dict:
        S = self.mix_stft(gains)
        y = sum(gains[e] * self.y[e] for e in self.y)
        return self._report(S, y)

    def report_full(self) -> dict:
        """report() for the profile rendered as the app plays it: all effects through one HapticEngine, output
        limiter included. The per-effect sum behind report() and the optimizer is exact only while the limiter
        is idle; a profile that reaches it (BeamNG does constantly) must be judged on this. The lag found by
        set_lag is kept, so both reports compare the same moments."""
        y = cached_full_render(self.path, self.profile, self.effects, self.sr, self.secs, self.frames,
                               self.susp_scale, self.seed)[:int(round(self.secs * self.sr))]
        shift = getattr(self, "lag_samples", 0)
        if shift:
            y = np.concatenate([np.zeros(shift, dtype=y.dtype), y[:len(y) - shift]])
        S, _ = stft(y, self.sr)
        if self.lag:
            S = np.roll(S, self.lag, axis=0)
        return self._report(S, y)

    def _report(self, S: np.ndarray, y: np.ndarray) -> dict:
        P = np.abs(S) ** 2
        lvl = 10 * np.log10(P[self.active].sum() / (self.P_hc[self.active].sum() + 1e-18))
        e2 = envelope(y, self.sr, 0.05)
        n = min(len(self.e_hc), len(e2))
        e2 = np.roll(e2[:n], self.lag)
        tt = np.arange(n) * 0.05
        act_e = np.interp(tt, np.arange(len(self.active)) * HOP / self.sr, self.active.astype(float)) > 0.5
        corr = float(np.corrcoef(self.e_hc[:n][act_e], e2[act_e])[0, 1]) if act_e.sum() > 10 else float("nan")
        return {"level_db": round(float(lvl), 1), "dist_db": round(self._band_distance(P @ self.bmat), 2),
                "corr": round(corr, 2),
                "bands_hc": np.round(band_shares(self.P_hc, self.freqs, self.active)).astype(int).tolist(),
                "bands_ours": np.round(band_shares(P, self.freqs, self.active)).astype(int).tolist()}


def optimize(sessions: list[Session], effects: list[str], start: dict, fixed: set) -> dict:
    from scipy.optimize import minimize
    free = [e for e in effects if e not in fixed]
    x0 = np.log10(np.array([max(start[e], 1e-3) for e in free]))

    def gains_of(x):
        g = dict(start)
        for e, v in zip(free, x):
            g[e] = float(10 ** v)
        return g

    def cost(x):
        g = gains_of(x)
        return sum(s.distance(g) * s.active.sum() for s in sessions) / sum(s.active.sum() for s in sessions)

    bounds = [(float(v) - BOUND_DECADES, float(v) + BOUND_DECADES) for v in x0]   # within +-20 dB of the start
    res = minimize(cost, x0, method="Powell", bounds=bounds, options={"xtol": 1e-3, "ftol": 1e-4, "maxiter": 4000})
    return gains_of(res.x), float(res.fun)


def on_bound(start: dict, gains: dict, fixed: set, tol: float = 0.01) -> list[str]:
    """Free effects whose fitted gain ended on the +-20 dB bound: the recordings do not constrain them."""
    out = []
    for e, g in gains.items():
        if e in fixed or g <= 0 or start.get(e, 0) <= 0:
            continue
        if abs(np.log10(g) - np.log10(max(start[e], 1e-3))) >= BOUND_DECADES - tol:
            out.append(e)
    return out


def apply_gains(profile: Path, data: dict, gains: dict, sessions: list[Path], cost: float,
                backups: Path | None = None) -> Path:
    """Write the fitted gains into the profile. A copy of the old file goes to sessions/_backups/ first, and
    the sessions are recorded with portable paths (no drive letter or user name in a shipped profile)."""
    backups = BACKUPS if backups is None else backups
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backups / f"{profile.parent.name}_{profile.stem}_{stamp}.json"
    shutil.copy2(profile, backup)
    for e, g in gains.items():
        data["effects"].setdefault(e, {})["gain"] = round(g, 4)
    data.setdefault("meta", {})["optimized_on"] = [config.portable_path(s) for s in sessions]
    data["meta"]["optimized_cost_db"] = round(cost, 3)
    profile.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return backup


def main(argv=None) -> int:
    global FLOOR_DB
    ap = argparse.ArgumentParser(prog="openshaker.optimize")
    ap.add_argument("sessions", nargs="+", help="HaptiConnect recordings (folders with audio.wav + telemetry.csv)")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--holdout", action="append", default=[], help="session(s) only evaluated, not fitted")
    ap.add_argument("--effects", help="comma list to fit (default: all effects in the profile + road)")
    ap.add_argument("--fix", default="", help="comma list of effects to keep at their current gain")
    ap.add_argument("--susp-scale", type=float, help="ACE suspension scale (m) to assume for ACE sessions")
    ap.add_argument("--apply", action="store_true", help="write the fitted gains into --profile (backup first)")
    ap.add_argument("--allow-bound", action="store_true", help="let --apply write gains that ended on the +-20 dB bound")
    ap.add_argument("--seed", type=int, help="repeatable random draws (gear-shift pitch)")
    ap.add_argument("--floor-db", type=float, default=FLOOR_DB)
    args = ap.parse_args(argv)
    FLOOR_DB = args.floor_db
    profile = Path(args.profile)
    data = json.loads(profile.read_text(encoding="utf-8"))
    effects = args.effects.split(",") if args.effects else sorted(set(list(data["effects"]) + ["road"]))
    start = {e: float(data["effects"].get(e, {}).get("gain", 1.0)) for e in effects}
    fixed = set(x for x in args.fix.split(",") if x)

    print(f"rendering {len(effects)} effects for {len(args.sessions) + len(args.holdout)} sessions (cached after the first run)"
          + (f", seed {args.seed}" if args.seed is not None else "") + " ...")
    train = [Session(Path(s), profile, effects, args.susp_scale, seed=args.seed) for s in args.sessions]
    hold = [Session(Path(s), profile, effects, args.susp_scale, seed=args.seed) for s in args.holdout]
    for s in train + hold:
        s.set_lag(start)
    before = {s.path.name: s.report(start) for s in train + hold}
    gains, cost = optimize(train, effects, start, fixed)
    for s in train + hold:
        s.set_lag(gains)
    after = {s.path.name: s.report(gains) for s in train + hold}

    print(f"\n{'effect':14s} {'before':>8s} {'after':>8s}")
    for e in effects:
        print(f"{e:14s} {start[e]:8.3f} {gains[e]:8.3f}" + ("  (fixed)" if e in fixed else ""))
    print(f"\n{'session':22s} {'lvl dB':>7s} {'dist dB':>8s} {'corr':>5s}   bands 15-35/35-50/50-70/70-100/100-150")
    for name in before:
        b, a = before[name], after[name]
        tag = " (holdout)" if any(s.path.name == name for s in hold) else ""
        print(f"{name:22s} {b['level_db']:+7.1f} {b['dist_db']:8.2f} {b['corr']:5.2f}   HC {b['bands_hc']}  ours {b['bands_ours']}   before{tag}")
        print(f"{'':22s} {a['level_db']:+7.1f} {a['dist_db']:8.2f} {a['corr']:5.2f}   HC {a['bands_hc']}  ours {a['bands_ours']}   after")
    bound = on_bound(start, gains, fixed)
    if bound:
        print(f"\nwarning: {', '.join(bound)} ended on the +-20 dB bound: these recordings do not constrain "
              f"{'it' if len(bound) == 1 else 'them'}. Pin with --fix {','.join(sorted(fixed | set(bound)))}")
    if args.apply:
        if bound and not args.allow_bound:
            print("not applied: a gain is on the bound (see above); refit with --fix, or pass --allow-bound")
            return 1
        backup = apply_gains(profile, data, gains, [s.path for s in train], cost)
        print(f"\napplied to {profile} (previous version: {config.portable_path(backup)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
