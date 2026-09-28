"""Scripted telemetry that exercises every effect (no game needed). Loops every 24 s."""
from __future__ import annotations

import math
import random
import time

from .sources.base import Source
from .telemetry import Telemetry

LOOP_S = 24.0
# The collision's spike must outlast the detector's min_hold_s (0.03 s in the HaptiConnect-matched
# profiles) by a couple of frames at 60 Hz, and clear Trackmania's 60 m/s^2 frame-to-frame jump, or the
# Demo never plays the hit (it used to be -60 for 20 ms and never did).
IMPACT_SPIKE_S = 0.08
IMPACT_SPIKE = -75.0


class DemoSource(Source):
    name = "demo"

    def __init__(self, rate_hz: float = 60.0) -> None:
        super().__init__()
        self.dt = 1.0 / rate_hz
        self.rng = random.Random(7)
        self.phase_name = ""
        self.susp = [0.5, 0.5, 0.5, 0.5]

    def run(self) -> None:
        t0 = time.perf_counter()
        while not self.stopping():
            self.publish(self.frame(time.perf_counter() - t0))
            time.sleep(self.dt)

    def frame(self, t: float) -> Telemetry:
        """The scripted telemetry at `t` seconds into the demo."""
        ph = t % LOOP_S
        susp = self.susp
        tele = Telemetry()
        tele.active = True
        tele.max_rpm, tele.idle_rpm = 8000.0, 900.0
        tele.engine_running = True
        # gentle road texture all the time
        for i in range(4):
            susp[i] += self.rng.uniform(-0.004, 0.004)
            susp[i] = min(max(susp[i], 0.3), 0.7)
        tele.susp_travel = list(susp)

        if ph < 2.0:
            self.phase_name = "idle"
            tele.rpm = 900.0 + 40.0 * math.sin(t * 6.0)
            tele.gear = 0
        elif ph < 10.0:
            self.phase_name = "accelerating through gears"
            seg = (ph - 2.0) / 1.6                    # 5 gears, 1.6 s each
            gear = min(int(seg) + 1, 5)
            frac = seg - int(seg)
            tele.gear = gear
            tele.rpm = 2500.0 + 5000.0 * frac
            tele.throttle = 1.0
            tele.speed = 8.0 * (ph - 2.0)
            tele.accel_long = 6.0
        elif ph < 12.0:
            self.phase_name = "rumble strip (right wheels)"
            tele.gear, tele.rpm, tele.throttle = 5, 6000.0, 0.6
            tele.speed = 45.0
            tele.rumble_strip = [False, True, False, True]
            tele.surface_rumble = [0.0, 0.6, 0.0, 0.6]
        elif ph < 13.5:
            self.phase_name = "braking with front lock-up"
            tele.gear, tele.rpm, tele.brake = 4, 4000.0, 1.0
            tele.speed = 45.0 - 25.0 * (ph - 12.0)
            tele.accel_long = -9.0
            tele.slip_ratio = [-3.0, -3.0, -0.5, -0.5]
        elif ph < 15.0:
            self.phase_name = "big bump"
            tele.gear, tele.rpm, tele.throttle, tele.speed = 3, 3500.0, 0.3, 20.0
            if 13.6 <= ph < 13.7:
                tele.susp_travel = [0.85, 0.85, 0.5, 0.5]
            if 13.7 <= ph < 13.8:
                tele.susp_travel = [0.5, 0.5, 0.85, 0.85]
        elif ph < 16.0:
            self.phase_name = "impact"
            tele.gear, tele.rpm, tele.throttle, tele.speed = 3, 3500.0, 0.3, 20.0
            if 15.1 <= ph < 15.1 + IMPACT_SPIKE_S:
                tele.accel_long = IMPACT_SPIKE
        elif ph < 19.0:
            self.phase_name = "wheelspin"
            tele.gear, tele.rpm, tele.throttle, tele.speed = 2, 6800.0, 1.0, 15.0
            tele.slip_ratio = [0.0, 0.0, 3.0, 3.0]
            tele.accel_long = 3.0
        elif ph < 21.0:
            self.phase_name = "ABS braking"
            tele.gear, tele.rpm, tele.brake = 3, 3000.0, 1.0
            tele.speed = 30.0 - 12.0 * (ph - 19.0)
            tele.abs_active = True
            tele.accel_long = -8.0
        else:
            self.phase_name = "coasting"
            tele.gear, tele.rpm, tele.speed = 2, 1800.0, 8.0
        return tele
