"""Learn a HaptiConnect-like effect profile from a recorded session (audio.wav + telemetry.csv).

  python -m openshaker.analyze sessions/NAME [--out profiles/NAME] [--channel 0]

Produces profile.json (effect parameters), one WAV template per transient effect, report.txt and,
when matplotlib is available, PNG plots. Load the result with  python -m openshaker --profile <profile.json>
or the GUI's "Load profile" button. Cleanest results come from sessions where only ONE HaptiConnect
effect was enabled.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from .config import portable_path

BAND = (15.0, 150.0)
SQRT2 = math.sqrt(2.0)


# ---------------------------------------------------------------- loading
def read_wav(path: Path, channel: int = 0):
    with wave.open(str(path), "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {sw}")
    x = x.reshape(-1, ch)
    return np.ascontiguousarray(x[:, min(channel, ch - 1)]), sr


def read_telemetry(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("telemetry.csv is empty")

    def col(name):
        return np.array([float(r[name]) for r in rows], dtype=np.float64)

    tel = {k: col(k) for k in ("t", "active", "engine_running", "rpm", "max_rpm", "gear", "speed", "throttle",
                               "brake", "handbrake", "accel_lat", "accel_long", "accel_vert", "abs_active", "tc_active")}
    for base in ("slip_ratio", "slip_angle", "susp_travel"):
        tel[base] = np.stack([col(f"{base}_{i}") for i in range(4)], axis=1)
    return tel


# ---------------------------------------------------------------- spectral analysis
def spectral_frames(x: np.ndarray, sr: int, win: int = 4096, hop: int = 480, chunk: int = 400) -> dict:
    n = len(x)
    if n < win:
        raise ValueError("recording too short")
    nfr = 1 + (n - win) // hop
    hann = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    df = freqs[1] - freqs[0]
    band = (freqs >= BAND[0]) & (freqs <= BAND[1])
    bfreqs = freqs[band]
    band_start = int(np.argmax(band))          # index of the first in-band bin (>= 1)
    out = {k: np.zeros(nfr) for k in ("freq", "mag", "rms", "harm", "centroid")}
    for start in range(0, nfr, chunk):
        idx = np.arange(win)[None, :] + hop * np.arange(start, min(start + chunk, nfr))[:, None]
        frames = x[idx]
        out["rms"][start:start + len(idx)] = np.sqrt(np.mean(frames ** 2, axis=1))
        mag = np.abs(np.fft.rfft(frames * hann, axis=1)) * (2.0 / hann.sum())   # sine of amp A -> peak ~A
        bmag = mag[:, band]
        # fundamental = the LOWEST local maximum that is at least 40% of the strongest in-band peak
        # (harmonic-rich tones would otherwise flip the pick between fundamental and 2nd harmonic)
        gmax = bmag.max(axis=1, keepdims=True)
        local = np.zeros_like(bmag, dtype=bool)
        local[:, 1:-1] = (bmag[:, 1:-1] >= bmag[:, :-2]) & (bmag[:, 1:-1] >= bmag[:, 2:]) & (bmag[:, 1:-1] >= 0.4 * gmax)
        has_local = local.any(axis=1)
        k = np.where(has_local, np.argmax(local, axis=1), np.argmax(bmag, axis=1))
        rows = np.arange(len(idx))
        # parabolic peak interpolation using neighbours from the FULL spectrum (no band-edge bias)
        kf = k + band_start
        a, b, c = mag[rows, kf - 1], mag[rows, kf], mag[rows, np.minimum(kf + 1, len(freqs) - 1)]
        denom = a - 2 * b + c
        delta = np.where(np.abs(denom) > 1e-12, 0.5 * (a - c) / np.where(denom == 0, 1, denom), 0.0)
        delta = np.clip(delta, -0.5, 0.5)
        pf = freqs[kf] + delta * df
        out["freq"][start:start + len(idx)] = pf
        # interpolated peak height removes the window's scalloping loss (tone between bins reads low)
        out["mag"][start:start + len(idx)] = b - 0.25 * (a - c) * delta
        k2 = np.clip(np.round(2.0 * pf / df).astype(int), 0, len(freqs) - 1)
        out["harm"][start:start + len(idx)] = mag[rows, k2] / np.maximum(b, 1e-9)
        out["centroid"][start:start + len(idx)] = (bmag * bfreqs).sum(axis=1) / np.maximum(bmag.sum(axis=1), 1e-12)
    out["t"] = (hop * np.arange(nfr) + win / 2.0) / sr
    return out


def telemetry_at(tel: dict, times: np.ndarray) -> dict:
    idx = np.searchsorted(tel["t"], times, side="right") - 1
    valid = idx >= 0
    idx = np.clip(idx, 0, len(tel["t"]) - 1)
    valid &= (times - tel["t"][idx]) < 0.5
    at = {"valid": valid}
    for k, v in tel.items():
        at[k] = v[idx]
    return at


# ---------------------------------------------------------------- events
def detect_events(tel: dict, impact_thr: float = 25.0, bump_thr: float = 1.0) -> dict:
    t = tel["t"]
    active = tel["active"] > 0.5
    dt = np.diff(t)
    ok = (dt > 0) & (dt < 0.5) & active[1:] & active[:-1]

    def with_cooldown(times, cd):
        keep, last = [], -1e9
        for tt in times:
            if tt - last >= cd:
                keep.append(float(tt))
                last = tt
        return keep

    shifts = with_cooldown(t[1:][ok & (np.diff(tel["gear"]) != 0)], 0.15)
    da = np.sqrt(np.diff(tel["accel_lat"]) ** 2 + np.diff(tel["accel_long"]) ** 2 + np.diff(tel["accel_vert"]) ** 2)
    dv = np.abs(np.diff(tel["speed"]))                    # a sudden speed loss is also an impact
    impacts = with_cooldown(t[1:][ok & ((da > impact_thr) | (dv > 3.0))], 0.3)
    if np.any(tel["susp_travel"] != 0):
        dv = np.abs(np.diff(tel["susp_travel"], axis=0)) / np.maximum(dt, 1e-3)[:, None]
        bumps = with_cooldown(t[1:][ok & (dv.max(axis=1) > bump_thr)], 0.15)
    else:
        # no suspension data (BeamNG packets): use vertical acceleration jumps instead
        dvert = np.abs(np.diff(tel["accel_vert"]))
        bumps = with_cooldown(t[1:][ok & (dvert > 6.0)], 0.15)

    slip = tel["slip_ratio"]
    lock = active & ((tel["brake"] > 0.05) | (tel["handbrake"] > 0.05)) & (tel["speed"] > 2.0) & (slip.min(axis=1) < -1.0)
    spin = active & (tel["throttle"] > 0.05) & (slip.max(axis=1) > 1.0)
    absm = active & (tel["abs_active"] > 0.5)
    accel = active & (np.abs(tel["accel_long"]) > 2.0) & ~lock & ~spin
    return {"shift": shifts, "impact": impacts, "bump": bumps,
            "lock": lock, "spin": spin, "abs": absm, "accel": accel,
            "lock_amount": np.clip((-slip.min(axis=1) - 1.0) / 2.0, 0, 1),
            "spin_amount": np.clip((slip.max(axis=1) - 1.0) / 1.5, 0, 1)}


def exclusion(times: np.ndarray, events: dict, before: float = 0.15, after: float = 0.7) -> np.ndarray:
    mask = np.zeros(len(times), dtype=bool)
    for key in ("shift", "impact", "bump"):
        for te in events[key]:
            mask |= (times >= te - before) & (times <= te + after)
    return mask


# ---------------------------------------------------------------- learners
def learn_engine(spec: dict, at: dict, clean: np.ndarray) -> dict | None:
    sel = clean & at["valid"] & (at["active"] > 0.5) & (at["engine_running"] > 0.5) & (at["rpm"] > 50) \
        & (spec["mag"] > 0.003)
    if sel.sum() < 30:
        return None
    rpm, f, amp, thr, harm = at["rpm"][sel], spec["freq"][sel], spec["mag"][sel], at["throttle"][sel], spec["harm"][sel]
    max_rpm = float(np.median(at["max_rpm"][sel]))
    bw = max(50.0, max_rpm / 50.0)
    table = []
    for lo in np.arange(0.0, max_rpm + bw, bw):
        m = (rpm >= lo) & (rpm < lo + bw)
        if m.sum() >= 5:
            table.append([round(lo + bw / 2, 1), round(float(np.median(f[m])), 2), float(np.median(amp[m])),
                          float(np.mean(thr[m])), int(m.sum())])
    if len(table) < 3:
        return None
    tbl = np.array(table)
    base = np.interp(rpm, tbl[:, 0], tbl[:, 2])
    resid = amp - base
    b = 0.0
    if np.std(thr) > 0.1:
        b = float(np.polyfit(thr - thr.mean(), resid, 1)[0])
        b = max(b, 0.0)
    curve = [[row[0], row[1], round(max(row[2] - b * row[3], 0.0), 4)] for row in table]
    return {"curve": curve, "amp_throttle": round(b, 4), "harmonic": round(float(np.median(harm)), 3),
            "frames": int(sel.sum()), "freq_range": [round(float(np.min(f)), 1), round(float(np.max(f)), 1)],
            "table": table}


def moving_rms(x: np.ndarray, n: int) -> np.ndarray:
    c = np.cumsum(np.concatenate([[0.0], x.astype(np.float64) ** 2]))
    out = np.sqrt(np.maximum(c[n:] - c[:-n], 0.0) / n)
    return np.concatenate([np.full(n - 1, out[0] if len(out) else 0.0), out])


def learn_template(x: np.ndarray, sr: int, events: list, length: float = 0.5, pre: float = 0.01,
                   search: float = 0.35) -> dict | None:
    if len(events) < 2:
        return None
    env = moving_rms(x, int(0.005 * sr))
    L = int(length * sr)
    segs, peaks, durs = [], [], []
    for te in events:
        i0, i1 = int((te - 0.05) * sr), int((te + search) * sr)
        b0, b1 = int((te - 0.40) * sr), int((te - 0.06) * sr)
        if b0 < 0 or i1 + L >= len(x):
            continue
        base = float(np.median(env[b0:b1]))
        local_peak = float(np.max(env[i0:i1]))
        if local_peak < base + 0.01:          # nothing happened above the background
            continue
        # onset = envelope has risen 40% of the way from the background to its local peak
        thr = base + max(0.01, 0.4 * (local_peak - base))
        above = np.nonzero(env[i0:i1] > thr)[0]
        if len(above) == 0:
            continue
        on = max(i0 + int(above[0]) - int(pre * sr), 0)
        seg = x[on:on + L].astype(np.float64)
        pk = float(np.max(np.abs(seg)))
        if pk < 0.01:
            continue
        e = env[on:on + L]
        k_peak = int(np.argmax(e))
        # transient is over once the envelope is back within 5% of the way to the background level
        settle = base + 0.05 * (float(e[k_peak]) - base)
        below = np.nonzero(e[k_peak:] < settle)[0]
        durs.append(float(k_peak + below[0]) / sr if len(below) else length)
        segs.append(seg / pk)
        peaks.append(pk)
    if len(segs) < 2:
        return None
    dur = float(np.median(durs))
    cut = min(L, int((dur + 0.02) * sr))     # keep the transient plus a 20 ms fade, drop background tail
    ref = segs[0]
    n_corr = min(len(ref), int(0.1 * sr))
    aligned = [ref]
    maxlag = int(0.006 * sr)
    for s in segs[1:]:
        c = np.correlate(s[:n_corr + maxlag], ref[:n_corr], mode="valid")     # lags 0..maxlag
        lag = int(np.argmax(c))
        aligned.append(np.concatenate([s[lag:], np.zeros(lag)]))
    avg = np.mean(aligned, axis=0)[:cut]
    # averaging smears square-ish bursts (lower RMS); use the single most typical burst instead
    scores = [float(np.dot(s[:cut], avg)) / (np.linalg.norm(s[:cut]) * np.linalg.norm(avg) + 1e-12) for s in aligned]
    tpl = np.array(aligned[int(np.argmax(scores))][:cut], dtype=np.float64)
    tpl /= max(float(np.max(np.abs(tpl))), 1e-9)
    fade = min(int(0.02 * sr), len(tpl))
    tpl[-fade:] *= np.linspace(1.0, 0.0, fade)
    return {"sample": tpl.astype(np.float32), "peak": float(np.median(peaks)), "peak_max": float(np.max(peaks)),
            "duration": dur, "count": len(segs), "template_similarity": round(float(np.max(scores)), 3)}


def learn_segment(spec: dict, at: dict, rows_mask: np.ndarray, clean: np.ndarray, amount: np.ndarray | None,
                  min_frames: int = 30) -> dict | None:
    sel = clean & at["valid"] & rows_mask
    if sel.sum() < min_frames:
        return None
    amp = spec["rms"][sel] * SQRT2
    res = {"freq": round(float(np.median(spec["freq"][sel])), 1),
           "centroid": round(float(np.median(spec["centroid"][sel])), 1),
           "amp": round(float(np.median(amp)), 4), "amp_p90": round(float(np.percentile(amp, 90)), 4),
           "frames": int(sel.sum())}
    if amount is not None:
        a = amount[sel]
        if np.std(a) > 0.05:
            k = float(np.polyfit(a, amp, 1)[0])
            res["amp_per_unit"] = round(max(k, 0.0), 4)
    return res


def write_wav_mono(path: Path, y: np.ndarray, sr: int) -> None:
    pcm = (np.clip(y, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- main
def analyze(session: Path, out: Path, channel: int = 0, plots: bool = True) -> dict:
    x, sr = read_wav(session / "audio.wav", channel)
    tel = read_telemetry(session / "telemetry.csv")
    meta = json.loads((session / "meta.json").read_text(encoding="utf-8")) if (session / "meta.json").exists() else {}
    out.mkdir(parents=True, exist_ok=True)

    spec = spectral_frames(x, sr)
    at = telemetry_at(tel, spec["t"])
    ev = detect_events(tel)
    excl = exclusion(spec["t"], ev)
    busy = (at["lock"] if "lock" in at else np.zeros(len(spec["t"]), bool))
    # per-frame masks from telemetry rows
    rows = np.clip(np.searchsorted(tel["t"], spec["t"], side="right") - 1, 0, len(tel["t"]) - 1)
    lock_f, spin_f, abs_f, accel_f = ev["lock"][rows], ev["spin"][rows], ev["abs"][rows], ev["accel"][rows]
    clean = ~excl & ~lock_f & ~spin_f & ~abs_f

    report = [f"session: {portable_path(session)}", f"note: {meta.get('note', '')}", f"audio: {len(x) / sr:.1f} s @ {sr} Hz, "
              f"peak {20 * math.log10(max(float(np.max(np.abs(x))), 1e-9)):.1f} dBFS",
              f"telemetry rows: {len(tel['t'])}, gear changes: {len(ev['shift'])}, impacts: {len(ev['impact'])}, "
              f"bumps: {len(ev['bump'])}, lock frames: {int(lock_f.sum())}, spin frames: {int(spin_f.sum())}, "
              f"abs frames: {int(abs_f.sum())}", ""]
    effects: dict = {}
    analysis: dict = {}

    eng = learn_engine(spec, at, clean)
    if eng:
        effects["engine"] = {"curve": eng["curve"], "amp_throttle": eng["amp_throttle"], "harmonic": eng["harmonic"]}
        analysis["engine"] = {k: v for k, v in eng.items() if k != "curve"}
        report.append(f"engine: {eng['frames']} clean frames, tone {eng['freq_range'][0]}-{eng['freq_range'][1]} Hz, "
                      f"throttle adds {eng['amp_throttle']:.3f}, 2nd harmonic {eng['harmonic']:.2f}")
        report.append("  rpm     freq    amp    frames")
        for row in eng["table"]:
            report.append(f"  {row[0]:6.0f}  {row[1]:6.1f}  {row[2]:.3f}  {row[4]}")
    else:
        report.append("engine: not enough steady engine-tone frames (record revving/driving with RPM effect on)")

    for key, name, synth_amp, ev_list in (("shift", "gear_shift", 0.9, ev["shift"]),
                                          ("impact", "impact", 0.75, ev["impact"]),
                                          ("bump", "suspension", 0.5, ev["bump"])):
        tpl = learn_template(x, sr, ev_list)
        if tpl:
            fn = f"{name}.wav"
            write_wav_mono(out / fn, tpl["sample"], sr)
            effects[name] = {"sample": fn, "gain": round(tpl["peak"] / synth_amp, 3)}
            analysis[name] = {k: v for k, v in tpl.items() if k != "sample"}
            report.append(f"{name}: template from {tpl['count']} events, peak {tpl['peak']:.3f}, "
                          f"~{tpl['duration'] * 1000:.0f} ms -> {fn}")
        else:
            report.append(f"{name}: no usable transients ({len(ev_list)} events detected)")

    seg = learn_segment(spec, at, lock_f & ~excl, np.ones(len(spec["t"]), bool), ev["lock_amount"][rows])
    if seg:
        analysis["wheel_lock"] = seg
        amp_full = seg.get("amp_per_unit", seg["amp_p90"])
        effects["wheel_lock"] = {"freq": seg["freq"], "noise_cutoff": round(max(seg["centroid"] * 1.4, 30.0), 1),
                                 "gain": round(amp_full / 0.9, 3)}
        report.append(f"wheel_lock: {seg['frames']} frames, {seg['freq']} Hz (centroid {seg['centroid']} Hz), amp {seg['amp']:.3f}")
    seg = learn_segment(spec, at, spin_f & ~excl, np.ones(len(spec["t"]), bool), ev["spin_amount"][rows])
    if seg:
        analysis["wheel_slip"] = seg
        effects["wheel_slip"] = {"freq": seg["freq"], "gain": round(seg.get("amp_per_unit", seg["amp_p90"]), 3)}
        report.append(f"wheel_slip: {seg['frames']} frames, {seg['freq']} Hz, amp {seg['amp']:.3f}")
    seg = learn_segment(spec, at, abs_f & ~excl, np.ones(len(spec["t"]), bool), None)
    if seg:
        analysis["abs"] = seg
        effects["abs"] = {"freq": seg["freq"], "gain": round(seg["amp_p90"], 3)}
        report.append(f"abs: {seg['frames']} frames, {seg['freq']} Hz, amp {seg['amp']:.3f}")
    seg = learn_segment(spec, at, accel_f & ~excl & ~lock_f & ~spin_f, np.ones(len(spec["t"]), bool),
                        np.abs(tel["accel_long"])[rows])
    if seg and "amp_per_unit" in seg and seg["amp_per_unit"] > 0:
        analysis["acceleration"] = seg
        effects["acceleration"] = {"freq": seg["freq"], "gain": round(seg["amp_per_unit"] / 0.075, 3)}
        report.append(f"acceleration: {seg['frames']} frames, {seg['freq']} Hz, {seg['amp_per_unit']:.4f} per m/s^2")

    profile = {"meta": {"session": portable_path(session), "note": meta.get("note", ""), "created":
                        datetime.now().isoformat(timespec="seconds"), "samplerate": sr, "channel": channel},
               "effects": effects, "analysis": analysis}
    (out / "profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    report.append("")
    report.append(f"learned effects: {', '.join(effects) or 'none'}")
    report.append(f"profile: {portable_path(out / 'profile.json')}")
    (out / "report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))

    if plots:
        try:
            make_plots(out, x, sr, spec, at, eng, effects, clean)
        except Exception as exc:  # plotting is optional
            print(f"(plots skipped: {type(exc).__name__}: {exc})")
    return profile


def make_plots(out: Path, x, sr, spec, at, eng, effects, clean) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), constrained_layout=True)
    ax = axes[0]
    with np.errstate(divide="ignore"):
        ax.specgram(x + 1e-7 * np.random.default_rng(0).standard_normal(len(x)), NFFT=4096, Fs=sr,
                    noverlap=3584, cmap="magma", vmin=-110)
    ax.set_ylim(0, 160)
    ax.set_ylabel("Hz")
    ax.set_title("HaptiConnect output (spectrogram) with RPM overlay")
    ax2 = ax.twinx()
    ax2.plot(spec["t"], at["rpm"], color="cyan", lw=0.7, alpha=0.8)
    ax2.set_ylabel("rpm", color="cyan")
    ax = axes[1]
    if eng:
        tbl = np.array(eng["table"])
        ax.plot(tbl[:, 0], tbl[:, 1], "o-", label="learned tone Hz")
        ax.set_xlabel("rpm")
        ax.set_ylabel("Hz")
        ax.legend(loc="upper left")
        ax3 = ax.twinx()
        ax3.plot(tbl[:, 0], tbl[:, 2], "s--", color="orange", label="amplitude")
        ax3.set_ylabel("amp", color="orange")
    ax.set_title("Engine effect: frequency and amplitude vs rpm")
    ax = axes[2]
    plotted = 0
    for name in ("gear_shift", "impact", "suspension"):
        p = out / f"{name}.wav"
        if p.exists():
            y, s2 = read_wav(p)
            ax.plot(np.arange(len(y)) / s2 * 1000, y, lw=0.8, label=name)
            plotted += 1
    ax.set_xlabel("ms")
    ax.set_title("Transient templates" if plotted else "Transient templates (none learned in this session)")
    if plotted:
        ax.legend()
    fig.savefig(out / "analysis.png", dpi=110)
    plt.close(fig)
    print(f"plots: {out / 'analysis.png'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.analyze", description="Learn an effect profile from a session.")
    ap.add_argument("session", help="session folder written by openshaker.record")
    ap.add_argument("--out", help="profile folder (default profiles/<session name>)")
    ap.add_argument("--channel", type=int, default=0, help="audio channel to analyze (0 = left)")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args(argv)
    session = Path(args.session)
    for required in ("audio.wav", "telemetry.csv"):
        if not (session / required).exists():
            print(f"error: {session / required} not found. Record a session first (python -m openshaker.record).")
            return 1
    out = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / "profiles" / session.name
    analyze(session, out, args.channel, plots=not args.no_plots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
