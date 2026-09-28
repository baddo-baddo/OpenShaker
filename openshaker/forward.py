"""Bridge: forward normalized telemetry to HaptiConnect in the packet format one of its plugins expects.

  outgauge    BeamNG.drive plugin, 127.0.0.1:4444, the 136-byte extended OutGauge struct
  horizon     Forza Horizon 5 plugin, 127.0.0.1:5301, the 324-byte Horizon "Data Out" packet
  motorsport  Forza Motorsport plugin, 127.0.0.1:5305, the 331-byte Motorsport packet
Any game this app can read (Forza Horizon 6, Assetto Corsa EVO, ...) can therefore be presented to
HaptiConnect as one of the games it supports. The Forza plugins only listen while the matching game
process is running (the game can sit at its menu).
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Callable, Optional

from .telemetry import Telemetry

OG_KM, OG_BAR = 16384, 32768
DL_TC, DL_HANDBRAKE, DL_ABS = 1 << 4, 1 << 2, 1 << 10
FMT = "<f4sH2xfb3x4fi5f2I3f16s16si4fi"
SIZE = struct.calcsize(FMT)  # 136
FORMATS = ("outgauge", "horizon", "motorsport", "sled", "raw")
DEFAULT_PORT = {"outgauge": 4444, "horizon": 5301, "motorsport": 5305, "sled": 5305}
WHEEL_RADIUS = 0.33


def _c01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def pack_outgauge(t: Telemetry, accel_scale: float = 1.0) -> bytes:
    slip = max(t.slip_ratio, key=abs) if t.slip_ratio else 0.0
    wheelspeed = max(t.speed * (1.0 + slip * 0.15), 0.0)
    dash = DL_HANDBRAKE | DL_ABS | DL_TC
    show = ((DL_HANDBRAKE if t.handbrake > 0.5 else 0)
            | (DL_ABS if t.abs_active else 0)
            | (DL_TC if t.tc_active else 0))
    return struct.pack(
        FMT,
        0.0, b"beam", OG_KM | OG_BAR, float(t.gear), 0,
        t.speed, wheelspeed, t.speed, t.rpm, int(t.max_rpm),
        0.0, 90.0, 0.5, 0.0, 90.0,
        dash, show,
        t.throttle, t.brake, t.clutch,
        b"", b"", 0,
        t.accel_lat * accel_scale, t.accel_long * accel_scale,
        t.accel_vert * accel_scale,
        (t.accel_vert if t.accel_vert2 is None else t.accel_vert2) * accel_scale,
        1 if (t.engine_running and t.active) else 0,
    )


def pack_forza(t: Telemetry, kind: str = "horizon", accel_scale: float = 1.0) -> bytes:
    """Build a Forza Data Out packet (Horizon 324 bytes or Motorsport 331 bytes) from telemetry."""
    horizon = kind == "horizon"
    buf = bytearray(324 if horizon else 331)
    struct.pack_into("<i", buf, 0, 1 if t.active else 0)
    struct.pack_into("<I", buf, 4, int(time.perf_counter() * 1000.0) & 0xFFFFFFFF)
    struct.pack_into("<3f", buf, 8, t.max_rpm, t.idle_rpm, t.rpm)
    struct.pack_into("<3f", buf, 20, t.accel_lat * accel_scale, t.accel_vert * accel_scale, t.accel_long * accel_scale)
    struct.pack_into("<3f", buf, 32, 0.0, 0.0, t.speed)
    susp = [_c01(x) for x in t.susp_travel]
    struct.pack_into("<4f", buf, 68, *susp)
    struct.pack_into("<4f", buf, 84, *[float(x) for x in t.slip_ratio])
    struct.pack_into("<4f", buf, 100, *[max(t.speed * (1.0 + s * 0.15), 0.0) / WHEEL_RADIUS for s in t.slip_ratio])
    struct.pack_into("<4i", buf, 116, *[1 if r else 0 for r in t.rumble_strip])
    struct.pack_into("<4f", buf, 148, *[float(x) for x in t.surface_rumble])
    struct.pack_into("<4f", buf, 164, *[float(x) for x in t.slip_angle])
    combined = [float(c) if c else (sr * sr + sa * sa) ** 0.5
                for c, sr, sa in zip(t.combined_slip, t.slip_ratio, t.slip_angle)]
    struct.pack_into("<4f", buf, 180, *combined)
    struct.pack_into("<4f", buf, 196, *[x * 0.15 for x in susp])
    struct.pack_into("<5i", buf, 212, 1, 7, 800, 1, int(t.cylinders or 6))
    d = 244 if horizon else 232
    if horizon:
        struct.pack_into("<i2f", buf, 232, 0, 0.0, 0.0)          # CarGroup, smashable fields
    struct.pack_into("<3f", buf, d, 0.0, 0.0, 0.0)               # position
    struct.pack_into("<3f", buf, d + 12, t.speed, 0.0, 0.0)      # speed m/s, power, torque
    struct.pack_into("<4f", buf, d + 24, 70.0, 70.0, 70.0, 70.0)  # tire temps
    struct.pack_into("<3f", buf, d + 40, 0.0, 0.5, 0.0)          # boost, fuel, distance
    struct.pack_into("<5B", buf, d + 71, int(_c01(t.throttle) * 255), int(_c01(t.brake) * 255),
                     int(_c01(t.clutch) * 255), int(_c01(t.handbrake) * 255), forza_gear_byte(t.gear))
    return bytes(buf)


def forza_gear_byte(gear: int) -> int:
    """Normalized gear -> Forza's gear byte: 0 = reverse, 1..10 = gears, 11 = neutral.

    Normalized telemetry uses -1 for reverse and 0 for neutral (sources/forza.py, sources/ace.py). Drive
    logs written before 2026-09-12 stored Forza's neutral as 11, so 11 and above also mean neutral.
    HaptiConnect fires a gear-shift burst on every gear-byte change, so neutral must not become reverse.
    """
    g = int(gear)
    if g < 0:
        return 0
    if g == 0 or g >= 11:
        return 11
    return min(g, 10)


def horizon_from_raw(raw: bytes) -> Optional[bytes]:
    """A logged Forza packet as the 324-byte Horizon layout, byte for byte (HaptiConnect's Horizon plugin,
    and its Motorsport plugin, which reads the dash at the Horizon offset).

    324 bytes (Horizon): unchanged. 331 bytes (Motorsport Car Dash): the 232-byte sled is kept, the 12-byte
    Horizon block (232..243) is zero, the 79-byte dash tail moves from 232..310 to 244..322 and one pad
    byte follows; the Motorsport tyre-wear and track-ordinal tail (311..330) has no Horizon slot. Sled
    (232 bytes, no dash) and anything else: None.
    """
    n = len(raw)
    if n == 324:
        return bytes(raw)
    if n == 331:
        return bytes(raw[:232]) + bytes(12) + bytes(raw[232:311]) + b"\x00"
    return None


def pack(t: Telemetry, fmt: str, accel_scale: float = 1.0) -> bytes:
    if fmt == "raw":                       # a logged packet sent as it is (replay prepares it with horizon_from_raw)
        if not t.raw:
            raise ValueError("fmt 'raw' needs the packet in Telemetry.raw")
        return bytes(t.raw)
    if fmt == "outgauge":
        return pack_outgauge(t, accel_scale)
    if fmt in ("horizon", "motorsport"):
        return pack_forza(t, fmt, accel_scale)
    if fmt == "sled":                      # Forza Motorsport "Sled" = the first 232 bytes (no dash tail)
        return pack_forza(t, "motorsport", accel_scale)[:232]
    raise ValueError(f"unknown forward format {fmt!r}; use one of {FORMATS}")


class TelemetryForwarder:
    def __init__(self, latest: Callable[[], Optional[Telemetry]], host: str = "127.0.0.1",
                 port: int = 4444, rate_hz: float = 60.0, accel_scale: float = 1.0,
                 fmt: str = "outgauge") -> None:
        if fmt not in FORMATS:
            raise ValueError(f"unknown forward format {fmt!r}; use one of {FORMATS}")
        self.latest = latest
        self.host, self.port = host, int(port)
        self.period = 1.0 / max(rate_hz, 1.0)
        self.accel_scale = accel_scale
        self.fmt = fmt
        self.sent = 0
        self.rate = 0.0
        self.error: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="telemetry-forward", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        nxt = time.perf_counter()
        count, t_rate = 0, nxt
        try:
            while not self._stop.is_set():
                tele = self.latest()
                if tele is not None:
                    try:
                        sock.sendto(pack(tele, self.fmt, self.accel_scale), (self.host, self.port))
                        self.sent += 1
                        count += 1
                    except OSError as exc:
                        self.error = str(exc)
                now = time.perf_counter()
                if now - t_rate >= 1.0:
                    self.rate = count / (now - t_rate)
                    count, t_rate = 0, now
                nxt += self.period
                delay = nxt - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    nxt = time.perf_counter()
        finally:
            sock.close()


