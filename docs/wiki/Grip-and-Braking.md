# Grip and braking

[OpenShaker guide](README.md) › Effects

The effects about the tyres: Wheel lock, Wheel slip / slide, ABS pulse and the Grip limit warning.

## Wheel lock (braking)

**What you feel:** a steady buzz for as long as a wheel is locked under braking.

**How it works.** OpenShaker compares how fast each wheel turns with how fast the car is moving. If you are braking and a wheel turns much slower than the road under it (a lock-up), a tone plays until it lets go. The worst wheel counts.

**It only plays when all of these are true:**

- brake or handbrake is above 5 %;
- the car is faster than 2 m/s (about 7 km/h);
- the wheel's slip is past the preset's threshold.

**About the slip numbers:** slip is measured so that 1.0 is roughly the limit of grip. A threshold of 3.5 means a hard lock-up, well past the limit.

**The details:**

- **Calibrated presets** work like a switch: nothing below the threshold, full level above it, as a pure tone.
- **Trackmania** fades in instead. It starts at slip 1.0 and is full at 3.0, with a 28 Hz tone plus a low rumble noise.

**Default in each preset:**

| Preset | Default | Level | Threshold | Tone |
|---|---|---|---|---|
| Forza Motorsport | On | 0.18 | 3.5 | 56.4 Hz |
| Forza Horizon 5/6 | On | 0.18 | **1.0** (triggers much earlier) | 54.5 Hz |
| Assetto Corsa EVO | On | 0.085 | 3.5 | 56.4 Hz |
| BeamNG.drive | On | 1.0 | 3.5 (wheel speed at or below 47.5 % of ground speed) | 56.3 Hz |
| Trackmania | On | 0.18 | fades in from 1.0 to 3.0 | 28 Hz + rumble |

**Game notes:**

- **Forza Motorsport, Sled format:** no brake data, so it never plays.
- **Assetto Corsa EVO:** works. The older Assetto Corsa and ACC send no slip, so it does not play there.
- **BeamNG:** it needs **both** OutGauge (brake and wheel speed) and Motion Sim (ground speed). The slip is one figure for the whole car, so it cannot tell which wheel locked. The BeamNG level has not been checked against HaptiConnect yet.
- **Trackmania:** slip is worked out from wheel rotation and a wheel size that OpenShaker learns while you drive straight: above 8 m/s, little steering, no brake, no slip. Until it has learned the size, and for wheels in the air or still settling after a landing, the slip reads 0. Trackmania sends no handbrake.

**Strength slider:** loudness only. The threshold stays the same.

**Tip:** BeamNG lock-ups are strong. In the calibration notes, wheel lock accounted for about half of the moments when BeamNG's output reached the limit. If lock-ups drown everything else, lower this one.

_Code: `WheelLockEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

## Wheel slip / slide

**What you feel:** a buzz when the wheels spin under power, and a rumble or tone when the car slides sideways.

**How it works.** Two things are measured separately:

- **Spin:** a wheel turning faster than the road. It needs a speed above 1 m/s and, unless the preset removes this check, more than 5 % throttle.
- **Slide:** the tyre's sideways slip angle. It needs a speed above 4 m/s (about 14 km/h).

Each part fades in between a start value and a full value. The calibrated presets play both as tones. Trackmania plays spin as a tone and slide as a low rumble noise.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport | On | 0.1313 | Spin counts on the rear wheels only, with no throttle check. Spin and slide both fade in from 0.45 to 0.6, below the grip limit. 54.5 Hz tones with a touch of buzz. A wheel past 1.4 spin or 1.2 slide stops counting, so very deep slides go quiet again. |
| Forza Horizon 5/6 | On | 0.12 | Same, but without that upper cut-off |
| Assetto Corsa EVO | On | 0.07 | Rear wheels, no throttle check. Spin 1.4 → 2.0, slide 1.1 → 1.5. Spin also follows the game's own slip vibration signal, whichever is stronger. |
| BeamNG.drive | **Silent (level 0)** | 0 | HaptiConnect's BeamNG preset has no slip effect |
| Trackmania | On | 0.2 | All four wheels, throttle check on. Slide 0.05 → 0.6 as rumble noise; spin 1.0 → 4.0 as a 32 Hz tone. Spin was softened, yet a standing burnout still reads full. |

**Game data:** per-wheel slip ratio (spin), slip angle (slide), throttle and speed. Assetto Corsa EVO also sends its own slip vibration signal.

- The older **Assetto Corsa and ACC** send no slip, so there is nothing to play.
- **BeamNG** only has a car-wide spin figure and no slide angle, and the preset is at level 0 anyway.
- **Trackmania's** slide comes from the game's own slip value × the car's sideways speed (full at 12 m/s sideways). Spin comes from the learned wheel size.

**Strength slider:** loudness only.

**Tip:** in Trackmania, if you want a warning *before* the car lets go on dirt, grass or snow, see [Grip limit warning](#grip-limit-warning).

_Code: `WheelSlipEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

## ABS pulse

**What you feel:** a pulsing vibration under braking while ABS is working.

**How it works.** While the game says ABS is active, a 50 Hz tone is switched smoothly on and off 13 times a second. When Assetto Corsa EVO sends its own ABS vibration signal, that signal sets the strength directly.

> **With the shipped presets, ABS pulse plays in no live game.** It only plays in the Demo, and only while a Forza preset is active.

**Default in each preset:**

| Preset | Default | Level | Why it does not play |
|---|---|---|---|
| Forza Motorsport | On | 0.25 | OpenShaker gets no ABS signal from Forza's Data Out, so it never triggers |
| Forza Horizon 5/6 | On | 0.25 | Same reason |
| Assetto Corsa EVO | **Silent (level 0)** | 0 | The game does send ABS data. Level 0 is "an engineering choice, not a measured absence". |
| BeamNG.drive | **Silent (level 0)** | 0 | BeamNG sends the ABS dash light (counted only while braking), but HaptiConnect's BeamNG preset has no ABS |
| Trackmania | Off | 0.25 | Trackmania sends no ABS data |

**Game data:** the game's "ABS active" flag, or Assetto Corsa EVO's ABS vibration signal.

**Strength slider:** in the Forza presets it only changes the ABS in the Demo. Everywhere else it has no audible effect.

_Code: `ABSEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

## Grip limit warning

**What you feel:** a pulsing tone that grows and pulses faster as the tyres near the limit of grip. It goes quiet once they let go, and [Wheel slip / slide](#wheel-slip--slide) takes over.

**How it works (Trackmania, where it is on).** OpenShaker estimates how close the car is to sliding. It compares:

- the sideways g-force with the grip limit of the surface; and
- the car's body slip angle with that surface's limit.

Whichever is closer counts. The warning starts at 60 % of the limit and is full at 100 %. As soon as any wheel starts to slide (Trackmania's own slip value goes above 0), it stops.

**It works on loose surfaces only:**

- At least half of the wheels touching the ground must be on one of the surfaces listed below.
- The most common listed surface under the car sets the limits.
- **Tarmac is not listed, so there is no warning on tarmac.** In testing, the Stadium car held 90 m/s² (about 9 g) sideways without letting go.
- It only works above 8 m/s (about 29 km/h).

| Surface | Sideways limit (m/s²) | Body slip limit |
|---|---|---|
| Dirt, DirtRoad, Gravel | 18 | 5° |
| WetDirtRoad | 15 | 5° |
| Sand | 15 | 5° |
| Grass, Green, Forest, Wheat | 14 | 5° |
| WetGrass | 12 | 5° |
| Snow | 10 | 5° |
| Ice, RoadIce | 6 | 4° |
| WetAsphalt, WetPavement | 30 | 5° |

These limits are first guesses. When the game gives no per-wheel surfaces, 20 m/s² and 6° are used. A preset file can override the table.

**The sound:**

- a 55 Hz tone that grows steeply towards the limit;
- a strong pulse (70 % deep) whose rate rises from 4 to 14 pulses a second as the margin shrinks.

**In other games** the warning is off by default, but you can tick it. It then uses the game's own slip numbers. It warns as the largest slip angle or slip ratio goes from 0.6 to 1.0 of the grip limit, and goes quiet at or past the limit. It needs slip data:

- It works in Forza and Assetto Corsa EVO.
- In BeamNG it only has the car-wide wheel-speed figure.
- In the older Assetto Corsa and ACC there is nothing to go on.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport | Off | 0.3 if ticked | Slip-based version |
| Forza Horizon 5/6 | Off | 0.3 if ticked | Slip-based version |
| Assetto Corsa EVO | Off | 0.3 if ticked | Slip-based version |
| BeamNG.drive | Off | 0.3 if ticked | Car-wide wheel-speed figure only |
| Trackmania | **On** | 0.3 | Loose surfaces only |

**Strength slider:** loudness only. The limits and the 60 % starting point stay the same.

**Tip:** with a source copy of OpenShaker, `python -m openshaker.tm_grip <drive folder> --apply` learns the grip limits from a drive you recorded with `--log`. See [Calibration](../CALIBRATION.md).

_Code: `GripMarginEffect` in [`openshaker/effects/trackmania.py`](../../openshaker/effects/trackmania.py)._

---

**Next:** [Impacts and forces](Impacts-and-Forces.md)

**See also:** [Effects overview](Effects-Overview.md) · [Trackmania](Trackmania.md)
