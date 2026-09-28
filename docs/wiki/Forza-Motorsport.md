# Forza Motorsport

[OpenShaker guide](README.md) › Games

Setting up Forza Motorsport, how OpenShaker reads it, what each effect does in it, and what is still different from HaptiConnect.

## Setup

1. In Forza Motorsport, open **Settings > HUD and Gameplay**.
2. Set **Data Out** to **On**, the IP address to `127.0.0.1` and the port to `5555`.
3. Set the Data Out format to **Car Dash**, not Sled (see below).
4. Drive. OpenShaker switches to the **Forza Motorsport** preset by itself.

**Playing on an Xbox or another PC?** See [Playing from an Xbox or another PC](Setting-Up-Your-Games.md#playing-from-an-xbox-or-another-pc).

## How OpenShaker connects

- OpenShaker listens for Forza's Data Out on UDP port **5555**. You can change the port under **Advanced... > Forza / Horizon Data Out port**.
- The Telemetry box shows **Forza (UDP)** and the frame rate.
- Forza keeps sending data from its menus, but marks it as "race not on". OpenShaker then shows **(paused)** and stays quiet.
- OpenShaker tells the Forza formats apart by the size of each packet:

| Data Out format | Contains | Use it? |
|---|---|---|
| **Car Dash** | Everything, including gear, throttle, brake, clutch and handbrake | **Yes** |
| **Sled** | Motion only: no gear and no pedals | No. **Gear shift and Wheel lock never play**, because they need the gear and the brake. The other effects still work |

Sled data still shows as "Forza Motorsport" and uses the same preset.

## Effects in Forza Motorsport

| Effect | Status | What you feel, and why |
|---|---|---|
| Engine RPM | Yes | A steady tone that rises with the revs: one pulse per engine turn, so 3,000 rpm is about 50 Hz. It stays at the same level at every rpm, as in HaptiConnect. |
| Gear shift | Yes (Car Dash only) | A short 80 ms kick on every gear change. Its pitch follows the revs (6,000 rpm gives 50 Hz, and it never goes below 7 Hz). It fires going into neutral as well as into a gear. |
| Wheel lock (braking) | Yes (Car Dash only) | A steady ~56 Hz tone while a wheel is locked hard under braking. It needs the brake or handbrake above 5 % and a speed above 7 km/h. |
| Wheel slip / slide | Yes | Two ~54.5 Hz tones, one for rear-wheel spin and one for sideways sliding. They start as the tyres approach their limit. They cut out again in very big spins and slides, like HaptiConnect's Forza slip effect: a wheel past about 1.4 times the grip limit (spin) or 1.2 times (slide) no longer counts. You don't need to be on the throttle. |
| ABS pulse | No data | Forza's Data Out has no ABS information, so this never plays, even though the box is ticked. |
| Suspension bumps | Yes | A continuous ~41 Hz "road bed" rumble that grows the harder the suspension works. Smooth tarmac is almost silent, and a bumpy road rumbles. This preset has no separate bump thumps. |
| Kerbs / rough road | Yes | A buzz while any wheel is on a rumble strip the game reports. The pitch rises with speed: about 35 Hz at 100 km/h, within 6-100 Hz. Only flagged rumble strips play. You feel rough ground through the suspension rumble instead. |
| Collisions | Yes | A short, fixed-strength 50 Hz hit. It plays when the car's combined forward and sideways acceleration rises more than about 1.5 g above its recent level and stays there for 30 ms. At most one hit every 0.3 s. |
| G-force rumble | Yes | A 58 Hz tone that follows whichever is strongest: braking, accelerating or cornering. Accelerating plays from about 0.2-0.3 g, reaches about 60 % by 0.4 g and stays below 80 %. Braking and cornering come in from about 0.5 g and reach full at about 0.8 g. |
| Shift indicator | Yes | A steady 70 Hz tone from about 84-85 % of the car's maximum rpm, like HaptiConnect's shift light. It stays on when you lift off and in neutral, and is practically silent in reverse. |
| Grip limit warning | Off | You can tick it. It then pulses as the tyres' slip nears the grip limit, pulses faster as you get closer, and goes quiet once they let go. It only works above about 29 km/h. No preset turns it on outside Trackmania, so it runs on its default settings. |
| Surface feel, Landings, Turbo & reactor boost | No data | Forza doesn't report surfaces, airtime or boosts. |

## Tips and quirks

- **Use Car Dash, not Sled.** Otherwise gear shifts and wheel lock are missing.
- **Port 5555 must be free.** If HaptiConnect or SimHub is using it, the status reads "cannot bind UDP 5555 … is HaptiConnect or another tool using it?". Close the other program, or pick another port in both the game and **Advanced...**.
- HaptiConnect's own Forza Motorsport plugin listens on port **5305**. Data Out aimed at 5305 goes to HaptiConnect, not OpenShaker.
- Normal driving in Forza is quieter than the **Test tone**.

## Known limits

These were measured against HaptiConnect:

- **No ABS effect.** The game doesn't send ABS data.
- **The road rumble uses an older suspension measure.** On a 9,000-rpm car it plays about 9 dB too strong. A closer version exists, but it has to wait for a better G-force sound.
- **G-force rumble is a single tone**, where HaptiConnect plays a spread-out rumble (about 52-72 Hz). Pure cornering plays about 6 dB too strong on the tuning laps. When forward and sideways g combine, it plays about 4 dB weak on the held-out laps, because OpenShaker takes the larger of the two instead of adding them.
- **Reverse:** HaptiConnect plays a faint 66-74 Hz buzz in reverse that OpenShaker doesn't (a gap of about 10.5-11.7 dB, measured on little data).
- **Collisions:** now and then, OpenShaker misses a hit that HaptiConnect plays.

---

**Next:** [Forza Horizon 5 and 6](Forza-Horizon-5-and-6.md)

**See also:** [Setting up your games](Setting-Up-Your-Games.md) · [Effect support by game](Effects-Overview.md#effect-support-by-game)
