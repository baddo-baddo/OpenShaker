# Calibration and tuning

Everything here is optional. The app works out of the box with the profiles in `profiles/`; this
page is for people who want to know where those numbers came from, tune a game from their own
recordings, or repeat the HaptiConnect matching.

These tools run from a source checkout (see the README's "For developers") and need extra
packages on top of the app's. They write sessions to `sessions/` and learned profiles to
`profiles/` inside the checkout:

```bash
python -m pip install -r requirements-dev.txt
```

## How the shipped profiles were made

The profiles for Forza Motorsport (`profiles/forza_motorsport`), Assetto Corsa EVO (`profiles/ace`),
Forza Horizon 5/6 (`profiles/forza_horizon`) and BeamNG.drive (`profiles/beamng`) were fitted to
recordings of **HaptiConnect 2.7.0** driving a **ButtKicker PRO**, so that 100 % on a strength slider
is what HaptiConnect produced at the strengths the references were recorded at (its sliders at 0.5 for the
Forza games and ACE, with RPMs at 0.51 on Horizon, and at 1 for BeamNG). Each `profile.json` holds only numbers:

- the rpm-to-frequency/amplitude table of the engine tone, acceleration and shift-indicator curves,
  the road-bed level curves, thresholds and one gain per effect;
- for the one-shot effects (gear shift, collision, suspension bump) a **template generated in code**
  from a few parameters - waveform shape, base frequency, duration, fades, decay, extra harmonics -
  and for the kerb buzz five harmonic weights. Those parameters were measured on HaptiConnect's
  output; no recorded audio ships (see below);
- an `analysis` block with the measurements the first versions were built from. Several of those early
  readings were later corrected by direct measurement on real laps; the current findings are in `meta`
  and on this page.

The Trackmania profile has no HaptiConnect reference: its levels are first guesses on the same scale.

### From recordings to generated templates

Early development versions played short clips cut from HaptiConnect's recorded output. The shipped profiles
replace them with templates built by `effects/base.synth_template()` and `synth_cycle()`:

| Effect | Measured on HaptiConnect's output | Generated template |
|---|---|---|
| Gear shift (Forza Motorsport, Forza Horizon, ACE) | square burst at rpm / 120 Hz (half the engine pitch), 0.32, fixed 80 ms, ~87 ms after the gear changes | pitched mode: `pitch_hz_per_rpm` 1/120, 80 ms, square |
| Gear shift (BeamNG) | the same square at rpm / 120 Hz, ~0.5, 157-175 ms (the older "~33 Hz" came from calibration runs held at 4000 rpm) | pitched mode: 1/120, 165 ms |
| Collision (Forza Motorsport, Forza Horizon) | one full-scale square cycle, ~50 Hz, ~20 ms (HaptiConnect's own extracted hit) | `square`, 50 Hz, 20 ms |
| Collision (ACE) | not measured on the ACE plugin: the earlier Forza Motorsport (v6) hit carried over, a saw-like hit (all harmonics), ~48 Hz, ~22 ms | `saw`, 48 Hz, 24 ms |
| Collision (BeamNG) | unverified: the clip it replaced read a saw-like hit, ~60 Hz, ~16 ms, but the BeamNG probe read one fixed 28 ms hit at ~36 Hz (see the BeamNG plugin table below), and no real drive has a clean HaptiConnect crash yet | `saw`, 60 Hz, 17 ms |
| Suspension bump | ~45 Hz, ~14 ms decay, 2nd/3rd harmonics ~0.4/0.5 | `sine`, 45 Hz, 50 ms, decay 14 ms, harmonics [0.4, 0.45] |
| Kerb buzz (Forza Motorsport) | a plain sine at 1.25 Hz per m/s, the same level at any speed, while a wheel is on a kerb | `wavetable_harmonics` [1.0], flat `strip_amp_curve` |
| Kerb buzz (Forza Horizon) | rough cycle, harmonics 1-5 ~ 1 / 0.2 / 0.45 / 0.2 / 0.15 (never plays: Horizon sends no kerb flag) | `wavetable_harmonics` [1.0, 0.2, 0.45, 0.2, 0.15] |

Each template's gain was first matched to the energy of the clip it replaces, then re-fitted with
`openshaker.optimize` against the HaptiConnect lap recordings, with every other effect held fixed:

- **Forza Motorsport:** gear shift, collision and kerb gains fitted on laps 1, 3, 4 and 5, with lap 6
  held out. The current profile (v6) was then refitted per effect on replays that send HaptiConnect
  the original game packets, their values moved into the Horizon layout that HaptiConnect's Motorsport
  plugin reads (six laps, two more held out). The engine, gear shift, shift
  light, kerb, acceleration and road-bed laws in the table under "What HaptiConnect does" come from
  those replays.
- **Assetto Corsa EVO:** the Motorsport v6 numbers, changed only where HaptiConnect's own ACE plugin
  measurably differs: no shift light, no kerb cycle, and the gear shift fires only when a gear
  engages (ACE passes through neutral on every shift).
- **Forza Horizon 5:** the gear shift fitted on its lap. That lap has no collisions and few kerbs, so
  those two fits ran into the optimizer's +20 dB bound and were rejected; at that stage they kept
  their energy-matched gains.
- **BeamNG:** HaptiConnect's near-constant BeamNG rumble masked the shifts, and the fit ran into the
  -20 dB bound, so the gear shift kept its energy-matched gain (for 1.0.0 it was refitted through the
  output limiter; see "BeamNG level" below). At the time no BeamNG recording contained
  collisions or vertical bumps, so those kept energy- and peak-matched levels.

**Exact-parity refit (September 2026).** The goal changed from "about as strong as HaptiConnect" to
"the same as HaptiConnect, loudness included", with no deliberate differences. Every effect was then
measured at the moments it plays: HaptiConnect's recording against the app's whole mix, in the
effect's own band, fitted on some recordings and checked on others held out of that fit. Changes that needed
new code were not imitated with a gain.

- **Forza Motorsport:** the collision became HaptiConnect's own hit. It was 1.4-2.5 dB weak and is
  now 0.5-0.9 dB weak. For 1.0.0 the shift light also lost its throttle gate (HaptiConnect plays it at
  lift-off too) and went silent in reverse (`min_gear` 0, `below_min_gear_scale` 0.001), where
  HaptiConnect is near silent and we were ~20 dB too loud.
- **Forza Horizon:** the engine is now rpm / 60 all the way to the redline, at HaptiConnect's level.
  The gear shift is the Motorsport plugin's rpm / 120 square; it was 7 dB too strong. The shift light
  is a 70 Hz step at ~84 % of max rpm with no throttle gate, silent in reverse. Acceleration moved to
  59 Hz; longitudinal and lateral g now add while accelerating (`combine` "sum"; braking still takes the
  larger) instead of taking the larger. Wheel slip
  keeps playing through large slides. For 1.0.0 the road bed follows the suspension travel in metres
  (`vel_curve_m` on the game's packet clock), carries a broadband 37-45 Hz noise voice (`bed_noise`)
  like HaptiConnect's, and has no low-speed floor. The collision is HaptiConnect's 50 Hz square hit.
- **Assetto Corsa EVO:** matched to one rendering of HaptiConnect's Evo plugin. The road bed,
  acceleration (forward g only), wheel slip (later onset, no upper cut-off), wheel lock and ABS were
  4-15 dB too strong. ABS is silenced by choice: the measured residual was too small to fit.
- **BeamNG:** the old same-loudness scaling is gone, so BeamNG plays at HaptiConnect's own level:
  about 12 dB (4x) stronger than before. HaptiConnect's BeamNG preset has no wheel slip, shift light,
  ABS or kerb effect, so those are at gain 0. Wheel lock, collision and bump levels had no usable
  HaptiConnect evidence; they are carried at their earlier fitted ratios until a clean recording exists.

### The calibration pipeline (needs HaptiConnect)

`openshaker.calibrate` drives HaptiConnect with synthetic telemetry, records what HaptiConnect plays
to the shaker through WASAPI loopback, and learns a profile from it. HaptiConnect must be installed
at `C:\Program Files\ButtKicker\connect\bk-connect.exe`, or point `OPENSHAKER_HC_EXE` at it.

HaptiConnect's BeamNG plugin only ever sees packets, so the app can play clean calibration sequences
into it (slow rpm sweeps, isolated shifts, impacts of growing size, ...) and record each effect on its
own. One-time setup: in HaptiConnect, BeamNG.drive page > Telemetry forwarding > add `localhost`
port `4446`. Then:

```bash
python -m openshaker.calibrate all
```

For each of the six BeamNG effects it sets HaptiConnect's profile to that effect alone, restarts
HaptiConnect, runs the sequence (you will feel it), records, learns, and finally restores your
original profile. Result: `profiles/beamng/profile.json`. Individual effects:
`python -m openshaker.calibrate rpm shift`. Profiles learned this way reference the recorded clips
(`sample`, `wavetable`); keep them local.

HaptiConnect's Forza Motorsport plugin has nine effects (it adds wheel slip, rumble strips and a
shift indicator) and accepts the rich Forza packet:

```bash
python -m openshaker.calibrate --plugin fm all
```

Forza Motorsport must be running at its main menu (HaptiConnect only listens while the process
exists), and the game's own Data Out must not point at HaptiConnect's port 5305 during this, because
Forza streams packets even from the menu. Set it to `127.0.0.1` port `5555`, which is where this app
listens anyway.

Measured quirk: that plugin decodes the packet tail (gear, pedals) at the Forza *Horizon* offsets, so
the calibrator sends it the 324-byte Horizon layout. Fed the 331-byte Motorsport layout, its gear
shift, wheel lock and shift indicator never fire.

### What HaptiConnect does (measured)

Forza Motorsport plugin:

| Effect | Behaviour |
|--------|-----------|
| RPM (probe, strength 1) | tone at rpm / 60 Hz, ~0.9 amplitude, no harmonics |
| Gear shift (probe, strength 1) | 94 ms full-scale burst per gear change; rpm drops alone do nothing |
| Acceleration (probe, strength 1) | ~60 Hz tone, on at ~3 m/s² accelerating, ~7 braking, ~7 lateral |
| Collision (probe, strength 1) | ~45 ms hit on g jumps of ~15 m/s² held 3+ frames (on laps: one ~20 ms square cycle) |
| Wheel lock (probe, strength 1) | 56 Hz full-scale tone only when the front wheels lock while the rears keep turning |
| Wheel slip (probe, strength 1) | 54.5 Hz tone for rear slip ratio ~0.5-1.3 or slip angle ~0.5-0.8; larger slip is ignored |
| Suspension | on real laps: a continuous 41 Hz square wave whose level follows the suspension velocity of the last ~50 ms, near silent on smooth road |
| Rumble strips | on real laps: one sine at 1.25 Hz per m/s (no frequency cap; 76 Hz at 61 m/s), 0.245 per wheel on a kerb and flat with speed, only while that wheel's kerb flag is set |
| Shift indicator | on real laps: a 70 Hz tone that steps straight to 0.40 at ~84 % of max rpm (no ramp, no throttle gate) |
| Gear shift (on laps) | a square burst at rpm / 120 Hz, 0.32, fixed 80 ms, ~87 ms after the gear byte changes; fires on nearly every gear-byte change (no burst on 20 of 210 in our laps), so a Forza shift through neutral gives two bursts. What looked like random pitch was the rpm spread |
| Engine, acceleration (on laps) | engine at rpm / 60 Hz, flat at 0.159 regardless of rpm or throttle, with no drop at high rpm; the acceleration tone sits near 58 Hz at around 0.06 of full scale, far below the probe's full scale, so lap recordings, not probes, set the levels |

The lap rows were measured on replays that send HaptiConnect the original game packets, at strength
0.5. Replaying rebuilt packets instead changes what HaptiConnect plays on kerbs and bumps.

Assetto Corsa EVO plugin (fed the recorded ACE physics through `Local\acpmf_*` shared memory, with
the game at its menu). HaptiConnect 2.7.0 only knows the older `Local\acpmf_*` names, while current
ACE builds publish `Local\acevo_pmf_*`, so in live play its ACE plugin receives nothing; it can only
be heard through a replay. It has the same engine and gear-shift voices as the Forza plugin, but no
shift light and no kerb cycle. The gear shift fires only when a gear engages, never into neutral.
Its acceleration tone clearly follows forward g; its response to cornering was too weak and inconsistent
between our two recordings to fit, so the 1.0.0 profile plays forward g only. Its acceleration, wheel-slip,
wheel-lock and road-bed
voices are 4-15 dB weaker than the Forza plugin's.

Replays have so far written ACC's version string ("1.9") into the static page. That most likely
wakes HaptiConnect's Competizione plugin as well, so every effect plays twice: the gear-shift squares
add in phase (+6 dB) and the engine line beats. `replay.py --ace-sm-version` writes a different string
so that only one rendering is recorded. Until such a recording exists, the doubled ones are scored
3 dB down.

Forza Horizon 5 plugin: the same engine (rpm / 60, flat at 0.176 with RPMs at 0.51), gear-shift
(rpm / 120, 80 ms, 0.32) and shift-light (70 Hz step at ~84 % of max rpm, no throttle gate) laws as
the Motorsport plugin. The acceleration tone sits at ~59 Hz and combines longitudinal and lateral g
more strongly than taking the larger of the two. Forza Horizon 5 and 6 never set the per-wheel kerb
flag (`WheelOnRumbleStrip` is 0 on every packet), so HaptiConnect plays no kerb cycle on Horizon. On
kerbs and rough ground it plays only its road bed. That bed is broadband around 41 Hz rather than a
single tone, follows the suspension travel in metres (`SuspensionTravelMeters`) rather than the
normalized travel, and rises with `SurfaceRumble`, which is a surface-material code, not a kerb flag.

BeamNG plugin:

| Effect | Behaviour |
|--------|-----------|
| RPM | tone at exactly rpm / 60 Hz, 0.91 at strength 1, faint 2nd harmonic, throttle ignored. Above ~0.975 x max rpm the engine line drops to ~0.6 under a ~60 Hz rev-limiter voice amplitude-modulated at ~10 Hz |
| Gear shift | a square at rpm / 120 Hz, ~0.5, 157-175 ms, on every gear change (the older calibration runs held 4000 rpm, hence "~33 Hz") |
| Wheel lock | on/off: a full-scale 56 Hz tone while wheel speed is below ~45 % of car speed under braking (probe only; no clean lock-up on a real drive yet) |
| Acceleration | ~60 Hz tone; on real drives it sits far lower relative to the engine than the probes suggested, and it matches at the old gain once everything else is un-scaled |
| Collision | one fixed 28 ms hit (~36 Hz) when longitudinal g jumps by 15 m/s² or more for at least 4 frames; vertical g ignored (probe only) |
| Suspension | on real drives no 41 Hz rumble while the engine plays (0.007-0.01); a 41 Hz tone at ~0.3 appeared once with the engine off, standing still. A fixed pulse per bump on the vertical g channel |

The BeamNG preset has only these six effects: no wheel slip, shift light, ABS or kerb effect.

HaptiConnect only evaluates telemetry about 12 times per second (once per audio buffer), so pulses
shorter than ~170 ms are hit or miss. Its delay is not constant either: measured gear change by gear change on the
Forza references, the median per recording is 75-92 ms, but within one Forza Horizon 5 replay it jumped between
73 and 249 ms, and on two Forza Motorsport laps single gear changes arrived 200-340 ms late. Its strength slider is not linear: 0.5 is at least 15.8 dB
below 1 (the strength-1 point sits on the output limiter's ceiling, so only a bound is known).
HaptiConnect drives the ButtKicker on the left channel only.

Every plugin's output ends in a gain-reducing peak limiter, not a clipper. In the clean recordings its ceiling is 0.985
(-0.13 dBFS; the one brief overshoot, to 0.991, is in a replay that held two copies of the plugin's output), it looks ahead ~1.3 ms, reacts within ~2.7 ms and recovers along a straight gain ramp
of ~0.85 per second. At Forza strengths it rarely engages. In BeamNG at strength 1 it ducks the
engine to about half under every gear shift, which a sum of effects cannot reproduce.

`python -m openshaker.calibrate collision_probe` (also `suspension_probe`, `lock_probe`, `accel_probe`)
records such experiments; `python -m openshaker.probe <session>` reads them out;
`python -m openshaker.viz <session>` draws input against output.

### Matching HaptiConnect on a real drive

1. Drive with the app and log it:
   `python -m openshaker --source forza --log sessions/my_drive`
2. Replay that exact telemetry into HaptiConnect and record its output (game at its menu,
   HaptiConnect on the profile you want to match):
   `python -m openshaker.replay sessions/my_drive --plugin fm --out sessions/my_drive_hc`
   Forza drives are sent as the original packets whenever the log holds them (`--packets auto`, the
   default; `--packets columns` rebuilds them from the CSV) at 60 packets/s (`--rate 0` keeps the
   original timing). `--plugin ace` writes the recorded Assetto Corsa physics to shared memory
   instead (Assetto Corsa EVO at its menu). The replay refuses an `--out` folder that already exists (default `<drive>_hc`).
3. Score and fit:
   `python -m openshaker.compare sessions/my_drive_hc --profile profiles/forza_motorsport/profile.json`
   and `python -m openshaker.fit sessions/my_drive_hc --profile ... --apply` (renders every effect
   alone and solves for the gains that reproduce HaptiConnect's spectrogram).
4. Fit across several laps with one held out:
   `python -m openshaker.optimize --profile <profile> <HaptiConnect sessions...> --holdout <session> --apply`
   minimizes the banded spectrogram distance (10 Hz bands, 50 ms frames) plus the level mismatch;
   `--fix` keeps chosen effects at their current gain. The fit sums effects rendered one at a time,
   which is exact only while the output limiter is idle; a profile that reaches the limiter (BeamNG at
   HaptiConnect's level does) has to be judged on the whole mix (`Session.report_full`). HaptiConnect's
   delay is searched in 5 ms steps and applied sample by sample. A fitted gain that lands on the ±20 dB bound
   means the recordings hardly contain that effect: do not trust it. `--apply` refuses such gains
   unless you pass `--allow-bound`, and backs up the old profile first.
   `--seed N` makes the random parts of the render (e.g. gear-shift pitch jitter) repeatable, so two
   profiles are compared on identical draws. Renders are cached in `~/.cache/openshaker/renders`
   (or `$OPENSHAKER_RENDER_CACHE`); the cache key includes the rendering code, so a code change re-renders.

`openshaker.compare`'s envelope correlation uses a 20 ms window, which reads near zero on a
near-constant rumble such as BeamNG's; measure flat material directly.

### Validation of the shipped profiles

Measured with `openshaker.optimize`'s scorer (`Session.report_full`) on each HaptiConnect recording: the app's
whole output as it plays (every effect through one engine, output limiter included), with HaptiConnect's delay
found in 5 ms steps (65-90 ms on most recordings) and the frames where HaptiConnect's own recording dropped out
(runs of exact zeros) left out. The 1.0.0 numbers are identical on `--seed 1` and `--seed 2`. The oldest Forza profiles still gave the gear change a random pitch, so their numbers move by up to 0.15 on a single lap (0.07 on the held-out averages) between seeds; seed 1 is shown.

- **Level:** the app's output relative to HaptiConnect's on the same drive, in dB.
- **Distance:** mean dB error over 10 Hz bands plus the level error; lower is closer.
- **Corr:** envelope correlation.
- **Bands:** share of energy per band, 15-35 / 35-50 / 50-70 / 70-100 / 100-150 Hz.

"Before" is each game's profile at the start of the HaptiConnect matching work and "after" is 1.0.0,
both rendered with the 1.0.0 engine. Recordings marked *held out* were left out of the final fits (for Forza Motorsport, out of every optimizer fit; lap 6 was also used to read HaptiConnect's engine level and shift-light pitch, and only lap 2 was never used). How each
generation in between scored is in [HOW_IT_WAS_TUNED.md](HOW_IT_WAS_TUNED.md).

| Recording | Profile | Level before -> after | Distance before -> after | Corr (after) | HaptiConnect bands | Our bands (after) |
|---|---|---|---|---|---|---|
| Forza Motorsport lap 1 | forza_motorsport | +0.2 -> -0.2 dB | 3.02 -> 1.77 | 0.77 | 7 / 26 / 26 / 31 / 11 | 4 / 31 / 22 / 31 / 11 |
| Forza Motorsport lap 3 | forza_motorsport | -0.8 -> -0.4 dB | 4.12 -> 2.46 | 0.73 | 5 / 19 / 46 / 23 / 7 | 4 / 36 / 29 / 21 / 10 |
| Forza Motorsport lap 4 | forza_motorsport | +0.2 -> +0.0 dB | 3.00 -> 1.77 | 0.82 | 5 / 24 / 28 / 35 / 8 | 3 / 31 / 23 / 32 / 10 |
| Forza Motorsport lap 5 | forza_motorsport | +0.7 -> -0.2 dB | 3.75 -> 2.01 | 0.79 | 12 / 13 / 27 / 39 / 10 | 10 / 19 / 24 / 37 / 10 |
| Forza Motorsport lap 7 (9000-rpm car) | forza_motorsport | -0.2 -> +0.3 dB | 3.72 -> 2.51 | 0.72 | 5 / 17 / 35 / 27 / 15 | 3 / 37 / 22 / 22 / 16 |
| Forza Motorsport lap 8 (9000-rpm car) | forza_motorsport | -0.3 -> +0.4 dB | 4.63 -> 2.49 | 0.82 | 4 / 8 / 28 / 38 / 21 | 3 / 28 / 18 / 30 / 21 |
| Forza Motorsport lap 6, *held out* | forza_motorsport | +0.4 -> -0.4 dB | 3.48 -> 2.23 | 0.76 | 19 / 15 / 34 / 25 / 6 | 19 / 21 / 29 / 25 / 7 |
| Forza Motorsport lap 2, *held out* | forza_motorsport | +0.8 -> -0.2 dB | 3.77 -> 2.13 | 0.64 | 15 / 26 / 36 / 21 / 3 | 20 / 40 / 16 / 20 / 4 |
| Forza Horizon 5 lap 4 | forza_horizon | -1.2 -> -1.3 dB | 5.00 -> 3.91 | 0.78 | 5 / 7 / 45 / 36 / 7 | 4 / 7 / 41 / 40 / 9 |
| Forza Horizon 5 lap 5 | forza_horizon | +0.1 -> +0.0 dB | 2.53 -> 1.71 | 0.69 | 6 / 9 / 39 / 37 / 9 | 3 / 8 / 48 / 32 / 9 |
| Forza Horizon 5 lap 1, *held out* | forza_horizon | -0.1 -> -0.6 dB | 3.43 -> 3.21 | 0.76 | 3 / 17 / 34 / 35 / 10 | 3 / 18 / 34 / 34 / 11 |
| Forza Horizon 6 lap (FH5 plugin), *held out* | forza_horizon | -1.6 -> -1.3 dB | 4.34 -> 3.11 | 0.73 | 3 / 12 / 53 / 27 / 6 | 3 / 8 / 48 / 34 / 8 |
| Assetto Corsa EVO drive 3 (Evo plugin, one copy) | ace | +4.7 -> +0.4 dB | 8.32 -> 2.31 | 0.62 | 15 / 22 / 21 / 31 / 11 | 14 / 20 / 15 / 34 / 17 |
| Assetto Corsa EVO drive 2 (Evo plugin, one copy), *held out* | ace | +3.2 -> -0.5 dB | 6.57 -> 2.27 | 0.69 | 15 / 19 / 21 / 35 / 11 | 15 / 19 / 19 / 35 / 13 |
| BeamNG.drive drive 1 | beamng | -10.9 -> +0.1 dB | 14.37 -> 1.52 | 0.80 | 20 / 16 / 23 / 30 / 11 | 20 / 16 / 23 / 30 / 12 |
| BeamNG.drive drive 3 (where HaptiConnect played), *held out* | beamng | -8.6 -> +0.6 dB | 12.26 -> 1.87 | 0.62 | 2 / 0 / 4 / 27 / 68 | 2 / 0 / 4 / 24 / 71 |

**Forza Horizon level.** Most Horizon effects now land closer to HaptiConnect at the moments they
play, yet three of the four laps still end 0.6-1.3 dB quieter overall. Before, the profile's
errors cancelled: a 7 dB-too-strong gear shift and a too-strong engine filled the bands where
HaptiConnect plays its broadband road bed, combined cornering-and-acceleration tone and surface
rumble, which the app cannot yet produce (see "Known gaps"). The same effect makes the old
band-share acceptance checks fail for this profile. No gain was raised to hide it.

**BeamNG level.** HaptiConnect's own BeamNG preset runs at strength 1. It is about 12 dB (4x)
hotter than its Forza one, and the engine tone carries about 95 % of it. The profile now plays at
that level: its engine matches HaptiConnect's to 0.1 dB. The earlier development profiles scaled every gain by
0.2488 so that BeamNG sat at the Forza level, which is why its row read -10.9 dB. Since the app's output
stage became the same kind of limiter as HaptiConnect's (ceiling 0.985), a gear shift ducks the
engine as HaptiConnect's does, and nothing is flat-topped any more; the gear-shift level was refitted
through it. Wheel lock, collision and bump levels have no clean HaptiConnect reference:
HaptiConnect's output faulted at every such moment in the one drive that contains them (drive 3; drive 1
has no Motion Sim data). They stand at their earlier
fitted ratios until a clean recording exists. On drive 3, HaptiConnect's own output dropped out for
71 % of the driving time, so only the stretches where it played are scored.

**Assetto Corsa EVO.** The rows are scored against one rendering of HaptiConnect's own Evo plugin
(the doubled recordings scored 3 dB down, see above). The same drives replayed through the Forza
Motorsport plugin read -4.9 and -4.4 dB with this profile (distance 8.45 and 7.79). That is a different plugin, and it is not
the target.

### Known gaps

These differences are measured and were not imitated with gains. The app has opt-in code for several
of them (see DEVELOPMENT.md, Parity keys). In 1.0.0 the Forza Horizon profile uses the metre-based,
broadband road bed and the summed g-forces, and both Forza profiles use the reverse gate for the shift
light. The rows below are how 1.0.0 plays; sizes are measured at the moments each one matters.

| Gap | Games | Size |
|---|---|---|
| The acceleration voice is one tone (~58-59 Hz); HaptiConnect's is a rumble spread over ~52-72 Hz | Forza Motorsport, Forza Horizon | on Forza Motorsport only 25 % of HaptiConnect's 44-76 Hz energy lies within 2 Hz of our tone (ours 94 %); pure cornering about +6 dB on the tuning laps, +2.8 dB on Horizon's held-out laps |
| The road bed still follows the normalized suspension travel (a metre-based bed is fitted but waits for the acceleration voice, whose gap the old bed currently fills) | Forza Motorsport | the 9000-rpm car's bed about +9 dB |
| Longitudinal and lateral g still take the larger of the two (the summed law is fitted but pushes hard slides 1.3 dB away) | Forza Motorsport | combined g about -4 dB on held-out laps |
| The road bed does not rise on the roughest surfaces (`SurfaceRumble` 0.6; only one recorded lap has them) | Forza Horizon | about -7 dB (band) to -10 dB (41 Hz line) there |
| HaptiConnect plays Forza Horizon 5 and 6 differently at the same inputs; one profile plays both | Forza Horizon | bed -5.9 to +6.9 dB by suspension speed on FH6; slip +3.0 (FH5) vs -0.1 dB (FH6) |
| The collision detector fires where HaptiConnect plays no hit, and misses some of its hits | Forza Horizon (Forza Motorsport rarely) | 11-21 of 40 Horizon fires without a HaptiConnect hit, depending on the criterion; 23 Horizon and 6 Motorsport HaptiConnect hits without a fire of ours |
| Wheel slip and wheel lock are weaker than HaptiConnect's; the road bed is far too strong at walking pace | Forza Horizon | slip about -3.9 dB (n 57); lock about -6.9 dB on held-out laps (n 9); bed at crawl speed +22 dB (n 7) |
| HaptiConnect still plays a faint broadband buzz (~66-74 Hz) in reverse; the 1.0.0 shift light is silent there | Forza Motorsport | about -10.5 dB (tuning laps, n 11) and -11.7 dB (cross-check, n 15); little data |
| HaptiConnect's ACE plugin responds to cornering (not fitted), deep slides disagree between the two recordings, and the absolute level rests on scoring doubled recordings at one copy's level | Assetto Corsa EVO | lateral about -8 dB; deep slides +14.1 dB on one recording and -1.4 dB on the other; level uncertain by up to 6-12 dB at the road bed until a single-copy recording exists |
| BeamNG's rev-limiter voice (~60 Hz, amplitude-modulated) is not played: the engine effect has opt-in code for it (`rev_voice_amp`), not fitted or switched on in 1.0.0 | BeamNG | the whole voice is missing |
| Wheel lock, collision and bump levels have no clean HaptiConnect reference | BeamNG | not measured |

### Recording a drive by hand

1. In HaptiConnect open the BeamNG.drive page, **Telemetry forwarding**, add `localhost` port `4446`.
2. On the HaptiConnect profile set every effect strength to 0 except the one to capture.
3. `python -m openshaker.record --note "rpm only"`, drive, press Enter. The session lands in `sessions/<timestamp>`.
4. `python -m openshaker.analyze sessions/<timestamp>` writes `profiles/<timestamp>/profile.json`,
   WAV templates, `report.txt` and plots. Those WAVs are recordings of HaptiConnect: keep them local.

## Tuning a game from your own drive (no HaptiConnect)

### BeamNG.drive

```bash
python -m openshaker --source beamng --log sessions/beamng_drive --duration 300
python -m openshaker.beamng_check sessions/beamng_drive
```

The checker replays the drive through the real source and reports which protocols arrived (OutGauge,
Motion Sim), which Motion Sim axis follows the car's speed changes, acceleration and jump percentiles
(what the impact and bump thresholds compare against), the biggest hits and bumps, and how long the
wheels were locked under braking.

### Trackmania

```bash
python -m openshaker --source trackmania --log sessions/tm_drive --duration 300
python -m openshaker.tm_grip sessions/tm_drive
python -m openshaker.tm_tune sessions/tm_drive
```

`tm_grip` finds every moment the car let go, reports the sideways load and body slip just before each
one per surface, and proposes the grip warning's limits. `tm_tune` reports engine range, bump
strength, crash threshold, landings and grip limits in one go and ranks the surfaces you drove on by
roughness. Both write their results with `--apply`.

## Effect parameters

`config.json` lives in the settings folder, `%APPDATA%\OpenShaker`, and is created on first start.
Every effect has `enabled` and `trim` (1.0 = the calibrated level; the window shows it as a
percentage), stored per game under `presets`. The absolute level of an effect comes from the active
profile and is deliberately not stored in `config.json`, so saving settings can never overwrite a
calibration.

The parameters below are the synthetic defaults used when no profile is loaded; a profile replaces
most of them.

- `engine`: tone from `freq_min` (idle) to `freq_max` (redline). `amp_throttle` adds level under power.
- `gear_shift`: thump on every gear change. `pitch_hz_per_rpm` (e.g. 1/120) plays it at a pitch that
  follows rpm instead of the template's fixed frequency, for `pitched_duration_s`, clamped to
  `pitch_hz_range`; `fire_into_neutral: false` stays silent when the gear goes to neutral.
- `shift_indicator`: tone at `freq` from `rpm_curve` [[fraction of max rpm, level], ...] while the
  throttle is above `min_throttle`.
- `wheel_lock` / `wheel_slip`: thresholds are in normalized slip where 1.0 is about the grip limit.
- `suspension`: `threshold` and `full` are suspension velocities (fraction of travel per second).
  `vel_curve` [[velocity, level], ...] turns on the continuous road bed at `idle_tone_freq`, following the
  fastest wheel's velocity with an exponential release of `vel_hold_s` seconds; `harmonics` shapes it (odd harmonics 1/3, 1/5, 1/7 = square).
- `road`: with a kerb cycle (`wavetable_harmonics` or `wavetable`, as in the shipped Forza and ACE profiles)
  the kerb buzz frequency = speed x `strip_hz_per_ms`, clamped to `strip_hz_min`..`strip_hz_max`, level
  from `strip_amp_curve` [[m/s, RMS], ...]; without one it is speed / `strip_spacing` (metres), clamped to
  20-90 Hz. `surface_gain` is rough-surface rumble.
- `impact`: `threshold` and `full` are jumps in body acceleration (m/s²) between two frames.
- `template` (gear_shift, impact, suspension): `{"shape": "sine"|"square"|"saw", "freq": Hz,
  "duration": s, "attack": s, "release": s, "decay": s, "harmonics": [2nd, 3rd, ...], "level": peak}`.
- `wavetable_harmonics` (road): relative amplitudes of harmonics 1, 2, 3, ... of the kerb cycle.
- `sources.ace.susp_scale_m`: metres of suspension travel that count as "full" in Assetto Corsa.
- `sources.beamng.accel_scale`: multiplies BeamNG's acceleration if impacts never or always trigger.

Shakers respond best between roughly 20 and 90 Hz, which is where the defaults sit.
