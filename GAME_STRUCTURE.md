# Papa Sangre — recovered game structure

Everything here was recovered from the shipped iOS bundle in `reference/`
(Objective-C class metadata, ARM64 disassembly, and the shipped data files).
Nothing in this document is invented; where a value is inferred rather than read
directly it is marked **(inferred)**.

Provenance tags used throughout:

* **[R]** Recovered — read directly out of the binary or the shipped data.
* **[I]** Inferred — deduced from surrounding evidence, still to be confirmed.
* **[N]** New — a Windows-side decision with no original counterpart.

---

## 1. The original application

| Fact | Value |
|---|---|
| Title | Papa Sangre (2016 re-release) |
| Bundle id | `com.ernesto.papa` (build config `com.somethinelse.papasangre`) |
| Binary | Mach-O 64-bit **arm64**, 3.3 MB, **decrypted** (`cryptid=0`) |
| Built with | Xcode 7.2.1, iOS SDK 9.2, min iOS 7.0 |
| Language | Objective-C (game) over C++ (audio engine) |
| Engine | "Papa Engine" — classes prefixed `PGE`, audio layer prefixed `S3D` |
| Audio core | **CSL** (CREATE Signal Library, UCSB) — `csl::BinauralPanner`, `csl::Spatializer(kBinaural)`, `csl::Stereoverb`, `csl::Butter` |
| Frameworks | AudioToolbox, OpenAL, AVFoundation, Accelerate, CoreMotion, UIKit |
| Version string | `1_1_020_2015_08_04_R` (Papa Engine licence check) |

The bundle also carries level exports and playlists for **Papa Sangre II** and
**The Nightjar** (used by the in-app cross-promotion), but only the `ps1/`
audio tree is shipped. The port covers Papa Sangre 1 — the complete game.

---

## 2. Data files that define the game

| Path | Count | Role |
|---|---|---|
| `Exports/Papa Sangre/ps1_*.json` | 27 | Tiled map exports — the levels |
| `Exports/Papa Sangre_hubList.plist` | 1 | Level list, titles, unlock order |
| `meta/S3DPlayListModel/*.sexp` | 104 | Per-level sound manifests (S-expressions) |
| `objectsList.plist` | 1 | Level-editor schema of object types |
| `messagesList.plist` | 1 | Level-editor schema of engine messages |
| `ps1/**/*.m4a` | 652 | All game audio (AAC, 44.1 kHz) |

**The game is fully data-driven.** No level logic is compiled into the binary;
levels are graphs of objects carrying declarative trigger scripts. This is why a
faithful port is achievable — the original content is recoverable as data, and
only the *engine* has to be re-implemented.

---

## 3. The 25 levels (+ 2 extra maps)

From `Papa Sangre_hubList.plist`, in unlock order. Only level 1 starts unlocked;
each level unlocks the next on completion. **[R]**

| # | File | Title |
|---|---|---|
| 1 | `ps1_1` | In the Dark |
| — | `ps1_1b` | (unlisted follow-on to level 1 — "SWYE" tutorial) |
| 2 | `ps1_2` | Soul Music |
| 3 | `ps1_3` | The Kennel |
| 4 | `ps1_4` | Bed of Bones |
| 5 | `ps1_5` | Hog Patrol |
| 6 | `ps1_6` | Bedtime |
| 7 | `ps1_7` | The Charnel Pits |
| 8 | `ps1_8` | The Island |
| 9 | `ps1_9` | Grin Reaper |
| 10 | `ps1_10` | Homerun |
| 11 | `ps1_11` | Quicksand |
| 12 | `ps1_12` | The River |
| 13 | `ps1_13` | Pathway of Pain |
| 14 | `ps1_14` | Chessboard |
| 15 | `ps1_15` | Feeding Time |
| 16 | `ps1_16` | Xylophone Road |
| 17 | `ps1_17` | Papa Sangre Says |
| 18 | `ps1_18` | Little Girl |
| 19 | `ps1_19` | Frozen Rivers |
| 20 | `ps1_20` | Zoo |
| 21 | `ps1_21` | Glass Cathedral |
| 22 | `ps1_22` | The Blizzard |
| 23 | `ps1_23` | The Ice Lake |
| 24 | `ps1_24` | The Fate Bell |
| 25 | `ps1_25` | Elysium |

`reckoner.json` is a separate map (the level-select "Reckoner" hub).

Total content inventory (ToolBar palette layers excluded): **145 Surfaces,
117 Sounds, 111 Collectibles, 27 Rooms, 27 Players, 25 Monsters, 6 Paths,
4 Dilemmas, 624 trigger statements.** See `docs/CONTENT_INVENTORY.md` for the
per-object checklist.

---

## 4. Coordinate system **[R]**

Levels are authored in Tiled pixel coordinates. `-[PGELevel createObjectFromDict:]`
converts to world space:

```
Room object (x, y, w, h) defines the level:
    level.rectangle      = CGRect(-w/2, -h/2, w, h)    # centred on the origin
    level.midRoomOnTiled = (x + w/2, y + h/2)

Every object, placed at the centre of its Tiled box, with Y NEGATED:
    world = ( (tx + tw/2) - midRoom.x ,  -((ty + th/2) - midRoom.y) )

A Surface additionally keeps a rectangle:
    origin = ( tx - midRoom.x , -(ty - midRoom.y) - th )
    size   = ( tw, th )

Path polyline points get the same treatment.
```

**The Y negation is easy to miss and changes everything.** It is a lone `fneg`
sitting after the subtraction at each of the five places the engine sets a
position (`popAtPosition:` twice, `setPosition:` for the player,
`initWithRectangle:` for surfaces, `addPointToPath:` for paths). Without it the
whole game is mirrored front-to-back: in level 1 the player would start facing
the back wall and walk away from all three notes and the exit.

The check that catches it: level 1's player has `startAngle = 90`, which gives
an orientation vector of `(0, +1)`, so every objective in that level must lie at
**greater** world Y than the start position. With the negation they do
(`-203` start, notes at `-174`, `-61`, `+52`, exit at `+188`); without it they
are all behind. `tests/test_dataimport.py` pins this.

Units are pixels; the player advances `pixelsPerStep` per footstep (5 px in
most levels). Wall collision is exactly
`CGRectContainsPoint(level.rectangle, newPosition)` inside `moveForwardOneStep:`
— the room rectangle *is* the level boundary. **[R]**

## 5. Object model **[R]**

Class hierarchy as recovered from the Objective-C metadata:

```
NSObject
└── PGEObjectWithTriggers          triggers[], name, position
    ├── PGEPlayer
    ├── PGEPlayerListener
    ├── PGESurface                 rectangle, surfaceId, z, footstepsPrefix,
    │   │                          tripBPM, runBPM, tripSound, shuffleSound
    │   ├── PGEActionSurface        + buttonLabel
    │   └── PGELevel                + agents, floors, alarms, paths, inactivity
    │       └── PGEHub
    └── PGEGameAgent               agentId, orientation, playlist, state, path,
        │                          chasingRadius, shootRange, speed, collideRadius
        ├── PGESound               looping, spatialized, skippable, gain, rails
        ├── PGECollectible         introSound, loopSound, collectSound, nextCollectible
        ├── PGEBeatable            onRangeSound
        ├── PGEDilemma             restSound, alertSound, thanksSound, abandonSound,
        │                          dilemmaID, bpmMalus, alertDistance
        ├── PGENPC                 hailSounds, briefingSound, levelName, hailInterval
        ├── PGESummoner
        ├── PGETagPlayer           tagState, fleeRadius, caughtRadius
        └── PGEEnemy               walkingSpeed, distractedTime, aware/chase/
            └── PGEForgetfulMan     notThere/attack/default sounds
```

Papa Sangre 1 level data uses only: **Player, Room, Surface, Sound,
Collectible, Monster, Path, Dilemma**. The rest belong to the other two games
that share the engine. **[R]**

### Generic property application **[R]**

`createObjectFromDict:` handles properties in two classes:

* keys beginning with `On` → parsed as **triggers**
* every other key → the engine builds the selector `set<Capitalised key>:` and
  calls it if the object responds; unknown keys are logged and ignored.

This is why the data can set `collideRadius`, `distractedTime`, `looping`,
`footstepsPrefix` etc. without any per-type code. The port reproduces this with
a name-mapped attribute applicator.

---

## 6. The trigger / message system **[R]**

### Trigger property syntax

```
OnCollide = "Msg1:key=val;key2=val2|Msg2|Msg3:afterDelay=1"
             └── statements separated by "|" ──┘
```

Per statement (`-[PGELevel createDictFromTriggerDescription:]`):

1. split on `:` — must yield exactly 2 parts to have parameters
2. part 0 is the message name; part 1 is `;`-separated `key=value` pairs
3. the keys `count`, `afterCount`, `afterDelay` are consumed by the trigger
   itself, everything else becomes a message parameter
4. a pair without `=` logs *"Trigger definition error : '=' is missing"* and is
   dropped
5. `soundName` parameters additionally post `PPAE_MESSAGE_CacheSound`

Message names are normalised by `-[PGEObjectWithTriggers messageNameFromString:]`:
already-prefixed `PGE_MESSAGE_*` names pass through, anything else gets
`PGE_MESSAGE_` prepended. This is why the shipped data mixes
`ActivateAgentWithName` and `PGE_MESSAGE_ActivateAgentWithName` freely.

### Trigger firing (`-[PGEObjectWithTriggers triggerWithType:]`) **[R]**

```
for each trigger whose triggerType matches (case-insensitive):
    if trigger has "count":       if count <= 0: skip;  count -= 1
    if trigger has "afterCount":  if afterCount > 1: afterCount -= 1; skip
    params = copy(trigger.parameters)
    params["senderName"] = self.name
    params["position"]   = self.position
    if afterDelay > 0:  performSelector(startTriggerAfterDelay:, params, afterDelay)
    else:               enqueue notification on NSNotificationQueue
```

Messages are **broadcast** through `NSNotificationCenter`; every agent inspects
the `name` parameter and ignores messages not addressed to it. This matters:
several shipped triggers name agents that do not exist, and they harmlessly do
nothing (see §11).

### Trigger types by object type **[R]**

| Object | Trigger properties |
|---|---|
| Room / Surface / ActionSurface | `OnEnter`, `OnStep`, `OnExit`, `OnExitNotJumping`, `OnExitJumping`, `OnButtonPressed` |
| Sound / Collectible | `OnActivate`, `OnDeactivate`, `OnEnteringShootRange`, `OnPathEnd`, `OnLoad`, `OnCollide`, `OnSoundEnd` |
| Monster / ForgetfulMan | as above plus `OnShoot`, `OnShootMissed` |
| Player | `OnTrip`, `OnShootMissed` |
| PlayerListener | `OnStart`, `OnDeath`, `OnWallCollision`, `OnTrip`, `OnRun`, `OnStartToRun` |

### Message vocabulary **[R]**

77 `PGE_MESSAGE_*` names exist in the binary. The 25 actually used by Papa
Sangre 1 level data are listed in `docs/CONTENT_INVENTORY.md`; the full set is in
`tools/ps_strings.txt`.

---

## 7. Player movement — the core mechanic **[R]**

Papa Sangre is walked by alternating left/right "foot" inputs in rhythm. The
engine measures the tempo of those inputs and derives the player's state.

### `-[PGEPlayer updateBPMCounter]` — called after every accepted step

```c
now = [NSDate timeIntervalSinceReferenceDate];
[walkTimes addObject:now];
while (walkTimes.count >= 6) [walkTimes removeObjectAtIndex:0];   // keep <= 5

n = min(walkTimes.count - 1, 5);
float sum = 0;
for (i = 0; i < n; i++)
    sum += walkTimes[i+1] - walkTimes[i];

float avg   = sum / walkTimes.count;      // NOTE: divides by count, not by n
walkBPM     = 60.0f / avg;
speed       = (walkBPM >= 200.0f - bpm_constaint) ? @"s3" : @"s1";
```

The `sum / count` (rather than `/ n`) is in the original and inflates BPM by
`count/(count-1)`; it is reproduced exactly. `speed` selects the footstep
sample bank (`s1` = normal, `s3` = fast).

### `-[PGEPlayer checkStepBPM]` — gate run before every step

```c
if (self.tripBPM == 0) return YES;      // level has no trip threshold
if (runBPM      == 0) return YES;
if (walkTimes.count >= 3) {
    if (walkBPM >= self.tripBPM) {            // too fast -> stumble
        if (state != 3) [self trip:nil];
    } else if (walkBPM > runBPM) {            // running
        if (state == 2) return YES;
        post PGE_MESSAGE_PlayerStartsToRun;
        [self changeState:@2];
        walkBPM = 30.0f;
    } else {                                  // walking
        if (state != 1) [self changeState:@1];
    }
} else {
    [self changeState:@1];
}
return YES;
```

Player states **[R/I]**: `0` = still (resets `walkBPM` and clears `walkTimes`),
`1` = walking, `2` = running, `3` = tripped, `4` = dead/locked (blocks movement).

### `-[PGEPlayer moveForwardOneStep:]`

```c
if (state == 4) return;
if (proximityRadius != 0)
    post PGE_MESSAGE_AlertEnemiesWithinRadius {radius, to};
cancel pending changeState:@0;
if (![self checkStepBPM]) return;

foot    = notification.object["lastFoot"];      // "L", "R" or "N"
newPos  = position + orientationVector * pixelsPerStep;
lastFoot = foot;

if (currentLevel && !CGRectContainsPoint(currentLevel.rectangle, newPos)) {
    post PGE_MESSAGE_PlayerDidCollideAWall;     // blocked by the room wall
    return;
}
position = newPos;
post PGE_MESSAGE_PlayerMovedToPosition;

if (speed == @"") speed = @"s1";
if (foot == @"N") return;                        // silent step
prefix = footstepsPrefix ?: @"foot_racetrack";
snd = [playlist anySoundWihPrefix: prefix_speed_foot]     // e.g. "foot_stone_s1_L"
   ?: [playlist anySoundWihPrefix: prefix + @"_s"];
snd.gain = 0.5;  snd.sendToReverb = YES;  snd.wetGain = 0.5;  [snd play];
[self updateBPMCounter];
```

`anySoundWihPrefix:` (the typo is the original's) picks a **random** sound whose
name starts with the prefix, which is how the `_a` / `_b` / `_c` footstep
variants get chosen.

Footstep asset naming: `<footstepsPrefix>_<speed>_<foot>[_<variant>]`, e.g.
`foot_stone_s1_L_a.m4a`. 46 distinct footstep prefixes are used across the game;
all resolve to shipped assets (verified by `tools/audit.py`).

### Which foot you may use next - `updateFeetView:` **[R]**

Both `footButtonPressed:` and `footButtonReleased:` begin with the same test:

```objc
if ([[feetViewDict objectForKey:Foot] isEqualToString:@"off"]) return;
```

**`"off"` means the foot is not available**, not that it is merely un-held. That
single line is the alternation rule, and it is why you cannot run by hammering
one control.

`-[PGEMoveInterpretor updateFeetView:]` rebuilds `feetViewDict` from scratch
every time it runs. Its argument is a debug tag and is never read. Per foot,
with `gap = min(|lastFootDate.timeIntervalSinceNow|, 100.0)`:

| condition | result |
|---|---|
| controls locked, or player state 3 | both feet `"off"` |
| it is `lastFootButtonPressed` and `gap < 2.0` | `"off"` |
| it is `lastFootButtonPressed` and `2.0 <= gap < 99.0` | post `PGE_ACTION_Shuffle`, `lastFootButtonPressed = "N"`, then `"on"` |
| anything else | `"on"` |

It then posts `PGE_MESSAGE_UpdateFeetView` carrying the whole dictionary, which
`PGEStepsViewController` uses to light the on-screen feet.

Constants: `2.0` from `fmov s9, #2.0` at 0x100008144 (left) and 0x10000823c
(right); `99.0f` at 0x100141be4; the `100.0` clamp at 0x100141bd0.

Callers: `lockControls`, `setSettingsToDefault`, `enableWalk`, `disableWalk`,
`enableSwim`, `disableSwim`, `jump:`, `playerStateDidChange:`, and
`footButtonReleased:` - which also schedules two `dispatch_after` re-entries, at
**0.1 s** (0x05f5e100 ns) and **2.0 s** (0x77359400 ns), neither cancelled. The
2.0 s one is what hands the foot back and fires the shuffle.

Net behaviour: **alternate and you walk at any tempo; repeat a foot and nothing
happens at all; stand still for two seconds and you hear yourself shuffle, after
which either foot may start.**

### `-[PGEPlayer shuffle]` **[R]**

```objc
if (paused) return;
prefix = footstepsPrefix ?: @"foot_racetrack";
if (shuffleSound is nil or @"") shuffleSound = [NSString stringWithFormat:@"%@_shuffle", prefix];
snd = [playlist S3DSound: shuffleSound];        // exact name, not a prefix
if (!snd) log red @"cannot find shuffle sound with name : %@";
snd.spatialized = NO;  snd.sendToReverb = YES;  snd.wetGain = 0.75;  [snd play];
```

Note `S3DSound:` - the shuffle is the one foot sound looked up by exact name, so
there are no `_a` / `_b` variants. 24 `*_shuffle` assets ship.
`-[PGELevel playerMovedToPosition:]` sets `player.shuffleSound` to the surface's
`shuffleSound`, or `@""` when the surface has none. That is why level 3's rings,
whose prefixes are `foot_stone-kennelA/B/C`, each name
`foot_stone-kennel_shuffle` explicitly - the computed name would not exist.

### The same-foot trip - real code, unreachable **[R]**

`footButtonReleased:` compares the two foot timestamps and, if you release the
foot whose timestamp is the newer one within `1.0 s` (`fmov d0, #1.0` against
`fabs(timeIntervalSinceNow)` at 0x1000088c4 and 0x100008968), posts
`PGE_ACTION_Trip` instead of `PGE_ACTION_OneStep` - skipping the timestamp
update, the step, and the `lastFootButtonPressed` assignment, but still
refreshing the feet view. `PGEPlayer` observes `PGE_ACTION_Trip` with no guard.

**Nothing can reach it.** Repeating a foot inside 1.0 s requires getting past
the `"off"` gate, and that gate holds the foot you last used for 2.0 s. The port
keeps the branch exactly, in `MoveInterpretor.trip_would_fire()`, and a test
asserts that no sequence of presses produces a `PGE_ACTION_Trip`.

---

## 8. Audio architecture **[R]**

### Two separate paths **[R]**

The engine builds a **different graph** depending on whether a sound is
spatialised, and only one of them involves head-related filtering:

* `-[S3DSound setupSpatialized]` -> `csl::Spatializer(kBinaural)` with a
  `SpatialSource` and a `DistanceSimulator`. This is the HRTF path.
* `-[S3DSound setupPlain]` -> an ordinary `csl::Panner` (a stereo one when
  `channelCount == 2`), mixed straight to the master. **No HRTF at all.**

That split matters: most of the game's audio is flat stereo - narration,
footsteps, ambience - and it was authored to be heard as stereo. The footstep
banks in particular carry their own placement, the left-foot samples leaning
about 1.4 dB left and the right-foot samples 1.5 dB right, which is how you hear
your feet alternate. Putting that through a head-related filter destroys it.

### Original

* CSL graph per sound: `CASoundFile → Butter (low-pass) → gain Mixer → FanOut →
  { drygain → Panner, wetgain → Stereoverb } → master Mixer`
* Spatialised sounds instead go through `csl::Spatializer(kBinaural)` with a
  `csl::SpatialSource`, `csl::DistanceSimulator` and a `csl::BinauralPanner`
  doing real HRTF convolution.
* Listener state: `S3DEngine.headPosition (x,y,z)`, `headOrientation`,
  `distanceScale`, `maxSpatialGain`.
* Reverb is disabled at runtime on pre-4th-generation hardware
  (*"Disabling reverb for Papa Engine - because hardware is less than 4th Gen"*).

### The HRTF — recovered **[R]**

The binary carries an **embedded HRTF database**, read through an in-memory
`MemFile` when no external path is supplied
(*"Using the builtin, embedded default HRTF instead."*).

```
location in binary : 0x100142c54, length 1 541 427 bytes (length word at 0x1002bb188)
extracted to       : tools/embedded_hrtf.dat
header             : "HRTF 1050\t188\t512\t256\t2"
                      name=1050  dirs=188  totalPerDir=512  perEar=256  channels=2
directions         : 188 lines of "<azimuth>\t<elevation>", IRCAM LISTEN grid
                      elevations -45..90 in 15° steps
                      azimuths   0..345 in 15° steps (fewer at high elevations)
payload            : per direction, 4 blocks of 256 8-byte elements
                      = 4 x 256 interleaved complex float32 (re,im) spectra
```

`1050` is IRCAM LISTEN subject **IRC_1050**. Blocks 2 and 3 are the left- and
right-ear transfer functions: inverse-transforming them yields impulse responses
whose onset difference and level difference track azimuth correctly (verified:
left ear leads for azimuths 30–180, right ear leads for 240–330, and the two are
symmetric at azimuth 0). Blocks 0 and 1 are a second, near-impulsive pair whose
role is still **[I]** (probably the ITD/excess-phase component).

This means the port can render with the *exact same* HRTF set the original used.

### Audio assets

| Folder | Files | Content |
|---|---|---|
| `ps1/footsteps` | 352 | per-surface footstep banks, `<prefix>_<s1\|s3>_<L\|R>_<variant>` |
| `ps1/cutscenes` | 69 | intro / win / fail narration, up to 112 s |
| `ps1/spatialized` | 63 | positioned world sounds (doors, notes, exits) |
| `ps1/reactions` | 54 | collection stings, Papa Sangre taunts |
| `ps1/inactive` | 35 | "are you still there" nags |
| `ps1/atmos` | 31 | looping room ambiences |
| `ps1/dilemmas` | 31 | the four rescuable characters + outcome narration |
| `ps1/monsters` | 17 | patrol / aware / chase / not-there / attack loops |

Sounds are named without extension in the data; the per-level `.sexp` playlist
maps a name to its folder, extension, and its `spatialized` flag.

A single `(sound ...)` form may declare **several** `(bundle ...)` entries that
share the form's flags — this is how every footstep bank is written (14 files in
one form for `_footsteps_stone`). Across the 104 playlists there are 982 sound
declarations, all of which resolve to shipped files. Four declarations in
`ps1_13`, `ps1_15`, `ps1_17` and `ps1_18` have an empty `name` and resolve to
nothing; they are inert in the original. **[R]**

### Channel counts **[R]**

Almost everything ships as stereo, including the positioned audio: of the 88
sounds the playlists mark `spatialized`, only 19 are mono on disk. The original
routes a sound file straight into `csl::Spatializer(kBinaural)` regardless -
`channelCount` is inspected only on the *non*-spatialised path
(`-[S3DSound setupPlain]` creates a stereo `Panner` when `channelCount == 2`).
A binaural panner consumes one channel, so the positioned stereo files are
collapsed to mono somewhere inside CSL; which channel, or whether they are
summed, is **[I]**. The port averages them - see PORTING_STATUS.md open
question 11.

Correlation between the two channels of the positioned stereo files: 49 of 69
are above 0.9 (effectively dual-mono, delivered as stereo), and 20 are genuinely
wide, the extreme being `monster_bird_01_dry_chase` at -0.04.

### Footstep selection quirk **[R]**

`moveForwardOneStep:` looks up `<prefix>_<speed>_<foot>` and, failing that,
falls back to the prefix `<prefix>_s`. Because that fallback also matches the
`s1` bank, a surface that ships no `s3` (fast) samples plays a *random* footstep
from its whole bank while running — losing left/right alternation. 54 of the
game's prefix/speed/foot combinations hit this path, all of them `s3` on water,
quicksand, swim and melodic surfaces (`ps1_11`, `ps1_12`, `ps1_16` and others).
The port reproduces the fallback exactly rather than filling the gap.

---

## 9. Enemies **[R]**

`PGEEnemy` extends `PGEGameAgent`. `-[PGEEnemy update:]` is a thirteen-way
switch on `state`, dispatched through a jump table at `0x10001de40`. Decoding
that table gives the whole machine:

| state | name | what it does |
|---|---|---|
| 1 | idle | loop `defaultSound`; `speed = walkingSpeed` |
| 2 | alerted to player | one frame only, falls straight through to 3 |
| 3 | chasing the player | `speed = chaseSpeed`, loop `chaseSound`, walk at the player, remember `positionBeforeChasing` |
| 4 | alerted to a position | one frame only → 5, once `wantedPosition` is set |
| 5 | going to that position | `chaseSpeed`, `chaseSound`, walk at `wantedPosition` |
| 6 | arrived | play `attackSound` or `notThereSound`; run `distractedTimer` up to `distractedTime`, then → 13 |
| 7 | attacking | stop the loop, play `attackSound` once |
| 8–11 | — | unused; the jump table sends them to the tail |
| 12 | alerted to an agent | play `awareSound`, `chaseSpeed`, then `changeStateTo:5` after **1.0 s** |
| 13 | returning | `defaultSound`, `walkingSpeed`, walk back to `positionBeforeChasing`; on arrival → 1 |

Every state does its entry work exactly once, guarded by comparing `state`
against `state_atPreviousFrame`, then its per-frame work.

Arrival is not a distance threshold. The enemy stores `squaredDistanceFromGoal`
each frame and treats **"stopped getting closer"** as having arrived, so an
enemy that overshoots or is blocked still gives up correctly.

### An enemy never notices you by itself **[R]**

There is no proximity check anywhere in `update:`. An enemy is only ever woken
by a message a level trigger sends:

| Message | Reaches |
|---|---|
| `AlertAllEnemies` | every enemy in the level |
| `AlertEnemyWithName` | the one named in `name` |
| `AlertEnemiesWithinRadius` | those closer to the player than `radius` |

Each carries `to` = `player`, `position` or `agent`, an optional `position`, and
an optional `chaseTime`. `-[PGEEnemy alertEnemy:]` **returns immediately if the
enemy is already in state 2 or 3**, so re-alerting something that is already
chasing you changes nothing.

Parameters carried in level data: `speed`, `chaseSpeed`, `distractedTime`,
`chasingRadius`, `collideRadius`, and the sound names `defaultSound`,
`awareSound`, `chaseSound`, `notThereSound`, `attackSound`,
`walkingPauseSound`. Monsters may also follow a `Path` (a Tiled polyline)
through `followPathWithName:` / `findNextPatrolPoint` — the only part of
`PGEEnemy` not yet recovered, and unused before level 5.

### Level 3, "The Kennel" — the design this explains **[R]**

`ps1_3` contains one enemy, `hog1`, and **no trigger in the level sends any
alert**. It therefore never wakes: it sleeps in the middle of the room looping
`monster_hog1_01_dry_still`, spatialised where it lies, and it kills you only if
you walk into it (`collideRadius` 20).

What makes the level playable is the floor. Four `Surface` rectangles are
layered concentrically around the hog at `z = 2`, each with a different
`footstepsPrefix`:

```
foot_stone   →  foot_stone-kennelA  →  foot_stone-kennelB
             →  foot_stone-kennelC  →  foot_kennel
```

so **the ground under your feet tells you how close to it you are**. The hog is
an obstacle to be heard and walked around, not a hunter.

---

## 10. Progression and saving **[R]**

`PGEGameProgress` (a singleton over `NSUserDefaults`) stores:

* `playerDidCompleteLevel:` / `isLevelCompleted:`
* `playerDidUnlockLevel:` / `isLevelUnlocked:` / `lastUnlockedLevel`
* `saveDilemmaStatus:forId:` / `getDilemmaStatus:` — whether each rescuable
  character was saved or abandoned
* `saveSkippableSound:` / `canSkipSound:` — a cutscene may only be skipped once
  it has been heard in full
* `saveLastPlaylist:` / `getLastPlaylist`

The dilemma outcomes feed `-[PGELevel solveDillemas]`, which picks an ending
narration from the binary tree `dilemmaOutcome_<d1>_<d2>_<d3>` (14 recordings in
`ps1/dilemmas/`). Three dilemma choices → eight endings, plus intermediate
nodes.

---

## 11. Faults in the original data that the port must reproduce **[R]**

These were found by `tools/audit.py` and are all real defects in the shipped
game. A faithful port reproduces the *effect* (silently nothing happens), not a
fix.

| Level | Statement | Effect in the shipped game |
|---|---|---|
| ps1_10 | `ActivateAgentWithName:name=atmos_crickets_01` | no such agent in this level — nothing happens |
| ps1_15 | `ActivateAgentWithName:name=chickens` | no such agent — nothing happens |
| ps1_1b | `ActivateAgentWithName:name=FINAL_SWYE_inactive_8sec` | no such agent — nothing happens |
| ps1_20 | `ActivateAgentWithName:name=chicken_launcher_1` | no such agent — nothing happens |
| ps1_25 | `ActivateAgentWithName:name=note1` | no such agent — nothing happens |
| ps1_7 | `ActivateAgentWithName:name=FINAL_Charnel_Win` | no such agent — nothing happens |
| ps1_19 | `DeactivateAgentWithName:chicken_N;afterDelay=20` (x3) | `name=` missing: pair dropped, message fires with no target after 20 s |
| ps1_19 | `ActivateAgentWithName:name=chicken_launcher_3:afterDelay=20` | two colons: whole string becomes the message name → unknown → dropped |
| ps1_19 | `AlertAllAgents:to=player` (x2) | misspelling of `AlertAllEnemies` → unknown message → dropped |
| ps1_10 | `ChangeInactivitySoundlist` | lower-case `l` → unknown message → dropped |
| ps1_11 | `quicksand_edge_atmos1&quicksand_edge_atmos2` as a message | not a message name → dropped |
| ps1_21 | `ChangeInactivitySoundList_soundList=...` | `_` instead of `:` → dropped; level keeps its original nag sounds |
| ps1_24 | `ChangeInactivitySoundList=soundList=...` and a bare sound name | both malformed → dropped |
| ps1_24 | `inactivitySounds = "FINAL_thefatebell_inactive_1\|FINAL_thefatebell_inactive_2"` | `\|` is not the list separator (`&` is) → one unresolvable name → no nag sounds |
| ps1_25 | `inactivitySounds = "Script_Elysium_3&Script_Elysium_4"` | neither asset ships → Elysium has no nag sounds |
| ps1_1b | Room property `foostepsPrefix` (typo for `footstepsPrefix`) | no setter matches → ignored, so that room falls back to the default footstep bank |

Because messages are broadcast and matched by name, every one of these is
naturally a no-op in the port as well — no special-casing needed.

### Sounds that exist but are never declared **[R]**

A second class of defect: the level data names a sound, the audio file ships,
but that level's own `.sexp` playlist never declares it. The engine looks the
name up in the playlist, gets nothing, and the sound is silent in play. Eight of
these:

| Level | Sound | Effect |
|---|---|---|
| ps1_1 | `FINAL_ITD_inactive_all` | the looping "keep going" voice never plays |
| ps1_5 | `atmos_stonedripping_01` | that ambience is missing |
| ps1_7 | `chase_violinTrill` (x3) | the chase sting never sounds |
| ps1_8 | `FINAL_theisland_inactive_18sec` | one nag line missing |
| ps1_21 | `FINAL_glasscathedral_inactive_1`, `_2` | both nag lines missing |

`tools/audit.py` reports these separately from genuinely absent files, because
the distinction matters: the file being present makes them easy to "fix" by
accident.

### Controls Papa Sangre 1 never uses **[R]**

The engine has hands, clapping, jumping and swimming, and Papa Sangre II uses
hands and clapping. **Papa Sangre 1 uses none of them.** Counting the
control messages across all 27 levels:

| Message | Times used |
|---|---|
| `DisableHands` | 27 |
| `EnableHands` | **0** |
| `EnableSwim` / `DisableSwim` | **0** |
| `EnableJump` / `DisableJump` | **0** |
| `EnableWalk` / `DisableWalk` | 25 / 26 |
| `EnableRotation` / `DisableRotation` | 25 / 26 |

So the whole game is walking and turning, and level 1 is walking only — its Room
disables rotation and nothing switches it back on.
