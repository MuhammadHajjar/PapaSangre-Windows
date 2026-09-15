"""Rebindable controller bindings - the pad's answer to :mod:`keymap`.

The original was a touchscreen game, so like the keyboard none of this is
recovered; what is shared with the keyboard is the *action* list, which is
recovered, so a pad button and a key that do the same thing are literally the
same action downstream.

The **triggers are in here too**, as ``lefttrigger`` and ``righttrigger``.
SDL reports them as axes rather than buttons, so nothing would ever have
offered them to bind; they are read each frame and turned into an ordinary
press and release, which is what lets someone put their feet on L2 and R2.

Buttons are named the way SDL's controller database names them - ``a``, ``b``,
``start``, ``dpleft`` - **not** by raw joystick number.  That matters: raw
numbering is per-device, so button 0 is A on an Xbox pad and Square on a
DualShock.  Binding by name means a binding made on one pad still means the
bottom face button on the other.

Bindings live in ``config/controller.json`` beside ``keys.json``.
"""

from __future__ import annotations

import json
import os

from ..util import paths
from .keymap import Action

#: Every button a player can bind, in the order the menu reads them out, with
#: the name spoken for it.  Both layouts are said, because a player with a
#: PlayStation pad has no "Y" to look for.
BUTTONS: tuple[tuple[str, str], ...] = (
    ('a', 'A, or cross'),
    ('b', 'B, or circle'),
    ('x', 'X, or square'),
    ('y', 'Y, or triangle'),
    ('back', 'Back, or share'),
    ('start', 'Start, or options'),
    ('guide', 'Guide'),
    ('leftshoulder', 'Left shoulder, L1'),
    ('rightshoulder', 'Right shoulder, R1'),
    ('lefttrigger', 'Left trigger, L2'),
    ('righttrigger', 'Right trigger, R2'),
    ('leftstick', 'Left stick click, L3'),
    ('rightstick', 'Right stick click, R3'),
    ('dpup', 'D-pad up'),
    ('dpdown', 'D-pad down'),
    ('dpleft', 'D-pad left'),
    ('dpright', 'D-pad right'),
)

BUTTON_LABELS = dict(BUTTONS)


def button_label(name: str) -> str:
    """What to say for a button name."""
    return BUTTON_LABELS.get(str(name).lower(), str(name))


#: Bumped when a *default* binding moves, so an older file is replaced rather
#: than silently overriding the new layout - same contract as the keyboard's.
#:   1  the first controller layout
PAD_BINDINGS_VERSION = 1
VERSION_KEY = '_version'

#: The defaults.
#:
#: The feet are the d-pad because walking is two discrete alternating presses,
#: never an axis - the whole movement system is built on the timing between
#: them, so a stick would have nothing to time.  Left and right on the d-pad
#: therefore mean *both* a foot and a menu direction: the two contexts ignore
#: what they do not use, which is what lets d-pad left be a foot while walking
#: and a slider in the options.
#:
#: ``a`` confirms *and* skips, exactly as Enter does on the keyboard.
DEFAULT_PAD_BINDINGS: dict[str, list[str]] = {
    Action.FOOT_LEFT.value:   ['dpleft'],
    Action.FOOT_RIGHT.value:  ['dpright'],
    Action.CONFIRM.value:     ['a'],
    Action.SKIP.value:        ['a', 'x'],
    Action.CANCEL.value:      ['b', 'back'],
    Action.PAUSE.value:       ['start'],
    Action.MENU_UP.value:     ['dpup'],
    Action.MENU_DOWN.value:   ['dpdown'],
    Action.MENU_LEFT.value:   ['dpleft'],
    Action.MENU_RIGHT.value:  ['dpright'],
    Action.VOLUME_UP.value:   ['rightshoulder'],
    Action.VOLUME_DOWN.value: ['leftshoulder'],
    # Papa Sangre 1 never enables hands, clapping, jumping or swimming, so
    # they stay unbound - but they are listed, so a file written out by the
    # game shows every action there is.
    Action.HAND_LEFT.value:   [],
    Action.HAND_RIGHT.value:  [],
    Action.CLAP.value:        [],
    Action.JUMP.value:        [],
    Action.SWIM.value:        [],
    Action.ACTION.value:      [],
    Action.TURN_LEFT.value:   [],     # the right stick turns; see gamepad.py
    Action.TURN_RIGHT.value:  [],
}


class PadMap:
    """Action <-> controller button bindings, loadable and saveable."""

    def __init__(self, bindings: dict[str, list[str]] | None = None,
                 path: str | None = None) -> None:
        self.bindings = ({k: list(v) for k, v in DEFAULT_PAD_BINDINGS.items()}
                         if bindings is None else
                         {k: list(v) for k, v in bindings.items()})
        #: Where this was loaded from, so ``save()`` goes back to it.
        self.path = path
        self.was_reset = False

    # ------------------------------------------------------------------
    @staticmethod
    def _key(action) -> str:
        return action.value if isinstance(action, Action) else str(action)

    def actions_for(self, button: str) -> list[str]:
        name = str(button).lower()
        return [a for a, b in self.bindings.items()
                if name in (x.lower() for x in b)]

    def buttons_for(self, action) -> list[str]:
        return list(self.bindings.get(self._key(action), ()))

    def bind(self, action, buttons) -> None:
        self.bindings[self._key(action)] = [str(b).lower() for b in buttons]

    def describe(self, action) -> str:
        buttons = self.buttons_for(action)
        return (' or '.join(button_label(b) for b in buttons)
                if buttons else 'unbound')

    # ------------------------------------------------------------------
    @classmethod
    def default_path(cls) -> str:
        d = os.path.join(paths.writable_root(), 'config')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, 'controller.json')

    @classmethod
    def load(cls, path: str | None = None, write_default: bool = True) -> 'PadMap':
        path = path or cls.default_path()
        pm = cls(path=path)
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    stored = json.load(fh)
            except (OSError, ValueError):
                return pm       # a corrupt file must never stop the game
            if not isinstance(stored, dict):
                return pm
            if int(stored.get(VERSION_KEY, 0) or 0) != PAD_BINDINGS_VERSION:
                pm.was_reset = True
                try:
                    pm.save(path)
                except OSError:
                    pass
                return pm
            for action, buttons in stored.items():
                if action != VERSION_KEY and isinstance(buttons, list):
                    pm.bindings[action] = [str(b).lower() for b in buttons]
        elif write_default:
            try:
                pm.save(path)
            except OSError:
                pass
        return pm

    def save(self, path: str | None = None) -> str:
        path = path or self.path or self.default_path()
        out = dict(self.bindings)
        out[VERSION_KEY] = PAD_BINDINGS_VERSION
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
        return path

    def reset(self) -> None:
        self.bindings = {k: list(v) for k, v in DEFAULT_PAD_BINDINGS.items()}

    def __repr__(self) -> str:
        bound = sum(1 for b in self.bindings.values() if b)
        return f'<PadMap {bound} actions bound>'
