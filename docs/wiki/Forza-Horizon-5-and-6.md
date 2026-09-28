# Forza Horizon 5 and 6

[OpenShaker guide](README.md) › Games

Setting up Forza Horizon 5 and 6, how OpenShaker tells them apart, what each effect does in them, and what is still different from HaptiConnect.

## Setup

1. In the game, open **Settings > HUD and Gameplay**.
2. Set **Data Out** to **On**, the IP address to `127.0.0.1` and the port to `5555`.
3. Drive. OpenShaker switches to the **Forza Horizon 5** or **Forza Horizon 6** preset by itself.

Horizon has only one Data Out format, so there is no format to choose. To play from an Xbox or another PC, see [Playing from an Xbox or another PC](Setting-Up-Your-Games.md#playing-from-an-xbox-or-another-pc), and read the note below about telling 5 and 6 apart.

## How OpenShaker connects and tells 5 from 6

- Horizon uses the same UDP port **5555** as Forza Motorsport.
- **Forza Horizon 5 and 6 send identical data.** OpenShaker tells them apart by checking which game program is running on this PC: `forzahorizon5.exe` or `forzahorizon6.exe`. It checks about every 5 seconds.
- If neither program is found (for example, the game runs on an Xbox or another PC), OpenShaker keeps the Horizon preset that is already active. If none is active, it uses Forza Horizon 5.
- **Forza Horizon 4** sends the same data (untested), so it plays with the Horizon preset that is active, or with Forza Horizon 5.
- **Separate strengths, shared tuning.** The Horizon 5 and Horizon 6 presets share one calibration, but each keeps its own strengths and switches. A change to one never moves the other. The tray's `Profile:` line reads `forza_horizon` for both.
- After a restart, the window opens on **Forza Horizon 5** until Horizon 6 is detected again.
- If the wrong Horizon preset keeps being picked (for example, because the game program has another name), you can change the program names in the `game_processes` setting in `%APPDATA%\OpenShaker\config.json`.

## Effects in Forza Horizon

| Effect | Status | What you feel, and why |
|---|---|---|
| Engine RPM | Yes | A steady tone at one pulse per engine turn (3,000 rpm is about 50 Hz), at the same level at every rpm. |
| Gear shift | Yes | A short 80 ms kick pitched by the revs, into neutral and into gears, the same as in Forza Motorsport. |
| Wheel lock (braking) | Yes | A steady ~54.5 Hz tone while a wheel locks under braking. It reacts to **lighter lock-ups** than the Forza Motorsport preset. It needs the brake or handbrake above 5 % and a speed above 7 km/h. |
| Wheel slip / slide | Yes | Rear-wheel spin and sideways sliding as two ~54.5 Hz tones. Unlike Forza Motorsport, it **keeps playing in big slides**. |
| ABS pulse | No data | Horizon's Data Out has no ABS information, so this never plays, even though the box is ticked. |
| Suspension bumps | Yes | A continuous road-bed rumble that follows the suspension's movement in metres, timed on the game's own clock. On top of it plays a band of 37-45 Hz rumble noise, so it sounds broader than Motorsport's single tone. |
| Kerbs / rough road | No data | **Horizon never reports rumble strips**, so this plays nothing in the game, even though the box is ticked. It does play in Demo, which is misleading. |
| Collisions | Yes | A short, fixed-strength 50 Hz hit, detected the same way as in Forza Motorsport. |
| G-force rumble | Yes | A 59 Hz tone. When you are not braking, it **adds** forward and sideways g together, so cornering under power builds up more. Under braking it follows whichever is stronger. It can go past 100 % of its calibrated level (up to 140 %). |
| Shift indicator | Yes | A steady 70 Hz tone from about 84-85 % of the car's maximum rpm. It stays on when you lift off and is practically silent in reverse. |
| Grip limit warning | Off | You can tick it (see [Grip limit warning](Grip-and-Braking.md#grip-limit-warning)). |
| Surface feel, Landings, Turbo & reactor boost | No data | Horizon doesn't report surfaces, airtime or boosts. |

## Known limits

Measured against HaptiConnect:

- Laps play 0 to 1.3 dB quieter overall.
- **Very rough ground** plays about 7-10 dB weaker. Only one recorded lap had such surfaces.
- **Horizon 5 and 6 share one tuning**, while HaptiConnect plays them noticeably differently. Its road rumble differs by up to 6-7 dB depending on suspension speed.
- **Collisions fire too eagerly:** on the four Horizon laps, 11 to 21 of the 40 detected crashes had no matching HaptiConnect hit, depending on how strictly a hit is counted. OpenShaker also misses some of HaptiConnect's hits.
- **Wheel slip** plays about 4 dB weaker and **wheel lock** about 7 dB weaker. At walking pace, the road rumble is far too strong.
- Braking, ABS and kerbs couldn't be measured in Horizon.

---

**Next:** [Assetto Corsa EVO](Assetto-Corsa-EVO.md)

**See also:** [Forza Motorsport](Forza-Motorsport.md) · [Presets and strengths](Presets-and-Strengths.md)
