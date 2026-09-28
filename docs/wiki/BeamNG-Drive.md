# BeamNG.drive

[OpenShaker guide](README.md) › Games

Setting up BeamNG.drive's two built-in data protocols, what each effect does in it, and what is still different from HaptiConnect.

## Setup

1. In BeamNG.drive, open **Options > Other**.
2. Tick **OutGauge** *and* **Motion Sim**. Leave both on `127.0.0.1` port `4444`.
3. Drive. No mod is needed.

## How OpenShaker connects

- By default, both of BeamNG's built-in protocols arrive on UDP port **4444**, and OpenShaker takes both there.
- If you send Motion Sim to a different port, enter it under **Advanced... > BeamNG Motion Sim port** (0 means "same as OutGauge"). The OutGauge port is also under Advanced.
- OpenShaker also accepts the extended data that HaptiConnect's BeamNG mod sends.
- The sources line tells you which box is missing:

| Status | Meaning |
|---|---|
| `listening on UDP 4444` | Nothing has arrived yet: check the boxes and port in BeamNG |
| `OutGauge + Motion Sim` | All good |
| `OutGauge only: tick Motion Sim in BeamNG (Options > Other) for crashes, bumps and wheel lock` | Motion Sim is off, or on another port |
| `Motion Sim only: tick OutGauge in BeamNG (Options > Other) for engine, gears and pedals` | OutGauge is off, or on another port |

**What each protocol gives:**

| | OutGauge | Motion Sim |
|---|---|---|
| Data | Revs, gear, throttle, brake, wheel speed, dashboard lights (ABS, handbrake) | Real ground speed, acceleration (g-forces) |
| Effects it enables | Engine RPM, Gear shift | Collisions, Suspension bumps, G-force rumble |
| Needs both | Wheel lock: compares the wheels' speed (OutGauge) with the car's real speed (Motion Sim) while you brake (OutGauge) | |

If one of the two stops arriving, OpenShaker drops it after half a second (OutGauge) or a quarter of a second (Motion Sim).

## Effects in BeamNG.drive

| Effect | Status | Needs | What you feel, and why |
|---|---|---|---|
| Engine RPM | Yes | OutGauge | A tone at about one pulse per engine turn, with a faint overtone, at HaptiConnect's BeamNG level. It is **much stronger** than in Forza. |
| Gear shift | Yes | OutGauge | A 165 ms kick pitched by the revs (10-120 Hz), longer than Forza's. A quick shift through neutral is felt once. |
| Wheel lock (braking) | Partly | Both | A steady ~56 Hz tone while you brake and the wheels turn at less than about half the car's real speed. BeamNG gives one reading for the whole car, so OpenShaker can't tell which wheel locked. Its strength isn't checked against HaptiConnect yet. |
| Wheel slip / slide | Silenced | – | HaptiConnect's BeamNG preset has no slip effect. BeamNG also reports no sideways slide. |
| ABS pulse | Silenced | – | BeamNG shows the ABS light (OpenShaker only counts it while you brake), but HaptiConnect's BeamNG preset has no ABS effect. |
| Suspension bumps | Partly | Motion Sim | **BeamNG doesn't report suspension travel.** Instead, OpenShaker plays a fixed 45 Hz thump when the vertical g jumps suddenly (by more than about 1.2 g), at most one every 0.15 s. There is no continuous road rumble. Its strength isn't checked against HaptiConnect yet. |
| Kerbs / rough road | No data | – | BeamNG reports no kerbs or surfaces, and the preset also ships it at zero. |
| Collisions | Yes | Motion Sim | A short 60 Hz hit when the combined forward and sideways g rises more than about 1.5 g above its recent level for 30 ms. Its level is **set above full scale**, so at full Master every crash briefly turns the rest of the mix down. Its strength isn't checked against HaptiConnect yet. |
| G-force rumble | Yes | Motion Sim | A 60 Hz tone that follows whichever is strongest: braking from about 0.4 g (full by about 0.5 g), cornering from about 0.6 g (full by about 1 g), and acceleration only above about 0.8 g. |
| Shift indicator | Silenced | – | Off and at zero. HaptiConnect's BeamNG preset has no shift light. |
| Grip limit warning | Off | Both | You can tick it, but in BeamNG it only sees wheelspin and lock, not sideways slides. |
| Surface feel, Landings, Turbo & reactor boost | No data | – | BeamNG doesn't report these. |

## Tips and quirks

- **If you play BeamNG, set your amplifier with it.** Most of the time it plays close to the Test tone level.
- **Port 4444 must be free.** If another program (HaptiConnect or SimHub, for example) is using it, the status reads "cannot bind UDP … is HaptiConnect, SimHub or another tool using it?".
- **BeamNG's OutGauge and Motion Sim don't report pauses**, so the window doesn't show "(paused)" for BeamNG. The effects go quiet one second after data stops arriving.
- If crashes never register, or register all the time, you can scale the acceleration with `sources.beamng.accel_scale` in `%APPDATA%\OpenShaker\config.json`. This is for advanced users.
- If you run OpenShaker from source, you can check a recorded drive with `python -m openshaker.beamng_check`. See [CALIBRATION.md](../CALIBRATION.md#tuning-a-game-from-your-own-drive-no-hapticonnect).

## Known limits

- HaptiConnect plays a buzzing rev-limiter sound (~60 Hz) that OpenShaker's BeamNG preset doesn't have yet.
- Wheel-lock, crash and bump strengths couldn't be checked against HaptiConnect, because its own output dropped out at those moments. They keep their earlier balance.
- The Motion Sim directions were checked on one drive only.

---

**Next:** [Trackmania](Trackmania.md)

**See also:** [Safety](Safety.md) · [Setting up your games](Setting-Up-Your-Games.md)
