"""BeamNG.drive source: the game's two built-in UDP protocols, merged (no mod needed).

  * OutGauge (96/92 bytes, Options > Other): pedals, rpm, gear, dash lights, and wheel speed in its
    `speed` field (BeamNG fills it from electrics.wheelspeed).
  * Motion Sim (88 bytes starting "BNG1", same menu): the car's velocity, acceleration without
    gravity, up vector and rotation rates, at up to 200 Hz. It carries crashes, bumps and acceleration,
    and its velocity is the real ground speed that wheel speed is compared with for lock-ups and spin.

Both default to 127.0.0.1:4444, so one socket normally receives both; `motion_port` also listens on a
second port when Motion Sim is pointed elsewhere. Each packet updates its half and publishes the merged
frame; a half that stops arriving is dropped after a moment, so OutGauge alone still drives the engine,
gears and pedals.

Also reads the 136-byte extended OutGauge struct HaptiConnect's BeamNG mod sends: the calibration tools
replay that layout to HaptiConnect and log its echo. Every layout is a plain C struct with natural
alignment (LuaJIT ffi.cdef), little endian.
"""
from __future__ import annotations

import dataclasses
import math
import select
import socket
import struct
import time
from typing import Optional

from ..telemetry import Telemetry
from .base import UDPSource

# HaptiConnect variant (natural alignment):
#  0 f total_time | 4 char[4] car | 8 H flags | 12 f gear | 16 c plid | 20 f speed | 24 f wheelspeed
# 28 f airspeed | 32 f engine_rate | 36 i max_rpm | 40 f turbo | 44 f engTemp | 48 f fuel
# 52 f oilPressure | 56 f oilTemp | 60 I dashLights | 64 I showLights | 68 f throttle | 72 f brake
# 76 f clutch | 80 char[16] | 96 char[16] | 112 i id | 116 f g_lat | 120 f g_long | 124 f g_vert
# 128 f g_vert2 | 132 i ignition   => 136 bytes
HC_SIZE = 136
# Stock OutGauge (BeamNG lua/vehicle/protocols/outgauge.lua, LFS InSim.txt):
#  0 I time | 4 char[4] car | 8 H flags | 10 c gear (0 R, 1 N, 2 first) | 11 c plid | 12 f speed
# 16 f rpm | 20 f turbo | 24 f engTemp | 28 f fuel | 32 f oilPressure | 36 f oilTemp | 40 I dashLights
# 44 I showLights | 48 f throttle | 52 f brake | 56 f clutch | 60 char[16] | 76 char[16] | 92 i id => 96
STOCK_SIZES = (96, 92)
# Motion Sim (lua/vehicle/protocols/motionSim.lua):
#  0 char[4] "BNG1" | 4 f pos xyz | 16 f vel xyz (world, m/s) | 28 f acc xyz (m/s^2, gravity not
# included) | 40 f up xyz | 52 f roll/pitch/yaw | 64 f their rates (rad/s) | 76 f their accelerations => 88
MOTION_SIZE = 88
MOTION_MAGIC = b"BNG1"
# which Motion Sim acceleration component feeds lat / long / vert, and its sign. Checked with
# openshaker.beamng_check on the one recorded drive with Motion Sim: long = +y (follows the ground
# speed's rate of change), lat = x only weakly (the effects use its magnitude), vert not beyond
# plausible magnitudes.
AXES = ((0, 1.0), (1, 1.0), (2, 1.0))

# dashLights (available) / showLights (lit) bits, the same in both OutGauge layouts
DL_HANDBRAKE = 1 << 2
DL_TC = 1 << 4
DL_BATTERY = 1 << 9          # BeamNG lights it while the engine is not running
DL_ABS = 1 << 10

OUTGAUGE_STALE_S = 0.5       # OutGauge runs at up to 60 Hz
MOTION_STALE_S = 0.25        # Motion Sim at up to 200 Hz
SLIP_FULL = 0.15             # wheel speed 15 % off the ground speed reads 1.0, about the grip limit


class BeamNGSource(UDPSource):
    name = "beamng"

    def __init__(self, port: int = 4444, accel_scale: float = 1.0, motion_port: int = 0,
                 host: str = "127.0.0.1") -> None:
        super().__init__(port, host=host)
        self.accel_scale = accel_scale
        self.motion_port = int(motion_port or 0)
        self._max_rpm_seen = 0.0
        self._og: Optional[Telemetry] = None
        self._og_t = -math.inf
        self._motion: Optional[dict] = None
        self._motion_t = -math.inf

    def ports(self) -> list[int]:
        second = [self.motion_port] if self.motion_port and self.motion_port != self.port else []
        return [self.port] + second

    def run(self) -> None:
        socks = []
        try:
            for port in self.ports():
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                socks.append(sock)
                try:
                    sock.bind((self.host, port))
                except OSError as exc:
                    self.error = (f"cannot bind UDP {port} ({exc.strerror or exc}); "
                                  f"is HaptiConnect, SimHub or another tool using it?")
                    self.status = "error"
                    return
            self.status = "listening on UDP " + " + ".join(str(p) for p in self.ports())
            while not self.stopping():
                ready, _, _ = select.select(socks, [], [], 0.5)
                for sock in ready:
                    try:
                        data, _ = sock.recvfrom(self.bufsize)
                    except OSError:              # Windows surfaces an earlier ICMP "port unreachable" here
                        continue
                    self.packets += 1
                    self.last_len = len(data)
                    try:
                        tele = self.parse(data)
                    except Exception:        # a malformed packet must never take the source down
                        self.malformed += 1
                        continue
                    if tele is not None:
                        tele.raw = data
                        self.publish(tele)
        finally:
            for sock in socks:
                sock.close()

    def parse(self, data: bytes, now: Optional[float] = None) -> Optional[Telemetry]:
        n = len(data)
        if n == HC_SIZE:
            self._show("extended OutGauge (HaptiConnect's layout)")
            return self._parse_hc(data)
        now = time.perf_counter() if now is None else now
        if n == MOTION_SIZE and data[:4] == MOTION_MAGIC:
            self._motion, self._motion_t = parse_motion(data), now
        elif n in STOCK_SIZES:
            self._og, self._og_t = self._parse_stock(data), now
        else:
            return None
        return self._merged(now)

    def _show(self, status: str) -> None:
        if self.status != status:
            self.status = status

    def _merged(self, now: float) -> Telemetry:
        og = self._og if now - self._og_t <= OUTGAUGE_STALE_S else None
        m = self._motion if now - self._motion_t <= MOTION_STALE_S else None
        if og is not None and m is not None:
            self._show("OutGauge + Motion Sim")
        elif og is not None:
            self._show("OutGauge only: tick Motion Sim in BeamNG (Options > Other) for crashes, bumps and wheel lock")
        else:
            self._show("Motion Sim only: tick OutGauge in BeamNG (Options > Other) for engine, gears and pedals")

        if og is not None:
            t = dataclasses.replace(og)
        else:
            t = Telemetry(active=True, engine_running=False, idle_rpm=800.0,
                          max_rpm=max(self._max_rpm_seen, 6000.0))
        wheel = abs(og.speed) if og is not None else None      # wheel speed has a sign in reverse
        extra = {"motion": m is not None, "wheel_speed": wheel}
        if m is not None:
            vx, vy, vz = m["vel"]
            ground = math.sqrt(vx * vx + vy * vy + vz * vz)
            acc, s = m["acc"], self.accel_scale
            (li, ls), (gi, gs), (vi, vs) = AXES
            t.speed = ground
            t.accel_lat, t.accel_long, t.accel_vert = acc[li] * ls * s, acc[gi] * gs * s, acc[vi] * vs * s
            if wheel is not None:
                t.slip_ratio = [(wheel - ground) / max(ground, 2.0) / SLIP_FULL] * 4
            roll, pitch, yaw = m["rate"]
            extra.update(ground_speed=ground, roll_rate=roll, pitch_rate=pitch, yaw_rate=yaw, up=m["up"])
        t.extra = extra
        return t

    def _parse_hc(self, d: bytes) -> Telemetry:
        gear_f, = struct.unpack_from("<f", d, 12)
        speed, wheelspeed, airspeed, rpm = struct.unpack_from("<4f", d, 20)
        max_rpm, = struct.unpack_from("<i", d, 36)
        show, = struct.unpack_from("<I", d, 64)
        throttle, brake, clutch = struct.unpack_from("<3f", d, 68)
        g_lat, g_long, g_vert, g_vert2 = struct.unpack_from("<4f", d, 116)
        ignition, = struct.unpack_from("<i", d, 132)

        t = Telemetry()
        t.gear = int(round(gear_f)) if math.isfinite(gear_f) else 0
        # HaptiConnect's mod fills wheelspeed and airspeed but never `speed`, which therefore arrives as 0
        t.speed = max(speed if speed > 0.0 else airspeed, 0.0)
        t.rpm = max(rpm, 0.0)
        t.max_rpm = float(max_rpm) if max_rpm > 0 else max(self._max_rpm_seen, 6000.0)
        self._max_rpm_seen = max(self._max_rpm_seen, t.rpm)
        t.idle_rpm = 800.0
        t.throttle, t.brake, t.clutch = _clamp01(throttle), _clamp01(brake), _clamp01(clutch)
        _lights(t, show)
        s = self.accel_scale
        t.accel_lat, t.accel_long, t.accel_vert = g_lat * s, g_long * s, g_vert * s
        # one slip figure for the whole car: wheel speed vs ground speed, normalized to ~grip limit
        ref = max(t.speed, 2.0)
        slip = (wheelspeed - t.speed) / ref / SLIP_FULL
        t.slip_ratio = [slip] * 4
        t.engine_running = ignition != 0 and t.rpm > 50
        t.active = ignition != 0
        return t

    def _parse_stock(self, d: bytes) -> Telemetry:
        gear_b, = struct.unpack_from("<b", d, 10)
        speed, rpm = struct.unpack_from("<2f", d, 12)
        dash, show = struct.unpack_from("<2I", d, 40)
        throttle, brake, clutch = struct.unpack_from("<3f", d, 48)
        t = Telemetry()
        t.gear = gear_b - 1               # LFS: 0 reverse, 1 neutral, 2 first
        t.speed = abs(speed)              # BeamNG's wheel speed, negative in reverse
        t.rpm = max(rpm, 0.0)
        self._max_rpm_seen = max(self._max_rpm_seen, t.rpm)
        t.max_rpm = max(self._max_rpm_seen, 6000.0)
        t.idle_rpm = 800.0
        t.throttle, t.brake, t.clutch = _clamp01(throttle), _clamp01(brake), _clamp01(clutch)
        _lights(t, show)
        stalled = bool(dash & DL_BATTERY) and bool(show & DL_BATTERY)
        t.engine_running = t.rpm > 50 and not stalled
        t.active = True
        return t


def parse_motion(d: bytes) -> dict:
    f = struct.unpack_from("<21f", d, 4)
    return {"pos": f[0:3], "vel": f[3:6], "acc": f[6:9], "up": f[9:12], "angle": f[12:15],
            "rate": f[15:18], "ang_acc": f[18:21]}


def _lights(t: Telemetry, show: int) -> None:
    t.handbrake = 1.0 if show & DL_HANDBRAKE else 0.0
    # ABS only regulates under braking. HaptiConnect's mod reads an electrics value that current BeamNG
    # may not provide (nil ~= 0 is true in Lua), which would leave the bit lit for good.
    t.abs_active = bool(show & DL_ABS) and t.brake > 0.05
    t.tc_active = bool(show & DL_TC)


def _clamp01(x: float) -> float:
    if not math.isfinite(x):
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x
