"""``PGEGameAgent`` - the base for everything in a level that is not the floor.

Recovered defaults from ``-[PGEGameAgent init]``: ``collideRadius`` 20,
``speed`` 10, ``active`` NO.

Collision (``checkCollisionsWithPlayer``) is a plain squared-distance test
against ``collideRadius``, run every time the player moves, and it fires
``OnCollide`` **every frame the player is inside the radius** - there is no
"already triggered" latch.  In practice the shipped levels deactivate the
trigger from inside its own ``OnCollide``, which is why that does not matter;
the port keeps the original behaviour rather than adding a latch.

Every agent listens to the same broadcast messages the original subscribes to in
``init``, and each decides for itself whether a ``name`` parameter is its own.
"""

from __future__ import annotations

import math

from ..core.messages import MessageBus, Params
from ..core.triggers import TriggerHost, addressed_to

DEFAULT_COLLIDE_RADIUS = 20.0        # -[PGEGameAgent init]
DEFAULT_SPEED = 10.0                 # -[PGEGameAgent init]
#: -[PGEGameAgent init] stores 0x7f800000 straight into shootRange: infinity.
#: So by default "in range" is purely a question of which way you are facing.
DEFAULT_SHOOT_RANGE = float('inf')

#: How closely you must be facing an agent to be "in shooting range".
#: -[PGEGameAgent updateSpatializedSound] compares the dot product of the
#: player's facing vector with the unit vector to the agent against
#: 0x3fef5c28f5c28f5c = 0.98, which is a cone of about +/-11.5 degrees.
#: This is the "turn until you are facing the voice" mechanic.
FACING_DOT_THRESHOLD = 0.98


class GameAgent(TriggerHost):
    """Base class: name-addressed activation, collision, spatial sound."""

    def __init__(self, bus: MessageBus, name: str = '',
                 position: tuple[float, float] = (0.0, 0.0),
                 bank=None, level=None) -> None:
        super().__init__(bus, name=name, position=position)
        self.bank = bank
        self.level = level
        self.active = False
        self.collide_radius = DEFAULT_COLLIDE_RADIUS
        self.speed = DEFAULT_SPEED
        #: The direction the base ``update:`` walks in.  Agents do not move
        #: themselves; they point this at something and let the base class
        #: carry them.  (0, 0) means standing still, which is every agent in
        #: the game until an enemy is alerted.
        self.orientation_vector = (0.0, 0.0)
        #: Set by find_direction_to; PGEEnemy's arrival test compares against it.
        self.squared_distance_from_goal = float('inf')
        self.sound_list = ''
        self.spatialized = False
        self.gain = 1.0
        self.sound = None                 # the live audio.engine.Sound
        self.player_position = (0.0, 0.0)
        self.player_orientation = 0.0
        self.player_orientation_vector = (1.0, 0.0)
        self.shoot_range = DEFAULT_SHOOT_RANGE
        self._is_in_shooting_range = False

        #: PGEGameAgent.state.  PGEEnemy drives it as its own state machine;
        #: on a plain agent it exists only so patrolling can check for 1.
        self.state = 0
        #: The patrol route, from PGE_MESSAGE_FollowPathWithName.
        self.path: list[tuple[float, float]] | None = None
        self.has_path = False
        self.path_current_point = 0
        self.wanted_patrol_point = (0.0, 0.0)
        self.squared_distance_from_next_patrol_point = float('inf')
        #: PGEGameAgent.soundWasPaused - see pause()/resume().
        self.sound_was_paused = False

        for msg, handler in (
            ('PGE_MESSAGE_PlayerMovedToPosition', self._on_player_moved),
            ('PGE_MESSAGE_ActivateAgentWithName', self._on_activate_named),
            ('PGE_MESSAGE_DeactivateAgentWithName', self._on_deactivate_named),
            ('PGE_MESSAGE_ChangeSoundListOnAgentWithName', self._on_change_sound_list),
            ('PGE_MESSAGE_PlaySpatialSoundOnAgentWithName', self._on_play_spatial_named),
            ('PGE_MESSAGE_MoveObjectToPositionWithName', self._on_move_named),
            ('PGE_MESSAGE_PlayerDidRotateToFixedAngle', self._on_player_rotated),
            ('PGE_MESSAGE_LevelInited', self._on_level_inited),
            ('PGE_MESSAGE_FollowPathWithName', self._on_follow_path),
            ('PGE_MESSAGE_StopFollowingPath', self._on_stop_following_path),
        ):
            bus.subscribe(msg, handler)

    # --------------------------------------------------------- properties
    def apply_properties(self, props: dict) -> None:
        """The engine's generic ``set<Key>:`` applicator, for our fields."""
        for key, raw in props.items():
            if key.startswith('On'):
                continue
            setter = _SETTERS.get(key)
            if setter is not None:
                setter(self, raw)

    # ------------------------------------------------------------ activity
    def activate(self) -> None:
        """``-[PGEGameAgent activate]``"""
        self.active = True
        self.trigger('OnActivate')

    def deactivate(self) -> None:
        """``-[PGEGameAgent deactivate]`` - stops and drops the sound."""
        if self.sound is not None:
            self.sound.stop()
            self.sound = None
        self.active = False
        self.trigger('OnDeactivate')

    def deactivate_no_callback(self) -> None:
        if self.sound is not None:
            self.sound.stop()
            self.sound = None
        self.active = False

    def pause(self) -> None:
        """``-[PGEGameAgent pause]`` - hold this agent's sound, remembering that
        we were the one who stopped it so ``resume`` only restarts what it
        actually paused."""
        self.sound_was_paused = bool(self.sound is not None and self.sound.playing)
        if self.sound_was_paused:
            self.sound.pause()

    def resume(self) -> None:
        """``-[PGEGameAgent resume]``"""
        if self.sound_was_paused and self.sound is not None:
            self.sound.resume()
        self.sound_was_paused = False

    # -------------------------------------------------------------- update
    def update(self, now: float, dt: float = 1.0 / 60.0) -> None:
        """``-[PGEGameAgent update:]`` - every active agent, every frame.

        Two things worth knowing.  The agent walks along ``orientationVector``
        at ``speed``: nothing here decides *where* to go, so a subclass steers
        by pointing that vector (see :meth:`find_direction_to`) and lets this
        do the carrying.  And the three follow-ups are gated on ``speed > 0``,
        so a genuinely motionless agent stops re-checking collisions too.

        The original also posts ``PGE_MESSAGE_AgentDidMove`` here.  Nothing in
        the binary observes it - it is telemetry for the on-screen debug map -
        so the port does not.
        """
        if not self.active:
            return
        vx, vy = self.orientation_vector
        self.position = (self.position[0] + vx * self.speed * dt,
                         self.position[1] + vy * self.speed * dt)
        if self.speed > 0:
            self.update_spatialized_sound()
            self.check_collisions_with_player()
        self._advance_patrol()

    # ------------------------------------------------------------- patrol
    def _on_follow_path(self, _name: str, params: Params) -> None:
        """``-[PGEGameAgent followPathWithName:]``

        Addressed by **senderName**, not by a ``name`` parameter: the trigger
        has to be on the agent that is meant to walk it, and ``name`` carries
        the *path's* name.  That is how ps1_5's hog starts patrolling - its own
        ``OnLoad`` says ``FollowPathWithName:name=path1``.
        """
        if params.get('senderName') != self.name:
            return
        self.path = None
        want = params.get('name')
        if want and self.level is not None:
            self.path = self.level.path_with_name(str(want))
        if self.path:
            self.has_path = True
            self.state = 1               # forced to idle so the patrol can run
            self.find_next_patrol_point()

    def _on_stop_following_path(self, _name: str, params: Params) -> None:
        """``-[PGEGameAgent stopFollowingPath:]``

        Note what it does *not* do: ``hasPath`` is left set.  With no path to
        read, ``findNextPatrolPoint`` returns immediately, and the zeroed
        orientation vector is what actually stops the agent.
        """
        if params.get('senderName') != self.name:
            return
        self.state = 0
        self.path = None
        self.orientation_vector = (0.0, 0.0)

    def find_next_patrol_point(self) -> None:
        """``-[PGEGameAgent findNextPatrolPoint]``

        Aims at the next point on the route and remembers how far it is.  Two
        things worth keeping: it only runs **while the agent is idle**, so an
        alerted enemy abandons its patrol and picks it up again when it calms
        down; and running off the end of the list fires ``OnPathEnd`` and wraps
        to the start, so a route is a loop rather than a one-way trip.
        """
        if self.state != 1 or not self.path:
            return
        idx = self.path_current_point
        if idx >= len(self.path):
            idx = 0
        goal = self.path[idx]
        self.wanted_patrol_point = goal
        dx = goal[0] - self.position[0]
        dy = goal[1] - self.position[1]
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 0.0:
            self.orientation_vector = (dx / dist, dy / dist)
        else:
            self.orientation_vector = (dx, dy)
        self.squared_distance_from_next_patrol_point = dist * dist
        self.path_current_point = idx + 1
        if self.path_current_point >= len(self.path):
            self.trigger_on_path_end()
            self.path_current_point = 0

    def trigger_on_path_end(self) -> None:
        self.trigger('OnPathEnd')

    def _advance_patrol(self) -> None:
        """The ``hasPath`` tail of ``-[PGEGameAgent update:]``.

        Arrival is the same "stopped getting closer" test the enemy uses for a
        goal: the squared distance is remembered each frame, and the moment it
        grows - or hits zero - the agent takes the next point.
        """
        if not self.has_path:
            return
        dx = self.wanted_patrol_point[0] - self.position[0]
        dy = self.wanted_patrol_point[1] - self.position[1]
        d2 = dx * dx + dy * dy
        if d2 == 0.0 or d2 > self.squared_distance_from_next_patrol_point:
            self.squared_distance_from_next_patrol_point = float('inf')
            self.find_next_patrol_point()
        else:
            self.squared_distance_from_next_patrol_point = d2

    def find_direction_to(self, x: float, y: float) -> float:
        """``-[PGEGameAgent findDirectionToPlayer]`` / ``-[PGEEnemy findDirectionTo:]``

        Points ``orientationVector`` at the goal, normalised, and returns how
        long the trip would take at ``chaseSpeed``.  ``PGEEnemy``'s version also
        records the squared distance, which is what its arrival test compares
        against, so it is recorded here for every agent.
        """
        dx = x - self.position[0]
        dy = y - self.position[1]
        dist = math.sqrt(dx * dx + dy * dy)
        if dist == 0.0:
            self.orientation_vector = (0.0, 0.0)
            self.squared_distance_from_goal = 0.0
            return 0.0
        self.orientation_vector = (dx / dist, dy / dist)
        self.squared_distance_from_goal = dist * dist
        speed = getattr(self, 'chase_speed', 0.0) or self.speed
        return dist / speed if speed else 0.0

    def find_direction_to_player(self) -> float:
        return self.find_direction_to(*self.player_position)

    # ---------------------------------------------------------- collisions
    def check_collisions_with_player(self) -> bool:
        """``-[PGEGameAgent checkCollisionsWithPlayer]``"""
        if not self.active:
            return False
        dx = self.player_position[0] - self.position[0]
        dy = self.player_position[1] - self.position[1]
        if (dx * dx + dy * dy) < (self.collide_radius * self.collide_radius):
            self.collides_with_player()
            return True
        return False

    def collides_with_player(self) -> None:
        """``-[PGEGameAgent collidesWithPlayer]``"""
        self.trigger('OnCollide')

    # ------------------------------------------------------- shooting range
    @property
    def is_in_shooting_range(self) -> bool:
        return self._is_in_shooting_range

    @is_in_shooting_range.setter
    def is_in_shooting_range(self, value: bool) -> None:
        """``-[PGEGameAgent setIsInShootingRange:]`` - edge triggered."""
        value = bool(value)
        if value and not self._is_in_shooting_range and self.active:
            self.on_entering_shooting_range()
        elif not value and self._is_in_shooting_range and self.active:
            self.on_leaving_shooting_range()
        self._is_in_shooting_range = value

    def on_entering_shooting_range(self) -> None:
        self.trigger('OnEnteringShootRange')

    def on_leaving_shooting_range(self) -> None:
        pass          # -[PGEGameAgent onLeavingShootingRange] does nothing

    # -------------------------------------------------------- spatial audio
    def update_spatialized_sound(self) -> None:
        """``-[PGEGameAgent updateSpatializedSound]``

        Keeps the sound where the agent is, and works out whether the player is
        facing it: the dot product of the player's facing vector with the unit
        vector towards this agent must exceed 0.98, and the distance must be
        within ``shootRange`` (infinite unless the level says otherwise).
        """
        if self.sound is not None and self.sound.spatialized:
            self.sound.planar = (self.position[0], self.position[1], 0.0)
        if not self.active:
            return
        dx = self.position[0] - self.player_position[0]
        dy = self.position[1] - self.player_position[1]
        dist = math.sqrt(dx * dx + dy * dy)
        if dist <= 0.0:
            self.is_in_shooting_range = False
            return
        ox, oy = self.player_orientation_vector
        dot = ox * (dx / dist) + oy * (dy / dist)
        if dot > FACING_DOT_THRESHOLD:
            self.is_in_shooting_range = dist < self.shoot_range
        else:
            self.is_in_shooting_range = False

    def play_spatial_sound(self, name: str) -> None:
        if self.bank is None:
            return
        s = self.bank.sound(name)
        if s is None:
            return
        s.spatialized = True
        s.planar = (self.position[0], self.position[1], 0.0)
        s.play()

    # ------------------------------------------------------------ handlers
    def _on_player_moved(self, _name: str, params: Params) -> None:
        """``-[PGEGameAgent playerMovedToPosition:]``

        Two things here are easy to get wrong, and both are deliberate:

        * the collision check runs **before** the new position is stored, so it
          tests where the player *was*.  A hit therefore registers one step
          late;
        * it is skipped entirely while either stored coordinate is exactly
          ``0.0``.  That guard exists for the uninitialised ``(0, 0)`` before
          the player has moved at all, but it also fires whenever the player is
          exactly on an axis - a fault, reproduced rather than corrected.
        """
        px, py = self.player_position
        if px != 0.0 and py != 0.0:
            self.check_collisions_with_player()
        pos = params.get('position')
        if isinstance(pos, (tuple, list)) and len(pos) >= 2:
            self.player_position = (float(pos[0]), float(pos[1]))
        ov = params.get('orientationVector')
        if isinstance(ov, (tuple, list)) and len(ov) >= 2:
            self.player_orientation_vector = (float(ov[0]), float(ov[1]))
        self.update_spatialized_sound()

    def _on_player_rotated(self, _name: str, params: Params) -> None:
        """``-[PGEGameAgent playerDidRotate:]``"""
        self.player_orientation = float(params.get('orientation', 0.0))
        ov = params.get('orientationVector')
        if isinstance(ov, (tuple, list)) and len(ov) >= 2:
            self.player_orientation_vector = (float(ov[0]), float(ov[1]))
        pos = params.get('position')
        if isinstance(pos, (tuple, list)) and len(pos) >= 2:
            self.player_position = (float(pos[0]), float(pos[1]))
        self.update_spatialized_sound()

    def _on_level_inited(self, _name: str, _params: Params) -> None:
        """``-[PGEGameAgent levelInited:]`` - fires this object's ``OnLoad``.

        The level posts ``PGE_MESSAGE_LevelInited`` once the room, the agents
        and the player are all built.  Eight monsters across seven levels hang
        their opening move on it (``FollowPathWithName``, ``AlertAllEnemies``),
        so without it they simply never start.
        """
        self.trigger('OnLoad')

    def _on_activate_named(self, _name: str, params: Params) -> None:
        """``activateAgentWithName:`` goes through ``setActive:``, which acts
        only on a **transition** - activating something already active does
        nothing, and does not re-fire ``OnActivate`` or restart its sound."""
        if addressed_to(params, self.name) and not self.active:
            self.activate()

    def _on_deactivate_named(self, _name: str, params: Params) -> None:
        if addressed_to(params, self.name) and self.active:
            self.deactivate()

    def _on_change_sound_list(self, _name: str, params: Params) -> None:
        if addressed_to(params, self.name):
            self.sound_list = params.get('soundList', self.sound_list)

    def _on_play_spatial_named(self, _name: str, params: Params) -> None:
        if addressed_to(params, self.name, key='agentName'):
            self.play_spatial_sound(params.get('soundName', ''))

    def _on_move_named(self, _name: str, params: Params) -> None:
        if addressed_to(params, self.name):
            pos = params.get('position')
            if isinstance(pos, (tuple, list)) and len(pos) >= 2:
                self.position = (float(pos[0]), float(pos[1]))
                self.update_spatialized_sound()


def _b(v) -> bool:
    return str(v).strip().lower() in ('yes', 'true', '1')


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


#: Property name -> how to apply it, standing in for the engine's
#: ``set<Capitalised key>:`` selector lookup.  Anything not listed is ignored,
#: exactly as an object that does not respond to the selector would be.
_SETTERS = {
    'active':          lambda o, v: setattr(o, 'active', _b(v)),
    'collideRadius':   lambda o, v: setattr(o, 'collide_radius', _f(v)),
    # KVC on the original sets the `speed` property and nothing else; the port
    # used to mirror it into walking_speed, which is not what the engine does.
    'speed':           lambda o, v: setattr(o, 'speed', _f(v)),
    'gain':            lambda o, v: setattr(o, 'gain', _f(v)),
    'soundList':       lambda o, v: setattr(o, 'sound_list', str(v)),
    'spatialized':     lambda o, v: setattr(o, 'spatialized', _b(v)),
    'looping':         lambda o, v: setattr(o, 'looping', _b(v)),
    'skippable':       lambda o, v: setattr(o, 'skippable', _b(v)),
    'shootRange':      lambda o, v: setattr(o, 'shoot_range', _f(v)),
    # PGEEnemy
    'defaultSound':    lambda o, v: setattr(o, 'default_sound', str(v)),
    'awareSound':      lambda o, v: setattr(o, 'aware_sound', str(v)),
    'chaseSound':      lambda o, v: setattr(o, 'chase_sound', str(v)),
    'notThereSound':   lambda o, v: setattr(o, 'not_there_sound', str(v)),
    'attackSound':     lambda o, v: setattr(o, 'attack_sound', str(v)),
    'walkingPauseSound': lambda o, v: setattr(o, 'walking_pause_sound', str(v)),
    'walkingSpeed':    lambda o, v: setattr(o, 'walking_speed', _f(v)),
    'chaseSpeed':      lambda o, v: setattr(o, 'chase_speed', _f(v)),
    # PGEDilemma
    'restSound':       lambda o, v: setattr(o, 'rest_sound', str(v)),
    'alertSound':      lambda o, v: setattr(o, 'alert_sound', str(v)),
    'thanksSound':     lambda o, v: setattr(o, 'thanks_sound', str(v)),
    'abandonSound':    lambda o, v: setattr(o, 'abandon_sound', str(v)),
    'dilemmaID':       lambda o, v: setattr(o, 'dilemma_id', str(v)),
    'bpmMalus':        lambda o, v: setattr(o, 'bpm_malus', _f(v)),
    'alertDistance':   lambda o, v: setattr(o, 'alert_distance', _f(v)),
    'distractedTime':  lambda o, v: setattr(o, 'distracted_time', _f(v)),
    'chasingRadius':   lambda o, v: setattr(o, 'chasing_radius', _f(v)),
    'onXrail':         lambda o, v: setattr(o, 'on_x_rail', _b(v)),
    'onYrail':         lambda o, v: setattr(o, 'on_y_rail', _b(v)),
    'introSound':      lambda o, v: setattr(o, 'intro_sound', str(v)),
    'loopSound':       lambda o, v: setattr(o, 'loop_sound', str(v)),
    'collectSound':    lambda o, v: setattr(o, 'collect_sound', str(v)),
    'nextCollectible': lambda o, v: setattr(o, 'next_collectible', str(v)),
}
