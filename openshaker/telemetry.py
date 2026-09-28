"""Normalized telemetry frame shared by every game source.

Conventions (every source converts into these):
  speed            m/s
  accel_*          m/s^2 in the car body frame (+lat = right, +long = forward, +vert = up)
  slip_ratio       per wheel, normalized so |1.0| ~= grip limit; negative = wheel slower than car (locking)
  slip_angle       per wheel, normalized so |1.0| ~= grip limit
  susp_travel      per wheel, fraction of full suspension travel (~0..1)
  susp_travel_m    per wheel, suspension travel in metres where the game reports it (Forza, ACE); else zeros
  gear             -1 reverse, 0 neutral, 1.. forward
  rumble_strip     per wheel, True while on a rumble strip / kerb
  surface_rumble   per wheel, 0..1 road roughness
  *_vib            0..1 vibration hints if the game supplies them (Assetto Corsa EVO does)
Wheel order is always FL, FR, RL, RR.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

WHEELS = ("FL", "FR", "RL", "RR")


def _zeros4() -> List[float]:
    return [0.0, 0.0, 0.0, 0.0]


def _false4() -> List[bool]:
    return [False, False, False, False]


@dataclass
class Telemetry:
    source: str = ""
    seq: int = 0
    t: float = 0.0
    active: bool = False
    engine_running: bool = True
    rpm: float = 0.0
    max_rpm: float = 8000.0
    idle_rpm: float = 900.0
    gear: int = 0
    speed: float = 0.0
    throttle: float = 0.0
    brake: float = 0.0
    clutch: float = 0.0
    handbrake: float = 0.0
    accel_lat: float = 0.0
    accel_long: float = 0.0
    accel_vert: float = 0.0
    slip_ratio: List[float] = field(default_factory=_zeros4)
    slip_angle: List[float] = field(default_factory=_zeros4)
    combined_slip: List[float] = field(default_factory=_zeros4)
    susp_travel: List[float] = field(default_factory=_zeros4)
    susp_travel_m: List[float] = field(default_factory=_zeros4)
    rumble_strip: List[bool] = field(default_factory=_false4)
    surface_rumble: List[float] = field(default_factory=_zeros4)
    abs_active: bool = False
    tc_active: bool = False
    cylinders: int = 0
    has_vib_hints: bool = False
    kerb_vib: float = 0.0
    slip_vib: float = 0.0
    road_vib: float = 0.0
    abs_vib: float = 0.0
    raw: Optional[bytes] = field(default=None, repr=False, compare=False)   # original packet, if any
    packet_ms: Optional[int] = None        # the game's own packet clock (Forza TimestampMS), if it sends one
    accel_vert2: Optional[float] = None    # BeamNG's second (smoothed) vertical g channel; None = same as accel_vert
    extra: dict = field(default_factory=dict, repr=False, compare=False)   # game-specific values (e.g. Trackmania)

    @property
    def rpm_norm(self) -> float:
        span = max(self.max_rpm - self.idle_rpm, 1.0)
        return min(max((self.rpm - self.idle_rpm) / span, 0.0), 1.0)

    def summary(self) -> str:
        return (f"rpm {self.rpm:5.0f}/{self.max_rpm:5.0f} gear {self.gear:2d} "
                f"{self.speed * 3.6:5.1f} km/h thr {self.throttle:.2f} brk {self.brake:.2f} "
                f"g({self.accel_lat / 9.81:+.2f},{self.accel_long / 9.81:+.2f},{self.accel_vert / 9.81:+.2f})")
