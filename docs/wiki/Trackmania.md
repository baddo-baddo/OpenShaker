# Trackmania

[OpenShaker guide](README.md) › Games

OpenShaker plays Trackmania (the 2020 game) through your shaker: the
engine and gear changes, every bump, landing and crash, the surface under each wheel, turbo pads,
and a warning that pulses as a corner on a loose surface builds toward a slide.

This page explains how Trackmania support works, how to set it up, what each effect feels like,
how to tune it, and what is not tested yet.

## Why Trackmania is special

Most racing games have a telemetry setting: a switch in their options that sends the car's data to
programs like OpenShaker. **Trackmania has no such setting** (it keeps an older built-in interface
that few tools use). OpenShaker gets the data through [Openplanet](https://openplanet.dev), a free
and widely used add-on for Trackmania, and its **Data Sender** plugin by ar. Data Sender reads the
state of the car you are watching many times a second, down to each wheel's surface and suspension,
and offers it on a local connection on your own PC (`127.0.0.1`, port `28765`). OpenShaker connects
to it and turns what it reads into vibration.

What that means for you:

- You need Openplanet and its Data Sender plugin. Both are free: Openplanet installs from its
  website, Data Sender from inside the game.
- Nothing leaves your PC: the connection only exists between Data Sender and OpenShaker.
- The shaker follows **the car you are watching**, so in a replay or while spectating it should play
  that car (not tested yet).
- Where Openplanet plugins are not allowed, OpenShaker gets no data and the shaker stays quiet (see
  [Limits](#limits-honestly)).

## Setup, step by step

1. **Install Openplanet** from [openplanet.dev](https://openplanet.dev) if you do not have it yet.
   Version 1.26 or newer is needed.
2. **Install Data Sender.** In the game, press **F3** to show the Openplanet bar, then
   **Openplanet > Plugin Manager**. Search for **Data Sender** (by ar,
   [openplanet.dev/plugin/datasender](https://openplanet.dev/plugin/datasender)) and click **Install**.
3. **Start OpenShaker** (it may already be running in the notification area) and load any map.

That is all. Data Sender ships with its service stopped and sending only ten times a second, so
**OpenShaker sets it up by itself** each time it connects:

- it **starts Data Sender's service** if it is stopped;
- it changes Data Sender's **broadcast interval from the default 100 ms to 0** (every frame), so
  bumps and crashes are not missed. An interval you chose yourself is left alone;
- for its own connection only, it switches off Data Sender's status messages, which would otherwise
  crowd out the car data;
- it changes nothing else.

**One tip.** If you raise Data Sender's **Vehicle state** rate yourself (Openplanet > Settings >
Data Sender > Sources), also set **TCP max telemetry msgs/s** to **0** on its TCP Server tab.
Otherwise the plugin's own per-second cap cuts the data off for a moment every second, and you feel
it as a stutter.

### How to see it is working

- The OpenShaker window shows **Trackmania (Openplanet)** with a frame rate, and says
  **Trackmania preset is active**. It switches to the Trackmania preset by itself.
- Right-click the tray icon: the status lines show the game and its frame rate.
- In Openplanet > Settings > Data Sender, the **General** tab says **Running** and the **TCP Server**
  tab lists OpenShaker as a client.

If the window keeps saying it is waiting for Data Sender, see
[Troubleshooting](Troubleshooting.md). It covers "Data Sender is full"
and "refuses control commands".

## What you feel

Every effect below has its own on/off box and strength slider in the Trackmania preset. The names
in bold are the names in the OpenShaker window.

### Engine and gear shifts

**Engine RPM** is a low hum whose pitch follows the revs, from about 22 Hz at idle to 80 Hz at the
limiter, and which gets stronger with the throttle. **Gear shift** is a short thump on every gear
change.

### Bumps

**Suspension bumps** follow each wheel's suspension: a quick movement plays a short knock from that
corner, and rough ground adds a fine texture.

In Trackmania a wheel's suspension stretches out fully as soon as it leaves the ground, which would
read as a big bump on every jump. OpenShaker holds each wheel's suspension still while it is in the
air, and a little before (the stretch starts just before the game says the wheel has left the
ground). After a real jump the landing effect plays the touchdown, and the bumps take over again once
the car has settled. After a small hop, only the compression beyond where the wheel was before the
hop counts as a bump.

### Landings

**Landings** plays a low thump, with a short click on top, when the car comes back down after being
in the air for at least 0.12 s. Its strength follows how fast the car was falling: from 1.5 m/s
(gentle) up to full strength at 15 m/s. Gentle touch-downs and tiny hops stay quiet, so they don't
compete with the bumps.

### Crashes

**Collisions** plays a hit when the car's own speed changes suddenly, forwards, backwards or
sideways: a wall, a barrier, another obstacle. The harder the change, the stronger the hit.

- **Landings never count as crashes.** For a moment after a landing, the ground's push is left out
  of what the crash effect sees, also on slopes and on nose-first landings, so a landing never
  plays a crash thump on top of its own.
- **Respawns and restarts are silent.** When the game teleports the car, OpenShaker ignores that
  instant, so a restart never feels like a crash.

### Surface feel

**Surface feel** gives each surface its own texture. Trackmania reports the material under each
wheel, and the roughest one sets what you feel. The texture grows with speed (full at about
145 km/h) and stops when the wheels leave the ground.

| Surface | What you feel |
|---|---|
| Tarmac, tech road | Nothing extra: the engine and the bumps carry it |
| Concrete, pavement | A faint texture |
| Dirt, dirt road, gravel, sand, rock | Rough and grainy |
| Grass, forest floor, wheat | Soft and low |
| Snow | Light |
| Ice, road ice | Almost nothing - slick |
| Plastic, rubber | Buzzy |
| Metal, metal fences | Resonant, with a ringing tone |
| Wood | A medium texture |
| Water | A slow slosh while you drive through it, and a splash as you enter |
| On the roof | A harsh scrape |

### Turbo pads and reactor boost

**Turbo & reactor boost**: driving over a turbo pad plays a surge and a rising sweep, then a light
hum while the turbo lasts. A reactor boost plays a smaller surge and a steady hum, stronger at
level 2. A boost that stays on does not fire again.

### Wheelspin and slides

**Wheel slip / slide** has two parts:

- **Wheelspin**: a low tone when the driven wheels turn faster than the car moves, for example on a
  full-throttle start. OpenShaker measures each wheel's size while you drive straight and steady, so
  it works for every car. Wheels that spin up in the air are not counted as wheelspin when they land.
  A burnout is real wheelspin and plays at full strength once the car creeps forward.
- **Slides**: a rumble while the car slides. Trackmania only says whether each tyre is sliding or
  not, with nothing in between, so the strength comes from how fast the car is moving sideways: a
  gentle drift is soft, a big skid after a crash is strong.

**Wheel lock (braking)** plays a rough buzz when braking stops the wheels turning with the road.

### The grip limit warning

**Grip limit warning** is a 55 Hz tone that pulses, faster and stronger as you get closer to losing
grip, and goes quiet the moment the car actually starts to slide. From then on the slide rumble
takes over. The gap between the two, warning then slide, is what you can learn to drive to.

Why it works the way it does:

- **Trackmania cannot warn by itself.** Its grip value is 0 while the tyres hold and jumps to "sliding"
  once they let go; there is no build-up to read. So OpenShaker watches what does build up: the
  sideways force in the corner, and how far the car points away from where it is going (body slip).
- **It only warns on loose surfaces**: dirt, dirt road, gravel, sand, grass, forest floor, wheat,
  snow, ice, road ice, and wet roads, dirt and grass. On tarmac the Stadium car turns as tightly as
  its steering allows without letting go. In the first real drives it held well over 60 m/s² of
  sideways force without sliding, so a warning there would pulse through every corner. That is why
  it stays quiet on tarmac.
- It starts at 60 % of the surface's limit, needs at least half of the wheels on the ground to be on
  a loose surface, and only plays above about 30 km/h.

For power users, the built-in limits are (sideways force in m/s², body slip in degrees): dirt, dirt
road and gravel 18 / 5; sand and wet dirt road 15 / 5; grass, forest floor and wheat 14 / 5; wet
grass 12 / 5; snow 10 / 5; ice and road ice 6 / 4; wet tarmac and pavement 30 / 5. These are first
guesses; see [Tuning](#tuning-for-power-users) to learn yours.

### Not used in Trackmania

**ABS pulse**, **Kerbs / rough road** and **Shift indicator** are off: Trackmania reports nothing that
drives them (**Surface feel** replaces the kerbs). **G-force rumble** is off too: Trackmania cars
corner so hard that it rumbled near full strength all the time. You can switch it back on.

## Tuning for power users

- **Strength sliders.** Each effect goes from 0 to 200 %, where 100 % is the shipped level. Changes
  save themselves and belong to the Trackmania preset only. **Reset preset to calibrated** puts
  every effect back to 100 %. **Master** sets the overall level for all games.
- **Learn from your own drive** (from a source checkout; see
  [DEVELOPMENT.md](../DEVELOPMENT.md#sources)). Quit the OpenShaker tray app first: a logged drive
  will not start while it runs. Then log a drive and let the tools read it:

  ```
  python -m openshaker --source trackmania --log sessions/my_drive --stop-file sessions/my_drive.stop
  python -m openshaker.tm_tune sessions/my_drive
  python -m openshaker.tm_grip sessions/my_drive
  ```

  The logging run stops when the stop file appears (create it from another window) or with Ctrl+C.
  Without `--apply` both tools only report. `tm_tune` proposes the rev range and suspension travel
  of each car, bump and crash thresholds and landing strength. `--apply --only landings` (or `cars`,
  `bumps`, `impacts`, `grip`, `names`) writes just the parts you want into
  `profiles/trackmania/profile.json`; `cars` and `bumps` belong together. `tm_grip --apply` learns
  the grip warning's limit for each loose surface from at least three clean slides on it, and never
  switches a surface back on that you switched off. Restart OpenShaker afterwards.

  A good tuning drive: full throttle to top speed, fast corners on dirt and grass pushed until the
  car slides, five or more jumps, a few wall hits, a couple of turbo pads and a respawn or two.

## Limits, honestly

- **The levels are first guesses.** They were set on the Stadium car from two felt drives and one
  logged drive. There is no reference app for Trackmania to match, as there is for the other games
  (see [How it was tuned](../HOW_IT_WAS_TUNED.md)).
- **Only the Stadium car has been driven,** on the Steam version. The Snow, Rally and Desert cars,
  the other environments and the other stores should work but are untested; each car can have its own rev range and suspension
  travel, which `tm_tune` can learn.
- **The loose-surface grip limits are guesses** until more slides have been logged. On road ice the
  game does not always report a slide as one, so the warning can keep pulsing through an ice slide.
- **Openplanet's rules apply.** Openplanet can limit which plugins may run in some places, for
  example official competitions or servers that allow only approved plugins. Where Data Sender cannot
  run, OpenShaker has no data and stays quiet.
- **Data Sender 2.0 is needed** (tested with 2.0.0 on Openplanet 1.28.0). It is a community plugin;
  a future version could change what it sends.

## Is there anything else for Trackmania?

First, what this is: **seat vibration** from a bass shaker such as a ButtKicker, **not wheel force
feedback**. Trackmania (2020) has no wheel force feedback of its own, and OpenShaker does not add any.

The big shaker apps do not support Trackmania (2020): SimHub and Sim Racing Studio list only the
older Trackmania 2 and Trackmania Turbo, and ButtKicker HaptiConnect and SimVibe list no Trackmania
game at all. **As far as we could find (September 2026), OpenShaker is the first ready-to-use
bass-shaker app with built-in effects for Trackmania (2020).**

It builds on community work, and there is earlier work worth knowing about:

- [Data Sender](https://openplanet.dev/plugin/datasender) by ar, the Openplanet plugin OpenShaker
  reads the game through.
- fentras LABS' Openplanet [Haptics](https://openplanet.dev/plugin/haptics) plugin (2022). It
  vibrates gamepads and Intiface devices from the game's revs, speed and gear. It does not drive
  bass shakers.
- Simracing-PC's [SPC-TM2020 SimHub plugin](https://simracing-pc.de/en/2025/07/24/spc-tm2020-trackmania-2020-simhub-plugin/)
  (2025). It brings Trackmania (2020)'s raw telemetry into SimHub for do-it-yourself setups, with a
  dashboard and LEDs, but has no ready-made shaker effects.

OpenShaker is an independent project. It is not made, endorsed or supported by Nadeo or Ubisoft.

If we missed a tool, tell us with the
[feedback form](https://github.com/baddo-baddo/OpenShaker/issues/new?template=hardware_feel_report.yml).

## Feedback

How does it feel on your setup? Please tell the maintainer with the
[hardware and feel report form](https://github.com/baddo-baddo/OpenShaker/issues/new?template=hardware_feel_report.yml):
your shaker and amplifier, which effects feel right, too strong, too weak or missing, and on which
surfaces or cars.

For installing OpenShaker itself and the other games, see the [README](../../README.md).

---

**Next:** [Effects overview](Effects-Overview.md)

**See also:** [Setting up your games](Setting-Up-Your-Games.md) · [Road and suspension](Road-and-Suspension.md) · [Troubleshooting](Troubleshooting.md)
