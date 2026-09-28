# Glossary

[OpenShaker guide](README.md) › Help

The words this guide uses, in plain language.

- **Telemetry:** live data a game sends about the car: revs, gear, speed, g-forces, wheel slip, suspension. OpenShaker converts every game's data into one common form.
- **Effect:** one kind of feeling, such as the engine, a gear kick or a kerb. There are 14.
- **Preset:** your settings for one game: each effect's strength and on/off switch. It is saved automatically.
- **Profile:** the calibration file that ships with OpenShaker for a game. It sets how each effect sounds and its calibrated level. You don't edit it. Forza Horizon 5 and 6 share one profile but have separate presets.
- **Strength:** the per-effect slider, 0-200 %. 100 % is the calibrated level.
- **Master:** one volume control for everything, 0-100 %.
- **Calibrated level:** the level a profile ships with. For Forza, ACE and BeamNG it was fitted to HaptiConnect's output on a ButtKicker PRO; for Trackmania it is a first guess.
- **Silenced:** an effect a preset ships at zero level. No strength setting makes it play.
- **Hz (hertz):** vibrations per second. Shakers work best at about 20-90 Hz.
- **dB, dBFS:** a loudness scale. 0 dBFS is the loudest a digital signal can be; -6 dB is about half the level.
- **Limiter:** the last stage before the shaker. It turns everything down briefly instead of letting peaks distort.
- **Dropouts:** moments when the audio stuttered. They are counted in the status line and tray.
- **Rumble strip / kerb:** the striped edge of a track. Forza Motorsport reports when a wheel is on one, and Assetto Corsa EVO sends a kerb signal; Forza Horizon never does.
- **Wheel lock:** a wheel stopping, or nearly stopping, under braking while the car still moves.
- **Wheel slip / slide:** wheels spinning faster than the car moves (wheelspin), or the car moving sideways (sliding).
- **G-force (g):** acceleration measured against gravity. 1 g ≈ 9.8 m/s².
- **Data Out:** Forza's setting that sends telemetry over the network. Its formats are "Sled" (no gear or pedal data), Horizon, and Motorsport "Car Dash".
- **OutGauge:** BeamNG's built-in dashboard data: revs, gear, pedals, dash lights, wheel speed.
- **Motion Sim:** BeamNG's built-in motion data: speed, g-forces and orientation.
- **Shared memory:** a block of memory a game publishes for other programs to read. Assetto Corsa EVO uses it.
- **Openplanet:** a free modding platform for Trackmania.
- **Data Sender:** an Openplanet plugin by ar that sends Trackmania car data to programs like OpenShaker.
- **UDP / TCP port:** a numbered "door" on your PC that game data arrives through. Only one program can listen on a given UDP port.
- **WASAPI, shared mode:** the Windows audio system OpenShaker prefers (it falls back to DirectSound or MME), in a mode that lets other apps play to the same device.
- **HaptiConnect:** ButtKicker's own app. The Forza, ACE and BeamNG presets were calibrated to match it.
- **Tray / notification area:** the icons next to the clock on the Windows taskbar.
- **One-shot:** an effect that plays a short sound once per event, such as a gear shift, a collision or a landing.
- **Slip ratio:** how much faster (spin) or slower (lock) a wheel turns than the road passes under it. 1.0 is roughly the grip limit.
- **Slip angle:** how far a tyre is sliding sideways. 1.0 is roughly the grip limit.

---

**Next:** back to the [OpenShaker guide](README.md)

**See also:** [Effects overview](Effects-Overview.md) · [FAQ](FAQ.md)
