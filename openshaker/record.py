"""Record a calibration session: HaptiConnect's audio to the ButtKicker (WASAPI loopback) plus the
telemetry packets it was reacting to, time-aligned, into a session folder.

Typical use (BeamNG + HaptiConnect):
  1. In HaptiConnect, BeamNG.drive page > Telemetry forwarding: add localhost, port 4446.
  2. Set all BeamNG effect strengths to 0 except the ONE you want to capture.
  3. python -m openshaker.record --note "rpm only"     (then drive; Enter or Ctrl+C stops)
  4. python -m openshaker.analyze sessions\\<folder>     -> profiles\\<folder>\\profile.json

  python -m openshaker.record --out sessions/NAME --source beamng --port 4446 --device ButtKicker
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from . import __version__, config, paths
from .drivelog import CSV_FIELDS, TelemetryLog, tele_row  # noqa: F401 - the drive-log format, shared
from .runtime import dbfs

try:
    import soundcard as sc
except Exception:  # pragma: no cover - optional dependency
    sc = None

PROJECT_DIR = Path(__file__).resolve().parent.parent


def find_loopback(device_substr: str):
    if sc is None:
        raise RuntimeError("the 'soundcard' package is missing: pip install soundcard")
    mics = [m for m in sc.all_microphones(include_loopback=True) if getattr(m, "isloopback", False)]
    cands = [m for m in mics if device_substr.lower() in m.name.lower()]
    if not cands:
        names = ", ".join(m.name for m in mics) or "none"
        raise RuntimeError(f"no loopback endpoint matching '{device_substr}'. Available: {names}")
    return cands[0]


class LoopbackRecorder(threading.Thread):
    """Captures what Windows is sending to an output device (what HaptiConnect plays)."""

    def __init__(self, device_substr: str, samplerate: int = 48000, channels: int = 2, block: int = 4800) -> None:
        super().__init__(name="loopback", daemon=True)
        self.mic = find_loopback(device_substr)
        self.sr = samplerate
        self.channels = channels
        self.block = block
        self.chunks: list[np.ndarray] = []
        self.frames = 0
        self.t0: float | None = None       # perf_counter time of sample 0
        self.peak = 0.0
        self.error: str | None = None
        self._stop = threading.Event()

    def run(self) -> None:
        import ctypes
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0)          # COM must be initialized on this thread (0 = multithreaded)
        try:
            with self.mic.recorder(samplerate=self.sr, channels=self.channels, blocksize=self.block) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=self.block)
                    now = time.perf_counter()
                    if data is None or len(data) == 0:
                        continue
                    if self.t0 is None:
                        self.t0 = now - len(data) / self.sr
                    data = np.asarray(data, dtype=np.float32)
                    self.chunks.append(data)
                    self.frames += len(data)
                    self.peak = max(self.peak * 0.7, float(np.max(np.abs(data))))
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            ole32.CoUninitialize()

    def stop(self) -> None:
        self._stop.set()
        self.join(timeout=3.0)

    def audio(self) -> np.ndarray:
        if not self.chunks:
            return np.zeros((0, self.channels), dtype=np.float32)
        return np.concatenate(self.chunks, axis=0)


def write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(audio.shape[1] if audio.ndim == 2 else 1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.record", description="Record HaptiConnect output + telemetry.")
    ap.add_argument("--out", help="session folder (default sessions/<timestamp>)")
    ap.add_argument("--device", default=None, help="output device to tap (default from config, 'ButtKicker')")
    ap.add_argument("--source", choices=["beamng", "forza", "ace"], default="beamng")
    ap.add_argument("--port", type=int, default=4446, help="UDP port to listen on (HaptiConnect forwarding target)")
    ap.add_argument("--duration", type=float, help="stop automatically after this many seconds")
    ap.add_argument("--note", default="", help="what was enabled in HaptiConnect, e.g. 'rpm only'")
    ap.add_argument("--config", help="default: the app's config.json in its settings folder")
    args = ap.parse_args(argv)

    cfg = config.load(args.config or str(paths.config_path()))
    device = args.device or cfg["audio"]["device"]
    out = Path(args.out) if args.out else PROJECT_DIR / "sessions" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out.mkdir(parents=True, exist_ok=True)

    # telemetry source
    if args.source == "beamng":
        from .sources.beamng import BeamNGSource
        src = BeamNGSource(port=args.port)
    elif args.source == "forza":
        from .sources.forza import ForzaSource
        src = ForzaSource(port=args.port)
    else:
        from .sources.ace import ACESource
        src = ACESource()
    log = TelemetryLog()
    src.listeners.append(log)

    try:
        rec = LoopbackRecorder(device)
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    print(f"tapping audio of: {rec.mic.name}")
    rec.start()
    src.start()
    time.sleep(0.3)
    print(f"telemetry: {src.name} - {src.error or src.status}")
    if src.error:
        rec.stop()
        return 1
    print(f"session: {out}")
    print("Recording. Drive now. Press Enter or Ctrl+C to stop.")

    stop = threading.Event()

    def wait_enter() -> None:
        try:
            line = sys.stdin.readline()
        except Exception:
            return
        if line == "":          # EOF (no console attached): keep recording until --duration / Ctrl+C
            return
        stop.set()

    threading.Thread(target=wait_enter, daemon=True).start()
    t_start = time.perf_counter()
    try:
        while not stop.is_set():
            time.sleep(0.5)
            if rec.error:
                print(f"\naudio capture error: {rec.error}")
                break
            tele = src.latest()
            elapsed = time.perf_counter() - t_start
            info = tele.summary() if tele else "no telemetry yet"
            line = (f"{elapsed:6.1f}s  audio {dbfs(rec.peak):6.1f} dBFS  packets {len(log):6d} "
                    f"({src.fps:3.0f}/s)  {info}")
            sys.stdout.write("\r" + line[:180].ljust(180))
            sys.stdout.flush()
            if args.duration and elapsed >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    print()
    rec.stop()
    src.stop()

    audio = rec.audio()
    if rec.t0 is None or len(audio) == 0:
        print("no audio captured (is the ButtKicker the device HaptiConnect plays to?)")
        return 1
    write_wav(out / "audio.wav", audio, rec.sr)
    with (out / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        with log.lock:
            for t in log.rows:
                w.writerow(tele_row(t, rec.t0))
    meta = {"version": __version__, "created": datetime.now().isoformat(timespec="seconds"), "note": args.note,
            "device": rec.mic.name, "samplerate": rec.sr, "channels": rec.channels,
            "duration_s": round(len(audio) / rec.sr, 2), "source": src.name, "port": args.port,
            "packets": len(log), "peak_dbfs": round(dbfs(float(np.max(np.abs(audio)))), 1)}
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"saved {meta['duration_s']} s of audio (peak {meta['peak_dbfs']} dBFS) and {meta['packets']} packets to {out}")
    if meta["peak_dbfs"] < -60:
        print("warning: the audio is essentially silent. Was HaptiConnect running with an effect enabled?")
    if meta["packets"] == 0:
        print("warning: no telemetry received. Check HaptiConnect's forwarding target (localhost:%d)." % args.port)
    print(f"next: python -m openshaker.analyze \"{out}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
