# Impacts and forces

[OpenShaker guide](README.md) › Effects

The effects for hits and forces: Collisions, G-force rumble, Landings and Turbo & reactor boost.

## Collisions

**What you feel:** a hard hit when you crash or make heavy contact.

**How it works.** OpenShaker watches the car's forward and sideways acceleration. A crash shows up as a sudden, large change that normal driving cannot produce. It detects hits in one of two ways:

- **Calibrated presets ("sustained" detector):**
  - A hit fires once when acceleration rises more than 15 m/s² (about 1.5 g) above its recent normal level and stays there for at least 30 ms.
  - It then waits at least 0.3 s, and re-arms once the excess drops below half.
  - Every hit plays at the same strength.
- **Trackmania ("jump" detector):**
  - A hit fires when acceleration changes by more than 60 m/s² (about 6 g) from one frame to the next.
  - Harder hits play stronger: half strength at the threshold, full strength at 600 m/s².
  - It waits at least 0.25 s between hits.

**The sound:**

| Preset | Sound |
|---|---|
| Forza Motorsport, Forza Horizon | One cycle of a 50 Hz square wave (20 ms): a sharp knock |
| Assetto Corsa EVO | A 48 Hz sawtooth burst, 24 ms |
| BeamNG.drive | A 60 Hz sawtooth burst, 17 ms |
| Trackmania | A deep 26 Hz thump that fades out |

A pause or a gap in the data restarts the detector from the current reading, so resuming does not count as a crash.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport | On | 0.9755 | |
| Forza Horizon 5/6 | On | 0.9649 | |
| Assetto Corsa EVO | On | 0.9755 | |
| BeamNG.drive | On | **1.668** | Above full scale, so every hit briefly ducks the whole mix. **Needs Motion Sim.** The level has not been checked against HaptiConnect yet. |
| Trackmania | On | 0.5 | Landings and respawns are filtered out so they do not count as crashes |

**Game data:** forward and sideways acceleration.

**Strength slider:** sets the loudness of the next hit. Once hits reach the limiter's ceiling, more strength only makes the rest of the mix duck harder.

_Code: `ImpactEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

## G-force rumble

**What you feel:** a low rumble that grows as you accelerate, brake and corner hard.

**How it works.** OpenShaker reads the forward/backward g and the sideways g, and looks each one up in a table of strengths. It combines the two and plays one steady tone at that strength. The combined strength is capped at 1.0 unless the preset raises the cap. It needs a speed above 1 m/s.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport | On | 0.12 | 58 Hz. The stronger of the two directions wins, capped at 1.0. **Braking:** starts past 2 m/s² and is full at 8 m/s². **Accelerating:** 0.6 at 4 m/s², 0.78 at 10. **Cornering:** rises from 4 m/s² to full at 8. Below 4 m/s² the cornering table keeps its first value, so a faint 0.02 plays whenever the car moves. |
| Forza Horizon 5/6 | On | 0.28 | 59 Hz. Unless you are braking, forward and sideways are **added together**; while braking, the stronger one wins. Capped at 1.4. |
| Assetto Corsa EVO | On | 0.025 | 58 Hz, **forward acceleration only**: starts at 2 m/s² and is full by 5. Braking and cornering add nothing. |
| BeamNG.drive | On | 0.2488 | 60 Hz. The stronger direction wins, capped at 1.0. **Braking:** from 3 m/s², full at 5. **Accelerating:** nothing until 8 m/s², full at 12. **Cornering:** from 6 m/s², full at 10. **Needs Motion Sim.** |
| Trackmania | **Off** | 0.12 | Off by choice, because Trackmania's 30-90 m/s² cornering loads kept it near full all the time. If you tick it, it plays a 30 Hz tone that is full when \|forward g\| + 0.7 × \|sideways g\| reaches 20 m/s² (this built-in mode plays at 0.6 × the level). |

**Game data:** forward/backward and sideways acceleration, and speed.

**Strength slider:** loudness only.

_Code: `AccelerationEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

## Landings

**What you feel:** a thump when the car touches down after a jump. The faster it was falling, the bigger the thump.

**How it works.** While the car is in the air, OpenShaker remembers when it took off and the fastest downward speed. On touchdown:

- A landing plays only if the car was airborne for at least 0.12 s and falling at least 1.5 m/s.
- The strength scales from 15 % at 1.5 m/s up to full at 15 m/s.
- The sound is a 30 Hz thump, plus a short 60 Hz click that marks the edge of the impact.

A respawn resets it. Small hops are left to [Suspension bumps](Road-and-Suspension.md#suspension-bumps). Trackmania's landing push is also taken out of the g-forces for a moment, so a landing does not count as a collision too.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport, Forza Horizon 5/6, Assetto Corsa EVO, BeamNG.drive | Off | 0.6 if ticked | No ground-contact data, so nothing plays even if you tick it |
| Trackmania | **On** | 0.6 | |

**Game data:** whether the car touches the ground, and its vertical speed. Only Trackmania sends these.

**Strength slider:** sets the loudness of the next landing.

_Code: `LandingEffect` in [`openshaker/effects/trackmania.py`](../../openshaker/effects/trackmania.py)._

## Turbo & reactor boost

**What you feel:** a surge when a boost starts, then a hum while it lasts.

**How it works:**

- **Turbo pad:**
  - When a turbo starts: a 42 Hz surge thump, plus a tone that sweeps up from 35 to 75 Hz over 0.6 s while fading out.
  - It fires only when the boost *starts*, so a held boost does not retrigger it.
  - While the turbo lasts: a 34 Hz hum at 0.25.
- **Reactor boost:**
  - Each time the reactor level goes up: a surge at 70 % strength.
  - While it lasts: the same 34 Hz hum, at 0.2 on level 1 and 0.4 on level 2.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport, Forza Horizon 5/6, Assetto Corsa EVO, BeamNG.drive | Off | 0.4 if ticked | No boost data, so nothing plays even if you tick it |
| Trackmania | **On** | 0.4 | |

**Game data:** turbo state and reactor boost level. Only Trackmania sends these.

**Strength slider:** loudness of the surge, the sweep and the hum.

_Code: `BoostEffect` in [`openshaker/effects/trackmania.py`](../../openshaker/effects/trackmania.py)._

---

**Next:** [The main window](The-Main-Window.md)

**See also:** [Effects overview](Effects-Overview.md) · [Safety](Safety.md)
