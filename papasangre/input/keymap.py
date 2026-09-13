"""Rebindable keyboard bindings.

The iOS original had no keyboard, so the *bindings* are new; the **actions**
are not - each one corresponds to something the original's
``PGEMoveInterpretor`` or view controllers could do, so gameplay code only ever
talks about actions and never about keys.

Bindings live in ``config/keys.json`` next to the executable, so they can be
changed without touching gameplay code.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum

from ..util import paths


class Action(str, Enum):
    """Everything the player can ask the game to do."""

    # Walking: the core mechanic. Feet alternate; pressing the same foot twice
    # inside a second trips you (recovered from footButtonReleased:).
    FOOT_LEFT = 'foot_left'
    FOOT_RIGHT = 'foot_right'

    # Turning. Continuous while held.
    TURN_LEFT = 'turn_left'
    TURN_RIGHT = 'turn_right'

    # Hands and clapping.  The engine supports these and Papa Sangre II uses
    # them; **Papa Sangre 1 never enables them** - across all 27 levels the data
    # sends DisableHands 27 times and EnableHands zero times, and never touches
    # swim or jump at all.  They are bound so the engine stays complete, but in
    # this game they do nothing.
    HAND_LEFT = 'hand_left'
    HAND_RIGHT = 'hand_right'
    CLAP = 'clap'

    JUMP = 'jump'
    SWIM = 'swim'
    ACTION = 'action'                      # ActionSurface button

    # Shell and accessibility.
    PAUSE = 'pause'
    CONFIRM = 'confirm'
    CANCEL = 'cancel'
    MENU_UP = 'menu_up'
    MENU_DOWN = 'menu_down'
    #: Changing a setting on the row you are on.  Deliberately *not* the feet:
    #: on the keyboard these are the arrow keys, and on a controller the d-pad,
    #: which happens to be the feet in play but is only ever a menu here.
    MENU_LEFT = 'menu_left'
    MENU_RIGHT = 'menu_right'
    SKIP = 'skip'                          # skippable cutscene
    VOLUME_UP = 'volume_up'
    VOLUME_DOWN = 'volume_down'


#: Bumped whenever a *default* binding moves, so a file written by an older
#: build is replaced rather than silently overriding the new layout.
#:   1  the original set
#:   2  escape opens the pause menu instead of quitting; menu_left/right added
#:   3  F1/F2/F3 and the comma/full-stop nudge removed - turning is the
#:      arrow keys and nothing else
BINDINGS_VERSION = 3
VERSION_KEY = '_version'

#: Default bindings.  Keys are SDL key names as pygame reports them.
#:
#: The layout is split by hand, because walking and turning have to happen at
#: the same time.  Walking is a constant left-right-left-right alternation, so
#: it gets a whole hand to itself:
#:
#:   LEFT HAND   A and D are the two feet; Q and E are the two hands, sitting
#:               directly above them; W jumps, S swims.
#:   RIGHT HAND  the arrow keys turn, plus the shell keys around them.
#:
#: Anything with both feet on one side of the keyboard (A and L, say) leaves no
#: hand free to steer with, which is why this is arranged the way it is.
DEFAULT_BINDINGS: dict[str, list[str]] = {
    # left hand
    Action.FOOT_LEFT.value:       ['a'],
    Action.FOOT_RIGHT.value:      ['d'],
    Action.HAND_LEFT.value:       ['q'],
    Action.HAND_RIGHT.value:      ['e'],
    Action.SWIM.value:            ['s'],
    Action.JUMP.value:            ['w', 'up'],
    # right hand
    Action.TURN_LEFT.value:       ['left'],
    Action.TURN_RIGHT.value:      ['right'],
    Action.CLAP.value:            ['right shift'],
    # Enter skips narration.  ACTION is deliberately unbound: it belongs to
    # PGEActionSurface, and no level in Papa Sangre 1 contains one, so giving it
    # a key would only clash with skip for a button nothing can press.
    Action.ACTION.value:          [],
    Action.CONFIRM.value:         ['return', 'keypad enter'],
    Action.SKIP.value:            ['return', 'keypad enter'],
    # [N] the original paused on a triple-tap.  Escape does both jobs here and
    # they never collide: in play it opens the pause menu (CANCEL is ignored
    # there), in a menu it backs out (PAUSE is ignored there).  **Nothing on
    # the keyboard quits the game** - that is alt+F4, or Quit in the menu.
    Action.PAUSE.value:           ['escape', 'p'],
    Action.CANCEL.value:          ['escape', 'backspace'],
    Action.MENU_UP.value:         ['up'],
    Action.MENU_DOWN.value:       ['down'],
    Action.MENU_LEFT.value:       ['left'],
    Action.MENU_RIGHT.value:      ['right'],
    Action.VOLUME_UP.value:       ['page up', '='],
    Action.VOLUME_DOWN.value:     ['page down', '-'],
}


@dataclass
class KeyMap:
    """Action <-> key bindings, loadable and saveable."""

    bindings: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_BINDINGS.items()})
    #: Where this was loaded from, so ``save()`` goes back to the same file
    #: rather than always to the default one.
    path: str | None = None

    # ------------------------------------------------------------------
    @staticmethod
    def _key(action) -> str:
        """Normalise an Action or plain string to the stored key.

        ``str(Action.FOOT_LEFT)`` gives 'Action.FOOT_LEFT' on Python 3.11+, not
        the value, so going through ``.value`` matters.
        """
        return action.value if isinstance(action, Action) else str(action)

    def actions_for(self, key_name: str) -> list[str]:
        key = key_name.lower()
        return [a for a, keys in self.bindings.items()
                if key in (k.lower() for k in keys)]

    def keys_for(self, action) -> list[str]:
        return list(self.bindings.get(self._key(action), ()))

    def bind(self, action, keys) -> None:
        self.bindings[self._key(action)] = [str(k).lower() for k in keys]

    def describe(self, action) -> str:
        keys = self.keys_for(action)
        return ' or '.join(keys) if keys else 'unbound'

    # ------------------------------------------------------------------
    @classmethod
    def default_path(cls) -> str:
        d = os.path.join(paths.writable_root(), 'config')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, 'keys.json')

    @classmethod
    def load(cls, path: str | None = None, write_default: bool = True) -> 'KeyMap':
        """Load the bindings, writing the defaults out on first run.

        Writing the file makes it discoverable: the player can open
        ``config/keys.json`` next to the executable and change any key without
        being told the file exists.

        **A file written by an older build is discarded.**  It has to be: a
        stored binding overrides the default, so when escape moved from "quit"
        to "open the pause menu", everyone who had already run the game kept
        the old one and escape did nothing.  The keys are not worth silently
        breaking the game over, so the file carries a version and a mismatch
        resets it - ``was_reset`` is set so the app can say so out loud.
        """
        path = path or cls.default_path()
        km = cls(path=path)
        km.was_reset = False
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    stored = json.load(fh)
            except (OSError, ValueError):
                return km     # a corrupt file must never stop the game starting
            if not isinstance(stored, dict):
                return km
            if int(stored.get(VERSION_KEY, 0) or 0) != BINDINGS_VERSION:
                km.was_reset = True
                try:
                    km.save(path)
                except OSError:
                    pass
                return km
            for action, keys in stored.items():
                if action != VERSION_KEY and isinstance(keys, list):
                    km.bindings[action] = [str(k).lower() for k in keys]
        elif write_default:
            try:
                km.save(path)
            except OSError:
                pass
        return km

    def conflicts(self, among=None) -> dict[str, list[str]]:
        """Keys bound to more than one of ``among`` (default: the game actions).

        Menu and gameplay actions may share a key because they are never live at
        the same time; two *gameplay* actions on one key is a real clash.
        """
        if among is None:
            among = [Action.FOOT_LEFT, Action.FOOT_RIGHT, Action.TURN_LEFT,
                     Action.TURN_RIGHT, Action.HAND_LEFT,
                     Action.HAND_RIGHT, Action.CLAP, Action.JUMP, Action.SWIM,
                     Action.ACTION, Action.SKIP, Action.CANCEL]
        wanted = {self._key(a) for a in among}
        seen: dict[str, list[str]] = {}
        for action, keys in self.bindings.items():
            if action not in wanted:
                continue
            for k in keys:
                seen.setdefault(k.lower(), []).append(action)
        return {k: v for k, v in seen.items() if len(v) > 1}

    def save(self, path: str | None = None) -> str:
        path = path or self.path or self.default_path()
        out = dict(self.bindings)
        out[VERSION_KEY] = BINDINGS_VERSION
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
        return path

    def reset(self) -> None:
        self.bindings = {k: list(v) for k, v in DEFAULT_BINDINGS.items()}
