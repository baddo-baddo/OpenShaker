# Is it working?

[OpenShaker guide](README.md) › Getting started

How to tell that OpenShaker is running and hearing your game, what it does when something is missing, and how to try the effects without a game.

## The status line

The line under **Start with Windows** in the window shows the state of the haptics:

| Text | Meaning |
|---|---|
| `Haptics off` | The switch is off. |
| `Haptics off (--no-start) - Haptics on starts them` | This launch was started with `--no-start`. |
| `Starting...` | The output and the game listeners are opening. |
| `Not running: <error> - retrying every 3 s` (or `15 s`) | Starting failed. OpenShaker keeps trying. |
| `Running -> <device> [<audio system>] @ <rate> Hz, <latency> ms   \|   <game or "no game"> -> profile <profile>` | Everything is working. `, N dropouts` appears after the latency if the audio has stuttered. |
| `Audio error: ...` | Rendering an audio block failed. That block was replaced with silence. |

## The tray icon

- The icon is **in colour while the haptics are running**. It is **grey** while starting, stopped, failed or switched off.
- Hovering over it shows `OpenShaker - running - <game or "no game">`, `OpenShaker - starting`, `OpenShaker - NOT running` or `OpenShaker - haptics off`.
- **Left-click** opens the window.

## The preset follows the game

You never pick a game. OpenShaker works it out:

- **It listens for every game at once.** While **Haptics on** is ticked and **Games** (not Demo) is selected, all four listeners run: Forza, BeamNG, Assetto Corsa EVO and Trackmania. The grey status line at the bottom of the window's Telemetry box (called the *sources line* on this page) shows each listener's status, for example `Forza (UDP): listening on UDP 5555`.
- **The preset follows the game.** When a game's data arrives, OpenShaker switches to that game's preset, and the message line says "*<game>* preset is active". Each game keeps its own strengths and on/off switches, and they save themselves.
- **Before any game is detected:** on a fresh install, the Forza Motorsport preset is active. After that, OpenShaker starts with the preset that was active the last time it saved its settings (it also saves when you quit).
- **Picking a preset by hand:** while the haptics are running, picking another preset only opens it for editing. The note next to the picker then says "(editing; *<preset>* is active)", and what you feel still follows the detected game. While the haptics are stopped, the preset you pick becomes the active one.
- **Several games at once:** every 10 ms, OpenShaker plays whichever game sent the newest data, and the preset can flip between them. Run one game at a time.

## Pauses, menus, replays and respawns

- **No data for 1 second** means everything goes silent. The window shows "no game detected (waiting for telemetry)".
- **Paused or in a menu:** the window and tray add "(paused)" and the effects go quiet. Each effect also
  resets itself, so un-pausing doesn't set off a false bump, crash or gear shift. What counts as paused
  depends on the game:
  - **Forza** keeps sending in menus but marks them as "not racing".
  - **Assetto Corsa EVO** counts as live only while you are driving, not in replays or pauses.
  - **Trackmania** sends nothing in menus or when spectating nothing, so it goes silent after 1 s.
  - **BeamNG** marks all its data as live, so it is silent only if the game stops sending.
- **Nothing fires by mistake on resume:**
  - a gear change made during a pause doesn't kick;
  - unpausing isn't felt as a bump;
  - a crash just before a pause doesn't play after it.
- **Trackmania respawns and restarts** mute the effects for 60 ms and start detection over, so a teleport never feels like a crash, a shift or a bump.
- **Reconnecting:** OpenShaker finds Trackmania's Data Sender again by itself (it retries every 1-2 s), and re-attaches to Assetto Corsa EVO when a new session starts.

## When something is missing, it keeps trying

- If starting fails (for example the shaker is still asleep at boot, or Windows hasn't found it yet), OpenShaker retries every **15 s**. Each try looks for sound devices again, so a USB shaker that appears after boot is found.
- If the shaker stops playing for 2 s (unplugged or switched off), OpenShaker says so, then retries every **3 s for the first minute** and every 15 s after that. **Restart haptics** retries straight away.
- The shaker output opens before the game listeners. If another program holds the shaker exclusively, the start fails before any game port is opened.
- A game port held by another program does not stop the start. That game's listener shows the error (in the Sources line and as the tray's `Problem:` line) and stays stopped until you press **Restart haptics** or switch the haptics off and on.

## Try the Demo

Pick **Demo** at the top right of the window to feel the effects without a game, and **Games** again to go back. Demo plays a scripted 24-second loop through the **currently active preset**, with your strengths. It is not a preset of its own and doesn't switch presets. The current scene shows in the Telemetry header.

| Time | Phase |
|---|---|
| 0-2 s | Idle |
| 2-10 s | Accelerating through gears 1-5 |
| 10-12 s | Rumble strip (right-side wheels) |
| 12-13.5 s | Braking with front lock-up |
| 13.5-15 s | Big bump |
| 15-16 s | Impact |
| 16-19 s | Wheelspin |
| 19-21 s | ABS braking |
| 21-24 s | Coasting |

**Good to know:**

- The Demo is a quiet preview. It plays at about 40 %, is scaled down further for loud presets such as BeamNG, and is capped at -6.1 dBFS whatever you set. Test tone is *not* capped.
- **Surface feel, Landings and Turbo & reactor boost never play in the Demo.** It sends no surface, airtime or boost data. The **Grip limit warning** never plays either, in any preset, because the Demo's slip values are either 0 or far past the limit.
- The lock-up is a slip of 3.0. That is below the 3.5 threshold of the Forza Motorsport, Assetto Corsa EVO and BeamNG presets, so the braking phase has no wheel lock there. With Forza Horizon (threshold 1.0) and Trackmania it plays.
- The wheelspin is a rear-wheel spin of 3.0. Forza Motorsport ignores spin past 1.4, so that phase plays no Wheel slip with the Forza Motorsport preset.
- **ABS pulse** is audible in the Demo only while a Forza preset is active. The Assetto Corsa EVO and BeamNG presets have it at level 0, and Trackmania has it switched off.
- The **Kerbs** phase plays with either Forza preset. This is the only place you will hear the Forza Horizon kerb sound.
- While Demo runs, OpenShaker doesn't listen to any game, so the game ports are free.

---

**Next:** [Forza Motorsport](Forza-Motorsport.md)

**See also:** [The main window](The-Main-Window.md) · [The tray menu](The-Tray-Menu.md) · [Troubleshooting](Troubleshooting.md)
