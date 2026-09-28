"""Building blocks for effects: click-free tones, decaying thumps, band-limited noise."""
from __future__ import annotations

import math

import numpy as np

TWO_PI = 2.0 * math.pi


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def onepole_lp(x: np.ndarray, a: float, z: float):
    """Vectorized one-pole low-pass: y[k] = z + a * (x[k] - z). Returns (y, new_state)."""
    out = np.empty(len(x), dtype=np.float64)
    r = 1.0 - a
    n = len(x)
    start = 0
    while start < n:
        seg = x[start:start + 256]
        m = len(seg)
        w = r ** np.arange(1, m + 1)
        y = w * (z + a * np.cumsum(seg / w))
        out[start:start + m] = y
        z = float(y[-1])
        start += m
    return out, z


class Ramp:
    """Linear ramp from the previous value to the new one over a block (no zipper noise)."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = float(value)

    def block(self, target: float, n: int) -> np.ndarray:
        target = float(target)
        if target == self.value:
            return np.full(n, target, dtype=np.float32)
        out = np.linspace(self.value, target, n, endpoint=False, dtype=np.float32)
        self.value = target
        return out


class Tone:
    """Continuous sine whose frequency and amplitude glide smoothly between blocks."""

    def __init__(self, sr: int) -> None:
        self.sr = sr
        self.phase = 0.0
        self.amp = Ramp()
        self.freq: float | None = None

    def render(self, n: int, freq: float, amp: float, harmonics=None) -> np.ndarray:
        """harmonics: optional relative amplitudes of the 2nd, 3rd, ... harmonics (square-ish tones)."""
        if not math.isfinite(freq):              # one garbled packet must not break the phase for good
            freq = self.freq if self.freq is not None and math.isfinite(self.freq) else 0.0
        if amp <= 0.0 and self.amp.value <= 0.0:
            self.freq = freq
            return np.zeros(n, dtype=np.float32)
        if self.freq is None:
            self.freq = freq
        f = np.linspace(self.freq, freq, n, endpoint=False, dtype=np.float64)
        self.freq = freq
        ph = self.phase + np.cumsum(TWO_PI * f / self.sr)
        self.phase = float(ph[-1] % TWO_PI)
        if not math.isfinite(self.phase):
            self.phase = 0.0
        wave = np.sin(ph)
        if harmonics:
            for k, h in enumerate(harmonics, start=2):
                if h:
                    wave = wave + float(h) * np.sin(k * ph)
        return (wave * self.amp.block(amp, n)).astype(np.float32)


class Wavetable:
    """Loops one recorded cycle (unit RMS) at a variable frequency; amplitude glides per block."""

    def __init__(self, sr: int, table: np.ndarray) -> None:
        self.sr = sr
        t = np.asarray(table, dtype=np.float64)
        t = t - t.mean()
        t /= max(float(np.sqrt(np.mean(t ** 2))), 1e-9)          # unit RMS -> amp parameter is RMS
        self.table = np.concatenate([t, t[:1]])                  # wrap point for interpolation
        self.n = len(t)
        self.phase = 0.0
        self.amp = Ramp()
        self.freq: float | None = None

    def render(self, n: int, freq: float, amp: float) -> np.ndarray:
        if amp <= 0.0 and self.amp.value <= 0.0:
            self.freq = freq
            return np.zeros(n, dtype=np.float32)
        if self.freq is None:
            self.freq = freq
        f = np.linspace(self.freq, freq, n, endpoint=False, dtype=np.float64)
        self.freq = freq
        ph = self.phase + np.cumsum(f / self.sr)
        self.phase = float(ph[-1] % 1.0)
        pos = (ph % 1.0) * self.n
        y = np.interp(pos, np.arange(self.n + 1), self.table)
        return (y * self.amp.block(amp, n)).astype(np.float32)


class Thump:
    """One-shot decaying sine: amp * exp(-t/tau) * sin(2*pi*f*t)."""

    __slots__ = ("sr", "freq", "amp", "tau", "t")

    def __init__(self, sr: int, freq: float, amp: float, tau: float) -> None:
        self.sr, self.freq, self.amp, self.tau, self.t = sr, freq, amp, max(tau, 0.005), 0.0

    def render(self, n: int) -> np.ndarray:
        t = self.t + np.arange(n, dtype=np.float64) / self.sr
        self.t += n / self.sr
        return self.amp * np.exp(-t / self.tau) * np.sin(TWO_PI * self.freq * t)

    @property
    def done(self) -> bool:
        return self.t > 6.0 * self.tau

    @property
    def current_amp(self) -> float:
        return self.amp * math.exp(-self.t / self.tau)


class ThumpBank:
    def __init__(self, sr: int, max_voices: int = 16) -> None:
        self.sr = sr
        self.max_voices = max_voices
        self.voices: list[Thump] = []
        self.level = 0.0

    def trigger(self, freq: float, amp: float, tau: float) -> None:
        if amp <= 0.0:
            return
        if len(self.voices) >= self.max_voices:
            self.voices.pop(0)
        self.voices.append(Thump(self.sr, freq, amp, tau))

    def render(self, n: int):
        if not self.voices:
            self.level = 0.0
            return None
        out = np.zeros(n, dtype=np.float64)
        for v in self.voices:
            out += v.render(n)
        self.voices = [v for v in self.voices if not v.done]
        self.level = max((v.current_amp for v in self.voices), default=0.0)
        return out.astype(np.float32)


def load_sample(path, sr: int):
    """Load a mono WAV template (recorded from HaptiConnect) as float32 at the engine sample rate."""
    import wave
    with wave.open(str(path), "rb") as w:
        fsr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        y = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        y = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {sw} in {path}")
    if ch > 1:
        y = y.reshape(-1, ch)[:, 0]
    if fsr != sr:
        t_src = np.arange(len(y)) / fsr
        t_dst = np.arange(0.0, t_src[-1], 1.0 / sr)
        y = np.interp(t_dst, t_src, y).astype(np.float32)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    return y / peak if peak > 0 else y


TEMPLATE_SHAPES = ("sine", "square", "saw")


def synth_template(sr: int, freq: float, duration: float, shape: str = "sine", attack: float = 0.002,
                   release: float = 0.004, decay: float | None = None, harmonics=None,
                   level: float = 1.0, bandlimit_hz: float = 1000.0, duty: float = 0.5) -> np.ndarray:
    """A one-shot template generated from a few numbers (the shipped profiles use no recordings).

    shape: "sine", "square" (odd harmonics) or "saw" (all harmonics), band-limited below `bandlimit_hz`
    (1 kHz). A square with bandlimit_hz 0 is a hard +-1 square - HaptiConnect's collision is one - whose
    positive part lasts `duty` of each period (HaptiConnect's: +10.0 / -8.7 ms, duty ~0.53).
    attack / release: linear fades at the start and end (s); decay: exponential time constant (s),
    None = flat. harmonics: extra relative amplitudes of the 2nd, 3rd, ... harmonic. level: the peak
    of the result, so a template can sit below or above full scale without touching the effect's gain.
    """
    if shape not in TEMPLATE_SHAPES:
        raise ValueError(f"unknown template shape {shape!r} (use one of {', '.join(TEMPLATE_SHAPES)})")
    n = max(int(round(float(duration) * sr)), 8)
    t = np.arange(n, dtype=np.float64) / sr
    ph = TWO_PI * float(freq) * t
    kmax = max(1, int(float(bandlimit_hz) // max(float(freq), 1.0)))
    if shape == "sine":
        y = np.sin(ph)
    elif shape == "square" and float(bandlimit_hz) <= 0.0:
        y = np.where((float(freq) * t) % 1.0 < float(duty), 1.0, -1.0)
    elif shape == "square":
        y = sum(np.sin(k * ph) / k for k in range(1, kmax + 1, 2))
    else:
        y = sum(np.sin(k * ph) / k for k in range(1, kmax + 1))
    for k, h in enumerate(harmonics or [], start=2):
        if h:
            y = y + float(h) * np.sin(k * ph)
    env = np.ones(n, dtype=np.float64)
    if decay:
        env *= np.exp(-t / max(float(decay), 1e-4))
    a = min(max(int(float(attack) * sr), 1), n)
    r = min(max(int(float(release) * sr), 1), n)
    env[:a] *= np.linspace(0.0, 1.0, a, endpoint=False)
    env[n - r:] *= np.linspace(1.0, 0.0, r)
    y = y * env
    peak = float(np.max(np.abs(y)))
    return (y * (float(level) / peak)).astype(np.float32) if peak > 0 else y.astype(np.float32)


def synth_cycle(harmonics, n: int = 256) -> np.ndarray:
    """One waveform cycle for a Wavetable from the relative amplitudes of harmonics 1, 2, 3, ..."""
    x = TWO_PI * np.arange(n, dtype=np.float64) / n
    y = sum(float(h) * np.sin((k + 1) * x) for k, h in enumerate(harmonics))
    return np.asarray(y, dtype=np.float32)


class SampleBank:
    """Plays recorded one-shot templates (amplitude-scaled) instead of synthetic thumps."""

    def __init__(self, max_voices: int = 8) -> None:
        self.max_voices = max_voices
        self.voices: list[list] = []   # [sample, position, amp]
        self.level = 0.0

    def trigger(self, sample: np.ndarray, amp: float, pitch: float = 1.0) -> None:
        """pitch > 1 plays the sample faster (higher); implemented by resampling once per trigger."""
        if amp <= 0.0 or sample is None or len(sample) == 0:
            return
        if pitch and abs(pitch - 1.0) > 1e-3:
            n_out = max(int(len(sample) / pitch), 8)
            sample = np.interp(np.linspace(0.0, len(sample) - 1, n_out), np.arange(len(sample)), sample).astype(np.float32)
        if len(self.voices) >= self.max_voices:
            self.voices.pop(0)
        self.voices.append([sample, 0, float(amp)])

    def render(self, n: int):
        if not self.voices:
            self.level = 0.0
            return None
        out = np.zeros(n, dtype=np.float32)
        keep = []
        lvl = 0.0
        for v in self.voices:
            sample, pos, amp = v
            seg = sample[pos:pos + n]
            out[:len(seg)] += amp * seg
            v[1] = pos + n
            if v[1] < len(sample):
                keep.append(v)
                lvl = max(lvl, amp * float(np.max(np.abs(seg))) if len(seg) else 0.0)
        self.voices = keep
        self.level = lvl
        return out


class Noise:
    """Low-passed white noise with a smoothed amplitude; ~unit peak at amp 1."""

    def __init__(self, sr: int, cutoff: float = 60.0, seed: int = 1) -> None:
        self.sr = sr
        self.rng = np.random.default_rng(seed)
        self.z = 0.0
        self.amp = Ramp()
        self.set_cutoff(cutoff)

    def set_cutoff(self, cutoff: float) -> None:
        self.a = 1.0 - math.exp(-TWO_PI * max(cutoff, 1.0) / self.sr)
        self.norm = 0.3 * math.sqrt(2.0 / self.a)   # white->LP variance is a/2; 0.3 RMS => peaks ~1

    def render(self, n: int, amp: float):
        if amp <= 0.0 and self.amp.value <= 0.0:
            return None
        white = self.rng.standard_normal(n)
        y, self.z = onepole_lp(white, self.a, self.z)
        return (y * self.norm * self.amp.block(amp, n)).astype(np.float32)


class BandNoise:
    """Noise that fills one frequency band, [lo, hi] Hz, and nothing much outside it.

    Two independent white noises (I and Q) are low-passed by `order` one-poles in cascade, tuned so the
    cascade is 3 dB down at half the band's width, and shifted up to the band's centre: y = I cos - Q sin.
    It is normalized to unit variance, so `amp` is in the same units as a sine's peak: a band noise at
    amp A carries the energy of a sine of amplitude A (HaptiConnect's road bed is measured that way).
    Seeded: the same seed gives the same noise, so offline renders repeat exactly.
    """

    def __init__(self, sr: int, lo: float, hi: float, order: int = 2, seed: int = 7) -> None:
        self.sr = sr
        lo, hi = sorted((max(float(lo), 0.0), min(float(hi), 0.45 * sr)))
        self.order = min(max(1, int(order)), 12)
        half = max((hi - lo) / 2.0, 0.25)
        # a stage above ~0.2 x sr would make onepole_lp underflow (it divides by r ** 256)
        stage = min(half / math.sqrt(2.0 ** (1.0 / self.order) - 1.0), 0.2 * sr)
        self.a = 1.0 - math.exp(-TWO_PI * stage / sr)
        self.w = TWO_PI * (lo + hi) / 2.0 / sr
        self.zi = [0.0] * self.order
        self.zq = [0.0] * self.order
        self.phase = 0.0
        self.rng = np.random.default_rng(seed)
        self.amp = Ramp()
        # the cascade's impulse response, long enough for its energy: an order-N cascade peaks near N / a
        length = (self.order + 10.0 * math.sqrt(self.order) + 20.0) / self.a
        h = np.zeros(int(min(max(length, 64.0), 60.0 * sr)))
        h[0] = 1.0
        for _ in range(self.order):
            h, _z = onepole_lp(h, self.a, 0.0)
        self.norm = 1.0 / math.sqrt(float(np.sum(h * h)))

    def render(self, n: int, amp: float):
        if amp <= 0.0 and self.amp.value <= 0.0:
            return None
        i, q = self.rng.standard_normal(n), self.rng.standard_normal(n)
        for k in range(self.order):
            i, self.zi[k] = onepole_lp(i, self.a, self.zi[k])
            q, self.zq[k] = onepole_lp(q, self.a, self.zq[k])
        ph = self.phase + self.w * np.arange(1, n + 1, dtype=np.float64)
        self.phase = float(ph[-1] % TWO_PI)
        y = (i * np.cos(ph) - q * np.sin(ph)) * self.norm           # unit variance
        return (y * self.amp.block(amp / math.sqrt(2.0), n)).astype(np.float32)


class Effect:
    """Base effect. on_frame() sees every new telemetry frame; render() fills audio blocks."""

    name = "effect"

    def __init__(self, cfg: dict, sr: int) -> None:
        self.cfg = cfg or {}
        self.sr = sr
        self.enabled = bool(self.cfg.get("enabled", True))
        self.gain = float(self.cfg.get("gain", 1.0))
        self.level = 0.0      # last output level, for the status display

    def p(self, key: str, default=None):
        return self.cfg.get(key, default)

    def on_frame(self, tele, prev, dt: float) -> None:
        pass

    def render(self, n: int, tele):
        return None


def mix(*blocks):
    out = None
    for b in blocks:
        if b is None:
            continue
        out = b if out is None else out + b
    return out
