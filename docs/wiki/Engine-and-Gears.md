# Engine and gears

[OpenShaker guide](README.md) › Effects

The effects that follow the engine: Engine RPM, Gear shift and the Shift indicator.

## Engine RPM

**What you feel:** a steady hum whose pitch rises and falls with the revs.

**How it works.** While the engine runs, OpenShaker plays one continuous tone whose pitch follows the rpm. You feel the engine climb through each gear and drop on every shift.

In the calibrated presets, the pitch follows the engine's own rotation rate, rpm ÷ 60, exactly or within a few percent. For example, about 3,000 rpm plays about 50 Hz and 6,000 rpm plays about 100 Hz. The loudness stays flat at every rpm, as HaptiConnect's does, and throttle adds only a hair.

**The details:**

- Calibrated presets use a table of rpm → pitch and level. Below or above the table, the nearest row is used.
- Trackmania uses the built-in formula instead:
  - the pitch runs in a straight line from 22 Hz at idle to 80 Hz at maximum rpm;
  - the level is 0.30 + 0.35 × throttle, so it gets stronger on throttle;
  - a quieter second tone at double the pitch (15 %) is added.
- The effect is silent when the engine is off, below 50 rpm, or when the game is paused.
- The code includes an optional rev-limiter buzz, but no shipped preset turns it on.

**Game data:** rpm, engine running and throttle. Trackmania also uses the idle and maximum rpm.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport | On | 0.1646 | Table from 560 to 10,000 rpm: exactly rpm ÷ 60 from 6,800 rpm up, within about 3 % of it below. About 0.158 at the output, matching HaptiConnect's flat 0.158. |
| Forza Horizon 5/6 | On | 0.1827 | Exactly rpm ÷ 60 from 560 to 12,080 rpm |
| Assetto Corsa EVO | On | 0.1646 | Same table as Forza Motorsport |
| BeamNG.drive | On | 0.908 | About rpm ÷ 60 from 880 to 8,080 rpm, with a raised bottom end (17.6 Hz up to 1,040 rpm) and a faint second harmonic. Plays at HaptiConnect's BeamNG level (0.91), roughly 15 dB stronger than Forza. |
| Trackmania | On | 0.175 | Built-in 22-80 Hz formula over 1,000-11,000 rpm. That range is a fixed guess, because the shipped preset has no per-car rev ranges. |

**Strength slider:** changes loudness only. The pitch always follows the rpm.

**Tips:**

- This is the effect you feel almost all the time. If the hum hides everything else, lower it first.
- If you play BeamNG, set your amplifier with BeamNG, because its engine is much stronger than Forza's.

_Code: `EngineEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

## Gear shift

**What you feel:** a short kick on every gear change.

**How it works.** When the gear number changes, a short burst plays.

- **Calibrated presets:** the burst is a buzzy square wave whose pitch follows the revs at that moment (rpm ÷ 120, so 6,000 rpm gives a 50 Hz kick). It lasts 80 ms, or 165 ms in BeamNG.
- **Trackmania:** a simple 45 Hz thump that dies away quickly.

**Rules that prevent false kicks:**

- Nothing plays across a pause, rewind, menu, respawn or a gap in the data longer than 0.5 s. Nothing plays for changes made while the effect was switched off either. The first frame back only notes the current gear.
- There is a minimum gap between kicks: 0.05 s in Forza and Assetto Corsa EVO, 0.12 s in BeamNG and Trackmania.
- Reverse counts as a gear.

**Neutral:**

| Preset | Behaviour |
|---|---|
| Forza Motorsport and Horizon | Kicks both going into neutral and leaving it, as HaptiConnect does |
| Assetto Corsa EVO | Kicks only when a gear engages, never into neutral. HaptiConnect's ACE plugin fired on 45 of 47 changes into a gear and on 0 of 35 into neutral. |
| BeamNG and Trackmania | A quick pass through neutral (under 0.6 s) counts once, when you leave the old gear |

**The details:** the pitch range is 7-120 Hz in Forza and Assetto Corsa EVO, and 10-120 Hz in BeamNG. The 7 Hz floor comes from HaptiConnect's lowest measured shift, 7.7 Hz at 930 rpm.

**Game data:** gear, plus rpm for the pitch. In Forza Motorsport's **Sled** format the gear is always 0, so this effect **never plays**; use **Car Dash**. BeamNG needs **OutGauge**.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport | On | 0.415 | 80 ms square at rpm ÷ 120. Kicks into and out of neutral. |
| Forza Horizon 5/6 | On | 0.417 | Same |
| Assetto Corsa EVO | On | 0.415 | Same sound, but only when a gear engages |
| BeamNG.drive | On | 0.9 | 165 ms at rpm ÷ 120. Tuned so the kick briefly ducks the rest of the mix, as HaptiConnect's does. |
| Trackmania | On | 0.5 | 45 Hz thump |

**Strength slider:** sets the loudness of the next kick. Timing and pitch do not change.

_Code: `GearShiftEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

## Shift indicator

**What you feel:** a shift light you can feel as the revs near the limit.

**How it works.** When the revs get close to the car's maximum, a tone plays. There are two styles:

- **Forza presets:**
  - A continuous 70 Hz tone that fades in over a narrow band just below the redline and then stays on.
  - It ignores the throttle, because HaptiConnect keeps its light on when you lift off.
  - It is practically silent in reverse (about -60 dB); neutral still plays.
- **Built-in style** (what Trackmania would use if you tick it): a 65 Hz tone that pulses 9 times a second above 95 % of maximum rpm, only with more than 20 % throttle.

The effect is off unless a preset switches it on. Both Forza presets switch it on. The Assetto Corsa EVO preset also switches it on, but at level 0, so it never plays.

**Default in each preset:**

| Preset | Default | Level | Notes |
|---|---|---|---|
| Forza Motorsport | On | 1.0 | Fades in from 83.5 % to 85.5 % of maximum rpm, then holds at 0.4 |
| Forza Horizon 5/6 | On | 1.0 | Fades in from 83.75 % to 84.75 % |
| Assetto Corsa EVO | **Silent (level 0)** | 0 | HaptiConnect's ACE plugin has no shift light |
| BeamNG.drive | Off | 0 | Off and level 0 |
| Trackmania | Off | 1.0 | The preset notes say "no Trackmania data". Trackmania does send rpm and throttle, but the maximum rpm is a fixed 11,000 guess, so the light would follow a guessed redline. |

**Game data:** rpm, maximum rpm, throttle, gear, and whether the engine is running.

**Strength slider:** loudness only.

_Code: `ShiftIndicatorEffect` in [`openshaker/effects/racing.py`](../../openshaker/effects/racing.py)._

---

**Next:** [Road and suspension](Road-and-Suspension.md)

**See also:** [Effects overview](Effects-Overview.md) · [Presets and strengths](Presets-and-Strengths.md)
