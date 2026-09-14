"""Game controller input, mapped onto the same actions as the keyboard.

The original was a touchscreen game with no controller support at all, so none
of this is recovered - it is a port-side addition, like the keyboard.  What it
does have to respect is the shape of the mechanic: walking is two *discrete
alternating presses*, not an axis, because the whole movement system is built
on the timing between them.  So the feet are on the d-pad, and nothing about
walking is derived from how far a stick is pushed.

Which button does what lives in :mod:`padmap` and is rebindable from the
options menu, exactly like the keyboard; the defaults are:

===================  ==========================================
D-pad left / right   left foot / right foot, and left/right in a menu
D-pad up / down      move through a menu
Right stick X        turn, proportional to how far it is pushed
A                    select, and skip narration
B / Back             back
Start                pause menu
Shoulders            volume
===================  ==========================================

**Button positions come from SDL's game controller database, not from raw
button numbers.**  That distinction is the whole reason this module is not
twenty lines long: raw joystick numbering is per-device and wildly
inconsistent.  On an Xbox pad button 0 is A and button 7 is Start; on a
DualShock 4 button 0 is Square and button 7 is R2.  Mapping raw numbers would
mean "A selects" silently became "Square selects, and R2 pauses" on a
PlayStation pad.  SDL knows the layout of several hundred controllers, so
``a`` here means *the bottom face button* - Cross on a PlayStation pad - and
``start`` means Options.

A pad SDL does not recognise falls back to raw joystick numbers, which is a
guess, but a guess that only applies to pads nobody has a mapping for.  The
right stick turns and is not rebindable: it is the only axis the game uses.
"""

from __future__ import annotations

import time

try:
    import pygame
except ImportError:                                   # pragma: no cover
    pygame = None

try:
    from pygame._sdl2 import controller as sdl_controller
except ImportError:                                   # pragma: no cover
    sdl_controller = None

from .keymap import Action
from .padmap import PadMap

#: Below this the stick is treated as centred.  Cheap pads rest at 0.1 or so.
DEAD_ZONE = 0.25


def _button_names() -> dict[int, str]:
    """SDL's normalised button number -> the name bindings are written in."""
    if pygame is None:
        return {}
    pairs = (
        ('CONTROLLER_BUTTON_A', 'a'),
        ('CONTROLLER_BUTTON_B', 'b'),
        ('CONTROLLER_BUTTON_X', 'x'),
        ('CONTROLLER_BUTTON_Y', 'y'),
        ('CONTROLLER_BUTTON_BACK', 'back'),
        ('CONTROLLER_BUTTON_GUIDE', 'guide'),
        ('CONTROLLER_BUTTON_START', 'start'),
        ('CONTROLLER_BUTTON_LEFTSTICK', 'leftstick'),
        ('CONTROLLER_BUTTON_RIGHTSTICK', 'rightstick'),
        ('CONTROLLER_BUTTON_LEFTSHOULDER', 'leftshoulder'),
        ('CONTROLLER_BUTTON_RIGHTSHOULDER', 'rightshoulder'),
        ('CONTROLLER_BUTTON_DPAD_UP', 'dpup'),
        ('CONTROLLER_BUTTON_DPAD_DOWN', 'dpdown'),
        ('CONTROLLER_BUTTON_DPAD_LEFT', 'dpleft'),
        ('CONTROLLER_BUTTON_DPAD_RIGHT', 'dpright'),
    )
    out: dict[int, str] = {}
    for attr, name in pairs:
        number = getattr(pygame, attr, None)
        if number is not None:
            out[int(number)] = name
    return out


#: Raw joystick numbers, used only for a pad SDL has no mapping for.  These are
#: the Xbox layout, which is the commonest thing an unknown pad imitates.
FALLBACK_BUTTON_NAMES = {
    0: 'a', 1: 'b', 2: 'x', 3: 'y',
    4: 'leftshoulder', 5: 'rightshoulder',
    6: 'back', 7: 'start', 8: 'leftstick', 9: 'rightstick',
}
#: A raw hat is one control reporting a direction, not four buttons, so it has
#: to be turned back into the four d-pad names the bindings are written in.
FALLBACK_HAT_NAMES = {
    (-1, 0): 'dpleft', (1, 0): 'dpright',
    (0, 1): 'dpup', (0, -1): 'dpdown',
}
FALLBACK_RIGHT_X_AXES = (2, 3, 4)


class Gamepad:
    """One connected controller, polled alongside the keyboard.

    Produces exactly the same ``(action, 'down'|'up', timestamp)`` tuples the
    keyboard does, so nothing downstream knows the difference.
    """

    def __init__(self, padmap: PadMap | None = None) -> None:
        self.controller = None          # SDL game controller, when recognised
        self.joystick = None            # raw fallback
        self.name = ''
        self.padmap = padmap or PadMap()
        self.held: set[str] = set()
        self._hat = (0, 0)
        self._names = _button_names()
        if pygame is None:
            return
        try:
            pygame.joystick.init()
        except pygame.error:
            return
        if pygame.joystick.get_count() <= 0:
            return
        if sdl_controller is not None:
            try:
                sdl_controller.init()
                if sdl_controller.is_controller(0):
                    self.controller = sdl_controller.Controller(0)
                    self.name = self.controller.name or 'controller'
                    return
            except (pygame.error, AttributeError):
                self.controller = None
        try:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            self.name = self.joystick.get_name()
        except pygame.error:
            self.joystick = None

    @property
    def connected(self) -> bool:
        return self.controller is not None or self.joystick is not None

    @property
    def recognised(self) -> bool:
        """True when SDL knew the pad's layout rather than guessing."""
        return self.controller is not None

    # ------------------------------------------------------------------
    def button_name(self, event) -> str:
        """The bindable name of whatever button an event is about, or ''.

        Used both by the normal loop and by the rebinding screen, so what you
        press to bind is by definition what the game will then listen for.
        """
        if pygame is None:
            return ''
        if event.type in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
            return self._names.get(event.button, '')
        if event.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
            return FALLBACK_BUTTON_NAMES.get(event.button, '')
        return ''

    def _emit(self, names, phase: str, now: float, out: list) -> None:
        for name in names:
            for action in self.padmap.actions_for(name):
                if phase == 'down':
                    self.held.add(action)
                else:
                    self.held.discard(action)
                out.append((action, phase, now))

    def handle(self, event) -> list[tuple[str, str, float]]:
        """Translate one SDL event.  Returns any actions it produced."""
        out: list[tuple[str, str, float]] = []
        if pygame is None or not self.connected:
            return out
        now = time.perf_counter()

        if self.controller is not None:
            if event.type == pygame.CONTROLLERBUTTONDOWN:
                self._emit([self.button_name(event)], 'down', now, out)
            elif event.type == pygame.CONTROLLERBUTTONUP:
                self._emit([self.button_name(event)], 'up', now, out)
            return out

        # Raw fallback.
        if event.type == pygame.JOYBUTTONDOWN:
            self._emit([self.button_name(event)], 'down', now, out)
        elif event.type == pygame.JOYBUTTONUP:
            self._emit([self.button_name(event)], 'up', now, out)
        elif event.type == pygame.JOYHATMOTION:
            # A foot is a press and a release, and both edges have to be
            # reported (held-state tracking needs the up) - and rolling from
            # one direction to another must release the first.
            was, now_hat = self._hat, tuple(event.value)
            self._hat = now_hat
            old = FALLBACK_HAT_NAMES.get(was, '')
            new = FALLBACK_HAT_NAMES.get(now_hat, '')
            if old and old != new:
                self._emit([old], 'up', now, out)
            if new and new != old:
                self._emit([new], 'down', now, out)
        return out

    def hat_name(self, value) -> str:
        """The d-pad name a raw hat position means, for the rebinding screen."""
        return FALLBACK_HAT_NAMES.get(tuple(value), '')

    # ------------------------------------------------------------------
    def _raw_right_x(self) -> float:
        """Right stick X as -1..1, whichever API is in use."""
        if self.controller is not None:
            try:
                v = self.controller.get_axis(pygame.CONTROLLER_AXIS_RIGHTX)
            except (pygame.error, AttributeError):
                return 0.0
            # The controller API reports a signed 16-bit value.
            return max(-1.0, min(1.0, v / 32767.0)) if abs(v) > 1 else float(v)
        if self.joystick is None:
            return 0.0
        value = 0.0
        for axis in FALLBACK_RIGHT_X_AXES:
            try:
                v = self.joystick.get_axis(axis)
            except (pygame.error, IndexError):
                continue
            if abs(v) > abs(value):
                value = v
        return value

    def turn_rate(self) -> float:
        """Right stick X with the dead zone removed and the edge smoothed.

        Negative is left, to match the arrow keys.
        """
        value = self._raw_right_x()
        if abs(value) < DEAD_ZONE:
            return 0.0
        # Rescale so the stick starts moving from zero at the dead zone edge
        # rather than jumping straight to a quarter speed.
        scaled = (abs(value) - DEAD_ZONE) / (1.0 - DEAD_ZONE)
        scaled = min(1.0, scaled)
        return -scaled if value < 0 else scaled

    def is_held(self, action) -> bool:
        key = action.value if isinstance(action, Action) else str(action)
        return key in self.held

    def describe(self) -> str:
        if not self.connected:
            return 'No controller found.'
        what = self.name or 'controller'
        how = '' if self.recognised else (
            ' This pad is not in the controller database, so the buttons are a '
            'best guess at an Xbox layout.')
        return (f'Controller: {what}. '
                f'Your feet are {self.padmap.describe(Action.FOOT_LEFT)} and '
                f'{self.padmap.describe(Action.FOOT_RIGHT)}. '
                'The right stick turns you. '
                f'{self.padmap.describe(Action.CONFIRM)} selects, '
                f'{self.padmap.describe(Action.CANCEL)} goes back, '
                f'{self.padmap.describe(Action.PAUSE)} pauses.' + how)

    def close(self) -> None:
        for obj in (self.controller, self.joystick):
            if obj is not None:
                try:
                    obj.quit()
                except Exception:                          # noqa: BLE001
                    pass
        self.controller = None
        self.joystick = None
