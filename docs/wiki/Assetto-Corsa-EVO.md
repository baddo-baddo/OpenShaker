# Assetto Corsa EVO

[OpenShaker guide](README.md) › Games

Assetto Corsa EVO needs no setup; this page covers how OpenShaker reads it, what each effect does in it, the older Assetto Corsa games, and what is still different from HaptiConnect.

## Setup

Nothing to set in the game. Start OpenShaker, start a session, and drive.

## How OpenShaker connects

- OpenShaker reads the game's **shared memory**: data the game publishes on your PC for other programs to read. It only reads, and it uses no network port, so it can run next to other tools, including HaptiConnect.
- The sources line reads "waiting for Assetto Corsa EVO" until the game is running, then "attached to …".
- **Paused, in replays or in menus:** the game only counts as live while its session is live and the engine is running, the revs are above zero or the car is moving. At other times the window shows **(paused)**.
- If the game stops updating for 5 seconds (for example, when you quit), OpenShaker lets go and waits for it again.
- The game must run on the same PC as OpenShaker.
- Two settings under **Advanced...**:
  - **ACE poll rate (Hz):** how often OpenShaker reads the game. The default is 200, and the minimum is 20.
  - **ACE suspension travel scale (m):** how many metres of suspension travel count as "full". The default is 0.08. Changing it changes how strong the suspension rumble is.
- Good to know: HaptiConnect 2.7.0 no longer gets live data from current Assetto Corsa EVO builds, because the game now publishes its data under new names. OpenShaker reads the new names.

## Effects in Assetto Corsa EVO

| Effect | Status | What you feel, and why |
|---|---|---|
| Engine RPM | Yes | A steady tone at one pulse per engine turn, at the same level at every rpm, as in Forza Motorsport. |
| Gear shift | Yes | A short kick pitched by the revs, **only when a gear engages**, never on the way into neutral. HaptiConnect's ACE plugin behaves the same way: 45 of 47 changes into a gear fired, and 0 of 35 into neutral. |
| Wheel lock (braking) | Yes | A steady ~56 Hz tone while a wheel is locked hard under braking. It is quieter than in Forza. |
| Wheel slip / slide | Yes | Rear-wheel spin and sideways sliding as two ~54.5 Hz tones. The game's own "slip vibration" signal also feeds it. You don't need to be on the throttle, but slip is only read above walking pace. |
| ABS pulse | Silenced | The game reports ABS, but the preset ships it at zero. This was a deliberate choice, not missing data: in the reference drives, HaptiConnect's ABS response couldn't be separated from wheel lock. |
| Suspension bumps | Yes | A continuous road-bed rumble that grows as the suspension works harder. |
| Kerbs / rough road | Silenced | HaptiConnect's ACE plugin has no kerb effect: you feel its extra kerb energy through the suspension rumble. OpenShaker does the same. |
| Collisions | Yes | A short, fixed-strength ~48 Hz hit, detected the same way as in Forza. |
| G-force rumble | Partly | **Forward acceleration only:** it starts at about 0.2 g and is full by about 0.5 g. Braking and cornering add nothing. This was fitted to HaptiConnect's ACE plugin under forward acceleration. HaptiConnect also plays a little while cornering and braking, which OpenShaker doesn't copy (see Known limits). |
| Shift indicator | Silenced | HaptiConnect's ACE plugin has no shift light. |
| Grip limit warning | Off | You can tick it (see [Grip limit warning](Grip-and-Braking.md#grip-limit-warning)). |
| Surface feel, Landings, Turbo & reactor boost | No data | The game doesn't report these. |

## Assetto Corsa and Assetto Corsa Competizione (untested)

The older games publish similar shared memory under older names, and OpenShaker reads those too. They use the **Assetto Corsa EVO preset** and are shown as "Assetto Corsa EVO". Much less data is available, though:

- There is no wheel slip data, so **Wheel lock, Wheel slip and the Grip limit warning don't play**.
- There are no ABS, traction-control or vibration signals.
- OpenShaker learns the maximum rpm from the highest rpm it sees (at least 6,000).

Engine, gear shift, suspension, collisions and G-force rumble work as in Assetto Corsa EVO.

## Known limits

- The HaptiConnect reference recordings contain two copies of its output, so the exact loudness is less certain than for Forza.
- HaptiConnect seems to respond to cornering in ACE, and OpenShaker plays about 8 dB less there. HaptiConnect also plays a little under braking, where OpenShaker is about 7 dB short.
- The two reference recordings disagree about deep slides by about 15 dB: OpenShaker plays 14 dB more than one and 1.4 dB less than the other.

---

**Next:** [BeamNG.drive](BeamNG-Drive.md)

**See also:** [Setting up your games](Setting-Up-Your-Games.md) · [Advanced settings](Advanced-Settings.md)
