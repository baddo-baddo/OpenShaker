# Shakers, amplifiers and channels

[OpenShaker guide](README.md) › Your hardware

Which outputs and shakers work, choosing the output channel, running two shakers, and how OpenShaker finds your shaker again after a re-plug.

## Which outputs work

- Any Windows sound output that feeds a shaker amplifier: line or headphone out, USB, optical or HDMI.
- The tested setup is a ButtKicker PRO (it shows up as "Speakers (ButtKicker PRO)").
- These should work but are untested: other ButtKicker models through their amps (Gamer Plus, Gamer PRO, LFE, Advance), Dayton BST-1 and TT25, and AuraSound AST-2B-4.

## Shared mode

- OpenShaker plays in Windows' shared mode, so other apps can still use the same output. It never takes the device exclusively.
- If another program has taken the shaker exclusively, OpenShaker can't start until it lets go.
- Right after being plugged in, a shaker may briefly appear only in an exclusive mode. OpenShaker then says it "is probably still waking up" and picks it up on the next retry.
- Check the Windows volume for the shaker's output too.

## Output channel

Under Advanced > Output channel:

- **Left** is the default, as in HaptiConnect.
- If your shaker is wired to one side of a stereo amp, pick that side.
- If your shaker mixes both channels (like the ButtKicker PRO), **Both** may feel stronger.
- OpenShaker opens every channel the output has and sends the signal only to the ones you picked; the rest get silence. This stops Windows spreading a one-channel signal to both sides, which can make a summing shaker up to 6 dB louder than intended.
- If you pick a channel the device doesn't have, it falls back to Left.
- Use **Test tone** to check the channel choice.

## Frequency range

shakers respond best between about 20 and 90 Hz, and most effects sit there. The engine hum and gear-shift kick follow the revs, so they go lower near idle, and the engine hum goes above 100 Hz at high revs in the Forza, ACE and BeamNG presets.

## Running two shakers

- Choose **Both** under Advanced > Output channel. Both shakers then get the **same** signal.
- OpenShaker makes one signal, so there is no front/rear or left/right split of effects.
- OpenShaker drives **one output device** at a time, so connect both shakers to one stereo output and amplifier.
- Balance them with the amplifier's channel levels.

## Finding the shaker again after a re-plug

Windows sometimes renames a device after re-plugging, for example "Speakers (ButtKicker PRO)" becomes "Speakers (2- ButtKicker PRO)". OpenShaker ignores that number, and differences in capital letters and spacing.

Picking the device itself is described under [Output](The-Main-Window.md#output-level-master-and-device) on The main window.

---

**Next:** [Safety](Safety.md)

**See also:** [Advanced settings](Advanced-Settings.md)
