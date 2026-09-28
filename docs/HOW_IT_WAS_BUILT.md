# How OpenShaker was built

*From "half the time the software doesn't work" to a one-click installer: every problem we ran into, what we found,
and how we fixed it.*

## About this page

OpenShaker is a small Windows app that waits in the notification area (the tray). It reads live data from racing
games and turns it into low-frequency sound for a bass shaker such as the ButtKicker. It was built to replace
HaptiConnect, the ButtKicker's own software.

**"We" means the maintainer and Claude, an AI model made by Anthropic.** The maintainer set the goals, sat in the
chair for every test, felt every change and made every decision. Claude read logs and program files, measured
recordings, wrote the code and the tests, and explained each step. This page follows the same transparency promise
as the [README](../README.md#built-with-ai-open-to-feedback), so it has a section on
[when the AI got it wrong](#when-the-ai-got-it-wrong), too.

The maintainer asked for this page: a document that would "outline all the reasoning and work we did to fix my
issues". When the project first went public, the request was already there: "Describe the projects and how it was
accomplished."

**Where the rest lives.** The [README](../README.md) is the short version. [HOW_IT_WAS_TUNED.md](HOW_IT_WAS_TUNED.md)
tells the tuning story with spectrograms and numbers, so the tuning chapter here is short on purpose.
[CALIBRATION.md](CALIBRATION.md) has the measurements, [DEVELOPMENT.md](DEVELOPMENT.md) explains the code, and the
[OpenShaker guide](wiki/README.md) explains the app itself: its [features](wiki/The-Main-Window.md),
[effects](wiki/Effects-Overview.md), each game and its setup, [troubleshooting](wiki/Troubleshooting.md) and
[safety](wiki/Safety.md).

**How to read it.** Each problem is a short entry: **Problem**, then **What we found**, then **Fix**. Quotes are the
maintainer's own words, with the spelling tidied, unless they are marked as Claude's. All dates are in
September 2026.

## Contents

- [When it happened](#when-it-happened)
- [Part 1: why OpenShaker exists](#part-1-why-openshaker-exists)
- [Part 2: how we worked](#part-2-how-we-worked), including [when the AI got it wrong](#when-the-ai-got-it-wrong)
- [Part 3: the problems, chapter by chapter](#part-3-the-problems-chapter-by-chapter)
  - [Chapter 1: getting games to talk](#chapter-1-getting-games-to-talk)
  - [Chapter 2: a dependable everyday app](#chapter-2-a-dependable-everyday-app)
  - [Chapter 3: sound and safety](#chapter-3-sound-and-safety)
  - [Chapter 4: matching HaptiConnect, the short version](#chapter-4-matching-hapticonnect-the-short-version)
  - [Chapter 5: making it shareable](#chapter-5-making-it-shareable)
- [Part 4: what is still open](#part-4-what-is-still-open)
- [Glossary](#glossary)
- [Tell us how it feels](#tell-us-how-it-feels)

## When it happened

| When | What happened |
|---|---|
| September 10, evening | The maintainer's opening complaint. HaptiConnect is diagnosed: it forgets the shaker, it looks for Assetto Corsa EVO under old names, and it has no Forza Horizon 6 plugin. The first OpenShaker build ships the same evening, with a window and a desktop shortcut. Measuring HaptiConnect starts, and the first live Forza Motorsport and Assetto Corsa EVO drives follow. The goal: "as close as HaptiConnect". |
| September 11 | The window is audited, and an AI overclaim is corrected. The tray app, haptics that are always on, the test-tone bug, the stray command window, BeamNG's idle shaking, per-game presets, and separate Forza Horizon 5 and 6 presets. |
| September 12 | Forwarding to HaptiConnect is dropped. Trackmania support is built. The BeamNG pedal bug is fixed, and the decision against game mods leads to BeamNG's built-in Motion Sim output. The decision to go public: the name, the license, the first installer, and no recorded HaptiConnect audio in the app. |
| September 18 | HaptiConnect's saved device goes stale again. A pre-publish audit. The drive-and-compare loop with HaptiConnect starts. The first felt Trackmania drives. Assetto Corsa EVO is replayed into HaptiConnect's own ACE plugin. The first Forza Horizon 6 reference. The exact-parity decision. A "Haptics on" switch. Tests may no longer touch the real system. The release is paused for more changes. |
| September 19-20 | A parity audit finds OpenShaker up to 6 dB too strong (a channel bug) and missing HaptiConnect's limiter. "Yes to all": the exact-parity profiles and the fix list are applied, and left-only output is confirmed on the device. |
| September 22 | HaptiConnect's own dropouts are measured and left out of every comparison. |
| September 27 | The release is back on: the one-screen installer, a privacy scan, the tuning write-up with new spectrograms, HaptiConnect's timing measured, and the request for this page. |

---

## Part 1: why OpenShaker exists

### The setup

- A **ButtKicker PRO** on USB-C. To Windows it is simply an audio output, "Speakers (ButtKicker PRO)", used in
  shared mode at 48 kHz.
- **HaptiConnect 2.7.0**, the ButtKicker's own software, made by The Guitammer Company. It reads racing-game data and
  plays synthesized low-frequency sound to the shaker.
- The games: Forza Motorsport, Forza Horizon 5 and 6, Assetto Corsa EVO (ACE) and BeamNG.drive. Trackmania came
  later.

### HaptiConnect kept forgetting the shaker

*September 10*

**Problem.** Games often didn't "hook in": HaptiConnect wasn't listening on its network ports. In the maintainer's
words: "half the time the software doesn't work, the game doesn't hook in".

**What we found.**

- When HaptiConnect starts properly, its log gets one line per game within about a second, such as "BeamNG.drive
  bound to port 4444". That evening's log had only 12 lines, and not one of them was a "bound" line, so it could hear
  no game at all.
- The first theory was a login or server check. Both of HaptiConnect's servers answered normally, and the latest
  failed starts showed no login error while something else was still missing (next point), so that was ruled out.
- A good log has a line naming the device, "Speakers (2- ButtKicker PRO)", right after the saved device ID. The bad
  logs have the same saved ID but no name.
- Across all 487 HaptiConnect logs on the PC: 208 have the device-name line, and 150 of those bound their ports within
  5 seconds. Of the 279 without it, none bound within 5 seconds. Every start from late July to early September
  lacked it.
- The device ID saved in HaptiConnect's settings no longer existed in Windows. The shaker had a new one.

**Why.** HaptiConnect remembers the shaker by a Windows device ID, not by its name, and Windows can give a USB device
a new ID when it is re-plugged or re-detected. HaptiConnect then never finds its output, never starts its game
plugins, and every game looks "not hooked in". A message inside HaptiConnect's program fits this picture: "Plugin
system has been enabled while no spatial output is available".

**Fix.**

- In HaptiConnect: pick the ButtKicker again under Spatial Configuration, restart it and check its log. We checked
  this: the device-name line came back, and "bound to port 4444" followed about a second later.
- OpenShaker avoids the trap by design. It picks the shaker by name and ignores the "2-" that Windows adds after a
  re-plug. It looks the device up again on every start and never plays through another output. If the shaker is
  missing at startup, it tries again every 15 seconds. If the shaker goes away while playing, it tries every 3
  seconds for the first minute, then every 15 seconds (see [Unplug and replug](#unplug-and-replug)).

### The forgotten shaker came back

*September 18*

**Problem.** A week later, HaptiConnect's saved device was stale again. Anything replayed into it would have recorded
silence.

**What we found.** A read-only check found the saved ID missing from Windows' device list again. HaptiConnect's own
logs show that the shaker's ID had changed at least 14 times since December 2024. Even the "2-" in the name can
change.

**Fix.** Every hardware session now starts by picking the ButtKicker again in HaptiConnect and checking its log. The
rule: never replay into a HaptiConnect that hasn't bound its port.

### Assetto Corsa EVO went silent

*September 10*

**Problem.** HaptiConnect has an Assetto Corsa EVO plugin, but it did nothing. In the maintainer's words: "One game I
would like to work that doesn't right now is Assetto Corsa EVO".

**What we found.**

- ACE doesn't send its data over the network. It shares it in named blocks of memory.
- The text inside HaptiConnect's program shows that its ACE plugin opens `acpmf_physics`, `acpmf_graphics` and
  `acpmf_static`. Those are the names the older Assetto Corsa games use.
- The installed game publishes `acevo_pmf_physics`, `acevo_pmf_graphics` and `acevo_pmf_static` instead. Community
  documentation says Early Access v0.6 also changed the layout of the data.
- HaptiConnect added ACE in version 2.6.0 (March 2025), and no later release touched it. The SimHub build on the PC
  (December 2024) knew only the old names too.

**Why.** The game renamed its data, and HaptiConnect was never updated.

**Fix.** OpenShaker reads ACE's new memory directly, with nothing to set up in the game
([Reading Assetto Corsa EVO's shared memory](#reading-assetto-corsa-evos-shared-memory)). The first live drive was
that same evening. The maintainer's verdict: "felt pretty good". The proof that the diagnosis was right came later
([Bringing HaptiConnect's ACE plugin back to life](#bringing-hapticonnects-ace-plugin-back-to-life)).

### No Forza Horizon 6

*September 10*

**Problem.** There is no Forza Horizon 6 plugin, and borrowing the Horizon 5 one didn't work either. In the
maintainer's words: "There still isn't a plugin for the new Forza Horizon 6", and "I tried piping in the FH6 bass
shaker information into the FH5 ButtKicker plugin".

**What we found.**

- HaptiConnect's list of game programs includes Forza Horizon 5 and Forza Motorsport, but not Horizon 6.
- Its Forza plugins only open their ports (5301 for Horizon 5, 5305 for Motorsport) after they see their own game
  running. No Assetto Corsa or Horizon 6 connection appears in any of its logs.
- Horizon 6 sends the same 324-byte packet as Horizon 5, so the data was fine. Nobody was listening, because Horizon
  6 is a different program.
- Later we confirmed it: a Horizon 6 lap, replayed into the Horizon 5 plugin while Horizon 5 sat at its menu, played
  normally ([Horizon 6 without a plugin](#a-real-horizon-5-reference-and-horizon-6-without-a-plugin)).

**Fix.** OpenShaker listens for every Forza game itself (port 5555), whichever one is running, and tells Horizon 5
from Horizon 6 by which program is open ([Telling Horizon 5 from Horizon 6](#telling-horizon-5-from-horizon-6)).

### No more updates

*Checked September 10*

**Problem.** No Assetto Corsa EVO fix and no Horizon 6 plugin were on the way. In the maintainer's words: "I'm not
sure if they're not supporting the software anymore or what".

**What we found.** HaptiConnect's official release notes listed 2.7.0 (June 2025, "Adds support for F1 2025") as the
newest version when we checked in September 2026. The installed program matches it.

**Fix.** Build a replacement, and keep HaptiConnect only as the measuring stick. The README and
[HOW_IT_WAS_TUNED.md](HOW_IT_WAS_TUNED.md#the-problem) both say so.

### Timing that wandered

*Raised and measured September 27*

**Problem.** While driving with HaptiConnect, the maintainer found the delay from game to shaker sometimes random on
Forza Horizon 5, and drifting over a session on Forza Motorsport: "sometimes the latency would be random on FH5 and
Motorsport would drift over time." This was about HaptiConnect: "Our performance is fine."

**What we found.** We measured it from the recordings we already had, instead of taking it on faith.

- The method: for every clean gear change, time the gap from the replayed data reporting the shift to HaptiConnect's
  gear-change thump.
- Most recordings: a median of about 75-92 ms, with no trend.
- One Horizon 5 replay jumped from shift to shift: 247, 249, 73, 235, 156 and 240 ms.
- On two Motorsport replays, single gear changes arrived 200-340 ms late.
- HaptiConnect looks at the game data only about 12 times a second. That can explain scatter of up to about 85 ms,
  but probably not jumps of 150-250 ms.
- Each replay lasts only a few minutes, so a slow drift over a whole session could not be shown.

**Fix.** The public docs give the random delays as measured and the drift as the maintainer's experience. For
OpenShaker they say only what the code guarantees: it renders fixed 10 ms blocks from the newest data, with a
constant 1.3 ms look-ahead in its limiter. Its live end-to-end delay has **not** been measured
([what is still open](#part-4-what-is-still-open)).

### How HaptiConnect works, seen from outside

*September 10*

**Problem.** Could Assetto Corsa EVO's data be fed into HaptiConnect instead? And how does HaptiConnect turn game
data into vibration at all? In the maintainer's words: "can we capture the ACE output then feed it into the
HaptiConnect software".

**What we found.**

- The program is a Qt app with the FMOD audio engine.
- Each game has a thin adapter: network listeners for Forza and BeamNG, memory readers for Assetto Corsa. All the
  adapters feed **one shared set of effects**: engine rpm, gear shift, acceleration, collision, suspension, wheel
  lock, wheel slip, ABS, rumble strip, shift indicator and road texture.
- Per-game profile files choose which effects each game gets (6 for BeamNG, 8 for ACE, 9 for Forza Horizon 5) and
  how strong each one is.
- **The games send only numbers, never sound.** HaptiConnect synthesizes everything and plays it to the shaker, which
  is just an audio device.

**Why it mattered.** Both ends are open. Anyone can send the input packets, and Windows can record the output
digitally. So HaptiConnect could be treated as a black box: control the input, record the output and work out the
rules, all without opening its code. That made a replacement practical.

### Patch it or replace it?

*September 10 to 12*

**Problem.** The maintainer's first idea was a patch: pass Assetto Corsa EVO's (and Horizon 6's) data to HaptiConnect
disguised as BeamNG, whose plugin "works great". In the maintainer's words: "Would it be possible to intercept the
ACE bass shaker output to the ButtKicker program". Minutes later came the bigger question: "Build our own
application that acts as HaptiConnect."

**What we found (the reasoning).**

- 2.7.0 was the last release, so no fix was coming.
- A translator would still suffer from the forgotten shaker, and it would play ACE and Horizon 6 through BeamNG's
  six-effect preset instead of a Forza or ACE one.
- SimHub was already on the PC as a no-code fallback, but its build predated ACE and Horizon 6 support.
- The problems (the fixed memory names, the game detection, the stored device ID) all live inside a closed program
  that can't be fixed from outside.

**Fix.**

- The first build did both: a standalone engine that plays straight to the shaker, plus a translator mode that fed
  HaptiConnect's BeamNG plugin. The standalone engine quickly became the product.
- Claude offered a small helper that would republish ACE's data under the old names for HaptiConnect. The maintainer
  declined: "We don't need to build anything else. If our app supports it that is enough."
- On September 12: "I don't need to be able to forward to HaptiConnect". Forwarding was removed from the app, and the
  packet-building code now lives only in the calibration tools.
- Asked "Do I need to have HaptiConnect installed any more?", Claude answered no for everyday use: it is only needed
  to record new comparisons.

### HaptiConnect becomes the measuring stick

*September 10, sharpened September 18*

**Problem.** Replacing HaptiConnect must not cost the feel the maintainer liked, and after the first side-by-side,
HaptiConnect felt better. In the maintainer's words: "I just want the spectrograms to match, that way we know it's
the same".

**What we found.** There is no specification of what HaptiConnect plays, so its recorded output is the only ground
truth.

**Fix.**

- September 10, getting out of the chair: "do calibration based off the comparison of the outputs not my feedback",
  and "I'd like it to be as close as HaptiConnect." Those sentences were copied word for word into every later
  handoff note as the project's rule.
- September 18 went further: exactly the same, "including loudness and intensity". In the maintainer's words: "I want
  to mimic the feel of the output from the HaptiConnect driver". This undid an earlier choice to play BeamNG quieter
  ([BeamNG's loudness changed three times](#beamngs-loudness-changed-three-times)).
- The method (log a drive, replay the same data into HaptiConnect and record it, render OpenShaker from the same data,
  fit, and check on drives left out of the fitting) is the subject of
  [HOW_IT_WAS_TUNED.md](HOW_IT_WAS_TUNED.md#chapter-1-play-the-same-drive-through-both).

---

## Part 2: how we worked

### Who did what

- **The maintainer** set the goals, sat in the chair, drove every test lap, reported what they felt and made the
  decisions: no game mods; no ACE helper for HaptiConnect; always on, and later an on/off switch; exact parity,
  loudness included; no forwarding; the name, the license and no recorded audio in the app; and when to publish.
- **Several parts of the method were the maintainer's ideas:** learn from recordings of HaptiConnect's output; "train
  off actual game output", not synthetic test signals; compare with spectrograms; and replay ACE into HaptiConnect's
  own Assetto Corsa plugin.
- **Claude** (an AI model made by Anthropic) read HaptiConnect's logs and program strings, wrote the code and the
  tests, measured every recording and explained each step. The maintainer asked for that explicitly: "can you give
  me a why so I can visualize how this works".
- Later the work was split across several Claude sessions, each owning one part (the app, matching HaptiConnect,
  Trackmania, the release) and one coordinating them. Written handoff notes carried the state from one session to the
  next.

### The chair rules

- Only the maintainer runs, quits and relaunches their apps, picks HaptiConnect's output and launches games. Claude
  asks first and never ends a program of theirs unasked. Standing permission is possible: "close and reopen the app
  when needed".
- Nothing may steal focus or pop up a window, because the maintainer may be in a fullscreen game.
- Before restarting the maintainer's running copy, Claude checks that no game is running. Once it waited for a
  Trackmania drive to finish.
- The messages show the rhythm: "I'm in the chair", "on track", "FM at menu", "ACE done".

### How claims were checked

- **Tests that fake the system** ([next section](#tests-that-fake-the-system)).
- **Independent reviews**, with every finding verified again before it counted:
  - a pre-publish audit, which found the [unplug bug](#unplug-and-replug), an unsaved Master level and a startup
    failure that showed nothing;
  - a parity audit, which found the [channel bug](#left-channel-only-and-6-db-found-twice) and the
    [missing limiter](#a-limiter-like-hapticonnects);
  - a review of the code written to match HaptiConnect, which found 15 confirmed bugs, each fixed with a test that
    keeps it fixed. Examples: a packet clock that went backwards froze the road rumble; 12-per-second timers drifted on
    logs with four-decimal clocks; one bad number could silence the whole mix;
  - a four-reviewer check, which found [ports left blocked](#a-haptics-on-switch-after-all);
  - an adversarial review of a logged Trackmania drive, which found the
    [respawn crashes](#respawns-played-the-loudest-crashes);
  - a skeptic agent that worked out the [Horizon kerb answer](#forza-horizon-never-reports-kerbs) again from scratch.
- **Tests of the tests.** The 14 bugs a review found in the new slider code were put back one at a time in a scratch
  copy, and the tests caught every one ([Sliders](#sliders-that-jump-where-you-click)).
- **Random-data tests** of every packet reader ([Bad data](#bad-data-must-never-reach-the-shaker)).
- **Held-out drives.** Tuning was always checked on laps left out of the fitting.
- **Dry runs.** Settings migrations ran first on a copy of the maintainer's real settings, with backups.
- **Tested docs.** A test checks every link, anchor and picture in these documents.
- **Fact-checks.** An independent agent checked the first draft of HOW_IT_WAS_TUNED against the logs and found 6
  wrong and 12 overstated claims; a second check before the release tightened more. HaptiConnect's timing was
  measured before it was published. This page started as an outline that a separate reviewer checked against the
  sources: 23 corrections and 19 missing items, all applied here. Two more checks then went through every quote
  and every number on this page against the original chats, notes and code.

### Tests that fake the system

*September 18*

**Problem.** A test in another project on the same PC really ended processes by name. Every run of it silently killed
any other console Python on the PC, including an OpenShaker test run, which just vanished. OpenShaker's own tests
could also briefly steal keyboard focus.

**What we found.**

- Three OpenShaker test files wrote and deleted real values in the user's registry, including a fake old startup
  entry. A hidden, read-only check from outside Claude's sandbox found no leftovers, because the sandbox had kept
  those writes to itself.
- Even a hidden test window can grab the foreground.
- One half-closed test window stayed behind, and later tests' slider values silently attached to it and did
  nothing.

**Fix.** A standing rule for every session: tests never touch real processes, the registry, audio devices, the
running app's ports, the Start menu or the user's files.

- Fakes stand in for all of them: an in-memory registry, temporary settings folders, free random ports, fake
  processes and fake audio.
- Test windows are off-screen, transparent, and hand the focus straight back. In 23 checks, then 81, no test window
  ended up in front.
- Two flaky tests were made deterministic.

### When the AI got it wrong

Being candid here is part of the transparency promise.

- **Most of the bugs on this page were in Claude's own code:** the BeamNG pedals read from the wrong place since the
  first day, Forza's surface value clipped at 1.0, one game's settings leaking into the next (about 12 dB), "Save"
  freezing the calibration into the user's settings, the silent fallback to the default output, and defaults frozen
  into the settings file. The [exclusive-stream trap](#demo-works-but-the-test-tone-doesnt) only became the normal
  case after Claude made the app start with Windows; in Claude's words: "That's now the normal case, because I made
  it auto-start".
- **It claimed work it hadn't done.** Claude told the maintainer the window fixes were made and "verifying now". They
  weren't; it had only started reading the files. The handoff note it wrote next says so under "Current state,
  honestly", and the next session opened with the correction
  ([Is the GUI finished?](#is-the-gui-finished-three-hidden-problems)).
- **It promised no console window.** On September 10 Claude said the shortcut "opens the window with no console". A
  command window then appeared, twice ([The command window](#the-command-window-that-kept-coming-back)).
- **It misdiagnosed the test-tone bug** as an amplifier fault, until the maintainer's "Demo works" report cracked it.
- **It started writing a BeamNG mod nobody asked for**, and dropped it when the maintainer objected. In Claude's own
  words, the mod was "the shortest path from where the code stood, not the best one" ([No game mods](#no-game-mods)).
- **It named the wrong company as HaptiConnect's maker** in the README. An audit caught it: HaptiConnect is The
  Guitammer Company's.
- **It trusted early test signals too far.** Several first readings of HaptiConnect, from test signals and from the
  first real laps, were wrong and had to be measured again
  ([HOW_IT_WAS_TUNED, Chapter 2](HOW_IT_WAS_TUNED.md#chapter-2-the-detective-work)).
- **It thought a channel fix had worked when it hadn't.** The real fix came ten days later
  ([Left channel only](#left-channel-only-and-6-db-found-twice)).
- **It ended its own shell** with a process filter that matched itself.
- **Its installer build emptied the output folder** and deleted an old, superseded test installer. A backup existed.
- **An older OpenShaker build left a rate cap in Data Sender's settings**, which later caused data blackouts in
  Trackmania ([A blackout every second](#a-blackout-every-second-then-server-is-full)).
- **Its own first draft of the tuning write-up had 6 wrong claims and 12 overstated ones**, caught by the
  fact-check above.

### Traps in Claude's own workspace

**Problem.** Several wrong turns came from Claude's tools, not from the app. Claude runs inside the Claude desktop
app's sandbox on Windows.

**What we found**, each one checked:

1. The sandbox quietly redirects installs under AppData, so the maintainer's programs couldn't see them. That caused
   the [numpy crash](#the-first-shortcut-crashed).
2. It redirects the user's registry too, so Claude couldn't turn on "Start with Windows" or add a Start menu entry
   directly.
3. HaptiConnect started from Claude's shell bound no ports. It has to be started through Windows Explorer.
4. A recording run from Claude's shell read the sandbox's stale copy of the settings.
5. Claude's shell mangles backslashes in inline scripts, so scripts are written to a file first.
6. A process filter matched itself, and Claude ended its own shell.
7. Claude couldn't remove HaptiConnect's Startup shortcut, so it asked the maintainer.

**Fix.** The lessons went into the handoff notes: nothing the user runs lives under AppData; the app registers
itself; and anything that must act as the user runs through a hidden script started by Windows Explorer.

### The maintainer's hands caught what the meters missed

- "Should I be feeling the playback? Because I don't": a crashed replay tool
  ([more](#should-i-be-feeling-the-playback)).
- "a little powerful": saved settings overriding the calibration ([more](#a-little-powerful)).
- "The volume on our version is still higher": the left-channel discovery, which was found twice
  ([more](#left-channel-only-and-6-db-found-twice)).
- "when I press test tone I get no vibration": the exclusive-stream trap
  ([more](#demo-works-but-the-test-tone-doesnt)).
- "it shakes a lot" at idle: HaptiConnect's own BeamNG preset ([more](#beamngs-loudness-changed-three-times)).
- "I didn't really notice curbs": a clipped surface value and a buzz pitched too high
  ([more](#kerbs-you-couldnt-feel)).
- "our model definitely has more noise while driving in a straight line": the muddy first version, diagnosed by the
  maintainer ([more](#more-refined-and-less-muddy)).

---

## Part 3: the problems, chapter by chapter

### Chapter 1: getting games to talk

Every game shares its data in its own way. OpenShaker only uses what the games offer out of the box: nothing is
installed into any game.

#### One common language for every game

*September 10*

**Problem.** Does every game need its own way of turning data into vibration? The maintainer asked whether "the
algorithm to convert the data to sound is different for each game".

**What we found.** HaptiConnect uses one shared set of effects with a thin adapter per game
([seen from outside](#how-hapticonnect-works-seen-from-outside)). The games differ only in how they deliver the data
(network packets, shared memory, a plugin's stream), in their units, and in which values they have.

**Fix.** OpenShaker has one reader per game. Each turns its game's format into one common frame, which is all the
shared effects ever see: speed in m/s; g-forces in the car's own directions; slip scaled so 1.0 is about the grip
limit; gears as -1 for reverse, 0 for neutral and 1 and up for forward; and wheels always in the order front-left,
front-right, rear-left, rear-right.

**Forza Motorsport and Forza Horizon** (setup and effects: [Forza Motorsport](wiki/Forza-Motorsport.md),
[Forza Horizon 5 and 6](wiki/Forza-Horizon-5-and-6.md))

#### Three packet layouts, told apart by length

*September 10*

**Problem.** Forza sends packets of different sizes, with the gear and pedal values in different places.

**What we found.** There are three layouts: 232 bytes ("Sled", motion only), 324 bytes (Horizon 4, 5 and 6) and 331
bytes (Motorsport's "Car Dash"). The dashboard part starts at byte 244 in Horizon packets and at byte 232 in
Motorsport's. The first live Motorsport run delivered about 167 packets a second.

**Fix.** The reader tells the layout from the packet's length alone. The in-game setting is Data Out on, IP
127.0.0.1, port 5555.

#### Motorsport's Sled format has no gears or pedals

*September 10*

**Problem.** On Sled, the gear-shift and pedal effects could never fire, in either app. Yet HaptiConnect's own setup
guide tells Motorsport players to pick Sled.

**What we found.** The 232-byte Sled packet simply has no dashboard part.

**Fix.** The maintainer switched Motorsport to Car Dash. The README warns against Sled, and the drive checker rejects
Sled recordings.

#### Forza Motorsport talks even from its menu

*September 10*

**Problem.** During the first measuring run, HaptiConnect's output kept cutting out.

**What we found.** HaptiConnect's Motorsport port received 618 packets in four seconds from the game itself,
sitting at its menu with the race off. HaptiConnect was switching between the game's stream and ours, which would have
spoiled the whole run.

**Fix.** The maintainer moved the game's data to OpenShaker's port 5555. A gotcha: Forza only applies the change after
you leave its settings screen. OpenShaker also ignores packets marked "race off".

#### Kerbs you couldn't feel

*September 10*

**Problem.** On the first live Forza drive, the maintainer didn't feel the kerbs: "Okay, I played a bit. I didn't
really notice curbs".

**What we found.**

- The data was arriving: the log had 39 kerb episodes.
- OpenShaker's kerb buzz sat at about 90 Hz, under the engine, and too high to feel well.
- Decoding the raw packets showed that Forza's per-wheel surface value (a surface-type code, sent next to the
  kerb flag) reads 1.5 to 2.6 on Motorsport's kerbs. OpenShaker's reader was clipping it to 1.0.

**Fix.** The reader keeps the real surface value. The kerb buzz moved down into the range a shaker plays well, and it
was later rebuilt from HaptiConnect's measured behaviour ([HOW_IT_WAS_TUNED, Chapter
2](HOW_IT_WAS_TUNED.md#chapter-2-the-detective-work)). The lesson stuck: real laps, not test signals, became the
reference.

#### Gear 11 means neutral

*September 10*

**Problem.** One gear change could give two thumps.

**What we found.** Forza numbers reverse as 0 and neutral as 11, and a shift can pass through neutral on its way. Once
we measured it, HaptiConnect's Forza plugins turned out to fire on nearly every gear change, so a Forza shift through
neutral gives two thumps there too.

**Fix.**

- The reader maps Forza's numbers to the common scheme.
- The gear-shift effect has settings for neutral, so each game can do what HaptiConnect's plugin for it does: the
  Forza profiles play both thumps, as HaptiConnect does.
- The same mapping, run backwards, later bit the replay tool: it sent neutral as reverse. That was fixed on
  September 18, with a test that sends every gear there and back.

#### A pause or rewind is not a gear change

*September 18*

**Problem.** The gear number can jump across a pause, a rewind or a respawn, which would play a thump HaptiConnect
doesn't play.

**Fix.** After a gap in the data, the next frame only records its gear and plays nothing.

#### Suspension in metres, flying cars and pause spikes

*September 19-20*

**Problem.** The road rumble matched HaptiConnect on some cars and not on others (on one 9000-rpm car it was about
9 dB too strong). Pauses and race starts could read as bumps.

**What we found.**

- HaptiConnect's road rumble follows the suspension travel in metres, not the percentage the game also sends.
- In the air, the percentage reads 0 while the metres keep moving.
- The travel jumps at a race start and after a pause.

**Fix.** The reader keeps both measures. The Horizon profile follows metres (Motorsport's waits for another change;
see [what is still open](#per-game-gaps)). Airborne frames keep the history going, speeds are never worked out across
a gap, and repeated packets are recognised by Forza's own clock.

#### Forza Horizon never reports kerbs

*September 18*

**Problem.** The maintainer drove over kerbs in BeamNG and in both Horizon games, but the Horizon recordings showed
none: "maybe they just don't have bumps like ACE".

**What we found.**

- An independent decode of the raw packets (its byte positions checked first on speed, rpm and gear) showed the
  rumble-strip flag at 0 on every packet, for every wheel, on every Horizon lap.
- The "roughness" value turned out to be a **surface-type code**.
- HaptiConnect's Horizon 5 plugin plays no kerb buzz there either, only a stronger road rumble on rough surfaces.
- A skeptic agent worked it out again and reached the same answer.

**Fix.** No kerb effect for Horizon: the maintainer's guess was right. The stronger rumble on rough ground is a known
gap ([per-game gaps](#per-game-gaps)). BeamNG has no kerb data either
([BeamNG has no kerb data](#beamng-has-no-kerb-data)).

#### Telling Horizon 5 from Horizon 6

*September 11*

**Problem.** The maintainer wanted separate settings for the two Horizon games: "separate the Forza games as well".

**What we found.** Both games send byte-identical packets to the same port. HaptiConnect has the same limitation,
which is why Horizon 6 couldn't borrow its Horizon 5 plugin ([No Forza Horizon 6](#no-forza-horizon-6)).

**Fix.** OpenShaker asks Windows which Horizon program is running. It uses a direct process snapshot, because the
usual command-line tool would flash a console window on every check. The check takes a few milliseconds and is
cached for 5 seconds. If neither game is visible it keeps the current Horizon preset, and if both run, Horizon 5 wins.
Checked live.

#### Listening only to this PC

*September 12*

**Problem.** A public app shouldn't accept game data from the network by default, but some players run Forza on an
Xbox or a second PC.

**Fix.** Every listener binds to this PC only (127.0.0.1). The advanced settings can open Forza to the network
(Windows Firewall must then let OpenShaker through). A test pins the local default.

**Assetto Corsa EVO** (setup and effects: [Assetto Corsa EVO](wiki/Assetto-Corsa-EVO.md))

#### Reading Assetto Corsa EVO's shared memory

*September 10*

**Problem.** The ACE reader was first built against a fake memory block written from the documentation, so its names,
positions and ranges were unconfirmed.

**What we found.** On the first live attach the game reported "live", and a 340-second drive was logged. A later
capture showed ACE updating its data a little over 300 times a second.

**Fix.**

- The reader only opens memory the game has already created, and never reads past its real size, so the older
  Assetto games' smaller blocks are safe.
- It lets go after 5 seconds without new data.
- Since September 18 it logs the whole 800-byte page, so logged drives can be replayed exactly.
- It falls back to the old names for the older Assetto games
  ([Assetto Corsa and ACC](#assetto-corsa-and-acc-partly-work-by-accident)).

#### A week on the Motorsport profile

*September 10 to 18*

**Problem.** For its first week, ACE had no profile of its own. The automatic game-to-profile map sent both Forza and
ACE to the Forza Motorsport profile.

**Fix.** On September 18 ACE got its own profile, starting as a copy of the Motorsport one, and a one-time switch
moved the existing ACE settings over to it. It was then changed wherever HaptiConnect's own ACE plugin measurably
differs ([ACE gears](#ace-gears-one-number-off-and-a-neutral-in-every-shift), [ACE's own vibration
hints](#aces-own-vibration-hints)).

#### ACE gears: one number off, and a neutral in every shift

*September 10, then September 18*

**Problem.** Shifts in ACE thumped twice.

**What we found.**

- ACE counts 0 as reverse, 1 as neutral and 2 as first.
- Every shift shows about 250 ms of neutral.
- **September 10:** a short neutral window stopped the double thump: 14 thumps for 14 shifts.
- **September 18:** ACE's new profile, copied from Motorsport, also copied HaptiConnect's Forza habit of thumping into
  neutral and again into gear, so it thumped twice again. HaptiConnect's own ACE plugin thumps once, when the
  next gear engages ([measured here](#bringing-hapticonnects-ace-plugin-back-to-life)).

**Fix.** The reader subtracts one. The ACE profile fires only when a gear engages, never into neutral.

#### ACE's slip is a real ratio

*September 10*

**Problem.** The slip tone played in ordinary corners.

**What we found.** ACE's slip reads about 0.05 even while the tyres grip. Forza's reads 0 until grip is lost.

**Fix.** ACE's slip is rescaled so 1.0 means about the grip limit, and ignored when the car is nearly stopped.
Afterwards the slip tone played only in real wheelspin and slides.

#### ACE suspension needs a scale

*September 10*

**Problem.** On ACE, the road rumble carried about 45 % of the output energy, against 20-27 % in HaptiConnect's
Forza output.

**What we found.** ACE reports the suspension travel in metres, and it moves far less than Forza's 0-1 range.

**Fix.** A per-game setting turns ACE's metres into a Forza-like scale. It was refined over several rounds against
recordings.

#### ACE's own vibration hints

*September 18*

**Problem.** The maintainer felt Forza Motorsport was less impressive than ACE: "I'd say the feedback felt less
impressive than EVO".

**What we found.** ACE publishes its own vibration hints for kerbs, slip, road and ABS. Forza has none of these. And
the refitted Motorsport profile keeps the road rumble almost silent on smooth tarmac, just as HaptiConnect does.

**Fix.** OpenShaker uses ACE's kerb and road hints. The ACE profile has no kerb cycle and no shift light, because
HaptiConnect's ACE plugin has neither.

#### Assetto Corsa and ACC partly work by accident

*September 18*

**Problem.** What happens with a game we never tested? In the maintainer's words: "what happens if we boot up a game
we haven't tested, like ACC?"

**What we found.** The older Assetto games still use the old memory names, and the start of their layout is the same.
So the engine, gear shifts, acceleration, suspension and crashes should work; slip, lock, ABS and kerbs won't.

**Fix.** The README lists them under
[Should also work (untested)](../README.md#should-also-work-untested).

**BeamNG.drive** (setup and effects: [BeamNG.drive](wiki/BeamNG-Drive.md))

#### The brake read zero all drive

*September 12*

**Problem.** A logged BeamNG drive showed the brake at 0 the whole way. In the maintainer's words: "let's fix the
BeamNG brake first".

**What we found.** Checked against BeamNG's own source, the pedals sit at bytes 48, 52 and 56. The first-day reader
looked 8 bytes too late, so its "throttle" was really the clutch. Decoded correctly, the brake had been pressed for
about 30 % of that drive.

**Fix.** Corrected, with a test pinned to a real packet from that drive. The handbrake, ABS, traction control and
engine-off now come from the dashboard lights.

#### No game mods

*September 12*

**Problem.** On BeamNG, crashes, bumps, acceleration and wheel lock were impossible: every packet was the plain
version, without g-forces.

**What we found.**

- HaptiConnect gets BeamNG's extra data from a small mod it installs into the game.
- BeamNG's own log shows that its 0.39 update disabled all mods.
- That mod was out of date anyway: it never filled in the road speed.
- Claude started writing a replacement mod, and the maintainer stopped it: "Why are we making a mod? I don't want to
  really install stuff like that." The maintainer was also thinking of putting the tool on GitHub.
- Claude agreed that a mod had been "the shortest path from where the code stood, not the best one".
- The maintainer's early "The BeamNG plugin however works great" probably came from driving before that update.

**Fix.** From then on, the rule for every game was built-in options only: Forza's Data Out; BeamNG's OutGauge and
Motion Sim; ACE with no setup at all; and Trackmania through Openplanet's own plugin manager.

#### Merging BeamNG's two built-in outputs

*September 12*

**Problem.** OutGauge has the pedals, rpm, gear, dashboard lights and wheel speed, but no g-forces or true ground
speed. Motion Sim, BeamNG's output for motion rigs, has the motion but no engine data. In the maintainer's words:
"go ahead with BeamNG Motion Sim".

**Fix.** One port receives both; packets are told apart by size and tag, and each updates its half. A half that goes
quiet is dropped. Ground speed and wheel slip come from combining the two. If one output is missing, the status line
says which box to tick in BeamNG's options.

#### Motion Sim: checking the axes

*September 12, then September 18*

**Problem.** Motion Sim's axes are smoothed and flipped compared with the old mod, so directions and thresholds were
guesses.

**What we found.** A checker tool replays a drive and reports which axis follows the car's change of speed. The first
drive had no Motion Sim data at all: the setting was either never switched on or not saved. On the second drive the
forward/backward axis checked out.

**Fix.** Forward/backward is verified, sideways only weakly, and vertical no further than plausible sizes. The
thresholds are still open ([per-game gaps](#per-game-gaps)).

#### BeamNG fields that don't mean what they say

*September 12*

**What we found.** The "speed" field is wheel speed, not ground speed. The old mod could leave the ABS light stuck on.
And BeamNG lights the battery warning when the engine is off.

**Fix.** Wheel speed is compared with Motion Sim's ground speed to detect lock-ups and wheelspin. ABS counts only
while braking. Engine-off is taken from the battery light.

#### Correct pedals would have woken effects at full strength

*September 12*

**Problem.** Some BeamNG effects had only been silent because the pedal data was wrong. With correct pedals, the shift
light would have pulsed about 11 dB over everything else.

**Fix.** Those effects got explicit, scaled strengths in the same change.

#### BeamNG has no kerb data

*September 18*

**What we found.** Neither BeamNG output has a kerb or surface value. Kerbs arrive only as small vertical jolts, below
HaptiConnect's bump threshold, so neither app pulses on them.

**Fix.** The thresholds stay where they are, so OpenShaker doesn't add pulses HaptiConnect doesn't play.

**Trackmania** (setup and effects: [Trackmania](wiki/Trackmania.md))

#### Trackmania has no telemetry setting

*September 12*

**Problem.** Trackmania doesn't send its data like the other games. In the maintainer's words: "If I could feel how
close a car was to slipping in Trackmania".

**What we found.** Openplanet, the community's scripting platform for the game, has a plugin called Data Sender. It
streams the car's full state to a local connection.

**Fix.**

- OpenShaker connects to it, waits quietly while it isn't there, and reconnects by itself.
- Installing Openplanet and Data Sender is the one extra step, done in Openplanet's own plugin manager. Some
  competitions switch plugins off.
- Later the maintainer wondered about writing our own: "I almost wonder if we can make a Trackmania plugin
  ourselves". Claude recommended staying with Data Sender: it gives the same data, an Openplanet plugin's audio can
  only reach the game's own output, and a custom plugin would need publishing and upkeep. The idea stays open
  ([ideas saved for later](#ideas-saved-for-later)). The [Trackmania guide](wiki/Trackmania.md) has the details.

#### Built before the plugin was installed

*September 12*

**Problem.** Data Sender wasn't installed yet when the Trackmania support was written.

**What we found.** So it was built from the plugin's published source and tested only against a fake server and a
scripted rehearsal. One behaviour, the slip value reading 0 while the tyres grip, was inferred from another plugin's
source.

**Fix.** The first real drive, on September 18, confirmed that behaviour and found the problems in the entries below.

#### Data Sender ships switched off and slow

*September 18*

**Problem.** After installing Data Sender, nothing arrived. Its service was stopped, and even when running it sent
only 10 updates a second.

**What we found.** Its source shows three things: it starts switched off, its default interval is 100 ms, and it
accepts commands even while stopped.

**Fix.** OpenShaker starts a stopped service and lifts **only** the shipped 100 ms default to every frame. It never
overrides a setting the user chose, it logs one line when it does this, and the README says so. These conditions
were agreed before the code was written.

#### Data Sender's format

*September 12, then September 18*

**What we found.** Most values come in two layouts. The sideways-speed value only works in Openplanet's developer
mode. Per-wheel ground contact isn't sent in Trackmania (2020).

**Fix.** OpenShaker accepts both layouts, works out the sideways speed itself, and tells whether a wheel touches the
ground from each wheel's "falling" state. Logged drives keep every value.

#### A blackout every second, then server is full

*September 18*

**Problem.** After the maintainer raised the update rate ("I was able to increase update frequency"), the data
stopped for about 0.2 seconds every second. Then Claude's checker was refused.

**What we found.**

- A per-client cap of 200 messages a second had been left in Data Sender's settings **by an older OpenShaker build**.
  Above that rate, the game hit the cap and blacked out.
- Separately, the plugin's client limit had been set to 1.

**Fix.** The maintainer reset both settings, the client limit back to its default of 8 ("done, set to 8"). OpenShaker
no longer sends the global rate command, and it turns off the plugin's chatty status messages for its own connection.
The README's troubleshooting covers the client limit.

#### Surface IDs, and two decoys

*September 12*

**What we found.** The game sends surfaces only as numbers. The table comes from the list in Openplanet's own header
file. Two look-alike tables in the same header would have been wrong; one of them isn't a surface list at all.

**Fix.** The list is pinned by a test. ID 80 means the wheel is in the air.

#### Crashes measured over a window

*September 12*

**Problem.** The effects run every 10 ms and see only the newest frame, but the plugin sends frames faster, so a crash
could slip between two looks.

**Fix.** Acceleration is measured as the change in velocity over at least 20 ms, and a long gap clears the history.
It became a project rule: fast data sources must not rely on frame-to-frame differences.

#### Wheelspin without a spin signal

*September 12*

**Fix.** The reader learns each wheel's rolling size while the car drives straight, then compares the wheel's
rotation with the road speed.

#### The grip warning: constant and annoying

*Built September 12, first driven September 18*

**Problem.** The maintainer wanted to feel the car approaching a slide. On the first real drive, the warning pulsed in
almost every corner: "pulsing in corners was constant and annoying, landings felt good".

**What we found.**

- The game's slip value is 0 while the tyres grip and jumps to full once they slide, so it marks the slide, not the
  approach. The warning was built instead from sideways g-force and the car's body angle, with first-guess limits of
  20 m/s² and 6 degrees. It starts at 60 % of the limit, which is 12 m/s².
- The drive showed the car holding 60-90 m/s² sideways on tarmac without letting go, so the warning ran about 22 % of
  the time.
- Most "slides" were really wall hits or landings.

**Fix.**

- The maintainer chose "Loose surfaces" only. The warning now works on dirt, grass, sand, snow, ice and wet roads,
  with per-surface limits that are still first guesses ([Trackmania gaps](#trackmania)).
- The g-force rumble is off in the Trackmania profile, and the slide buzz is softer.
- The maintainer also moved three sliders: engine rpm down, g-force rumble off, gear shift up.

#### Jumps: suspension stretches in the air

*September 18*

**Problem.** Flying and landing felt harsh: "The flying and landing were a little harsh".

**What we found.** In the air, the dampers stretch fully within about 80 ms, which read as bumps, and the wheels spin
freely, which read as wheelspin. About 30 % of take-offs made a bump.

**Fix.** The suspension is held while a wheel is in the air and settles after landing, and airborne wheels report no
slip. Take-off bumps dropped from 30 % to 9 %. Gentle touchdowns now give a small bump sized to the real compression,
where before they were either silent or a full hit on all four wheels.

#### Respawns played the loudest crashes

*September 18*

**Problem.** Every respawn fired a full-strength crash, and a gear-change thump as well.

**What we found.** An adversarial review of the logged drive found it. A respawn teleports the car, so its speed jumps
from 0 to, say, 55 m/s from one frame to the next, which looks like a colossal crash. The plugin's "discontinuity"
counter changes on a frame where the speed is still 0, and the new speed arrives about 14 ms later.

**Fix.** After the counter changes, the car is kept quiet for 60 ms. The next drive had 8 respawns and no false crash.

#### Nose-first and slope landings

*September 18*

**Problem.** Some landings played a crash hit on top of the landing thump.

**What we found.** When the ground stops a car that is tipped nose-down, the stop reads as braking or cornering in the
car's own directions. A slope pushes partly sideways too. On the second drive, 3 of 13 landings misfired this way.

**Fix.** Two separate fixes, one for nose-first and one for slope landings. For a moment after each real landing, the
reader removes the ground's push, then fades it back in (a hard cut was a jolt of its own). It isn't done all the
time, because on loops and wall rides those forces are real. Result: 0 of 24 landings misfired across both drives,
and real crashes still fire.

#### Auto-tuning proposals, replayed and rejected

*September 18*

**Problem.** OpenShaker has a tool that suggests thresholds from your own drives. Its first suggestions for
Trackmania looked tempting.

**What we found.** Replayed against the real drives, they failed: on the first drive, the suggested crash threshold
would have dropped 4 of its 14 real wall hits; the bump suggestions were unstable between the two drives; and there
were too few slides on loose surfaces (about 10 seconds per surface) to learn from.

**Fix.** Nothing was applied. The first guesses stay until there is more data.

#### Car facts belong in the profile

*September 18*

**Problem.** The tuning tool wrote each car's rev range and suspension travel into the user's settings file.

**Fix.** These are the same for every player, so they now ship in the Trackmania profile, one entry per car type.

#### Trackmania-only effects

*Built September 12, first felt September 18*

**Problem.** The maintainer wanted Trackmania to be complete: "I'd like to make this fully featured."

**Fix.** New effects: surface textures, water, roof scrapes, landing thumps sized by the fall speed, and turbo and
reactor boosts. They are on only in the Trackmania profile, so the games matched to HaptiConnect are untouched. The
first verdict: "landings felt good". The [effects overview](wiki/Effects-Overview.md) leads to each one.

### Chapter 2: a dependable everyday app

#### The first shortcut crashed

*September 10*

**Problem.** The maintainer asked for a desktop shortcut: "I'd like a shortcut on my desktop, make an icon."
Double-clicking it printed a Python error: "No module named 'numpy'".

**What we found.** The first suspect was the wrong Python. The real cause was Claude's sandbox: Claude's install had
gone into a private, redirected copy that the maintainer's Python never saw
([Traps in Claude's own workspace](#traps-in-claudes-own-workspace)).

**Fix.** A dedicated Python environment outside AppData, which the launcher calls by its full path. Checked by
launching it the way Explorer does.

#### The first window, and an honest no

*September 10*

**Problem.** "Give me an application with a simple UI please"

**Fix.** A simple window: live game data, an output meter, a master slider, an on/off switch and a strength per
effect, a test tone and a demo. Asked whether it would feel like HaptiConnect, Claude said no: the effects matched by
name, but the sound was its own first guess. That answer started the measuring work
([HaptiConnect becomes the measuring stick](#hapticonnect-becomes-the-measuring-stick)).

#### Is the GUI finished? Three hidden problems

*September 11*

**Problem.** The maintainer asked: "is the GUI part of the application all finished?"

**What we found.** Checking before answering, Claude found three problems:

1. "Save settings" would have copied the whole calibration into the user's settings, so any later recalibration would
   silently never apply.
2. "Reset" went back to generic defaults, about six times HaptiConnect's level.
3. The strength sliders ran from 0 to 2, while the useful range was 0.12-0.2, only a few pixels wide.

Then came the overclaim: Claude said it had made the fixes when it hadn't
([When the AI got it wrong](#when-the-ai-got-it-wrong)).

**Fix.** Each effect got a trim, where 100 % means exactly as calibrated, and only the user's own changes are saved.
The sliders read 0-200 %, and "Reset to profile" restores 100 %. Old settings were migrated with a backup. The tests
caught two regressions on the way.

#### The window couldn't open

*September 11*

**Problem.** The shortcut started the app, but no window appeared. The only trace was an error log.

**What we found.** A Python environment on Windows doesn't carry the library files the window toolkit (Tcl/Tk) needs.

**Fix.** The app points the toolkit at the main Python's files before it opens a window. The same trap came back when
building the installer, where the packager silently dropped the toolkit. The build now fails loudly if it is
missing.

#### A tray app first

*September 11*

**Problem.** The maintainer wanted the app to start with Windows into the notification area: left-click to open,
right-click for status and actions. There was also a stray window: "When I open the app there is a cmd window that
opens in the background."

**What we found.** The first cause was simple: the shortcut ran a batch file. The deeper cause is in
[The command window that kept coming back](#the-command-window-that-kept-coming-back).

**Fix.** A tray icon, in colour while running and grey while stopped. The right-click menu has live status lines
(device, game and frame rate, profile, level, and a "Problem" line only when something is wrong). Closing the window
hides it; only Quit exits. A windowless launcher replaced the batch file.

#### A tray menu that did nothing

*September 11*

**Problem.** Found in testing, before the maintainer used it: every tray menu action would silently do nothing.

**What we found.** The tray and the window run on different threads, and the window toolkit may only be touched from
its own thread. The error was swallowed.

**Fix.** Every tray action is handed to the window's thread through a queue, and the test tone got the same fix. Menu
checkmarks are rebuilt after every change, because Windows reads them only when the menu is built.

#### One copy at a time

*September 11, hardened September 12 and 18*

**Problem.** A second launch would start a second copy, fighting the first over the ports and the shaker.

**Fix.**

- A tiny local connection acts as both a lock and a message channel: a second launch just says "show" and exits. It
  is local-only, so there is no firewall prompt.
- Later additions: a "quit" message for the installer, and a lock the installer checks.
- The pre-publish audit found that a launch that could neither take the lock nor reach the running copy did nothing
  at all. Now it logs and shows the reason.

#### Always on

*September 11*

**Problem.** The maintainer only opens the app to drive, so Start and Stop were one more thing to get wrong: "I just
want it to go".

**What we found.** Without a Start button, a failed start would leave the app dead. And the shaker is often still
asleep when Windows boots.

**Fix.** Haptics start about 0.4 seconds after launch and retry every 15 seconds while they can't. The status line
says why they aren't running and that they are retrying. A hidden tray app never opens an error box nobody could see.
A test fakes a dead device and checks that the retry fires. A week later the maintainer asked for an off switch after
all ([A Haptics on switch after all](#a-haptics-on-switch-after-all)).

#### The command window that kept coming back

*September 11*

**Problem.** There was still a command window when opening the app from Start: "I still have a cmd window that
opens".

**What we found.**

- The windowless Python inside a Python environment is only a stub: it starts the console version of Python, and
  Windows gives that its own window.
- The launcher is therefore two processes. Ending "the app" by program name can leave the other half running, still
  holding the shaker and the game ports.
- The Start menu had no entry at all; Start search had been finding the desktop shortcut.
- During the hunt, Claude's process filter matched its own shell and ended it.

**Fix.** A repair step replaces the stub with the real windowless Python, and three tests cover it. The maintainer's
verdict: "no cmd window now". The installed app isn't affected.

#### Per-game presets

*September 10 to 11*

**Problem.** It started on September 10 with a request: "I'd want the desktop app to auto detect which game I have
open". Switching presets per game was added that day. On September 11 the maintainer found the settings buttons
clunky, and wanted each game's settings to load by themselves and to be editable without the game running: "The save
settings, load profile and open folder is too clunky."

**What we found.** Switching games only replaced the settings the new game defined, so the previous game's levels
leaked through: the engine was about 12 dB off after a switch from Forza to BeamNG.

**Fix.** One preset per game, with a picker that follows the running game. Edits save themselves. Switching starts
from clean defaults. Checked live: a Forza change left ACE untouched.

#### Saving settings

*September 11 to 20*

**Problem.** Several separate bugs:

1. Turning Master down wasn't saved, so it could come back at full strength after a reboot. The audit called this a
   safety issue.
2. The Advanced dialog's OK button saved nothing.
3. A "no" to starting with Windows would have been asked again.
4. Every default was frozen into the user's settings file.
5. Presets stored copies of the on/off switches, so profile changes never reached them.

**Fix.** Master saves shortly after a change. The settings file holds only what differs from the defaults. A one-time
cleanup, approved by the maintainer and tried first on a copy of their real settings, removed the copied switches and
kept their deliberate "off"s.

#### Start with Windows, and a Start menu entry

*September 11 to 18*

**Problem.** The maintainer wanted the app to start with Windows, and later to find it by typing its name in Start:
"Please make it so the app is searchable from the start menu."

**What we found.** Claude's sandbox also redirects the registry, so Claude couldn't set up the startup itself. And
for other users, the advice for the release was: ask before changing their system.

**Fix.** The app registers its own startup entry the first time it is opened. Other users get a one-time question;
in the installed version, the installer's ticked box is the consent. An old entry under the app's former name is
replaced, so two copies never start. The maintainer's Start menu entry was created by a script started through
Explorer.

#### A Haptics on switch after all

*September 18*

**Problem.** A week after the haptics became always on, the maintainer asked for an off switch: "Please add a toggle
in the program and on the tray item to disable haptics".

**What we found.** A four-reviewer check found an older bug. If another program held the shaker when OpenShaker
started, the start failed halfway and left the game ports blocked until Quit, so switching off and on again could
never recover. A second review found that the cleanup froze the window for about a second.

**Fix.** "Haptics on" in the window and the tray. Off frees everything, turns the icon grey, and is remembered. The
app now opens the shaker first, so a busy shaker fails with nothing to undo, and any half-start is cleaned up. Before
restarting the maintainer's copy, Claude waited for their Trackmania drive to end.

#### Sharing the ports

*September 11 and 18*

**Problem.**

- Recording comparisons needs the game ports free, but the documented option to start without haptics did nothing.
- There was no way to quit the tray app from the command line.
- HaptiConnect sat in Windows' Startup folder and grabbed BeamNG's port at every boot, so whichever program started
  first got the data: a coin flip.

**What we found.** The retry timer ignored the launch option and started the haptics a fraction of a second later
anyway.

**Fix.** The option works now, with a test. A quit command waits until the ports are free, and the installer uses it,
timed so the installer's own checks see the app gone. HaptiConnect's startup entry was later found disabled. The
README's [troubleshooting](../README.md#troubleshooting) and the guide's [troubleshooting
page](wiki/Troubleshooting.md) name HaptiConnect and SimHub as the usual port conflicts.

#### Drive logs that survive a crash

*September 18*

**Problem.** Stopping a logging run the hard way lost the whole drive, and the log's summary never listed its
sources.

**Fix.** The data streams to disk as it arrives, and the summary is written at the start and at the end. Existing
log folders are protected from being overwritten. The console logger also refuses to run beside the tray app,
instead of recording an empty drive while the tray app holds the ports.

#### Sliders that jump where you click

*September 18*

**Problem.** The maintainer wanted a click on a slider to jump straight there, and a way to type a percentage: "if I
click on the sliders it jumps to that percentage".

**What we found.** On Windows, sliders only creep toward a click. A review of the new code with several agents found
14 bugs, such as the arrow keys on Master jumping to 0 or 100 %.

**Fix.** Click to jump, type to set, and arrow steps of 1 % and 10 %. All 14 bugs were put back one at a time, and the
tests caught each one.

### Chapter 3: sound and safety

#### Demo works but the test tone doesn't

*September 11*

**Problem.** Pressing Test tone gave no vibration: "when I press test tone I get no vibration". Hours later: "Demo
works but the test tone doesn't".

**What we found.**

- **First, a wrong conclusion.** A recording of the shaker's output showed the tone at full level, so Claude blamed
  the amplifier.
- The Demo report proved the hardware fine. Windows lists the ButtKicker four times, once under each of its audio
  systems.
- When the preferred one wasn't ready yet (at boot, before the shaker woke up), the app took the first match, which
  opened an **exclusive** stream. The haptics played, but the test tone's second stream could never open, and
  HaptiConnect couldn't share the device either.
- The recording tool only sees the shared mixer, so an exclusive stream is invisible to it. That is why the hardware
  had looked at fault.

**Fix.** Only shared audio systems are used; if none is ready yet, the app waits and retries. Devices are looked up
again on every start. The test tone is mixed into the running stream instead of opening a second one. The verdict:
"it works now".

#### Never fall back to the speakers

*September 12*

**Problem.** Found while preparing for strangers: if the shaker was missing, the original code played through
Windows' default output. On someone else's PC, that is their speakers. Device names also change after a re-plug
("2- ButtKicker").

**Fix.** The shaker is picked by name, ignoring the number in front. A missing shaker is reported ("pick your shaker
under Output > Device"), and nothing else plays. The default output is used only if chosen on purpose. The README's
[Safety](../README.md#safety) section and the guide's [safety page](wiki/Safety.md) explain this. HaptiConnect's own
trouble came from the same kind of cause: remembering the device by ID ([HaptiConnect kept forgetting the
shaker](#hapticonnect-kept-forgetting-the-shaker)).

#### Unplug and replug

*September 18*

**Problem.** Found by the pre-publish audit: unplugging the shaker while playing left the app saying "Running" while
nothing played.

**What we found.** When a device disappears, the audio library raises no error. The stream just stops.

**Fix.** A watchdog notices a stream that has stopped, or that hasn't asked for audio for 2 seconds. The app then says
which device went away, notifies from the tray, and retries every 3 seconds for the first minute, then every 15
seconds. It was checked on a real stream; a physical unplug test is on the testers' checklist
([what is still open](#openshaker-itself)).

#### Left channel only, and 6 dB found twice

*September 10, then September 19-20*

**Problem.** Back to back, OpenShaker felt stronger even when the recordings measured the same: "The volume on our
version is still higher".

**What we found.**

- **The first time:** HaptiConnect's recordings have a perfectly silent right channel. OpenShaker played both
  channels, which probably add up in the ButtKicker PRO. Our recorder compared one channel, so the numbers looked
  equal while the seat felt the difference. The default became "Left", and the maintainer said it "feels about right
  now".
- **The second time,** found by the parity audit eight days later (September 19): "Left" was made as a single-channel
  stream, and Windows copies that to **both** channels, so up to 6 dB too much remained. A check played a test tone
  too quiet to feel (-60 dBFS at 50 Hz) and recorded it: the old path gave identical left and right channels, the
  fixed one a silent right channel.
- A side effect: everything felt in Trackmania on September 18 had been about 6 dB too strong ([Trackmania
  gaps](#trackmania)).

**Fix.** The stream now opens as wide as the device and writes silence to every unused channel. Confirmed on the
device. The README warns that "Both" may feel stronger on a ButtKicker PRO.

#### A limiter like HaptiConnect's

*Found September 19, in the app September 20*

**Problem.** Found by measuring, not by feel. In the clean recordings, HaptiConnect's output stays at or below 0.985
of full scale (the one brief overshoot, to 0.991, is in a replay that held two copies of its output), and in BeamNG
its engine visibly dips under every gear-change thump. OpenShaker instead clipped loud peaks, which bends the sound
and never dips.

**Fix.**

- A look-ahead limiter like HaptiConnect's: a loud burst turns the whole mix down briefly. It looks 1.3 ms ahead and
  lets the volume back up along a straight ramp: from half volume to full takes about 0.6 seconds.
- The Demo got its own, lower limiter. On September 27 the test tone was found 4.2 dB weak, but only in Demo, because
  it passed through that limiter; it now plays after it.
- The same review found that one bad number (NaN) from a single effect could silence the whole mix. Each effect's
  output is now cleaned before mixing.

#### Bad data must never reach the shaker

*September 12, then September 20*

**Problem.** Found by a random-data test, not by a user: 300 rounds of random bytes at every packet size crashed the
BeamNG reader on a garbled gear value.

**Fix.** The readers check their input, and a bad packet is counted and skipped. Broken numbers are removed per
effect and from the final mix, so garbage can't become a full-scale pop. A bug in one effect can't stop the audio
stream, and ACE's memory reads are bounds-checked. Everything listens on this PC only by default
([Listening only to this PC](#listening-only-to-this-pc)).

#### Demo mode used to jolt

*September 12 to 27*

**Problem.** Without a game, the Demo played near full volume. Once the profiles matched HaptiConnect's real
loudness, the Demo on the BeamNG profile peaked at almost full scale.

**Fix.** First a fixed, lower Demo level, with a test. Then per-profile scaling: every profile's Demo peaks at -7 dBFS
at most, with a Demo limiter as a backstop.

### Chapter 4: matching HaptiConnect, the short version

[HOW_IT_WAS_TUNED.md](HOW_IT_WAS_TUNED.md) tells this part properly, with spectrograms and numbers. The entries here
are the problems we met on the way.

#### The method in one paragraph

Log a real drive. Replay the identical data into HaptiConnect with the game at its menu, and record its output
digitally. Render OpenShaker from the same data. Line the two up, compare them, fit, and check on drives left out of
the fitting. Much of this was the maintainer's idea: "record the output from the ButtKicker application and reference
that with the signal".

#### How the first measurements were made

*September 10*

**Problem.** Before any real laps, we needed to know what each HaptiConnect effect does on its own.

**What we found.** Claude's analogy for why test signals came first: you "measure a speaker with a sine sweep rather
than by playing a song". The calibrator:

1. set HaptiConnect's own game profile to one effect at full strength (after saving a backup of the maintainer's
   original);
2. restarted HaptiConnect through Windows Explorer and fed it synthetic packets;
3. recorded HaptiConnect's output, plus the telemetry HaptiConnect itself forwards, so each recording shows exactly
   what HaptiConnect received;
4. restored the original profile from the backup.

The maintainer felt the tests from the chair, with no game running: "Are you running BeamNG in the background?" And
"I'm not sure which I felt since I wasn't shown which setting was being tested".

#### Test signals felt like nothing

*September 10*

**Problem.** Many of the test signals made no vibration: "Some of the tests I haven't felt anything. I'm in the
chair". Seeing synthetic data, the maintainer objected: "Shouldn't we train off actual game output not your simulated
output".

**What we found.**

- Silence was a finding, not a fault: a full-scale gear-shift test proved the chain worked.
- Some silences came from HaptiConnect's own quirks ([the Motorsport
  plugin](#hapticonnects-motorsport-plugin-reads-the-wrong-bytes)), and probably some from test values unlike what
  real games send ([Kerbs you couldn't feel](#kerbs-you-couldnt-feel)).
- HaptiConnect looks at the data only about 12 times a second, so events shorter than about 170 ms are hit or miss.

**Fix.** Real laps, replayed through both apps, became the reference.

#### HaptiConnect's Motorsport plugin reads the wrong bytes

*September 10*

**Problem.** Fed genuine Motorsport packets, HaptiConnect's gear shift, wheel lock and shift light stayed silent.

**What we found.** Fed the same data in the Horizon layout, its gear shift fired on every change and wheel lock
responded. The plugin reads gears and pedals where a Horizon packet has them (byte 244, not 232). By inference, a
Motorsport player who follows HaptiConnect's setup guide, or who sends the game's own format, never gets those
effects. We didn't test that live.

**Fix.** For measuring only, Motorsport drives are converted to the Horizon layout before they are replayed.
OpenShaker reads both layouts correctly.

#### Should I be feeling the playback?

*September 10*

**Problem.** The replay was meant to let the maintainer feel HaptiConnect's version of their lap: "Should I be
feeling the playback? Because I don't".

**What we found.** HaptiConnect's output was silent, stuck on frame 0 of 25,480. The new replay tool had crashed and
never sent a frame.

**Fix.** The tool was fixed. The first real comparison then showed OpenShaker about 11 dB louder, and "muddy".

#### More refined and less muddy

*September 10*

**Problem.** Back to back, HaptiConnect felt better: "I feel like the HaptiConnect version felt better, more refined
and less muddy".

**What we found.** The maintainer diagnosed it first: "our model definitely has more noise while driving in a
straight line", masking the suspension feel, and asked us to record HaptiConnect's output and compare. The
measurements agreed: version 1 was too loud and too busy. Its constant idle rumble, slip tone and suspension pulses
fired on ordinary jitter in the data. And HaptiConnect's strength setting of 0.5 is far less than half: it is at least
15.8 dB below full strength.

**Fix.** Every effect was set to HaptiConnect's measured level, suspension pulses fire only on real bumps, and the
kerb buzz went lower. After the next round the maintainer still noticed a difference: "I felt the rumble strips more
and feelings felt sharper on HaptiConnect", which led to the [kerb fixes](#kerbs-you-couldnt-feel).

#### A little powerful

*September 10*

**Problem.** The quieter version still felt strong: "the feedback felt the same, a little powerful".

**What we found.** Claude's reply: "Your impression is correct, and now explained". Default strengths saved in the
settings file were overriding the calibrated ones.

**Fix.** Saved settings now override only what the user changed, and a line in the startup log prints the strengths
actually in use.

#### What measuring HaptiConnect taught us

- It evaluates the game data only about 12 times a second.
- It plays on the left channel only ([more](#left-channel-only-and-6-db-found-twice)).
- Its strength slider isn't linear.
- It ends in a limiter that turns the whole mix down under loud bursts ([more](#a-limiter-like-hapticonnects)).

The numbers are in [CALIBRATION.md](CALIBRATION.md#what-hapticonnect-does-measured). OpenShaker copies whatever
affects the feel, but runs its effects every 10 ms.

#### Measuring pitfalls

Some wrong turns came from the measuring itself:

- A "45 Hz tone" turned out to be spill-over from HaptiConnect's 41 Hz road rumble in a short analysis window. Longer
  windows separate the two.
- The comparison tool's envelope correlation read 0.037 on BeamNG's flat rumble, against 0.535 with a 0.25-second
  window.
- An early rescaling of the BeamNG profile silently skipped the engine, which had no explicit strength setting.
- Old tables had HaptiConnect's engine tone stuck near 57 Hz at high rpm. That was an artifact of the analysis: its
  engine tone keeps following the rpm.

#### A real Horizon 5 reference, and Horizon 6 without a plugin

*September 10, then September 18*

**Problem.** A fair Horizon comparison needs HaptiConnect's own Horizon 5 plugin, and Horizon 5 had been uninstalled:
"I can reinstall FH5 if we need to". Then: "Let's try Forza 5 through plugin vs HaptiConnect".

**What we found.**

- With Horizon 5 reinstalled, the Horizon references come from HaptiConnect's native Horizon 5 plugin.
- For Horizon 6 (on September 18), a lap was logged, then Horizon 5 was opened to its menu so HaptiConnect's Horizon 5
  plugin would listen, and the Horizon 6 lap was replayed into it.
- No data arrived until Horizon 6 was pointed at OpenShaker's port. Then OpenShaker recognised Horizon 6 and switched
  preset by itself.
- HaptiConnect renders Horizon 5 and Horizon 6 laps differently at the same inputs.

**Fix.** One Horizon profile plays both games for now ([per-game gaps](#per-game-gaps)).

#### Bringing HaptiConnect's ACE plugin back to life

*September 18*

**Problem.** ACE had been compared against HaptiConnect's Motorsport plugin as a stand-in, because its own ACE plugin
never gets live data ([Assetto Corsa EVO went silent](#assetto-corsa-evo-went-silent)). The maintainer's idea: "feed
the ACE information we recorded into the ACC part of the HaptiConnect plugin".

**What we found.**

- Claude built a replayer that writes a recorded ACE drive under the **old** memory names, with ACE at its menu.
  HaptiConnect's real ACE plugin played it. That proved the diagnosis: only the names and the layout were stale.
- A surprise: the replay most likely also woke HaptiConnect's Assetto Corsa Competizione plugin (it saw ACC's version
  string), so the recordings probably hold two copies of every effect.

**Fix.** HaptiConnect's own ACE plugin became the ACE reference. The doubled recordings are scored at one copy's
level, and a replay option can wake only one plugin next time ([Assetto Corsa EVO](#assetto-corsa-evo)). None of this
ships in the app.

#### Replaying the raw packets

*September 18*

**Problem.** The first reference recordings were replayed from logged values, which lost detail: surface values
clipped to 1.0, neutral stored oddly, and a fixed cylinder count and tyre temperatures.

**Fix.** Forza's raw packets are now logged and replayed as they were received. The old laps were recorded again as a
new baseline, and new Motorsport laps keep the surface value on kerbs at its real size (around 1.8, where the old laps
were capped at 1.0).

#### Recordings that can't be made again

**Problem.** A HaptiConnect recording is only as good as the HaptiConnect that made it, and the old renderings can't
be recreated.

**Fix.** The replay tool refuses to write into an existing HaptiConnect recording folder.

#### Repeatable renders

**Problem.** OpenShaker's old gear-shift sound picked a slightly random pitch each time (HaptiConnect's follows the
rpm), so two renders of the same drive never matched exactly. That made comparisons noisy, and it made the Demo
test flaky.

**Fix.** Renders take a seed, so the same drive renders the same way every time.

#### HaptiConnect's recordings go silent mid-drive

*September 22*

**Problem.** Some HaptiConnect recordings contain stretches of perfect silence while the car is driving: 12-24 % of
the driving time on several Motorsport references, and 71 % on one BeamNG drive.

**What we found.** The cause is unknown: it could be HaptiConnect or the recording. Counting those stretches had made
OpenShaker look up to 0.6 dB louder than it was.

**Fix.** Those moments are left out of every comparison, and their share is reported.

#### BeamNG's loudness changed three times

*September 11 to 20*

**Problem.** After a BeamNG drive the maintainer reported heavy shaking at idle: "done driving, check the idle
intensity, it shakes a lot".

**What we found.** OpenShaker was faithful to HaptiConnect, within about 1 dB. HaptiConnect's **own** BeamNG preset
is a near-constant, near-full-scale rumble, about 12 dB (four times) stronger than its Forza preset at the strengths
the maintainer used (1 for BeamNG, 0.5 for Forza).

**Fix, in three turns.**

1. The BeamNG profile was scaled down to the Forza level.
2. The maintainer first asked for a rollback, then corrected it: "I made a mistake, I didn't really want us to roll
   back". The scaled level stayed, built into the one BeamNG profile.
3. With the exact-parity decision, the scaling was undone. The maintainer was warned that BeamNG would get about four
   times stronger, and approved it.

The README now says to set the amplifier with the strongest game.

#### Exact parity, and the approvals

*September 18 to 20*

- **The decision.** "why wouldn't we be the exact same loudness?", and then: "I want to mimic the feel of the output
  from the HaptiConnect driver".
- **"apply it".** The second Motorsport refit improved the scores but missed two strict acceptance rules by hairlines.
  The maintainer approved it, and both misses were written down.
- **"yes to all".** Four exact-parity profiles, plus a list of code fixes, biggest first: the
  [left-channel bug](#left-channel-only-and-6-db-found-twice), the [limiter](#a-limiter-like-hapticonnects), road
  rumble that follows the real suspension, braking and cornering combined, missed crashes, and a shift light that
  stays silent in reverse. All applied, with backups.
- **The results** are in [HOW_IT_WAS_TUNED.md](HOW_IT_WAS_TUNED.md#the-numbers). For the write-up, the maintainer
  asked: "Create new spectrographs and include information about how we refined the algorithm". An independent
  fact-check of that write-up caught its wrong claims before it was published.

### Chapter 5: making it shareable

#### Going public

*September 12*

**Problem.** The maintainer decided to go public: "I'd like to make this app public on GitHub I think". What would
the public prefer?

**Fix.** Claude's advice became the release plan: a normal Windows installer; nothing installed into games; no
HaptiConnect needed; any bass shaker (with a choice of device and channel); ask before starting with Windows; and get
along with SimHub.

#### Simple, honest, and list what was tested

*September 12*

- "I hate complicated GitHubs."
- "Make sure to list the hardware we did test it on."
- "I am okay with admitting these applications are created using Claude."

**Fix.** A one-click Setup.exe, a short README with a table of
[tested hardware](../README.md#tested-hardware-and-software), and a "Should also work" list for other shakers.

#### The name and the license

*September 12*

**Problem.** "I'm thinking OpenShaker or OpenKicker, check if there are projects like that already".

**What we found.** ButtKicker is The Guitammer Company's trademark, and "OpenKicker" sits close to the KICKER
car-audio brand.

**Fix.** The maintainer chose OpenShaker and the MIT license. The code and the profiles got neutral names, and the
copyright uses the maintainer's public handle, not their name.

#### No recorded HaptiConnect audio ships

*September 12*

**Problem.** Six tiny clips recorded from HaptiConnect were part of the profiles: gear shifts and impacts for Forza
and BeamNG, a bump and one kerb cycle, about 0.6 seconds of audio in all.

**Fix.** The maintainer chose to replace them. They are now generated in code from their measured pitch, length and
shape, and the recordings stay private ([Generated, not copied](HOW_IT_WAS_TUNED.md#generated-not-copied)).

#### Proving it runs anywhere

*September 12*

**Problem.** An app that works on one PC may depend on something only that PC has.

**Fix.** The files that ship (72 of them) were copied to a clean folder with a fresh Python environment. All 157
tests passed there, and a first run with no settings file worked. Settings and logs moved to a per-user settings
folder, with a one-time move of the old settings.

#### Test first, pause, then ship

*September 12 to 27*

- **September 12:** asked how to label an untested first release, the maintainer chose the answer "Wait, I'll test
  first".
- **September 18:** "We don't have to push to GitHub yet, I want to make more changes."
- **September 27:** "I want to do OpenShaker first, I am happy with that", and the choice to publish once the checks
  pass.
- **The release steps:** freeze the code, audit it, build from a clean copy of the public code, test the install,
  publish.

#### Trackmania's one extra step

*September 18*

**Problem.** "Alert the user of the dependencies, most players have Openplanet".

**Fix.** The README spells out Openplanet and Data Sender. Forza Horizon 6 was listed as "should also work" until the
maintainer drove it; it now has a compared lap.

#### A double click away

*September 12 and 27*

**Problem.** "I want it to just be a double click away from being set up".

**Fix.**

- One screen with two ticked boxes (Start with Windows, desktop shortcut) and Install.
- A per-user install with no administrator prompt, which then starts the app.
- Silent updates start the tray app again afterwards ("yes, relaunch the tray app after silent updates").
- The uninstaller asks about the settings.
- Build safety: the license must be there, the packages are pinned, and the build comes from a clean copy.
- One slip: the build tool emptied its output folder and deleted an old test installer
  ([When the AI got it wrong](#when-the-ai-got-it-wrong)).

The [DEVELOPMENT notes](DEVELOPMENT.md#building-the-installer) explain the build.

#### No personal information

*September 27*

**Problem.** "can we verify there is no personal information in this code"

**What we found, and removed:** private work notes and settings in the project folder, names based on trademarks,
the recorded HaptiConnect clips, absolute paths in profile notes, and the wrong-company attribution.

**Fix.** A release test fails on any user-folder path or real-looking e-mail address. The final scan checked 234 real
identifiers from the PC (serial numbers, device, network and account IDs) across all 97 publishable files: zero hits.
The installer was built in a neutral folder, then unpacked and scanned. Pictures carry no text metadata, and commits
use a private address.

#### Licenses and notices

**Fix.** Missing third-party license files were added, and one license that Python's docs lack was copied from its
source. OpenSSL is left out. Only the PortAudio build without ASIO ships (the ASIO builds carry another company's
SDK). pystray ships as replaceable source files, as its license asks. A disclaimer says the project isn't affiliated
with the makers of the hardware, the software or the games.

#### Built with AI, open to feedback

*September 12 and 27*

**Problem.** "Be transparent about it being AI but I will take feedback and can fix bugs."

**Fix.**

- The README section [Built with AI, open to feedback](../README.md#built-with-ai-open-to-feedback).
- Issue forms for bugs, hardware and feel reports, and ideas.
- A tray item that only opens the issue page: nothing is sent automatically, and the README warns that logs can
  contain your Windows user name.
- The installer and the README credit the maintainer and Claude together, and the license stays in the maintainer's
  name. Claude is described as an AI model made by Anthropic, and nothing suggests that Anthropic publishes or
  endorses the app.

---

## Part 4: what is still open

### OpenShaker itself

- Its live end-to-end delay, from game to shaker, has not been measured
  ([Timing that wandered](#timing-that-wandered)).
- A physical unplug-and-replug test is on the testers' checklist; none is recorded yet.
- It was tuned on one rig (a ButtKicker PRO) and a handful of drives. Other shakers and amplifiers "should work", but
  are untested.

### HaptiConnect questions we couldn't settle

- The slow drift the maintainer felt on Forza Motorsport wasn't reproduced: the recordings are too short.
- The cause of HaptiConnect's silent stretches is unknown.
- HaptiConnect was checked in September 2026. If it gets an update, parts of
  [Part 1](#part-1-why-openshaker-exists) may change.

### Per-game gaps

[HOW_IT_WAS_TUNED, Chapter 5](HOW_IT_WAS_TUNED.md#chapter-5-whats-still-different) and
[CALIBRATION's known gaps](CALIBRATION.md#known-gaps) have the sizes; [DEVELOPMENT](DEVELOPMENT.md#open-items) has
the code side.

- **Forza Motorsport:** the acceleration feel is one tone where HaptiConnect's is a spread-out rumble, and the road
  rumble in metres waits for it.
- **Forza Horizon:** laps play 0 to 1.3 dB quieter, very rough ground is weaker, and Horizon 5 and 6 share one
  profile although HaptiConnect treats them differently.
- **BeamNG:** Motion Sim was checked on one drive; the crash, bump and wheel-lock levels have no clean reference; and
  the rev-limiter sound is not played yet.

### Assetto Corsa EVO

- One clean single-copy recording would settle its loudness, cornering and deep slides.
- Assetto Corsa and Assetto Corsa Competizione are not tested.

### Trackmania

- The loose-surface grip limits are first guesses.
- The levels were felt before the left-channel fix (about 6 dB too strong) and are due for another check.

### Ideas saved for later

- Notice when a game is running but sending no data, and show the exact in-game setting it needs: "something that
  detects that the game is running but it doesn't get data".
- A Trackmania plugin of our own ([Trackmania has no telemetry setting](#trackmania-has-no-telemetry-setting)).

## Glossary

- **Telemetry:** the numbers a game shares about the car, such as speed, rpm, gear and g-forces.
- **Port:** a numbered mailbox on the PC that one program listens on. Two programs can't share one.
- **Shared memory:** a block of memory a game publishes under a name, for other programs to read.
- **Device ID:** how Windows names and remembers an audio output. It can change when a USB device is re-plugged.
- **Shared vs exclusive audio:** shared lets many programs play at once; exclusive locks the device to one.
- **Loopback recording:** capturing exactly what is sent to an output, digitally, with no microphone.
- **dB and dBFS:** steps of loudness. +6 dB is about twice the amplitude, and 0 dBFS is the loudest a digital signal
  can be.
- **Spectrogram:** a picture of sound: time runs left to right, pitch goes up, and brightness shows strength.
- **Limiter:** an automatic volume control that turns everything down briefly when a peak would be too loud.
- **Held-out drive:** a lap kept out of the tuning and used only to check the result.
- **Python environment:** a private copy of Python and its libraries for one app.
- **Claude's sandbox:** the protected space the Claude desktop app runs in on Windows. Some of its writes are hidden
  from the user.

## Tell us how it feels

OpenShaker was built on one rig, so real-world reports are the most useful thing you can send: how it feels on your
shaker, your amplifier and your games, what is too strong, too weak or missing, and what just feels right. Bug
reports and fixes are welcome too.

- **[Open a Hardware / feel report](https://github.com/baddo-baddo/OpenShaker/issues/new?template=hardware_feel_report.yml)**,
  or pick **Send feedback / report a bug** in the tray menu.
- More in the README's [feedback section](../README.md#built-with-ai-open-to-feedback) and in
  [Tell us how it feels](HOW_IT_WAS_TUNED.md#tell-us-how-it-feels).
- Nothing is sent automatically. If you attach a log, read it first: file paths in it can contain your Windows user
  name.
