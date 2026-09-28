# Presets and strengths

[OpenShaker guide](README.md) › Using OpenShaker

How each game gets its own preset, how strengths and switches are saved, and how to go back to the calibrated levels.

## One preset per game

A **preset** holds your settings for one game: each effect's strength and whether it is on. The **Preset** list has six entries:

- Forza Motorsport
- Forza Horizon 5
- Forza Horizon 6
- Assetto Corsa EVO
- BeamNG.drive
- Trackmania

Forza Horizon 5 and 6 use the same shipped calibration but keep **separate presets**, so a change you make for one never affects the other.

**The detected game decides what plays.** When a game starts sending telemetry, its preset becomes active, the window jumps to it, and the message line says "*&lt;preset&gt;* preset is active (*&lt;game&gt;*)."

The note next to the list tells you what editing will do:

| Note | Meaning |
|---|---|
| (active - editing changes what you feel now) | You are editing the preset that is playing. |
| (loaded - editing changes what you feel now) | The haptics aren't running; this preset will be used. |
| (editing; *&lt;preset&gt;* is active) | You are looking at a different preset from the one playing. Changes are saved but you won't feel them until that game is detected. |

Good to know:
- **While the haptics are running**, picking a preset only opens it for editing. **While they are stopped**, picking a preset makes it the active one.
- Turning the mouse wheel over the list also changes the preset.
- If a game is detected while you are typing a strength, the window switches preset, your unfinished number is dropped, and the message adds "The number you were typing was not applied."
- On a brand-new install nothing has been detected yet, so **Forza Motorsport** is used.
- Horizon 5 and 6 share one profile file, so after a restart the window opens on **Forza Horizon 5** until Horizon 6 is detected again.

## Saving

- Strengths and Master save themselves about 0.8 s after you stop changing them. The device, Advanced
  settings and the Haptics on switch save immediately, and Quit also saves.
- A tick box is only saved when it differs from the preset's own setting, so a later calibration update
  still reaches you.
- You edit the preset **shown in the picker**. If that is not the game playing right now, you feel the
  change only once that game is detected.

## Going back to the calibrated levels

**Reset preset to calibrated**, at the bottom of the window, puts every effect of the preset **on screen**
back to 100 % and to the preset's own on/off setting. The message reads "*&lt;preset&gt;*: back to 100% (the
shipped level)." Master and your other presets are not changed.

## Strengths and Master

Each preset keeps a strength from 0 to 200 % for every effect; **Master** (0-100 %) is one level for all presets. What a strength does to the sound is explained in [What the strength slider does](Effects-Overview.md#what-the-strength-slider-does).

---

**Next:** [Advanced settings](Advanced-Settings.md)

**See also:** [The Effects rows](The-Main-Window.md#effects) · [Effects overview](Effects-Overview.md)
