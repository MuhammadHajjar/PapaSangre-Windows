# Divergence register

Every place the port does not do exactly what the original binary does, and why.
One line per item, four verdicts:

| verdict | meaning |
|---|---|
| **INVENTED** | behaviour I added that the original does not have. Should be empty. |
| **REQUESTED** | a change from the original that Muhammad asked for, knowing it is one. §4c. |
| **MISSING** | the original does it, the port does not. Each one is a bug until fixed. |
| **N/A** | the original does it, but it is iOS plumbing with no audible effect. Evidence required. |
| **PORT-SIDE** | scaffolding a keyboard/screen-reader build needs and a touchscreen did not. |

Anything not listed here is a claim that the port matches the binary. That claim
is only as good as the audit behind it, so §5 records exactly how far the audit
has actually got.

---

## 1. INVENTED — must be empty

| item | status |
|---|---|
| 180 degree snap turn on the down arrow | **removed** 2026-09-08. Nothing in the binary has it. |
| `SAME_FOOT_TRIPS` switch | **removed** 2026-09-08. A flag that exists nowhere in the original, used to disable a recovered behaviour. Turning it off silently created fast-walking, a bug in neither the original nor the disassembly. |
| `to=position` fell through to state 12 when the enemy was already distracted | **removed** 2026-09-10. The original does **nothing at all** on that branch (0x10001e428). Mine sent the enemy to `ALERT_AGENT`, which plays `awareSound` and re-schedules `changeStateTo:5` — so on ps1_7's guts, which alert on every step, the roar restarted under your feet. |
| `to=position` / `to=player` set `wantedPosition` from the notification | **removed** 2026-09-10. Only the `agent` branch reads `position`; the other two jump straight to the release at 0x10001e5a4. State 4 sets the goal itself, from `playerPosition` (0x10001dabc). |

Nothing currently outstanding.

## 2. MISSING — the original does it, the port does not

| what | where | status |
|---|---|---|
| Foot alternation (`updateFeetView:` holds the used foot `"off"` for 2 s) | every level | **fixed** 2026-09-08 |
| `playSound:looping:` returns the sound's duration and state 6 feeds it to `setDistractedTime:` (0x10001dc20) — the port kept the level's own `distractedTime`, so an enemy that lost you stood there silent for the balance of it (10 s by default, 90 s in ps1_15) instead of giving up as its grunt ended | every level with an enemy | **fixed** 2026-09-14 |
| The little girl's scream: `dilemma_girl_monsterprox`, **hardcoded in `alertEnemy:`** at 0x10001e274 and named in no level's data, played once per approach off the `withinRadius` edge | ps1_18 | **fixed** 2026-09-14 |
| An enemy in state 6 with no `attackSound` borrows its `chaseSound` and keeps it (`setAttackSound:`, 0x10001d518), playing it looping | ps1_23 | **fixed** 2026-09-14 |
| `PGE_ACTION_Shuffle` and `-[PGEPlayer shuffle]` | every level, 24 assets | **fixed** 2026-09-08 |
| Wall-collision sound: the `@"hitwall"` fallback at 0x100032ea0 | every level (**no level sets `hitWallSound`**) | **fixed** 2026-09-08 |
| `OnLoad` never fired — `-[PGEGameAgent levelInited:]` was not ported | 8 monsters across 7 levels hang their opening move on it | **fixed** 2026-09-08 |
| `-[PGEGameAgent update:]` — the per-frame move + collision check every agent inherits | all agents | **fixed** 2026-09-08 |
| `findDirectionTo:` / `findDirectionToPlayer` — enemies steer, the base class moves | all enemies | **fixed** 2026-09-08 |
| Surface `entered` / `exited` latches: `OnEnter` fires once per level, not once per visit | every level with floor triggers | **fixed** 2026-09-08 |
| `setActive:` acts only on a transition — re-activating an active agent was replaying its intro | every level | **fixed** 2026-09-08 |
| `startTriggerAfterDelay:` posts directly where an immediate trigger enqueues | ordering, every level | **fixed** 2026-09-08 |
| The shuffle's 2 s re-check was scheduled off `bus.now` (last frame) while the foot was stamped with the key-release time, so it landed early and `gap` came out just under 2.0 — the shuffle fired only when the two clocks happened to agree | every level | **fixed** 2026-09-08 |
| `-[PGEPlayer init]` BPM defaults — tripBPM 10000, runBPM 180, pixelsPerStep 1.0; the port had zeros, and `checkStepBPM` returns on its first line when either BPM is zero, so the player never entered the running state | every level | **fixed** 2026-09-08 |
| `applyBPMConstraint:` sets `tripBPM` as well as storing the value | ps1_12, ps1_23 | **fixed** 2026-09-08 |
| **State 7 (ATTACK) did not silence the enemy.** The original sets `speed` to 0, stops the current sound **unconditionally**, and only then plays `attackSound` if there is one - and it does this every frame, with no entry guard. The port only stopped the sound when an `attackSound` existed, so the kennel hog kept looping its grunt beside you all through the failure narration. Related: `playSound:looping:` guards on the **name alone** (0x10001e878), not on whether the sound is still playing, which is what keeps it silent once stopped. | ps1_3 on | **fixed** 2026-09-08 |
| **`-[PGEEnemy collidesWithPlayer]` was not overridden.** `PGEGameAgent` has no "already triggered" latch - it fires `OnCollide` every frame you are inside the radius - and `PGEEnemy` is what provides one: `if (state == 7) return; setSpeed:0; changeStateTo:7; [super collidesWithPlayer]`. Without it the kennel hog re-fired `ShutDownLevel` every frame, and since that deactivates every agent *except the sender*, the failure narration was switched off the frame after it started, never reached `OnSoundEnd`, and the level never reloaded - while the hog, being the sender, kept grunting. Froze the game with a stuck hog. | ps1_3 on | **fixed** 2026-09-08 |
| **The room is the floor, and the port did not know it.** `PGELevel` *is* a `PGESurface`, and `playerMovedToPosition:` starts its search with **self** as the current best floor (0x10003231c); a Surface only takes over by containing the player at a higher `z`. The port treated "on no surface" as a separate case with nothing assigned, so in a level with no Surface objects - ps1_1, ps1_5, ps1_9 and others - the player never received a `tripBPM` at all and could not fall. Fixed by making `Level` a real `Surface` and running one unified path. | every level | **fixed** 2026-09-10 |
| **Falling was impossible.** `-[PGELevel createObjectFromDict:]` gives every Surface (and the Room) a default `tripBPM` of **280** and `runBPM` of **180** when the level data names none (0x100141d24 / 0x100141d1c). The port left them at 0, so no surface ever handed the player a threshold and nothing could trip you | every level with a Surface, i.e. everything from ps1_2 on | **fixed** 2026-09-08 |
| `PGEGameProgress` was not implemented at all - completion, unlocks, `lastLevelUnlocked`, the last playlist, skippable narration and dilemma answers | saves | **built** 2026-09-08, keeping the original's key names including `lastPLaylist` and the backwards `_locked` |
| `pause` / `resume` on `PGEGameAgent`, `PGEPlayer` and `PGELevel` | every level | **built** 2026-09-08 |
| Off-surface property reset (my own addition) — the original assigns `tripBPM` / `runBPM` / `tripSound` / `shuffleSound` **only** inside the surface branch | every level | **removed** 2026-09-08 |
| `-[PGEEnemy init]` defaults — chaseSpeed 15, walkingSpeed 10, distractedTime 10, chasingRadius 200; the port had zeros, so an enemy whose data named no speed would never move | every enemy from ps1_5 on | **fixed** 2026-09-08 |
| `followPathWithName:` / `findNextPatrolPoint` / `stopFollowingPath:` / `triggerOnPathEnd` / `pathWithName:` — the patrol-route system | first needed ps1_5 | **built** 2026-09-09 |
| **IDLE was overwriting the level's patrol speed.** The port's state 1 did `speed = walkingSpeed`; the original's IDLE touches only the sound, and `walkingSpeed -> setSpeed:` appears **once**, in state 13. A hog authored at 36.6 was patrolling at 10. | every monster with a `speed` | **fixed** 2026-09-09 |
| **State 6 (AT_POSITION) did not stop the enemy.** `setSpeed:0` at 0x10001d4d4 is what holds a searching enemy still. | ps1_4 on | **fixed** 2026-09-09 |
| The `speed` property was mirrored into `walking_speed` | all agents | **fixed** 2026-09-09 — the original applies level properties by KVC, which sets `speed` alone |
| `PGEDilemma` and `solveDillemas` - the dilemma system and its fourteen endings | ps1_7, 12, 18, 23 | **built** 2026-09-10 |
| **Dilemma sounds did not loop.** `-[PGEDilemma playSound:]` ends `play:` with `mov w2, #1` (0x1000457c8) — the same looping flag `PGECollectible startLoop` passes, and the opposite of the one-shot `hitwall`. The baby called once and went silent. | ps1_7, 12, 18, 23 | **fixed** 2026-09-10 |
| `shouldAttackOnWantedPosition` — set by state 12 (0x10001d798), cleared by state 4, and the thing that makes states 5/6 refuse every alert (0x10001e140) | all enemies | **fixed** 2026-09-10 |
| State 4 was a no-op. The original plays `awareSound`, aims at `playerPosition`, and latches `hasWantedPosition`. | ps1_4 on | **fixed** 2026-09-10 |
| **`hasWantedPosition` is never re-armed, so every alert after the first re-snarled.** The latch is set at 0x10001dbb4 — `strb w8, [x19, x22]`, w8 = 1 — and `x22` still holds the offset loaded for the *test* at the top of state 4, 2300 bytes earlier. Because the store carries no ivar annotation, searching for writers of the name finds none, and I concluded the flag was dead. It is not: it is what makes the second and later alerts take the silent re-aim branch instead of playing `awareSound` again. **This was the guts bug.** | ps1_7 above all | **fixed** 2026-09-10 |
| State 5 had an entry guard the original does not have — it asks for `chaseSound` and `chaseSpeed` on every frame (0x10001d338), which is what makes a silent re-aim inaudible | ps1_4 on | **fixed** 2026-09-10 |
| State 6 expiry went to `RETURNING`. Both branches at 0x10001dd18 change state to **1**, one of them resuming the patrol; a hog alerted to a place never walks home. The test at 0x10001dccc is a strict `>`, and `distractedTime <= 0` means it never gives up at all. | ps1_4 on | **fixed** 2026-09-10 |
| **Reverb ran on `S3DEngine`'s init values, not the ones the game uses.** `-[PGEngine init]` overrides all three afterwards — roomSize 2.1 (clamped up to the setter's 2.2 floor), dampening **5**, volume 1 — where the port had 1.5 / 50 / 1. Every level was drier and duller than the original. | every level | **fixed** 2026-09-11 |
| `PGE_MESSAGE_PresentAdiosVC` — the end of the game. `-[PGEViewController viewDidLoad]` observes it and presents `PGEAdiosViewController` + `playMenuAtmos`; both of ps1_25's doors send it | ps1_25 | **built** 2026-09-11 — no view controllers here, so it means "no next level, the game is over" |
| `PGEGameProgress` (completion, unlocks, skippable sounds, last playlist) | menus/saves | open — phase L |
| `startToJump` / `updateJump` / `landFromJump`, `startToSwim` | no level enables jump or swim (0 uses of `EnableJump`/`EnableSwim`) | open — unreachable content, low priority |

## 3. N/A — present in the binary, silent in effect

| what | evidence |
|---|---|
| `PGE_MESSAGE_StartFullWheelRotation` (ps1_1b) | `startFullWheelRotation` runs a 1/22.5 s timer 360 times calling `rotateDialVisualByAngle:`, which is a `CGAffineTransformRotate` on `dialImageView`, a `UIImageView`. No player rotation, no audio. |
| `isInfinite` toroidal wrap in `playerDidCollideAWall:` | wraps the player to the far edge instead of playing the thump. **No level sets `isInfinite`**, so the branch is dead in the shipped game. |
| Same-foot `PGE_ACTION_Trip` (0x1000088c4 / 0x100008968) | real code, unreachable: tripping needs a same-foot release inside 1.0 s, but the `"off"` gate holds that foot for 2.0 s and both press and release return early on it. Kept exact in `trip_would_fire()`; a test asserts no press sequence reaches it. |
| `updateHandsView:`, `handButtonPressed:`, `handsClapped:` | `EnableHands` is used 0 times across all 27 levels (`DisableHands` 27 times). Papa Sangre 1 never switches hands on. |
| `sendDidMoveMessage` → `PGE_MESSAGE_AgentDidMove` | posted by three classes, **observed by none**. Telemetry for the on-screen debug map. |
| `PGE_MESSAGE_RoomInited` | posted in `loadLevelStructure:`, observed by nothing. |
| `-[PGESound onDoubleTap]` | a touch gesture. |
| `PGEDilemma.bpmMalus` | in the class and in ps1_7's data (50), but **nothing in the binary reads it** - only its own getter and setter exist. Dead data from an earlier design; the price of the baby is its `OnCollide`. The port parses and stores it, and uses it for nothing. |
| `PGELevel startAlarm:` and the whole `PGEAlarm` class | **no level sends the message.** |
| `PGEGameProgress isLevelCompleted:` | the selector has **no entry in `__objc_selrefs`** - nothing in the binary ever calls it. The port implements it anyway, since the companion write does get called. |
| `PGEngine`'s `win` / `lose` branch, which is what calls `playerDidCompleteLevel:` and `playerDidUnlockLevel:` | `loadLevelWithName:` special-cases the names `win` and `lose`, but **every `LoadLevelWithName` in all 27 levels names a real level** (`ps1_4`, `ps1_1b`, …). The win/lose path is driven by the menu layer, so progression is recorded there, not during play. Storage implemented; call sites are phase L. |
| `sendActivityChangedMessage` | posted, observed by nothing - like `AgentDidMove`. |
| `PGEPlayerListener` (`playerStartsToRun:`, `playerDidTrip:`, `playerDidCollideAWall:` -> `OnStartToRun`, `OnTrip`, `OnWallCollide`, `OnDeath`) | a real object the level owns, turning player events into triggers. **No level in the game defines any of those four trigger types**, so it has nothing to fire. Not built. |
| The whole shooting group (`playerDidShoot:`, `wasShot`, `wasMissed`, `triggerOnShoot`, `triggerOnShootMissed`) | two independent proofs. **Every `OnShoot` in the game's data is an empty string**, on unnamed template Monsters in ps1_1, ps1_1b, ps1_7 and ps1_11. And `PGE_ACTION_Shoot` is posted from exactly one place, `-[PGEMoveInterpretor handButtonPressed:]`, which returns early unless `playerCanUseHands` — never true in this game. |
| `PGEForgetfulMan` and its `updateWhiteNoise` | the type is never used by any level (0 of 27). |
| `PGEActionSurface` / `triggerOnButtonPressed` | never used by any level. |
| `NPC`, `Comment` and untyped objects, and the unnamed `Monster`s | all editor template leftovers: the four NPCs carry no properties at all, `Comment` carries only the designer's `Goal` note, and the unnamed Monsters carry only an empty `OnShoot`. The port's loader drops them; the original would build inert, inactive objects. |
| `activateEnemy:` | a named-activation handler routed through `setActive:`; no level sends its message. |
| `incrementCollectibles` on `PGEGameTracker` | Flurry telemetry, nothing audible. |
| `OnExitJumping` / `OnExitNotJumping` | implemented and split on player state 4, but **no level uses either trigger**, and no level enables jumping. |
| All `PGE*ViewController` touch/nib/gyro/tilt/swipe code | screen and touch handling with no audio consequence. |
| Level-data keys `Goal`, `SoundList`, `collisionRadius` | none of the three appears anywhere in the binary. `Goal` is a designer's note; the real keys are `soundList` and `collideRadius`, so these are typos the original ignores too. The port ignores them identically. |
| `foot_stone_*` declared but unreachable in ps1_1b | ps1_1b never posts `EnableWalk` (0 uses) — it is the turning-only tutorial. The sounds arrive through a shared playlist include and cannot play in the original either. |

## 4. PORT-SIDE — keyboard and screen-reader scaffolding

A touchscreen swipe and a pair of foot pads have no keyboard equivalent, so
these exist only in the port. None of them changes game logic.

| what | note |
|---|---|
| Turn rate 120 deg/s while a key is held, adjustable in Options | the original turned by swiping, so there is no rate to recover |
| Master volume keys and `AudioEngine.master_volume` | no original counterpart |
| P pauses and resumes | the original paused on a triple-tap, which a keyboard has no equivalent for. Escape already quits, so pause gets its own key |
| Spoken control announcements before each level | ditto |
| `Run\Start at level N.cmd` launchers | convenience, no effect in-game |
| Reverb: OpenAL Soft EFX rather than `csl::Stereoverb` | the two models are not equivalent; needs matching by ear |
| HRTF: makemhr minimum-phase + delay rather than direct convolution | measured: 8-sample ITD at 180 deg vs 3 in the raw data |
| Distance attenuation, and the beacon trim | `csl::DistanceSimulator` is the original's attenuator and **its methods are stripped from the binary**, so its curve cannot be recovered - only the STL containers holding it survive as symbols. Two port-side consequences, both measured: `reference_distance` was 1.0, which with a distance scale of 0.008 meant **nothing within 125 px attenuated at all**, so every spatialised source sat pinned at full gain across most of a room; it is now 0.5. And `COLLECTIBLE_LOOP_GAIN` trims the homing beacon by ~4 dB, because this game masters nearly everything near full scale (doors -0.8 dBFS, monsters -1.6, narration -3.9) while footsteps sit at -15.8 and are then halved - and the beacon is the only one of those that plays *continuously*. Measured effect on an approach in ps1_2: 4-7 dB quieter through the mid-field, worst peak -1.5 -> -3.8 dBFS. Every recovered per-sound gain is untouched. |
| Stereo to mono downmix for positioned sounds | the original feeds one channel to `csl::Spatializer`; which channel is not recovered. Port averages; worst measured change -3.7 dB. `AudioEngine.mono_policy` switches to channel 0. |
| Agent collision timing, reproduced not corrected | `-[PGEGameAgent playerMovedToPosition:]` checks collisions **before** storing the new player position, and skips the check entirely while either stored coordinate is exactly `0.0`. Both are faults; both are now reproduced. The per-frame base `update:` is what stops the first one mattering. |
| `active` as a plain attribute rather than a property | `-[PGEGameAgent setActive:]` is a custom setter calling `activate`/`deactivate` on a transition, re-entering itself once harmlessly. The port keeps `active` a plain flag and puts the transition guard in the two message handlers, where the original's guard effectively sits. Same behaviour, different shape. |

## 4b. FAITHFUL BUT ODD — the original's own bugs, reproduced

These are places where the shipped game does something that sounds wrong.  The
port reproduces them because the rule is "no difference", but each one is a
decision waiting on Muhammad, not a claim that it is good.

### The trip sound is picked at random, not per ground

`-[PGEPlayer trip:]` (0x100027360) builds the prefix exactly the way
`-[PGEPlayer shuffle]` does:

```
0x100027480   x19 = self->footstepsPrefix ?: @"foot_racetrack"
...
0x10002777c   objc_release(x19)          <- and that is the only other use
```

It is computed, retained, and released. **Never read.** `shuffle` finishes the
job with `[NSString stringWithFormat:@"%@_shuffle", prefix]` (0x10002622c);
there is no `@"%@_trip"` anywhere in the binary. What `trip:` does instead:

* `tripSound` set and non-empty → `[playlist S3DSound: tripSound]`;
* otherwise → `[playlist anySoundContaining:@"trip"]`.

`S3DSound:` is an **exact** name lookup. `anySoundContaining:` is not: it goes
to `anySoundMatchingPredicate:`, collects every sound whose key contains the
substring, and picks one with **`arc4random`** (0x1000d331c).

`tripSound` has exactly one writer — `-[PGELevel playerMovedToPosition:]` at
0x100032648 — which copies it off the surface underfoot, or assigns `@""` when
that surface names none. **Four levels do name one**, so the good path is real
and used:

| level | `tripSound` |
|---|---|
| ps1_2 | `FINAL_soulmusic_tripped_1` (on the **Room**, not a Surface) |
| ps1_3 | `foot_stone-kennel_trip` — all four kennel rings |
| ps1_11 | `foot_sand-water_trip` |
| ps1_12 | `foot_reeds-water_trip` |

ps1_7 names none. Its playlist pulls in both `_footsteps_stone` and
`_footsteps_guts` (flattened into one list by `-[S3DEngine staticPlayLists]`,
0x1000d1828), so both `foot_stone_trip` and `foot_guts_trip` match "trip" and
you get a coin flip on every fall.

**Verdict: reproduced.** This is an authoring gap in ps1_7's map data, not a
dead code path — the engine supports exactly what Muhammad expects and three
other levels use it. Two possible fixes, neither taken without his say-so:
add `tripSound` to ps1_7's six surfaces (edits the original level data), or
restore the missing `stringWithFormat:@"%@_trip"` the discarded prefix was
plainly meant for (edits engine behaviour on every level that names none).

### The one-second wind-up in state 4 is dead code

State 4 schedules `changeStateTo:5` with `afterDelay:1.0` (0x10001da80), which
reads like a deliberate head start. It never elapses: the same frame latches
`hasWantedPosition`, and on the very next frame the other branch of state 4
changes the state immediately. The delayed call lands a second later on an
enemy that moved on long ago. **Reproduced, dead code included** — the snarl
gets about two frames before the roar takes over.

## 4c. REQUESTED — asked for, knowing it is a change

The places the port deliberately does not sound like Papa Sangre.

### Walking away from a lost soul leaves them resting again

**The original has no way out of state 8.**
`-[PGEDilemma checkCollisionsWithPlayer]` only ever moves 9 (alert) to 8
(abandoned) — 8 is reachable from 9 and nowhere else — and `playSound:` ends
in `play:` with `mov w2, #1` at 0x1000457c8, so every dilemma sound loops.
Once you had been near the baby, the old man, the girl or the siren, they
called after you for the rest of the level.

Reported by a player on 2026-09-14 and asked for on 2026-09-15: the abandoned
line now gets **one play**, timed by its own duration, and then they go back to
the resting loop they started on. Which also means the aware loop is only ever
heard inside `alertDistance`, where it belongs. Re-entering the radius
interrupts it the ordinary way, because state 9 is set before the check runs.

This is the only dilemma sound that does not loop.

### ps1_17's third note is given a voice

`note3` in *Papa Sangre Says* is the **only collectible in the game with an
empty `loopSound`**, and ps1_17's playlist is the only one of the five brass
levels that does not carry the d note at all. Every sibling — 13, 14, 15, 16,
18 — gives its third note `note_brass_01_dry_d_living_+5`. So the note is
there and cannot be heard: you follow the summoner's voice onto a thing that
makes no sound. The port reproduced that faithfully until a player reported
it. `Level.apply_missing_third_note` now hands the note the file its siblings
use, the same way the telephone door is handed one.

**This is a bug in the original's data, and filling it in is a change.**

### A level shutdown sweeps until nothing is left running

`deactivate` fires an agent's `OnDeactivate` whether or not it was ever active
(0x10002049c is an unconditional tail call), and those triggers activate other
agents — ps1_23's `chicken_1` re-arms the cage launcher every time it goes
quiet. When that lands on an agent the shutdown has already passed, the agent
comes back to life behind the sweep and its loop plays on over the closing
narration. A player hit exactly that at the ice lake exit with the chickens
still caged.

The original walks `agentArray` once (0x1000347e4) and nils each agent's
delegate afterwards, but that delegate gates only a collectible's *collect*
sound — the sole game-side read of it is in `playCollectSound` — so it is not
what would silence a loop. Rather than leave a looping alarm running into the
next level, `_on_shut_down` repeats the sweep while anything is still active.

### Feet step on key-down, not key-up

**The original steps on release.** `-[PGEMoveInterpretor footButtonPressed:]`
only marks the foot `"pressed"`; the step — the `PGE_ACTION_OneStep` post, the
timestamp, `lastFootButtonPressed` — is all in `footButtonReleased:`. On a
touchscreen that is the natural shape: your thumb is already on the foot and
lifting it is the deliberate act.

Proposed by masonasons on 2026-09-14 and taken after playing it on
2026-09-15: with A and D under your fingers, waiting for the key to come back
up puts a hold-length delay between the keystroke and the footfall you hear.

**What the port does now.** The key-down handler runs `foot_pressed` and, if it
is allowed, `foot_released` immediately after, with the key-**down** timestamp.
Key-up no longer does anything. `MoveInterpretor` itself is unchanged — the
alternation gate (`"off"` for 2 s), the shuffle, the clamp and the dead trip
branch all still run exactly as recovered — so the only thing that moves is the
instant the foot lands. You still cannot walk by hammering one key.

Both `apps/play.py` and `apps/walk_in_the_dark.py`; it applies to the
controller's feet too, since they feed the same action stream.

### Outdoor levels get their own reverb

**The original has one reverb for the entire game.** Evidence, gathered before
changing anything:

* no playlist declares a reverb field — the complete set of sexp keys is
  `name`, `path`, `extension`, `bundle`, `sound`, `spatialized`,
  `unloadonstop`, `playlist`, `repeat`, `preload`;
* no level property names one, and there is not a single string literal
  containing "reverb" in the binary;
* the three parameters have exactly two writers, both engine `init`
  (`-[S3DEngine init]` 1.5/1.0/50, then `-[PGEngine init]` 2.1/1.0/5 which
  runs second and wins);
* the only conditional is `disableReverb`, called from `-[PGEngine init]`
  behind a hardware test logging *"Disabling reverb for Papa Engine - because
  hardware is less than 4th Gen"* — so on modern hardware it is simply on.

So the island in ps1_8 was reverberated exactly like the cellar in ps1_1.
Muhammad asked whether that was authentic, was told it was, and asked for it
to be changed anyway (2026-09-11): *"leave reverb settings as they are, but for
outdoor make a custom reverb, and if not doable then no reverb for outdoors"*.

**What the port does now.** Indoor levels are untouched — they get the
original's setting exactly. Open-air levels get one of two added profiles,
selected in `config/audio.json` (`outdoorReverb`):

| profile | character | measured tail vs indoor |
|---|---|---|
| `outdoor` (default) | EAX "plain": low density, almost no early reflection, so the tail reads as distance rather than walls | 6.6 % |
| `dry` | no tail at all — the fallback he asked for | 4.0 % |
| `indoor` | puts the original back on every level and undoes this entirely | 100 % |

**Which levels.** Decided by the ground underfoot, not a list of names, so a
level answers for itself — `papasangre/world/ambience.py`. A level is outdoors
only when *every* ground it names is an outdoor one, so a hut in a field stays
indoors. That gives ps1_8–12 (the marshes), ps1_19, 20, 22, 23 (the ice) and
ps1_25 (the fields); a test asserts exactly that set and that no
`footstepsPrefix` in any of the 27 maps is left unclassified.

### A controller, a menu, and an options screen

Asked for on 2026-09-11. The original was a touchscreen game: no controller
support of any kind, and its menus are iOS nibs.

**What is recovered and kept.** The level list is not invented - it is the
game's own `Exports/Papa Sangre_hubList.plist`, read in `positionInMenu` order,
using `altName` for the spoken name, and said with the two formats that are
literally in `-[AccessibleAllLevelsViewController tableView:cellForRowAtIndexPath:]`:

```
"Play Level %i: %@"        unlocked
"Level %i: %@; locked"     not
```

Only `ps1_1` is `unlocked` in the plist; everything else comes from
`PGEGameProgress`, which is what that class does too. The main menu's rows are
the ones `-[PGEViewController ...]` logs — *Continue button pressed*, *Level
selection pressed*, *Accessibility level selection pressed*, *Credits button
pressed* — minus **Cast** and **More Games**, which are App Store links with no
meaning off an iPhone. The credits line is the binary's own, typo included.

**What is added.**

| addition | why |
|---|---|
| Controller: d-pad = feet, right stick = turn, A select, B back, Start pause | asked for. The feet are on the **hat**, not a stick, because a step is a discrete press and the engine times the interval between them |
| Every key **and every controller button** rebindable, each with a restore-defaults row | asked for. Buttons are stored by SDL's own names (`a`, `dpleft`), never by raw number, so a binding made on one pad still means the same button on another |
| Options: volume, turning speed, keys, controller buttons | asked for. The original had no options screen at all: volume was the iOS hardware volume, and the only sensitivity slider in the binary belongs to `PGEStepsWithHeightViewController`, a control scheme Papa Sangre 1 never switches on |
| Pause menu | the original paused on a triple-tap and had no menu behind it |

Turning speed is stored in `config/settings.json`; key bindings in
`config/keys.json` and controller bindings in `config/controller.json`, each
carrying a version so a file written by an older build is replaced rather than
silently overriding a default that has moved; volume stays where the audio
engine already kept it, in `config/audio.json`. **Bug found while doing this:**
`save_master_volume` wrote that file with a single key, which would have wiped
the `outdoorReverb` setting added earlier the same day. It merges now, and a
test holds it to that.

## 5. How far the audit has actually got

Sweeps that are complete and mechanical, so they can be re-run (`tools/coverage.py`,
and the sweep scripts described in PORTING_STATUS.md):

* **Level property keys** — 47 distinct keys across all 27 levels; the port
  handles 44; the other 3 are the typos in §3. **Clean.**
* **Messages fired by level triggers** — 13 distinct; the port handles 12; the
  13th is `StartFullWheelRotation` in §3. **Clean.**
* **Trigger types** — 10 distinct (`OnEnter`, `OnSoundEnd`, `OnCollide`,
  `OnStep`, `OnLoad`, `OnActivate`, `OnShoot`, `OnExit`, `OnEnteringShootRange`,
  `OnDeactivate`); all 10 are named in the port. `OnShoot` is *named* but its
  behaviour is unread — see §2.
* **Asset reachability** — every sound each playlist declares, against every
  name a port code path can produce. This is the sweep that would have caught
  the shuffle. Remaining unexplained entries are all in levels 4+ and are listed
  in §2.

The method-by-method pass is **done**. What remains is whole subsystems, not
unread methods:

* **Method-by-method reading of the ported classes.** `tools/coverage.py`
  lists 167 behaviour methods and flags which have no counterpart by name, but a
  name match is not a logic match - `updateFeetView:` had a counterpart and was
  still wrong. Each one has to be read on both sides. Read and reconciled so far:

  | class | state |
  |---|---|
  | `PGEMoveInterpretor` | complete |
  | `PGEObjectWithTriggers` | complete |
  | `PGESurface` / `PGEActionSurface` | complete |
  | `PGECollectible` | complete |
  | `PGESound` | complete |
  | `PGEGameAgent` | complete |
  | `PGEEnemy` | complete |
  | `PGEPlayer` | complete |
  | `PGELevel` | complete |
  | `PGEDilemma` | complete |
  | `PGEGameProgress` | complete |
  | `PGEPlayerListener` | complete - read, and N/A (no level defines its triggers) |
  | `PGEngine` | read as far as `loadLevelWithName:`; the rest is menu/hub flow, phase L |

  `tools/coverage.py` now reports **124 of 124** behaviour methods implemented.
  What remains is the menu/hub layer (phase L) - the win/lose flow, the level
  select and the save-game screens - and nothing else.
