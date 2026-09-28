"""Shared runtime used by both the command line and the GUI: sources + engine + audio."""
from __future__ import annotations

import collections
import math
import os
import threading
import time
import wave
from datetime import datetime
from typing import Optional

import numpy as np

from .audio import AudioOutput
from .engine import HapticEngine, PeakLimiter


# Demo packs a gear change, the shift light, a kerb and a crash into seconds, so its peaks stack up;
# it plays 8 dB below a game so a first try never jolts anyone. A profile whose game plays loud
# (BeamNG, at HaptiConnect's BeamNG level) is scaled down further, so the Demo stays a safe preview
# whatever preset is active: aimed at DEMO_TARGET_DBFS, and never above DEMO_MAX_DBFS - the Demo's
# own limiter sits there, so a strength or Master raised during the Demo cannot push it past. It caps
# the Demo's mix only: the test tone joins after it and plays as strong as in a game.
DEMO_OUTPUT_SCALE = 0.4
DEMO_TARGET_DBFS = -7.0
DEMO_MAX_DBFS = -6.1
FORZA_PACKET_BYTES = {"sled": 232, "horizon": 324, "motorsport": 331}


class _ScriptFeed:
    """A stand-in source for measuring the Demo offline: whatever frame was set last."""

    name = "demo"

    def __init__(self) -> None:
        self.frame = None

    def latest(self):
        return self.frame


def demo_output_scale(cfg: dict, sr: int = 48000, seed: int = 0) -> float:
    """The Demo's output scale for this cfg (profile, strengths, Master): DEMO_OUTPUT_SCALE, or lower
    when the whole Demo script would peak above DEMO_TARGET_DBFS at it. Renders the script once
    offline (a quarter of a second or so)."""
    from .demo import LOOP_S, DemoSource
    demo, feed = DemoSource(), _ScriptFeed()
    engine = HapticEngine(cfg, sr, [feed], stale_after=math.inf, output_scale=1.0, seed=seed)
    engine.limiter.ceiling = math.inf                    # the peak before any limiting
    block, peak, seq = int(sr // 100), 0.0, 0
    for b in range(int(LOOP_S * 100)):
        t = b / 100.0
        if int(t * 60) != int((t - 0.01) * 60) or b == 0:  # the live Demo's 60 frames a second
            frame = demo.frame(t)
            frame.t, frame.seq, frame.source = t, seq, "demo"
            seq += 1
            feed.frame = frame
        peak = max(peak, float(np.max(np.abs(engine.render(block)))))
    if peak <= 0.0:
        return DEMO_OUTPUT_SCALE
    return min(DEMO_OUTPUT_SCALE, 10.0 ** (DEMO_TARGET_DBFS / 20.0) / peak)


def demo_engine(cfg: dict, sr: int, sources: list, **kw) -> HapticEngine:
    """The engine Demo mode plays through: scaled for this profile, capped at DEMO_MAX_DBFS."""
    engine = HapticEngine(cfg, sr, sources, output_scale=demo_output_scale(cfg, sr), **kw)
    engine.mix_limiter = PeakLimiter(sr, block=engine.limiter.block, ceiling=10.0 ** (DEMO_MAX_DBFS / 20.0))
    return engine


def build_sources(cfg: dict, which: str = "auto") -> list:
    from .sources.ace import ACESource
    from .sources.beamng import BeamNGSource
    from .sources.forza import ForzaSource
    from .sources.trackmania import TrackmaniaSource
    s = cfg["sources"]
    out = []
    if which in ("auto", "forza") and (which == "forza" or s["forza"]["enabled"]):
        out.append(ForzaSource(port=int(s["forza"]["port"]), host=str(s["forza"].get("host") or "127.0.0.1")))
    if which in ("auto", "beamng") and (which == "beamng" or s["beamng"]["enabled"]):
        out.append(BeamNGSource(port=int(s["beamng"]["port"]), accel_scale=float(s["beamng"]["accel_scale"]),
                                motion_port=int(s["beamng"].get("motion_port") or 0),
                                host=str(s["beamng"].get("host") or "127.0.0.1")))
    if which in ("auto", "ace") and (which == "ace" or s["ace"]["enabled"]):
        out.append(ACESource(poll_hz=float(s["ace"]["poll_hz"]), susp_scale_m=float(s["ace"]["susp_scale_m"])))
    tm = s.get("trackmania") or {}
    if which in ("auto", "trackmania") and (which == "trackmania" or tm.get("enabled", True)):
        out.append(TrackmaniaSource(host=str(tm.get("host", "127.0.0.1")), port=int(tm.get("port", 28765)),
                                    max_rate=int(tm.get("max_rate", 200)),
                                    damper_range_m=float(tm.get("damper_range_m", 0.2)),
                                    accel_window_ms=float(tm.get("accel_window_ms", 20.0)),
                                    slip_ratio_full=float(tm.get("slip_ratio_full", 0.15)),
                                    max_rpm=float(tm.get("max_rpm", 11000.0)),
                                    idle_rpm=float(tm.get("idle_rpm", 1000.0))))
    return out


def dbfs(x: float) -> float:
    return -120.0 if x <= 1e-6 else 20.0 * math.log10(x)


class WavCapture:
    """Writes the rendered output to a WAV while it plays, so a killed run keeps what it had.

    The audio callback only queues each block; a writer thread appends them to the file twice a
    second, and `wave` rewrites the header's length on every write, so the file is valid throughout.
    """

    def __init__(self, path: str, samplerate: int) -> None:
        self.path = path
        self.samplerate = samplerate
        self.frames = 0
        self._q: collections.deque = collections.deque()
        self._file = open(path, "wb")              # ours, so each write can be flushed to disk
        self._w = wave.open(self._file, "wb")
        self._w.setnchannels(1)
        self._w.setsampwidth(2)
        self._w.setframerate(samplerate)
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, name="wav-capture", daemon=True)
        self._thread.start()

    def __call__(self, mono: np.ndarray) -> None:
        self._q.append(mono.copy())               # the audio thread never touches the disk

    def _run(self) -> None:
        while not self._done.wait(0.5):
            self._drain()

    def _drain(self) -> None:
        blocks = []
        while True:
            try:
                blocks.append(self._q.popleft())
            except IndexError:
                break
        if blocks:
            data = np.concatenate(blocks)
            self._w.writeframes((np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())
            self._file.flush()
            self.frames += len(data)

    def close(self) -> float:
        self._done.set()
        self._thread.join(timeout=2.0)
        self._drain()
        self._w.close()                            # patches the header; a file object passed in stays open
        self._file.close()
        return self.frames / float(self.samplerate)


class Runtime:
    """Owns everything that runs while haptics are active. start()/stop() are idempotent."""

    def __init__(self, cfg: dict, demo: bool = False, source: str = "auto",
                 no_audio: bool = False, wav: Optional[str] = None, log_dir: Optional[str] = None,
                 outputs=()) -> None:
        self.cfg = cfg
        self.outputs = tuple(outputs)          # extra outputs (openshaker.outputs); only the window passes any
        self.output_errors: dict = {}
        self.demo = demo
        self.source = source
        self.no_audio = no_audio
        self.wav = wav
        self.log_dir = log_dir
        self._log = None
        self._log_created = ""
        self.log_meta: Optional[dict] = None     # what the drive's meta.json says (--log)
        self.audio: Optional[AudioOutput] = None
        self.engine: Optional[HapticEngine] = None
        self.sources: list = []
        self.capture: Optional[WavCapture] = None
        self.sr = int(cfg["audio"]["samplerate"])
        self.running = False
        self._stop = threading.Event()
        self._clock: Optional[threading.Thread] = None
        self.started_at = 0.0
        # per-game profile switching
        self.profiles = dict(cfg.get("profiles") or {})
        self.active_profile: Optional[str] = cfg.get("profile")
        self.manual_profile = False           # set when the user loads a profile by hand (disables auto-switch)
        self.profile_changed = False          # flag for UIs to refresh their sliders
        self.game_label = ""

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        cfg = self.cfg
        a = cfg["audio"]
        if not self.no_audio:
            from .audio import refresh_devices
            refresh_devices()          # a boot-time device list can predate the ButtKicker
        self.audio = AudioOutput(device_substr=a["device"], api_pref=a["api"], samplerate=a["samplerate"],
                                 blocksize=a["blocksize"], channels=a["channels"])
        self.sr = int(a["samplerate"]) if self.no_audio else self.audio.resolve()

        if self.demo:
            from .demo import DemoSource
            self.sources = [DemoSource()]
        else:
            self.sources = build_sources(cfg, self.source)
        if self.log_dir:
            from .drivelog import DriveLogWriter
            os.makedirs(self.log_dir, exist_ok=True)
            self._log = DriveLogWriter(os.path.join(self.log_dir, "telemetry.csv"))
            self._log_created = datetime.now().isoformat(timespec="seconds")
            for s in self.sources:
                s.listeners.append(self._log)
            if not self.wav:
                self.wav = os.path.join(self.log_dir, "ours.wav")
        try:
            # the engine renders silence until a source publishes, so the output opens first: it is what
            # fails when another program holds the shaker exclusively, and failing before any source is up
            # leaves nothing to stop (stopping a source waits out its socket timeout, up to a second)
            if self.demo:
                self.engine = demo_engine(cfg, self.sr, self.sources)
            else:
                self.engine = HapticEngine(cfg, self.sr, self.sources)

            self.capture = WavCapture(self.wav, self.sr) if self.wav else None
            self._stop.clear()
            if self.no_audio:
                self._clock = threading.Thread(target=self._software_clock, args=(int(a["blocksize"]),),
                                               daemon=True)
                self._clock.start()
            else:
                self.audio.render = self.engine.render
                self.audio.on_block = self.capture
                self.audio.start()
            self.started_at = time.perf_counter()
            for s in self.sources:
                s.start()
            self.running = True
            if self._log is not None:
                self._log.begin(self.started_at)       # telemetry.csv times count from ours.wav's first sample
                self._write_log_meta(self.sources, complete=False)   # a killed run still says what it was
        except BaseException:
            self._abort_start()
            raise
        if self.outputs:                           # last: only a runtime that is fully up starts them
            from .outputs import OutputContext
            ctx = OutputContext(sources=list(self.sources), cfg=self.cfg, demo=self.demo, log_dir=self.log_dir,
                                preset=lambda: self.cfg.get("_preset"))
            for out in self.outputs:
                self._output_call(out, "start", ctx)

    def _abort_start(self) -> None:
        """Undo a start that failed part-way. The sources it started hold the game ports, and nothing else
        would ever stop them: the caller drops this runtime, and stop() only stops a running one."""
        self.running = False
        self._stop.set()
        steps = [s.stop for s in self.sources]
        if self.audio is not None and not self.no_audio:
            steps.insert(0, self.audio.stop)
        if self._clock is not None:
            steps.insert(0, lambda: self._clock.join(timeout=1.0))   # raises if it never got to start
        if self.capture is not None:
            steps.append(self.capture.close)
        if self._log is not None:
            steps.append(self._log.close)
        for step in steps:
            try:
                step()
            except Exception:
                pass                               # the error that failed the start is the one to report
        self._clock = None
        self.sources = []
        self.capture = None

    def stop(self) -> Optional[float]:
        if not self.running:
            return None
        self.running = False
        self._stop.set()
        if self._clock is not None:
            self._clock.join(timeout=1.0)
            self._clock = None
        if self.audio is not None and not self.no_audio:
            self.audio.stop()
        for out in self.outputs:                   # before the sources they read from stop
            self._output_call(out, "stop")
        stopped = list(self.sources)              # meta.json below still needs their names
        for s in self.sources:
            s.stop()
        self.sources = []
        secs = None
        if self.capture is not None:
            secs = self.capture.close()
            self.capture = None
        if self._log is not None and self.log_dir:
            self._log.close()
            self._write_log_meta(stopped, complete=True, seconds=secs)
        return secs

    def _write_log_meta(self, sources: list, complete: bool, seconds: Optional[float] = None) -> None:
        """meta.json of a --log drive: what was running and how it was set up, for the tools that read it."""
        import json
        from . import __version__
        from .config import portable_path
        cfg = self.cfg
        forza = next((s for s in sources if s.name == "forza"), None)
        kind = getattr(forza, "kind", None)
        kind = kind if kind in FORZA_PACKET_BYTES else None
        meta = {"note": "live drive logged by openshaker (ours.wav = this app's output)",
                "version": __version__, "created": self._log_created, "complete": complete,
                "samplerate": self.sr, "frames": len(self._log),
                "duration_s": None if seconds is None else round(seconds, 2),
                "sources": [s.name for s in sources], "frames_by_source": self._log.counts(),
                "forza_kind": kind, "forza_packet_bytes": FORZA_PACKET_BYTES.get(kind),
                "game": cfg.get("_preset"), "game_label": self.game_label, "demo": self.demo,
                "profile": portable_path(cfg["profile"]) if cfg.get("profile") else None,
                "master_gain": float(cfg["audio"]["master_gain"]),
                "effects": {name: {"enabled": bool(e.get("enabled", True)), "trim": float(e.get("trim", 1.0))}
                            for name, e in sorted((cfg.get("effects") or {}).items()) if isinstance(e, dict)},
                "ace_susp_scale_m": float(cfg["sources"]["ace"]["susp_scale_m"])}
        self.log_meta = meta
        tmp = os.path.join(self.log_dir, "meta.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, os.path.join(self.log_dir, "meta.json"))

    def _software_clock(self, blocksize: int) -> None:
        period = blocksize / self.sr
        nxt = time.perf_counter()
        while not self._stop.is_set():
            mono = self.engine.render(blocksize)
            if self.capture is not None:
                self.capture(mono)
            nxt += period
            delay = nxt - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

    # -- per-game profiles ------------------------------------------------------
    @staticmethod
    def _label(tele, sources) -> str:
        if tele is None:
            return ""
        if tele.source == "forza":
            src = next((s for s in sources if s.name == "forza"), None)
            kind = getattr(src, "kind", "?")
            return {"horizon": "Forza Horizon", "motorsport": "Forza Motorsport", "sled": "Forza (Sled)"}.get(kind, "Forza")
        return {"ace": "Assetto Corsa EVO", "beamng": "BeamNG.drive", "trackmania": "Trackmania",
                "demo": "Demo"}.get(tele.source, tele.source)

    def switch_profile(self, path: Optional[str], manual: bool = False,
                       preset: Optional[str] = None) -> None:
        """Rebuild the effects from the base config plus `path` (None = base config only).

        `preset` is the detected game; it decides whose saved strengths come along, which matters
        when two games share a profile (Forza Motorsport and ACE).
        """
        import copy
        from . import config as _config
        from .effects import build_effects
        base = _config.load(None) if "_user" not in self.cfg else None
        new_cfg = copy.deepcopy({k: v for k, v in self.cfg.items() if not k.startswith("_") or k == "_user"})
        new_cfg["effects"] = copy.deepcopy(_config.base_effects(self.cfg.get("_user", {}))) \
            if base is None else copy.deepcopy(base["effects"])
        if path:
            _config.apply_profile(new_cfg, path, preset=preset)   # that game's own saved strengths
        else:
            _config.apply_trims(new_cfg, _config.preset_settings(new_cfg, "default"))
        effects = build_effects(new_cfg["effects"], self.sr)
        if self.engine is not None:
            self.engine.effects = effects            # atomic swap between audio blocks
        self.cfg["effects"] = new_cfg["effects"]
        self.cfg["_base_gains"] = new_cfg.get("_base_gains", {})
        self.cfg["_base_enabled"] = new_cfg.get("_base_enabled", {})
        self.cfg["_profile_effects"] = new_cfg.get("_profile_effects", {})
        self.cfg["_preset"] = new_cfg.get("_preset", preset)
        self.cfg["profile"] = path
        self.active_profile = path
        self.manual_profile = manual
        self.profile_changed = True
        for out in self.outputs:
            self._output_call(out, "on_preset", self.cfg.get("_preset"), path)

    def _output_call(self, out, method: str, *args) -> None:
        """An output's trouble is its own: note it for status(), never let it stop the haptics."""
        try:
            getattr(out, method)(*args)
        except Exception as exc:
            self.output_errors[getattr(out, "name", "output")] = f"{method}: {type(exc).__name__}: {exc}"

    def _output_status(self, out) -> dict:
        name = getattr(out, "name", "output")
        try:
            st = dict(out.status())
        except Exception as exc:
            st = {"state": "error", "summary": "", "problem": f"status: {type(exc).__name__}: {exc}"}
        if self.output_errors.get(name) and not st.get("problem"):
            st["problem"] = self.output_errors[name]
        st["name"] = name
        return st

    def resume_auto(self) -> None:
        """Re-enable per-game profile switching after a profile was loaded by hand."""
        self.manual_profile = False
        self._auto_profile()

    def _horizon_key(self) -> str:
        """Which Horizon is running. Their telemetry is identical, so go by the executable."""
        from . import config as _config
        from .procs import is_running
        names = self.cfg.get("game_processes") or {}
        for key in _config.HORIZON_KEYS:
            if key in self.profiles and is_running(names.get(key)):
                return key
        current = self.cfg.get("_preset")
        if current in _config.HORIZON_KEYS:
            return current                      # neither exe seen; do not flap away from the active one
        return next((k for k in _config.HORIZON_KEYS if k in self.profiles), "forza_horizon")

    def _auto_profile(self) -> None:
        if self.manual_profile or self.engine is None or not self.profiles:
            return
        tele = self.engine.current
        self.game_label = self._label(tele, self.sources)
        if tele is None:
            return
        key = tele.source
        if key == "forza":
            src = next((s for s in self.sources if s.name == "forza"), None)
            if src is not None and getattr(src, "kind", "") == "horizon":
                key = self._horizon_key()       # FH5 and FH6 share a layout, not a preset
        if key not in self.profiles:
            return
        from . import config as _config
        self.game_label = _config.GAME_LABELS.get(key, self.game_label)
        want = str(_config.resolve_profile(self.cfg, self.profiles[key]))
        if (want != self.active_profile or key != self.cfg.get("_preset")) and os.path.exists(want):
            self.switch_profile(want, preset=key)

    # -- live tuning ------------------------------------------------------------
    def set_master(self, gain: float) -> None:
        self.cfg["audio"]["master_gain"] = float(gain)
        if self.engine is not None:
            self.engine.master = float(gain)

    def set_effect(self, name: str, enabled: Optional[bool] = None, gain: Optional[float] = None) -> None:
        e_cfg = self.cfg["effects"].setdefault(name, {})
        if enabled is not None:
            e_cfg["enabled"] = bool(enabled)
        if gain is not None:
            e_cfg["gain"] = float(gain)
        if self.engine is not None:
            for e in self.engine.effects:
                if e.name == name:
                    if enabled is not None:
                        e.enabled = bool(enabled)
                    if gain is not None:
                        e.gain = float(gain)

    def set_trim(self, name: str, trim: float) -> float:
        """Set an effect's strength as a fraction of its calibrated gain (1.0 = exactly as measured)."""
        e_cfg = self.cfg["effects"].setdefault(name, {})
        base = float(self.cfg.get("_base_gains", {}).get(name, e_cfg.get("gain", 1.0)))
        e_cfg["trim"] = float(trim)
        gain = base * float(trim)
        self.set_effect(name, gain=gain)
        return gain

    def play_test_tone(self, seconds: float, low: float, high: float, amp: float) -> bool:
        """Mix a sweep into the output that is already running. False when nothing is running."""
        if self.engine is None or not self.running:
            return False
        from .engine import TestTone
        self.engine.tone = TestTone(self.sr, seconds, low, high, amp)
        return True

    def audio_lost(self) -> bool:
        """True while running with an output that stopped playing (unplugged, switched off)."""
        return bool(self.running and not self.no_audio and self.audio is not None and not self.audio.alive)

    # -- status -----------------------------------------------------------------
    def status(self) -> dict:
        if self.running:
            self._auto_profile()
        st = {"running": self.running, "device": "", "sr": self.sr, "latency_ms": 0.0, "xruns": 0,
              "sources": [], "tele": None, "peak_db": -120.0,
              "levels": {}, "audio_error": None, "game": self.game_label, "profile": self.active_profile,
              "manual_profile": self.manual_profile, "preset": self.cfg.get("_preset"),
              "audio_lost": self.audio_lost()}
        if self.audio is not None:
            st["device"] = f"{self.audio.device_name} [{self.audio.api}]"
            st["latency_ms"] = self.audio.latency_ms
            st["xruns"] = self.audio.xruns
            st["audio_error"] = self.audio.last_error
        for s in self.sources:
            st["sources"].append({"name": s.name, "status": s.error or s.status, "fps": s.fps,
                                  "error": bool(s.error), "phase": getattr(s, "phase_name", "")})
        st["outputs"] = [self._output_status(out) for out in self.outputs]
        if self.engine is not None:
            st["tele"] = self.engine.current
            st["peak_db"] = dbfs(self.engine.peak)
            st["levels"] = {e.name: e.level for e in self.engine.effects}
        return st
