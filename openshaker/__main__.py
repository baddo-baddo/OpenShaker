"""Command line entry point: python -m openshaker [options]   (python -m openshaker --gui for the window)"""
from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from pathlib import Path

import numpy as np

from . import APP_NAME, __version__, config, paths, single_instance
from .audio import AudioOutput, DeviceNotFound
from .runtime import Runtime, dbfs

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_FILES = ("telemetry.csv", "ours.wav", "meta.json")
ALREADY_RUNNING = (f"error: {APP_NAME} is already running (the tray app, or another console run) and owns the "
                   f"game ports, so this run would record nothing. Quit it from the tray, or run "
                   f"'python -m openshaker.gui --quit', then try again.")


def log_dir_problem(path: Path, overwrite: bool) -> str | None:
    """Why --log DIR must not be used, or None."""
    if path.exists() and not path.is_dir():
        return f"--log {path} is a file, not a folder"
    taken = [name for name in LOG_FILES if (path / name).exists()]
    if taken and not overwrite:
        return (f"{path} already holds a logged drive ({', '.join(taken)}). "
                f"Pick a new folder, or add --overwrite to replace it.")
    return None


def replay_hint(meta: dict | None, log_dir: str) -> str:
    """The closing line of a --log run: which HaptiConnect plugin the drive replays into."""
    counts = (meta or {}).get("frames_by_source") or {}
    source = max(counts, key=counts.get) if counts else None
    head = f"logged drive to {log_dir}"
    if source is None:
        return f"{head}  (no telemetry arrived - check the game's telemetry setting)"
    if source == "trackmania":
        return f"{head}  (Trackmania has no HaptiConnect plugin; tune from it: python -m openshaker.tm_tune {log_dir})"
    if source == "demo":
        return f"{head}  (Demo drive)"
    if source == "forza":
        plugin = "fh5" if meta.get("forza_kind") == "horizon" else "fm"
    else:
        plugin = {"beamng": "beamng", "ace": "ace"}.get(source, "fm")
    # profiles/ace is matched to HaptiConnect's own ACE plugin, fed through shared memory: the game at its menu
    note = " with Assetto Corsa EVO at its menu" if plugin == "ace" else ""
    return f"{head}  (replay into HaptiConnect: python -m openshaker.replay {log_dir} --plugin {plugin}{note})"


def run_test_tone(audio: AudioOutput, seconds: float, freq: float, gain: float) -> None:
    sr = audio.resolve()
    phase = [0.0]

    def render(n: int) -> np.ndarray:
        ph = phase[0] + 2.0 * math.pi * freq * np.arange(1, n + 1) / sr
        phase[0] = float(ph[-1] % (2.0 * math.pi))
        return (gain * np.sin(ph)).astype(np.float32)

    audio.render = render
    audio.start()
    print(f"test tone {freq:.0f} Hz at gain {gain:.2f} -> [{audio.device_index}] {audio.device_name} "
          f"({audio.api}, {sr} Hz, {audio.nch} ch, ~{audio.latency_ms:.0f} ms)")
    try:
        time.sleep(seconds)
    finally:
        audio.stop()
    print(f"done, {audio.callbacks} callbacks, {audio.xruns} xruns")


def effect_gain_note(name: str, params: dict) -> str:
    """e.g. engine=0.18, or engine=0.09@50% when the user trimmed it below the calibrated level."""
    trim = float(params.get("trim", 1.0))
    note = f"{name}={float(params.get('gain', 1.0)):.2f}"
    if abs(trim - 1.0) > 1e-6:
        note += f"@{trim * 100:.0f}%"
    return note if params.get("enabled", True) else note + "(off)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker",
                                 description="Drive a ButtKicker or other bass shaker from game telemetry.")
    ap.add_argument("--gui", action="store_true", help="open the control panel window")
    ap.add_argument("--config", help="JSON config (default: config.json in %%APPDATA%%\\OpenShaker, created if missing)")
    ap.add_argument("--profile", help="profile.json learned by openshaker.analyze (overrides config's profile)")
    ap.add_argument("--list-devices", action="store_true", help="list audio output devices and exit")
    ap.add_argument("--device", help='output device name or part of it ("" = Windows default; see --list-devices)')
    ap.add_argument("--test-tone", type=float, metavar="SECONDS", help="play a sine to the device and exit")
    ap.add_argument("--tone-freq", type=float, default=40.0, help="test tone frequency (Hz)")
    ap.add_argument("--demo", action="store_true", help="use scripted telemetry instead of a game")
    ap.add_argument("--duration", type=float, help="stop after this many seconds")
    ap.add_argument("--wav", metavar="PATH", help="also write the rendered output to a WAV file")
    ap.add_argument("--log", metavar="DIR", help="log the drive: telemetry.csv + ours.wav into DIR (for openshaker.replay)")
    ap.add_argument("--overwrite", action="store_true", help="let --log replace a drive already logged in DIR")
    ap.add_argument("--stop-file", metavar="PATH",
                    help="stop cleanly as soon as this file exists (an old one is removed at start, and it is removed at the end)")
    ap.add_argument("--no-audio", action="store_true", help="render without opening an audio device")
    ap.add_argument("--source", choices=["auto", "forza", "ace", "beamng", "trackmania"], default="auto")
    ap.add_argument("--forza-port", type=int)
    ap.add_argument("--beamng-port", type=int)
    ap.add_argument("--gain", type=float, help="master gain override (0..1)")
    ap.add_argument("-v", "--verbose", action="store_true", help="show per-effect levels")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    if not args.config:
        paths.migrate_config()
        args.config = str(paths.config_path())
    cfg = config.load(args.config, profile=args.profile)
    if cfg.get("_profile_missing"):
        print(f"warning: profile not found: {cfg['_profile_missing']}")
    if args.device:
        cfg["audio"]["device"] = args.device
    if args.forza_port:
        cfg["sources"]["forza"]["port"] = args.forza_port
    if args.beamng_port:
        cfg["sources"]["beamng"]["port"] = args.beamng_port
    if args.gain is not None:
        cfg["audio"]["master_gain"] = args.gain

    if args.gui:
        from .gui import run_gui
        listener = single_instance.acquire()
        if listener is None:
            if single_instance.signal_existing():
                print(f"{APP_NAME} is already running; its window was brought to the front.")
                return 0
            print(ALREADY_RUNNING)
            return 1
        single_instance.hold_app_mutex()
        return run_gui(cfg, args.config, listener=listener)

    if args.list_devices:
        for d in AudioOutput.output_devices():
            print(f"[{d['index']:2d}] {d['name']}  ({d['api']}, {d['channels']} ch, {d['samplerate']:.0f} Hz)")
        return 0

    a = cfg["audio"]
    if args.test_tone:
        audio = AudioOutput(device_substr=a["device"], api_pref=a["api"], samplerate=a["samplerate"],
                            blocksize=a["blocksize"], channels=a["channels"])
        try:
            run_test_tone(audio, args.test_tone, args.tone_freq, float(a["master_gain"]))
        except DeviceNotFound as exc:
            print(f"error: {exc}. Pick one with --device (see --list-devices).")
            return 1
        return 0

    if args.log:
        problem = log_dir_problem(Path(args.log), args.overwrite)
        if problem:
            print(f"error: {problem}")
            return 1
    listener = single_instance.acquire()     # the tray app and a console run never share the game ports
    if listener is None:
        print(ALREADY_RUNNING)
        return 1
    try:
        return _run(args, cfg, listener)
    finally:
        listener.close()


def _run(args, cfg: dict, listener) -> int:
    quit_asked = threading.Event()
    listener.on_quit = quit_asked.set         # --quit (and the installer) stop a console run cleanly too
    stop_file = Path(args.stop_file) if args.stop_file else None
    if stop_file is not None and stop_file.exists():
        try:
            stop_file.unlink()                # left over from an earlier run: it would stop this one at once
            print(f"removed an old stop file: {stop_file}")
        except OSError as exc:
            print(f"error: cannot remove the old stop file {stop_file}: {exc}")
            return 1
    a = cfg["audio"]
    rt = Runtime(cfg, demo=args.demo, source=args.source, no_audio=args.no_audio, wav=args.wav, log_dir=args.log)
    try:
        rt.start()
    except DeviceNotFound as exc:
        print(f"error: {exc}. Pick one with --device (see --list-devices) or in the window.")
        return 1
    if args.no_audio:
        print(f"rendering in software at {rt.sr} Hz (no audio device)")
    else:
        print(f"output -> [{rt.audio.device_index}] {rt.audio.device_name} ({rt.audio.api}, {rt.sr} Hz, "
              f"{rt.audio.nch} ch, block {a['blocksize']}, ~{rt.audio.latency_ms:.0f} ms)")
    print(f"config: {args.config}")
    if cfg.get("profile"):
        print(f"profile: {cfg['profile']} (learned: {', '.join(cfg.get('_profile_effects', {})) or 'nothing'})")
    print("effect gains: " + "  ".join(effect_gain_note(n, p) for n, p in cfg["effects"].items())
          + f"  | master={cfg['audio']['master_gain']:.2f}")
    time.sleep(0.3)
    for s in rt.sources:
        print(f"source {s.name}: {s.error or s.status}")
    print("Ctrl+C to stop")

    t_start = time.perf_counter()
    last_status = {s.name: (s.error or s.status) for s in rt.sources}
    try:
        while True:
            time.sleep(0.5)
            st = rt.status()
            for s in st["sources"]:
                if s["status"] != last_status.get(s["name"]):
                    print(f"\nsource {s['name']}: {s['status']}")
                    last_status[s["name"]] = s["status"]
            if st.get("profile") != last_status.get("_profile"):
                last_status["_profile"] = st.get("profile")
                print(f"\ngame: {st.get('game') or '-'} | profile: {st.get('profile') or 'defaults'}")
            tele = st["tele"]
            if tele is None:
                line = "waiting for telemetry"
            else:
                src = next((s for s in st["sources"] if s["name"] == tele.source), None)
                fps = src["fps"] if src else 0.0
                extra = f" [{src['phase']}]" if src and src["phase"] else ""
                line = f"[{tele.source} {fps:4.0f} fps]{extra} {tele.summary()}"
                if not tele.active:
                    line += " (paused)"
            line += f" | out {st['peak_db']:6.1f} dBFS"
            if not args.no_audio:
                line += f" xruns {st['xruns']}"
            if args.verbose:
                line += " | " + " ".join(f"{k}:{v:.2f}" for k, v in st["levels"].items() if v > 0.01)
            if st["audio_error"]:
                line += f" | ERROR {st['audio_error']}"
            sys.stdout.write("\r" + line[:200].ljust(200))
            sys.stdout.flush()
            if args.duration and time.perf_counter() - t_start >= args.duration:
                break
            if stop_file is not None and stop_file.exists():
                break
            if quit_asked.is_set():
                break
    except KeyboardInterrupt:
        pass
    finally:
        print()
        secs = rt.stop()
        if secs is not None:
            print(f"wrote {rt.wav} ({secs:.1f} s)")
        if stop_file is not None and stop_file.exists():
            try:
                stop_file.unlink()            # so the next run does not stop at once
            except OSError:
                pass
        if args.log:
            print(replay_hint(rt.log_meta, args.log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
