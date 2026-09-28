"""Trackmania-only effects: the grip-limit warning, surface textures, landings and boosts.

Trackmania is the only game that reports surfaces, airtime and boosts, so these are off in DEFAULTS
and on only in profiles/trackmania. openshaker.effects.racing re-exports them, so older imports work.
"""
from __future__ import annotations

import numpy as np

from .base import Effect, Noise, ThumpBank, Tone, clamp, mix
from .racing import _Triggered


class GripMarginEffect(Effect):
    """How close the car is to losing grip - felt BEFORE it slides.

    A pulsing tone that grows and pulses faster as the tyres approach the limit, then goes quiet the
    moment they actually let go so wheel_slip can take over. That hand-over is the point: the warning
    and the slide feel different, so the gap between them is something you can drive to.

    Trackmania: SlipCoef stays 0 while the tyres grip and only turns positive once sliding, so it
    cannot warn. The margin comes from what builds first - smoothed sideways acceleration against a
    limit (m/s^2) and the car's body slip angle against a limit (degrees) - and SlipCoef > 0 on any
    wheel is the hand-over. On tarmac the Stadium car turns as tight as its steering allows without
    ever letting go (measured: 90 m/s^2 sideways and still gripping), so it only warns on LOOSE
    surfaces - dirt, grass, sand, snow, ice, wet roads - where the car does slide out of a corner.
    `surfaces` {"Dirt": [lat_limit, slip_limit_deg], ...} adds to or overrides the built-in table
    (a limit of 0 switches a surface off); at least `min_share` of the wheels on the ground must be
    on listed surfaces, and the most common one sets the limits. `materials` {"<id>": "Dirt"} renames
    a material id as the surface effect's does (tm_tune --name writes both). A frame without
    per-wheel surfaces falls back to `lat_limit` / `slip_limit_deg` everywhere. Other games already normalise slip so
    that 1.0 is roughly the limit, so there the margin is simply the largest |slip_angle| or |slip_ratio|.

    `onset`..`full` shape the margin into 0..1; `curve_pow` makes the last stretch louder.
    """

    name = "grip_margin"

    LOOSE = {
        # surface: (sideways-accel limit m/s^2, body-slip limit degrees) - first guesses on the Stadium
        # car, to be replaced per surface by `python -m openshaker.tm_grip <drive> --apply`
        "Dirt": (18.0, 5.0), "DirtRoad": (18.0, 5.0), "WetDirtRoad": (15.0, 5.0), "Gravel": (18.0, 5.0),
        "Sand": (15.0, 5.0), "Grass": (14.0, 5.0), "Green": (14.0, 5.0), "WetGrass": (12.0, 5.0),
        "Forest": (14.0, 5.0), "Wheat": (14.0, 5.0), "Snow": (10.0, 5.0),
        "Ice": (6.0, 4.0), "RoadIce": (6.0, 4.0), "WetAsphalt": (30.0, 5.0), "WetPavement": (30.0, 5.0),
    }

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.tone = Tone(sr)
        self._margin = 0.0
        self._lat = 0.0
        self._lfo = 0.0
        self.limits = dict(self.LOOSE)
        for surface, spec in (self.p("surfaces") or {}).items():
            try:
                lat, slip = (float(x) for x in spec)
            except (TypeError, ValueError):
                continue
            if lat > 0.0 and slip > 0.0:
                self.limits[surface] = (lat, slip)
            else:
                self.limits.pop(surface, None)
        self.renames = {}
        for key, name in (self.p("materials") or {}).items():
            try:
                self.renames[int(key)] = str(name)
            except (TypeError, ValueError):
                continue

    def limits_for(self, extra: dict):
        """(lat_limit, slip_limit_deg) under the car, or None on grippy ground; the fallback pair when
        the frame has no per-wheel surfaces."""
        names = extra.get("surfaces")
        if not names:
            return float(self.p("lat_limit", 20.0)), float(self.p("slip_limit_deg", 6.0))
        if self.renames:                                  # the same id -> name fixes the surface effect uses
            ids = extra.get("materials") or []
            names = [self.renames.get(m, n) for m, n in zip(ids, names)] + list(names[len(ids):])
        contact = extra.get("wheel_contact") or [True] * len(names)
        on_ground = [n for n, c in zip(names, contact) if c]
        loose = [n for n in on_ground if n in self.limits]
        if not loose or len(loose) < float(self.p("min_share", 0.5)) * len(on_ground):
            return None
        counts = {n: loose.count(n) for n in loose}
        top = max(counts.values())
        return min((self.limits[n] for n, c in counts.items() if c == top), key=lambda lim: lim[0])

    def margin_from(self, tele) -> float:
        extra = getattr(tele, "extra", None) or {}
        if "slip_coef" in extra:
            if self.p("handover", True) and any(c > 0.0 for c in extra.get("slip_coef", ())):
                self._lat = 0.0
                return 0.0                                    # already sliding: wheel_slip speaks now
            self._lat += (abs(tele.accel_lat) - self._lat) * float(self.p("smooth", 0.15))
            limits = self.limits_for(extra)
            if limits is None:
                return 0.0                                    # grippy ground: nothing to warn about
            lat = self._lat / max(limits[0], 1e-6)
            body = abs(float(extra.get("body_slip_deg", 0.0))) / max(limits[1], 1e-6)
            return max(lat, body)
        worst = max([abs(x) for x in tele.slip_angle] + [abs(x) for x in tele.slip_ratio] + [0.0])
        if self.p("handover", True) and worst >= float(self.p("full", 1.0)):
            return 0.0
        return worst

    def on_frame(self, tele, prev, dt):
        m = 0.0
        if tele.active and tele.speed > float(self.p("min_speed", 8.0)):
            m = self.margin_from(tele)
        onset, full = float(self.p("onset", 0.6)), float(self.p("full", 1.0))
        self._margin = clamp((m - onset) / max(full - onset, 1e-6))

    def render(self, n, tele):
        margin = self._margin if tele is not None else 0.0
        self.level = margin
        if margin <= 0.0 and self.tone.amp.value <= 0.0:
            return None
        lo, hi = float(self.p("pulse_min_hz", 4.0)), float(self.p("pulse_max_hz", 14.0))
        rate = lo + (hi - lo) * margin
        ph = self._lfo + 2.0 * np.pi * rate * np.arange(1, n + 1) / self.sr
        self._lfo = float(ph[-1] % (2.0 * np.pi))
        depth = float(self.p("pulse_depth", 0.7))
        envelope = (1.0 - depth) + depth * 0.5 * (1.0 + np.sin(ph))
        amp = (margin ** float(self.p("curve_pow", 1.5))) * self.gain
        y = self.tone.render(n, float(self.p("freq", 55.0)), amp)
        return (y * envelope).astype(np.float32)


class SurfaceEffect(Effect):
    """What the tyres are running on - dirt, grass, ice, plastic, metal - plus water and roof scrapes.

    Trackmania reports a surface material per wheel, so each gets its own texture: band-limited noise
    at a surface-specific cutoff and level, plus an optional tone for resonant surfaces. The level grows
    with speed and stops when the wheels leave the ground. Water adds a slow slosh and a splash on the
    way in; sliding on the roof adds a harsh scrape. Games without per-wheel materials feel nothing.

    Material names come from Openplanet's own EPlugSurfaceMaterialId table. A profile can still rename
    an id with `materials` {"<id>": "Dirt", ...} and retune any surface with
    `textures` {"Dirt": [noise_cutoff_hz, noise_level, tone_hz, tone_level], ...}.
    """

    name = "surface"

    TEXTURES = {
        # name: (noise cutoff Hz, noise level, tone Hz, tone level) - first guesses, tunable per profile
        # smooth roads add nothing: the engine and the suspension already carry them
        "Asphalt": (60.0, 0.0, 0.0, 0.0), "WetAsphalt": (60.0, 0.0, 0.0, 0.0), "Tech": (60.0, 0.0, 0.0, 0.0),
        "TechGround": (60.0, 0.0, 0.0, 0.0), "TechSafe": (60.0, 0.0, 0.0, 0.0), "TechArmor": (60.0, 0.02, 0.0, 0.0),
        "Concrete": (60.0, 0.03, 0.0, 0.0), "RoadSynthetic": (55.0, 0.05, 0.0, 0.0),
        "Pavement": (55.0, 0.06, 0.0, 0.0), "WetPavement": (55.0, 0.05, 0.0, 0.0), "PavementStair": (40.0, 0.3, 0.0, 0.0),
        # loose and rough
        "Dirt": (35.0, 0.55, 0.0, 0.0), "DirtRoad": (35.0, 0.5, 0.0, 0.0), "WetDirtRoad": (30.0, 0.5, 0.0, 0.0),
        "Gravel": (45.0, 0.6, 0.0, 0.0), "Sand": (28.0, 0.45, 0.0, 0.0), "Rock": (50.0, 0.5, 0.0, 0.0),
        "Stone": (50.0, 0.45, 0.0, 0.0),
        # soft
        "Grass": (22.0, 0.4, 0.0, 0.0), "Green": (22.0, 0.4, 0.0, 0.0), "WetGrass": (20.0, 0.35, 0.0, 0.0),
        "Forest": (25.0, 0.45, 0.0, 0.0), "Wheat": (20.0, 0.3, 0.0, 0.0),
        # slick
        "Ice": (70.0, 0.05, 0.0, 0.0), "RoadIce": (70.0, 0.04, 0.0, 0.0), "Snow": (40.0, 0.15, 0.0, 0.0),
        # buzzy and resonant
        "Plastic": (50.0, 0.15, 62.0, 0.3), "Rubber": (45.0, 0.2, 55.0, 0.3), "SlidingRubber": (45.0, 0.2, 55.0, 0.25),
        "RubberBand": (45.0, 0.2, 58.0, 0.3),
        "Metal": (60.0, 0.1, 48.0, 0.3), "ResonantMetal": (60.0, 0.1, 44.0, 0.4), "MetalTrans": (60.0, 0.08, 50.0, 0.25),
        "MetalFence": (60.0, 0.15, 46.0, 0.35), "TechMagnetic": (60.0, 0.03, 70.0, 0.15),
        "TechSuperMagnetic": (60.0, 0.03, 70.0, 0.2), "TechMagneticAccel": (60.0, 0.03, 70.0, 0.2),
        "Wood": (45.0, 0.3, 0.0, 0.0), "SlidingWood": (45.0, 0.25, 0.0, 0.0),
    }

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.noise = Noise(sr, 40.0, seed=21)
        self.tone = Tone(sr)
        self.water = Noise(sr, float(self.p("water_cutoff", 18.0)), seed=22)
        self.scrape = Noise(sr, float(self.p("scrape_cutoff", 85.0)), seed=23)
        self.splash = ThumpBank(sr)
        self._noise_amp = self._tone_amp = self._water_amp = self._scrape_amp = 0.0
        self._tone_hz, self._cutoff = 50.0, 40.0
        self._was_wet = False
        self.textures = dict(self.TEXTURES)
        for surface, spec in (self.p("textures") or {}).items():
            self.textures[surface] = tuple(float(x) for x in spec)
        self.names = {int(k): v for k, v in (self.p("materials") or {}).items()}

    def texture_for(self, material: int, guess: str):
        return self.textures.get(self.names.get(material, guess))

    def on_frame(self, tele, prev, dt):
        noise = tone = water = scrape = 0.0
        cutoff, tone_hz = self._cutoff, self._tone_hz
        extra = getattr(tele, "extra", None) or {}
        if tele.active and "materials" in extra:
            span = max(float(self.p("speed_full", 40.0)), 1e-6)
            speed = clamp((tele.speed - float(self.p("min_speed", 2.0))) / span) ** 0.8
            grounded = extra.get("ground_contact", True)
            contact = extra.get("wheel_contact") or []
            guesses = extra.get("surfaces") or []
            for i, material in enumerate(extra.get("materials", ())):
                on_ground = grounded and (i >= len(contact) or contact[i])
                if not on_ground or material < 0:
                    continue
                spec = self.texture_for(material, guesses[i] if i < len(guesses) else "")
                if spec is None:
                    continue
                c, level, t_hz, t_level = spec
                if level > noise:
                    noise, cutoff = level, c
                if t_level > tone:
                    tone, tone_hz = t_level, t_hz
            noise *= speed
            tone *= speed
            immersion = float(extra.get("water", 0.0))
            wet = immersion > 0.05
            if wet:
                water = clamp(immersion) * float(self.p("water_level", 0.5)) * max(speed, 0.2)
                if not self._was_wet and tele.speed > 5.0:
                    self.splash.trigger(float(self.p("splash_freq", 22.0)),
                                        clamp(tele.speed / 40.0) * float(self.p("splash_amp", 0.8)) * self.gain,
                                        float(self.p("splash_tau", 0.25)))
            self._was_wet = wet
            if extra.get("top_contact"):
                scrape = float(self.p("scrape_level", 0.5)) * max(speed, 0.3)
        if abs(cutoff - self._cutoff) > 0.5:
            self.noise.set_cutoff(cutoff)
            self._cutoff = cutoff
        self._noise_amp, self._tone_amp, self._tone_hz = noise, tone, tone_hz
        self._water_amp, self._scrape_amp = water, scrape

    def render(self, n, tele):
        live = 1.0 if tele is not None else 0.0
        g = self.gain * live
        y = mix(self.noise.render(n, self._noise_amp * g), self.tone.render(n, self._tone_hz, self._tone_amp * g),
                self.water.render(n, self._water_amp * g), self.scrape.render(n, self._scrape_amp * g),
                self.splash.render(n))
        self.level = max(live * max(self._noise_amp, self._tone_amp, self._water_amp, self._scrape_amp),
                         self.splash.level)
        return y


class LandingEffect(_Triggered):
    """A hit when the car comes back down after a jump, sized to how fast it was falling.

    Watches overall ground contact: once the car has been in the air for `min_air_s`, touching down
    fires a low thump (plus a short click for the edge of the impact) whose strength follows the
    fastest downward speed seen while airborne, between `v_min` and `v_full` m/s. Tiny hops over
    bumps and gentle touch-downs stay silent - the suspension effect covers those.
    """

    name = "landing"

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.click = ThumpBank(sr)
        self._air_since = None
        self._fall = 0.0

    def on_frame(self, tele, prev, dt):
        extra = getattr(tele, "extra", None) or {}
        if not tele.active or "ground_contact" not in extra:
            self._air_since, self._fall = None, 0.0
            return
        falling = -float(extra.get("vert_speed", 0.0))
        if not extra["ground_contact"]:
            if self._air_since is None:
                self._air_since, self._fall = tele.t, 0.0
            self._fall = max(self._fall, falling)
            return
        if self._air_since is None:
            return
        airtime, fall = tele.t - self._air_since, max(self._fall, falling)
        self._air_since, self._fall = None, 0.0
        v_min, v_full = float(self.p("v_min", 1.5)), float(self.p("v_full", 15.0))
        if airtime < float(self.p("min_air_s", 0.12)) or fall < v_min:
            return
        amp = max(clamp((fall - v_min) / max(v_full - v_min, 1e-6)) ** 0.7, 0.15)
        self.fire(float(self.p("freq", 30.0)), amp * self.gain, float(self.p("tau", 0.18)))
        click = float(self.p("click_amp", 0.35))
        if click > 0.0:
            self.click.trigger(float(self.p("click_freq", 60.0)), amp * click * self.gain, 0.03)

    def render(self, n, tele):
        y = mix(self.render_shots(n), self.click.render(n))
        self.level = max(self.level, self.click.level)
        return y


class BoostEffect(Effect):
    """Turbo pads and reactor boost: a surge when a boost starts, and a hum while it lasts.

    Driving over a turbo pad fires a thump and a rising sweep (`sweep_lo` -> `sweep_hi` Hz over
    `sweep_s`); the turbo itself keeps a light hum. A reactor boost fires a smaller surge and hums at
    `reactor_freq`, stronger at level 2. A boost held on does not retrigger.
    """

    name = "boost"

    def __init__(self, cfg, sr):
        super().__init__(cfg, sr)
        self.surge = ThumpBank(sr)
        self.sweep = Tone(sr)
        self.hum = Tone(sr)
        self._sweep_left = 0.0
        self._was_turbo = False
        self._was_reactor = 0
        self._hum = 0.0

    def on_frame(self, tele, prev, dt):
        extra = getattr(tele, "extra", None) or {}
        turbo = bool(extra.get("turbo")) and tele.active
        reactor = int(extra.get("reactor_level", 0)) if tele.active else 0
        surge_freq, surge_tau = float(self.p("surge_freq", 42.0)), float(self.p("surge_tau", 0.25))
        if turbo and not self._was_turbo:
            self.surge.trigger(surge_freq, self.gain, surge_tau)
            self._sweep_left = float(self.p("sweep_s", 0.6))
        if reactor > self._was_reactor:
            self.surge.trigger(surge_freq, 0.7 * self.gain, surge_tau)
        self._was_turbo, self._was_reactor = turbo, reactor
        hum = float(self.p("turbo_hum", 0.25)) if turbo else 0.0
        if reactor > 0:
            hum = max(hum, float(self.p("reactor_amp", 0.4)) * min(reactor, 2) / 2.0)
        self._hum = hum

    def render(self, n, tele):
        live = tele is not None
        sweep_s = max(float(self.p("sweep_s", 0.6)), 1e-6)
        lo, hi = float(self.p("sweep_lo", 35.0)), float(self.p("sweep_hi", 75.0))
        sweep = None
        if self._sweep_left > 0.0 and live:
            k = 1.0 - self._sweep_left / sweep_s
            sweep = self.sweep.render(n, lo + (hi - lo) * k, (1.0 - k) * 0.6 * self.gain)
            self._sweep_left = max(0.0, self._sweep_left - n / self.sr)
        elif self.sweep.amp.value > 0.0:
            sweep = self.sweep.render(n, hi, 0.0)
        hum = self.hum.render(n, float(self.p("reactor_freq", 34.0)), self._hum * self.gain if live else 0.0)
        y = mix(self.surge.render(n), sweep, hum)
        self.level = max(self.surge.level, self._hum if live else 0.0, 0.6 * self._sweep_left / sweep_s)
        return y
