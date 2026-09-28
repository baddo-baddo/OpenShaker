# Troubleshooting

[OpenShaker guide](README.md) › Help

Symptoms and messages, their likely cause, and the fix.

| Symptom or message | Likely cause | Fix |
|---|---|---|
| "Windows protected your PC" when installing | The installer isn't code-signed | Click **More info**, then **Run anyway** |
| "output device '...' is not connected - pick your shaker under Output > Device" | The named device isn't there, or Windows hasn't found it yet after boot | Pick your shaker under **Device**. OpenShaker also retries every 15 s. |
| "... is only offered on an exclusive host API right now ... probably still waking up" | The shaker was only just plugged in or switched on | Wait. The next retry picks it up. |
| "... stopped playing - unplugged or switched off?" | The shaker was unplugged or powered off | Plug it back in or switch it on. OpenShaker retries every 3 s for a minute, then every 15 s. **Restart haptics** tries now. |
| Grey tray icon, nothing plays, "Haptics off" | **Haptics on** is unticked (remembered across restarts), or `--no-start` was used | Tick **Haptics on** or press **Restart haptics** |
| "Running" but the shaker is quiet | Wrong channel, Windows volume low, amplifier off, or no game data | Press **Test tone**. Try Advanced > Output channel **Right** or **Both**. Check the Windows volume and the amp. Press **Restart haptics**. |
| "cannot bind UDP 5555 ... is HaptiConnect or another tool using it?" (or 4444, also naming SimHub) | Another program has the game's port | Close the other program, then press **Restart haptics** (OpenShaker doesn't retry the port by itself). Or move the port in the game and in **Advanced...** |
| "no game detected (waiting for telemetry)" while driving | Data Out off in the game, wrong IP or port, or the game is on another machine | Check [Setting up your games](Setting-Up-Your-Games.md). For an Xbox or another PC, set the Forza listen address to 0.0.0.0. |
| BeamNG: "OutGauge only: tick Motion Sim ..." or "Motion Sim only: tick OutGauge ..." | One of BeamNG's two protocols is off or on a different port | Tick both in Options > Other, or set the Motion Sim port in **Advanced...** |
| BeamNG: collisions never or always trigger | BeamNG's g-force scale doesn't suit your car | Adjust `sources.beamng.accel_scale` in the settings file |
| Forza Motorsport: no gear shifts or wheel lock | Data Out format is "Sled" | Set the format to **Car Dash** |
| Forza Horizon: kerbs do nothing | Horizon never reports kerbs | Expected |
| ABS pulse never plays | No game gives it data with the shipped presets | Expected. See [ABS pulse](Grip-and-Braking.md#abs-pulse). |
| A slider does nothing | The preset ships that effect at zero, or the game has no data for it | Expected. See [the table](Effects-Overview.md#effect-support-by-game). |
| Wrong Horizon preset (5 vs 6) | The game runs on another machine, or its program name is different | Pick the right strengths in the right preset, or edit `game_processes` in the settings file |
| Assetto Corsa EVO: "waiting for Assetto Corsa EVO" | The game isn't running, or hasn't updated for 5 s | Start a session. It re-attaches by itself. |
| Trackmania: "waiting for Openplanet Data Sender on 127.0.0.1:28765 ..." | Openplanet or Data Sender isn't running | Start Trackmania with Openplanet and the Data Sender plugin |
| Trackmania: "... refuses control commands: tick Allow external control commands (TCP Server tab), or press Start and tick Start service on plugin load (General tab)" | Data Sender won't take commands | Do either of those in Data Sender's settings |
| Trackmania: "Data Sender is full: raise TCP max clients ..." | All the plugin's client slots are in use (8 by default) | Raise **TCP max clients** in Data Sender (TCP Server tab) |
| Everything ducks under big hits; Level near 0 dB | The limiter is at work | Lower Master or the loudest effect's strength |
| "... saved; they apply when the haptics are switched on" | You changed a setting while the haptics were off | Switch them on |
| "Could not save settings: ..." or the Haptics on switch "could not be saved" | The settings folder isn't writable | Fix the permissions on `%APPDATA%\OpenShaker` |
| The window won't open, or "another copy seems to be running but does not answer, or another program is using its local port 49731" | A stuck copy, or a port clash | Quit OpenShaker from the tray or Task Manager. Read `%APPDATA%\OpenShaker\logs\gui_error.log`. To reset to defaults, delete `config.json`. |
| "Update to X.Y.Z failed: ... Nothing was installed; Update now tries again." | No internet, GitHub not reachable, the download did not match its published size or SHA-256 (it was deleted), or the installer ended early | Try **Update now** again later, or download the installer from the release page (**What's new**). `logs\update.log` in the settings folder says what happened. |
| "The update did not install, so OpenShaker X was started again." | The installer could not finish (a file was locked, or OpenShaker did not close in time) and put the old version back | Nothing to repair; the update is offered again at the next check |
| Can't find the window | Closing it only hides it | Left-click the tray icon, or start OpenShaker from the Start menu |
| "(no tray icon: ...)" (source copies) | The tray packages aren't installed | Install the requirements |
| A console window opens at sign-in (source copies) | The Python used at sign-in is a launcher stub | Run `python -m openshaker.autostart repair` from the source copy's environment |

Still stuck? Use tray > **Send feedback / report a bug**.

---

**Next:** [FAQ](FAQ.md)

**See also:** [Is it working?](Is-It-Working.md)
