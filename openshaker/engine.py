"""Mixes all effects into one mono stream, driven by whichever source is currently live."""
from __future__ import annotations

import math
import time
import zlib
from typing import Optional

import numpy as np

from .effects import build_effects
from .telemetry import Telemetry


def seed_effects(effects: list, seed: int) -> None:
    """Make the effects' random draws (gear-shift pitch jitter) repeat exactly for the same seed.

    Each effect gets its own stream derived from the seed and its name, so adding or reordering
    effects does not change another effect's draws.
    """
    for e in effects:
        if hasattr(e, "rng"):
            e.rng = np.random.default_rng([int(seed), zlib.crc32(e.name.encode("utf-8"))])


class TestTone:
    """A one-shot sweep mixed straight into the live output.

    Opening a second stream for the test tone cannot work when the device is held exclusively
    (WDM-KS, or WASAPI exclusive), which is exactly when someone reaches for the test tone.
    """

    def __init__(self, sr: int, seconds: float, low: float, high: float, amp: float) -> None:
        self.sr = sr
        self.total = max(1, int(seconds * sr))
        self.low, self.high, self.amp = float(low), float(high), float(amp)
        self.ramp = max(1, int(0.05 * sr))
        self.i = 0
        self.phase = 0.0

    @property
    def done(self) -> bool:
        return self.i >= self.total

    def block(self, n: int) -> np.ndarray:
        idx = np.arange(self.i, self.i + n)
        self.i += n
        k = np.clip(idx / self.total, 0.0, 1.0)
        freq = self.low + (self.high - self.low) * k
        ph = self.phase + np.cumsum(2.0 * math.pi * freq / self.sr)
        self.phase = float(ph[-1] % (2.0 * math.pi))
        env = np.clip(np.minimum(idx, self.total - idx) / self.ramp, 0.0, 1.0)
        return (self.amp * env * np.sin(ph)).astype(np.float32)


class PeakLimiter:
    """HaptiConnect's output stage, measured from its own recordings: a peak limiter that never waveshapes.

    Each block's gain target is ceiling / the block's peak, known when the block starts; the audio runs
    `delay` samples behind the gain, so the gain is already falling ~1.3 ms before a burst. The fall is a
    linear ramp over `attack` samples, clamped per sample so nothing passes the ceiling; the rise is a
    linear-gain ramp of `release` gain units per second, never above what the rest of the block allows.
    So a loud burst ducks everything else in the mix by the same factor and it comes back over ~0.5 s -
    the soft clipper used before bent every sample above 0.9 and never ducked. Below the ceiling the
    output is the input, `delay` samples late. It lives in this module because the calibration tools'
    render cache hashes engine.py (optimize.RENDER_CODE).
    """

    CEILING = 0.985              # -0.13 dBFS: the highest sample in every clean HaptiConnect recording
    DELAY = 64                   # samples of lookahead (1.3 ms at 48 kHz)
    ATTACK = 128                 # samples of linear ramp down (2.7 ms)
    RELEASE = 0.853              # linear gain per second back up (0 -> 1 in 1.17 s; median of 6 recoveries)

    def __init__(self, sr: int, block: int = 480, ceiling: float = CEILING, delay: int = DELAY,
                 attack: int = ATTACK, release: float = RELEASE) -> None:
        self.ceiling = float(ceiling)
        self.block = max(1, int(block))
        self.attack = max(1, int(attack))
        self.step = float(release) / float(sr)               # gain per sample
        self.gain = 1.0                                       # carried across blocks and calls
        self.line = np.zeros(max(0, int(delay)), dtype=np.float64)   # the delayed samples still owed
        self._i = np.arange(1, self.block + 1, dtype=np.float64)
        self._ramp = np.arange(1, self.attack + 1, dtype=np.float64) / self.attack

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        if n == 0:
            return np.asarray(x, dtype=np.float32)
        d = np.concatenate((self.line, np.asarray(x, dtype=np.float64)))
        if len(self.line):
            self.line = d[n:].copy()
        d = d[:n]
        y = np.empty(n, dtype=np.float32)
        c = self.ceiling
        for s in range(0, n, self.block):
            seg = d[s:s + self.block]
            m = len(seg)
            mag = np.abs(seg)
            req = np.minimum(c / np.maximum(mag, 1e-12), 1.0)        # the gain that keeps each sample in
            cap = np.minimum.accumulate(req[::-1])[::-1]              # what the rest of the block allows
            g = np.empty(m)
            g0, k = self.gain, 0
            target = float(cap[0])                                    # ceiling / the block's peak
            if target < g0 - 1e-12:                                   # attack: straight down to the target
                k = min(self.attack, m)
                ramp = g0 - (g0 - target) * self._ramp[:k] * (self.attack / k if k < self.attack else 1.0)
                np.minimum(ramp, req[:k], out=g[:k])
                g0 = float(ramp[-1])
            if k < m:                                                 # release: up at `step` per sample, capped
                i = self._i[:m - k]
                v = np.minimum.accumulate(np.minimum(np.minimum(cap[k:], 1.0) - self.step * i, g0))
                np.minimum(v + self.step * i, 1.0, out=g[k:])
            y[s:s + m] = seg * g
            self.gain = float(g[-1])
        return y


class HapticEngine:
    def __init__(self, cfg: dict, sr: int, sources: list, stale_after: float = 1.0,
                 output_scale: float = 1.0, seed: Optional[int] = None) -> None:
        self.sr = sr
        self.limiter = PeakLimiter(sr, block=int(cfg.get("audio", {}).get("blocksize", 480)))
        self.mix_limiter: Optional[PeakLimiter] = None   # Demo's lower ceiling: the mix only, never the test tone
        self.sources = sources
        self.stale_after = stale_after
        self.effects = build_effects(cfg.get("effects", {}), sr)
        if seed is not None:                       # offline renders only; live play stays random
            seed_effects(self.effects, seed)
        self.master = float(cfg.get("audio", {}).get("master_gain", 0.8))
        self.output_scale = float(output_scale)     # below 1 for Demo; the master slider stays the user's
        self.prev: Optional[Telemetry] = None
        self.last_key = None
        self.current: Optional[Telemetry] = None
        self.peak = 0.0
        self.blocks = 0
        self.tone: Optional[TestTone] = None

    def pick(self) -> Optional[Telemetry]:
        best, best_t = None, -math.inf
        for s in self.sources:
            tele = s.latest()
            if tele is not None and tele.t > best_t:
                best, best_t = tele, tele.t
        if best is None or time.perf_counter() - best.t > self.stale_after:
            return None
        return best

    def render(self, n: int) -> np.ndarray:
        tele = self.pick()
        self.current = tele
        if tele is None:
            self.prev = None
            self.last_key = None
        else:
            key = (tele.source, tele.seq)
            if key != self.last_key:
                same = self.prev is not None and self.prev.source == tele.source
                prev = self.prev if same else None
                dt = (tele.t - prev.t) if prev is not None else 0.0
                for e in self.effects:
                    if e.enabled:
                        try:
                            e.on_frame(tele, prev, dt)
                        except Exception as exc:       # one effect choking on odd telemetry mutes only itself
                            self.effect_error = f"{e.name}: {type(exc).__name__}: {exc}"
                self.prev = tele
                self.last_key = key
        out = np.zeros(n, dtype=np.float32)
        for e in self.effects:
            if not e.enabled:
                continue
            try:
                y = e.render(n, tele)
            except Exception as exc:
                self.effect_error = f"{e.name}: {type(exc).__name__}: {exc}"
                continue
            if y is not None:
                if not np.isfinite(y).all():     # one effect's NaN must not silence the whole mix
                    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
                out += y
        out *= self.master * self.output_scale
        # NaN or inf from a garbled packet must never reach the shaker as a full-scale pop
        np.nan_to_num(out, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        if self.mix_limiter is not None:
            out = self.mix_limiter.process(out)
        tone = self.tone                       # swapped in from the UI thread, read once
        if tone is not None:
            out = out + tone.block(n)
            if tone.done:
                self.tone = None
        out = self.limiter.process(out)         # HaptiConnect's: a loud moment ducks the mix, nothing clips
        pk = float(np.max(np.abs(out))) if n else 0.0
        self.peak = max(self.peak * 0.85, pk)
        self.blocks += 1
        return out

    def levels(self) -> str:
        return " ".join(f"{e.name}:{e.level:.2f}" for e in self.effects if e.enabled and e.level > 0.01)
