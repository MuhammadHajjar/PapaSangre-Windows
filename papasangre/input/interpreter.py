"""``PGEMoveInterpretor`` - turns raw input into the engine's action messages.

This is where Papa Sangre's walking mechanic lives.  You do not hold a
direction; you place one foot, then the other, and the *timing* of that
alternation is the whole control scheme.  Everything below is recovered from
``-[PGEMoveInterpretor footButtonPressed:]`` and ``footButtonReleased:``.

The rules, exactly as the original has them:

* Nothing happens unless ``player_can_walk``.
* Nothing happens while the player state is 3 (tripped).
* A foot must be pressed and then **released** - the step fires on release.
  (The Windows port calls both on key-down instead, so the foot lands as you
  press it; nothing in this class changes for that - see DIVERGENCES §4c.)
* **A foot whose entry in ``feetViewDict`` is "off" is ignored entirely**, on
  both press and release.  This is the alternation rule, and it is the whole
  reason you cannot run by hammering one key: the foot you just used is put
  "off" and stays there.
* Otherwise the foot's timestamp is updated and ``PGE_ACTION_OneStep`` is posted
  carrying ``lastFoot``, which is what advances the player.

``updateFeetView:`` is what decides which feet are available, and it is called
after every step and again 0.1 s and 2.0 s later.  For each foot:

* if it is the foot you last used and you used it less than **2 seconds** ago,
  it is **"off"** - unavailable;
* otherwise it is **"on"**, and if it is the foot you last used and the gap has
  grown past 2 seconds (but is under 99), the engine posts ``PGE_ACTION_Shuffle``
  - the sound of you shifting your weight - and forgets which foot you used, so
  both feet are free again.

So: alternate and you walk; repeat a foot and nothing happens at all; stand
still for two seconds and you hear yourself shuffle and may start on either
foot.  The 1-second same-foot ``PGE_ACTION_Trip`` branch further down is real
code in the binary but is unreachable behind this gate - see ``trip_would_fire``.

The enable/disable flags (walk, rotate, jump, hands, swim) are driven by the
``PGE_MESSAGE_Enable*`` / ``Disable*`` messages that level triggers send - every
level's Room begins by disabling walking and rotation until its intro narration
finishes.
"""

from __future__ import annotations

from ..core.messages import MessageBus, Params

# Action messages this layer produces, named as the original names them.
ACTION_ONE_STEP = 'PGE_ACTION_OneStep'
ACTION_TRIP = 'PGE_ACTION_Trip'
ACTION_ROTATE_FROM_ANGLE = 'PGE_ACTION_RotatePlayerFromAngle'
ACTION_ROTATE_TO_FIXED_ANGLE = 'PGE_ACTION_RotatePlayerToFixedAngle'
ACTION_JUMP = 'PGE_ACTION_Jump'
ACTION_SWIM = 'PGE_ACTION_Swim'
ACTION_HANDS = 'PGE_ACTION_Hands'
ACTION_BUTTON_PRESSED = 'PGE_MESSAGE_ActionButtonPressed'

ACTION_SHUFFLE = 'PGE_ACTION_Shuffle'
MESSAGE_UPDATE_FEET_VIEW = 'PGE_MESSAGE_UpdateFeetView'

#: The two ``dispatch_after`` re-evaluations at the end of
#: ``footButtonReleased:``: 0x05f5e100 ns and 0x77359400 ns.
INTERNAL_UPDATE_FEET_VIEW = 'PGE_INTERNAL_UpdateFeetView'
FEET_VIEW_DELAYS = (0.1, 2.0)

#: How long the foot you just used stays unavailable.  ``fmov s9, #2.0``
#: compared against the clamped ``|timeIntervalSinceNow|`` at 0x100008144 (left)
#: and 0x10000823c (right) in ``-[PGEMoveInterpretor updateFeetView:]``.
FOOT_LOCKOUT_SECONDS = 2.0

#: Past the lockout the engine plays a shuffle and frees both feet - but only
#: below this bound, so a foot you have not used in a very long time (or at all)
#: stays silent.  0x100141be4 = 99.0f.
SHUFFLE_MAX_SECONDS = 99.0

#: ``|timeIntervalSinceNow|`` is clamped before either test.  0x100141bd0 = 100.0.
FOOT_INTERVAL_CLAMP = 100.0

#: Repeating the same foot inside this many seconds posts ``PGE_ACTION_Trip``.
#: Recovered: ``fmov d0, #1.0`` against ``fabs(timeIntervalSinceNow)`` at
#: 0x1000088c4 and 0x100008968 in ``-[PGEMoveInterpretor footButtonReleased:]``.
#:
#: **This branch cannot be reached.**  To repeat a foot within one second you
#: must first get past the ``"off"`` gate, and that gate holds the foot you last
#: used for two full seconds.  The port keeps the branch because the binary has
#: it; ``trip_would_fire`` exists so a test can prove it stays dead.
SAME_FOOT_TRIP_WINDOW = 1.0

LEFT, RIGHT, NONE = 'L', 'R', 'N'

#: ``feetViewDict`` values.  **"off" means the foot is unavailable**, not that it
#: is merely un-held: ``footButtonPressed:`` and ``footButtonReleased:`` both
#: return immediately when they see it.
OFF, ON, PRESSED = 'off', 'on', 'pressed'


class MoveInterpretor:
    """Input -> action messages, with the original's gating and trip rule."""

    def __init__(self, bus: MessageBus) -> None:
        self.bus = bus

        # -[PGEMoveInterpretor init] calls lockControls, so everything starts off.
        self.player_can_walk = False
        self.player_can_rotate = False
        self.player_can_jump = False
        self.player_can_use_hands = False
        self.player_can_swim = False
        self.player_state = 0

        self.last_left_foot_time: float | None = None
        self.last_right_foot_time: float | None = None
        self.last_foot_button_pressed: str | None = None
        #: The original's ``feetViewDict``: which feet you are allowed to use.
        #: ``init`` calls ``lockControls``, which sets both to "off".
        self.feet = {LEFT: OFF, RIGHT: OFF}

        for name, handler in (
            ('PGE_MESSAGE_EnableWalk', self._enable_walk),
            ('PGE_MESSAGE_DisableWalk', self._disable_walk),
            ('PGE_MESSAGE_EnableRotation', self._enable_rotation),
            ('PGE_MESSAGE_DisableRotation', self._disable_rotation),
            ('PGE_MESSAGE_EnableJump', self._enable_jump),
            ('PGE_MESSAGE_DisableJump', self._disable_jump),
            ('PGE_MESSAGE_EnableHands', self._enable_hands),
            ('PGE_MESSAGE_DisableHands', self._disable_hands),
            ('PGE_MESSAGE_EnableSwim', self._enable_swim),
            ('PGE_MESSAGE_DisableSwim', self._disable_swim),
            ('PGE_MESSAGE_SetControlSettingsToDefault', self._set_defaults),
            ('PGE_MESSAGE_PlayerStateDidChange', self._state_changed),
            (INTERNAL_UPDATE_FEET_VIEW, self._deferred_feet_view),
        ):
            bus.subscribe(name, handler)

    # ------------------------------------------------------------ gating
    def lock_controls(self) -> None:
        self.player_can_walk = False
        self.player_can_rotate = False
        self.player_can_jump = False
        self.player_can_use_hands = False
        self.player_can_swim = False
        self.update_feet_view()

    def set_settings_to_default(self) -> None:
        self.player_can_walk = True
        self.player_can_rotate = True
        self.player_can_jump = False
        self.player_can_use_hands = True
        self.player_can_swim = False
        self.update_feet_view()

    # Only these five re-evaluate the feet; rotation, hands and jump do not.
    def _enable_walk(self, *_):
        self.player_can_walk = True
        self.update_feet_view()

    def _disable_walk(self, *_):
        self.player_can_walk = False
        self.update_feet_view()

    def _enable_swim(self, *_):
        self.player_can_swim = True
        self.update_feet_view()

    def _disable_swim(self, *_):
        self.player_can_swim = False
        self.update_feet_view()

    def _enable_rotation(self, *_):  self.player_can_rotate = True
    def _disable_rotation(self, *_): self.player_can_rotate = False
    def _enable_jump(self, *_):      self.player_can_jump = True
    def _disable_jump(self, *_):     self.player_can_jump = False
    def _enable_hands(self, *_):     self.player_can_use_hands = True
    def _disable_hands(self, *_):    self.player_can_use_hands = False

    def _set_defaults(self, *_):
        self.set_settings_to_default()

    def _state_changed(self, _name: str, params: Params) -> None:
        self.player_state = int(params.get('state', self.player_state))
        self.update_feet_view()

    # -------------------------------------------------------------- feet
    def foot_pressed(self, foot: str) -> bool:
        """``-[PGEMoveInterpretor footButtonPressed:]``"""
        if not self.player_can_walk:
            return False
        if self.player_state == 3:            # tripped
            return False
        if foot not in (LEFT, RIGHT):
            return False
        if self.feet.get(foot) == OFF:
            return False                      # that foot is not yours to use yet
        self.feet[foot] = PRESSED
        self.bus.post(MESSAGE_UPDATE_FEET_VIEW, dict(self.feet))
        return True

    def foot_released(self, foot: str, now: float) -> bool:
        """``-[PGEMoveInterpretor footButtonReleased:]`` - this is the step."""
        if not self.player_can_walk:
            return False
        if self.player_state == 3:
            return False
        if foot not in (LEFT, RIGHT):
            return False
        if self.feet.get(foot) == OFF:
            return False                      # same gate as the press

        info = {'lastFoot': foot}
        if self.trip_would_fire(foot, now):
            # Dead code in the shipped game - see SAME_FOOT_TRIP_WINDOW.  Note
            # what it skips: no timestamp, no step, and lastFootButtonPressed is
            # left alone; only the feet view is refreshed.
            self.bus.post(ACTION_TRIP, info)
            self._refresh_feet_view(now)
            return False

        self._record(foot, now)
        self.bus.post(ACTION_ONE_STEP, info)
        self.last_foot_button_pressed = foot
        self._refresh_feet_view(now)
        return True

    # ------------------------------------------------------- the feet view
    def update_feet_view(self, now: float | None = None) -> None:
        """``-[PGEMoveInterpretor updateFeetView:]`` - who may step next.

        Rebuilds ``feetViewDict`` from scratch every time, which is why the
        transient ``"pressed"`` state never survives it, and posts the result.
        The argument the original takes is only a debug tag; it is never read.
        """
        if not self.player_can_walk or self.player_state == 3:
            self.feet = {LEFT: OFF, RIGHT: OFF}
            self.bus.post(MESSAGE_UPDATE_FEET_VIEW, dict(self.feet))
            return

        if now is None:
            now = self.bus.now
        self.feet = {}
        for foot, stamp in ((LEFT, self.last_left_foot_time),
                            (RIGHT, self.last_right_foot_time)):
            # [nil timeIntervalSinceNow] is 0.0, and the result is clamped.
            gap = 0.0 if stamp is None else abs(now - stamp)
            gap = min(gap, FOOT_INTERVAL_CLAMP)
            used_last = self.last_foot_button_pressed == foot
            if used_last and gap < FOOT_LOCKOUT_SECONDS:
                self.feet[foot] = OFF
                continue
            if used_last and FOOT_LOCKOUT_SECONDS <= gap < SHUFFLE_MAX_SECONDS:
                self.bus.post(ACTION_SHUFFLE, {})
                self.last_foot_button_pressed = NONE
            self.feet[foot] = ON
        self.bus.post(MESSAGE_UPDATE_FEET_VIEW, dict(self.feet))

    def _refresh_feet_view(self, now: float) -> None:
        """Re-evaluate now, then again after each of the two fixed delays.

        The original schedules these with ``dispatch_after`` and never cancels
        them, so every step queues its own pair.  The 2.0 s one is the **only**
        thing that ever releases the foot again and fires the shuffle - nothing
        else re-evaluates once you have stopped walking, because there is no
        idle timer in the engine (the ``cancelPreviousPerformRequests`` in
        ``moveForwardOneStep:`` targets ``trip:``'s own recovery).

        So the base instant matters.  The original stamps the foot with
        ``[NSDate date]`` and schedules from the same moment, so the callback is
        guaranteed to land at or after 2.0 s of elapsed foot time.  Here the
        stamp comes from the key event while ``bus.now`` is the previous
        frame, and scheduling off ``bus.now`` made the callback arrive a few
        milliseconds *early* - ``gap`` came out at 1.995 rather than 2.0, the
        foot stayed "off", and the shuffle silently never played.  That is why
        it fired only sometimes.  Schedule from the stamp instead.
        """
        self.update_feet_view(now)
        drift = now - self.bus.now
        for delay in FEET_VIEW_DELAYS:
            self.bus.post_after(max(0.0, delay + drift),
                                INTERNAL_UPDATE_FEET_VIEW, {})

    def _deferred_feet_view(self, *_args) -> None:
        self.update_feet_view()

    # --------------------------------------------------------------- trips
    def trip_would_fire(self, foot: str, now: float) -> bool:
        """The recovered same-foot test, kept exact although nothing reaches it.

        Only meaningful once **both** feet have been used: the original compares
        two NSDates, and comparing against a nil date is undefined, so the port
        does not guess at that case.
        """
        left, right = self.last_left_foot_time, self.last_right_foot_time
        if left is None or right is None:
            return False
        if left < right and foot == RIGHT:
            return abs(now - right) < SAME_FOOT_TRIP_WINDOW
        if left > right and foot == LEFT:
            return abs(now - left) < SAME_FOOT_TRIP_WINDOW
        return False

    def _record(self, foot: str, now: float) -> None:
        if foot == LEFT:
            self.last_left_foot_time = now
        else:
            self.last_right_foot_time = now

    # ------------------------------------------------------------ turning
    def rotate_by(self, radians: float) -> bool:
        """Post a relative turn; the player applies and wraps it."""
        if not self.player_can_rotate:
            return False
        self.bus.post(ACTION_ROTATE_FROM_ANGLE, {'angle': float(radians)})
        return True

    def rotate_to(self, radians: float) -> bool:
        if not self.player_can_rotate:
            return False
        self.bus.post(ACTION_ROTATE_TO_FIXED_ANGLE, {'angle': float(radians)})
        return True

    # ------------------------------------------------------- other actions
    def jump(self) -> bool:
        if not self.player_can_jump:
            return False
        self.bus.post(ACTION_JUMP, {})
        self.update_feet_view()
        return True

    def swim(self, foot: str) -> bool:
        if not self.player_can_swim:
            return False
        self.bus.post(ACTION_SWIM, {'lastFoot': foot})
        return True

    def hand(self, side: str) -> bool:
        if not self.player_can_use_hands:
            return False
        self.bus.post(ACTION_HANDS, {'hand': side})
        return True

    def action_button(self) -> None:
        self.bus.post(ACTION_BUTTON_PRESSED, {})

    # ---------------------------------------------------------------- info
    def describe_state(self) -> str:
        allowed = [n for n, on in (('walk', self.player_can_walk),
                                   ('turn', self.player_can_rotate),
                                   ('jump', self.player_can_jump),
                                   ('hands', self.player_can_use_hands),
                                   ('swim', self.player_can_swim)) if on]
        return ', '.join(allowed) if allowed else 'controls locked'
