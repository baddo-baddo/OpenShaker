# OpenShaker guide

This guide covers **OpenShaker 1.0.1**, a free Windows app by baddo & Claude. It reads live data from racing games
and turns it into low-frequency vibration for a ButtKicker or another bass shaker. The app waits in the
notification area (the tray) and plays whenever a supported game sends data.

New here? Start with [Installing OpenShaker](Installing-OpenShaker.md) and read the pages in order; each one ends
with a link to the next.

## 1. Getting started

- **[Installing OpenShaker](Installing-OpenShaker.md):** download, the browser and SmartScreen warnings, the
  one-screen installer, and the first run: amplifier down, the shaker picked by name, Test tone.
- **[Setting up your games](Setting-Up-Your-Games.md):** the one setting each game needs, sharing the game ports
  with other apps, and playing Forza from an Xbox or another PC.
- **[Is it working?](Is-It-Working.md):** the status line, the tray icon's colours, how the preset follows the
  game, what happens in pauses and menus, and the Demo.

## 2. Games

- **[Forza Motorsport](Forza-Motorsport.md):** Data Out with the Car Dash format, and what each effect does in it.
- **[Forza Horizon 5 and 6](Forza-Horizon-5-and-6.md):** one data format, two presets, and how OpenShaker tells
  the two games apart.
- **[Assetto Corsa EVO](Assetto-Corsa-EVO.md):** nothing to set up, plus the older Assetto Corsa games.
- **[BeamNG.drive](BeamNG-Drive.md):** why both OutGauge and Motion Sim need ticking.
- **[Trackmania](Trackmania.md):** the deep dive - the Openplanet Data Sender plugin, what each effect feels like,
  tuning from your own drives, and the limits.

## 3. Effects

- **[Effects overview](Effects-Overview.md):** all 14 effects at a glance, the full effect-by-game support table,
  why some effects are silent, what the strength slider does, and how the mix is kept safe.
- **[Engine and gears](Engine-and-Gears.md):** Engine RPM, Gear shift and Shift indicator.
- **[Road and suspension](Road-and-Suspension.md):** Suspension bumps, Kerbs / rough road and Surface feel.
- **[Grip and braking](Grip-and-Braking.md):** Wheel lock, Wheel slip / slide, ABS pulse and Grip limit warning.
- **[Impacts and forces](Impacts-and-Forces.md):** Collisions, G-force rumble, Landings and Turbo & reactor boost.

## 4. Using OpenShaker

- **[The main window](The-Main-Window.md):** every control, top to bottom.
- **[The tray menu](The-Tray-Menu.md):** each item of the right-click menu, and the notifications.
- **[Presets and strengths](Presets-and-Strengths.md):** one preset per game, saving, and going back to the
  calibrated levels.
- **[Advanced settings](Advanced-Settings.md):** the Advanced dialog, the settings file and logs, and the
  command-line options.
- **[Start with Windows, updates and uninstalling](Start-With-Windows-Updates-and-Uninstalling.md):** what each
  of these does and keeps.

## 5. Your hardware

- **[Shakers, amplifiers and channels](Shakers-Amplifiers-and-Channels.md):** which outputs and shakers work, the
  output channel, two shakers, and re-plugging.
- **[Safety](Safety.md):** setting the level, how loud each game plays, and what protects the output.

## 6. Help

- **[Troubleshooting](Troubleshooting.md):** symptoms and messages, their cause and the fix.
- **[FAQ](FAQ.md):** short answers to common questions.
- **[Glossary](Glossary.md):** the words this guide uses.

## 7. Behind the scenes

- **[How it was built](../HOW_IT_WAS_BUILT.md):** every problem along the way, what was found, and the fix.
- **[How it was tuned](../HOW_IT_WAS_TUNED.md):** how the effects were matched to HaptiConnect, "a detective story
  told in spectrograms".
- **[Development notes](../DEVELOPMENT.md)** and **[calibration tools](../CALIBRATION.md):** for working on the code.
- **[Contributing](../../.github/CONTRIBUTING.md):** how to report, suggest and contribute.

## Feedback

Found a bug, have an idea, or want to report how OpenShaker feels on your hardware? Open the
[feedback page](https://github.com/baddo-baddo/OpenShaker/issues/new/choose) and pick a form: **Bug report**,
**Idea / feature request** or **Hardware / feel report**. Questions go in Discussions, linked from the same page.
The tray menu's **Send feedback / report a bug** opens the same page; nothing is attached or sent automatically.
