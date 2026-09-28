# Effects overview

[OpenShaker guide](README.md) › Effects

What the 14 effects are, which ones play in which game and why, what the strength sliders do, and how the mix is kept safe.

> **Calibrated presets.** The Forza, Assetto Corsa EVO and BeamNG presets were fitted to the output of HaptiConnect 2.7.0 (ButtKicker's own app) on a ButtKicker PRO. HaptiConnect has no Trackmania support to compare against, so every Trackmania value is a first guess, checked on real drives and by feel. See [How it was tuned](../HOW_IT_WAS_TUNED.md).

## At a glance

| Effect (as named in the window) | What you feel | Kind |
|---|---|---|
| Engine RPM | A hum whose pitch follows the revs | Continuous |
| Gear shift | A short kick on each gear change | One-shot |
| Wheel lock (braking) | A buzz while a wheel locks under braking | While locked |
| Wheel slip / slide | Wheelspin buzz and a sideways-slide rumble | While slipping |
| ABS pulse | A pulsing vibration while ABS works | While ABS is active |
| Suspension bumps | Bumps and a low hum that grows on rough road | Continuous and one-shots |
| Kerbs / rough road | The rattle of rumble strips, rising in pitch with speed | While on a kerb |
| Collisions | A hard hit when you crash | One-shot |
| G-force rumble | A rumble that grows with acceleration, braking and cornering | Continuous |
| Shift indicator | A felt "shift light" near the rev limit | Near redline |
| Grip limit warning | A pulse that speeds up as the tyres near the limit | Pulsing |
| Surface feel | What the tyres are driving on, plus water and roof scrapes | Continuous |
| Landings | A thump on touchdown after a jump | One-shot |
| Turbo & reactor boost | A surge when a boost starts, then a hum | One-shot and hum |

**Quick answers:**

- **ABS pulse does not play in any game** with the shipped presets. It only plays in the Demo. See [ABS pulse](Grip-and-Braking.md#abs-pulse).
- **Kerbs only play in Forza Motorsport.** Forza Horizon never tells OpenShaker when you are on a kerb. See [Kerbs / rough road](Road-and-Suspension.md#kerbs--rough-road).
- **Surface feel, Landings and Turbo & reactor boost only work in Trackmania.** No other game sends the data they need.
- **BeamNG needs both OutGauge and Motion Sim ticked** in the game. Without Motion Sim you get no collisions, bumps, G-force or wheel lock.
- **Forza Motorsport must use the "Car Dash" Data Out format.** "Sled" has no gear or pedal data, so gear shifts and wheel lock never play.

Each effect has its own section: [Engine RPM](Engine-and-Gears.md#engine-rpm) · [Gear shift](Engine-and-Gears.md#gear-shift) · [Shift indicator](Engine-and-Gears.md#shift-indicator) · [Suspension bumps](Road-and-Suspension.md#suspension-bumps) · [Kerbs / rough road](Road-and-Suspension.md#kerbs--rough-road) · [Surface feel](Road-and-Suspension.md#surface-feel) · [Wheel lock](Grip-and-Braking.md#wheel-lock-braking) · [Wheel slip / slide](Grip-and-Braking.md#wheel-slip--slide) · [ABS pulse](Grip-and-Braking.md#abs-pulse) · [Grip limit warning](Grip-and-Braking.md#grip-limit-warning) · [Collisions](Impacts-and-Forces.md#collisions) · [G-force rumble](Impacts-and-Forces.md#g-force-rumble) · [Landings](Impacts-and-Forces.md#landings) · [Turbo & reactor boost](Impacts-and-Forces.md#turbo--reactor-boost).

## Effect support by game

**Full** means it plays with the shipped preset and the game supplies everything it needs. **Partial** means it plays, but some input is missing or it is limited by design. **None** means it does not play with the shipped preset, and the reason says why:

- *no data*: the game does not send what the effect needs;
- *silenced (level 0)*: the preset level is 0, and it cannot be brought back from the window;
- *off*: the effect is unticked; you can tick it to try it.

| Effect | Forza Motorsport | Forza Horizon 5/6 | Assetto Corsa EVO | BeamNG.drive | Trackmania |
|---|---|---|---|---|---|
| **Engine RPM** | **Full** | **Full** | **Full** | **Full**: needs OutGauge | **Partial**: generic 22-80 Hz map on a guessed 1,000-11,000 rpm range |
| **Gear shift** | **Full**: Car Dash format only | **Full** | **Full**: only when a gear engages, like HaptiConnect | **Full**: needs OutGauge | **Full**: simple 45 Hz thump |
| **Wheel lock (braking)** | **Full**: not in Sled format | **Full**: triggers earlier (1.0) | **Full** | **Partial**: one figure for the whole car; needs OutGauge *and* Motion Sim | **Full**: once the wheel size is learned |
| **Wheel slip / slide** | **Full**: rear-wheel spin; quiet again in very deep slides | **Full** | **Full**: plus the game's own slip signal | **None**: silenced (level 0); no slide-angle data | **Full** |
| **ABS pulse** | **None**: no data (OpenShaker reads no ABS from Forza) | **None**: no data | **None**: silenced (level 0), although the data exists | **None**: silenced (level 0), although the ABS light exists | **None**: no data; off |
| **Suspension bumps** | **Full**: road bed | **Full**: road bed in metres plus rumble noise | **Full**: road bed | **Partial**: no suspension data; vertical-g thumps only (needs Motion Sim) | **Full**: bumps plus texture |
| **Kerbs / rough road** | **Full**: rumble-strip flags | **None**: the game never sets the kerb flag (Demo only) | **None**: silenced (level 0); only car-wide kerb data exists | **None**: no data; level 0 | **None**: no data; off (Surface feel replaces it) |
| **Collisions** | **Full** | **Full** | **Full** | **Full**: needs Motion Sim; the strongest hits of any game | **Full** |
| **G-force rumble** | **Full** | **Full** | **Partial**: forward acceleration only, by design | **Full**: needs Motion Sim | **None**: off by choice (data exists; tick to try) |
| **Shift indicator** | **Full** | **Full** | **None**: silenced (level 0) | **None**: off and level 0 | **None**: off; the redline would be a guess |
| **Grip limit warning** | **None**: off (tick for the slip-based version) | **None**: off (tick for the slip-based version) | **None**: off (tick for the slip-based version) | **None**: off; if ticked, car-wide wheel-speed figure only | **Full**: loose surfaces only |
| **Surface feel** | **None**: no data | **None**: no data | **None**: no data | **None**: no data | **Full** |
| **Landings** | **None**: no data | **None**: no data | **None**: no data | **None**: no data | **Full** |
| **Turbo & reactor boost** | **None**: no data | **None**: no data | **None**: no data | **None**: no data | **Full** |

### Special cases

| Setup | What changes compared with the table above |
|---|---|
| **Forza Motorsport, Sled format** | No gear or pedal data. **Gear shift** and **Wheel lock** never play. Everything else behaves as in Car Dash, including Wheel slip and the Shift indicator, which do not need the throttle in this preset. |
| **Assetto Corsa / ACC** (older games, untested, use the Assetto Corsa EVO preset) | No slip data and no vibration signals. **Wheel lock**, **Wheel slip / slide** and the **Grip limit warning** have nothing to react to. The maximum rpm is learned from the highest rpm seen (at least 6,000). |
| **BeamNG with only OutGauge ticked** | Engine RPM and Gear shift play. **No** Collisions, G-force rumble, Suspension thumps or Wheel lock. |
| **BeamNG with only Motion Sim ticked** | Collisions, G-force rumble and Suspension thumps play. **No** Engine RPM, Gear shift or Wheel lock. |
| **Forza Horizon 4** (untested) | Its packets are read as Forza Horizon packets. OpenShaker does not look for the Horizon 4 program, so it plays through the current Horizon preset, or Forza Horizon 5. |
| **Forza Horizon on an Xbox or another PC** | Set *Advanced... → Forza listen address* to `0.0.0.0` to receive it. OpenShaker tells FH5 from FH6 by the program running on this PC. With the game elsewhere, it keeps the current Horizon preset, or uses Forza Horizon 5. Both share one calibration, so only your own strengths differ. |
| **Demo** | Plays through the active preset. Never plays Surface feel, Landings, Turbo & reactor boost or the Grip limit warning. ABS pulse is heard only with a Forza preset. The lock-up phase is silent with the Forza Motorsport, Assetto Corsa EVO and BeamNG presets, and the wheelspin phase is silent with Forza Motorsport. |

## Why some effects are silent

The Forza, ACE and BeamNG presets were calibrated to match HaptiConnect, so they leave out what HaptiConnect leaves out:
- **Assetto Corsa EVO:** HaptiConnect's ACE plugin plays no shift light and no kerb effect, so those two are silenced. ABS is silenced as a deliberate choice, not because it was measured to be absent.
- **BeamNG.drive:** HaptiConnect's BeamNG preset only plays engine, gear shift, acceleration, collisions, suspension and wheel lock. ABS, kerbs, slip and shift light are silenced.
- **Trackmania:** it has no ABS or kerb data, so those are off and Surface feel does the kerb job. The shift indicator is off too, because Trackmania doesn't report each car's rev limit. G-force rumble is off by choice.

Silenced effects keep their checkbox and slider, and their live bar can still move, but **0 × any strength is still 0**. The window can't bring them back. Only an edited copy of the game's profile file could.

## What each game sends

An effect can only react to what the game reports. This is the short version.

| Game | How OpenShaker gets the data | What it has | What it lacks |
|---|---|---|---|
| **Forza Motorsport** | Data Out (UDP), "Car Dash" format | rpm, g-forces, per-wheel suspension, slip and slide, rumble-strip flags, speed, pedals, gear | ABS (OpenShaker reads none from Forza). The "Sled" format also lacks gear and pedals. |
| **Forza Horizon 5 / 6** | Data Out (UDP) | Same as Motorsport | ABS. The rumble-strip flag is never set. |
| **Assetto Corsa EVO** | Shared memory, nothing to set up | rpm, g-forces, per-wheel suspension, slip and slide, pedals, gear, ABS and TC state, and the game's own kerb/slip/road/ABS vibration signals | Handbrake |
| **Assetto Corsa / ACC** (older, untested) | Same, older layout | rpm, g-forces, suspension, pedals, gear | Slip, slide, ABS, vibration signals |
| **BeamNG.drive** | OutGauge + Motion Sim (UDP) | OutGauge: rpm, gear, pedals, wheel speed, handbrake and ABS lights. Motion Sim: g-forces, ground speed. | Suspension travel, slide angle, kerbs, surfaces. Slip is one figure for the whole car. |
| **Trackmania** | Openplanet "Data Sender" plugin (TCP) | rpm, gear, pedals, speed, g-forces, damper travel, slide, spin, per-wheel surface, ground contact, water, roof contact, turbo, reactor | ABS, kerbs, handbrake, per-car rev range (the shipped preset has none, so 1,000-11,000 rpm is assumed) |

## What the strength slider does

- It changes **loudness only**. It never changes when an effect triggers, its pitch or its timing.
- Continuous effects follow the slider within about 10 ms. One-shot effects (kicks, hits, thumps) use the strength in force when they fire.
- The slider moves in whole percent. Clicking the track jumps straight to that point.
- Going above 100 % on a strong effect mostly makes the output limiter turn *everything else* down. It does not make peaks louder. See [How the effects are mixed](#how-the-effects-are-mixed-and-kept-safe).

The slider itself, the number box and the live bar are described on [The main window](The-Main-Window.md#effects); presets and saving on [Presets and strengths](Presets-and-Strengths.md).

## How the effects are mixed and kept safe

1. **Every effect is added into one signal.** OpenShaker plays the same signal on every output channel you choose; it never splits effects between channels. The default is the left channel only. You can change it under *Advanced... → Output channel*.
2. **Master scales the whole mix.** Master runs from 0 to 100 % and is shared by all presets. It cannot go above 100 %, so for more punch raise individual strengths or your amplifier.
3. **An output limiter catches the peaks.** It never clips the signal. Instead it looks 1.3 ms ahead and smoothly turns the *whole mix* down so peaks stay just under full scale (0.985, or -0.13 dBFS). It then comes back up steadily, at about 0.85 of full gain per second: about 0.6 s from a duck to half gain, 1.2 s from full silence.

**What this means for you:** one loud burst briefly ducks every other effect by the same amount. BeamNG's gear shift is tuned to do this, the way HaptiConnect's does. BeamNG collisions (preset level 1.668, not yet checked against HaptiConnect) and strengths above 100 % also duck the mix. If the **Level** meter keeps sitting near -0.1 dB, more strength will not feel stronger; the rest of the mix just ducks harder. Lower Master or the loudest effect instead.

**When effects go quiet:**

- While the game reports paused, in a menu, or respawning, effects stop or start their measurements over.
- If no telemetry newer than 1 second arrives, every effect fades out.

**Built-in protection:**

- A garbled value from the game is zeroed, so it never reaches the shaker as a full-scale pop.
- An effect that runs into an error mutes only itself.

**Test tone** is a 5-second sweep from 25 to 70 Hz at 0.8 of full scale (about -2 dBFS), a little below the hardest hits. It is added after Master (so Master does not change it), but it still passes the limiter.

## How to read the effect pages

Each section follows the same pattern:

- **What you feel**
- **How it works** in plain words, then **the details** for the curious
- **Game data** it uses
- **Default in each preset**
- **Strength slider**
- **Tips**

"Level" in the preset tables is the preset's calibrated gain, the number your strength multiplies. It is not always how loud the effect plays, because many effects also multiply it by their own table or curve. For example, Forza Motorsport's road bed is 1.6 × a table that tops out at 0.22, and its shift light is 1.0 × 0.4. At the output, 1.0 is full scale.

## Compared with HaptiConnect

- **All calibrated games:** levels come from one rig, a ButtKicker PRO with HaptiConnect 2.7.0 (its last version, June 2025) as the reference. End-to-end delay hasn't been measured.
- Each game's page lists what is still different, measured: [Forza Motorsport](Forza-Motorsport.md#known-limits), [Forza Horizon 5 and 6](Forza-Horizon-5-and-6.md#known-limits), [Assetto Corsa EVO](Assetto-Corsa-EVO.md#known-limits), [BeamNG.drive](BeamNG-Drive.md#known-limits) and [Trackmania](Trackmania.md#limits-honestly). The full story is in [How it was tuned](../HOW_IT_WAS_TUNED.md).

## Where these facts come from

Everything in this guide was checked against the code and shipped presets. For the technically curious:

- **Game data:** [Forza](../../openshaker/sources/forza.py#L18-L93), [Assetto Corsa EVO](../../openshaker/sources/ace.py#L40-L194), [BeamNG.drive](../../openshaker/sources/beamng.py#L118-L233), [Trackmania](../../openshaker/sources/trackmania.py#L416-L551)
- **Presets:** [Forza Motorsport](../../profiles/forza_motorsport/profile.json), [Forza Horizon](../../profiles/forza_horizon/profile.json), [Assetto Corsa EVO](../../profiles/ace/profile.json), [BeamNG.drive](../../profiles/beamng/profile.json), [Trackmania](../../profiles/trackmania/profile.json). Each preset's `meta` section explains its choices.
- **Effects:** [classic racing effects](../../openshaker/effects/racing.py), [Trackmania-only effects](../../openshaker/effects/trackmania.py)
- **Game detection and preset switching:** [runtime.py](../../openshaker/runtime.py#L404-L435), [config.py](../../openshaker/config.py#L16-L28)
- **Limiter and "no data" timeout:** [engine.py](../../openshaker/engine.py#L56-L146)
- **Measured differences from HaptiConnect:** [How it was tuned, chapter 5](../HOW_IT_WAS_TUNED.md#chapter-5-whats-still-different) and [Calibration, known gaps](../CALIBRATION.md#known-gaps)

---

**Next:** [Engine and gears](Engine-and-Gears.md)

**See also:** [Try the Demo](Is-It-Working.md#try-the-demo) · [Presets and strengths](Presets-and-Strengths.md)
