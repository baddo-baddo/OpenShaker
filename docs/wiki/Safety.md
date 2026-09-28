# Safety

[OpenShaker guide](README.md) › Your hardware

How to set the level safely, how loud each game plays, and what protects your shaker and amplifier.

## Setting the level

- **Turn the amplifier down before the first run.** Pick your shaker under **Device**, press **Test tone**, and raise the amp until the sweep feels firm but never clatters.
- **Test tone is about as strong as the hardest hits.** It ignores Master, so it is a fixed reference for setting the amp.
- **Set the amp with the loudest game you play.** Normal Forza driving is much quieter than the test tone. BeamNG plays close to that level most of the time, like HaptiConnect's BeamNG preset.
- **Back off if it clatters, buzzes or distorts.** That can damage the shaker, the amp or the seat mount.
- **Think of your neighbours.** Low frequencies travel through floors and walls.
- **Pick the shaker by name** rather than "(Windows default output)", so a missing shaker never turns into shaking speakers.

## How loud each game plays

- **Each game plays at the level HaptiConnect uses for that game.** BeamNG.drive, like HaptiConnect's BeamNG preset, is **much stronger** than the Forza games. Its engine tone alone is about 15 dB louder than Forza Motorsport's.
- The Trackmania levels are first guesses, set on the same scale as the calibrated Forza presets.
- At full Master, BeamNG's collision hits are loud enough to make the limiter (below) turn the whole mix down on every crash.

## What protects the output

- A limiter holds peaks just below full scale (-0.13 dBFS). It never distorts the sound. Instead, a loud burst **turns the whole mix down**, which then recovers within about a second.
- Once the Level meter sits near 0 dB, raising Master or strengths makes the rest of the mix duck harder, not the peaks louder. Lower the loudest effect instead.
- A corrupted value in the telemetry is caught before it can reach the shaker as a full-scale pop.
- If one effect fails, only that effect goes silent.
- Volume changes glide smoothly, so there are no clicks.
- Demo is capped well below full level.

How the limiter works is explained in [How the effects are mixed and kept safe](Effects-Overview.md#how-the-effects-are-mixed-and-kept-safe).

---

**Next:** [Troubleshooting](Troubleshooting.md)

**See also:** [Shakers, amplifiers and channels](Shakers-Amplifiers-and-Channels.md) · [First run](Installing-OpenShaker.md#first-run)
