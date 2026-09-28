"""Fidelity check: replay a recorded session's telemetry through OUR engine (with a learned profile) and
score the result against HaptiConnect's recorded output.

  python -m openshaker.compare sessions/<session> --profile profiles/beamng/profile.json
Options: --effects engine,gear_shift   (default: the effect the session was recorded for, or all learned)
Writes compare.png + compare.json next to the profile and prints the scores.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

from . import config
from .analyze import read_wav, spectral_frames
from .effects import REGISTRY
from .engine import HapticEngine
from .sources import forza
from .sources.ace import OFF as ACE_OFF
from .sources.base import Source
from .telemetry import Telemetry

ACE_SUSP_OFF = ACE_OFF["suspensionTravel"]      # suspension travel (m) in an ACE physics page, as sources/ace reads it

APP_EFFECT = {"rpm": "engine", "shift": "gear_shift", "accel": "acceleration", "collision": "impact",
              "suspension": "suspension", "lock": "wheel_lock", "slip": "wheel_slip", "rumble": "road",
              "shift_indicator": "shift_indicator"}


class OfflineSource(Source):
    name = "offline"

    def feed(self, tele: Telemetry, seq: int) -> None:
        tele.seq = seq
        tele.source = self.name
        with self._lock:
            self._latest = tele


def load_frames(path: Path) -> list[Telemetry]:
    frames = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = Telemetry(active=r["active"] == "1", engine_running=r["engine_running"] == "1",
                          rpm=float(r["rpm"]), max_rpm=float(r["max_rpm"]), idle_rpm=float(r["idle_rpm"]),
                          gear=int(float(r["gear"])), speed=float(r["speed"]), throttle=float(r["throttle"]),
                          brake=float(r["brake"]), clutch=float(r["clutch"]), handbrake=float(r["handbrake"]),
                          accel_lat=float(r["accel_lat"]), accel_long=float(r["accel_long"]),
                          accel_vert=float(r["accel_vert"]),
                          slip_ratio=[float(r[f"slip_ratio_{i}"]) for i in range(4)],
                          slip_angle=[float(r[f"slip_angle_{i}"]) for i in range(4)],
                          susp_travel=[float(r[f"susp_travel_{i}"]) for i in range(4)],
                          rumble_strip=[r[f"rumble_strip_{i}"] == "1" for i in range(4)],
                          surface_rumble=[float(r[f"surface_rumble_{i}"]) for i in range(4)],
                          abs_active=r["abs_active"] == "1", tc_active=r["tc_active"] == "1")
            t.t = float(r["t"])
            t.source = r.get("source") or ""
            # ACE's vibration hints drive road/slip/abs live (sources/ace.py sets has_vib_hints); keep them offline
            if t.source in VIB_HINT_SOURCES and r.get("kerb_vib") is not None:
                t.has_vib_hints = True
                t.kerb_vib, t.slip_vib = float(r["kerb_vib"]), float(r["slip_vib"])
                t.road_vib, t.abs_vib = float(r["road_vib"]), float(r["abs_vib"])
            if t.gear >= 11:
                t.gear = 0                  # the first Forza logs stored the packet's neutral byte (11) as the gear
            _from_raw(t, r.get("raw_hex") or "")
            frames.append(t)
    return frames


def _from_raw(t: Telemetry, hx: str) -> None:
    """Fields the live sources read from the packet but the CSV has no column for: the suspension travel in
    metres and the game's packet clock. Without them an offline render falls back to normalized travel and
    frame time, so a profile using vel_curve_m, vel_time_source "packet" or the susp_vel_m trigger would
    render differently offline than live (the bed velocity came out 2.65x too high on fm_drive_7_hc)."""
    if not hx:
        return
    n = len(hx) // 2
    try:
        if n in forza.KINDS:
            pkt = forza.parse_packet(bytes.fromhex(hx))
            if pkt is not None:
                t.susp_travel_m = list(pkt.susp_travel_m)
                t.packet_ms = pkt.packet_ms
        elif t.source in VIB_HINT_SOURCES and n >= ACE_SUSP_OFF + 16:
            raw = bytes.fromhex(hx[2 * ACE_SUSP_OFF:2 * (ACE_SUSP_OFF + 16)])
            t.susp_travel_m = [abs(float(x)) if math.isfinite(x) else 0.0 for x in struct.unpack("<4f", raw)]
    except ValueError:              # a damaged hex field keeps the CSV's own values
        pass


# drive-log sources whose rows carry ACE's vibration hints: live ACE logs and replay --plugin ace pairs (parsed
# from the ACE physics page). Column replays of ACE drives ("replay") never carried them.
VIB_HINT_SOURCES = ("ace", "replay_ace")


def render_offline(frames: list[Telemetry], seconds: float, cfg: dict, effects: list[str],
                   sr: int = 48000, block: int = 480, seed: int | None = None) -> np.ndarray:
    """Our output for a logged drive, one 10 ms block at a time like the live app. seed: repeatable random
    draws (gear-shift pitch), so two profiles can be compared on identical draws; None = fresh randomness."""
    for name in REGISTRY:
        cfg["effects"].setdefault(name, {})["enabled"] = name in effects
    src = OfflineSource()
    eng = HapticEngine(cfg, sr, [src], stale_after=float("inf"), seed=seed)
    eng.master = 1.0                                   # compare raw effect output; master is a user setting
    out = np.zeros(int(seconds * sr) + block, dtype=np.float32)
    n_blocks = int(seconds * sr) // block
    fi = 0
    for b in range(n_blocks):
        t_block = b * block / sr
        while fi < len(frames) and frames[fi].t <= t_block:
            src.feed(frames[fi], fi + 1)
            fi += 1
        out[b * block:(b + 1) * block] = eng.render(block)
    return out[: int(seconds * sr)]


def envelope(x: np.ndarray, sr: int, win_s: float = 0.02) -> np.ndarray:
    n = max(int(win_s * sr), 1)
    c = np.cumsum(np.concatenate([[0.0], x.astype(np.float64) ** 2]))
    e = np.sqrt(np.maximum(c[n:] - c[:-n], 0.0) / n)
    return e[::n]                                      # one value per window


def best_lag(e1: np.ndarray, e2: np.ndarray, step_s: float, max_lag_s: float = 0.4) -> int:
    """Lag (in envelope steps) that best aligns ours (e2) to theirs (e1); positive = ours is earlier."""
    m = int(max_lag_s / step_s)
    a = e1 - e1.mean()
    b = e2 - e2.mean()
    best, best_c = 0, -np.inf
    for lag in range(-m, m + 1):
        if lag >= 0:
            c = float(np.dot(a[lag:], b[:len(b) - lag])) if lag < len(a) else -np.inf
        else:
            c = float(np.dot(a[:lag], b[-lag:]))
        if c > best_c:
            best, best_c = lag, c
    return best


def score(theirs: np.ndarray, ours: np.ndarray, sr: int) -> dict:
    n = min(len(theirs), len(ours))
    theirs, ours = theirs[:n], ours[:n]
    step = 0.02
    e1, e2 = envelope(theirs, sr, step), envelope(ours, sr, step)
    m = min(len(e1), len(e2))
    e1, e2 = e1[:m], e2[:m]
    lag = best_lag(e1, e2, step)
    res = {"seconds": round(n / sr, 1), "active_fraction_theirs": round(float((e1 > 0.02).mean()), 3),
           "active_fraction_ours": round(float((e2 > 0.02).mean()), 3),
           "latency_ours_vs_theirs_ms": round(-lag * step * 1000.0)}
    if lag > 0:                      # ours leads: delay ours
        e2 = np.concatenate([np.zeros(lag), e2[:m - lag]])
        ours = np.concatenate([np.zeros(int(lag * step * sr), dtype=ours.dtype), ours])[:n]
    elif lag < 0:
        e2 = np.concatenate([e2[-lag:], np.zeros(-lag)])
        ours = np.concatenate([ours[int(-lag * step * sr):], np.zeros(int(-lag * step * sr), dtype=ours.dtype)])[:n]
    active = (e1 > 0.02) | (e2 > 0.02)
    if active.sum() > 10:
        res["envelope_correlation"] = round(float(np.corrcoef(e1[active], e2[active])[0, 1]), 3)
        res["level_ratio_db"] = round(20 * math.log10((e2[active].mean() + 1e-9) / (e1[active].mean() + 1e-9)), 1)
        both = (e1 > 0.02) & (e2 > 0.02)
        res["overlap_fraction"] = round(float(both.sum() / max(active.sum(), 1)), 3)
        # pitch agreement where both are active
        s1, s2 = spectral_frames(theirs, sr), spectral_frames(ours, sr)
        m = min(len(s1["freq"]), len(s2["freq"]))
        act = (s1["rms"][:m] > 0.02) & (s2["rms"][:m] > 0.02)
        if act.sum() > 5:
            d = np.abs(s1["freq"][:m][act] - s2["freq"][:m][act])
            res["pitch_median_abs_diff_hz"] = round(float(np.median(d)), 1)
            res["pitch_within_3hz"] = round(float((d < 3.0).mean()), 3)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.compare", description="Score our model against a HaptiConnect recording.")
    ap.add_argument("session")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--effects", help="comma-separated effect names to enable in our engine")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args(argv)
    session = Path(args.session)
    meta = json.loads((session / "meta.json").read_text(encoding="utf-8")) if (session / "meta.json").exists() else {}
    theirs, sr = read_wav(session / "audio.wav")
    frames = load_frames(session / "telemetry.csv")
    cfg = config.load(None)
    config.apply_profile(cfg, args.profile)
    learned = list(cfg.get("_profile_effects", {}))
    if args.effects:
        effects = args.effects.split(",")
    elif meta.get("effect") in APP_EFFECT:
        effects = [APP_EFFECT[meta["effect"]]]
    else:
        effects = learned
    seconds = len(theirs) / sr
    ours = render_offline(frames, seconds, cfg, effects, sr=sr)
    res = score(theirs, ours, sr)
    res["effects"] = effects
    res["session"] = config.portable_path(session)
    res["profile"] = config.portable_path(args.profile) if args.profile else None
    print(json.dumps(res, indent=2))
    out_dir = Path(args.profile).parent
    (out_dir / f"compare_{session.name}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    if not args.no_plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            e1, e2 = envelope(theirs, sr), envelope(ours, sr)
            tt = np.arange(len(e1)) * 0.02
            fig, axes = plt.subplots(3, 1, figsize=(11, 8), constrained_layout=True)
            axes[0].plot(tt, e1[:len(tt)], lw=0.8, label="HaptiConnect")
            axes[0].plot(tt[:len(e2)], e2[:len(tt)], lw=0.8, alpha=0.8, label="ours")
            axes[0].set_title(f"Envelope: {', '.join(effects)}   corr={res.get('envelope_correlation')}  "
                              f"level={res.get('level_ratio_db')} dB  pitch|d|={res.get('pitch_median_abs_diff_hz')} Hz")
            axes[0].legend()
            with np.errstate(divide="ignore"):
                axes[1].specgram(theirs + 1e-7 * np.random.default_rng(0).standard_normal(len(theirs)), NFFT=4096,
                                 Fs=sr, noverlap=3584, cmap="magma", vmin=-110)
                axes[2].specgram(ours + 1e-7 * np.random.default_rng(1).standard_normal(len(ours)), NFFT=4096,
                                 Fs=sr, noverlap=3584, cmap="magma", vmin=-110)
            for ax, name in ((axes[1], "HaptiConnect"), (axes[2], "ours")):
                ax.set_ylim(0, 160)
                ax.set_ylabel(f"{name} Hz")
            png = out_dir / f"compare_{session.name}.png"
            fig.savefig(png, dpi=110)
            plt.close(fig)
            print("plot:", png)
        except Exception as exc:
            print(f"(plot skipped: {type(exc).__name__}: {exc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
