"""``PGELevel`` - one playable area, its agents, and the loop that runs them.

Load order is the original's three passes: the ``Room`` first (it defines the
world's origin and the level rectangle), then every agent, then the player.

Per player move, ``-[PGELevel playerMovedToPosition:]``:

1. reset the inactivity clock;
2. start from the level's own ``footstepsPrefix``;
3. find every ``Surface`` whose rectangle contains the player and keep the one
   with the **highest z**;
4. fire ``OnEnter`` if that surface's id differs from the one the player was on,
   otherwise ``OnStep``;
5. copy the surface's ``tripBPM`` / ``runBPM`` / ``tripSound`` onto the player,
   but only where they are greater than zero - a surface that does not specify
   one leaves the previous value alone.

The inactivity nag is the same clock: when nothing has happened for
``inactivityTime`` seconds the level plays the next sound from its list, pushes
the clock forward by that sound's own duration so it cannot retrigger during
playback, and advances to the next sound, wrapping at the end.
"""

from __future__ import annotations

import os
import random

from ..assets.tiled import LevelData, load_level
from ..audio.bank import SoundBank
from ..core.messages import MessageBus, Params
from ..core.triggers import TriggerHost
from ..entities.agent import GameAgent
from ..entities.collectible import Collectible
from ..entities.dilemma import Dilemma
from ..entities.monster import Monster
from ..entities.player import STATE_JUMPING, Player
from ..entities.sound_agent import SoundAgent
from .ambience import configured_outdoor_profile, reverb_profile_for
from .surface import (DEFAULT_RUN_BPM, DEFAULT_TRIP_BPM,
                      Surface, _f, _i)

#: Object types the port creates.  Papa Sangre 1 uses only these; the remaining
#: engine types belong to the other two games that share the engine.
AGENT_CLASSES = {
    'Sound': SoundAgent,
    'Collectible': Collectible,
    'Monster': Monster,
    'ForgetfulMan': Monster,      # PGEForgetfulMan is a PGEEnemy subclass
    'Dilemma': Dilemma,
}

#: What ``playerDidCollideAWall:`` falls back to when ``hitWallSound`` is unset -
#: which is every level in the game.  0x100032ea0.
DEFAULT_HIT_WALL_SOUND = 'hitwall'
HIT_WALL_WET_GAIN = 0.5           # fmov s0, #0.5 at 0x100032ee0


class Level(Surface):
    """A loaded level: geometry, agents, player, and the update loop."""

    def __init__(self, bus: MessageBus, bank: SoundBank,
                 progress=None, rng: random.Random | None = None) -> None:
        # PGELevel *is* a PGESurface, and that is not a detail: the level is
        # the floor you are standing on whenever no smaller surface covers you,
        # which is how a room's own tripBPM, footstepsPrefix and shuffleSound
        # reach the player at all.  See _on_player_moved.
        super().__init__(bus, rect=(0.0, 0.0, 0.0, 0.0), surface_id=0,
                         z=0, name='')
        self.bank = bank
        self.progress = progress
        self.rng = rng or random.Random()

        self.data: LevelData | None = None
        self.agents: list[GameAgent] = []
        self.floors: list[Surface] = []
        #: PGELevel.pathArray - patrol routes, by name.
        self.paths: dict[str, list[tuple[float, float]]] = {}
        self.player: Player | None = None

        # footsteps_prefix, trip_bpm, run_bpm, trip_sound and shuffle_sound all
        # come from Surface now, with the loader's own defaults.
        self.hit_wall_sound = ''

        self.inactivity_time = 0.0
        self.inactivity_sounds: list[str] = []
        self.current_inactivity_sound = 0
        self.last_activity = 0.0
        self._inactivity_sound = None

        self._last_update = 0.0
        self.shutting_down = False
        self.paused = False
        #: Deliberate divergence: which profile the open-air levels get.
        #: 'outdoor' for the custom one, 'dry' for no tail at all.
        self.outdoor_reverb = configured_outdoor_profile()
        self.reverb_profile = 'indoor'
        self.next_level: str | None = None
        self.finished = False
        #: ps1_25 only: the game itself is over, not just this level.
        self.game_complete = False

        for msg, handler in (
            ('PGE_INTERNAL_EnemyState', self._on_enemy_state),
            ('PGE_MESSAGE_PlaySpatialSound', self._on_play_spatial_sound),
            ('PGE_MESSAGE_ChangeInactivityTime', self._on_change_inactivity_time),
            ('PGE_MESSAGE_ChangeInactivitySoundList', self._on_change_inactivity_list),
            ('PGE_MESSAGE_LoadLevelWithName', self._on_load_level),
            ('PGE_MESSAGE_ShutDownLevel', self._on_shut_down),
            ('PGE_MESSAGE_PresentAdiosVC', self._on_present_adios),
            ('PGE_MESSAGE_PlayerMovedToPosition', self._on_player_moved),
            ('PGE_MESSAGE_PlayerDidCollideAWall', self._on_wall),
        ):
            bus.subscribe(msg, handler)

    # ------------------------------------------------------------- loading
    def load(self, path: str, name: str | None = None) -> 'Level':
        data = load_level(path, name)
        self.data = data
        self.name = data.name
        self.rect = data.rect

        # pass 1: the Room
        room = data.room
        if room is not None:
            self.apply_room(room)

        # pass 2: agents and surfaces
        for obj in data.objects:
            if obj.type in ('Surface', 'ActionSurface'):
                s = Surface(self.bus, obj.rect or (obj.x, obj.y, obj.width, obj.height),
                            surface_id=len(self.floors) + 1, name=obj.name)
                s.apply_properties(obj.settable)
                s.add_triggers(obj.triggers)
                self.floors.append(s)
            elif obj.type in AGENT_CLASSES:
                cls = AGENT_CLASSES[obj.type]
                a = cls(self.bus, name=obj.name, position=(obj.x, obj.y),
                        bank=self.bank, level=self)
                a.apply_properties(obj.settable)
                a.add_triggers(obj.triggers)
                self.agents.append(a)
            elif obj.type == 'Path':
                self.paths[obj.name] = list(obj.polyline)

        # pass 3: the player
        if data.player is not None:
            p = Player(self.bus, level=self, rng=self.rng)
            p.playlist = self.bank
            p.position = (data.player.x, data.player.y)
            p.pixels_per_step = _f(data.player.properties.get('pixelsPerStep'), 5.0)
            # Only footstepsPrefix comes from the level: playerMovedToPosition:
            # re-seeds it from `self` on every move, and the other four are
            # assigned solely from a Surface.  No Room in the game sets tripBPM,
            # runBPM or shuffleSound anyway, and the single Room tripSound -
            # ps1_2's FINAL_soulmusic_tripped_1 - arrives the ordinary way,
            # because the level *is* the surface you are on when nothing
            # smaller covers you.
            p.footsteps_prefix = self.footsteps_prefix
            p.add_triggers(data.player.triggers)
            p.set_start_angle(_f(data.player.properties.get('startAngle'), 0.0))
            self.player = p

        self.apply_reverb_profile()
        self.apply_telephone_door()
        self.apply_missing_third_note()

        # -[PGELevel actuallyLoadDataFromJsonFile] posts this once the three
        # passes are done; every agent answers it by firing its OnLoad.
        self.bus.post('PGE_MESSAGE_LevelInited', {'name': self.name})
        return self

    # ------------------------------------------------------- telephone door
    #: The beacon you home in on to leave a dilemma level.  ps1_7's door is a
    #: ringing telephone; ps1_12, 18 and 23 got ordinary doors - a balloon, a
    #: vacuum and a castle - which is an inconsistency in the shipped data
    #: rather than a design.  REQUESTED: make all four ring.
    TELEPHONE_DOOR = 'door_telephone_living'
    TELEPHONE_PATH = 'ps1/spatialized/door_telephone_living.m4a'

    def apply_telephone_door(self) -> str:
        """Give a dilemma level's exit the telephone beacon.

        **Not the original's behaviour** - see DIVERGENCES.md.  Only ps1_7
        declares the sound, so the other three levels have to be handed the
        file directly; if it is missing the door is left exactly as it was.
        """
        from ..entities.dilemma import Dilemma                   # noqa: PLC0415
        if not any(isinstance(a, Dilemma) for a in self.agents):
            return ''
        door = None
        for a in self.agents:
            if not isinstance(a, Collectible):
                continue
            if any('ShutDownLevel' in str(t.notification_name)
                   for t in a.triggers):
                door = a
                break
        if door is None or door.loop_sound == self.TELEPHONE_DOOR:
            return ''
        ensure = getattr(self.bank, 'ensure', None)
        if ensure is None or not ensure(self.TELEPHONE_DOOR,
                                        self.TELEPHONE_PATH, True):
            return ''
        door.loop_sound = self.TELEPHONE_DOOR
        return self.TELEPHONE_DOOR

    # ------------------------------------------------------ ps1_17's note3
    #: ps1_17's ``note3`` is the only collectible in the whole game with an
    #: empty ``loopSound``, and ps1_17's playlist is the only one of the five
    #: brass levels that does not carry the d note at all.  Every other level
    #: in that set - 13, 14, 15, 16, 18 - gives its third note
    #: ``note_brass_01_dry_d_living_+5``.  So the note is there, and audibly
    #: is not: you follow the summoner's voice onto a thing you cannot hear.
    #:
    #: **This is a bug in the original's data, and filling it in is a
    #: divergence** - the port reproduced the silence faithfully until a
    #: player reported it.  See DIVERGENCES.md.
    THIRD_NOTE_LEVEL = 'ps1_17'
    THIRD_NOTE_AGENT = 'note3'
    THIRD_NOTE = 'note_brass_01_dry_d_living_+5'
    THIRD_NOTE_PATH = 'ps1/spatialized/note_brass_01_dry_d_living_+5.m4a'

    def apply_missing_third_note(self) -> str:
        """Give ps1_17's third note the voice its siblings all have."""
        if self.name != self.THIRD_NOTE_LEVEL:
            return ''
        note = None
        for a in self.agents:
            if isinstance(a, Collectible) and a.name == self.THIRD_NOTE_AGENT:
                note = a
                break
        if note is None or note.loop_sound:
            return ''
        ensure = getattr(self.bank, 'ensure', None)
        if ensure is None or not ensure(self.THIRD_NOTE,
                                        self.THIRD_NOTE_PATH, True):
            return ''
        note.loop_sound = self.THIRD_NOTE
        return self.THIRD_NOTE

    # ---------------------------------------------------------- reverb
    def apply_reverb_profile(self) -> str:
        """Pick a reverb for this level from the ground it puts you on.

        **Not in the original**, which has one reverb for the whole game and no
        notion of being outdoors at all - see ``papasangre.world.ambience`` and
        DIVERGENCES.md.  Indoor levels get the original's setting untouched.
        """
        grounds = [s.footsteps_prefix for s in self.floors]
        grounds.append(self.footsteps_prefix)
        profile = reverb_profile_for(grounds, self.outdoor_reverb)
        self.reverb_profile = profile
        engine = getattr(self.bank, 'engine', None)
        setter = getattr(engine, 'set_reverb_profile', None)
        if setter is not None:
            setter(profile)
        return profile

    def path_with_name(self, name: str):
        """``-[PGELevel pathWithName:]`` - the route an agent asks to walk."""
        return self.paths.get(name)

    def apply_room(self, room) -> None:
        props = room.settable
        self.apply_properties(props)          # the Room's surface half
        self.hit_wall_sound = str(props.get('hitWallSound', ''))
        self.inactivity_time = _f(props.get('inactivityTime'))
        self.set_inactivity_sounds(props.get('inactivitySounds', ''))
        self.add_triggers(room.triggers)

    def set_inactivity_sounds(self, value: str) -> None:
        self.inactivity_sounds = [n for n in str(value or '').split('&') if n]
        self.current_inactivity_sound = 0

    # ------------------------------------------------------------- running
    def start(self, now: float = 0.0) -> None:
        """Fire the Room's ``OnEnter`` and activate whatever starts active."""
        self.last_activity = now
        self._last_update = now
        self.bus.update(now)
        self.trigger_on_enter()
        self.bus.update(now)
        for a in self.agents:
            if a.active:
                a.active = False        # activate() sets it and fires OnActivate
                a.activate()
        self.bus.update(now)

    def update(self, now: float) -> None:
        if self.paused:
            return
        dt = max(0.0, now - self._last_update)
        self._last_update = now
        self.bus.update(now)
        for a in self.agents:
            upd = getattr(a, 'update', None)
            if upd is None:
                continue
            upd(now, dt)
        self.bus.drain()
        self._update_inactivity(now)

    # -------------------------------------------------------- inactivity
    def player_was_active(self, now: float) -> None:
        self.last_activity = now

    def _update_inactivity(self, now: float) -> None:
        if self.inactivity_time <= 0 or not self.inactivity_sounds:
            return
        if now - self.last_activity < self.inactivity_time:
            return
        self.play_inactivity_sound(now)

    def play_inactivity_sound(self, now: float) -> None:
        """``-[PGELevel playInactivitySound]``"""
        if self._inactivity_sound is not None and self._inactivity_sound.playing:
            self._inactivity_sound.stop()
        if not self.inactivity_sounds:
            return
        idx = self.current_inactivity_sound % len(self.inactivity_sounds)
        sound = self.bank.sound(self.inactivity_sounds[idx])
        duration = 0.0
        if sound is not None:
            sound.spatialized = False
            sound.looping = False
            sound.play()
            duration = sound.duration
            self._inactivity_sound = sound
        # push the clock past the end of the sound so it cannot retrigger
        self.last_activity = now + duration
        self.current_inactivity_sound = (idx + 1) % len(self.inactivity_sounds)

    # ------------------------------------------------------------ surfaces
    def _on_player_moved(self, _name: str, params: Params) -> None:
        pos = params.get('position')
        if not (isinstance(pos, (tuple, list)) and len(pos) >= 2):
            return
        x, y = float(pos[0]), float(pos[1])
        self.player_was_active(self.bus.now)
        if self.player is None:
            return

        # -[PGELevel playerMovedToPosition:] starts the search with **self**
        # as the current best floor (0x10003231c), because PGELevel is a
        # PGESurface.  A real surface only takes over by containing the player
        # at a higher z.  So there is no "standing on nothing" case: off every
        # surface you are standing on the room, and the room's own tripBPM -
        # 280 by the loader's default - is what lets you fall.  Getting this
        # wrong is why levels with no Surface objects could not trip you.
        best = self
        for s in self.floors:
            if s.contains(x, y) and s.z > best.z:
                best = s

        if best.footsteps_prefix:
            prefix = best.footsteps_prefix
        else:
            prefix = self.footsteps_prefix

        if self.player.current_surface_id != best.surface_id:
            for s in self.floors:
                if s is not best and s.player_is_on_surface:
                    s.player_is_on_surface = False
                    self._exit_surface(s)
            best.player_is_on_surface = True
            self.player.current_surface_id = best.surface_id
            best.trigger_on_enter()
        else:
            best.trigger_on_step()

        if best.trip_bpm > 0:
            self.player.trip_bpm = best.trip_bpm
        if best.run_bpm > 0:
            self.player.run_bpm = best.run_bpm
        # Always assigned, exactly like shuffleSound below.  The original has
        # an else arm here - ``setTripSound:@""`` at 0x1000326b8 - so stepping
        # onto a surface that names no tripSound *clears* the player's and the
        # trip falls back to anySoundContaining:@"trip".  Only ever setting it
        # meant the last trip sound you crossed stuck for the rest of the
        # level: reported as the quicksand trip playing everywhere in ps1_11.
        self.player.trip_sound = best.trip_sound or ''
        # Always assigned, so a surface with no shuffleSound clears it and the
        # player falls back to "<footstepsPrefix>_shuffle".
        self.player.shuffle_sound = best.shuffle_sound or ''

        self.player.footsteps_prefix = prefix

    def _exit_surface(self, s: Surface) -> None:
        """Leaving a surface, in the original's order.

        ``OnExit`` first, then exactly one of the jumping variants depending on
        whether the player is in state 4.  No level uses either variant, and no
        level enables jumping, so only the ``OnExit`` half can ever be observed -
        but the split is what ``playerMovedToPosition:`` does.
        """
        s.trigger_on_exit()
        if self.player is not None and self.player.state == STATE_JUMPING:
            s.trigger_on_exit_jumping()
        else:
            s.trigger_on_exit_not_jumping()

    def _on_wall(self, _name: str, _params: Params) -> None:
        """``-[PGELevel playerDidCollideAWall:]``, the finite-level branch.

        The fallback name is not a nicety: **no level in the game sets
        ``hitWallSound``**, so ``"hitwall"`` is what you actually hear every
        time you walk into a wall.  ps1_1 and ps1_1b do not declare it in their
        playlists, so those two are silent here in the original too.

        The original sets only reverb and wet gain - ``spatialized`` is left to
        the playlist, which declares ``hitwall`` unspatialised.
        """
        s = self.bank.sound(self.hit_wall_sound or DEFAULT_HIT_WALL_SOUND)
        if s is None:
            return
        s.send_to_reverb = True
        s.wet_gain = HIT_WALL_WET_GAIN
        s.play()

    # ------------------------------------------------------------ messages
    def _on_play_spatial_sound(self, _name: str, params: Params) -> None:
        name = params.get('soundName', '')
        s = self.bank.sound(name)
        if s is None:
            return
        s.spatialized = True
        pos = params.get('position')
        if isinstance(pos, (tuple, list)) and len(pos) >= 2:
            s.planar = (float(pos[0]), float(pos[1]), 0.0)
        s.play()

    def _on_enemy_state(self, _name: str, params: Params) -> None:
        a = self.agent(params.get('name', ''))
        if isinstance(a, Monster):
            a.change_state_to(int(params.get('state', 1)))

    def _on_change_inactivity_time(self, _name: str, params: Params) -> None:
        self.inactivity_time = _f(params.get('value'))
        self.last_activity = self.bus.now

    def _on_change_inactivity_list(self, _name: str, params: Params) -> None:
        self.set_inactivity_sounds(params.get('soundList', ''))

    def _on_load_level(self, _name: str, params: Params) -> None:
        self.next_level = params.get('name')
        self.finished = True

    def _on_present_adios(self, _name: str, _params: Params) -> None:
        """``PGE_MESSAGE_PresentAdiosVC`` - the end of the game.

        Observed by ``-[PGEViewController viewDidLoad]``, which presents
        ``PGEAdiosViewController`` and calls ``playMenuAtmos``: the goodbye
        screen with "play this again" and "quit" on it.  Only ps1_25 sends it,
        from **both** of its doors - there is a good ending and a bad one and
        each of them finishes the game.

        There are no view controllers here, so what it means for this port is
        simply: there is no next level, the game is over.
        """
        self.game_complete = True
        self.finished = True
        self.next_level = None

    def _on_shut_down(self, _name: str, params: Params) -> None:
        """``-[PGELevel shutDownLevel:]``

        Every agent **except the one that sent the message** is deactivated, the
        inactivity sound is stopped and its list emptied, and the player is
        frozen.  The sender is spared so the thing you just walked into can
        finish speaking - which is exactly what stops the "are you still there"
        nag from talking over the closing narration.

        **The sweep is repeated until nothing is left running, and that part
        is a port-side fix** (see DIVERGENCES.md).  ``deactivate`` fires the
        agent's ``OnDeactivate`` whether or not it was active (0x10002049c, an
        unconditional tail call), and those triggers activate other agents:
        ps1_23's ``chicken_1`` re-arms the cage launcher every time it goes
        quiet.  Landing on an agent the sweep has already passed brings it back
        to life *behind* the sweep, and its alarm loop then plays on over the
        closing narration - which is what a player hit at the ice lake exit
        with the chickens still caged.  The original walks the array once
        (fast enumeration over ``agentArray``, 0x1000347e4) and nils each
        agent's delegate, but that delegate only gates a collectible's
        *collect* sound (the sole game-side read is in ``playCollectSound``),
        so it cannot be what silences a loop.  Rather than leave a looping
        alarm running into the next level, the sweep runs again while anything
        is still active.
        """
        self.shutting_down = True
        sender = params.get('senderName')
        for _ in range(4):
            running = [a for a in self.agents
                       if a.name != sender and (a.active or a.sound is not None)]
            if not running:
                break
            for a in running:
                a.deactivate()
        if self._inactivity_sound is not None and self._inactivity_sound.playing:
            self._inactivity_sound.stop()
        self.inactivity_sounds = []
        self.inactivity_time = 0.0
        self.bus.post('PGE_MESSAGE_DisableHands', {})
        self.bus.post('PGE_MESSAGE_DisableWalk', {})
        self.bus.post('PGE_MESSAGE_DisableRotation', {})

    # ----------------------------------------------------------- progress
    def can_skip_sound(self, key: str) -> bool:
        return bool(self.progress and self.progress.can_skip_sound(key))

    def save_skippable_sound(self, key: str) -> None:
        if self.progress:
            self.progress.save_skippable_sound(key)

    def solve_dilemmas(self) -> str:
        """``-[PGELevel solveDillemas]`` - the ending your choices have earned.

        Two passes, exactly as the original has them.  First every Dilemma in
        *this* level writes its `collected` flag into saved progress under its
        own id, and the highest ``dilemma_<n>`` present is remembered.  Then the
        name is built from **all** dilemmas up to that number, read back out of
        progress - so ps1_7 asks about one choice, ps1_12 about two and ps1_18
        about three, and the earlier answers come from levels you played before.

        That is why there are fourteen endings: two at depth one, four at depth
        two, eight at depth three.
        """
        highest = 0
        for a in self.agents:
            if not isinstance(a, Dilemma):
                continue
            if self.progress is not None:
                self.progress.save_dilemma_status(a.collected, a.dilemma_id)
            # the original takes the last character of the id and reads it as a
            # number; ids only ever run from 1 to 4, so that is the whole index
            tail = a.dilemma_id[-1:] if a.dilemma_id else ''
            if tail.isdigit():
                highest = max(highest, int(tail))

        name = 'dilemmaOutcome'
        for i in range(1, highest + 1):
            saved = bool(self.progress
                         and self.progress.get_dilemma_status(f'dilemma_{i}'))
            name += f'_{int(saved)}'
        return name

    # ---------------------------------------------------------------- info
    def contains(self, x: float, y: float) -> bool:
        rx, ry, rw, rh = self.rect
        return rx <= x < rx + rw and ry <= y < ry + rh

    def agent(self, name: str) -> GameAgent | None:
        for a in self.agents:
            if a.name == name:
                return a
        return None

    def pause(self) -> None:
        """``-[PGELevel pause:]`` - stop the clock and hold every sound.

        The original invalidates its update timer and pauses each agent; the
        port sets a flag that :meth:`update` honours, which is the same thing
        without a timer object.
        """
        if self.paused:
            return
        self.paused = True
        if self.player is not None:
            self.player.pause()
        for a in self.agents:
            a.pause()

    def resume(self, now: float) -> None:
        """``-[PGELevel resume:]`` - restart the clock from *now*.

        The original resets its date before rescheduling the timer, so the
        paused interval does not count against the inactivity nag.  The port
        pushes ``last_activity`` and ``_last_update`` forward for the same
        reason.
        """
        if not self.paused:
            return
        self.paused = False
        if self.player is not None:
            self.player.resume()
        for a in self.agents:
            a.resume()
        self.last_activity = now
        self._last_update = now

    def shutdown(self) -> None:
        for a in self.agents:
            a.deactivate_no_callback()
        self.bank.stop_all()
        self.bus.clear()

    def __repr__(self) -> str:
        return (f'<Level {self.name!r} {len(self.agents)} agents, '
                f'{len(self.floors)} surfaces>')


def load_level_by_name(bus: MessageBus, bank: SoundBank, exports_dir: str,
                       stem: str, progress=None,
                       rng: random.Random | None = None) -> Level:
    path = os.path.join(exports_dir, f'{stem}.json')
    return Level(bus, bank, progress=progress, rng=rng).load(path, stem)
