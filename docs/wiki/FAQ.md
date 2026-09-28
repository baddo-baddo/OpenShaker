# FAQ

[OpenShaker guide](README.md) › Help

Short answers to the questions people ask most.

**Why is "ABS pulse" ticked, but I never feel it?**
With the 1.0.0 presets, no real game triggers it. Forza doesn't send ABS data. Assetto Corsa EVO's ABS is silenced by choice (see [Assetto Corsa EVO](Assetto-Corsa-EVO.md#effects-in-assetto-corsa-evo)). BeamNG's is silenced to match HaptiConnect's BeamNG preset, which has no ABS effect. Trackmania has no ABS. Only Demo plays it, with a Forza preset active.

**Why do kerbs do nothing in Forza Horizon?**
Horizon never reports rumble strips. You feel rough ground and kerbs through the suspension rumble instead.

**Why does a strength slider do nothing?**
Either the preset ships that effect at zero strength (Silenced), or the game doesn't send its data (No data). See [Effect support by game](Effects-Overview.md#effect-support-by-game). You can't bring a silenced effect back from the window, because its strength is a percentage of zero.

**Why does everything go quiet for a moment after a big crash?**
That is the output limiter protecting the shaker. Instead of clipping, a very loud hit turns the whole mix down briefly, and the mix comes back within about a second. At full Master, every BeamNG crash does this.

**Can I get Surface feel, Landings or Boost in other games?**
No. Only Trackmania reports surfaces, airtime and boosts.

**Can I use the Grip limit warning outside Trackmania?**
Yes: tick it in that game's preset. It then warns as the tyres' slip nears the limit and goes quiet when they let go. In BeamNG it only sees wheelspin and lock. In Assetto Corsa and ACC (the older games) it has no data.

**OpenShaker picked the wrong Forza Horizon preset.**
OpenShaker tells Horizon 5 and 6 apart by the program running on this PC. If the game runs on an Xbox or another PC, OpenShaker keeps the Horizon preset that was active, or uses Horizon 5. Both presets play the same tuning; only your own strengths differ.

**How is OpenShaker different from SimHub?**
[SimHub](https://www.simhubdash.com/) can drive bass shakers too, with its ShakeIt module, for the other games OpenShaker supports, and it does much more: dashboards, motion rigs, wind and LEDs. OpenShaker does one thing: it feels like HaptiConnect straight away, with presets tuned against HaptiConnect's own output, so there is nothing to set up. It also supports Trackmania (2020), which [SimHub's list of supported games](https://www.simhubdash.com/supported-games/) doesn't include (it lists Trackmania 2 and Trackmania Turbo; checked in September 2026). If SimHub already works for you, keep using it.

**Will it work with my shaker?**
Probably: to Windows a bass shaker is just a sound output, so any shaker your PC can play sound to should work, although only the ButtKicker PRO has been tested. Pick it by name, check the channel, and set your amplifier with Test tone; see [Shakers, amplifiers and channels](Shakers-Amplifiers-and-Channels.md).

**Does OpenShaker phone home?**
Only to ask GitHub, once a day, whether a newer version exists. That request carries nothing but the app's name and version; your game data, settings and hardware are never sent anywhere. Nothing is downloaded until you click **Update now**, unless you switched on [automatic updates](Start-With-Windows-Updates-and-Uninstalling.md#automatic-updates). Switch the check off under **Advanced... > Check for updates** and OpenShaker never contacts the internet. See [Updating](Start-With-Windows-Updates-and-Uninstalling.md#updating).

**Something is missing or not working.**
[Troubleshooting](Troubleshooting.md) lists symptoms and messages with their cause and fix, for example
Forza Motorsport without gear shifts (the Sled format) or BeamNG without crashes (Motion Sim not ticked).

---

**Next:** [Glossary](Glossary.md)

**See also:** [Troubleshooting](Troubleshooting.md) · [Effects overview](Effects-Overview.md)
