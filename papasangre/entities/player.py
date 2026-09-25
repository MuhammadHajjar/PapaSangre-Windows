"""``PGEPlayer`` - position, bearing, walking tempo and footsteps.

Every number and every branch here was read out of the arm64 binary; the
methods keep the original's names so the two can be compared line by line.
See GAME_STRUCTURE.md section 7 for the disassembly these came from.

State values (recovered from the branches in ``checkStepBPM``,
``moveForwardOneStep:`` and ``changeState:``):

===  ==========================================================
0    still - clears ``walkBPM`` and the step-time history
1    walking
2    running
3    tripped - blocks further input until recovery
4    dead / locked - ``moveForwardOneStep:`` returns immediately
===  ==========================================================
"""

from __future__ import annotations

import math
import random

from ..core.messages import MessageBus, Params
from ..core.triggers import TriggerHost

# State 4 is JUMPING, not death: -[PGEPlayer startToJump] does changeState:@4
# at 0x100026cb4, and -[PGELevel playerMovedToPosition:] compares against 4 to
# choose between OnExitJumping and OnExitNotJumping.
STATE_STILL, STATE_WALKING, STATE_RUNNING, STATE_TRIPPED, STATE_JUMPING = 0, 1, 2, 3, 4
STATE_NAMES = {0: 'still', 1: 'walking', 2: 'running', 3: 'tripped',
               4: 'jumping'}

#: -[PGEPlayer updateBPMCounter]: at most five step times are kept.
MAX_WALK_TIMES = 5
#: The speed-bank threshold: walkBPM >= 200 - bpmConstraint selects the fast bank.
SPEED_THRESHOLD_BPM = 200.0
#: -[PGEPlayer checkStepBPM] resets the tempo to this on starting to run.
RUN_RESET_BPM = 30.0
#: -[PGEPlayer moveForwardOneStep:] gain / reverb send for a footstep.
SHUFFLE_WET_GAIN = 0.75    # -[PGEPlayer shuffle] sets only this
FOOTSTEP_GAIN = 0.5
FOOTSTEP_WET_GAIN = 0.5
#: Used when a Room or Surface names no footstep bank.
DEFAULT_FOOTSTEPS_PREFIX = 'foot_racetrack'
#: -[PGEPlayer trip:] schedules changeState:@0 with afterDelay 2.0 - the only
#: delayed state change in the class, so there is no separate idle timer.
TRIP_RECOVERY_SECONDS = 2.0


class Player(TriggerHost):
    """The listener, and the only thing that moves under the player's control."""

    def __init__(self, bus: MessageBus, level=None, rng: random.Random | None = None):
        super().__init__(bus, name='player', position=(0.0, 0.0))
        self.level = level
        self.rng = rng or random.Random()

        self.player_angle = 0.0            # radians
        self.orientation_vector = (1.0, 0.0)
        self.state = STATE_STILL

        self.walk_times: list[float] = []
        self.walk_bpm = 0.0
        self.bpm_constraint = 0.0
        self.proximity_radius = 0.0

        self.last_foot = 'N'
        self.speed = ''                     # 's1' or 's3'
        self.pixels_per_step = 1.0        # 0x3f800000 at 0x1000249ec

        # Set from the Room / Surface the player is standing on.
        self.footsteps_prefix = ''
        # -[PGEPlayer init] defaults, not zero.  With zeros checkStepBPM
        # returned on its first line and the player never entered the running
        # state at all.  tripBPM 10000 means "never trip from speed" - only a
        # Surface (ps1_11 on) or ApplyBpmConstraint lowers it to something
        # reachable.  0x461c4000 and 0x43340000 at 0x100024a4c / 0x100024a64.
        # ``setTripBPM:`` is not a plain setter and ``init`` goes through it
        # (0x100024a44 sends it 0x461c4000), so the backing store has to exist
        # first.  See the property at the bottom of the class.
        self._trip_bpm = 0.0
        self.trip_bpm = 10000.0
        self.run_bpm = 180.0
        self.trip_sound = ''
        self.shuffle_sound = ''
        self.trip_time_penalty = 0.0
        self.current_surface_id = -1
        #: ``PGEPlayer.paused`` - the shuffle is the only thing that reads it.
        self.paused = False

        #: Supplied by the level: name -> plays a sound, and a bank picker.
        self.playlist = None

        for name, handler in (
            ('PGE_ACTION_OneStep', self._on_step),
            ('PGE_ACTION_Trip', self._on_trip_action),
            ('PGE_ACTION_Shuffle', self._on_shuffle),
            ('PGE_ACTION_RotatePlayerFromAngle', self._on_rotate_from),
            ('PGE_ACTION_RotatePlayerToFixedAngle', self._on_rotate_to),
            ('PGE_MESSAGE_ApplyBpmConstraint', self._on_bpm_constraint),
            ('PGE_MESSAGE_ApplyProximityRadiusToPlayer', self._on_proximity),
            ('PGE_MESSAGE_MovePlayerToPosition', self._on_move_to),
            ('PGE_MESSAGE_PlaySound', self._on_play_sound),
            ('PGE_INTERNAL_ChangeState', self._on_internal_state),
        ):
            bus.subscribe(name, handler)

    # ------------------------------------------------------------ geometry
    def compute_new_orientation_vector(self) -> None:
        """``-[PGEPlayer computeNewOrientationVector]`` - cos/sin, normalised."""
        x = math.cos(self.player_angle)
        y = math.sin(self.player_angle)
        length = math.sqrt(x * x + y * y)
        if length > 0.0:
            x /= length
            y /= length
        self.orientation_vector = (x, y)

    def set_start_angle(self, degrees: float) -> None:
        """Level data gives degrees; the engine works in radians."""
        self.rotate_to_fixed_rotation(math.radians(float(degrees)))

    def rotate_player_from_angle(self, delta_radians: float) -> None:
        """``-[PGEPlayer rotatePlayerFromAngle:]``

        Note the wrap is a single correction, not a modulo: a delta larger than
        a full turn leaves the angle outside 0..2pi, exactly as the original.
        """
        self.player_angle += float(delta_radians)
        if self.player_angle < 0.0:
            self.player_angle += 2.0 * math.pi
        elif self.player_angle > 2.0 * math.pi:
            self.player_angle -= 2.0 * math.pi
        self.compute_new_orientation_vector()
        self.bus.post('PGE_MESSAGE_PlayerDidRotateToFixedAngle',
                      self.get_state_dictionary())

    def rotate_to_fixed_rotation(self, radians: float) -> None:
        self.player_angle = float(radians)
        self.compute_new_orientation_vector()
        self.bus.post('PGE_MESSAGE_PlayerDidRotateToFixedAngle',
                      self.get_state_dictionary())

    @property
    def bearing_degrees(self) -> float:
        return math.degrees(self.player_angle) % 360.0

    # --------------------------------------------------------------- state
    def get_state_dictionary(self) -> Params:
        """``-[PGEPlayer getStateDictionnary]`` - the payload of every player message."""
        return {
            'position': self.position,
            'speed': self.speed,
            'lastFoot': self.last_foot,
            'orientation': self.player_angle,
            'orientationVector': self.orientation_vector,
            'state': self.state,
            'stateTextValue': STATE_NAMES.get(self.state, str(self.state)),
        }

    def change_state(self, new_state: int) -> None:
        """``-[PGEPlayer changeState:]``"""
        self.state = int(new_state)
        if self.state == STATE_STILL:
            self.walk_bpm = 0.0
            self.walk_times.clear()
        self.bus.post('PGE_MESSAGE_PlayerStateDidChange',
                      self.get_state_dictionary())

    def reset_bpm(self) -> None:
        self.walk_times.clear()

    # ----------------------------------------------------------- the tempo
    def update_bpm_counter(self, now: float) -> None:
        """``-[PGEPlayer updateBPMCounter]`` - with the original's fencepost fixed.

        Everything here is the original except the divisor, and the divisor is
        the whole reason the ice levels were unplayable.

        The original sums the gaps between the timestamps it is holding and then
        divides by the **number of timestamps** instead of the number of gaps
        (`ucvtf s0, x0` on `[walkTimes count]` at 0x100025d64, then
        `fdiv s0, s1, s0` at 0x100025d6c).  Five stamps span four gaps, so the
        answer comes out `count / (count - 1)` too high - and since the array
        fills from empty, *how* much too high depends on how many steps ago the
        history was last cleared:

        ====== ================ ==============================================
        stamps reading          ps1_19's ice, whose data says tripBPM 80
        ====== ================ ==============================================
        3      90 / interval    trips you above 53 real BPM - slower than 1.125s
        4      80 / interval    slower than 1.000s
        5      75 / interval    slower than 0.938s
        ====== ================ ==============================================

        So the authored number never meant what it says, and worse, the
        threshold moved. `resetBPM` runs when you cross onto ground with a
        different `tripBPM` **and again on every trip**, so going down put you
        straight back into the three-stamp window at its strictest: three free
        steps, then a fall, three free steps, then a fall. On a seven-step ice
        band that is not a difficulty spike, it is a level you cannot leave -
        reported as "every like 4 steps in the thin ice I trip, even if I walk
        very very slowly... like a softlock".

        Dividing by the gaps makes the reading exactly 60 / interval - your
        tempo, in beats per minute, whatever the history holds. Every authored
        cap then means what it says: the ice trips you above 80 real BPM
        (0.75s a step), ps1_11's quicksand above 65 (0.923s), the siren and the
        old man above 50 (1.2s). The reset stops changing the threshold and just
        gives you three steps' grace on new ground, and a rhythm that was safe
        stays safe - which is what both players remembered of the original.

        This is a change, not a recovery. See DIVERGENCES.md 4c.
        """
        self.walk_times.append(float(now))
        while len(self.walk_times) >= 6:
            self.walk_times.pop(0)

        n = min(len(self.walk_times) - 1, MAX_WALK_TIMES)
        total = 0.0
        if n >= 1:
            for i in range(n):
                total += self.walk_times[i + 1] - self.walk_times[i]

        # [REQUESTED] ``/ float(n)`` where the original has
        # ``/ float(len(self.walk_times))``.  One character of difference and
        # the whole of the read-out above.
        average = (total / float(n)) if n >= 1 else 0.0
        self.walk_bpm = (60.0 / average) if average else float('inf')
        threshold = SPEED_THRESHOLD_BPM - self.bpm_constraint
        self.speed = 's3' if self.walk_bpm >= threshold else 's1'

    def check_step_bpm(self) -> bool:
        """``-[PGEPlayer checkStepBPM]`` - always returns True; may trip."""
        if self.trip_bpm == 0.0:
            return True
        if self.run_bpm == 0.0:
            return True
        if len(self.walk_times) >= 3:
            if self.walk_bpm >= self.trip_bpm:
                if self.state != STATE_TRIPPED:
                    self.trip()
            elif self.walk_bpm > self.run_bpm:
                if self.state == STATE_RUNNING:
                    return True
                self.bus.post('PGE_MESSAGE_PlayerStartsToRun',
                              self.get_state_dictionary())
                self.change_state(STATE_RUNNING)
                self.walk_bpm = RUN_RESET_BPM
            else:
                if self.state != STATE_WALKING:
                    self.change_state(STATE_WALKING)
        else:
            self.change_state(STATE_WALKING)
        return True

    def apply_bpm_constraint(self, value: float) -> None:
        """``-[PGEPlayer applyBPMConstraint:]`` - **this is what makes you fall.**

        It sets ``tripBPM`` as well as storing the constraint, so a level that
        sends ``ApplyBpmConstraint:value=50`` is saying "step faster than 50 BPM
        here and you go down".  Only ps1_12 and ps1_23 do that; everywhere else
        ``tripBPM`` stays at its default 10000 and speed alone cannot trip you.

        **The order is not arbitrary.**  ``setTripBPM:`` runs first
        (0x100025afc) and only then is the constraint stored (0x100025b3c) -
        which matters because the setter refuses to do anything once a
        constraint is in place.  Doing it the other way round would make the
        constraint unable to apply itself."""
        self.trip_bpm = float(value)
        self.bpm_constraint = float(value)

    # ------------------------------------------------------------ tripBPM
    #
    # ``tripBPM`` is a real method, not a synthesised accessor, and what it does
    # decides whether the ice levels are playable.
    #
    #   -[PGEPlayer setTripBPM:]   0x100025e38
    #       if (value == _tripBPM)       return;      # 0x100025e44
    #       if (bpm_constaint != 0.0f)   return;      # 0x100025e58
    #       _tripBPM = value;
    #       [self resetBPM];                          # 0x100025e68
    #
    # ``-[PGELevel playerMovedToPosition:]`` sends this on **every step**, so
    # the first clause is doing real work: walking on one surface changes
    # nothing, and only crossing onto ground with a different tripBPM reaches
    # ``resetBPM``.
    #
    # **Crossing onto different ground therefore throws the tempo history
    # away.**  That is the whole safety valve of a thin-ice level.  Without it
    # the check that runs as you take your second step on the ice is computed
    # from the four intervals *before* the ice - so on ps1_19, where the first
    # ice band is four steps from where you start, walking the snow at a normal
    # pace and then slowing right down for the ice still read 113 BPM against
    # the ice's tripBPM of 80 and put you straight on the ground.  Slowing down
    # could not help, because ``checkStepBPM`` runs before the new step is
    # recorded and the window is four intervals long: by the time the reading
    # caught up you had already fallen.  Reported from ps1_19 and ps1_23 as
    # "six really slow steps, then one more at the same speed or slower and I
    # just randomly trip".  With the reset the ice is measured only from steps
    # taken *on* the ice, which is what makes the rhythm learnable.
    #
    # The second clause is ps1_23's siren: ``ApplyBpmConstraint:value=50``
    # leaves ``bpm_constaint`` non-zero, and from that moment **no surface can
    # move tripBPM again**.  The constraint is meant to last the rest of the
    # level; a plain assignment let the very next step overwrite it and the
    # dilemma stopped costing anything at all.
    @property
    def trip_bpm(self) -> float:
        """``-[PGEPlayer tripBPM]`` (0x100028a44) - the plain ivar read."""
        return self._trip_bpm

    @trip_bpm.setter
    def trip_bpm(self, value: float) -> None:
        value = float(value)
        if value == self._trip_bpm:
            return
        if self.bpm_constraint != 0.0:
            return
        self._trip_bpm = value
        self.reset_bpm()

    # -------------------------------------------------------------- moving
    def move_forward_one_step(self, foot: str, now: float) -> bool:
        """``-[PGEPlayer moveForwardOneStep:]`` - returns True if the player moved."""
        if self.state == STATE_JUMPING:
            return False

        if self.proximity_radius != 0.0:
            self.bus.post('PGE_MESSAGE_AlertEnemiesWithinRadius',
                          {'radius': str(self.proximity_radius), 'to': 'player'})

        # The original cancels its pending 'you have stopped' state change.
        self.bus.cancel((id(self), 'idle'))

        if not self.check_step_bpm():
            return False

        px, py = self.position
        ox, oy = self.orientation_vector
        new_x = px + ox * self.pixels_per_step
        new_y = py + oy * self.pixels_per_step
        self.last_foot = foot

        if self.level is not None and not self.level.contains(new_x, new_y):
            self.bus.post('PGE_MESSAGE_PlayerDidCollideAWall',
                          self.get_state_dictionary())
            return False

        self.position = (new_x, new_y)
        self.bus.post('PGE_MESSAGE_PlayerMovedToPosition',
                      self.get_state_dictionary())

        if self.speed == '':
            self.speed = 's1'
        if self.last_foot != 'N':
            self.play_footstep()
        self.update_bpm_counter(now)
        return True

    def footstep_sound_name(self) -> str:
        prefix = self.footsteps_prefix or DEFAULT_FOOTSTEPS_PREFIX
        return f'{prefix}_{self.speed}_{self.last_foot}'

    def play_footstep(self) -> None:
        """Pick a footstep from the surface's bank and play it.

        ``anySoundWihPrefix:`` (the original's spelling) chooses at random among
        every sound whose name starts with the prefix, which is how the _a/_b/_c
        variants get used.  If the exact speed/foot bank is missing it falls
        back to ``<prefix>_s``, which also matches the other speed - so surfaces
        with no fast samples lose left/right alternation while running, exactly
        as in the original.
        """
        if self.playlist is None:
            return
        prefix = self.footsteps_prefix or DEFAULT_FOOTSTEPS_PREFIX
        sound = self.playlist.any_sound_with_prefix(self.footstep_sound_name())
        if sound is None:
            sound = self.playlist.any_sound_with_prefix(f'{prefix}_s')
        if sound is None:
            return
        sound.gain = FOOTSTEP_GAIN
        sound.send_to_reverb = True
        sound.wet_gain = FOOTSTEP_WET_GAIN
        sound.play()

    def shuffle(self) -> None:
        """``-[PGEPlayer shuffle]`` - you shifting your weight where you stand.

        Fires from ``updateFeetView:`` two seconds after your last step, at the
        moment that foot becomes usable again.  Unlike a footstep this is looked
        up by **exact** name, not by prefix, and it is not spatialised - it is
        you, so it is in your head.
        """
        if self.paused or self.playlist is None:
            return
        prefix = self.footsteps_prefix or DEFAULT_FOOTSTEPS_PREFIX
        if not self.shuffle_sound:
            # the computed name is cached back onto the player, as the original
            # does, so a surface that names its own sound keeps overriding it
            self.shuffle_sound = f'{prefix}_shuffle'
        sound = self.playlist.sound(self.shuffle_sound)
        if sound is None:
            return                       # the original logs this one in red
        sound.spatialized = False
        sound.send_to_reverb = True
        sound.wet_gain = SHUFFLE_WET_GAIN
        sound.play()

    def _on_shuffle(self, _name: str, _params: Params) -> None:
        self.shuffle()

    def walked_on_surface_with_id(self, surface_id: int) -> None:
        self.current_surface_id = int(surface_id)
        self.bus.post('PGE_MESSAGE_PlayerWalkedOnSurfaceWithId',
                      {'surfaceId': surface_id})

    def move_player_to_position(self, x: float, y: float) -> None:
        self.position = (float(x), float(y))
        self.bus.post('PGE_MESSAGE_PlayerMovedToPosition',
                      self.get_state_dictionary())

    # ---------------------------------------------------------- play sound
    def play_sound(self, sound_name: str, gain: float | None = None,
                   loop: bool = False):
        """``-[PGEPlayer playSound:]`` - the engine's general "play this" message.

        Three details that matter, all recovered:

        * ``soundName`` may be an ``&``-separated list, and **one is chosen at
          random** - not all of them played.
        * a name ending in ``_a`` is treated as a *prefix*: the suffix is
          stripped and a random variant is chosen, which is how a single trigger
          gets a different take each time.
        * the sound is forced un-spatialised.
        """
        if self.playlist is None or not sound_name:
            return None
        names = [n for n in str(sound_name).split('&') if n]
        if not names:
            return None
        name = self.rng.choice(names)
        if name.endswith('_a'):
            sound = self.playlist.any_sound_with_prefix(name[:-2])
        else:
            sound = self.playlist.sound(name)
        if sound is None:
            return None
        sound.spatialized = False
        if gain is not None:
            sound.gain = gain
        sound.looping = bool(loop)
        sound.play()
        return sound

    def _on_play_sound(self, _name: str, params: Params) -> None:
        gain = params.get('gain')
        self.play_sound(params.get('soundName', ''),
                        float(gain) if gain is not None else None,
                        str(params.get('loop', '')).lower() in ('yes', 'true', '1'))

    # --------------------------------------------------------------- trips
    def trip(self) -> None:
        """``-[PGEPlayer trip:]``

        Order and values taken from the disassembly: clear the tempo history,
        go to state 3, announce it, then schedule the return to state 0 exactly
        **two seconds** later.  Then the sound, played unspatialised, and
        finally the ``OnTrip`` trigger plus an alert to every enemy in the
        level, telling them where the noise came from.

        The lookup has two arms (0x10002754c), and they are not the same kind
        of lookup:

        * ``tripSound`` set and not ``@""`` -> ``[playlist S3DSound: tripSound]``,
          an **exact** name lookup.  ps1_2, ps1_3, ps1_11 and ps1_12 all name
          one on their surfaces, so this is the live path on those levels;
        * otherwise -> ``[playlist anySoundContaining:@"trip"]``, which collects
          every sound whose key contains "trip" and picks one with
          ``arc4random``.  On a level whose playlist carries two grounds' worth
          of trip sounds and names none of them - ps1_7 - that is a coin flip.
          See DIVERGENCES.md 4b.

        Note what the original does *not* do: it builds
        ``footstepsPrefix ?: @"foot_racetrack"`` at 0x100027480 and then throws
        it away at 0x10002777c without ever reading it.  ``shuffle`` does the
        same thing and finishes with ``stringWithFormat:@"%@_shuffle"``; there
        is no ``@"%@_trip"`` in the binary.
        """
        self.reset_bpm()
        self.change_state(STATE_TRIPPED)
        self.bus.post('PGE_MESSAGE_PlayerDidTrip', self.get_state_dictionary())

        self.bus.cancel((id(self), 'idle'))
        self.bus.post_after(TRIP_RECOVERY_SECONDS, 'PGE_INTERNAL_ChangeState',
                            {'state': STATE_STILL}, token=(id(self), 'idle'))

        if self.playlist is not None:
            if self.trip_sound:
                sound = self.playlist.sound(self.trip_sound)
            else:
                sound = self.playlist.any_sound_containing('trip')
            if sound is not None:
                sound.spatialized = False
                sound.play()

        self.trigger('OnTrip')
        # ``snarl`` is not in the original's payload.  [REQUESTED] Going down is
        # the loudest thing you can do and it has to be answered by a sound: on
        # ground that alerts on every step the enemy is already holding a
        # wanted position, and the state 4 latch would then re-aim it in
        # silence, so something arrived out of nowhere.  See DIVERGENCES 4c.
        self.bus.post('PGE_MESSAGE_AlertAllEnemies',
                      {'position': self.position, 'to': 'position',
                       'snarl': True})

    # ------------------------------------------------------------ handlers
    def _on_step(self, _name: str, params: Params) -> None:
        # Stamp the step with the moment the key went down, not with the frame
        # the message is delivered on.  ``updateBPMCounter`` reads the clock
        # itself in the original, and it runs on the same call as the touch, so
        # the touch's own instant is the faithful one; taking ``bus.now``
        # quantised every interval to the previous frame.
        when = params.get('time')
        self.move_forward_one_step(params.get('lastFoot', 'N'),
                                   float(when) if when is not None
                                   else self.bus.now)

    def _on_trip_action(self, _name: str, _params: Params) -> None:
        if self.state != STATE_TRIPPED:
            self.trip()

    def _on_rotate_from(self, _name: str, params: Params) -> None:
        self.rotate_player_from_angle(float(params.get('angle', 0.0)))

    def _on_rotate_to(self, _name: str, params: Params) -> None:
        self.rotate_to_fixed_rotation(float(params.get('angle', 0.0)))

    def _on_bpm_constraint(self, _name: str, params: Params) -> None:
        self.apply_bpm_constraint(float(params.get('value', 0.0)))

    def _on_proximity(self, _name: str, params: Params) -> None:
        self.proximity_radius = float(params.get('value', 0.0))

    def _on_internal_state(self, _name: str, params: Params) -> None:
        self.change_state(int(params.get('state', STATE_STILL)))

    def _on_move_to(self, _name: str, params: Params) -> None:
        pos = params.get('position')
        if isinstance(pos, (tuple, list)) and len(pos) >= 2:
            self.move_player_to_position(pos[0], pos[1])

    # ---------------------------------------------------------------- info
    def pause(self) -> None:
        """``-[PGEPlayer pause]`` - the level pauses the player with everything else."""
        self.paused = True

    def resume(self) -> None:
        """``-[PGEPlayer resume]``"""
        self.paused = False

    def describe_movement(self) -> str:
        """A spoken readout of the walking machine.  [N] - port-side.

        There is no way to see any of this without a screen, and the numbers
        decide whether you run and whether you fall, so they are worth being
        able to ask for.
        """
        state = STATE_NAMES.get(self.state, str(self.state))
        bits = [f'{self.walk_bpm:.0f} beats per minute', state]
        bits.append('running footsteps' if self.speed == 's3'
                    else 'walking footsteps')
        if self.trip_bpm >= 9999.0:
            bits.append('this level cannot trip you')
        else:
            bits.append(f'you fall above {self.trip_bpm:.0f}')
        bits.append(f'you break into a run above {self.run_bpm:.0f}')
        return ', '.join(bits) + '.'

    def describe(self) -> str:
        x, y = self.position
        return (f'{STATE_NAMES.get(self.state, self.state)}, '
                f'facing {self.bearing_degrees:.0f} degrees, '
                f'at {x:.0f}, {y:.0f}')
