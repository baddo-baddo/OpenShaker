# Road and suspension

[OpenShaker guide](README.md) › Effects

The effects that carry the road: Suspension bumps, Kerbs / rough road and Surface feel.

## Suspension bumps

**What you feel:** the road through the seat. That means bumps, ripples, and a low hum that grows as the surface gets rougher.

**How it works.** This effect has several ingredients, and each preset uses a different mix:

- **Road bed (Forza and Assetto Corsa EVO presets):** a continuous low tone around 41 Hz. Its strength follows how fast the suspension is moving, so smooth tarmac is quiet and broken surfaces are louder. It has a slightly buzzy, square-wave character to match HaptiConnect, and plays above 1 m/s.
- **Bumps (Trackmania):**
  - A separate short thump for each wheel when that wheel's suspension moves quickly: 38 Hz at the front, 30 Hz at the rear.
  - Faster movement gives a stronger thump.
  - Each wheel thumps at most once every 0.04 s.
- **Texture (Trackmania):** a fine, low rumble (noise below about 40 Hz) that follows how busy the suspension is overall.
- **Vertical-g thumps (fallback):** when a game sends no suspension movement at all, a thump plays when the vertical g-force jumps suddenly. That is always the case in BeamNG, and in Forza while the car is in the air.

After a pause, a race start or a gap in the data, the effect starts its measurements over. Unpausing never plays a phantom bump.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport | On | 1.6 | Road bed only: 41.2 Hz, following suspension speed, with a 50 ms hold. Per-wheel bumps and texture are off. In the air, a 45 Hz thump plays on vertical-g jumps over 12 m/s², at most every 0.1 s. |
| Forza Horizon 5/6 | On | 0.6 | Road bed that follows suspension movement **in metres**, timed on the game's own clock, frame by frame (no hold). A band of rumble noise at 37-45 Hz is added. Bumps and texture are off. |
| Assetto Corsa EVO | On | 1.0 | Road bed from the game's suspension data, with a 50 ms hold. Bumps and texture are off. |
| BeamNG.drive | On | 0.7 | BeamNG sends no suspension data, so there are **only vertical-g thumps**: 45 Hz at a fixed level, on jumps over 12 m/s², at most every 0.15 s. **Needs Motion Sim.** The level has not been checked against HaptiConnect yet. |
| Trackmania | On | 0.6 | Per-wheel bumps plus texture, no road bed. Suspension is held while a wheel is in the air and settled after landings, so a jump does not turn into a burst of bumps. |

**Game data:** each wheel's suspension travel (Forza Horizon uses metres), the vertical g-force for the fallback, and speed.

**Strength slider:** loudness of every part of the effect.

**Tips:**

- **Assetto Corsa EVO:** *Advanced... → ACE suspension travel scale (m)* (default 0.08) sets how many metres count as full travel. A smaller number makes the same movement count as more travel, so the road bed gets stronger.
- **Trackmania:** big jumps are handled by [Landings](Impacts-and-Forces.md#landings). Small hops are left to this effect.

_Code: `SuspensionEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

## Kerbs / rough road

**What you feel:** the rattle of rumble strips and kerbs, rising in pitch as you go faster.

**How it works.** When the game reports that a wheel is on a rumble strip, a repeating wave plays. Its pitch climbs with speed, the way the ridges pass under you faster. It stops as soon as no wheel is on a strip.

**The details:**

- In Forza Motorsport the pitch is 1.25 Hz per m/s of speed: about 35 Hz at 100 km/h and about 69 Hz at 200 km/h. It is limited to 6-100 Hz.
- The effect also has a built-in rough-road noise, but the calibrated presets do not use it and no shipped preset plays it.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport | On | 0.3 | A pure sine at 1.25 Hz per m/s, 6-100 Hz, at a steady level. Triggered by Forza's per-wheel rumble-strip flags. |
| Forza Horizon 5/6 | On | 1.0 | A richer wave, 6-42 Hz, getting quieter as speed rises. **It plays nothing in Horizon, because the game never sets the rumble-strip flag.** You only hear it in the Demo. |
| Assetto Corsa EVO | **Silent (level 0)** | 0 | HaptiConnect's ACE plugin has no kerb effect. The game does send a car-wide kerb signal. |
| BeamNG.drive | **Silent (level 0)** | 0 | BeamNG sends no kerb data |
| Trackmania | Off | 1.0 | Trackmania sends no kerb data. [Surface feel](#surface-feel) replaces it. |

**Game data:** per-wheel rumble-strip flags (Forza), the kerb vibration signal (Assetto Corsa EVO), and speed.

**Strength slider:** loudness only.

_Code: `RoadEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

## Surface feel

**What you feel:** what the tyres are driving on, whether dirt, gravel, grass, ice, plastic or metal. You also feel water sloshing and splashing, and the roof scraping.

**How it works.** Trackmania reports which material each wheel is touching, and each material has its own texture. That texture is a band of rumble noise with its own depth and level. "Resonant" materials such as plastic, rubber and metal also add a tone. Among the wheels on the ground, the strongest noise texture and the strongest tone are played. They can come from different wheels.

It grows with speed: nothing below 2 m/s, reaching full strength at about 150 km/h.

**Water and roof:**

- **In water** (more than 5 % submerged): a very low slosh (below about 18 Hz) that grows the deeper you are. It keeps at least 20 % strength even when slow.
- **Hitting water** faster than 5 m/s (18 km/h): a 22 Hz splash thump, stronger the faster you hit.
- **Roof scraping the ground:** a scrape noise (up to about 85 Hz), with at least 30 % strength even when slow.

**Surface textures.** "Depth" is the noise's brightness: a lower number means a deeper rumble. "Level" is how strong it is.

| Group | Materials (depth Hz, level) |
|---|---|
| Smooth, nothing added | Asphalt, WetAsphalt, Tech, TechGround, TechSafe |
| Smooth, barely there | TechArmor (0.02), Concrete (0.03), RoadSynthetic (0.05), WetPavement (0.05), Pavement (0.06) |
| Stairs | PavementStair (40, 0.3) |
| Loose | Dirt (35, 0.55), DirtRoad (35, 0.5), WetDirtRoad (30, 0.5), Gravel (45, 0.6), Sand (28, 0.45), Rock (50, 0.5), Stone (50, 0.45) |
| Soft | Grass and Green (22, 0.4), WetGrass (20, 0.35), Forest (25, 0.45), Wheat (20, 0.3) |
| Slick | Ice (70, 0.05), RoadIce (70, 0.04), Snow (40, 0.15) |
| Wood | Wood (45, 0.3), SlidingWood (45, 0.25) |

Resonant materials add a tone:

| Material | Tone (Hz, level) |
|---|---|
| Plastic | 62 Hz, 0.3 (on top of a 50 Hz / 0.15 rumble) |
| Rubber | 55 Hz, 0.3 (on top of a 45 Hz / 0.2 rumble) |
| SlidingRubber | 55 Hz, 0.25 |
| RubberBand | 58 Hz, 0.3 |
| Metal | 48 Hz, 0.3 (on top of a 60 Hz / 0.1 rumble) |
| ResonantMetal | 44 Hz, 0.4 |
| MetalTrans | 50 Hz, 0.25 |
| MetalFence | 46 Hz, 0.35 |
| TechMagnetic | 70 Hz, 0.15 |
| TechSuperMagnetic, TechMagneticAccel | 70 Hz, 0.2 |

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport, Forza Horizon 5/6, Assetto Corsa EVO, BeamNG.drive | Off | 0.5 if ticked | No surface data, so nothing plays even if you tick it |
| Trackmania | **On** | 0.5 | Replaces Kerbs / rough road |

**Game data:** the material under each wheel, which wheels touch the ground, water depth, roof contact and speed. Only Trackmania sends these.

**Strength slider:** loudness of everything in this effect, including the splash.

_Code: `SurfaceEffect` in [`openshaker/effects/trackmania.py`](../../openshaker/effects/trackmania.py)._

---

**Next:** [Grip and braking](Grip-and-Braking.md)

**See also:** [Effects overview](Effects-Overview.md) · [Trackmania](Trackmania.md)
