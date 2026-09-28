"""Racing effects. Each turns the normalized telemetry into a mono float32 audio block.

Effects can run in two modes:
  * synthetic (default): tones, filtered noise and decaying thumps with tunable parameters;
  * fitted: parameters from a "profile":
      engine.curve      [[rpm, Hz, amplitude], ...] lookup table replaces the linear map
      gear_shift.template / impact.template / suspension.template
                        a one-shot generated from a few numbers (base.synth_template) played on trigger
      road.wavetable_harmonics   the kerb cycle's harmonic weights (base.synth_cycle)
    `sample` (a WAV file) and `wavetable` (an .npy cycle) still load, for profiles the analysis tools learn.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from .base import (TWO_PI, BandNoise, Effect, Noise, SampleBank, ThumpBank, Tone, clamp, load_sample, mix,
                   synth_cycle, synth_template)


class _Triggered(Effect):
    """Shared plumbing for one-shot effects: synthetic thump bank plus an optional template."""

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.bank = ThumpBank(sr)
        self.samples = SampleBank()
        self.sample = None
        self.rng = None             # HapticEngine(seed=...) sets a seeded generator; unset = fresh randomness
        template, path = self.p("template"), self.p("sample")
        try:
            if template:
                self.sample = synth_template(sr, **template)
            elif path:
                self.sample = load_sample(path, sr)
        except Exception as exc:                 # a bad template falls back to the synthetic thump
            self.sample_error = f"{exc}"

    def fire(self, freq: float, amp: float, tau: float) -> None:
        if self.sample is not None:
            jitter = self.p("pitch_jitter")           # [min, max] pitch ratio, drawn per trigger (HaptiConnect randomizes)
            pitch = 1.0
            if jitter:
                if self.rng is None:
                    self.rng = np.random.default_rng()
                lo, hi = float(jitter[0]), float(jitter[1])
                pitch = float(np.exp(self.rng.uniform(np.log(lo), np.log(hi))))
            self.samples.trigger(self.sample, amp, pitch)
        else:
            self.bank.trigger(freq, amp, tau)

    def render_shots(self, n: int):
        y = mix(self.bank.render(n), self.samples.render(n))
        self.level = max(self.bank.level, self.samples.level)
        return y


class EngineEffect(Effect):
    """Continuous engine tone: frequency follows RPM, amplitude rises with throttle.

    Rev-limiter voice (HaptiConnect's BeamNG RPMs effect; off unless `rev_voice_amp` > 0): while
    rpm >= `rev_voice_frac` (0.98) x max_rpm (and >= `rev_voice_min_rpm`), a second tone plays at
    `rev_voice_hz_per_rpm` (0.00825 = 0.99 / 120) x max_rpm - `rev_voice_freq_mode` "max_rpm" (default),
    "rpm" or "fixed" (`rev_voice_freq`, 60 Hz) - with a sinusoidal envelope 1 + depth x cos at
    `rev_voice_am_hz` (10), `rev_voice_am_depth` (0.65): the carrier line is the amp and each sideband
    amp x depth / 2. `rev_voice_hold_hz` (0 = every block; HaptiConnect 11.72) decides on/off only that
    often. The engine duck HaptiConnect shows under it is its output limiter (engine.PeakLimiter), not a
    separate effect; `rev_voice_engine_scale` (1.0) is a fallback only.
    """

    name = "engine"

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.tone = Tone(sr)
        self.tone2 = Tone(sr)
        self.rev_tone = Tone(sr)
        self._rev_on = False
        self._rev_clock = 0                    # samples since the last on/off decision (rev_voice_hold_hz)
        self._am_phase = 0.0
        self._freq = float(self.p("freq_min", 22.0))
        self.curve = None
        curve = self.p("curve")
        if curve:
            arr = np.array(curve, dtype=np.float64)
            if arr.ndim == 2 and arr.shape[1] >= 3 and len(arr) >= 2:
                order = np.argsort(arr[:, 0])
                self.curve = arr[order]

    def render(self, n, tele):
        fmin = float(self.p("freq_min", 22.0))
        fmax = float(self.p("freq_max", 80.0))
        if tele is None or not tele.active or not tele.engine_running or tele.rpm < 50.0:
            amp, freq = 0.0, self._freq
        elif self.curve is not None:
            freq = float(np.interp(tele.rpm, self.curve[:, 0], self.curve[:, 1]))
            amp = float(np.interp(tele.rpm, self.curve[:, 0], self.curve[:, 2])) \
                + float(self.p("amp_throttle", 0.0)) * tele.throttle
        else:
            norm = tele.rpm_norm ** float(self.p("curve_pow", 1.0))
            freq = fmin + (fmax - fmin) * norm
            amp = float(self.p("amp_idle", 0.30)) + float(self.p("amp_throttle", 0.35)) * tele.throttle
        self._freq = freq
        self.level = amp
        rev_amp = float(self.p("rev_voice_amp", 0.0))
        rev_on = rev_amp > 0.0 and self._rev_voice_on(n, tele)
        if rev_on:
            amp *= float(self.p("rev_voice_engine_scale", 1.0))
        y = self.tone.render(n, freq, amp * self.gain, self.p("harmonics"))
        h = float(self.p("harmonic", 0.0))
        if h > 0.0:
            y = y + self.tone2.render(n, 2.0 * freq, amp * self.gain * h)
        if rev_amp > 0.0:
            y = y + self._rev_voice(n, tele, rev_amp if rev_on else 0.0)
        return y

    def _rev_voice_on(self, n, tele) -> bool:
        hold_hz = float(self.p("rev_voice_hold_hz", 0.0))
        if hold_hz > 0.0:
            self._rev_clock += n                 # a float clock keeping the remainder: 11.72 Hz stays 11.72 Hz
            period = self.sr / hold_hz
            if self._rev_clock < period:
                return self._rev_on              # between decisions: as last decided
            self._rev_clock -= period
            if self._rev_clock >= period:        # far behind (a long stall): catch up in one go
                self._rev_clock %= period
        ok = (tele is not None and tele.active and tele.engine_running
              and math.isfinite(tele.rpm) and math.isfinite(tele.max_rpm) and tele.max_rpm > 0.0)
        self._rev_on = bool(ok and tele.rpm >= float(self.p("rev_voice_frac", 0.98)) * tele.max_rpm
                            and tele.rpm >= float(self.p("rev_voice_min_rpm", 0.0)))
        return self._rev_on

    def _rev_voice(self, n, tele, amp: float) -> np.ndarray:
        mode = str(self.p("rev_voice_freq_mode", "max_rpm"))
        k = float(self.p("rev_voice_hz_per_rpm", 0.99 / 120.0))
        fixed = float(self.p("rev_voice_freq", 60.0))
        if mode == "fixed" or tele is None:
            carrier = fixed
        else:
            carrier = k * (tele.rpm if mode == "rpm" else tele.max_rpm)
        if not math.isfinite(carrier) or carrier <= 0.0:
            carrier = self.rev_tone.freq if self.rev_tone.freq is not None else fixed
        y = self.rev_tone.render(n, carrier, amp * self.gain)
        ph = self._am_phase + TWO_PI * float(self.p("rev_voice_am_hz", 10.0)) * np.arange(1, n + 1) / self.sr
        self._am_phase = float(ph[-1] % TWO_PI)
        return y * (1.0 + float(self.p("rev_voice_am_depth", 0.65)) * np.cos(ph)).astype(np.float32)


class GearShiftEffect(_Triggered):
    """Thump (or generated template) whenever the gear number changes.

    Optional rpm pitch (off unless a profile sets `pitch_hz_per_rpm`), as HaptiConnect plays it: the
    shift sounds at rpm x `pitch_hz_per_rpm` Hz (HaptiConnect: 1/120) for a fixed
    `pitched_duration_s` (default 0.08 s), in the `template`'s shape and fades (a square wave when
    there is no template), clamped to `pitch_hz_range` (default [20, 120]). The rpm is the shifting
    frame's (`pitch_rpm_from` "now", default) or the frame before it ("prev"). The level is
    0.9 x gain, as for every shift, and `pitch_jitter` does not apply: the pitch follows the rpm.

    `fire_into_neutral: false` (default true) plays nothing when the gear goes to neutral, only when
    the next gear engages - HaptiConnect's ACE plugin works that way, its Forza plugin does not.
    """

    name = "gear_shift"

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self._last = -1.0
        self._gear = None            # gear of the last ACTIVE frame; None = re-base on the next one
        self._seen = None            # time of the last frame this effect saw

    def on_frame(self, tele, prev, dt):
        # A pause, rewind, menu or respawn (inactive frames), a gap in the stream or a spell with the
        # effect switched off is not a shift: the next active frame only records its gear.
        # HaptiConnect plays nothing there.
        limit = float(self.p("rebase_gap_s", 0.5))
        first = self._seen is None
        # the engine hands every effect its own previous frame: if that is not the last frame this
        # effect saw, it was switched off in between and missed frames (a shift, a pause, a respawn)
        missed = not first and prev is not None and prev.t != self._seen
        gap = dt > limit or missed
        self._seen = tele.t
        if first and prev is not None and prev.active and not gap:
            self._gear = prev.gear               # the engine's previous frame is a fair place to start
        if prev is None or not tele.active or gap:
            self._gear = tele.gear if tele.active else None
            return
        last, self._gear = self._gear, tele.gear
        if last is None or tele.gear == last:
            return
        if tele.gear == 0 and not self.p("fire_into_neutral", True):
            return                               # e.g. HaptiConnect's ACE plugin: only the engagement plays
        # a shift usually passes through neutral (gear 0): fire when leaving the old gear, and do not fire
        # again when the new gear engages shortly after
        if tele.gear == 0 or last == 0:
            if tele.t - self._last < float(self.p("neutral_window_s", 0.6)):
                return
        if (tele.t - self._last) > float(self.p("cooldown", 0.12)):
            if self.p("pitch_hz_per_rpm"):
                self._fire_pitched(prev.rpm if self.p("pitch_rpm_from", "now") == "prev" else tele.rpm)
            else:
                self.fire(float(self.p("freq", 45.0)), 0.9 * self.gain, float(self.p("tau", 0.06)))
            self._last = tele.t

    def _fire_pitched(self, rpm: float) -> None:
        lo, hi = (float(v) for v in (self.p("pitch_hz_range") or (20.0, 120.0)))
        freq = min(max(float(rpm) * float(self.p("pitch_hz_per_rpm")), lo), hi)
        spec = dict(self.p("template") or {"shape": "square", "attack": 0.002, "release": 0.003})
        spec.update(freq=freq, duration=float(self.p("pitched_duration_s", 0.08)))
        try:
            shot = synth_template(self.sr, **spec)
        except Exception as exc:                 # a bad template: no shot rather than a crash
            self.sample_error = f"{exc}"
            return
        self.samples.trigger(shot, 0.9 * self.gain)

    def render(self, n, tele):
        return self.render_shots(n)


class WheelLockEffect(Effect):
    """Brake lock-up: wheels turning much slower than the car while braking."""

    name = "wheel_lock"

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.tone = Tone(sr)
        self.noise = Noise(sr, float(self.p("noise_cutoff", 70.0)), seed=11)
        self._level = 0.0

    def on_frame(self, tele, prev, dt):
        lock = 0.0
        need_brake = bool(self.p("need_brake", True))
        if tele.active and (not need_brake or tele.brake > 0.05 or tele.handbrake > 0.05) \
                and tele.speed > float(self.p("min_speed", 2.0)):
            th = float(self.p("threshold", 1.0))
            full = float(self.p("full", 3.0))
            for s in tele.slip_ratio:
                if self.p("binary", False):
                    lock = max(lock, 1.0 if -s >= th else 0.0)      # HaptiConnect: on/off at a threshold
                else:
                    lock = max(lock, clamp((-s - th) / max(full - th, 1e-6)))
        self._level = lock

    def render(self, n, tele):
        lvl = self._level if tele is not None else 0.0
        self.level = lvl
        amp = lvl * self.gain
        tone_amp = float(self.p("tone_amp", 0.5))
        noise_amp = float(self.p("noise_amp", 0.6))
        y = self.tone.render(n, float(self.p("freq", 28.0)), amp * tone_amp, self.p("harmonics"))
        if noise_amp > 0.0:
            y = mix(y, self.noise.render(n, amp * noise_amp))
        return y


class WheelSlipEffect(Effect):
    """Traction loss: wheelspin under power (buzz) and lateral sliding (rumble)."""

    name = "wheel_slip"

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.tone = Tone(sr)
        self.noise = Noise(sr, float(self.p("noise_cutoff", 45.0)), seed=12)
        self._spin = 0.0
        self._slide = 0.0

    def on_frame(self, tele, prev, dt):
        spin = slide = 0.0
        if tele.active:
            spin_max = float(self.p("spin_max", 1e9))      # HaptiConnect's Forza slip effect is band-limited
            slide_max = float(self.p("slide_max", 1e9))
            wheels = self.p("spin_wheels") or [0, 1, 2, 3]
            if (tele.throttle > 0.05 or not self.p("need_throttle", True)) \
                    and tele.speed > float(self.p("spin_min_speed", 1.0)):
                th = float(self.p("spin_threshold", 1.0))
                full = float(self.p("spin_full", 2.5))
                for i in wheels:
                    s = tele.slip_ratio[i]
                    if s <= spin_max:
                        spin = max(spin, clamp((s - th) / max(full - th, 1e-6)))
            if tele.speed > 4.0:
                th = float(self.p("slide_threshold", 1.0))
                full = float(self.p("slide_full", 2.0))
                for a in tele.slip_angle:
                    if abs(a) <= slide_max:
                        slide = max(slide, clamp((abs(a) - th) / max(full - th, 1e-6)))
            if tele.has_vib_hints:
                spin = max(spin, tele.slip_vib)
        self._spin, self._slide = spin, slide

    def render(self, n, tele):
        spin = self._spin if tele is not None else 0.0
        slide = self._slide if tele is not None else 0.0
        self.level = max(spin, slide)
        slide_tone = self.p("slide_tone_freq")          # HaptiConnect renders slides as a tone, not noise
        if slide_tone:
            if not hasattr(self, "tone2"):
                self.tone2 = Tone(self.sr)
            return mix(self.tone.render(n, float(self.p("freq", 42.0)), spin * self.gain, self.p("harmonics")),
                       self.tone2.render(n, float(slide_tone), slide * self.gain, self.p("harmonics")))
        return mix(self.tone.render(n, float(self.p("freq", 42.0)), spin * self.gain),
                   self.noise.render(n, slide * self.gain * 0.8))


class _PulsedTone(Effect):
    """Helper: a carrier tone gated by a smooth pulse train."""

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.tone = Tone(sr)
        self.gphase = 0.0

    def pulsed(self, n, freq, pulse_hz, amp):
        y = self.tone.render(n, freq, amp)
        if amp > 0.0 or self.tone.amp.value > 0.0:
            ph = self.gphase + TWO_PI * pulse_hz * np.arange(1, n + 1, dtype=np.float64) / self.sr
            self.gphase = float(ph[-1] % TWO_PI)
            gate = (0.5 - 0.5 * np.cos(ph)) ** 2
            y = y * gate.astype(np.float32)
        return y


class ABSEffect(_PulsedTone):
    """ABS regulation: pulsing brake vibration."""

    name = "abs"

    def render(self, n, tele):
        amp = 0.0
        if tele is not None and tele.active:
            if tele.has_vib_hints and tele.abs_vib > 0.02:
                amp = tele.abs_vib
            elif tele.abs_active:
                amp = 1.0
        self.level = amp
        return self.pulsed(n, float(self.p("freq", 50.0)), float(self.p("pulse_hz", 13.0)), amp * self.gain)


class ShiftIndicatorEffect(_PulsedTone):
    """Shift point warning.

    Default: pulses when RPM reaches `rpm_pct` of max. HaptiConnect-style (profile): `rpm_curve`
    [[rpm/max_rpm, amp], ...] gives a continuous ~68 Hz tone whose level ramps up from ~80% of max rpm
    (measured on real Forza laps), `pulse_hz` 0 = continuous, `min_throttle` gates it. `min_gear` (unset =
    every gear): below that gear (-1 reverse, 0 neutral) the level is scaled by `below_min_gear_scale`
    (default 0 = silent) - HaptiConnect's Forza plugins are all but silent in reverse.
    """

    name = "shift_indicator"

    def render(self, n, tele):
        amp = 0.0
        curve = self.p("rpm_curve")
        if tele is not None and tele.active and tele.engine_running and tele.throttle > float(self.p("min_throttle", 0.2)):
            if curve:
                c = np.array(curve, dtype=np.float64)
                amp = float(np.interp(tele.rpm / max(tele.max_rpm, 1.0), c[:, 0], c[:, 1]))
            elif tele.rpm >= float(self.p("rpm_pct", 0.95)) * tele.max_rpm:
                amp = 1.0
            min_gear = self.p("min_gear")
            if min_gear is not None and tele.gear < int(min_gear):
                amp *= float(self.p("below_min_gear_scale", 0.0))
        self.level = amp
        pulse = float(self.p("pulse_hz", 9.0))
        if pulse <= 0.0:
            return self.tone.render(n, float(self.p("freq", 65.0)), amp * self.gain, self.p("harmonics"))
        return self.pulsed(n, float(self.p("freq", 65.0)), pulse, amp * self.gain)


class SuspensionEffect(_Triggered):
    """Bumps from suspension velocity per corner, plus fine road texture from small movements, plus the
    road bed: HaptiConnect's continuous ~41 Hz rumble (Forza plugins), when the profile sets `vel_curve`.

    Road-bed keys for HaptiConnect parity. All are opt-in: without them the bed is exactly as before.
      vel_curve_m       [[m/s, amp], ...] - the bed follows SuspensionTravelMeters (Forza packet offset 196),
                        which is what HaptiConnect follows, instead of normalized travel (`vel_curve`, per s).
                        A game that reports no metres uses normalized x `metres_per_unit` (default 0.15, what
                        forward.py's replay packets carry).
      vel_span_s        velocity over this span instead of frame to frame (HaptiConnect polls at ~12 Hz)
      vel_poll_hz       sample the travel only this often and difference poll to poll (a sampled 12 Hz
                        poll, unlike the sliding span); the velocity holds between polls
      vel_time_source   "frame" (default) or "packet": the game's packet clock; a repeated packet is skipped
      wheel_combine     how four wheels make one velocity: max (default), sum, mean, rms, front_max, rear_max
      vel_hold_floor_s  the shortest release `vel_hold_s` may have (default 0.05)
      bed_env           "peak_hold" (default) or "frame": no hold, the newest velocity
      bed_update_hz     hold the bed level for 1/hz s at a time (HaptiConnect steps it ~12 times a second)
      amp_mpu_ref, amp_mpu_exp   experimental: the curve's output times (mpu / ref) ** exp, where mpu is the
                        car's metres of travel per normalized unit (learned from the two travel values). A
                        hypothesis for the per-car ceiling the calibration notes see; off unless both are set.
      surface_gain_curve / surface_add_curve   [[SurfaceRumble, x], ...]: the bed times / plus a term of the
                        surface material code (offset 148). surface_mode "scale" (default: v*g + a) or "max"
                        (max(v*g, a)); surface_reduce max (default), mean, sum, count_nonzero; surface_hold_s
      bed_noise         {"curve": [[x, amp], ...], "floor": amp, "drive": "line" | "vpeak" | "speed",
                        "band": [lo, hi] (default [35, 47]) or "bands": [[lo, hi, rel_db], ...], "order": 2}:
                        a band-noise voice beside the 41 Hz line - HaptiConnect's bed is broadband when quiet
                        and nearly a pure tone when loud. Amplitudes are pre-gain, in sine-peak units.
      render_part       all (default), line, noise, bed (line + noise) or shots (bumps + texture): one part
                        only, for measuring
    """

    name = "suspension"
    BED_KEYS = ("vel_curve_m", "vel_span_s", "vel_poll_hz", "vel_time_source", "wheel_combine", "bed_env")

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.noise = Noise(sr, float(self.p("texture_cutoff", 40.0)), seed=3)
        self.idle_tone = Tone(sr)          # HaptiConnect keeps a constant low rumble while moving
        self.texture = 0.0
        self._last = [-1.0] * 4
        self._vpeak = 0.0
        self._surf = 0.0
        self._hist: deque = deque()        # (time, travel per wheel) for the bed's velocity
        self._bed_t = None
        self._step_next, self._step_amp = None, 0.0   # bed_update_hz: when the level may change next
        self._poll = None                  # (time, travel) of the last poll sample (vel_poll_hz)
        self._poll_next = None             # when the next poll is due: a timer, so 12 Hz stays 12 Hz
        self._mpu = None                   # learned metres per normalized unit (amp_mpu_*)
        default = {"vel_time_source": "frame", "wheel_combine": "max", "bed_env": "peak_hold"}
        self._bed_keys = any(self.p(k) not in (None, default.get(k), 0, 0.0, "") for k in self.BED_KEYS)
        self._noise_voices = self._build_bed_noise(self.p("bed_noise"), sr)

    @staticmethod
    def _build_bed_noise(spec, sr):
        if not isinstance(spec, dict):
            return []
        bands = spec.get("bands") or [list(spec.get("band") or [35.0, 47.0]) + [0.0]]
        weights = [10.0 ** (float(b[2] if len(b) > 2 else 0.0) / 20.0) for b in bands]
        total = math.sqrt(sum(w * w for w in weights)) or 1.0      # the whole voice carries `amp`
        order = int(spec.get("order", 2))
        return [(BandNoise(sr, float(b[0]), float(b[1]), order=order, seed=7 + i), w / total)
                for i, (b, w) in enumerate(zip(bands, weights))]

    def on_frame(self, tele, prev, dt):
        # no velocity across an inactive frame: the travel jumps at race start and on unpause, which
        # read as a ~70/s spike - a bump that never happened
        if prev is None or dt <= 0.0 or dt > 0.5 or not tele.active or not prev.active:
            self.texture *= 0.5
            self._hist.clear()
            self._bed_t = self._poll = self._poll_next = self._step_next = None
            self._surf = 0.0                     # a pause releases the holds: no pre-pause level afterwards
            if self._bed_keys:
                self._vpeak = 0.0
            return
        th = float(self.p("threshold", 1.0))
        full = float(self.p("full", 8.0))
        tau = float(self.p("tau", 0.045))
        min_int = float(self.p("min_interval", 0.04))
        fixed = bool(self.p("fixed_amp", False))
        has_susp = any(tele.susp_travel) or any(prev.susp_travel)
        if not has_susp:
            # no suspension data (BeamNG packets): bumps from vertical-g jumps, like HaptiConnect does
            vth = float(self.p("vert_threshold", 6.0))
            jump = abs(tele.accel_vert - prev.accel_vert)
            if jump > vth and tele.t - self._last[0] > min_int:
                amp = 1.0 if fixed else clamp((jump - vth) / max(float(self.p("vert_full", 30.0)) - vth, 1e-6)) ** 0.7
                self.fire(float(self.p("front_freq", 38.0)), amp * self.gain, tau)
                self._last[0] = tele.t
            self.texture *= 0.5
            if self._bed_keys and (any(tele.susp_travel_m) or any(prev.susp_travel_m)):
                # airborne in Forza: normalized travel is all 0 but the metres still move - keep the
                # bed's history going frame by frame, or the landing reads as the whole flight's average
                self._track_bed(tele, prev)
            return
        total = 0.0
        pulse_amp = float(self.p("pulse_amp", 1.0))       # 0 = bumps only (re)trigger the latched tone
        vmax = 0.0
        for i in range(4):
            v = (tele.susp_travel[i] - prev.susp_travel[i]) / dt
            if not math.isfinite(v):
                continue                         # a garbled value must not poison the texture for good
            mag = abs(v)
            total += mag
            vmax = max(vmax, mag)
            if mag > th and tele.t - self._last[i] > min_int:
                amp = 1.0 if fixed else clamp((mag - th) / max(full - th, 1e-6)) ** 0.7
                freq = float(self.p("front_freq", 38.0)) if i < 2 else float(self.p("rear_freq", 30.0))
                if pulse_amp > 0.0:
                    self.fire(freq, amp * self.gain * pulse_amp, tau)
                self._last[i] = tele.t
        # roughness tracker: peak-hold of the fastest wheel movement with exponential release
        if self._bed_keys:
            self._track_bed(tele, prev)
        else:
            hold_tau = float(self.p("vel_hold_s", 1.0))
            floor = float(self.p("vel_hold_floor_s", 0.05))
            self._vpeak = max(vmax, self._vpeak * math.exp(-dt / max(hold_tau, floor)))
        self._track_surface(tele, dt)
        if self.p("amp_mpu_ref") and self.p("amp_mpu_exp") is not None:
            self._track_mpu(tele, prev)
        tex = clamp(total / 4.0 / th) * float(self.p("texture_gain", 0.35))
        self.texture += (tex - self.texture) * 0.3
        if not math.isfinite(self.texture):
            self.texture = 0.0

    # -- the road bed's inputs ------------------------------------------------------------------------
    def _travel(self, t, metres: bool) -> list:
        if not metres:
            return list(t.susp_travel)
        if any(t.susp_travel_m):
            return list(t.susp_travel_m)
        k = float(self.p("metres_per_unit", 0.15))
        return [x * k for x in t.susp_travel]

    def _clock(self, t) -> float:
        if str(self.p("vel_time_source", "frame")) == "packet" and t.packet_ms is not None:
            return t.packet_ms / 1000.0
        return t.t

    def _track_mpu(self, tele, prev) -> None:
        """Learn the car's metres per normalized unit: the two travel values are exactly linear per car."""
        slopes = [(m1 - m0) / (n1 - n0) for n0, n1, m0, m1 in zip(prev.susp_travel, tele.susp_travel,
                                                                   prev.susp_travel_m, tele.susp_travel_m)
                  if abs(n1 - n0) > 1e-3 and (m0 or m1)]
        if slopes:
            s = abs(sum(slopes) / len(slopes))
            self._mpu = s if self._mpu is None else 0.9 * self._mpu + 0.1 * s

    def _track_bed(self, tele, prev) -> None:
        metres = bool(self.p("vel_curve_m"))
        now = self._clock(tele)
        poll_hz = float(self.p("vel_poll_hz", 0.0))
        last_t = self._poll[0] if (poll_hz > 0.0 and self._poll) else (self._hist[-1][0] if self._hist else None)
        if last_t is not None and now < last_t - 0.25:
            # the clock went back (a restart, or TimestampMS wrapping): start over rather than wait for it
            self._hist.clear()
            self._poll = self._poll_next = self._bed_t = None
        if poll_hz > 0.0:
            # HaptiConnect-style poll: sample the travel every 1/hz s, difference sample to sample
            period = 1.0 / poll_hz
            if self._poll is None:
                self._poll = (self._clock(prev), self._travel(prev, metres))
                self._poll_next = self._poll[0] + period
            if now < self._poll_next - 5e-4:
                return                           # between polls: nothing new is known
            ref, self._poll = self._poll, (now, self._travel(tele, metres))
            self._poll_next += period            # a timer: a late frame does not slow the rate down
            if now >= self._poll_next:
                self._poll_next = now + period   # more than a period late (a sparse stream): resync
            if now <= ref[0]:
                return
            vs = [abs(a - b) / (now - ref[0]) for a, b in zip(self._poll[1], ref[1])]
            last = ref[0]
        else:
            hist = self._hist
            if not hist:
                hist.append((self._clock(prev), self._travel(prev, metres)))
            if now <= hist[-1][0]:
                return                           # the same packet again (or a clock that went back)
            hist.append((now, self._travel(tele, metres)))
            span = max(float(self.p("vel_span_s", 0.0)), 0.0)
            ref = next((h for h in reversed(list(hist)[:-1]) if h[0] <= now - span), hist[0])
            while hist[0] is not ref:
                hist.popleft()
            vs = [abs(a - b) / (now - ref[0]) for a, b in zip(hist[-1][1], ref[1])]
            last = hist[-2][0]
        mode = str(self.p("wheel_combine", "max"))
        if mode == "sum":
            v = sum(vs)
        elif mode == "mean":
            v = sum(vs) / len(vs)
        elif mode == "rms":
            v = math.sqrt(sum(x * x for x in vs) / len(vs))
        elif mode == "front_max":
            v = max(vs[:2])
        elif mode == "rear_max":
            v = max(vs[2:])
        else:
            v = max(vs)
        since = now - (self._bed_t if self._bed_t is not None else last)
        self._bed_t = now
        if str(self.p("bed_env", "peak_hold")) == "frame":
            self._vpeak = v
        else:
            tau = max(float(self.p("vel_hold_s", 1.0)), float(self.p("vel_hold_floor_s", 0.05)))
            self._vpeak = max(v, self._vpeak * math.exp(-since / max(tau, 1e-6)))

    def _track_surface(self, tele, dt) -> None:
        if not (self.p("surface_gain_curve") or self.p("surface_add_curve")):
            return
        codes = [abs(float(x)) for x in tele.surface_rumble]
        mode = str(self.p("surface_reduce", "max"))
        if mode == "mean":
            s = sum(codes) / len(codes)
        elif mode == "sum":
            s = sum(codes)
        elif mode == "count_nonzero":
            s = float(sum(1 for x in codes if x > 0.0))
        else:
            s = max(codes)
        hold = float(self.p("surface_hold_s", 0.0))
        self._surf = max(s, self._surf * math.exp(-dt / hold)) if hold > 0.0 else s

    def _bed_level(self, curve, tele) -> float:
        """The bed line's pre-gain amplitude: velocity curve, surface term, speed floor, update steps."""
        c = np.array(curve, dtype=np.float64)
        amp = float(np.interp(self._vpeak, c[:, 0], c[:, 1]))
        ref, exp = self.p("amp_mpu_ref"), self.p("amp_mpu_exp")
        if ref and exp is not None and self._mpu:
            amp *= (self._mpu / float(ref)) ** float(exp)
        gcurve, acurve = self.p("surface_gain_curve"), self.p("surface_add_curve")
        if gcurve or acurve:
            g = float(np.interp(self._surf, *np.array(gcurve, dtype=np.float64).T)) if gcurve else 1.0
            a = float(np.interp(self._surf, *np.array(acurve, dtype=np.float64).T)) if acurve else 0.0
            amp = max(amp * g, a) if str(self.p("surface_mode", "scale")) == "max" else amp * g + a
        sf = self.p("speed_floor_curve")
        if sf and tele is not None:
            s = np.array(sf, dtype=np.float64)
            amp = max(amp, float(np.interp(tele.speed, s[:, 0], s[:, 1])))
        hz = float(self.p("bed_update_hz", 0.0))
        if hz > 0.0 and tele is not None:
            period, nxt = 1.0 / hz, self._step_next
            if nxt is None or tele.t < nxt - 2.0 * period:          # the first step, or the clock went back
                self._step_amp, self._step_next = amp, tele.t + period
            elif tele.t + 5e-4 >= nxt:
                self._step_amp, nxt = amp, nxt + period             # a timer: late frames keep the rate
                self._step_next = tele.t + period if tele.t >= nxt else nxt
            amp = self._step_amp
        return amp

    def _render_bed_noise(self, n, tele, line_amp: float, on: bool):
        if not self._noise_voices:
            return None
        spec = self.p("bed_noise")
        lvl = 0.0
        if on:
            drive = str(spec.get("drive", "line"))
            x = line_amp if drive == "line" else self._vpeak if drive == "vpeak" else (tele.speed if tele else 0.0)
            curve = spec.get("curve")
            if curve:
                c = np.array(curve, dtype=np.float64)
                lvl = float(np.interp(x, c[:, 0], c[:, 1]))
            lvl = max(lvl, float(spec.get("floor", 0.0)))
        out = None
        for voice, w in self._noise_voices:
            out = mix(out, voice.render(n, lvl * w * self.gain))
        return out

    def render(self, n, tele):
        if tele is None:
            self.texture = 0.0
        idle_amp = float(self.p("idle_tone_amp", 0.0))
        idle = bed_noise = None
        vel_curve = self.p("vel_curve_m") or self.p("vel_curve")
        if idle_amp > 0.0 or vel_curve:
            on = tele is not None and tele.active and tele.speed > float(self.p("idle_min_speed", 1.0))
            hold = float(self.p("latch_hold_s", 0.0))
            if hold > 0.0 and on:
                # optional latch: the tone stays on for `hold` seconds after the last bump
                last = max(self._last) if self._last else -1.0
                on = last > 0.0 and (tele.t - last) < hold
            if vel_curve:
                # HaptiConnect (Forza plugins, measured on real laps): a continuous 41 Hz tone whose amplitude
                # follows recent suspension velocity ("road roughness"), e.g. [[0, .03], [7, .05], [15, .08], [25, .2]],
                # with a floor at low speed given by `speed_floor_curve` [[m/s, amp], ...]
                amp = self._bed_level(vel_curve, tele)
            else:
                amp = idle_amp
            idle = self.idle_tone.render(n, float(self.p("idle_tone_freq", 41.0)), amp * self.gain if on else 0.0,
                                         self.p("harmonics"))
            bed_noise = self._render_bed_noise(n, tele, amp if on else 0.0, on)
        shots, texture = self.render_shots(n), self.noise.render(n, self.texture * self.gain)
        part = str(self.p("render_part", "all"))
        if part == "line":
            y = idle
        elif part == "noise":
            y = bed_noise
        elif part == "bed":
            y = mix(idle, bed_noise)
        elif part == "shots":
            y = mix(shots, texture)
        else:
            y = mix(shots, texture, idle, bed_noise)
        self.level = max(self.level, self.texture, idle_amp if idle is not None else 0.0)
        return y


class RoadEffect(Effect):
    """Rumble strips / kerbs (speed-dependent buzz) and rough-surface rumble.

    HaptiConnect-style (profile): `wavetable_harmonics` = one rough cycle built from harmonic weights
    (or `wavetable`, an .npy cycle) looped at strip_hz_per_ms * speed (capped at strip_hz_max), RMS level
    from `strip_amp_curve` [[m/s, rms], ...], on while any wheel reports a rumble strip (Forza) or the
    game's kerb hint is up (ACE).

    `strip_per_wheel: true` (opt-in, HaptiConnect sums its kerbs this way): one voice per wheel on a
    strip instead of one for the car, each starting at phase 0 when its wheel reaches the strip, so
    wheels that hit it at different moments add with independent phases. Each voice plays at the same
    level the single voice would, times `strip_wheel_scale` (default 1). Games without per-wheel
    strips (ACE's kerb hint) keep the single voice.
    """

    name = "road"

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.tone = Tone(sr)
        self.noise = Noise(sr, float(self.p("noise_cutoff", 55.0)), seed=5)
        self._strip = 0.0
        self._surface = 0.0
        self._freq = 40.0
        self.wave = None
        self.wheel_waves = None
        self._wheel_amp = [0.0] * 4
        cycle, path = self.p("wavetable_harmonics"), self.p("wavetable")
        try:
            from .base import Wavetable
            table = synth_cycle(cycle) if cycle else (np.load(path) if path else None)
            if table is not None:
                self.wave = Wavetable(sr, table)
                if self.p("strip_per_wheel", False):
                    self.wheel_waves = [Wavetable(sr, table) for _ in range(4)]
        except Exception as exc:
            self.wave_error = f"{exc}"

    def on_frame(self, tele, prev, dt):
        strip = surface = 0.0
        if tele.active:
            if tele.has_vib_hints:
                strip, surface = (1.0 if tele.kerb_vib > 0.05 else 0.0) if self.wave is not None else tele.kerb_vib, tele.road_vib
            else:
                strip = (1.0 if any(tele.rumble_strip) else 0.0) if self.wave is not None else clamp(sum(1 for r in tele.rumble_strip if r) / 2.0)
                surface = clamp(sum(tele.surface_rumble) / 4.0)
            if self.wave is not None:
                hz = float(self.p("strip_hz_per_ms", 1.25)) * tele.speed
                self._freq = clamp(hz, float(self.p("strip_hz_min", 6.0)), float(self.p("strip_hz_max", 42.0)))
                curve = self.p("strip_amp_curve")
                level = 1.0
                if curve:
                    c = np.array(curve, dtype=np.float64)
                    level = float(np.interp(tele.speed, c[:, 0], c[:, 1]))
                strip *= level
                if self.wheel_waves is not None and not tele.has_vib_hints:
                    scale = float(self.p("strip_wheel_scale", 1.0))
                    for i, on in enumerate(tele.rumble_strip):
                        voice = self.wheel_waves[i]
                        if on and self._wheel_amp[i] <= 0.0 and voice.amp.value <= 0.0:
                            voice.phase = 0.0            # a wheel reaching the strip starts its own cycle,
                            voice.freq = None            # at today's pitch, not a glide from the last kerb
                        self._wheel_amp[i] = level * scale if on else 0.0
                    strip = 0.0                          # the wheel voices carry the kerb, not the single one
            else:
                spacing = float(self.p("strip_spacing", 0.35))
                self._freq = clamp(tele.speed / max(spacing, 0.05), 20.0, 90.0)
        if not tele.active or tele.has_vib_hints:
            self._wheel_amp = [0.0] * 4
        self._strip, self._surface = strip, surface

    def render(self, n, tele):
        if tele is None:
            self._wheel_amp = [0.0] * 4          # the stream went stale: every wheel starts afresh when it is back
        strip = self._strip if tele is not None else 0.0
        surface = self._surface if tele is not None else 0.0
        self.level = max(strip, surface)
        if self.wheel_waves is not None and (any(self._wheel_amp) or
                                             any(w.amp.value > 0.0 for w in self.wheel_waves)):
            amps = self._wheel_amp if tele is not None else [0.0] * 4
            self.level = max([surface] + list(amps))
            out = np.zeros(n, dtype=np.float32)
            for voice, amp in zip(self.wheel_waves, amps):
                out += voice.render(n, self._freq, amp * self.gain)
            return out
        if self.wave is not None:
            return self.wave.render(n, self._freq, strip * self.gain)
        return mix(self.tone.render(n, self._freq, strip * self.gain * float(self.p("strip_amp", 1.0)), self.p("harmonics")),
                   self.noise.render(n, surface * self.gain * float(self.p("surface_gain", 0.6))))


class ImpactEffect(_Triggered):
    """Collisions and hard hits.

    Default: a jump in body acceleration between two frames, amplitude growing with the jump.
    HaptiConnect-style (profile): `axes` limits which axes count, `min_hold_s` requires the excursion
    to persist (HaptiConnect needs ~4 frames), `fixed_amp` plays the hit at a constant level.

    Parity keys (opt-in; without them the detector is exactly as before):
      jump_window_s  the jump rule compares with the frame this long ago, not the previous one, so it
                     does not depend on the frame rate (replays run at ~180 Hz, the game at 60)
      eval_hz        look at the telemetry only this often (HaptiConnect evaluates ~12 times a second, so
                     a short spike is hit or miss), from a seeded random phase
      fire_delay_s   play the hit this long after the trigger
      triggers       extra rules, OR'd with the main one; they share its last hit and cooldown:
                     [{"signal": "long_lat" | "vert" | "accel_3d" | "susp_vel_m" | "susp_vel" | "kerb_onset",
                       "mode": "jump" | "excursion" | "level", "threshold", "window_s", "min_hold_s",
                       "min_speed", "kerb": "ignored" | "required" | "excluded", "min_wheels", "cooldown",
                       "name"}, ...]
                     `last_rule` and `fire_log` [(t, rule), ...] say which rule fired, so the calibration
                     tools can count each rule's hits and false fires.
    """

    name = "impact"
    SIGNALS = ("long_lat", "vert", "accel_3d", "susp_vel_m", "susp_vel", "kerb_onset")

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self._last = -math.inf                          # no hit yet: a long cooldown must not block the first
        self._baseline = 0.0
        self._excursion_start = None
        self._fired_this = False
        self._hist: deque = deque()                     # frames kept for jump_window_s
        self._eval_prev = None
        self._next_eval = None
        self._pending: list = []                        # (due time, strength, threshold, rule)
        self._render_t = 0.0                            # the render clock the delayed hits are released on
        self.last_rule = ""
        self.fire_log: deque = deque(maxlen=4096)
        self._rules = [self._rule_state(r, i) for i, r in enumerate(self.p("triggers") or []) if isinstance(r, dict)]

    @staticmethod
    def _rule_state(rule: dict, i: int) -> dict:
        return {"rule": rule, "name": str(rule.get("name") or f"rule{i + 1}:{rule.get('signal', 'long_lat')}"),
                "baseline": None, "start": None, "fired": False, "hist": deque(), "kerbs": None}

    def _mag(self, tele) -> float:
        axes = self.p("axes") or ["lat", "long", "vert"]
        comps = {"lat": tele.accel_lat, "long": tele.accel_long, "vert": tele.accel_vert}
        return math.sqrt(sum(comps[a] ** 2 for a in axes if a in comps))

    def on_frame(self, tele, prev, dt):
        self._render_t = tele.t                          # the delayed hits' clock starts at every frame
        if self._pending:
            self._fire_due(tele.t)
        gap = prev is None or dt <= 0.0 or dt > 0.5 or not tele.active or not prev.active
        eval_hz = float(self.p("eval_hz", 0.0))
        if eval_hz > 0.0:
            # HaptiConnect-style sampling: the detector only sees the telemetry every 1/eval_hz s
            if gap:
                self._next_eval = None                   # a pause or gap in the stream restarts the sampling
            if not tele.active:
                self._eval_prev = None
                self._reset(tele)
                return
            if self._next_eval is None:                  # (re)starting: a random phase on the grid
                if self.rng is None:
                    self.rng = np.random.default_rng()
                self._next_eval = tele.t + float(self.rng.uniform(0.0, 1.0 / eval_hz))
                self._eval_prev = tele
                self._reset(tele)
                return
            if tele.t < self._next_eval:
                return
            while self._next_eval <= tele.t:
                self._next_eval += 1.0 / eval_hz
            prev, self._eval_prev = self._eval_prev, tele
            dt = tele.t - prev.t
            gap = dt <= 0.0 or dt > max(0.5, 1.5 / eval_hz)  # the sampling interval itself is no gap
        if gap:
            self._reset(tele)
            return
        self._main_rule(tele, prev, dt)
        for st in self._rules:
            self._extra_rule(st, tele, prev, dt)

    def _reset(self, tele) -> None:
        """After a pause or a gap: start the detectors afresh from this frame, and forget hits still
        waiting on fire_delay_s (a crash just before the game stopped must not play when it is back)."""
        self._baseline = self._mag(tele) if tele.active else 0.0
        self._hist.clear()
        self._pending.clear()
        for st in self._rules:
            st.update(baseline=None, start=None, fired=False, kerbs=None)
            st["hist"].clear()

    def _main_rule(self, tele, prev, dt) -> None:
        th = float(self.p("threshold", 25.0))
        hold = float(self.p("min_hold_s", 0.0))
        cooldown = float(self.p("cooldown", 0.12))
        if hold <= 0.0:
            axes = self.p("axes") or ["lat", "long", "vert"]
            window = float(self.p("jump_window_s", 0.0))
            ref = prev
            if window > 0.0:
                ref = self._window_ref(self._hist, tele, prev, window)
            d2 = 0.0
            if "lat" in axes:
                d2 += (tele.accel_lat - ref.accel_lat) ** 2
            if "long" in axes:
                d2 += (tele.accel_long - ref.accel_long) ** 2
            if "vert" in axes:
                d2 += (tele.accel_vert - ref.accel_vert) ** 2
            d = math.sqrt(d2)
            if d > th and tele.t - self._last > cooldown:
                self._fire(d, th, tele.t, "main")
                self._last = tele.t
            return
        # sustained-excursion detector: |a| above a slow baseline by more than th for at least `hold` seconds
        mag = self._mag(tele)
        excess = mag - self._baseline
        self._baseline += (mag - self._baseline) * min(dt / 1.0, 1.0) * (0.2 if excess > th else 1.0)
        if excess > th:
            if self._excursion_start is None:
                self._excursion_start, self._fired_this = tele.t, False
            elif not self._fired_this and tele.t - self._excursion_start >= hold and tele.t - self._last > cooldown:
                self._fire(excess, th, tele.t, "main")
                self._last = tele.t
                self._fired_this = True
        elif excess < th * 0.5:
            self._excursion_start = None

    @staticmethod
    def _window_ref(hist: deque, tele, prev, window: float):
        """The newest frame at least `window` old (the oldest one kept while none is that old yet)."""
        if not hist:
            hist.append(prev)
        hist.append(tele)
        while len(hist) > 2 and hist[1].t <= tele.t - window:
            hist.popleft()
        return hist[0]

    # -- extra trigger rules -------------------------------------------------------------------------
    @staticmethod
    def _vector(tele, signal: str) -> tuple:
        if signal == "vert":
            return (tele.accel_vert,)
        if signal == "accel_3d":
            return (tele.accel_lat, tele.accel_long, tele.accel_vert)
        return (tele.accel_lat, tele.accel_long)

    def _extra_rule(self, st: dict, tele, prev, dt) -> None:
        rule = st["rule"]
        signal = str(rule.get("signal", "long_lat"))
        kerb = str(rule.get("kerb", "ignored"))
        on_kerb = any(tele.rumble_strip)
        # the filters only gate firing: the rule keeps its history, baseline and kerb count on every frame,
        # so it never compares against a frame from before the filter closed
        gate = (tele.speed >= float(rule.get("min_speed", 0.0))
                and not (kerb == "required" and not on_kerb) and not (kerb == "excluded" and on_kerb))
        th = float(rule.get("threshold", 25.0))
        cooldown = float(rule.get("cooldown", self.p("cooldown", 0.12)))
        if signal == "kerb_onset":
            count = sum(1 for r in tele.rumble_strip if r)
            before = st["kerbs"] if st["kerbs"] is not None else sum(1 for r in prev.rumble_strip if r)
            st["kerbs"] = count
            if gate and count - before >= int(rule.get("min_wheels", 1)) and tele.t - self._last > cooldown:
                self._fire(th, th, tele.t, st["name"])
                self._last = tele.t
            return
        mode = str(rule.get("mode", "jump"))
        if signal in ("susp_vel_m", "susp_vel"):
            now = tele.susp_travel_m if signal == "susp_vel_m" else tele.susp_travel
            before = prev.susp_travel_m if signal == "susp_vel_m" else prev.susp_travel
            x = max(abs(a - b) for a, b in zip(now, before)) / dt
            if mode == "jump":
                mode = "level"                      # a velocity is already a rate of change
        elif mode == "jump":
            window = float(rule.get("window_s", 0.0))
            ref = self._window_ref(st["hist"], tele, prev, window) if window > 0.0 else prev
            x = math.sqrt(sum((a - b) ** 2 for a, b in zip(self._vector(tele, signal), self._vector(ref, signal))))
        else:
            x = math.sqrt(sum(a * a for a in self._vector(tele, signal)))
        if mode == "excursion":
            if st["baseline"] is None:
                st["baseline"] = x
            level = x - st["baseline"]
            st["baseline"] += (x - st["baseline"]) * min(dt / 1.0, 1.0) * (0.2 if level > th else 1.0)
        else:
            level = x
        if not gate:
            st["start"], st["fired"] = None, False        # a closed filter counts as below the threshold
            return
        hold = float(rule.get("min_hold_s", 0.0))
        if level > th:
            if st["start"] is None:
                st["start"], st["fired"] = tele.t, False
            if not st["fired"] and tele.t - st["start"] >= hold and tele.t - self._last > cooldown:
                self._fire(level, th, tele.t, st["name"])
                self._last = tele.t
                st["fired"] = True
        elif level < th * 0.5 or mode != "excursion":
            st["start"] = None

    # -- the hit ----------------------------------------------------------------------------------------
    def _fire(self, d: float, th: float, t: float = 0.0, rule: str = "main") -> None:
        # one physical event, one hit: every detector in the middle of an episode counts it as its own
        if self._excursion_start is not None:
            self._fired_this = True
        for st in self._rules:
            if st["start"] is not None:
                st["fired"] = True
        delay = float(self.p("fire_delay_s", 0.0))
        if delay > 0.0:
            self._pending.append((t + delay, d, th, rule))
            return
        self._play(d, th, t, rule)

    STALE_S = 0.1                                       # a delayed hit this far overdue is dropped, not played

    def _fire_due(self, now: float) -> None:
        due = [p for p in self._pending if p[0] <= now]
        self._pending = [p for p in self._pending if p[0] > now]
        for when, d, th, rule in due:
            if now - when <= self.STALE_S:
                self._play(d, th, now, rule)            # logged when it actually sounds

    def _play(self, d: float, th: float, t: float, rule: str) -> None:
        self.last_rule = rule
        self.fire_log.append((t, rule))
        if self.p("fixed_amp", False):
            amp = 1.0
        else:
            full = float(self.p("full", 100.0))
            amp = 0.5 + 0.5 * clamp((d - th) / max(full - th, 1e-6)) ** 0.6
        self.fire(float(self.p("freq", 26.0)), amp * self.gain, float(self.p("tau", 0.15)))

    def render(self, n, tele):
        if tele is None:
            self._pending.clear()                        # the stream went stale: no hit from before it
        elif self._pending:
            end = self._render_t + n / self.sr           # released in the block it falls in
            due = [p for p in self._pending if p[0] <= end]
            self._pending = [p for p in self._pending if p[0] > end]
            for when, d, th, rule in due:
                if self._render_t - when <= self.STALE_S:
                    self._play(d, th, max(when, self._render_t), rule)
        self._render_t += n / self.sr
        return self.render_shots(n)


class AccelerationEffect(Effect):
    """Low rumble that grows with longitudinal and lateral g-force.

    With the lookup tables, `combine` says how the two axes make one level: "max" (default) takes the
    larger, "sum" adds them - what HaptiConnect's Forza plugins do (measured: a p-norm with p ~1.0; max
    and root-sum-square are both rejected) - and "power" is the p-norm with `combine_p` (1 = sum,
    2 = root-sum-square). The combined level is capped at `max_level` (default 1.0, i.e. the effect's
    gain); HaptiConnect goes past what a cap of 1 allows under hard cornering.
    """

    name = "acceleration"

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.tone = Tone(sr)
        self._level = 0.0

    def combined(self, lvl_long: float, lvl_lat: float, braking: bool = False) -> float:
        """`combine_brake` (unset = `combine`) is the mode while braking; `combine_cross` k adds k x long x lat
        (HaptiConnect may be a little more than additive under hard cornering on power)."""
        mode = str(self.p("combine_brake") if braking and self.p("combine_brake") else self.p("combine", "max")).lower()
        a, b = max(lvl_long, 0.0), max(lvl_lat, 0.0)
        if mode == "sum":
            lvl = a + b
        elif mode == "power":
            p = max(float(self.p("combine_p", 1.0)), 0.1)
            lvl = (a ** p + b ** p) ** (1.0 / p)
        else:
            lvl = max(a, b)
        cross = float(self.p("combine_cross", 0.0))
        if cross:
            lvl += cross * a * b
        return min(lvl, max(float(self.p("max_level", 1.0)), 0.0))

    def on_frame(self, tele, prev, dt):
        lvl = 0.0
        if tele.active and tele.speed > 1.0:
            curve_long, curve_lat = self.p("curve_long"), self.p("curve_lat")
            if curve_long or curve_lat:
                # HaptiConnect-style lookup tables: [[signed long g, level], ...] and [[|lat g|, level], ...]
                lvl_long = lvl_lat = 0.0
                if curve_long:
                    c = np.array(curve_long, dtype=np.float64)
                    c = c[np.argsort(c[:, 0])]
                    lvl_long = float(np.interp(tele.accel_long, c[:, 0], c[:, 1]))
                if curve_lat:
                    c = np.array(curve_lat, dtype=np.float64)
                    c = c[np.argsort(c[:, 0])]
                    lvl_lat = float(np.interp(abs(tele.accel_lat), c[:, 0], c[:, 1]))
                lvl = self.combined(lvl_long, lvl_lat, braking=tele.accel_long < 0.0)
            else:
                g = abs(tele.accel_long) * float(self.p("long_weight", 1.0)) \
                    + abs(tele.accel_lat) * float(self.p("lat_weight", 0.7))
                lvl = clamp(g / float(self.p("ref", 8.0)))
        self._level = lvl

    def render(self, n, tele):
        lvl = self._level if tele is not None else 0.0
        burst = float(self.p("burst_s", 0.0))
        if burst > 0.0:
            # HaptiConnect (Forza plugin): a fixed-length burst when the g level switches on, then silence
            now = tele.t if tele is not None else 0.0
            if not hasattr(self, "_burst_t0"):
                self._burst_t0, self._was_on = -1e9, False
            on = lvl > 0.05
            if on and not self._was_on:
                self._burst_t0 = now
            self._was_on = on
            lvl = 1.0 if (on and now - self._burst_t0 < burst) else 0.0
        self.level = lvl
        scale = 1.0 if (self.p("curve_long") or self.p("curve_lat")) else 0.6
        return self.tone.render(n, float(self.p("freq", 30.0)), lvl * self.gain * scale, self.p("harmonics"))


# The Trackmania-only effects live in effects/trackmania.py; re-exported so existing imports keep working.
from .trackmania import BoostEffect, GripMarginEffect, LandingEffect, SurfaceEffect  # noqa: E402,F401
