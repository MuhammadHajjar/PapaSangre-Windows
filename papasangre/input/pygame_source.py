"""Keyboard input via SDL, mapped through the rebindable :class:`KeyMap`.

A window is needed only to receive key events; nothing is ever drawn in it.
Key **timing** is what the whole game runs on, so the loop polls at a high rate
and timestamps events from ``time.perf_counter`` on arrival - the same
granularity the original got from ``[NSDate date]`` inside its touch handler.
"""

from __future__ import annotations

import time

import pygame

from .gamepad import Gamepad
from .keymap import Action, KeyMap
from .padmap import PadMap


class PygameInput:
    """Opens a window, translates SDL keys into actions."""

    def __init__(self, keymap: KeyMap | None = None,
                 title: str = 'Papa Sangre',
                 padmap: PadMap | None = None) -> None:
        self.keymap = keymap or KeyMap.load()
        self.padmap = padmap or PadMap.load()
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((640, 200))
        pygame.display.set_caption(title)
        pygame.key.set_repeat(0)             # no auto-repeat: steps are discrete
        self.quit_requested = False
        self.held: set[str] = set()
        #: A controller, if one is plugged in.  It feeds the same action
        #: stream as the keyboard, so nothing downstream knows the difference.
        self.pad = Gamepad(self.padmap)

    # ------------------------------------------------------------------
    @staticmethod
    def key_name(key: int) -> str:
        return pygame.key.name(key).lower()

    # ------------------------------------------------------------------
    def capture_key(self, timeout: float = 10.0) -> str | None:
        """Wait for one raw key and return its name.

        Raw: the key is *not* run through the bindings, because the whole
        point is to find out which key was pressed before it means anything.
        Escape cancels, which is why escape itself cannot be rebound here -
        it has to stay the way out of a screen that is swallowing every key.
        Returns None if cancelled or nothing was pressed in ``timeout``.
        """
        pygame.event.clear()
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit_requested = True
                    return None
                if event.type == pygame.KEYDOWN:
                    name = self.key_name(event.key)
                    return None if name == 'escape' else name
            pygame.time.wait(10)
        return None

    def capture_button(self, timeout: float = 10.0) -> str | None:
        """Wait for one controller button and return its bindable name.

        Escape on the keyboard cancels: a controller has no key that is
        guaranteed not to be the one you are trying to bind.
        """
        pygame.event.clear()
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit_requested = True
                    return None
                if event.type == pygame.KEYDOWN:
                    if self.key_name(event.key) == 'escape':
                        return None
                    continue
                if event.type == pygame.JOYHATMOTION:
                    name = self.pad.hat_name(event.value)
                    if name:
                        self.pad._hat = tuple(event.value)
                        return name
                    continue
                name = self.pad.button_name(event)
                if name and event.type in (pygame.CONTROLLERBUTTONDOWN,
                                           pygame.JOYBUTTONDOWN):
                    return name
            # A trigger sends no event, so it has to be looked at rather than
            # waited for.  Without this the rebinding screen simply ignored
            # anyone pulling L2 or R2, which is how the feet could not be put
            # on the triggers.
            pulled = self.pad.pressed_trigger()
            if pulled:
                self.pad._trigger_down[pulled] = True
                return pulled
            pygame.time.wait(10)
        return None

    def poll(self) -> list[tuple[str, str, float]]:
        """Return ``(action, 'down'|'up', timestamp)`` for everything pending."""
        out: list[tuple[str, str, float]] = []
        for event in pygame.event.get():
            now = time.perf_counter()
            if event.type == pygame.QUIT:
                self.quit_requested = True
            elif event.type in (pygame.KEYDOWN, pygame.KEYUP):
                name = self.key_name(event.key)
                phase = 'down' if event.type == pygame.KEYDOWN else 'up'
                for action in self.keymap.actions_for(name):
                    if phase == 'down':
                        self.held.add(action)
                    else:
                        self.held.discard(action)
                    out.append((action, phase, now))
            else:
                out.extend(self.pad.handle(event))
        # The triggers are axes, so they arrive as no event at all and have to
        # be read once a frame - see Gamepad.poll_triggers.
        out.extend(self.pad.poll_triggers())
        return out

    def is_held(self, action) -> bool:
        key = action.value if isinstance(action, Action) else str(action)
        return key in self.held or self.pad.is_held(key)

    def turn_rate(self) -> float:
        """Right stick deflection, -1..1.  Zero when no pad is connected."""
        return self.pad.turn_rate()

    def close(self) -> None:
        self.pad.close()
        pygame.display.quit()
