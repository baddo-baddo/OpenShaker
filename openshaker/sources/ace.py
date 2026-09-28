"""Assetto Corsa EVO shared-memory source.

Reads the game's named file mappings directly (no game setting needed):
  Local\\acevo_pmf_physics   800 bytes, _pack_=4, updated every physics step
  Local\\acevo_pmf_graphics  only the status field is used (2 == live session)
Falls back to the AC1/ACC names (Local\\acpmf_*) whose first 416 bytes share the same layout.
Only opens mappings that already exist, so the game always owns them.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import time

from ..telemetry import Telemetry
from .base import Source

FILE_MAP_READ = 0x0004
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.OpenFileMappingW.restype = wt.HANDLE
_k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k32.UnmapViewOfFile.restype = wt.BOOL
_k32.CloseHandle.argtypes = [wt.HANDLE]
_k32.CloseHandle.restype = wt.BOOL


class _MemoryInfo(ctypes.Structure):          # MEMORY_BASIC_INFORMATION
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD), ("RegionSize", ctypes.c_size_t),
                ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]


_k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MemoryInfo), ctypes.c_size_t]
_k32.VirtualQuery.restype = ctypes.c_size_t

PHYSICS_NAMES = ("Local\\acevo_pmf_physics", "Local\\acpmf_physics")
GRAPHICS_NAMES = ("Local\\acevo_pmf_graphics", "Local\\acpmf_graphics")
PHYSICS_BYTES = 800
AC_LIVE = 2

# physics offsets (EVO layout; the first 416 bytes are the AC1-compatible prefix)
OFF = dict(packetId=0, gas=4, brake=8, gear=16, rpms=20, speedKmh=28, accG=44, wheelSlip=56,
           wheelAngularSpeed=104, suspensionTravel=184, abs=252, clutch=364,
           currentMaxRpm=588, slipRatio=640, slipAngle=656, tcInAction=672, absInAction=676,
           ignitionOn=772, isEngineRunning=780, kerbVibration=784, slipVibrations=788,
           roadVibrations=792, absVibrations=796)


class SharedMem:
    def __init__(self, names, nbytes: int) -> None:
        self.names = names
        self.nbytes = nbytes
        self.handle = None
        self.ptr = None
        self.name = None
        self.readable = 0

    def open(self) -> bool:
        for name in self.names:
            h = _k32.OpenFileMappingW(FILE_MAP_READ, False, name)
            if not h:
                continue
            p = _k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)  # 0 = map the whole object
            if not p:
                _k32.CloseHandle(h)
                continue
            self.handle, self.ptr, self.name = h, p, name
            info = _MemoryInfo()                   # never read past the end of a smaller mapping
            if _k32.VirtualQuery(p, ctypes.byref(info), ctypes.sizeof(info)):
                self.readable = min(self.nbytes, int(info.RegionSize))
            return True
        return False

    def read(self) -> bytes:
        """Always nbytes long: whatever the mapping does not hold reads as zeros."""
        data = ctypes.string_at(self.ptr, self.readable) if self.ptr and self.readable else b""
        return data.ljust(self.nbytes, b"\0")

    def close(self) -> None:
        if self.ptr:
            _k32.UnmapViewOfFile(self.ptr)
        if self.handle:
            _k32.CloseHandle(self.handle)
        self.handle = self.ptr = self.name = None
        self.readable = 0

    @property
    def is_open(self) -> bool:
        return self.ptr is not None


def parse_physics(d: bytes, evo: bool, susp_scale_m: float, max_rpm_fallback: float) -> Telemetry:
    t = Telemetry()
    gas, brake = struct.unpack_from("<2f", d, OFF["gas"])
    gear, rpms = struct.unpack_from("<2i", d, OFF["gear"])
    speed_kmh, = struct.unpack_from("<f", d, OFF["speedKmh"])
    acc_lat, acc_vert, acc_long = struct.unpack_from("<3f", d, OFF["accG"])
    wheel_slip = struct.unpack_from("<4f", d, OFF["wheelSlip"])
    susp = struct.unpack_from("<4f", d, OFF["suspensionTravel"])
    clutch, = struct.unpack_from("<f", d, OFF["clutch"])

    t.gear = gear - 1                       # game: 0 reverse, 1 neutral, 2 first
    t.rpm = float(max(rpms, 0))
    t.speed = max(speed_kmh, 0.0) / 3.6
    t.throttle, t.brake, t.clutch = _c01(gas), _c01(brake), _c01(clutch)
    t.accel_lat, t.accel_vert, t.accel_long = acc_lat * 9.81, acc_vert * 9.81, acc_long * 9.81
    t.combined_slip = [float(x) for x in wheel_slip]
    t.susp_travel = [abs(x) / susp_scale_m for x in susp]
    t.susp_travel_m = [abs(float(x)) for x in susp]      # the game's own metres, before the scale above
    t.idle_rpm = 1000.0

    if evo:
        max_rpm, = struct.unpack_from("<i", d, OFF["currentMaxRpm"])
        slip_ratio = struct.unpack_from("<4f", d, OFF["slipRatio"])
        slip_angle = struct.unpack_from("<4f", d, OFF["slipAngle"])
        tc_act, abs_act = struct.unpack_from("<2i", d, OFF["tcInAction"])
        ignition, starter, running = struct.unpack_from("<3i", d, OFF["ignitionOn"])
        kerb, slipv, road, absv = struct.unpack_from("<4f", d, OFF["kerbVibration"])
        t.max_rpm = float(max_rpm) if max_rpm > 0 else max_rpm_fallback
        if t.speed > 1.0:                                  # slip is undefined with the wheels (nearly) stopped
            # ACE gives a true slip ratio (~0.05 while gripping); Forza's is ~0 until grip is lost.
            # Re-zero the driving side so both land on the same scale (1.0 ~= grip limit).
            t.slip_ratio = [(max(x - 0.05, 0.0) / 0.15) if x >= 0 else (x / 0.15) for x in slip_ratio]
            t.slip_angle = [x / 0.20 for x in slip_angle]  # ~0.2 rad = peak grip -> 1.0
        else:
            t.slip_ratio = [0.0] * 4
            t.slip_angle = [0.0] * 4
        t.tc_active = tc_act != 0
        t.abs_active = abs_act != 0
        t.engine_running = running != 0
        t.has_vib_hints = True
        t.kerb_vib, t.slip_vib, t.road_vib, t.abs_vib = _c01(kerb), _c01(slipv), _c01(road), _c01(absv)
        t.rumble_strip = [kerb > 0.05] * 4
    else:
        t.max_rpm = max_rpm_fallback
        t.slip_ratio = [0.0] * 4
        t.engine_running = t.rpm > 50
    return t


LOG_POLL_HZ = 1000.0     # while a drive is logged: ACE updates ~316 times a second, catch every packet


class ACESource(Source):
    name = "ace"

    def __init__(self, poll_hz: float = 200.0, susp_scale_m: float = 0.10,
                 physics_names=PHYSICS_NAMES, graphics_names=GRAPHICS_NAMES) -> None:
        super().__init__()
        self.period = 1.0 / max(poll_hz, 20.0)
        self.susp_scale_m = susp_scale_m
        self.phys = SharedMem(physics_names, PHYSICS_BYTES)
        self.gfx = SharedMem(graphics_names, 8)
        self._max_rpm_seen = 0.0

    def poll_period(self) -> float:
        """The configured rate for the live haptics; every packet while something logs the drive."""
        return min(self.period, 1.0 / LOG_POLL_HZ) if self.listeners else self.period

    def run(self) -> None:
        last_id = None
        last_change = time.perf_counter()
        while not self.stopping():
            if not self.phys.is_open:
                self.status = "waiting for Assetto Corsa EVO"
                if not self.phys.open():
                    time.sleep(0.5)
                    continue
                self.gfx.open()
                self.status = f"attached to {self.phys.name}"
                last_id, last_change = None, time.perf_counter()
            data = self.phys.read()
            packet_id, = struct.unpack_from("<i", data, OFF["packetId"])
            now = time.perf_counter()
            if packet_id != last_id:
                last_id, last_change = packet_id, now
                evo = "acevo" in (self.phys.name or "")
                tele = parse_physics(data, evo, self.susp_scale_m, max(self._max_rpm_seen, 6000.0))
                self._max_rpm_seen = max(self._max_rpm_seen, tele.rpm)
                live = True
                if self.gfx.is_open:
                    status, = struct.unpack_from("<i", self.gfx.read(), 4)
                    live = status == AC_LIVE
                tele.active = live and (tele.engine_running or tele.rpm > 0 or tele.speed > 0.5)
                tele.raw = data                  # the whole physics page, so a logged drive replays byte-exact
                self.publish(tele)
            elif now - last_change > 5.0:
                # game closed or session ended: drop the mapping and wait for a fresh one
                self.phys.close()
                self.gfx.close()
            time.sleep(self.poll_period())
        self.phys.close()
        self.gfx.close()


def _c01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)
