from .base import Effect  # noqa: F401
from .racing import (ABSEffect, AccelerationEffect, EngineEffect, GearShiftEffect, ImpactEffect,
                     RoadEffect, ShiftIndicatorEffect, SuspensionEffect, WheelLockEffect, WheelSlipEffect)
from .trackmania import BoostEffect, GripMarginEffect, LandingEffect, SurfaceEffect

REGISTRY = {
    "engine": EngineEffect,
    "gear_shift": GearShiftEffect,
    "wheel_lock": WheelLockEffect,
    "wheel_slip": WheelSlipEffect,
    "abs": ABSEffect,
    "suspension": SuspensionEffect,
    "road": RoadEffect,
    "impact": ImpactEffect,
    "acceleration": AccelerationEffect,
    "shift_indicator": ShiftIndicatorEffect,
    "grip_margin": GripMarginEffect,
    "surface": SurfaceEffect,
    "landing": LandingEffect,
    "boost": BoostEffect,
}


def build_effects(cfg_effects: dict, sr: int) -> list:
    return [cls(cfg_effects.get(name, {}), sr) for name, cls in REGISTRY.items()]
