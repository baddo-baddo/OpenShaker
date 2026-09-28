# Setting up your games

[OpenShaker guide](README.md) › Getting started

Which setting to change in each game, how OpenShaker receives the data, and how to share the game ports with other apps or play from an Xbox or another PC.

## At a glance

| Game | What to set in the game | How OpenShaker gets the data | Preset it uses | How well it was tested |
|---|---|---|---|---|
| **Forza Motorsport** | Data Out **On**, IP `127.0.0.1`, port `5555`, format **Car Dash** | Listens on UDP port 5555 | Forza Motorsport | Live: 8 laps, all within 0.4 dB of HaptiConnect |
| **Forza Horizon 5 / 6** | Data Out **On**, IP `127.0.0.1`, port `5555` | Listens on UDP port 5555. It tells 5 and 6 apart by which game program is running | Forza Horizon 5 or Forza Horizon 6 | Live: laps play 0 to 1.3 dB quieter than HaptiConnect |
| **Assetto Corsa EVO** | Nothing | Reads the game's shared memory (no port) | Assetto Corsa EVO | Live and felt. Compared with HaptiConnect's ACE plugin through a replay: +0.4 and -0.5 dB (scored at one copy's level; the recordings likely hold HaptiConnect's output twice) |
| **BeamNG.drive** | Options > Other: tick **OutGauge** and **Motion Sim**, both `127.0.0.1` port `4444` | Listens on UDP port 4444 | BeamNG.drive | Live: within 0.6 dB. Crash, bump and wheel-lock strengths not yet checked |
| **Trackmania** | Install Openplanet and its **Data Sender** plugin | Connects to Data Sender on TCP port 28765 | Trackmania | Live and felt (Stadium car). All levels are first guesses |
| Forza Horizon 4 *(untested)* | Same as Horizon 5 | Same as Horizon 5 | The Horizon preset that is already active, otherwise Forza Horizon 5 | Should work: it sends the same data as Horizon 5 |
| Assetto Corsa / ACC *(untested)* | Nothing | Same shared memory, under older names | Assetto Corsa EVO | Basic effects only |

**HaptiConnect** is ButtKicker's own app. The Forza, Assetto Corsa EVO and BeamNG presets were tuned to match the output of HaptiConnect 2.7.0 on a ButtKicker PRO. HaptiConnect doesn't support Trackmania, so the Trackmania levels are the maintainer's first guesses.

Each game has its own page with the setup steps, how OpenShaker connects, which effects play and the known limits: [Forza Motorsport](Forza-Motorsport.md) · [Forza Horizon 5 and 6](Forza-Horizon-5-and-6.md) · [Assetto Corsa EVO](Assetto-Corsa-EVO.md) · [BeamNG.drive](BeamNG-Drive.md) · [Trackmania](Trackmania.md).

## Running next to other haptics apps

| What | Default | Can it be shared? |
|---|---|---|
| Forza Data Out | UDP 5555 | **No.** Only one program can receive on the port. If HaptiConnect or another tool has it, you'll see "cannot bind UDP 5555 ... is HaptiConnect or another tool using it?" |
| BeamNG OutGauge + Motion Sim | UDP 4444 | **No.** "... is HaptiConnect, SimHub or another tool using it?" |
| Assetto Corsa EVO | Shared memory | **Yes.** OpenShaker only reads it. |
| Trackmania Data Sender | TCP 28765 | **Yes**, up to the plugin's "TCP max clients" (8 by default) |
| OpenShaker's own lock | TCP 49731, this PC only | Only if another program happens to use that port (see Troubleshooting) |
| Shaker output | Shared mode | Yes, unless another app takes it exclusively |

**To let another app use the game ports:**
- Untick **Haptics on** (window or tray). This frees every game port, and the setting is remembered until you tick it again.
- Or quit with tray > **Quit**, or `OpenShaker.exe --quit`.
- Or start with `--no-start` for one session.
- Or move one game to another port, both in the game and in **Advanced...**.
- Or stop listening for one game for good with `sources.<game>.enabled: false` in the settings file.

**Other points:**
- HaptiConnect's own Forza plugins listen on port **5301** (Forza Horizon 5) and **5305** (Forza Motorsport). If Forza's Data Out points there, the data goes to HaptiConnect, not OpenShaker.
- OpenShaker doesn't pass telemetry on to other apps.
- If two supported games send data at once, the newest data wins and the preset can flip between them. Run one game at a time.

## Playing from an Xbox or another PC

- For **Forza** on an Xbox or another PC:
  1. Set **Advanced > Forza listen address** to `0.0.0.0`.
  2. Point the game's Data Out at **this PC's network address**, on port 5555.
  3. When Windows Firewall asks, allow OpenShaker. The installer adds no firewall rule, so Windows asks the first time.
- The default, 127.0.0.1, only accepts games on the same PC.
- With Forza Horizon on another machine, OpenShaker can't see which Horizon game is running. It keeps the current Horizon preset, or uses Forza Horizon 5. Both presets share the same calibration, so only your own strength changes differ.
- The BeamNG and Trackmania addresses can only be changed in the settings file (`sources.beamng.host`, `sources.trackmania.host`).
- **Assetto Corsa EVO must run on the same PC**, because its data is shared memory.

---

**Next:** [Is it working?](Is-It-Working.md)

**See also:** [Troubleshooting](Troubleshooting.md) · [Advanced settings](Advanced-Settings.md)
