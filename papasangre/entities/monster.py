"""``PGEEnemy`` - the things in the dark.

``-[PGEEnemy update:]`` is a thirteen-way switch on ``state``, dispatched
through a jump table at 0x10001de40.  Decoding that table gives:

===  =========  ==================================================
 1   IDLE       play ``defaultSound`` on a loop, walk speed
 2   ALERT_PLAYER    one shot, becomes 3
 3   CHASE_PLAYER    ``chaseSpeed``, ``chaseSound``, head for the player,
                     remembering where it started
 4   ALERT_POSITION  one shot, becomes 5
 5   GO_TO_POSITION  ``chaseSpeed``, ``chaseSound``, head for ``wantedPosition``
 6   AT_POSITION     stopped getting closer; ``distractedTimer`` runs, optional
                     ``attackSound``, then goes home
 7   ATTACK          stop the current sound and play ``attackSound``
 8-11               unused - the jump table sends them straight to the tail
12   ALERT_AGENT     ``awareSound``, then becomes 5 after one second
13   RETURNING       ``defaultSound``, ``walkingSpeed``, walk back to where it
                     was before it was disturbed; on arrival becomes 1
===  =========  ==================================================

Each state does its entry work once, guarded by ``state_atPreviousFrame``, then
its continuous work every frame.

Confidence: states 1, 2, 3, 13 and the alert entry points are read directly and
are what level 3 needs.  States 4 to 7 and 12 are implemented from the same
disassembly but no level has exercised them yet - see PORTING_STATUS.md.

Note what is *not* here: nothing in ``update:`` looks at how close the player
is.  An enemy never notices you by itself; it has to be told, by
``AlertAllEnemies``, ``AlertEnemyWithName`` or ``AlertEnemiesWithinRadius``.
Level 3's sleeping hog is never alerted by anything, which is the point of that
level - it is an obstacle you have to hear and walk around, and the four
concentric floor rings around it change your footstep sound so you can tell how
close you are.
"""

from __future__ import annotations

import math

from ..core.messages import MessageBus, Params
from ..core.triggers import addressed_to
from .agent import GameAgent

IDLE = 1
ALERT_PLAYER = 2
CHASE_PLAYER = 3
ALERT_POSITION = 4
GO_TO_POSITION = 5
AT_POSITION = 6
ATTACK = 7
ALERT_AGENT = 12
RETURNING = 13

STATE_NAMES = {
    IDLE: 'idle', ALERT_PLAYER: 'alerted to player', CHASE_PLAYER: 'chasing',
    ALERT_POSITION: 'alerted to position', GO_TO_POSITION: 'going to position',
    AT_POSITION: 'searching', ATTACK: 'attacking',
    ALERT_AGENT: 'alerted to agent', RETURNING: 'returning',
}

#: -[PGEEnemy update:] state 12 schedules changeStateTo:5 with afterDelay 1.0.
AGENT_ALERT_DELAY = 1.0


class Monster(GameAgent):
    """A ``PGEEnemy``: idle until something alerts it, then it comes for you."""

    def __init__(self, bus: MessageBus, name: str = '',
                 position=(0.0, 0.0), bank=None, level=None) -> None:
        super().__init__(bus, name=name, position=position, bank=bank, level=level)
        self.state = IDLE
        self.state_at_previous_frame = 0

        self.default_sound = ''
        self.aware_sound = ''
        self.chase_sound = ''
        self.not_there_sound = ''
        self.attack_sound = ''
        self.walking_pause_sound = ''

        # -[PGEEnemy init] defaults, 0x10001ce9c onward.  These matter: an
        # enemy whose level data does not name a speed still walks.
        self.walking_speed = 10.0
        self.chase_speed = 15.0
        self.distracted_time = 10.0
        self.distracted_timer = -1.0        # 0xBF800000 at 0x10001ce7c
        self.chasing_time = 0.0
        self.chasing_radius = 200.0         # 0xc8 at 0x10001cf3c

        self.wanted_position = (float('-inf'), float('-inf'))
        self.has_wanted_position = False
        self.position_before_chasing = (0.0, 0.0)
        #: Left at the origin by init - only entering state 3 or state 12
        #: records where the enemy actually was.  An enemy alerted straight to
        #: a position (state 4) therefore "returns" to the world origin.  That
        #: is the original's behaviour, quirk included.
        self.should_attack_on_wanted_position = False
        self.squared_distance_from_goal = float('inf')
        self.within_radius = False

        self.spatialized = True          # every monster sound is positioned
        self._current_sound_name = ''

        for msg, handler in (
            ('PGE_MESSAGE_AlertAllEnemies', self._on_alert_all),
            ('PGE_MESSAGE_AlertEnemyWithName', self._on_alert_named),
            ('PGE_MESSAGE_AlertEnemiesWithinRadius', self._on_alert_radius),
        ):
            bus.subscribe(msg, handler)

    # ------------------------------------------------------------ activity
    def change_state_to(self, state: int) -> None:
        """``-[PGEEnemy changeStateTo:]`` - it only assigns."""
        self.state = int(state)

    # -------------------------------------------------------------- sound
    def play_sound(self, name: str, looping: bool = True) -> None:
        """``-[PGEEnemy playSound:looping:]`` - swap the looping voice."""
        if self.bank is None or not name:
            return
        # The guard is on the **name alone** - the original never asks whether
        # the sound is still playing (0x10001e878).  That matters in state 7,
        # where the sound is stopped every frame and this refuses to restart it.
        if name == self._current_sound_name:
            return
        if self.sound is not None:
            self.sound.stop()
        sound = self.bank.sound(name)
        if sound is None:
            return
        self.sound = sound
        self._current_sound_name = name
        sound.spatialized = True
        sound.looping = looping
        self.update_spatialized_sound()
        sound.play()

    # ------------------------------------------------------------- alerts
    def alert(self, to: str, position=None, chase_time: float = 0.0) -> None:
        """``-[PGEEnemy alertEnemy:]``

        Two entry guards, both read from 0x10001e11c-0x10001e154:

        * in ``GO_TO_POSITION``/``AT_POSITION``, an enemy that has
          ``shouldAttackOnWantedPosition`` set ignores everything - that flag is
          raised by state 12, so an enemy sent after an agent cannot be
          re-aimed on the way;
        * in ``ALERT_PLAYER``/``CHASE_PLAYER`` nothing can distract it at all.

        Then exactly one of three branches runs, and **only the agent branch
        reads the notification's position** - the other two jump straight to
        the release at 0x10001e5a4.  A ``to=position`` alert therefore carries
        no destination; state 4 supplies one from where you are standing.
        """
        if not self.active:
            return
        if self.state in (GO_TO_POSITION, AT_POSITION):
            if self.should_attack_on_wanted_position:
                return
        elif self.state in (ALERT_PLAYER, CHASE_PLAYER):
            return
        if to == 'player':
            self.change_state_to(ALERT_PLAYER)
        elif to == 'position':
            # 0x10001e428: a distracted enemy is already busy with a noise and
            # will not be sent after another until its distractedTime is up.
            # The original does nothing at all here - no state change.
            if self.distracted_timer != -1.0:
                return
            self.change_state_to(ALERT_POSITION)
        elif to == 'agent':
            self.distracted_timer = 0.0
            self.change_state_to(ALERT_AGENT)
            if position is not None:
                self.wanted_position = (float(position[0]), float(position[1]))
                self.find_direction_to(*self.wanted_position)
        if chase_time:
            self.chasing_time = 0.0

    def _on_alert_all(self, _name: str, params: Params) -> None:
        self.alert(params.get('to', 'player'), params.get('position'),
                   float(params.get('chaseTime', 0) or 0))

    def _on_alert_named(self, _name: str, params: Params) -> None:
        if addressed_to(params, self.name):
            self.alert(params.get('to', 'player'), params.get('position'),
                       float(params.get('chaseTime', 0) or 0))

    def _on_alert_radius(self, _name: str, params: Params) -> None:
        """``AlertEnemiesWithinRadius`` - only those close enough hear it."""
        try:
            radius = float(params.get('radius', 0))
        except (TypeError, ValueError):
            radius = 0.0
        dx = self.player_position[0] - self.position[0]
        dy = self.player_position[1] - self.position[1]
        inside = math.sqrt(dx * dx + dy * dy) < radius
        self.within_radius = inside
        if inside:
            self.alert(params.get('to', 'player'), self.player_position)

    # ---------------------------------------------------------- collision
    def collides_with_player(self) -> None:
        """``-[PGEEnemy collidesWithPlayer]`` - and it only lands once.

        ``PGEGameAgent`` has no "already triggered" latch: it fires ``OnCollide``
        every frame you are inside the radius.  ``PGEEnemy`` provides the latch
        itself by going to state 7 and refusing to run again while it is there,
        and by dropping its speed to zero, which also stops the base ``update:``
        from re-checking collisions at all.

        Without this the kennel hog re-fires ``ShutDownLevel`` every frame; each
        one deactivates every agent *except the sender*, so the failure
        narration is switched off again the moment after it is switched on, it
        never reaches ``OnSoundEnd``, the level never reloads, and the hog - the
        sender, and so the one agent left running - keeps grunting. The game
        looks frozen with a stuck hog.
        """
        if self.state == ATTACK:
            return
        self.speed = 0.0
        self.change_state_to(ATTACK)
        super().collides_with_player()

    # -------------------------------------------------------------- update
    def update(self, now: float, dt: float = 1.0 / 60.0) -> None:
        """``-[PGEEnemy update:]`` - the state switch."""
        if not self.active:
            return
        self.check_collisions_with_player()
        entering = self.state != self.state_at_previous_frame
        state = self.state

        if state == IDLE:
            if entering:
                # Only the sound.  IDLE does **not** touch speed - the level
                # data's own `speed` is what a patrol walks at, and only state
                # 13 ever replaces it with walkingSpeed (0x10001d814).
                self.play_sound(self.default_sound)

        elif state == ALERT_PLAYER:
            self.change_state_to(CHASE_PLAYER)

        elif state == CHASE_PLAYER:
            if entering:
                self.speed = self.chase_speed or self.speed
                self.play_sound(self.chase_sound)
                self.position_before_chasing = self.position
            self._steer_towards(self.player_position, dt)
            self.chasing_time += dt

        elif state == ALERT_POSITION:
            # ``hasWantedPosition`` is the latch that makes a floor which
            # alerts on every step (ps1_7's guts) bearable.  It is set at
            # 0x10001dbb4 - ``strb w8, [x19, x22]`` with w8 = 1 - and x22 is
            # still the offset loaded for the *test* at the top of this state,
            # 2300 bytes earlier.  The store carries no ivar annotation
            # because of that, which is exactly why searching for writers of
            # the name finds nothing.  Read the register, not the comment.
            #
            # First alert: snarl, and take a whole second to wind up.  Every
            # alert after that, while it is still hunting: silently re-aim and
            # carry straight on - **no awareSound**, so the chase loop it is
            # already playing is never interrupted.  State 6 clears the latch
            # when it gives up, so the next disturbance snarls again.
            if self.has_wanted_position:
                self.find_direction_to_player()
                self.change_state_to(GO_TO_POSITION)     # at once, no delay
            else:
                self.play_sound(self.aware_sound)
                self.bus.post_after(AGENT_ALERT_DELAY,
                                    'PGE_INTERNAL_EnemyState',
                                    {'name': self.name, 'state': GO_TO_POSITION},
                                    token=(id(self), 'alert'))
                self.find_direction_to_player()
            self.wanted_position = self.player_position
            if entering:                # 0x10001dae8 - the rest is entry work
                self.should_attack_on_wanted_position = False
                self.position_before_chasing = self.position
                self.chasing_time = 0.0
                self.has_wanted_position = True
                self.speed = self.chase_speed

        elif state == GO_TO_POSITION:
            # No entry guard at all in the original (0x10001d338): it asks for
            # the chase sound and the chase speed on **every** frame.  That is
            # safe because playSound: refuses a name it is already on, and it
            # is what makes a re-aim inaudible - the loop just keeps running.
            self.play_sound(self.chase_sound)
            self.speed = self.chase_speed or self.speed
            arrived = self._steer_towards(self.wanted_position, dt)
            if arrived:
                self.change_state_to(AT_POSITION)

        elif state == AT_POSITION:
            if entering:
                self.distracted_timer = 0.0
                # setSpeed:0 at 0x10001d4d4 - this is what actually holds a
                # searching enemy still; nothing clears the orientation vector.
                self.speed = 0.0
                if self.should_attack_on_wanted_position and self.attack_sound:
                    self.play_sound(self.attack_sound, looping=False)
                elif self.not_there_sound:
                    self.play_sound(self.not_there_sound, looping=False)
            self.has_wanted_position = False         # 0x10001dc38
            self.chasing_time += dt
            self.distracted_timer += dt
            # 0x10001dcb0: distractedTime <= 0 means it never gives up, and the
            # test at 0x10001dccc is a strict >, so it waits the full time.
            if self.distracted_time > 0.0 and self.distracted_timer > self.distracted_time:
                self.chasing_time = 0.0
                self.distracted_timer = -1.0
                # Both branches at 0x10001dd18 go to state 1; one of them picks
                # the patrol up again where it left off.
                self.change_state_to(IDLE)
                if self.has_path:
                    self.find_next_patrol_point()
                    self.speed = self.walking_speed

        elif state == ATTACK:
            # No entry guard on this one, and the stop is unconditional: the
            # enemy shuts up the moment it has you.  An attack sound gets a
            # single frame at most, because play_sound refuses to replay a name
            # it is already on while the stop keeps taking it back down.  The
            # silence is the point - you should not still hear it beside you
            # while the failure narration plays.
            self.speed = 0.0
            if self.sound is not None:
                self.sound.stop()
            if self.attack_sound:
                self.play_sound(self.attack_sound)      # playSound: = looping YES
            self.chasing_time += dt

        elif state == ALERT_AGENT:
            # The only state with a real entry guard of its own (0x10001d678
            # and again at 0x10001d6bc).  playSound: here is the looping form.
            if entering:
                self.play_sound(self.aware_sound)
                self.speed = self.chase_speed or self.speed
                self.bus.post_after(AGENT_ALERT_DELAY,
                                    'PGE_INTERNAL_EnemyState',
                                    {'name': self.name, 'state': GO_TO_POSITION},
                                    token=(id(self), 'alert'))
                self.position_before_chasing = self.position
                # 0x10001d798 - and this is what stops the enemy being
                # re-aimed while it is on its way (see alert()).
                self.should_attack_on_wanted_position = True

        elif state == RETURNING:
            if entering:
                self.play_sound(self.default_sound)
                self.speed = self.walking_speed or self.speed
            if self._steer_towards(self.position_before_chasing, dt):
                self.change_state_to(IDLE)

        self.state_at_previous_frame = state
        # PGEEnemy update: ends with [super update:], which is what actually
        # walks the enemy along the vector the state machine just aimed.
        super().update(now, dt)

    # ------------------------------------------------------------ movement
    def _steer_towards(self, target, _dt: float) -> bool:
        """Point at ``target`` and report whether we have arrived.

        ``-[PGEEnemy update:]`` never calls ``setPosition:`` or
        ``setOrientationVector:``.  It calls ``findDirectionTo:``, which aims
        the orientation vector and stores ``squaredDistanceFromGoal``, and the
        walking is done afterwards by ``[super update:]``.  Arrival is not a
        distance threshold either: the new squared distance is compared with the
        stored one, and the moment it **stops getting smaller** the enemy has
        arrived (0x10001d454).  An enemy that overshoots or is blocked therefore
        gives up correctly.
        """
        dx = target[0] - self.position[0]
        dy = target[1] - self.position[1]
        d2 = dx * dx + dy * dy
        arrived = d2 > self.squared_distance_from_goal
        self.find_direction_to(target[0], target[1])
        if arrived:
            self.squared_distance_from_goal = float('inf')
        # The vector is deliberately left pointing where it was: nothing in the
        # original clears it, and the states that need the enemy to stand still
        # drop `speed` to 0 instead.  Zeroing it here used to strand a patrol,
        # because the route only re-aims once the enemy has drifted far enough
        # from its stale target for the distance test to trip.
        return arrived

    # ---------------------------------------------------------------- info
    @property
    def state_name(self) -> str:
        return STATE_NAMES.get(self.state, str(self.state))

    def __repr__(self) -> str:
        return (f'<Monster {self.name!r} {self.state_name} at '
                f'({self.position[0]:.0f},{self.position[1]:.0f})>')
