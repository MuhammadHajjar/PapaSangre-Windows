# Papa Sangre — Windows port: status journal

Reference material: `reference/` holds the untouched extraction of
`C:\Users\Muhammad\Downloads\ps.zip`. **The archive itself is never modified.**
Recovered structure lives in `GAME_STRUCTURE.md`; the per-object checklist is
`docs/CONTENT_INVENTORY.md` (regenerate with `python tools/audit.py`).

---

## Technology decision

| Requirement | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | The game is a data-driven interpreter, not a hot loop. All per-frame work is bookkeeping over a few dozen objects; the DSP runs in native code. Python also gives the reverse-engineering and asset pipeline in one language, and makes the test suite cheap. |
| Audio | **OpenAL Soft 1.25.2** (`vendor/openal/soft_oal.dll`) via a hand-written `ctypes` binding | Matches the original's feature set almost one-for-one: HRTF binaural rendering, per-source distance attenuation, EFX reverb sends, per-source low-pass — the exact CSL graph Papa Engine built. It also accepts a **custom HRTF**, which lets the port use the original's own IRCAM 1050 data set. |
| HRTF | The original's **embedded IRCAM 1050 set**, extracted to `tools/embedded_hrtf.dat` and converted to OpenAL Soft `.mhr` with the bundled `makemhr.exe` | Maximum fidelity: the same 188-direction measured HRTF the iOS build convolved with. |
| Input / window | **pygame-ce (SDL2)** | Reliable key-down/key-up with sub-millisecond polling — needed because the whole movement system is built on the *timing* of alternating foot presses. Also gives a focusable window, which keyboard input requires. |
| Speech | **NVDA controller client** (`nvdaControllerClient64.dll`) with SAPI 5 fallback | Direct, lowest latency, no COM round-trip. Sits behind a small `speech` interface so other screen readers can be added. |
| Audio assets | **The original `.m4a` files, unmodified**, decoded at runtime with **PyAV** | Measured (see below): transcoding to Ogg Vorbis degrades the audio *and* saves no space. PyAV is a pip wheel with FFmpeg bundled, decodes the shipped AAC bit-identically at 261x realtime, and needs no external tools. |
| Distribution | PyInstaller **one-file** builds in `Run/` | Everything handed over is double-clickable: no terminal, no Python, no paths to type. Each exe carries its own `soft_oal.dll`, the generated `.mhr`, and the NVDA controller client; it speaks as it runs and waits for Enter before closing. The game itself will ship the same way, with the original `ps1/` audio tree alongside. |

### Why not the alternatives

* **NVGT** — good fit for an audiogame written from scratch, but its
  spatialisation gives far less control than the original needs (per-source
  low-pass, reverb wet/dry sends, custom HRTF, explicit distance curves), and
  the level interpreter, message bus and 27 map imports would be considerably
  more painful in AngelScript than in Python.
* **C++** — would allow compiling CSL itself, i.e. bit-exact audio. Rejected:
  there is no C/C++ toolchain on this machine, so nothing could be built or
  verified, and the maintenance burden is much higher for a codebase that is
  90% data plumbing.
* **C#** — viable, but buys nothing over Python here (the DSP is native either
  way) while costing iteration speed and asset-pipeline convenience.

---

## Architecture

```
PapaSangre/
  reference/        untouched extraction of ps.zip            (read-only)
  tools/            reverse-engineering + build tooling
      classdump.py      Objective-C class/ivar/method dumper
      psdis.py          ARM64 disassembler w/ selector+ivar resolution
      summ.py           disassembly condenser
      audit.py          content audit -> docs/CONTENT_INVENTORY.md
      embedded_hrtf.dat the original IRCAM 1050 HRTF, extracted
  vendor/           soft_oal.dll, makemhr.exe
  build/            generated: the .mhr HRTF (audio is used in place)
  papasangre/
      assets/       sexp.py (playlists), tiled.py (levels), audio loading
      core/         message bus, run loop, timing, state machine
      audio/        OpenAL binding, S3D engine equivalent, playlists
      input/        rebindable key map and controller map, foot/hand
                    interpreter
      accessibility/ speech output, menu focus model
      world/        level, room, surface, path
      entities/     player, sound agent, collectible, monster, dilemma
      dialogue/     cutscene + scripted-sequence sequencer
      menus/        hub, level select, options
      save/         progression, dilemma outcomes, skippable-sound state
  apps/             entry points that get frozen into executables
  Run/              the built .exe files, plus a plain-text README
  tests/            unit + regression tests
```

The module layout mirrors the original's class structure so that
`PGEPlayer` ↔ `player.Player`, `PGESound` ↔ `entities.SoundAgent`, and so on;
this keeps behaviour comparisons direct.

---

## Phase plan

| Phase | Content | State |
|---|---|---|
| 0 | Inspect archive, recover engine structure | **done** |
| A | Data importers (playlists, levels) + content audit | **done** |
| B | Audio asset strategy (codec trial; ship originals) | **done** |
| C | Audio engine: OpenAL binding, custom HRTF, spatial sources | **done** (reverb tuning outstanding) |
| D | Message bus + trigger runtime | **done** |
| E | Input layer + foot/BPM interpreter | **done** |
| F | Player movement, rotation, wall collision, footsteps | **done** |
| G | First playable cell: `ps1_1` "In the Dark" | **done** |
| H | Collectibles, surfaces, rooms, inactivity system | **done** (surfaces need a level that uses them to verify) |
| I | Cutscene / scripted-sequence sequencer | not started |
| J | Enemies and paths | **done** for enemies (paths outstanding) |
| K | Dilemmas | not started |
| L | Menus, hub, level select (NVDA-accessible) | not started |
| M | Save / progression | not started |
| N | Remaining 24 levels, one at a time | not started |
| O | Accessibility polish, packaging | not started |

---

## Runnable builds

`python tools/build_exes.py` freezes everything in `apps/` into `Run/`.
Current programs:

| Executable | What it does |
|---|---|
| `Listen to spatial audio.exe` | Plays real game audio around your head through the recovered HRTF, announcing each position. Judged by ear. |
| `Verify spatial audio.exe` | Renders test sounds at eight bearings and measures the interaural cues in the output. No listening required. |
| `Check game content.exe` | Parses all 27 levels and 104 playlists and verifies every reference resolves; writes `docs/CONTENT_INVENTORY.md`. |

Each is one self-contained file, speaks through NVDA as it runs, prints plain
ASCII (the console code page mangles anything else), and waits for Enter before
closing so a failure is never a window that flashes past.

---

## Progress log

### 2026-09-21 - the roar before the charge

Reported twice and dismissed once by me, which is the part worth recording.

A player wrote that a monster starting a chase does not play its opening
sound, "it just runs at you. This is not how the 2010 version did it". I
tested the case I assumed he meant - an idle hog, a trip nearby - watched
`monster_hog1_01_dry_aware` play correctly, and filed it as the player's
memory against the binary, to be asked about rather than changed.

That was the wrong case. A trip sends `AlertAllEnemies:to=position`, which is
state 4, and state 4 does roar. Being alerted **to the player** is state 2,
and state 2 in the port was one line: change to state 3. The way to find it
was to stop reasoning about which state I thought was involved and count the
reads of `awareSound` in the binary instead. There are three - 0x10001d6c8,
0x10001d958 and 0x10001da1c - and the port only played it in two places.

The missing one is state 2, and it is four things:

* an entry guard on the previous frame's state, 0x10001d94c;
* `awareSound` through `playSound:`, 0x10001d974;
* `chaseSpeed` into `setSpeed:`, 0x10001d9a0;
* `changeStateTo:3` through `performSelector:withObject:afterDelay:` with a
  delay of **1.0**, 0x10001d9dc.

So the enemy roars for a second at full chase speed before the charge proper
begins, and because state 2 never steers, it spends that second running along
whatever vector it was already facing. It only turns towards you when state 3
takes over. That last detail moved a test: `positionBeforeChasing` is where
the enemy stood when the charge began, not where it was standing when it first
heard you, because it has already been moving for a second by then.

Nine tests broke on this change and every one of them had encoded the fault -
they alerted an enemy and asserted it was chasing on the same frame. They now
assert the roar, let the second elapse, and then assert the chase, which is
what a player actually experiences.

---

### 2026-09-14 - what players found, and the hog that deleted itself

Two people played the whole game and reported. Six things between them; four
were real, and one of those four is the most consequential bug the port has
had.

**A hog that loses you goes silent and stops mattering.** Both players felt
it, one of them as "I kind of breezed through it" and the other as "it just
sits there, then resets". `-[PGEEnemy playSound:looping:]` **returns the
duration of the sound it started** - both exits read it off `duration`,
0x10001e8a4 for the early-out and 0x10001eb14 for the normal path - and state
6 passes that straight to `setDistractedTime:` at 0x10001dc20. So a searching
enemy gives up exactly as its "not there" grunt ends, and its patrol loop is
back in the same breath. The port threw the return away and kept the level's
own `distractedTime`, which meant a hog grunted for two seconds and then stood
in silence for the remaining eight - or, in ps1_15, eighty-eight. Silent and
stationary is the same thing as absent, which is why the game got easy.

Worth recording that the level data's `distractedTime` is **dead** once an
enemy has searched once: state 6 overwrites it before the comparison that
reads it, every time. Six levels carry a value (2, 5, 5, 20, 30, 90) and none
of them decides anything.

**The little girl never screamed.** Carrying her applies a proximity radius to
you (`ApplyProximityRadiusToPlayer:value=40`, the only place ps1_18 mentions
the mechanic) and every step then asks who is near. The scream itself is
`dilemma_girl_monsterprox` - **hardcoded in `alertEnemy:` at 0x10001e274 and
named in no level's data at all**. The only way to find it is to read the
enemy's alert path, or to notice a file in `ps1/` that nothing references.
`withinRadius` is an edge latch (0x10001e254 skips the scream when it is
already set, 0x10001e2b8 sets it either way), so she gives you away once per
approach rather than once per step.

**The third note of Papa Sangre Says cannot be heard, and that one is the
original's fault.** ps1_17's `note3` is the only collectible in the game with
an empty `loopSound`, and ps1_17's playlist is the only one of the five brass
levels that does not carry the d note. Every sibling level uses
`note_brass_01_dry_d_living_+5`. The player's description was precise: you
collect it by following the summoner's voice and never hear the note. Filling
it in is a change, not a recovery, and is in DIVERGENCES.md as one.

**The ice lake cage keeps ringing after you leave.** `deactivate` fires
`OnDeactivate` whether or not the agent was ever active - 0x10002049c is an
unconditional tail call - and ps1_23's `chicken_1` answers that by re-arming
the cage launcher. During a shutdown that lands behind the sweep, so the
launcher comes back to life with its alarm looping and nothing left to stop
it. The player even gave the condition: only with the chickens still caged,
because a released `chicken_1` has re-armed the launcher earlier and the sweep
then finds it the ordinary way. A first attempt at this copied the original's
`[agent setDelegate:nil]` (0x1000348d8) and broke every failure narration in
the game, which was the useful part: the delegate gates a collectible's
*collect* sound and nothing else - the only game-side read is in
`playCollectSound` - so it was never what silenced a loop. The sweep repeats
instead, and that is a port-side fix.

**Two reports where the binary disagrees with the player, left alone.** The
lost souls' listen radius is `alertDistance`, no level sets it, and both
`-[PGEDilemma init]` and the port use 100. The "don't leave me" line loops
because `-[PGEDilemma playSound:]` passes 1 to `play:` unconditionally
(0x1000457c8) and `checkCollisionsWithPlayer` has no path from abandoned back
to resting - states 8/9/10/11, and 8 is reachable only from 9. Changing either
would be inventing a switch, so both are questions rather than commits.

---

### 2026-09-13 - the shipping pass: what a player actually meets

Two days of Muhammad playing the release build and reporting what was wrong
with it. None of this is engine work; all of it is the difference between a
port that runs and one that can be handed to someone.

**The release itself.** One zip, `PapaSangre-Windows-<version>.zip`, holding
one file: `Play Papa Sangre.exe`. No README, no `.cmd` launchers (the main menu
has *Choose level*, so a folder of 26 batch files was noise), no `config/` at
all, and **none of the diagnostic tools** - `Listen to spatial audio`, `Verify
spatial audio`, `Check game content` and `Walk in the dark` are how the port
was built and checked, not part of the game. Muhammad called that second
archive the debug version, which is exactly what it was; `pack_release.py` can
no longer make one. That last one mattered twice over - the packed `alsoft.ini`
carried `hrtf-paths = C:\Users\Muhammad\...`, which would have leaked a local
path *and* silently disabled HRTF on every other machine. `alsoft.ini` is
generated into the temp directory now, and `tools/pack_release.py` refuses to
pack any text file containing a local path. The game is a `--windowed` build,
so there is no console window behind it.

**Escape.** It opens the pause menu and nothing on the keyboard quits - that is
alt+F4, or Quit in a menu. The first attempt did not work for Muhammad and the
reason is worth keeping: his `config/keys.json` already existed, and a stored
binding overrides a default, so the new escape binding never reached him.
Bindings now carry a `_version`, and a file from an older build is discarded
with the reset said out loud. `config/controller.json` does the same.

**Five requested additions.** A key-mapping screen under Options with a
restore-defaults row; a menu after each level (continue, replay, choose level,
main menu) instead of dropping straight into the next one, with **that level's
ambience still playing** underneath; the telephone door on every dilemma level,
not just the baby one; the game's own splash as a skippable intro; and the
"in this level you can walk and turn" readout removed.

Two of those were wrong first time and both failures were the same shape -
implementing what the words could mean rather than what the game does.
`deactivate` sets `sound = None`, so restarting `agent.sound` for the
level-complete ambience was restarting nothing; it has to be fetched from the
bank by name again. And "the telephone sound" meant the door's `loopSound`,
`door_telephone_living` - not narration about the outcome, which is what got
built first, and which queued a phone call on *every note* in ps1_7 so the
level could never end. The door is identified as the collectible that fires
`ShutDownLevel`.

**The chicken cage, ps1_23.** Only the first cage opened. `-[PGECollectible
deactivate]` clears `collected` (`strb wzr` at 0x10001bb04, before the call to
super) and the port's override did not, so a cage that had been triggered once
stayed latched forever. The fix needed a second field: `collected` is the
transient latch the state machine re-arms, `was_collected` the durable record
the level uses to know the cage has been opened.

**F1, F2, F3 and the nudge, removed.** Asked for, and right: the two nudge keys
turned by a fixed 15 degrees, which is the arrow keys with extra steps, and the
three F-keys spoke information (where am I, what can I do here, how fast am I
moving) that had become clutter. `turnStepDegrees` is gone from the settings
file with them.

**Controller buttons are rebindable now.** They were not - the layout was a
table inside `gamepad.py`. It lives in `papasangre/input/padmap.py`, the pad's
exact counterpart to `keymap.py`, with its own menu under Options and its own
restore-defaults row. Buttons are stored by SDL's own names - `a`, `dpleft`,
`start` - never by raw number, so a binding made on an Xbox pad still means the
bottom face button on a DualShock. The right stick is not in the list: it is
the only axis the game uses and there is nowhere to move it to.

**A bug the tests could not see.** `run_menu` called `rebind(...)`, and
`rebind` did not exist anywhere in the project - choosing any row in the key
menu would have raised `NameError`. Every test built menus and asserted on
their rows; none had ever *driven* one. There are five now that do, with a
scripted input source, and they cover both rebinding screens, cancelling, and
rebinding with no pad plugged in. While writing them, `KeyMap.save()` turned
out to always write the default path rather than the file it was loaded from,
which meant a test could overwrite the real bindings; both maps remember their
path now.

---

### 2026-09-11 - controller, menus, options

All 25 levels confirmed playable by Muhammad, so: a controller, the game's menu
structure, and an options screen.

**The level list is recovered, not invented.** `AccessibleAllLevelsViewController`
builds its table from `<AppName>_hubList.plist`, which is still in the bundle -
25 entries with `positionInMenu`, `altName`, `title` and `unlocked`. Only
`ps1_1` is unlocked in the file; everything else comes from `PGEGameProgress`.
The two spoken formats are lifted straight out of that class:
`"Play Level %i: %@"` and `"Level %i: %@; locked"`. The main menu's rows are
the ones `PGEViewController` logs, minus Cast and More Games, which are App
Store links. Even the credits line is the binary's own, *"Developped by
Somethin' Else, published by Playground"*, typo included. `ps1_1b` is correctly
absent - the original's hub list does not list it either, because ps1_1 chains
to it internally.

**The controller.** D-pad left/right are the feet, right stick turns, A
selects, B goes back, X skips, Y is "where am I", Start pauses. The feet are on
the **hat** rather than a stick deliberately: a step is a discrete press and
`footButtonReleased:` times the interval between them, so an axis cannot
express it. Both edges are reported, and rolling the d-pad from left to up
releases the foot it leaves - otherwise a foot would stick down and the
alternation rule would jam. The stick is read as a *rate* with a dead zone that
ramps from zero at its edge, so half-pushed is half speed; that is what makes
it feel like the swipe it replaces.

**Options** - volume, turning speed, turn nudge - is an addition; the original
had no options screen. Turning speed goes in `config/settings.json`, clamped to
30-400 deg/s, and applies to the arrow keys and the stick together.

**A bug this turned up.** Volume was already persisted, by
`save_master_volume`, into `config/audio.json` - the same file the outdoor
reverb setting went into earlier today. It wrote a single key over the whole
file, so changing the volume once would have silently wiped the reverb choice.
It merges now, and a test holds it there. Worth recording because it is the
second time a "new file" turned out to be an existing one: check what is
already in a config path before adding to it.

Tests: 260 (22 new).

### 2026-09-11 - levels 11 to 25: the rest of the game

Muhammad asked for the remaining fifteen levels in one go. The headline is that
**the engine needed almost nothing**: a survey of every object type, property,
trigger type and message used by ps1_11 through ps1_25 turned up exactly two
things that were not built, and one of those turned out to be a typo in the
map data.

* **`PresentAdiosVC`** - real, and now ported. Observed by
  `-[PGEViewController viewDidLoad]`, which presents `PGEAdiosViewController`
  and calls `playMenuAtmos`: the goodbye screen. Only ps1_25 sends it, from
  **both** of its doors. There are no view controllers here, so what it means
  is "there is no next level, the game is over" - `Level.game_complete`,
  surfaced through `Game.game_complete`, and `play.py` now says *You have
  finished Papa Sangre* instead of looking for a level 26.
* **`AlertAllAgents`** - not real. `PGE_MESSAGE_AlertAllAgents` appears
  **zero** times in the binary; only `AlertAllEnemies` exists. ps1_19 uses it
  on two surfaces, so those two triggers do nothing at all. Reproduced.

#### The autoplay harness, and what it taught me

`tools/autoplay.py` walks a level's collectible chain automatically. Getting it
to work was more instructive than the levels:

1. It gave up the frame after collecting something, because the next link is
   activated by an enqueued `OnCollide` and there is always a gap.
2. It kept dying on ps1_12 until I paced it properly. `updateBPMCounter` keeps
   five stamps and divides by the *count* rather than the interval count, so a
   steady tempo reads as **75/interval** BPM. ps1_11 caps you at 65, which is
   better than a second between steps. Walking fast on quick ground and then
   stepping onto slow ground trips you - `checkStepBPM` tests the tempo you
   *arrive* with against the new surface - and a trip alerts every enemy in the
   level. That is the mechanic, not a bug: the bot had to learn to slow down
   before crossing, exactly as a player must.
3. It could never finish ps1_16, because its door sits **exactly on the level
   boundary** and the harness had a keep-off-the-walls rule. My bug, not the
   game's.

It now runs in two modes. `--peaceful` deactivates the hunters and checks the
level's *structure* - chain, doors, exit, successor. That is the honest test:
whether a bot can out-manoeuvre a hog that runs at 30 px/s when the player
manages about 22 is not a statement about the port. The hunters have their own
per-level tests.

**Result: every level from ps1_2 to ps1_25 completes and hands on to exactly
the level it should, ending in GAME COMPLETE.** ps1_1 and ps1_1b have no
collectible chain to walk (ps1_1b has no `Collectible` at all - it is the
turn-to-the-voice trainer), and are covered by their own file.

#### Six more mistakes in the shipped data

The back half of the game is where the map data gets sloppy. All six
reproduced, each with a test that names it:

| level | what |
|---|---|
| ps1_11 | two quicksand edges carry the same `OnEnter`; one says `PlaySound:soundName=...` and the other is just the bare sound list, so one edge warns you and the other is silent |
| ps1_19 | `AlertAllAgents:to=position` on two surfaces - a message that does not exist |
| ps1_21 | `ChangeInactivitySoundList_soundList=` - underscore where a colon belongs |
| ps1_24 | `ChangeInactivitySoundList=soundList=` on note1 - equals where a colon belongs; note2 carries both a correct message and a bare sound name |
| ps1_25 | the intro activates `note1`, which the level does not have |

Writing those tests caught two wrong assumptions of my own: I assumed ps1_11's
malformed edge was the only one (there are two edges, and the other is fine),
and that ps1_24's note2 was broken (it carries a *correct* message as well, so
it works).

#### The dilemmas, finished

All four now exercised. The baby (ps1_7) wakes the enemies, the old man
(ps1_12) and the siren (ps1_23) each cost 50 BPM off your top speed, and the
girl (ps1_18) puts a 40 px radius on you that enemies can hear. Three levels
ask the tree - ps1_7 one deep, ps1_12 two, ps1_18 three - which is 2 + 4 + 8 =
**fourteen** recorded endings, and a test asserts every one of them exists.

The siren is the odd one out: `dilemma_4` is written to the save file and then
**nothing ever reads it**. ps1_23's own door plays a fixed `FINAL_IceLake_Win`
and ps1_25's two endings are fixed as well. That is why the tree stops at three.

Tests: 238 (20 new). Launchers for all 25 levels.

### 2026-09-11 - level 10, Home Run

ps1_9 again with the difficulty moved from speed to arithmetic: two reapers
instead of one and five notes instead of two, with both hunters much slower to
compensate - 3.6 and 2.5 px/s against the 8.3 of the single one. They have a
voice each, which is the only way to tell them apart, and each still uses its
one sound for all four states. The Room is again the only ground. No new engine
code; third level in a row.

The interesting part is that the shipped map data carries **two mistakes**, and
both are now reproduced with a test naming them:

* **note3's `OnCollide` is spelt `ChangeInactivitySoundlist`** - lowercase L.
  Nothing observes that message, so of the five notes, the third is the only
  one that does not reorder the nagging. It is the sole occurrence of that
  spelling in all 27 maps. Writing the test turned up a trap of my own: note4
  asks for the *same* order note2 did, so "did the list change" is not a valid
  check - the test compares against what each note actually asked for.
* **the intro activates `atmos_crickets_01`, which ps1_10 does not have.** Its
  intro was copied from ps1_9's, which did. The crickets are simply never heard
  here, and the rest of the chain has to keep running regardless.

The intro also contains a stray empty message (`...name=note1||Activate...`),
harmless but it has to be tolerated. All three were already being reported by
`tools/audit.py`, which is the first time that sweep has pre-empted a level
rather than confirmed it afterwards.

Tests: 218 (9 new).

### 2026-09-11 - level 9, The Grin Reaper

Second level in a row that needed no new engine code. `ChangeInactivitySoundList`
and `AlertAllEnemies:to=player` from a sound's `OnSoundEnd` were both already
built; everything else it uses is older still.

It is the simplest level in the game and the first genuinely frightening one.
One room, two notes, a door, and the reaper - which the **intro** sets on you:
`FINAL_GrinReaper_Intro`'s `OnSoundEnd` ends `AlertAllEnemies:to=player`, the
branch that goes straight to `CHASE_PLAYER`. Nothing in the level ever calls it
off, so from the moment the narration stops it is walking at you.

Two design details worth recording, because both depend on engine behaviour
recovered earlier:

* **The reaper has one voice.** `defaultSound`, `awareSound`, `chaseSound` and
  `notThereSound` are all `monster_reaper1_01_dry_chase`. `playSound:` guards
  on the name alone, so no state change can interrupt it: the reaper is a
  single unbroken tone that only ever moves. Had the name guard been wrong -
  which it was, twice, before the ps1_7 work - this level would stutter
  continuously. A test walks 60 steps and asserts the voice starts exactly once.
* **It is slower than you.** 8.3 px/s against roughly 22 at a normal walking
  tempo. The level is winnable but only by never standing still; the test walks
  it with a simple "head for the next thing, bend away from the reaper when it
  is within 70 px" rule and gets out in about 40 seconds.

It is also the **first level with no `Surface` objects at all** - the Room is
the only ground in it. That works only because `PGELevel` is a `PGESurface`,
the fix from 2026-09-09; without it ps1_9 would have no footstep sound.

The three inactivity lines are reordered by each note's `OnCollide`
(`ChangeInactivitySoundList`), so being nagged twice never sounds like a
repeat. Verified the list rotates and that standing still cycles all three and
wraps.

Tests: 209 (9 new).

### 2026-09-11 - the reverb question: one room for the whole game

Muhammad asked why an island sounds like a small room, and whether outdoor
levels could be dry - "or is this how it is in the real game?" It is how the
real game is, and checking it turned up a bug of mine.

**There is exactly one reverb in Papa Sangre and nothing ever changes it.**
No playlist declares a reverb field (the only sexp keys in the whole set are
name, path, extension, bundle, sound, spatialized, unloadonstop, playlist,
repeat, preload). No level property names one - there is not a single string
literal containing "reverb" in the binary. The three parameters have exactly
two writers, both of them `init`:

| | roomSize | volume | dampening |
|---|---|---|---|
| `-[S3DEngine init]` | 1.5 | 1.0 | 50 |
| `-[PGEngine init]` | 2.1 | 1.0 | 5 |

`PGEngine` is the game engine singleton (`+[PGEngine sharedGameEngine]`), it
runs second, and it wins. **The port was using the first row.** Fixed.

The setters clamp, and the clamps are worth recording because they make the
authored numbers slightly beside the point: `setReverbRoomSize:` clamps to
**[2.2, 2.3]**, so 2.1 comes back *up* to 2.2 and S3DEngine's 1.5 could never
have applied even if it had been last. Dampening clamps to [0, 100], volume to
[0, 8]. All three return early when `[self reverb]` is nil, which is how
`disableReverb` works - and that is called from `-[PGEngine init]` behind a
hardware test logging "Disabling reverb for Papa Engine - because hardware is
less than 4th Gen". On anything this port runs on, reverb is on.

So the island was reverberated exactly like the cellar on an iPhone too. What
the correction does is make it *more* reverberant, not less: EFX decay goes
1.5 s to 2.2 s and gainHF 0.5 to 0.95 (much brighter). That is the faithful
direction even though it is the opposite of the complaint.

What remains genuinely open is the **mapping**, which has always been flagged
port-side: csl::Stereoverb and EFX reverb are different models, and treating
`roomSize` as a decay time in seconds is a guess. The [2.2, 2.3] clamp is a
suspiciously narrow band for a time in seconds, which suggests the unit is
something else.

**Asked, and answered: he wants the outdoor reverb anyway.** "Leave reverb
settings as they are, but for outdoor make a custom reverb, and if not doable
then no reverb for outdoors." So indoor levels keep the original's setting
untouched and the open-air ones get an added profile. This is the port's only
deliberate change to how the game *sounds*, and it is written up in
DIVERGENCES.md §4c, under a new **REQUESTED** verdict so it is never confused
with something I decided on my own.

Three things worth recording about the implementation:

* **Classification comes from the ground, not a list of level names.** Every
  `footstepsPrefix` in all 27 maps splits cleanly into outdoor materials
  (reeds, sand, water, cornfield, quicksand, hillclimb, snow, ice, field,
  stonepath) and indoor ones (stone, kennel, bone, guts, metal, wood, marble,
  broken glass, hot water). A level counts as outdoors only when *every*
  ground it names is outdoor, so one wooden floor makes it a building. That
  yields ps1_8-12, 19, 20, 22, 23 and 25 - which is exactly the game's three
  outdoor chapters, arrived at without naming any of them. A test asserts the
  set and that nothing is left unclassified.
* **The profile is `config/audio.json`**, so `outdoor` / `dry` / `indoor` can
  be switched without a rebuild. `indoor` reverts the whole feature.
* **Verified by measurement, not by the call returning True.** Rendering the
  same sound through the loopback device and integrating everything after the
  direct sound has finished: outdoor's tail is 6.6% of indoor's, dry's is 4%.
  That check is in the suite.

### 2026-09-10 - level 8, The Island

The first level that needed **no new engine code at all**. Everything ps1_8
asks for was already built: `multipleOnEnter`, `ChangeInactivityTime`, the `&`
or-list in `soundName`, `DisableHands`, `startAngle`, the nested-surface depth
search. It loaded and played end to end on the first try, which is the first
time that has happened.

The island is six rectangles nested inside one another, each smaller and
wetter than the last - stonepath, reeds, reeds-waterB, waterswim, sand-waterB,
sand - with the level itself as the outermost at z 1. Walking in takes you
through all six in order and the footstep sound is the only depth gauge there
is. `foot_waterswim` at z 4 is *not* swimming: nothing in ps1_8 enables it
(there are still zero uses of `EnableSwim` anywhere), it is just the sound set
for wading through the deep part.

Two mechanics got their first real exercise:

* **`multipleOnEnter`** clears the `entered` latch that otherwise makes
  `OnEnter` fire once in the life of a level. The three stone strips along the
  island's edges set it, so their birds call on every crossing - they are
  boundary markers and would be useless once-only. Verified against the reed
  bank next to them, which does not set the flag and speaks exactly once no
  matter how many times you wade in. Note the flag governs `OnExit` too.
* **`ChangeInactivityTime:value=18`** from the intro's `OnSoundEnd`. The nag
  itself is the Room's `inactivitySounds`.

Two pieces of dead content in the original data, both reproduced: a sound agent
called `FINAL_theisland_inactive_18sec` that nothing ever activates *and* that
the level playlist does not declare, and the usual `ToolBar` layer.

One trap while testing: the southern stone strip overlaps the reed bank and
both sit at z 2, so a point inside both is ambiguous - the depth search keeps
the first z it meets and `>` never replaces an equal. Test points for the strip
have to be clear of the reeds.

Tests: 193 (11 new).

### 2026-09-10 (later still) - the guts bug, and the offset-register trap

Muhammad reported the hog restarting its roar on every step on the guts again,
after I had told him the original does the same and offered to leave it. He was
right and my proof was wrong, in a way worth writing down.

I had searched for writers of `hasWantedPosition` and found none — one read at
0x10001d2d0, one `strb wzr` clearing it in state 6 — and concluded the flag was
dead and its `if` never fired. It is set, at **0x10001dbb4**:

```
0x10001d2d0   ldrsw x22, [x8, #0x29c]     ; x22 = offsetof(hasWantedPosition) = 200
...                                        ; ~2300 bytes of state 4
0x10001dbb0   mov   w8, #1
0x10001dbb4   strb  w8, [x19, x22]        ; hasWantedPosition = YES
```

The compiler cached the ivar offset in `x22` at the top of the state and reused
it at the bottom, so the store references no symbol and carries no `IVAR`
comment. **Grepping for the ivar name cannot find a store like that.** The only
way to catch it is to enumerate the `strb`/`str` instructions in the function
and resolve each offset register back to where it was loaded.

With the latch understood, state 4 reads completely differently:

* **first** alert — `hasWantedPosition` is NO: play `awareSound`, aim at the
  player, schedule `changeStateTo:5` a second out;
* **every alert after that** — the flag is YES: `findDirectionToPlayer`,
  `changeStateTo:5` **immediately, and no sound at all**.

That silent re-aim is the whole answer. ps1_7's guts alert on every step, and
every one of those after the first re-aims the hog without touching its voice;
state 5 then asks for `chaseSound` again on a name it is already playing, which
`playSound:` refuses. One snarl, one roar, and then it just hunts you. State 6
clears the latch when it gives up, so the next disturbance snarls again.

Two smaller things fell out of the same read: state 5 has **no** entry guard —
it asks for `chaseSound` and `chaseSpeed` every frame (0x10001d338), which is
what makes the re-aim inaudible — and the `afterDelay:1.0` in state 4 never
elapses, because the latch pulls the state over on the very next frame. Dead
code, reproduced as dead code.

Re-checking the trip sound with the same suspicion turned up a second real bug
and corrected a claim I had made the day before. I had written that **no**
surface in any level names a `tripSound`. Four levels do — ps1_2 (on the Room),
ps1_3's four kennel rings, ps1_11 and ps1_12 — so that path is live, and my
`trip()` was calling `anySoundContaining:` for it when the original calls
`S3DSound:`, an exact lookup. Fixed. ps1_7 genuinely names none, so the coin
flip there is an authoring gap in its map data rather than dead engine code;
DIVERGENCES.md 4b now says so and lays out the two possible fixes.

Tests: 181. A new one walks a dozen steps across a guts patch at 60 fps and
asserts the chase sound starts exactly once.

### 2026-09-10 (later) - three bugs from playing ps1_7

Muhammad reported three things: the wrong ground's trip sound, the hog
restarting its roar on every step on the guts, and the baby playing once
instead of looping. Two were mine. One is the original's.

**The baby.** `-[PGEDilemma playSound:]` ends with `SEL "play:"` and
`mov w2, #1` at 0x1000457c8. `play:` takes a **looping** flag — the same one
`-[PGECollectible startLoop]` passes, and the opposite of the `mov w2, #0` that
`playerDidCollideAWall:` uses for the one-shot `hitwall`. My port never set it.
One line. Every dilemma voice — the baby, the old man, the girl, the siren —
now calls until its state changes.

**The hog.** This one went deep, and it turned up three separate inventions of
mine sitting on top of each other.

`alertEnemy:`'s `to=position` branch is gated on `distractedTimer != -1`
(0x10001e428): a hog that is already standing over a noise ignores every new
one. My port instead sent it to state 12 in that case, which plays `awareSound`
and re-schedules `changeStateTo:5`. Since ps1_7's guts fire
`AlertAllEnemies:to=position` on *every* step, that detour re-triggered the
whole aware→chase pair under your feet, continuously. The original does nothing
at all on that branch.

Reading further out from there, three more:

* Only the `agent` branch reads the notification's `position`. `player` and
  `position` both jump straight to the release at 0x10001e5a4. My port was
  setting `wantedPosition` from the trigger's own position — which is the
  *surface's* origin, not yours.
* State 4 was a no-op in my port because it tested `hasWantedPosition`. I first
  concluded nothing ever sets that flag — see the correction in the next entry,
  which is where the actual guts bug was. What state 4 does on the *first*
  alert is the `else` at 0x10001da18: play `awareSound`, set
  `wantedPosition = playerPosition` (0x10001dabc, ivar 40 — confirmed against
  the raw `__objc_ivar` table), `findDirectionToPlayer`, and schedule
  `changeStateTo:5` with `afterDelay:1.0`.
* State 12 sets `shouldAttackOnWantedPosition = YES` (0x10001d798), which is
  what makes states 5 and 6 refuse every later alert (0x10001e140). State 4
  clears it. Neither was ported.
* State 6's expiry goes to state **1** on both branches (0x10001dd18), one of
  them resuming the patrol; my port went to `RETURNING`. The comparison is a
  strict `>`, and `distractedTime <= 0` means it never gives up at all.

Jump table re-derived from scratch to check all of this: index *i* at
0x10001de40 is state *i+1*, which puts the four states `PGEDilemma` borrows
(8-11) exactly on the four table entries that fall through to the tail.

**The trip sound is the original's own bug, and I have left it alone.**
`-[PGEPlayer trip:]` computes `footstepsPrefix ?: @"foot_racetrack"` at
0x100027480, retains it, and releases it at 0x10002777c without ever reading
it. `-[PGEPlayer shuffle]` does the same thing and finishes the job with
`stringWithFormat:@"%@_shuffle"`; there is no `@"%@_trip"` in the binary at
all. So `trip:` falls to `anySoundContaining:@"trip"`, which picks with
`arc4random` (0x1000d331c). `tripSound` has exactly one writer in the whole
binary — `playerMovedToPosition:` at 0x100032648, copying it off the surface —
and **no surface in any level sets one**. On ps1_7, whose playlist flattens in
both `_footsteps_stone` and `_footsteps_guts`, that is a coin flip on every
fall. Recorded in DIVERGENCES.md §4b, not silently corrected.

Same verdict for the tail of the hog problem: while the hog is *walking* to a
noise, the original does re-alert it every step. The guard only covers the
standing-still phase. Also §4b, also his call.

Tests: 180, all passing. Three of my own had to be rewritten — they had been
asserting the invented behaviour.

### 2026-09-10 - dilemmas, and level 7

The last unbuilt subsystem. Four dilemmas exist across the game - the baby in
ps1_7, the old man in ps1_12, the girl in ps1_18, the siren in ps1_23 - and
each is a person lying in the dark asking to be carried out.

**`PGEDilemma`** is a `PGEGameAgent` that drives the **same `state` ivar the
enemies use**, on the four values their jump table leaves unused:

| state | meaning | sound |
|---|---|---|
| 10 | resting | `restSound`, looping |
| 9 | you came within `alertDistance` | `alertSound` |
| 8 | you were near and then left | `abandonSound` |
| 11 | you picked them up | `thanksSound`, and it is final |

`activate` sets 10. `checkCollisionsWithPlayer` returns immediately at 11, and
otherwise compares the squared distance with `alertDistance` (default **100**,
from `setAlertDistance:` at 0x100045240): inside sets 9, outside sets 8 **only
if it was already 9** - so someone you never went near never cries after you.
`collidesWithPlayer` sets `collected` and state 11.

**`solveDillemas`** is two passes. Every Dilemma in *this* level writes its
`collected` flag into saved progress under its own id, and the highest
`dilemma_<n>` present is remembered; then the name is built as
`dilemmaOutcome` plus one `_0`/`_1` for each dilemma from 1 to that number,
read back out of progress. So ps1_7 asks about one choice, ps1_12 about two and
ps1_18 about three, with the earlier answers coming from levels played before.
Hence exactly fourteen endings: 2 + 4 + 8. All fourteen are shipped assets and a
test asserts every branch resolves to one.

The exit's `collectSound` is the literal string `dilemmaOutcome`, swapped for
the real ending at the moment you touch the door.

**`bpmMalus`** is in the class and in ps1_7's data (50), but **nothing in the
binary reads it** - only its getter and setter exist. Dead data from an earlier
design. The price of the baby is its `OnCollide`: `AlertAllEnemies:to=player`,
so carrying it sets the hog on you for the rest of the level.

**Level 7, The Charnel House**, needed nothing else. Worth recording: the file
carries a **copy of level 2's objects in an invisible `ToolBar` layer**,
including a second `note1` and `note2` that would answer the level's own
`ActivateAgentWithName` messages. Both the original and the port skip that
layer by name, and a test now pins it. Its floor is three patches of guts, each
sitting inside a ring of stone that warns you before you step in the loud part.

`tools/coverage.py`: **124 of 124**. The only subsystem still unbuilt is the
menu/hub layer. 12 tests for the level, 177 in total.


### 2026-09-10 - level 6, Bedtime, and the first real chase

Nothing new had to be built; the interest is in which code path it finally
reaches. Every earlier level either leaves its hog asleep (ps1_3) or alerts it
to a **place** (ps1_4, `to=position`), which sends it to investigate a noise
and go home. ps1_6's bone strip fires ``AlertAllEnemies:to=player``, and that
is the branch that goes 2 -> 3, ``CHASE_PLAYER``. So this is the first level in
the game where something actually runs at you, and the first to exercise those
two states outside a unit test.

It is also the first level with **two** monsters, and they are not copies:
hog1 walks at 50.8 and chases at 33.3 with the `hog1` sound set, hog2 walks at
5 and chases at 26.6 with `hog2`. Both wake together.

The layout is a nice piece of design: the two notes sit west with hog1 asleep
squarely between them - the straight line from one to the other passes exactly
`collideRadius` from it, so you have to go round - and the exit is behind a
150 px strip of bones down the east wall that cannot be avoided.

Verified end to end: the hogs stay idle while you take the notes, both flip to
``CHASE_PLAYER`` at their chase speeds with their own chase sounds the moment
you touch the bones, the chase closes ground while you stand still, the note
chain runs through to `ps1_7`, and being caught reloads the level.

8 tests for the level, 165 in total.


### 2026-09-10 - the room is the floor

Reported: tripping stopped working again, and it should work in every level
without exception. Both halves of that were right, and the second half is what
pointed at the answer.

I had the trip threshold arriving from a **Surface**, and levels with no
Surface objects - ps1_1, ps1_5, ps1_9 among them - therefore never handed the
player one. The missing piece is a single instruction:

    0x10003231c  mov  x24, x23        ; best floor = self

`-[PGELevel playerMovedToPosition:]` begins its search **with the level itself
as the current best floor**, because `PGELevel` is a `PGESurface`. A Surface
only takes over by containing the player at a higher `z`. There is no
"standing on nothing" case at all: off every surface you are standing on the
room, and the room carries the same loader default of `tripBPM` 280.

That also explains three things I had been treating separately:

* why `createObjectFromDict:` defaults `tripBPM`/`runBPM` in the **Room**
  branch as well as the Surface branch - the room needs them because it *is* a
  floor;
* why `footstepsPrefix` is seeded from `self` before the loop - it is just the
  starting floor's prefix, like every other property;
* why `PGESurface` bothers to latch `entered`. Standing off every surface makes
  the level the current floor, so `triggerOnEnter` is called on the **room** -
  and the room's `OnEnter` is `DisableWalk|DisableRotation`. Without the latch
  a single step off a surface would lock the controls mid-level.

Fixed properly: `Level` now subclasses `Surface`, inheriting rect, z,
surfaceId, the entered/exited latches and the five floor properties, and
`_on_player_moved` runs one path with `best = self`. `start()` fires the room's
`OnEnter` through `trigger_on_enter()` so the latch is set.

Verified across ps1_1, ps1_2, ps1_3, ps1_4, ps1_5, ps1_6, ps1_9 and ps1_11:
every one hands the player 280 on the first step and trips on a fast run.
ps1_1b is the only exception and correctly so - it never enables walking.

Two of my own level 3 tests had been passing for the wrong reason and asserted
the wrong model; both rewritten. 157 tests.

**The lesson, third time in this shape**: I read where the surface loop
*finished* and not where it *started*. `updateFeetView:`, `createObjectFromDict:`,
and now this one instruction before the loop.


### 2026-09-09 - level 5, Hog Patrol, and the patrol-route system

The last unbuilt subsystem in the engine. A single path runs down the middle of
ps1_5's room and the hog walks it end to end for ever; you have to time your
crossing. Its own `OnLoad` says `FollowPathWithName:name=path1`, so without the
route system the level has no obstacle at all.

**Recovered and built**, five methods and a level list:

* `-[PGELevel pathWithName:]` - looks a route up in `pathArray`.
* `-[PGEGameAgent followPathWithName:]` - addressed by **senderName**, not by a
  `name` parameter; `name` carries the *path's* name. It forces `state = 1` and
  takes the first point immediately.
* `findNextPatrolPoint` - aims `orientationVector` at `path[pathCurrentPoint]`,
  records the squared distance, advances the index, and on running off the end
  fires `OnPathEnd` and **wraps to 0**, so a route is a loop.
  It returns immediately unless the agent is **idle**, which is how an alerted
  enemy abandons its patrol and picks it up again once it settles.
* The `hasPath` tail of `-[PGEGameAgent update:]` - arrival is the same
  "stopped getting closer" test the enemy uses for a goal.
* `stopFollowingPath:` - sets state 0, drops the path and zeroes the
  orientation vector. Notably it does **not** clear `hasPath`.

Path points come out of Tiled relative to their object; the world transform is
the same one every other position gets, Y negation included. The port's loader
already did that correctly.

**Three bugs the level exposed**, all the same shape - reading a state's entry
work without checking what it does *not* do:

1. **IDLE was overwriting the authored patrol speed.** The port's state 1 did
   `speed = walkingSpeed`. The original's IDLE touches only the sound;
   `walkingSpeed -> setSpeed:` appears exactly **once** in the whole update, in
   state 13. ps1_5's hog is authored at 36.6 and was patrolling at 10.
2. **State 6 did not stop the enemy.** `setSpeed:0` at 0x10001d4d4 is what
   holds a searching enemy still.
3. **`_steer_towards` zeroed the orientation vector on arrival** - my
   invention. Nothing in the original clears it; the states that need an enemy
   to stand still drop `speed` instead. Zeroing it stranded a patrol, because
   the route only re-aims once the enemy has drifted far enough from its stale
   target for the distance test to trip.

Also corrected: the port's `speed` property setter mirrored its value into
`walking_speed`. The original applies level properties by KVC, which sets
`speed` alone.

`tools/coverage.py` now reports **124 of 124**. Every method on every ported
class has been read and reconciled. What is left is not unread code but one
unbuilt subsystem - `solveDillemas` (phase K) - and the menu layer (phase L).

9 tests for the level, 157 in total.

### 2026-09-09 - the exit beacon, turned down

Reported as too loud. Chased it properly rather than reaching for a multiplier.

`csl::DistanceSimulator` is the original's attenuator and **its methods are
stripped** - only the STL containers that hold it survive as symbols - so its
curve is not recoverable. What *is* measurable:

* No playlist declares a gain, and neither `startLoop` nor `playIntroSound`
  sets one, so a beacon plays at 1.0 in the original too.
* `reference_distance` was 1.0, which with `distanceScale` 0.008 meant
  **nothing within 125 px attenuated at all**. Every spatialised source sat
  pinned at full gain across most of a room.
* Measured across the ps1_1-4 playlists, this game masters nearly everything
  near full scale - doors -0.8 dBFS, monsters -1.6, narration -3.9 - while
  footsteps sit at -15.8 and are then played at gain 0.5. So the beacon is not
  an outlier in level; it is the only sound at that level that plays
  **continuously**.

Two port-side changes, both documented as such: reference distance 1.0 -> 0.5,
and a named `COLLECTIBLE_LOOP_GAIN` trimming the homing loop ~4 dB. Every
recovered per-sound gain is untouched. Measured on an approach in ps1_2: 4-7 dB
quieter through the mid-field, worst peak -1.5 -> -3.8 dBFS.


### 2026-09-09 - level 4, Bed of Bones

The first level in the game where an enemy actually hunts you. Levels 1-3 never
send an alert; here the **floor** does it. A band of bones lies across the room
between the player and the notes, and its surfaces carry
``OnEnter``/``OnStep`` triggers that fire ``AlertAllEnemies:to=position``. The
level is therefore the first thing to exercise the alerted half of
``-[PGEEnemy update:]`` - states 5, 6 and 13 - which had been implemented from
the disassembly since the level 3 milestone but never once run.

Verified as a whole cycle: the hog walks to where it heard you
(``GO_TO_POSITION``, playing ``chaseSound``), searches there for
``distractedTime`` - 10 s by the recovered default - then heads home
(``RETURNING``) and settles back to ``IDLE``. No chasing: nothing in ps1_4 ever
sends ``to=player``, so the hog investigates noises rather than pursuing you.

Nothing new had to be built. Every object type, message and trigger the level
uses was already in place, all 60 playlist sounds resolve, and both footstep
banks (``foot_stone`` and ``foot_bone``) have their shuffle and trip variants.
The only wrinkle in the data is a **doubled pipe** in four of the triggers
(``PlaySound:...||AlertAllEnemies:to=position``); the port's parser drops the
empty statement between them and both halves fire, which is what the counts
confirm.

Two details worth recording. The hog carries its own ``speed`` of 21.6 and
``chaseSpeed`` of 36.6 from the level data, the first monster to override the
``PGEEnemy`` init defaults. And because ``positionBeforeChasing`` is only
written by states 3 and 12, a hog alerted to a *position* returns to the world
origin rather than to where it started - reproduced deliberately, and here that
lands it in the middle of the room.

7 tests for the level, 148 in total.


### 2026-09-08 - the hog kept growling while it ate you

The freeze was gone but the grunt was not: the hog stayed audible beside the
player right through the failure narration. Two more misreadings in the same
state machine.

**State 7 (ATTACK), read properly this time.** The block has *no entry guard* -
it runs every frame - and it does three things in order:

```objc
[self setSpeed:0];
if (self.sound) [self.sound stop];        // UNCONDITIONAL
if (self.attackSound) [self playSound: self.attackSound];
chasingTime += dt;
```

The port had the stop inside `if attack_sound:`, so a monster with no
`attackSound` - which is every monster in the game bar one in ps1_23 - never
stopped its loop at all.

**And `playSound:looping:` guards on the name alone** (0x10001e878). It does
*not* check whether the sound is still playing; the port added that condition.
It matters exactly here: state 7 stops the sound every frame, and the name-only
guard then refuses to restart it, so an attack sound gets a single frame and
the enemy is silent from then on. With the port's extra `playing` check it
would have restarted every frame instead. The silence is the design - the thing
that has just eaten you should not still be chewing in your ear.

Also confirmed while reading: `playSound:` (one argument) is
`playSound:looping:YES`, not NO.

Verified on the loopback renderer: grunting before the catch, silent from the
frame it lands, still silent five seconds into dying, and the hog stays
*active* throughout - it is the sender, so `shutDownLevel:` spares it. Silent
but active is the correct state.


### 2026-09-08 - the kennel freeze

Reported: the game freezes when the hog catches you, and sometimes the hog's
grunt sticks even after it has eaten you. One cause behind both.

`PGEGameAgent` has **no "already triggered" latch** on collision - it fires
`OnCollide` every single frame the player is inside `collideRadius`. The latch
lives on the subclass, and I had aliased `-[PGEEnemy collidesWithPlayer]` away
as "inherited" instead of reading it:

```objc
- (void)collidesWithPlayer {
    if (self.state == 7) return;     // ATTACK: it already has you
    [self setSpeed:0];               // also stops update: re-checking, since
    [self changeStateTo:7];          //   that path is gated on speed > 0
    [super collidesWithPlayer];      // fires OnCollide, exactly once
}
```

Without it, ps1_3's hog re-fired its `OnCollide` -
`ShutDownLevel|ActivateAgentWithName:name=FINAL_Kennel_Fail` - every frame.
`shutDownLevel:` deactivates every agent **except the sender**, so each repeat
switched the failure narration off again one frame after the previous repeat
switched it on. It never reached its `OnSoundEnd`, so `LoadLevelWithName` never
fired and the level never reloaded; and the hog, being the sender, was the one
agent left running, looping its grunt. Soft lock with a stuck hog - exactly the
two symptoms.

Verified end to end on the loopback renderer, which advances the audio clock in
lockstep with the game clock (a plain headless run cannot test this: simulated
time outruns real playback, so a 16.7 s narration never finishes). After the
fix: one `ShutDownLevel`, the hog latches to `attacking` at speed 0, the
narration plays out, `history` becomes `['ps1_3', 'ps1_3']`, and the grunt
stops.

A reminder that `tools/coverage.py` saying "implemented" only means a name
exists. `collidesWithPlayer` was in my ELSEWHERE table pointing at the base
class - which was true, and still hid a real override.


### 2026-09-08 (late) - falling, found at last

The player kept saying running too fast should drop you and it did not. I said
four times that the data disagreed. **He was right and I was wrong**, and the
reason is worth writing down.

I read `-[PGEPlayer init]`, saw `tripBPM = 10000.0`, verified it in the raw
bytes, checked that no level sets `tripBPM` before ps1_11, and concluded the
mechanic was off. Every one of those facts is true. The mistake was stopping
there: **the loader overrides the init default.**

`-[PGELevel createObjectFromDict:]` reads `tripBPM` from the object's
dictionary, and *when the key is absent* calls `setTripBPM:` with a constant -
`0x100141d24` = **280.0**. The same branch defaults `runBPM` to
`0x100141d1c` = **180.0**. There are two such sites, one in the Room branch and
one in the Surface branch.

So the chain is: every Surface is born with `tripBPM` 280, and
`playerMovedToPosition:` copies a surface's value onto the player when you
stand on it. You carry the unreachable 10000 until your first surface, and 280
for the rest of the level - and because nothing restores the value when you
step off (the faithful behaviour restored earlier the same day), it stays.

That also explains the shape of what he described: ps1_1 has **no Surface
objects at all**, so level 1 genuinely cannot trip you, but every level from
ps1_2 on can, the moment you touch a floor patch. And it explains why the
designers shipped a `_trip` sound for all 46 footstep prefixes.

Fixed by giving `Surface` and the level's own surface fields the loader's
defaults rather than zero. Verified in ps1_3: the player picks up 280 on the
first kennel ring and goes down while running.
`tools/record_gameplay.py ps1_3 --trip` now records a natural fall with no
constraint applied. Two regression tests: one that running on the rings trips
you, and one that ps1_1 - having no surfaces - still cannot.

**The lesson, again**: a default in `init` is not the value the object runs
with. I checked where the field was *declared* and not where it was *assigned*.
The same class of mistake as reading `footButtonReleased:` without
`updateFeetView:`.


### 2026-09-08 (night) - the audit is finished

Every class the port claims to implement has now been read against the binary.
`tools/coverage.py` reports **119 of 124** behaviour methods implemented, and
the five that are not are exactly the patrol-path system (phase J, ps1_5).

**Two classes I had never opened**, both found by chasing the trip question:

* **`PGEPlayerListener`** - the level owns one; it turns `PlayerStartsToRun`,
  `PlayerDidTrip` and `PlayerDidCollideAWall` into `OnStartToRun`, `OnTrip`,
  `OnWallCollide` and `OnDeath` triggers. No level defines any of those four
  trigger types, so it has nothing to fire. N/A, recorded.
* **`PGEngine`** - the top-level object the port's `Game` stands in for.
  `loadLevelWithName:` special-cases the names `win` and `lose`, and *that* is
  where `playerDidCompleteLevel:` and `playerDidUnlockLevel:` are called. But
  every `LoadLevelWithName` in all 27 levels names a real level, so the win/lose
  path belongs to the menu layer. Progression is recorded there, not during play.

**`PGEGameProgress` built.** A singleton over `NSUserDefaults` in the original;
here a JSON file next to the executable, keeping the original's key names
including its oddities - `lastPLaylist` with the capital L, and `<level>_locked`
which is set **true to mean unlocked**. `lastLevelUnlocked` is written only on
a level's first unlock, so replaying an early level does not wind progress back.
`isLevelCompleted:` has no entry in `__objc_selrefs` at all - nothing in the
binary calls it - but the port implements it since its companion write is used.

**`pause` / `resume` built** on `PGEGameAgent`, `PGEPlayer` and `PGELevel`.
`soundWasPaused` means resume only restarts what the pause actually stopped.
Bound to **P**; the original used a triple-tap, and escape already quits.

**Resolved as N/A with evidence**: `startAlarm:` and `PGEAlarm` (no level sends
it), `sendActivityChangedMessage` (observed by nothing, like `AgentDidMove`),
`PGEForgetfulMan`, `PGEActionSurface`, `Summoner`, `Position`, `Beatable`,
`TagPlayer` (types no level uses).

**Verified equivalent, no change needed**: the inactivity list reset (the index
returns to 0), `changeInactivityTime:` pushing `lastActivity` forward,
`popAtPosition:`, `setSoundsFromString:` splitting on `&`, and
`updateBPMCounter`'s 60.0 and 200.0 constants.

`tools/coverage.py` now carries the verified alias and not-applicable tables, so
its number means something and a future rename cannot hide a gap. 137 tests.


### 2026-09-08 (evening) - the shuffle, and the trip question settled

**The shuffle fired only sometimes, and the reason was a clock.** The original
stamps the foot with `[NSDate date]` and schedules its 2.0 s `dispatch_after`
from the same instant, so the callback always lands at or after 2.0 s of
elapsed foot time. The port stamped the foot with the key-release time from the
input event but scheduled the re-check off `bus.now`, which is the *previous*
frame. The callback arrived a few ms early, `gap` came out around 1.995, the
foot stayed `"off"`, and the shuffle silently did not play. Whether it worked
depended on which way the two clocks fell on a given step.

There is no second chance, which is why it failed outright rather than being
late: **the engine has no idle timer.** Across the whole binary only
`-[PGEPlayer trip:]` schedules a delayed `changeState:`, so the
`cancelPreviousPerformRequests` in `moveForwardOneStep:` is cancelling trip's
own recovery. That 2.0 s `dispatch_after` is the only thing that can ever fire
a shuffle. (Closes open question 4.) Now scheduled from the foot's own stamp,
and pinned by a test that simulates key stamps 0/1/4/8 ms ahead of the frame
clock. Confirmed working in play.

**Falling from running: the mechanic is real, the early levels switch it off.**
Confirmed from four directions and then by the player in-game.

* `-[PGEPlayer init]` sets `tripBPM = 10000.0` - read as raw bytes from the
  Mach-O (`00401c46` at `0x100141ce8`), not from disassembler formatting.
* `tripBPM` appears 15 times in level data, all on Surfaces, none before ps1_11.
* `applyBPMConstraint:` sets `tripBPM`; only ps1_12 and ps1_23 send it (50).
* Only `checkStepBPM` and the unreachable same-foot branch reach `trip:`.

The player's own F3 readout in a shipped level: **"404 beats per minute,
running, running footsteps, this level cannot trip you, you break into a run
above 180."** The BPM counter, the run state and the footstep bank are all
working; the level simply has no trip threshold. Nothing to fix. The trip
machinery itself is verified by `tools/record_gameplay.py --trip`, which applies
the ps1_12 constraint and records the fall.

Two real bugs came out of chasing it: the `PGEPlayer` BPM defaults were zeros
(`checkStepBPM` returns on its first line when either is zero, so the running
state never engaged at all), and `applyBPMConstraint:` was not setting
`tripBPM`. Both fixed.


### 2026-09-08 (audit, part 2) - the eight remaining classes

Method-by-method against the binary. `PGEObjectWithTriggers`, `PGESurface`,
`PGECollectible`, `PGESound`, `PGEGameAgent` and `PGEEnemy` are now complete.

**Seven more behaviours the port did not have:**

1. **`OnLoad` was never fired.** `-[PGEGameAgent levelInited:]` answers
   `PGE_MESSAGE_LevelInited` by firing the object's `OnLoad`. Eight monsters
   across seven levels hang their opening move on it (`FollowPathWithName`,
   `AlertAllEnemies`), so they would simply never have started.
2. **`-[PGEGameAgent update:]` was missing entirely.** Every active agent moves
   along `orientationVector` at `speed` each frame, and - gated on `speed > 0` -
   re-checks collisions. `PGESound` and `PGECollectible` inherit it.
3. **Enemies steer, they do not move.** `-[PGEEnemy update:]` never calls
   `setPosition:` or `setOrientationVector:`; it calls `findDirectionTo:`, which
   aims the vector and stores `squaredDistanceFromGoal`, and `[super update:]`
   does the walking. The port had merged both into one method.
4. **`PGESurface` latches `entered` and `exited`.** `OnEnter` fires **once in
   the life of the level**, not once per visit, unless `multipleOnEnter` is set -
   which also lifts the `OnExit` latch. Cross a trigger line twice and the
   second crossing is silent.
5. **`setActive:` acts only on a transition.** Re-activating an already-active
   agent does nothing; the port was re-firing `OnActivate` and restarting intro
   sounds.
6. **Delayed triggers post directly.** `startTriggerAfterDelay:` ends in
   `postNotificationName:`, where an immediate trigger ends in
   `enqueueNotification:postingStyle:NSPostWhenIdle`. A delayed message
   therefore overtakes anything already queued.
7. **`-[PGEEnemy init]` defaults.** chaseSpeed 15, walkingSpeed 10,
   distractedTime 10, chasingRadius 200. The port had zeros, so any enemy whose
   level data named no speed would have stood still forever.

**Two faults reproduced rather than corrected**, per the brief:

* `-[PGEGameAgent playerMovedToPosition:]` checks collisions **before** storing
  the new player position, and skips the check entirely while either stored
  coordinate is exactly `0.0`.
* `positionBeforeChasing` is left at the origin by `init`; only states 3 and 12
  record the real position. An enemy alerted straight to a *place* - which is
  what tripping does - walks back to the world origin when it gives up.

**One of my own additions removed.** `playerMovedToPosition:` assigns
`tripBPM` / `runBPM` / `tripSound` / `shuffleSound` only inside the "found a
surface" branch; the port also reset them to the level's values when the player
was on no surface. Checked first: no Room in the game sets tripBPM, runBPM or
shuffleSound, and the single Room `tripSound` (ps1_2) is found anyway by
`trip:`'s `anySoundContaining:@"trip"`. So the reset was pure invention and is
gone.

**Resolved as not applicable, with evidence**: the whole shooting group (every
`OnShoot` in the game's data is an empty string, and `PGE_ACTION_Shoot` is
posted only from `handButtonPressed:`, which needs hands - never enabled);
`PGEForgetfulMan`, `PGEActionSurface`, `NPC`, `Comment` and the unnamed template
`Monster`s (never used, or carrying no properties at all);
`PGE_MESSAGE_AgentDidMove` and `PGE_MESSAGE_RoomInited` (posted, observed by
nothing).

127 tests. Still unread: `PGEPlayer`'s jump/swim/shoot/beat (none reachable),
`PGELevel`'s alarms, dilemmas and pause/resume, and `PGEGameProgress`.


### 2026-09-08 (audit) - stopped adding levels, went back over what shipped

Asked to port piece by piece with no inventions, I had instead: invented a
control, invented a config switch to disable a recovered behaviour, lost a whole
audible feature without noticing, and advanced two levels past a broken core
mechanic. So no new content until what exists has been checked against the
binary. New file: **DIVERGENCES.md**, the register that should have existed from
the start.

**Four mechanical sweeps, now kept as tools so they can be re-run:**

| tool | what it checks | result |
|---|---|---|
| `tools/sweep_properties.py` | every level-data property key vs the port | 47 keys, 44 handled, 3 are typos the binary ignores too |
| `tools/sweep_messages.py` | every `PGE_MESSAGE_*` fired by a trigger | 13 distinct, 12 handled, 1 is visual-only |
| `tools/sweep_assets.py` | every declared sound vs every name a port path can produce | found the `hitwall` bug |
| `tools/coverage.py` | every method on the 12 ported classes vs the port | 167 behaviour methods; lists what has no counterpart |

**Bug found and fixed: the wall thump never played.**
`-[PGELevel playerDidCollideAWall:]` falls back to `[playlist S3DSound:@"hitwall"]`
when `hitWallSound` is unset, with `sendToReverb = YES` and `wetGain = 0.5`.
**No level in the game sets `hitWallSound`** - 0 of 27 - so the fallback is what
you always hear. The port guarded on `if self.hit_wall_sound:` and therefore
never played anything, in any level. ps1_1 and ps1_1b do not declare `hitwall`
in their playlists and so are silent here in the original too; ps1_2 and ps1_3
declare it and should thump.

**Three findings that turned out to be faithful already**, recorded so they are
not re-investigated:

* `collisionRadius`, `SoundList` and `Goal` appear in level data and are ignored
  by the port. None of the three appears anywhere in the binary - the real keys
  are `collideRadius` and `soundList`, and `Goal` is a designer's note. The
  original ignores them too.
* `PGE_MESSAGE_StartFullWheelRotation` (ps1_1b) drives
  `rotateDialVisualByAngle:`, a `CGAffineTransformRotate` on a `UIImageView`.
  Silent. Not applicable to an audio-only port.
* ps1_1b declares `foot_stone_*` that no port path can reach - because **ps1_1b
  never posts `EnableWalk`** (0 uses). It is the turning-only tutorial; those
  sounds arrive through a shared playlist include and cannot play in the
  original either.

**Still unread**, and the register says so plainly: the method-by-method pass
over `PGEPlayer`, `PGEGameAgent`, `PGEEnemy`, `PGECollectible`, `PGESound`,
`PGESurface` and the rest of `PGELevel`. A name match is not a logic match -
`updateFeetView:` had a counterpart and was still wrong - so each one has to be
read on both sides.


### 2026-09-08 (later) - the alternation rule, and two wrong answers before it

**The bug.** Repeating one foot walked you, at whatever speed you could press
the key. That is not the game: in Papa Sangre you place a foot, then the *other*
foot, and a foot you have just used will not take a second step.

**Why I missed it: I read one branch backwards.** `footButtonPressed:` and
`footButtonReleased:` both begin with

```
if ([[feetViewDict objectForKey:Foot] isEqualToString:@"off"]) return;
```

I had implemented that as "ignore the press if the foot is *not* off", reading
`"off"` as "not currently held". It is the opposite: **`"off"` means the foot is
not available to you**, and that one test is the entire alternation rule.

**Where availability is decided.** `-[PGEMoveInterpretor updateFeetView:]`
rebuilds `feetViewDict` from scratch each time it runs. Per foot, with
`gap = min(|lastFootDate.timeIntervalSinceNow|, 100.0)`:

| condition | result |
|---|---|
| it is `lastFootButtonPressed` and `gap < 2.0` | `"off"` - you may not use it |
| it is `lastFootButtonPressed` and `2.0 <= gap < 99.0` | post `PGE_ACTION_Shuffle`, set `lastFootButtonPressed = "N"`, then `"on"` |
| anything else | `"on"` |

Constants: `fmov s9, #2.0` at 0x100008144 / 0x10000823c; 99.0f at 0x100141be4;
the 100.0 clamp at 0x100141bd0.

It runs after every step and from `lockControls`, `setSettingsToDefault`,
`enableWalk`, `disableWalk`, `enableSwim`, `disableSwim`, `jump:` and
`playerStateDidChange:` - and, crucially, `footButtonReleased:` ends with two
`dispatch_after` re-entries at **0.1 s** (0x05f5e100 ns) and **2.0 s**
(0x77359400 ns), never cancelled. The 2.0 s one is what gives the foot back.

So: alternate and you walk at any tempo; repeat a foot and **nothing happens at
all**; stand still for two seconds and you hear yourself shuffle and may then
start on either foot.

**The shuffle was missing entirely.** `-[PGEPlayer shuffle]` plays
`shuffleSound`, or `"<footstepsPrefix>_shuffle"` if that is empty, looked up by
**exact** name (`S3DSound:`, not `anySoundWihPrefix:`), `spatialized = NO`,
`sendToReverb = YES`, `wetGain = 0.75`. 24 `*_shuffle` assets ship and the
playlists declare them. `-[PGELevel playerMovedToPosition:]` copies the
surface's `shuffleSound` onto the player, or `@""` when the surface has none -
which is exactly why level 3's rings, whose prefixes are `foot_stone-kennelA/B/C`,
each name `foot_stone-kennel_shuffle` explicitly. All of that is now ported.

**And it settles the trip question, which I got wrong in both directions.**
First I implemented the same-foot trip because the disassembly plainly posts
`PGE_ACTION_Trip`. Told that the real game does not do that, I switched it off -
which quietly turned "same foot does nothing" into "same foot is a full step",
and that is the bug above. The actual answer: **the trip branch is real code
that cannot be reached.** To trip you must release the same foot within 1.0 s,
but that foot is held `"off"` for 2.0 s, and both the press and the release
return early on it. The branch is kept, exact, in `trip_would_fire()`, and a
test proves no sequence of presses reaches it.

The lesson worth keeping: the player's account of the behaviour was right both
times, and both of my readings were wrong because I had stopped one function
short of the one that mattered.


### 2026-09-08 - Level 3, monsters, and two corrections

**Two corrections from the player, both right.**

*The 180 degree snap turn is gone.* I had bound it to the down arrow; the
original turned by swiping and had no such thing. Small nudge turns on `,` and
`.` remain, as the keyboard equivalent of a short swipe. Pinned by
`test_there_is_no_snap_turn`.

*Repeating a foot no longer trips you.* This one is a genuine conflict in the
evidence. `-[PGEMoveInterpretor footButtonReleased:]` compares the two foot
timestamps and, if you release the foot you last used within one second, posts
`PGE_ACTION_Trip`; `PGEPlayer` observes that and `trip:` runs with no guard of
any kind. I read that correctly. But someone who has played the iOS game reports
that repeating a foot there simply does nothing, and on how the game *behaves*
that outranks my reading of a code path whose reachability under the shipped
control scheme I have not proved. The recovered rule is kept, exact, behind
`MoveInterpretor.same_foot_trips`, defaulting **off**. Both behaviours are
tested. **Open question**: find out which is right - the likeliest resolution is
that the shipped view controller cannot deliver two releases of the same foot.

**Monsters.** `-[PGEEnemy update:]` is a thirteen-way switch dispatched through
a jump table at 0x10001de40. Decoded:

| state | meaning |
|---|---|
| 1 | idle - loop `defaultSound`, walking speed |
| 2 | alerted to player (one shot) -> 3 |
| 3 | chasing the player - `chaseSpeed`, `chaseSound`, remembers where it started |
| 4 | alerted to a position (one shot) -> 5 |
| 5 | going to that position |
| 6 | arrived; `distractedTimer` runs, then home |
| 7 | attacking |
| 8-11 | unused; the jump table sends them to the tail |
| 12 | alerted to an agent - `awareSound`, then 5 after one second |
| 13 | returning to where it was before it was disturbed |

Each state does its entry work once, guarded by `state_atPreviousFrame`.

**Nothing in `update:` looks at how close the player is.** An enemy never
notices you on its own; it has to be told, by `AlertAllEnemies`,
`AlertEnemyWithName` or `AlertEnemiesWithinRadius`. And **no trigger in level 3
sends any alert at all** - so the hog there never wakes. That is the design:

**Level 3 "The Kennel"** is built entirely around listening. A hog sleeps in the
middle of the room looping `monster_hog1_01_dry_still`, spatialised where it
lies. Four concentric surfaces are layered around it at `z = 2`, each with a
different footstep bank - `foot_stone-kennelA`, then `B`, then `C`, then
`foot_kennel` - so **the ground under your feet tells you how close you are to
it**. Touch it and the level ends and restarts. Verified by walking in: the
footstep bank changes ring by ring exactly as designed.

11 new tests. Confidence: states 1, 2, 3, 13 and the alert entry points are read
directly and are what level 3 exercises. States 4 to 7 and 12 are implemented
from the same disassembly but no level has driven them yet.

### 2026-09-08 - Flat sound was going through the HRTF

Reported from playing: everything sounded slightly tilted, and "like the HRTF
compresses it into a tiny box".

**Cause.** The engine has two separate audio paths and only one is binaural:
`setupSpatialized` builds `csl::Spatializer(kBinaural)`, while `setupPlain`
builds an ordinary `csl::Panner` and mixes straight to the master. OpenAL Soft
with HRTF enabled virtualises *everything* - a stereo source becomes a pair of
virtual loudspeakers convolved with the HRIRs - so the port was putting
narration, footsteps and ambience through a head-related filter the original
never applied to them.

Measured on the shipped assets:

| asset | inter-channel correlation | L-R balance | peak |
|---|---|---|---|
| `Atmos_darkrumble_01` source | 0.011 | +0.05 dB | -16.0 dBFS |
| ... through HRTF | **0.879** | -1.67 dB | **-25.8 dBFS** |
| `foot_stone_s1_L_a` source | 0.999 | **+1.42 dB** | -17.9 dBFS |
| ... through HRTF | 0.829 | **+0.01 dB** | -23.6 dBFS |

The ambience, a wide decorrelated stereo bed, was being squashed almost to mono.
And the footstep banks carry their own placement - left-foot samples lean 1.4 dB
left, right-foot 1.5 dB right, which is how you hear your feet alternate - and
that was being flattened to nothing.

**Fix.** `AL_DIRECT_CHANNELS_SOFT` on every un-spatialised source, using
`AL_REMIX_UNMATCHED_SOFT` so a mono flat sound is spread across both channels
rather than dropped. Spatialised sources keep the recovered HRTF. This restores
the original's split exactly. Verified: balance and stereo width now pass
through identical to the source file, and the binaural sweep still passes with a
0.79 ms peak lateral delay.

**Side effect: the level problem was largely this.** The HRTF path was costing
9.8 dB on ambience, 5.6 dB on footsteps and 2.6 dB on narration. With everything
now reaching the output at source level, the master volume default drops from
2.5 (+8 dB) to 1.4 (+2.9 dB).

Three new tests, including one that renders the shipped stereo assets and
asserts their balance and width survive unchanged.

### 2026-09-08 - Levels 1b and 2, and the face-the-sound mechanic

`Run/Play Papa Sangre.exe` now carries every level and chains between them the
way the game does - the exit's win narration ends, which fires
`LoadLevelWithName`.

**Level 1b is a turning puzzle**, and it needed a mechanic the port did not
have. Recovered from `-[PGEGameAgent updateSpatializedSound]`:

```
dx, dy = agent - player
dist   = hypot(dx, dy)
dot    = playerFacing . (dx/dist, dy/dist)
if dot > 0.98:  isInShootingRange = dist < shootRange
else:           isInShootingRange = NO
```

`0.98` is a cone of **+/-11.5 degrees**, and `shootRange` defaults to
**infinity** (`-[PGEGameAgent init]` stores `0x7f800000` straight into the
ivar), so out of the box it is purely a question of which way you are facing.
`setIsInShootingRange:` is **edge triggered** - entering the cone fires
`OnEnteringShootRange` once, and `onLeavingShootingRange` is empty.

That is the whole of level 1b: wait for the summoner, hear "I'm over here",
turn until you face it, and the level answers.

**Level 2 "Soul Music"** needed nothing new - chained collectibles, surfaces
layered over the room and turning were already in place. It is the first level
with both walking and turning, uses a 10 pixel stride instead of 5, and has two
full-width floor strips at `z = 2` that sound as you cross them.

`StartFullWheelRotation` (used by 1b's intro) is handled by
`PGEStepsAndSwipeViewController` - it puts the iOS screen into a rotation-wheel
mode. There is no keyboard equivalent because turning is always available, so it
is a documented no-op.

10 new tests. The build script now passes whole directories to PyInstaller
rather than one entry per file, because 700 `--add-data` arguments exceeds
Windows' command-line length limit once the full audio tree is carried.

`Game` (`core/game.py`) owns level loading and transitions, and reports which
object types a level contains that the port cannot build yet - so walking into
level 3 says out loud that its monster is missing rather than quietly omitting
it.

### 2026-09-08 - Three fixes from playing it

**1. The closing narration was being talked over.** Collecting the exit means
you stop moving, and the inactivity clock is 18 seconds while the win narration
runs 24 - so the "are you still there" nag fired straight over it.
`-[PGELevel shutDownLevel:]` turns out to deactivate **every agent except the
one that sent the message**, stop the inactivity sound, empty its list, and
disable walking, hands and rotation. The sender is spared precisely so the thing
you walked into can finish speaking. Implemented and pinned by two tests; a
logged timeline of a full playthrough now shows no overlap anywhere.

**2. `PGE_MESSAGE_PlaySound` was under-implemented.** It is handled by
`PGEPlayer`, not the level, and does three things I had missed: `soundName` may
be an `&`-separated list from which **one is chosen at random**; a name ending
in `_a` is treated as a *prefix* so a random variant is picked; and `gain` and
`loop` parameters are honoured. The sound is forced un-spatialised.

**3. Everything was too quiet**, which is true of the original mix on a PC
rather than a bug: narration peaks near -4 dBFS, footsteps around -18, ambience
near -24, and footsteps play at half gain on top. Measuring the chain showed
only -1 to -5 dB of loss through OpenAL, so nothing was broken - the game is
simply mixed for a phone with the volume up. Added a master volume (default
+8 dB) that scales everything equally, so the authored mix is preserved; OpenAL
Soft's output limiter is switched on so raising it cannot clip. Page up and page
down adjust it in 2 dB steps and it persists to `config/audio.json`.

**Also corrected, from the player:** I had described hands, clapping, jumping
and swimming as Papa Sangre controls. They are engine features that Papa
Sangre 1 never enables - `DisableHands` 27 times, `EnableHands` zero, swim and
jump never mentioned. Papa Sangre II is the one with hands and clapping. The
docs and the in-game control list now say so.

**And a new class of original defect**, found while chasing the overlap: eight
sounds that the level data names and that ship as files, but that the level's own
playlist never declares - so the engine's lookup finds nothing and they are
silent in play. `FINAL_ITD_inactive_all` in level 1 is one. The audit now
reports these separately from genuinely missing files, because the file being
present makes them easy to "fix" by accident.

### 2026-09-08 - Phases F, G and H: level 1 is playable

`Run/Walk in the dark.exe` plays Papa Sangre level 1 end to end on the recovered
engine.

* `audio/bank.py` - the `S3DPlayList` equivalent: loads a level's playlist and
  the footstep banks it includes, with the original's random `anySoundWihPrefix:`
  and `anySoundContaining:` lookups.
* `entities/agent.py`, `sound_agent.py`, `collectible.py` - `PGEGameAgent` and
  the two subclasses level 1 needs, with the recovered defaults
  (`collideRadius` 20, `speed` 10, inactive) and lifecycles.
* `world/surface.py`, `world/level.py` - `PGESurface` and `PGELevel`, including
  the highest-`z`-wins surface pick, the enter/step/exit triggers, the
  conditional copy of `tripBPM`/`runBPM`/`tripSound` onto the player, and the
  inactivity nag that pushes its own clock past the length of the sound it just
  played.
* `input/pygame_source.py` and `apps/walk_in_the_dark.py` - SDL keyboard, with
  steps timestamped on key release.

**A serious bug found here.** Level 1's player starts at world Y `-203` facing
`(0, +1)`, so the three notes and the exit must be at greater Y. With my
importer they were all *behind* the player, who walked into the back wall in
seven steps. The cause was a lone `fneg` in the engine's position maths that I
had missed: **world Y is negated relative to Tiled**. Every object position and
every surface rectangle was mirrored. Corrected, documented in
GAME_STRUCTURE.md section 4, and pinned by a test that asserts level 1's
objectives lie ahead of the player rather than behind.

14 new tests walk level 1 from its start position to the exit and check every
scripted beat: the room locking the controls, the narration unlocking walking
and starting the atmosphere, the three notes firing in order and deactivating
themselves, the exit appearing only after the third note, the win sound leading
to `LoadLevelWithName: ps1_1b`, the far wall stopping the player, and the
inactivity nag cycling its three sounds. Every one of the 27 levels also builds
without error.

**Keyboard layout.** Walking is a constant left-right alternation, so it needs a
hand to itself or there is nothing left to steer with. The feet are **A** and
**D** under the left hand; the arrow keys turn, under the right. Hands sit on Q
and E directly above the feet they belong to. The first attempt put the feet on
A and L - opposite ends of the keyboard, both hands committed, no way to turn
while walking - which the player spotted immediately. Pinned by
`tests/test_core.py::test_walking_and_turning_use_different_hands`, along with a
check that no two gameplay actions share a key. Bindings are written to
`config/keys.json` on first run so they can be changed without being told the
file exists.

**Two further port-side decisions**, both recorded because they have no original
to copy: turning is continuous at 120 degrees per second while held (the original
turned by swiping, so there is no rate to recover), and when the player presses
a turn key in a level where rotation is disabled the game says so once. Level 1
disables rotation in its Room and never re-enables it - "In the Dark" is a
straight corridor - and on iOS a swipe that did nothing was self-evident in a
way that silence is not.

### 2026-09-08 - Phases D and E: message bus, triggers, input, player

Spatial audio confirmed working by ear, so the game logic on top of it.

* `core/messages.py` - the `NSNotificationCenter` / `NSNotificationQueue`
  equivalent, with the original's three delivery paths: immediate `post`,
  deferred `enqueue` (`NSPostWhenIdle`, recovered), and cancellable
  `post_after`. Messages are **broadcast**; every agent filters by the `name`
  parameter itself, which is precisely why the 6 triggers naming non-existent
  agents are no-ops without any special handling.
* `core/triggers.py` - `PGEObjectWithTriggers`: case-insensitive type match,
  `count` / `afterCount` / `afterDelay` handling, and `senderName` + `position`
  injected into every message.
* `input/keymap.py` - rebindable actions saved to `config/keys.json`. The
  bindings are new (there was no keyboard); the actions all correspond to
  something the original could do.
* `input/interpreter.py` - `PGEMoveInterpretor`. **The walking mechanic is
  recovered in full**: a step fires on foot *release*, not press; whichever foot
  has the newer timestamp is the one you used last; and using that same foot
  again within **one second** posts `PGE_ACTION_Trip` instead of a step. Leave
  more than a second and repeating a foot is fine, because you have stopped.
* `entities/player.py` - `PGEPlayer`: the tempo maths, the run/trip thresholds,
  stepping, wall collision, footstep bank selection and tripping, all with the
  original's arithmetic including its quirks.

34 tests, covering each recovered branch. Two caught real mistakes while
writing: a `str(Enum)` slip that made rebinding silently no-op on Python 3.11+,
and - more importantly - a `trip:` recovery I had *invented* rather than
recovered. Going back to the disassembly gave the real sequence and closed three
open questions at once (2, 3 and 4).

### 2026-09-08 - Positioned audio was playing flat (fixed)

Reported from listening: everything sounded centred. It did.

**Cause.** OpenAL - like the binaural panner the original used - only applies a
head-related transfer function to a *mono* source. A stereo buffer is routed
straight to the two output channels and its position is ignored entirely. Of the
88 sounds the playlists mark `spatialized`, **69 ship as stereo**, so most of the
game's directional audio was rendering with no direction at all.

Measured before the fix, `door_castle_living` at 90 and 270 degrees:

| bearing | ITD (samples) | ILD (dB) |
|---|---|---|
| 90 | -18 | +3.80 |
| 270 | -18 | +3.80 |

Identical - the position was doing nothing. After forcing mono: **+28 / -36**.

**Why the test suite missed it.** The loopback sweep used a synthetic mono
click, so it verified the HRTF chain while the real assets bypassed it. The
lesson is not "add a test" but "test with the real inputs" - a synthetic signal
happened to sidestep the exact property that was broken.

Added `tests/test_audio.py::test_real_game_audio_is_actually_spatialised`, which
renders the shipped files and asserts that 90 and 270 degrees do not come out
the same. Confirmed it fails on the old behaviour (`|diff| = 0`) and passes on
the new (`|diff| = 64`).

**Also checked and ruled out** as contributing causes: Windows' mono-audio
accessibility setting (off on this machine) and the output device (Realtek, not
one of the several virtual devices present). Both are now reported by
`Listen to spatial audio.exe`, which also opens with a blunt hard-left /
hard-right check so a dead output path is obvious in the first ten seconds
rather than after ninety.

### 2026-09-08 — Standalone executables

Everything that needs running is now a double-clickable program in `Run/`,
because driving a terminal with a screen reader is painful and the desktop
client's run button does not work on this machine.

* `papasangre/util/paths.py` resolves resources identically whether running from
  source or frozen (PyInstaller unpacks to `sys._MEIPASS`; anything that must
  persist goes next to the executable instead).
* `papasangre/util/console.py` gives each tool spoken plus printed output, and
  holds the window open on success *and* on an unhandled exception.
* The NVDA controller client is bundled inside each build rather than assumed
  to be installed.
* The content audit moved from `tools/audit.py` into `papasangre/assets/audit.py`
  so the tool and the executable share one implementation; the executable
  carries the level exports, playlists and a pre-computed audio-name index
  (660 names) instead of the 96 MB audio tree.
* All three verified working frozen, with identical results to running from
  source.

### 2026-09-07 — Phase C: the audio engine

The port now renders through the original game's own measured HRTF.

* **HRTF recovered and rebuilt.** `tools/extract_hrtf.py` decodes the embedded
  blob and writes 187 stereo impulse-response WAVs plus a makemhr definition;
  `vendor/makemhr/makemhr.exe` turns them into `build/hrtf/papa_ircam_1050.mhr`,
  which OpenAL Soft loads by name.
  * The stored spectra are **conjugated** relative to the usual DFT convention.
    Read naively they give the correct magnitude response but a time-reversed
    impulse, which shows as an interaural delay of the right size and the wrong
    sign. Negating the imaginary part yields causal responses with 99.7 % of
    their energy in the first 128 taps.
  * Verified against head physics before conversion: ITD and ILD agree in sign
    at all ten test azimuths, and the delay peaks at 0.67-0.77 ms at +/-90
    degrees, which is what a real head produces.
  * The set covers elevations -45 to +90 (IRCAM never measured lower);
    makemhr synthesises the three missing rings.
* **Binding.** `papasangre/audio/openal.py` — ctypes over `soft_oal.dll`,
  covering sources, buffers, the listener, `ALC_SOFT_HRTF`, `ALC_EXT_EFX` and
  `ALC_SOFT_loopback`.
* **Engine.** `papasangre/audio/engine.py` — the port's `S3D` equivalent, with
  the recovered listener transform and constants (see the table in that module).
* **End-to-end verification.** `tools/verify_spatial.py` renders a click at
  eight bearings through OpenAL's loopback device and measures the output:

  | bearing | ITD (samples) | ILD (dB) |
  |---|---|---|
  | 0 | -2 | -2.00 |
  | 45 | +16 | +12.64 |
  | 90 | +28 | +10.30 |
  | 135 | +12 | +6.38 |
  | 180 | +8 | +0.68 |
  | 225 | -26 | -4.55 |
  | 270 | -35 | -12.25 |
  | 315 | -20 | -13.97 |

  Peak lateral delay 0.79 ms. Front and back image centrally; every lateral
  bearing puts the near ear both earlier and louder. This is the whole chain —
  recovered HRTF, .mhr conversion, listener transform, axis mapping and
  OpenAL's renderer — measured rather than assumed.
* **Bug caught here:** OpenAL Soft reads its configuration once, when the
  library initialises. Writing `alsoft.ini` and setting `ALSOFT_CONF` inside
  `open()` was too late, and the playback device silently fell back to
  `Built-In HRTF` — the port would have sounded plausible but wrong. The config
  is now written before the DLL loads, and `AudioEngine.open()` raises if the
  recovered HRTF is not the one in use.
* **Speech.** `papasangre/accessibility/speech.py` — NVDA controller client
  (detected and working on this machine), SAPI 5 fallback, null backend for
  tests.
* **Listening check.** `tools/listen.py` plays real game audio (the level 1
  exit door, a hog) around the head with spoken announcements.

### 2026-09-07 — Phase B: audio asset strategy

Ran `tools/codec_trial.py` over a twelve-file cross-section (transient footsteps,
tonal and dense loops, long narration, mono monster loops, positioned sounds),
encoding each at Vorbis q5/q6/q7/q8/q10 and FLAC and measuring the added-noise
SNR against the decoded original.

| candidate | median SNR | worst SNR | median size vs original |
|---|---|---|---|
| vorbis q5 | 19.3 dB | 8.1 dB | 69 % |
| vorbis q6 | 21.7 dB | 11.2 dB | 79 % |
| vorbis q7 | 25.1 dB | 12.8 dB | 92 % |
| vorbis q8 | 27.6 dB | 15.0 dB | 107 % |
| vorbis q10 | 36.8 dB | 32.5 dB | 171 % |
| flac | 117.8 dB | 93.9 dB | 575 % |

The source is already ~128 kbps AAC, so a second lossy pass is a cascade: Vorbis
has to spend as many bits as the original just to stand still. At every setting
that saves space it measurably degrades the audio; at every setting that is
close to clean it is *larger* than the original.

**Decision: do not transcode.** Ship the original `.m4a` files unmodified and
decode at runtime with PyAV.

* verified bit-identical to the FFmpeg CLI decoder on four spot-checked files
* 261x realtime on the 112-second level-1 intro
* a whole level's playlist (13-25 sounds, 120-200 s of audio) decodes in
  0.4-0.6 s and occupies 22-35 MB of PCM
* install size stays at the original 96 MB instead of growing to ~575 MB

`tools/codec_trial.py` is kept so the measurement can be re-run if the decision
is ever revisited.

### 2026-09-07 — Phase 0 and A

* Extracted `ps.zip` to `reference/` (232 MB, 1315 entries). Archive untouched.
* Identified the game: **Papa Sangre**, 2016 re-release, arm64, decrypted.
* Built reverse-engineering tooling: Mach-O section parser, Objective-C class
  dumper (`tools/classdump.txt`, 4627 lines), ARM64 disassembler with selector /
  ivar / CFString / float-constant resolution.
* Recovered the complete engine class model and the message vocabulary.
* Recovered the core movement mathematics (`updateBPMCounter`, `checkStepBPM`,
  `moveForwardOneStep:`) — see `GAME_STRUCTURE.md` §7.
* Recovered the trigger/message grammar and firing rules.
* Located and extracted the **embedded IRCAM 1050 HRTF** database
  (1 541 427 bytes at binary offset `0x100142c54`) to `tools/embedded_hrtf.dat`;
  confirmed the direction grid and that blocks 2/3 are the left/right ear
  transfer functions (correct ITD/ILD polarity across azimuth).
* Wrote `papasangre/assets/sexp.py` — parses all 104 playlists, 0 failures,
  **982** distinct sound declarations.
  *Bug found and fixed the same day:* a single `(sound ...)` form may carry
  several `(bundle ...)` entries — that is how every footstep bank is written.
  Reading only the first bundle silently dropped 400 declarations, including 13
  of every 14 footsteps. Pinned by
  `tests/test_dataimport.py::test_one_sound_form_may_hold_many_bundles`.
* Wrote `papasangre/assets/tiled.py` — reproduces the original three-pass level
  load, coordinate transform, trigger grammar and generic property applicator.
* Wrote `tools/audit.py` — parses all 27 levels and validates every reference.
  Result: **0 unknown object properties, 0 unresolved footstep prefixes**, and
  25 genuine defects in the original data catalogued in `GAME_STRUCTURE.md` §11.
* Generated `docs/CONTENT_INVENTORY.md`: the per-object porting checklist.

---

## Verification results

| Check | Result |
|---|---|
| Binaural cues in rendered output | correct at all 8 bearings; peak lateral ITD 0.79 ms |
| Real shipped assets actually spatialised | yes; 90 vs 270 degrees differ by 64 samples of delay |
| Positioned sounds forced to mono | 69 of 88 need it; enforced, and `load()` raises if one slips through |
| Custom HRTF in use at runtime | `papa_ircam_1050`, enforced (open() raises otherwise) |
| Audio decode vs original | bit-identical |
| Playlists parsed | 104 / 104, 0 errors, 982 sound declarations |
| Playlist declarations resolving to a shipped file | 982 / 982 (excluding 4 empty declarations in the original) |
| Footstep banks reachable from a level's own playlist | 46 / 46 prefixes, 0 missing |
| Levels parsed | 27 / 27, 0 errors |
| Object properties with no engine setter | 0 (excluding the one original typo, `foostepsPrefix` in `ps1_1b`) |
| Footstep prefixes without assets | 0 / 46 |
| Sound references unresolved | 6 — all traced to original data defects (§11) |
| Message names unknown to the engine | 8 — all traced to original data defects (§11) |
| Dangling agent-name references | 6 — all traced to original data defects (§11) |
| `LoadLevelWithName` targets missing | 0 |
| `FollowPathWithName` targets missing | 0 |

---

## Open questions still to be resolved

Tracked so they are not forgotten; each is blocking the phase named.

1. ~~**HRTF payload blocks 0/1**~~ — *partly resolved.* Blocks 2/3 are the ear
   transfer functions and are what the port uses; verified physically. The role
   of the first pair (near-impulsive, azimuth-dependent amplitude, far lower
   energy) is still unconfirmed and is not needed. *Revisit only if the
   spatial character turns out to differ from the original.*
2. **Rotation model** — `rotatePlayerFromAngle:`,
   `computeNewOrientationVector`, `rotatePlayerToFixedRotation:` and the mapping
   from `startAngle` to the orientation vector are not yet disassembled.
   *Phase F.*
3. **`trip:` penalty** — `tripTimePenality` semantics and the recovery sequence.
   *Phase F.*
3b. ~~**Does repeating a foot trip you?**~~ — **resolved, and I had it wrong
   twice.** See the 2026-09-08 entry below. The answer is that repeating a foot
   does nothing at all, and the mechanism is `updateFeetView:`, not the trip
   branch. Nothing outstanding.
4. ~~**Idle timeout**~~ — *resolved.* Nothing arms it. Across the whole
   binary only `-[PGEPlayer trip:]` ever schedules a `changeState:` with a
   delay, so the `cancelPreviousPerformRequests` in `moveForwardOneStep:` is
   cancelling **trip's own two-second recovery**, not an idle timer. The engine
   has no "player has stopped" callback at all, which is why the 2.0 s
   `dispatch_after` in `footButtonReleased:` is the only thing that can ever
   fire the shuffle.
5. **Surface `z` semantics** — whether `z` is only overlap priority or also
   feeds the audio listener height. *Phase H.*
6. **Enemy state machine** — transition thresholds, `distractedTime` and
   `chasingRadius` behaviour in `-[PGEEnemy update:]`. *Phase J.*
7. **Inactivity system** — exact scheduling in `-[PGELevel update]` /
   `playInactivitySound`. *Phase H.*
8. **NSNotificationQueue posting style** — triggers are enqueued rather than
   posted directly, so ordering within a frame matters. *Phase D.*
9. **Distance model** — *partly resolved.* Recovered: `distanceScale` = 0.008
   for Papa Sangre (0.015625 for The Nightjar), `maxSpatialGain` = 100,
   `masterGain` = 1, reverb room size 1.5 / volume 1.0 / dampening 50. The
   auto-reverb mix curve is also recovered: wet rises linearly from
   `minWetSend` at `minReverbDistance` to `maxWetSend` at `maxReverbDistance`,
   dry = 1 - wet. Still needed: the defaults of those four per-sound fields,
   and CSL's `DistanceSimulator` attenuation curve (the port currently uses
   OpenAL's inverse-distance-clamped model). *Phase H, once footsteps and
   ambience give something to compare against.*
11. **Stereo-to-mono policy for positioned sounds** - the original feeds the
    sound file straight into `csl::Spatializer`, which consumes a single
    channel, but which channel is not recovered. The port averages the two
    (keeping both channels' content); 49 of the 69 affected files are
    effectively dual-mono so it makes no difference there, and the worst
    measured level change on the rest is -3.7 dB. `AudioEngine.mono_policy`
    switches to taking channel 0. *Revisit if any positioned sound turns out to
    sound thin or hollow.*
12. **Dilemma outcome tree** — how `solveDillemas` walks
    `dilemmaOutcome_<a>_<b>_<c>`. *Phase K.*

---

## Known discrepancies (port vs original)

Recorded as they arise. Nothing here yet beyond the intended ones:

* **Audio: none.** The port ships the original `.m4a` files untouched and
  decodes them with the same FFmpeg AAC decoder, verified bit-identical. There
  is no transcode generation loss.
* Reverb is OpenAL Soft's EFX reverb rather than `csl::Stereoverb`. The
  original's room size 1.5 / volume 1.0 / dampening 50 are mapped onto EFX decay
  time, gain and high-frequency gain as a starting point; the two models are not
  equivalent and this needs matching by ear.
* HRTF rendering goes through makemhr's minimum-phase-plus-delay model rather
  than direct convolution of the original responses. Measured effect: the delay
  at 180 degrees comes out as 8 samples where the raw data has 3. Both are far
  below the lateral 35, so both image centrally.
