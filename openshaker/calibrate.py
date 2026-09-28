"""Automatic calibration against HaptiConnect, no driving required (or with a real game).

For each effect it: sets the chosen HaptiConnect game profile to that single effect at full strength,
restarts HaptiConnect, feeds it telemetry in the packet format that plugin expects (clean synthetic
sequences, or a live game bridged through), records what HaptiConnect plays to the ButtKicker
(WASAPI loopback) together with the telemetry, and learns the effect with openshaker.analyze.
Finally it merges everything into one profile and restores the original HaptiConnect profile.

  python -m openshaker.calibrate all                      # HaptiConnect's BeamNG plugin (6 effects)
  python -m openshaker.calibrate --plugin fh5 all         # Forza Horizon 5 plugin (9 effects; FH5 must be
                                                         #   running, its main menu is enough)
  python -m openshaker.calibrate --plugin fh5 --game ace all   # drive Assetto Corsa EVO, bridged as FH5
  python -m openshaker.calibrate --reanalyze all          # re-learn recorded sessions only
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from .analyze import analyze
from .config import portable_path
from .forward import TelemetryForwarder
from .record import CSV_FIELDS, LoopbackRecorder, TelemetryLog, tele_row, write_wav
from .sources.base import Source
from .sources.beamng import BeamNGSource
from .telemetry import Telemetry

PROJECT_DIR = Path(__file__).resolve().parent.parent
# HaptiConnect's default install folder; OPENSHAKER_HC_EXE points the calibration tools at another copy
HC_EXE = Path(os.environ.get("OPENSHAKER_HC_EXE") or r"C:\Program Files\ButtKicker\connect\bk-connect.exe")
HC_MISSING = (f"HaptiConnect was not found at {HC_EXE}. The calibration tools drive HaptiConnect, so it "
              "has to be installed; set OPENSHAKER_HC_EXE to its bk-connect.exe if it lives elsewhere.")
HC_GAMES = Path(os.environ.get("APPDATA", "")) / "Guitammer" / "HaptiConnect" / "Games"
HC_LOGS = Path(os.environ.get("LOCALAPPDATA", "")) / "Guitammer" / "HaptiConnect" / "logs"
MAX_RPM, IDLE = 8000.0, 900.0

FORZA_KEYS = {"rpm": "RPMs", "rumble": "Rumble%20Strips", "shift": "Gear%20Shift", "accel": "Acceleration",
              "collision": "Collisions", "suspension": "Suspension", "lock": "Wheels%20Lock",
              "slip": "Wheels%20Slip", "shift_indicator": "Shift%20Indicator%20Warning"}
PLUGINS = {
    "beamng": {"game": "BeamNG.drive", "port": 4444, "fmt": "outgauge", "process": None,
               "keys": {"rpm": "RPMs", "shift": "Gear%20Shift", "accel": "Acceleration",
                        "collision": "Collisions", "suspension": "Suspension", "lock": "Wheels%20Lock"}},
    "fh5": {"game": "Forza Horizon 5", "port": 5301, "fmt": "horizon", "process": "ForzaHorizon5",
            "keys": FORZA_KEYS},
    # measured: HaptiConnect's Motorsport plugin decodes the packet tail (gear, pedals) at the HORIZON offsets,
    # so feed it the 324-byte Horizon layout; the 331-byte Motorsport layout only drives the sled fields
    "fm": {"game": "Forza Motorsport", "port": 5305, "fmt": "horizon", "process": "forza_",
           "keys": FORZA_KEYS},
}
# effect name used by this app's engine for each calibration effect
APP_EFFECT = {"rpm": "engine", "shift": "gear_shift", "accel": "acceleration", "collision": "impact",
              "suspension": "suspension", "lock": "wheel_lock", "slip": "wheel_slip", "rumble": "road",
              "shift_indicator": "shift_indicator"}
ORDER = ["rpm", "shift", "accel", "collision", "suspension", "lock", "slip", "rumble", "shift_indicator"]


# ------------------------------------------------------------------ stimulus sequences
def _base(t: float) -> Telemetry:
    return Telemetry(active=True, engine_running=True, rpm=3000.0, max_rpm=MAX_RPM, idle_rpm=IDLE, gear=3,
                     speed=20.0, throttle=0.3, susp_travel=[0.5, 0.5, 0.5, 0.5], cylinders=6)


def stim_rpm(t: float):
    """Idle, then a slow sweep up/down at closed throttle, then the same at full throttle."""
    up, down = 30.0, 15.0
    cycle = up + down + 2.0
    if t >= 3.0 + 2 * cycle:
        return None
    tele = _base(t)
    if t < 3.0:
        tele.rpm, tele.throttle = IDLE + 30 * math.sin(t * 5), 0.0
    else:
        u = (t - 3.0) % cycle
        tele.throttle = 0.0 if (t - 3.0) < cycle else 1.0
        frac = u / up if u < up else 1.0 if u < up + 2.0 else max(0.0, 1.0 - (u - up - 2.0) / down)
        tele.rpm = IDLE + (MAX_RPM - IDLE) * frac
    tele.speed = 5.0 + 40.0 * (tele.rpm / MAX_RPM)
    return tele


def stim_shift(t: float):
    """Constant rpm; a gear change every 2.5 s: 1..6 up, then back down, twice."""
    if t >= 3.0 + 2.5 * 24:
        return None
    tele = _base(t)
    tele.rpm, tele.throttle, tele.speed = 4000.0, 0.5, 25.0
    k = int(max(t - 3.0, 0.0) // 2.5)
    cyc = k % 12
    tele.gear = 1 + cyc if cyc < 6 else 12 - cyc
    return tele


def stim_accel(t: float):
    """Longitudinal g steps (drive, then brake), then lateral steps."""
    steps = [0, 2, 4, 6, 8, 10, 0, -2, -4, -6, -8, -10, 0]
    lat = [0, 2, 4, 6, 8, 0]
    hold = 4.0
    n1 = len(steps) * hold
    if t >= n1 + len(lat) * hold:
        return None
    tele = _base(t)
    tele.rpm, tele.speed = 3500.0, 25.0
    if t < n1:
        a = steps[int(t // hold)]
        tele.accel_long = float(a)
        tele.throttle = 0.8 if a > 0 else 0.1
        tele.brake = 0.8 if a < 0 else 0.0
    else:
        tele.accel_lat = float(lat[int((t - n1) // hold)])
    return tele


# collision variants: (label, frames of g-spike, g magnitude m/s^2, speed after (None = unchanged))
COLLISION_VARIANTS = [
    ("g1f_100", 1, 100.0, None), ("g3f_100", 3, 100.0, None), ("g10f_100", 10, 100.0, None),
    ("v20to10", 0, 0.0, 10.0), ("v20to10_g3f_100", 3, 100.0, 10.0), ("v20to0_g3f_200", 3, 200.0, 0.0),
    ("g3f_40", 3, 40.0, None), ("v20to15", 0, 0.0, 15.0), ("g3f_100_lat", 3, 100.0, None),
    ("g1f_100", 1, 100.0, None), ("v20to10_g3f_100", 3, 100.0, 10.0), ("v20to0_g3f_200", 3, 200.0, 0.0),
]


def stim_collision(t: float):
    """Cruise at 20 m/s; every 4 s one impact variant (g-spike length / speed drop combinations)."""
    gap = 4.0
    if t >= 3.0 + gap * len(COLLISION_VARIANTS) + 2.0:
        return None
    tele = _base(t)
    tele.rpm, tele.speed, tele.throttle = 3000.0, 20.0, 0.3
    k = int((t - 3.0) // gap) if t >= 3.0 else -1
    if 0 <= k < len(COLLISION_VARIANTS):
        label, frames, g, v_after = COLLISION_VARIANTS[k]
        phase = (t - 3.0) - k * gap
        if 0.0 <= phase < frames / 60.0 + 1e-6 and frames > 0:
            if "lat" in label:
                tele.accel_lat = g
            else:
                tele.accel_long = -g
        if v_after is not None and phase >= 0.0:
            # speed drops instantly and recovers over the next 2 s
            tele.speed = v_after + (20.0 - v_after) * min(phase / 2.0, 1.0)
    return tele


def stim_suspension(t: float):
    """Per-wheel bumps of growing size (also mirrored into vertical g for the BeamNG plugin),
    then sustained road texture at three levels."""
    sizes = [0.1, 0.2, 0.3, 0.4, 0.3, 0.3, 0.3, 0.3]
    wheels = [0, 1, 2, 3, 0, 1, 2, 3]
    gap, width = 3.0, 0.10
    n1 = 3.0 + gap * len(sizes)
    tex_levels = [0.02, 0.05, 0.10]
    tex_hold = 8.0
    if t >= n1 + tex_hold * len(tex_levels) + 2.0:
        return None
    tele = _base(t)
    tele.rpm, tele.speed, tele.throttle = 3000.0, 20.0, 0.3
    if t < n1:
        k = int((t - 3.0) // gap) if t >= 3.0 else -1
        if 0 <= k < len(sizes):
            phase = (t - 3.0) - k * gap
            if 0.0 <= phase < width:
                s = math.sin(math.pi * phase / width)
                tele.susp_travel[wheels[k]] = 0.5 + sizes[k] * s
                tele.accel_vert = sizes[k] * 80.0 * s
    else:
        lvl = tex_levels[min(int((t - n1) // tex_hold), len(tex_levels) - 1)]
        rng = np.random.default_rng(int(t * 60))
        noise = rng.standard_normal(4)
        tele.susp_travel = [float(0.5 + lvl * n) for n in noise]
        tele.accel_vert = float(lvl * 40.0 * noise[0])
    return tele


def stim_lock(t: float):
    """Braking with increasing front-wheel lock (normalized slip -0.7, -1.5, -3, -6), 4 s on / 3 s off, twice."""
    levels = [-0.7, -1.5, -3.0, -6.0, -0.7, -1.5, -3.0, -6.0]
    on, off = 4.0, 3.0
    if t >= 3.0 + (on + off) * len(levels):
        return None
    tele = _base(t)
    tele.rpm, tele.speed, tele.throttle = 2500.0, 25.0, 0.0
    k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
    if 0 <= k < len(levels) and ((t - 3.0) - k * (on + off)) < on:
        tele.brake = 1.0
        tele.accel_long = -8.0
        tele.slip_ratio = [levels[k], levels[k], levels[k] * 0.3, levels[k] * 0.3]
    return tele


def stim_slip(t: float):
    """Wheelspin on the rear wheels at growing slip ratio, then lateral slides at growing slip angle."""
    spins = [0.5, 1.0, 2.0, 4.0, 1.0, 2.0]
    slides = [0.5, 1.0, 2.0, 3.0, 1.0, 2.0]
    on, off = 3.0, 2.0
    n1 = 3.0 + (on + off) * len(spins)
    if t >= n1 + (on + off) * len(slides):
        return None
    tele = _base(t)
    tele.rpm, tele.speed = 5000.0, 20.0
    if t < n1:
        k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
        tele.throttle = 1.0
        if 0 <= k < len(spins) and ((t - 3.0) - k * (on + off)) < on:
            tele.slip_ratio = [0.05, 0.05, spins[k], spins[k]]
    else:
        k = int((t - n1) // (on + off))
        tele.throttle, tele.speed = 0.5, 28.0
        if 0 <= k < len(slides) and ((t - n1) - k * (on + off)) < on:
            tele.slip_angle = [slides[k]] * 4
            tele.accel_lat = 6.0
    return tele


def stim_rumble(t: float):
    """Rumble strips under right wheels, all wheels, left wheels at two speeds; then rough surface levels."""
    pattern = [([False, True, False, True], 15.0), ([True, True, True, True], 15.0), ([True, False, True, False], 15.0),
               ([False, True, False, True], 35.0), ([True, True, True, True], 35.0), ([True, False, True, False], 35.0)]
    on, off = 3.0, 2.0
    n1 = 3.0 + (on + off) * len(pattern)
    surf = [0.25, 0.5, 1.0]
    hold = 5.0
    if t >= n1 + hold * len(surf) + 2.0:
        return None
    tele = _base(t)
    tele.rpm, tele.throttle = 3500.0, 0.4
    if t < n1:
        k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
        if 0 <= k < len(pattern):
            flags, speed = pattern[k]
            tele.speed = speed
            if ((t - 3.0) - k * (on + off)) < on:
                tele.rumble_strip = list(flags)
    else:
        tele.speed = 25.0
        lvl = surf[min(int((t - n1) // hold), len(surf) - 1)]
        tele.surface_rumble = [lvl] * 4
    return tele


def stim_shift_indicator(t: float):
    """Full-throttle pulls to 97% of max rpm held 3 s, three times, then partial pulls to 85%."""
    seq = [0.97, 0.97, 0.97, 0.85, 0.92, 0.99]
    cycle = 7.0
    if t >= 3.0 + cycle * len(seq):
        return None
    tele = _base(t)
    tele.throttle, tele.gear = 1.0, 3
    k = int((t - 3.0) // cycle) if t >= 3.0 else -1
    if k < 0:
        tele.rpm = 3000.0
    else:
        phase = (t - 3.0) - k * cycle
        top = seq[k] * MAX_RPM
        tele.rpm = 3000.0 + (top - 3000.0) * min(phase / 3.0, 1.0) if phase < 6.0 else 3000.0
    tele.speed = 10.0 + 30.0 * tele.rpm / MAX_RPM
    return tele


# ---- probe sequences: same HaptiConnect effect, questions about its detector -------------------
COLLISION_PROBE = [  # (label, frames, g, axis)
    ("g10f_5", 10, 5.0, "long"), ("g10f_10", 10, 10.0, "long"), ("g10f_15", 10, 15.0, "long"),
    ("g10f_20", 10, 20.0, "long"), ("g10f_30", 10, 30.0, "long"), ("g10f_40", 10, 40.0, "long"),
    ("g6f_40", 6, 40.0, "long"), ("g4f_40", 4, 40.0, "long"), ("g2f_40", 2, 40.0, "long"),
    ("g10f_40_vert", 10, 40.0, "vert"), ("g10f_40_lat", 10, 40.0, "lat"), ("g10f_+40", 10, -40.0, "long"),
    ("g120f_40_sustained", 120, 40.0, "long"), ("g10f_40", 10, 40.0, "long"),
]


def stim_collision_probe(t: float):
    """Threshold, duration, axis and sign of HaptiConnect's collision detector; 4 s apart."""
    gap = 4.0
    if t >= 3.0 + gap * len(COLLISION_PROBE) + 2.0:
        return None
    tele = _base(t)
    tele.rpm, tele.speed, tele.throttle = 3000.0, 20.0, 0.3
    k = int((t - 3.0) // gap) if t >= 3.0 else -1
    if 0 <= k < len(COLLISION_PROBE):
        label, frames, g, axis = COLLISION_PROBE[k]
        phase = (t - 3.0) - k * gap
        if 0.0 <= phase < frames / 60.0 + 1e-6:
            if axis == "long":
                tele.accel_long = -g
            elif axis == "lat":
                tele.accel_lat = g
            else:
                tele.accel_vert = g
    return tele


SUSP_PROBE = [  # (label, size m/s^2, channel: both|v1|v2, width s)
    ("both_2", 2.0, "both", 0.10), ("both_5", 5.0, "both", 0.10), ("both_10", 10.0, "both", 0.10),
    ("both_20", 20.0, "both", 0.10), ("both_30", 30.0, "both", 0.10), ("both_40", 40.0, "both", 0.10),
    ("both_60", 60.0, "both", 0.10), ("v1_20", 20.0, "v1", 0.10), ("v2_20", 20.0, "v2", 0.10),
    ("v1_40", 40.0, "v1", 0.10), ("v2_40", 40.0, "v2", 0.10), ("both_20_wide", 20.0, "both", 0.40),
    ("both_20_1frame", 20.0, "both", 1.0 / 60.0), ("both_-20", -20.0, "both", 0.10), ("both_20", 20.0, "both", 0.10),
]

ACCEL_PROBE = [  # (label, long m/s^2, lat m/s^2), 3 s on / 1.5 s off
    ("+8", 8, 0), ("+10", 10, 0), ("+12", 12, 0), ("+15", 15, 0), ("+20", 20, 0),
    ("-3", -3, 0), ("-4", -4, 0), ("-5", -5, 0), ("-6", -6, 0), ("-7", -7, 0),
    ("lat6", 0, 6), ("lat8", 0, 8), ("lat10", 0, 10), ("lat12", 0, 12), ("lat15", 0, 15), ("lat-10", 0, -10),
    ("-5_lat5", -5, 5),
]


def stim_accel_probe(t: float):
    """Finer g steps around the thresholds seen in the first sweep, both signs and lateral."""
    on, off = 3.0, 1.5
    if t >= 3.0 + (on + off) * len(ACCEL_PROBE):
        return None
    tele = _base(t)
    tele.rpm, tele.speed, tele.throttle = 3500.0, 25.0, 0.3
    k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
    if 0 <= k < len(ACCEL_PROBE) and ((t - 3.0) - k * (on + off)) < on:
        _, lon, lat = ACCEL_PROBE[k]
        tele.accel_long, tele.accel_lat = float(lon), float(lat)
        tele.throttle = 0.8 if lon > 0 else 0.3
        tele.brake = 0.8 if lon < 0 else 0.0
    return tele


def stim_suspension_probe(t: float):
    """Which vertical channel drives the suspension effect, how level scales, and pulse width."""
    gap = 3.0
    if t >= 3.0 + gap * len(SUSP_PROBE) + 2.0:
        return None
    tele = _base(t)
    tele.rpm, tele.speed, tele.throttle = 3000.0, 20.0, 0.3
    k = int((t - 3.0) // gap) if t >= 3.0 else -1
    if 0 <= k < len(SUSP_PROBE):
        label, size, chan, width = SUSP_PROBE[k]
        phase = (t - 3.0) - k * gap
        if 0.0 <= phase < width:
            s = size * math.sin(math.pi * phase / width) if width > 0.02 else size
            if chan in ("both", "v1"):
                tele.accel_vert = s
            tele.accel_vert2 = s if chan in ("both", "v2") else 0.0
        else:
            tele.accel_vert2 = 0.0
    else:
        tele.accel_vert2 = 0.0
    return tele


LOCK_PROBE = [  # (label, slip, brake, speed)
    ("s-0.3_b1", -0.3, 1.0, 25.0), ("s-0.7_b1", -0.7, 1.0, 25.0), ("s-1.5_b1", -1.5, 1.0, 25.0),
    ("s-3_b1", -3.0, 1.0, 25.0), ("s-6.7_b1", -6.7, 1.0, 25.0), ("s-3_b0", -3.0, 0.0, 25.0),
    ("s-3_b1_v8", -3.0, 1.0, 8.0), ("s-3_b1_v50", -3.0, 1.0, 50.0), ("s+3_b1", 3.0, 1.0, 25.0),
]


def stim_lock_probe(t: float):
    """Lock level scaling, brake dependence, speed dependence, and wheelspin (positive slip) under brake."""
    on, off = 3.0, 2.0
    if t >= 3.0 + (on + off) * len(LOCK_PROBE):
        return None
    tele = _base(t)
    tele.rpm, tele.throttle = 2500.0, 0.0
    k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
    if 0 <= k < len(LOCK_PROBE):
        label, slip, brake, speed = LOCK_PROBE[k]
        tele.speed = speed
        if ((t - 3.0) - k * (on + off)) < on:
            tele.brake = brake
            tele.slip_ratio = [slip] * 4
    return tele


# ---- Forza-plugin probes (rich packet fields) --------------------------------------------------
RUMBLE_PROBE = [  # (label, wheel flags FL FR RL RR, speed, surface rumble)
    ("all4_v10", [1, 1, 1, 1], 10.0, 0.0), ("all4_v20", [1, 1, 1, 1], 20.0, 0.0), ("all4_v25", [1, 1, 1, 1], 25.0, 0.0),
    ("all4_v30", [1, 1, 1, 1], 30.0, 0.0), ("all4_v40", [1, 1, 1, 1], 40.0, 0.0), ("right_v35", [0, 1, 0, 1], 35.0, 0.0),
    ("left_v35", [1, 0, 1, 0], 35.0, 0.0), ("front_v35", [1, 1, 0, 0], 35.0, 0.0), ("rear_v35", [0, 0, 1, 1], 35.0, 0.0),
    ("FL_v35", [1, 0, 0, 0], 35.0, 0.0), ("surface1_v35", [0, 0, 0, 0], 35.0, 1.0), ("surface0.5_v35", [0, 0, 0, 0], 35.0, 0.5),
    ("all4+surf_v35", [1, 1, 1, 1], 35.0, 1.0), ("all4_v35", [1, 1, 1, 1], 35.0, 0.0),
]


def stim_rumble_probe(t: float):
    on, off = 4.0, 2.0
    if t >= 3.0 + (on + off) * len(RUMBLE_PROBE):
        return None
    tele = _base(t)
    tele.rpm, tele.throttle, tele.speed = 3500.0, 0.4, 35.0
    k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
    if 0 <= k < len(RUMBLE_PROBE):
        _, flags, speed, surf = RUMBLE_PROBE[k]
        tele.speed = speed
        if ((t - 3.0) - k * (on + off)) < on:
            tele.rumble_strip = [bool(f) for f in flags]
            tele.surface_rumble = [surf] * 4
    return tele


RUMBLE2_PROBE = [  # (label, wheel flags FL FR RL RR, speed m/s, SurfaceRumble magnitude)  real strips: flag + 1.5-2.6
    ("flag_s1.2_v20", [1, 0, 0, 0], 20.0, 1.2), ("flag_s1.5_v20", [1, 0, 0, 0], 20.0, 1.5),
    ("flag_s1.8_v20", [1, 0, 0, 0], 20.0, 1.8), ("flag_s2.6_v20", [1, 0, 0, 0], 20.0, 2.6),
    ("noflag_s1.8_v20", [0, 0, 0, 0], 20.0, 1.8), ("flag_s0_v20", [1, 0, 0, 0], 20.0, 0.0),
    ("flag_s1.8_v5", [1, 0, 0, 0], 5.0, 1.8), ("flag_s1.8_v10", [1, 0, 0, 0], 10.0, 1.8),
    ("flag_s1.8_v15", [1, 0, 0, 0], 15.0, 1.8), ("flag_s1.8_v25", [1, 0, 0, 0], 25.0, 1.8),
    ("flag_s1.8_v35", [1, 0, 0, 0], 35.0, 1.8), ("flag_s1.8_v50", [1, 0, 0, 0], 50.0, 1.8),
    ("right_s1.8_v20", [0, 1, 0, 1], 20.0, 1.8), ("all4_s1.8_v20", [1, 1, 1, 1], 20.0, 1.8),
]


def stim_rumble_probe2(t: float):
    on, off = 3.0, 1.5
    if t >= 3.0 + (on + off) * len(RUMBLE2_PROBE):
        return None
    tele = _base(t)
    tele.rpm, tele.throttle, tele.speed = 3500.0, 0.4, 20.0
    k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
    if 0 <= k < len(RUMBLE2_PROBE):
        _, flags, speed, surf = RUMBLE2_PROBE[k]
        tele.speed = speed
        if ((t - 3.0) - k * (on + off)) < on:
            tele.rumble_strip = [bool(f) for f in flags]
            tele.surface_rumble = [surf if f else 0.0 for f in flags] if any(flags) else [surf] * 4
    return tele


SLIP_PROBE = [  # (label, slip ratio [FL FR RL RR], slip angle all, throttle, lat g)
    ("rear0.3", [0, 0, 0.3, 0.3], 0.0, 1.0, 0.0), ("rear0.6", [0, 0, 0.6, 0.6], 0.0, 1.0, 0.0),
    ("rear1.0", [0, 0, 1.0, 1.0], 0.0, 1.0, 0.0), ("rear1.5", [0, 0, 1.5, 1.5], 0.0, 1.0, 0.0),
    ("rear3.0", [0, 0, 3.0, 3.0], 0.0, 1.0, 0.0), ("rear6.0", [0, 0, 6.0, 6.0], 0.0, 1.0, 0.0),
    ("front1.5", [1.5, 1.5, 0, 0], 0.0, 1.0, 0.0), ("all1.5", [1.5] * 4, 0.0, 1.0, 0.0),
    ("rear1.5_thr0", [0, 0, 1.5, 1.5], 0.0, 0.0, 0.0), ("angle0.3", [0] * 4, 0.3, 0.3, 6.0),
    ("angle0.6", [0] * 4, 0.6, 0.3, 6.0), ("angle1.0", [0] * 4, 1.0, 0.3, 6.0), ("angle2.0", [0] * 4, 2.0, 0.3, 6.0),
    ("rear1.5", [0, 0, 1.5, 1.5], 0.0, 1.0, 0.0),
]


def stim_slip_probe(t: float):
    on, off = 4.0, 2.0
    if t >= 3.0 + (on + off) * len(SLIP_PROBE):
        return None
    tele = _base(t)
    tele.rpm, tele.speed, tele.throttle = 5000.0, 22.0, 0.3
    k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
    if 0 <= k < len(SLIP_PROBE):
        _, ratios, angle, thr, lat = SLIP_PROBE[k]
        tele.throttle = thr
        if ((t - 3.0) - k * (on + off)) < on:
            tele.slip_ratio = [float(r) for r in ratios]
            tele.slip_angle = [angle] * 4
            tele.accel_lat = lat
    return tele


SHIFTIND_PROBE = [  # (label, rpm fraction of max, throttle, gear change mid-hold)
    ("90%", 0.90, 1.0, False), ("95%", 0.95, 1.0, False), ("98%", 0.98, 1.0, False), ("100%", 1.00, 1.0, False),
    ("103%", 1.03, 1.0, False), ("100%_thr0", 1.00, 0.0, False), ("100%_shift", 1.00, 1.0, True), ("98%", 0.98, 1.0, False),
]


def stim_shift_indicator_probe(t: float):
    on, off = 4.0, 2.0
    if t >= 3.0 + (on + off) * len(SHIFTIND_PROBE):
        return None
    tele = _base(t)
    tele.rpm, tele.throttle, tele.speed, tele.gear = 3000.0, 1.0, 20.0, 3
    k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
    if 0 <= k < len(SHIFTIND_PROBE):
        _, frac, thr, shift = SHIFTIND_PROBE[k]
        phase = (t - 3.0) - k * (on + off)
        tele.throttle = thr
        if phase < on:
            tele.rpm = frac * MAX_RPM
            if shift and phase > 2.0:
                tele.gear = 4
    return tele


LOCK_FM_PROBE = [  # (label, slip ratios [FL FR RL RR], slip angle, brake, handbrake, accel long)
    ("slip-6_brake", [-6.0] * 4, 0.0, 1.0, 0.0, -8.0), ("slip-1_brake", [-1.0] * 4, 0.0, 1.0, 0.0, -8.0),
    ("slip-0.5_brake", [-0.5] * 4, 0.0, 1.0, 0.0, -8.0), ("slip-6_nobrake", [-6.0] * 4, 0.0, 0.0, 0.0, 0.0),
    ("brake_only", [0.0] * 4, 0.0, 1.0, 0.0, -8.0), ("angle3_brake", [0.0] * 4, 3.0, 1.0, 0.0, -8.0),
    ("slip-6_handbrake", [-6.0] * 4, 0.0, 0.0, 1.0, -4.0), ("slip-20_brake", [-20.0] * 4, 0.0, 1.0, 0.0, -8.0),
    ("front-6_brake", [-6.0, -6.0, 0.0, 0.0], 0.0, 1.0, 0.0, -8.0), ("slip-6_brake_v8", [-6.0] * 4, 0.0, 1.0, 0.0, -8.0),
]


def stim_lock_fm_probe(t: float):
    on, off = 4.0, 2.0
    if t >= 3.0 + (on + off) * len(LOCK_FM_PROBE):
        return None
    tele = _base(t)
    tele.rpm, tele.speed, tele.throttle = 2500.0, 25.0, 0.0
    k = int((t - 3.0) // (on + off)) if t >= 3.0 else -1
    if 0 <= k < len(LOCK_FM_PROBE):
        label, ratios, angle, brake, hb, acc = LOCK_FM_PROBE[k]
        if label.endswith("_v8"):
            tele.speed = 8.0
        if ((t - 3.0) - k * (on + off)) < on:
            tele.slip_ratio = [float(r) for r in ratios]
            tele.slip_angle = [angle] * 4
            tele.brake, tele.handbrake, tele.accel_long = brake, hb, acc
    return tele


SUSP_FM_PROBE = [  # (label, wheels, size (fraction of travel), width s) one bump each, 6 s apart
    ("FL_0.05", [0], 0.05, 0.10), ("FL_0.1", [0], 0.10, 0.10), ("FL_0.2", [0], 0.20, 0.10), ("FL_0.4", [0], 0.40, 0.10),
    ("RL_0.2", [2], 0.20, 0.10), ("all_0.2", [0, 1, 2, 3], 0.20, 0.10), ("FL_0.2_wide", [0], 0.20, 0.50),
    ("FL_0.2_1frame", [0], 0.20, 1.0 / 60.0), ("FL_0.2", [0], 0.20, 0.10), ("rough_0.02", None, 0.02, 6.0),
    ("rough_0.05", None, 0.05, 6.0), ("FL_0.2", [0], 0.20, 0.10),
]


def stim_susp_fm_probe(t: float):
    gap = 6.0
    if t >= 3.0 + gap * len(SUSP_FM_PROBE) + 2.0:
        return None
    tele = _base(t)
    tele.rpm, tele.speed, tele.throttle = 3000.0, 20.0, 0.3
    k = int((t - 3.0) // gap) if t >= 3.0 else -1
    if 0 <= k < len(SUSP_FM_PROBE):
        _, wheels, size, width = SUSP_FM_PROBE[k]
        phase = (t - 3.0) - k * gap
        if wheels is None:                       # rough road: random walk for `width` seconds
            if phase < width:
                rng = np.random.default_rng(int(t * 60))
                tele.susp_travel = [float(0.5 + size * n) for n in rng.standard_normal(4)]
        elif 0.0 <= phase < width:
            s = math.sin(math.pi * phase / width) if width > 0.02 else 1.0
            for w in wheels:
                tele.susp_travel[w] = 0.5 + size * s
    return tele


SHIFT_PROBE = [  # (label, gear change?, rpm before, rpm after, throttle)  6 s apart, rpm ramps back up after
    ("gear+rpmdrop", True, 7000.0, 4500.0, 1.0), ("gear_only", True, 5000.0, 5000.0, 1.0),
    ("rpmdrop_only", False, 7000.0, 4500.0, 1.0), ("gear+rpmdrop_thr0", True, 7000.0, 4500.0, 0.0),
    ("gear+rpmrise(down)", True, 4000.0, 6500.0, 0.5), ("small_drop", False, 6000.0, 5000.0, 1.0),
    ("gear+rpmdrop", True, 7000.0, 4500.0, 1.0), ("gear_only", True, 5000.0, 5000.0, 1.0),
    ("rpmdrop_only", False, 7000.0, 4500.0, 1.0), ("gear+rpmdrop", True, 7000.0, 4500.0, 1.0),
]


def stim_shift_probe(t: float):
    """What the Forza plugin needs to call it a gear shift: the gear byte, an rpm drop, or both."""
    gap = 6.0
    if t >= 3.0 + gap * len(SHIFT_PROBE) + 2.0:
        return None
    tele = _base(t)
    tele.speed, tele.gear = 25.0, 3
    k = int((t - 3.0) // gap) if t >= 3.0 else -1
    if k < 0:
        tele.rpm, tele.throttle = 5000.0, 0.5
        return tele
    if k >= len(SHIFT_PROBE):
        tele.rpm, tele.throttle = 5000.0, 0.5
        return tele
    _, gear_change, before, after, thr = SHIFT_PROBE[k]
    phase = (t - 3.0) - k * gap
    tele.throttle = thr
    tele.gear = 3 + sum(1 for j in range(k) if SHIFT_PROBE[j][1]) % 3      # gear count drifts 3..5 with each change
    if phase < 2.0:                          # approach: hold/ramp to the 'before' rpm
        tele.rpm = before
    else:                                    # the event at phase 2.0, then recover linearly back over 3 s
        tele.rpm = after + (before - after) * min((phase - 2.0) / 3.0, 1.0) if before > after else \
            after - (after - before) * min((phase - 2.0) / 3.0, 1.0)
        if gear_change:
            tele.gear += 1
    return tele


STIMULI = {"rpm": stim_rpm, "shift": stim_shift, "accel": stim_accel, "collision": stim_collision,
           "suspension": stim_suspension, "lock": stim_lock, "slip": stim_slip, "rumble": stim_rumble,
           "shift_indicator": stim_shift_indicator,
           "collision_probe": stim_collision_probe, "suspension_probe": stim_suspension_probe,
           "lock_probe": stim_lock_probe, "accel_probe": stim_accel_probe,
           "rumble_probe": stim_rumble_probe, "slip_probe": stim_slip_probe,
           "shift_indicator_probe": stim_shift_indicator_probe, "lock_fm_probe": stim_lock_fm_probe,
           "susp_fm_probe": stim_susp_fm_probe, "shift_probe": stim_shift_probe, "rumble_probe2": stim_rumble_probe2}
# probes reuse the base effect's HaptiConnect profile key
PROBE_BASE = {"collision_probe": "collision", "suspension_probe": "suspension", "lock_probe": "lock",
              "accel_probe": "accel", "rumble_probe": "rumble", "slip_probe": "slip",
              "shift_indicator_probe": "shift_indicator", "lock_fm_probe": "lock", "susp_fm_probe": "suspension",
              "shift_probe": "shift", "rumble_probe2": "rumble"}
DRIVE_HINTS = {
    "rpm": "rev through the whole range in neutral a few times, slowly, then drive normally",
    "shift": "drive and shift up and down a lot",
    "accel": "hard acceleration, hard braking, fast corners; hold each for a few seconds",
    "collision": "hit walls, cones and other cars at different speeds, a few seconds apart",
    "suspension": "kerbs, gravel, jumps and rough tarmac",
    "lock": "brake hard enough to lock the wheels (ABS off), several times",
    "slip": "wheelspin from standstill and power slides",
    "rumble": "drive along kerbs / rumble strips, then rough surfaces",
    "shift_indicator": "hold each gear to the rev limiter a few times",
}


class StimulusSource(Source):
    name = "stimulus"

    def __init__(self, fn, rate_hz: float = 60.0) -> None:
        super().__init__()
        self.fn = fn
        self.dt = 1.0 / rate_hz
        self.done = False

    def run(self) -> None:
        t0 = time.perf_counter()
        nxt = t0
        while not self.stopping():
            tele = self.fn(time.perf_counter() - t0)
            if tele is None:
                self.done = True
                return
            self.publish(tele)
            nxt += self.dt
            delay = nxt - time.perf_counter()
            if delay > 0:
                time.sleep(delay)


# ------------------------------------------------------------------ HaptiConnect control
def profile_path(plugin: str) -> Path:
    return HC_GAMES / PLUGINS[plugin]["game"] / "Profiles" / "Profile 1.ini"


def set_profile(plugin: str, effect: str | None) -> None:
    """effect=None restores the original profile (saved as Profile 1.ini.orig on first use)."""
    prof = profile_path(plugin)
    orig = prof.with_suffix(".ini.orig")
    if not orig.exists():
        shutil.copy(prof, orig)
    if effect is None:
        shutil.copy(orig, prof)
        return
    key = PLUGINS[plugin]["keys"][effect]
    lines = []
    for line in prof.read_text(encoding="utf-8").splitlines():
        if "_strength=" in line:
            name = line.split("_strength=")[0]
            line = f"{name}_strength={'1' if name == key else '0'}"
        elif "_enabled=" in line:
            name = line.split("_enabled=")[0]
            line = f"{name}_enabled={'true' if name == key else 'false'}"
        lines.append(line)
    prof.write_text("\n".join(lines) + "\n", encoding="utf-8")


def game_process_running(needle: str | None) -> bool:
    if not needle:
        return True
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout.lower()
    return needle.lower() in out


def newest_log() -> Path | None:
    logs = sorted(HC_LOGS.glob("*.log"), key=lambda p: p.stat().st_mtime)
    return logs[-1] if logs else None


def restart_hapticonnect(plugin: str, timeout: float = 25.0) -> bool:
    if not HC_EXE.exists():
        print(HC_MISSING)
        return False
    game, port = PLUGINS[plugin]["game"], PLUGINS[plugin]["port"]
    subprocess.run(["taskkill", "/F", "/IM", "bk-connect.exe"], capture_output=True)
    time.sleep(2.0)
    before = newest_log()
    # launch through Explorer so it runs in the normal desktop context (not a child of this process)
    subprocess.Popen(["explorer.exe", str(HC_EXE)])
    needle = f'"{game}" bound to port {port}'
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
        log = newest_log()
        if log is not None and log != before:
            try:
                txt = log.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if needle in txt:
                return True
    return False


def make_game_source(game: str):
    if game == "ace":
        from .sources.ace import ACESource
        return ACESource()
    if game == "forza":
        from .sources.forza import ForzaSource
        return ForzaSource(port=5555)
    return None                      # beamng talks to HaptiConnect directly


_OVERLAY_SRC = r"""
import sys, tkinter as tk
title, body, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
root = tk.Tk(); root.overrideredirect(True); root.attributes("-topmost", True); root.configure(bg="#111")
sw = root.winfo_screenwidth(); root.geometry(f"+{sw - 520}+40")
tk.Label(root, text=title, font=("Segoe UI", 16, "bold"), fg="#ff7a00", bg="#111", padx=18, pady=(10)).pack(anchor="w")
tk.Label(root, text=body, font=("Segoe UI", 11), fg="#ddd", bg="#111", padx=18, pady=(0), justify="left", wraplength=460).pack(anchor="w", pady=(0, 12))
root.after(int(secs * 1000), root.destroy); root.mainloop()
"""


def show_overlay(title: str, body: str, seconds: float):
    """Small always-on-top desktop label so the person in the chair knows what is being tested."""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw) if pyw.exists() else sys.executable
    try:
        return subprocess.Popen([exe, "-c", _OVERLAY_SRC, title, body, str(seconds)],
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return None


EXPECT = {
    "rpm": "a tone that climbs and falls with rpm, two slow sweeps",
    "shift": "one short burst per gear change, every 2.5 s",
    "accel": "a ~60 Hz tone that switches on at strong acceleration, braking, cornering",
    "collision": "single hard hits, 4 s apart (some variants may be silent)",
    "suspension": "steady low rumble plus a pulse per bump",
    "lock": "a steady tone during hard braking with locked wheels",
    "slip": "buzzes during wheelspin, then during slides",
    "rumble": "buzz while on rumble strips",
    "shift_indicator": "pulses when held at the rev limiter",
}


def wait_enter(stop: threading.Event) -> None:
    try:
        line = sys.stdin.readline()
    except Exception:
        return
    if line != "":
        stop.set()


# ------------------------------------------------------------------ one effect
def run_effect(effect: str, args) -> Path | None:
    plugin = args.plugin
    cfg = PLUGINS[plugin]
    base = PROBE_BASE.get(effect, effect)
    print(f"\n=== {effect} via HaptiConnect {cfg['game']} plugin ===")
    if not game_process_running(cfg["process"]):
        print(f"  {cfg['game']} is not running. HaptiConnect only listens for it while the game process exists: "
              f"start {cfg['game']} and leave it at the main menu, then run again.")
        return None
    set_profile(plugin, base)
    print(f"  profile set to {cfg['keys'][base]} only; restarting HaptiConnect ...")
    if not restart_hapticonnect(plugin):
        print(f"  HaptiConnect did not bind port {cfg['port']} for {cfg['game']}. If this is BeamNG, open "
              "Spatial Configuration and re-select the ButtKicker; for Forza make sure the game is running.")
        return None
    time.sleep(1.5)

    game = args.game
    tag = f"cal_{effect}_{plugin}_{game or 'synthetic'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    session = PROJECT_DIR / "sessions" / tag
    session.mkdir(parents=True, exist_ok=True)
    rec = LoopbackRecorder(args.device)
    log = TelemetryLog()
    echo = None
    if game:
        src = make_game_source(game)
    else:
        src = StimulusSource(STIMULI[effect])
    fwd = None
    if src is not None:
        src.listeners.append(log)
        fwd = TelemetryForwarder(lambda: src.latest() if src.age() < 1.0 else None, host="127.0.0.1",
                                 port=cfg["port"], rate_hz=60.0, fmt=cfg["fmt"])
    else:
        echo = BeamNGSource(port=args.listen)         # game=beamng: log what HaptiConnect forwards back
        echo.listeners.append(log)

    rec.start()
    if echo is not None:
        echo.start()
        time.sleep(0.5)
        if echo.error:
            print("  cannot listen on", args.listen, ":", echo.error)
            rec.stop()
            return None
    if src is not None:
        src.start()
    if fwd is not None:
        fwd.start()
    stop = threading.Event()
    est = getattr(args, "seconds", None) or 120.0
    if not game:
        tt = 0.0
        while STIMULI[effect](tt) is not None and tt < 600:
            tt += 1.0
        est = tt + 3.0
    overlay = show_overlay(f"Testing: {cfg['keys'][base].replace('%20', ' ')}" + (" (probe)" if effect in PROBE_BASE else ""),
                           (f"Drive: {DRIVE_HINTS[base]}" if game else f"Expect: {EXPECT.get(base, '')}")
                           + f"\nHaptiConnect {cfg['game']} plugin, ~{est:.0f} s", est + 2.0)
    if game:
        print(f"  DRIVE NOW ({game}): {DRIVE_HINTS[effect]}")
        print("  press Enter when done" + (f" (auto-stop after {args.seconds:.0f} s)" if args.seconds else ""))
        threading.Thread(target=wait_enter, args=(stop,), daemon=True).start()
    t0 = time.perf_counter()
    try:
        while not rec.error and not stop.is_set():
            time.sleep(0.5)
            el = time.perf_counter() - t0
            if game:
                if args.seconds and el >= args.seconds:
                    break
                st = (src.error or src.status) if src is not None else "game -> HaptiConnect directly"
                fps = src.fps if src is not None else echo.fps
                info = f"{st} {fps:3.0f} fps"
            else:
                if src.done or src.error or (args.seconds and el >= args.seconds):
                    break
                info = f"fwd {fwd.rate:3.0f}/s"
            pk = 20 * math.log10(max(rec.peak, 1e-6))
            sys.stdout.write(f"\r  {el:5.1f}s  audio {pk:6.1f} dBFS  frames {len(log):5d}  {info}".ljust(110))
            sys.stdout.flush()
    except KeyboardInterrupt:
        print("\ninterrupted")
    print()
    time.sleep(0.8)
    if fwd is not None:
        fwd.stop()
    if src is not None:
        src.stop()
    rec.stop()
    if echo is not None:
        echo.stop()
    if rec.error:
        print("  audio capture error:", rec.error)
        return None
    audio = rec.audio()
    if rec.t0 is None or len(audio) == 0:
        print("  no audio captured")
        return None
    write_wav(session / "audio.wav", audio, rec.sr)
    with (session / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        with log.lock:
            for t in log.rows:
                w.writerow(tele_row(t, rec.t0))
    peak = 20 * math.log10(max(float(np.max(np.abs(audio))), 1e-6))
    (session / "meta.json").write_text(json.dumps({
        "note": f"calibration: HaptiConnect {cfg['game']} plugin, {cfg['keys'][base]} only, "
                + (f"driven by {game}" if game else f"synthetic stimulus '{effect}'"),
        "effect": base, "stimulus": effect, "plugin": plugin, "game": game, "device": rec.mic.name, "samplerate": rec.sr,
        "channels": rec.channels, "duration_s": round(len(audio) / rec.sr, 2), "frames": len(log),
        "peak_dbfs": round(peak, 1), "created": datetime.now().isoformat(timespec="seconds")}, indent=2),
        encoding="utf-8")
    print(f"  recorded {len(audio) / rec.sr:.1f} s, peak {peak:.1f} dBFS, {len(log)} telemetry frames")
    if len(log) == 0:
        print("  no telemetry frames: the game source produced nothing")
        return None
    if peak < -60:
        print("  silent recording: HaptiConnect produced no output for this effect")
    if effect in PROBE_BASE:
        print(f"  probe recorded; inspect with: python -m openshaker.probe \"{session}\"")
        return None
    out = PROJECT_DIR / "profiles" / session.name
    analyze(session, out, plots=True)
    return out / "profile.json"


def merge_profiles(paths: list[Path], out_dir: Path) -> Path:
    """Update (not replace) the merged profile with the effects learned in these sessions."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "profile.json"
    if target.exists():
        merged = json.loads(target.read_text(encoding="utf-8"))
        merged.setdefault("effects", {})
        merged.setdefault("analysis", {})
        merged.setdefault("meta", {}).setdefault("parts", [])
        merged["meta"]["updated"] = datetime.now().isoformat(timespec="seconds")
    else:
        merged = {"meta": {"created": datetime.now().isoformat(timespec="seconds"), "parts": []},
                  "effects": {}, "analysis": {}}
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        meta = json.loads((PROJECT_DIR / "sessions" / p.parent.name / "meta.json").read_text(encoding="utf-8"))
        name = APP_EFFECT[meta["effect"]]
        if name in data["effects"]:
            params = dict(data["effects"][name])
            if params.get("sample"):
                dst = out_dir / f"{name}.wav"
                shutil.copy(p.parent / params["sample"], dst)
                params["sample"] = dst.name
            merged["effects"][name] = params
            merged["analysis"][name] = data["analysis"].get(name, {})
        part = portable_path(p)
        if part not in merged["meta"]["parts"]:
            merged["meta"]["parts"].append(part)
    (out_dir / "profile.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return out_dir / "profile.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="openshaker.calibrate", description="Calibrate against HaptiConnect automatically.")
    ap.add_argument("effects", nargs="*", default=["all"],
                    help="rpm shift accel collision suspension lock slip rumble shift_indicator | all")
    ap.add_argument("--plugin", choices=list(PLUGINS), default="beamng", help="which HaptiConnect plugin to drive")
    ap.add_argument("--game", choices=["ace", "forza", "beamng"],
                    help="drive a real game instead of synthetic sequences (ACE/Forza are bridged into HaptiConnect)")
    ap.add_argument("--seconds", type=float, help="game mode: auto-stop each effect after this many seconds")
    ap.add_argument("--listen", type=int, default=4446, help="port HaptiConnect forwards BeamNG packets to (game=beamng)")
    ap.add_argument("--device", default="ButtKicker", help="output device to tap")
    ap.add_argument("--keep-profile", action="store_true", help="do not restore the original HaptiConnect profile")
    ap.add_argument("--out", help="merged profile folder (default profiles/<beamng|forza_motorsport|forza_horizon>[_<game>])")
    ap.add_argument("--reanalyze", action="store_true",
                    help="do not touch HaptiConnect: re-learn the newest recorded session of each effect and merge")
    ap.add_argument("--fmt", choices=["outgauge", "horizon", "motorsport", "sled"],
                    help="override the packet format sent to the plugin (Forza Motorsport: motorsport or sled)")
    args = ap.parse_args(argv)
    if args.fmt:
        PLUGINS[args.plugin]["fmt"] = args.fmt

    keys = PLUGINS[args.plugin]["keys"]
    effects = [e for e in ORDER if e in keys] if (args.effects == ["all"] or "all" in args.effects) else args.effects
    bad = [e for e in effects if e not in STIMULI]
    if bad:
        print("unknown effect(s):", bad)
        return 2
    skipped = [e for e in effects if PROBE_BASE.get(e, e) not in keys]
    if skipped:
        print(f"{PLUGINS[args.plugin]['game']} plugin has no effect for: {', '.join(skipped)} (skipped)")
        effects = [e for e in effects if PROBE_BASE.get(e, e) in keys]
    out_dir = Path(args.out) if args.out else PROJECT_DIR / "profiles" / (
        {"fm": "forza_motorsport", "fh5": "forza_horizon"}.get(args.plugin, args.plugin) + (f"_{args.game}" if args.game else ""))

    if args.reanalyze:
        results = []
        for e in effects:
            pattern = f"cal_{e}_{args.plugin}_{args.game or 'synthetic'}_*"
            sessions = sorted((PROJECT_DIR / "sessions").glob(pattern)) or \
                (sorted((PROJECT_DIR / "sessions").glob(f"cal_{e}_2*")) if args.plugin == "beamng" and not args.game else [])
            if not sessions:
                print(f"{e}: no recorded session")
                continue
            session = sessions[-1]
            print(f"\n=== {e}: {session.name} ===")
            analyze(session, PROJECT_DIR / "profiles" / session.name, plots=True)
            results.append(PROJECT_DIR / "profiles" / session.name / "profile.json")
        if results:
            merged = merge_profiles(results, out_dir)
            print(f"\nmerged profile: {merged}\nlearned: {', '.join(json.loads(merged.read_text())['effects'])}")
        return 0

    if not HC_EXE.exists():
        print(HC_MISSING)
        return 1
    results = []
    try:
        for e in effects:
            r = run_effect(e, args)
            if r is not None:
                results.append(r)
    finally:
        if not args.keep_profile:
            set_profile(args.plugin, None)
            print("\nrestoring the original HaptiConnect profile and restarting HaptiConnect ...")
            restart_hapticonnect(args.plugin, timeout=15.0)
    if results:
        merged = merge_profiles(results, out_dir)
        learned = json.loads(merged.read_text())["effects"]
        print(f"\nmerged profile: {merged}\nlearned: {', '.join(learned) or 'nothing'}")
        print("Load it in the GUI with 'Load profile...' or run: python -m openshaker --profile", merged)
    return 0


if __name__ == "__main__":
    sys.exit(main())
