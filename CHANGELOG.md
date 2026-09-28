# Changelog

All notable changes to OpenShaker are listed here. Versions follow [semantic versioning](https://semver.org/).

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

[1.0.0]: https://github.com/baddo-baddo/OpenShaker/releases/tag/v1.0.0
