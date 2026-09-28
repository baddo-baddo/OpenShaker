"""Forza Data Out UDP source (Forza Horizon 6 / Horizon 5 / Motorsport 2023).

Packet layout is a flat little-endian C struct:
  * 232 bytes  "Sled"  (Motorsport with format = Sled)
  * 324 bytes  Horizon (232 sled + 12-byte Horizon block + 79-byte dash tail + 1 pad); FH6 == FH5
  * 331 bytes  Motorsport "Car Dash" (232 sled + 79 dash tail + 16 tire wear + 4 track ordinal)
In-game: Settings > HUD and Gameplay > Data Out = On, IP 127.0.0.1, port = this source's port.
"""
from __future__ import annotations

import math
import struct
from typing import Optional

from ..telemetry import Telemetry
from .base import UDPSource

SLED = 232
HORIZON = 324
MOTORSPORT_DASH = 331


KINDS = {SLED: "sled", HORIZON: "horizon", MOTORSPORT_DASH: "motorsport"}


def dash_offset(n: int) -> Optional[int]:
    if n == HORIZON:
        return 244
    if n == MOTORSPORT_DASH:
        return 232
    return None


class ForzaSource(UDPSource):
    name = "forza"

    def __init__(self, port: int = 5555, host: str = "127.0.0.1") -> None:
        super().__init__(port, host=host, bufsize=1024)
        self.kind = "?"

    def parse(self, data: bytes) -> Optional[Telemetry]:
        t = parse_packet(data)
        if t is not None:
            self.kind = KINDS[len(data)]
        return t


def parse_packet(data: bytes) -> Optional[Telemetry]:
    """One Forza Data Out packet as a Telemetry frame, or None for a size no Forza sends. Also for tools:
    a drive log's raw_hex decodes with parse_packet(bytes.fromhex(row["raw_hex"]))."""
    n = len(data)
    if n in KINDS:
        t = Telemetry()
        is_race_on, packet_ms = struct.unpack_from("<iI", data, 0)
        max_rpm, idle_rpm, rpm = struct.unpack_from("<3f", data, 8)
        ax, ay, az = struct.unpack_from("<3f", data, 20)        # x right, y up, z forward
        vx, vy, vz = struct.unpack_from("<3f", data, 32)
        susp = struct.unpack_from("<4f", data, 68)             # normalized 0..1
        slip_ratio = struct.unpack_from("<4f", data, 84)
        rumble = struct.unpack_from("<4i", data, 116)
        surface = struct.unpack_from("<4f", data, 148)
        slip_angle = struct.unpack_from("<4f", data, 164)
        combined = struct.unpack_from("<4f", data, 180)
        travel_m = struct.unpack_from("<4f", data, 196)         # SuspensionTravelMeters: what HaptiConnect's bed follows
        cylinders, = struct.unpack_from("<i", data, 228)

        t.active = is_race_on != 0
        t.packet_ms = int(packet_ms)                            # the game's clock: a repeated packet keeps it
        t.rpm = max(rpm, 0.0)
        t.max_rpm = max_rpm if max_rpm > 0 else 8000.0
        t.idle_rpm = idle_rpm if 0 < idle_rpm < t.max_rpm else 900.0
        t.accel_lat, t.accel_vert, t.accel_long = ax, ay, az
        t.susp_travel = [float(x) for x in susp]
        t.susp_travel_m = [float(x) if math.isfinite(x) else 0.0 for x in travel_m]
        t.slip_ratio = [float(x) for x in slip_ratio]
        t.slip_angle = [float(x) for x in slip_angle]
        t.combined_slip = [float(x) for x in combined]
        t.rumble_strip = [bool(x) for x in rumble]
        t.surface_rumble = [abs(float(x)) for x in surface]     # 0 off strips; ~1.5-2.6 on rumble strips (not 0..1)
        t.cylinders = cylinders
        t.engine_running = t.rpm > 0.0
        t.speed = math.sqrt(vx * vx + vy * vy + vz * vz)

        d = dash_offset(n)
        if d is not None:
            speed, = struct.unpack_from("<f", data, d + 12)
            accel, brake, clutch, handbrake, gear = struct.unpack_from("<5B", data, d + 71)
            t.speed = max(speed, 0.0)
            t.throttle, t.brake = accel / 255.0, brake / 255.0
            t.clutch, t.handbrake = clutch / 255.0, handbrake / 255.0
            t.gear = -1 if gear == 0 else (0 if gear >= 11 else int(gear))   # Forza: 0 = reverse, 11 = neutral
        return t
    return None
