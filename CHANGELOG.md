# Changelog

All notable changes to OpenShaker are listed here. Versions follow [semantic versioning](https://semver.org/).

## [1.0.1] - 2026-09-28

### Added
- **Update check with one-click update.** Once a day OpenShaker asks GitHub whether a newer version
  exists. There are no pop-ups: the tray icon gets a small "!", the tray menu an **Update to X.Y.Z**
  item and the window a bar with **Update now**, **What's new** and **Skip this version**.
  - **Update now** downloads the installer from the GitHub release, checks its size and SHA-256,
    installs it and starts OpenShaker again, without an administrator prompt.
  - Nothing is downloaded before you click it.
  - Switch the check off under **Advanced... > Check for updates**
    ([how updating works](docs/wiki/Start-With-Windows-Updates-and-Uninstalling.md#updating)).

### Changed
- The window no longer opens about 1,480 px wide: the status and game-source lines wrap at the window's
  width, and the sources are listed one per line.
- The installer includes Python's `ssl` module (OpenSSL) for the update check's HTTPS request.
- Run over an installed copy, the installer's two boxes start from what you have now (Start with
  Windows, desktop shortcut), and unticking one removes it. If the installer is cancelled or stops after
  closing OpenShaker, it starts OpenShaker again.

## [1.0.0] - 2026-09-28

The first public release.

### Games
- **Forza Motorsport, Forza Horizon 5 and Forza Horizon 6** through the games' own Data Out telemetry
  (Horizon 5 and 6 are told apart by the running game).
- **Assetto Corsa EVO** through its shared memory - nothing to set up.
- **BeamNG.drive** through its built-in OutGauge and Motion Sim outputs - no mod.
- **Trackmania** through Openplanet's Data Sender plugin, with Trackmania-only effects: surface feel,
  landings, turbo and reactor boost, and a grip-limit warning.

### Feel
- Engine, gear shifts, shift light, wheel lock and slip, ABS, road rumble, kerbs, crashes and
  acceleration, tuned to match HaptiConnect 2.7.0's output on recorded laps
  ([how it was tuned](docs/HOW_IT_WAS_TUNED.md)). The short hits are generated from measured numbers;
  no recorded audio is included.
- One preset per game with a strength slider for every effect; the preset follows the game you drive.
- An output limiter, left-channel output by default (Right or Both selectable) and a quieter Demo mode.

### App
- Lives in the tray, starts with Windows if you like, and recovers by itself when the shaker is
  unplugged and plugged back in.
- Plays to the shaker you pick by name, so an unplugged shaker never falls back to your speakers.
- One-screen installer without administrator rights; clean uninstall.
- **Send feedback / report a bug** in the tray menu, and issue forms for bugs, feel reports and ideas.

[1.0.1]: https://github.com/baddo-baddo/OpenShaker/releases/tag/v1.0.1
[1.0.0]: https://github.com/baddo-baddo/OpenShaker/releases/tag/v1.0.0
