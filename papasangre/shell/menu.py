"""The menus, spoken.

Structure follows the original's own main menu, which is readable from the
strings in ``-[PGEViewController ...]``: *Continue button pressed*, *Level
selection pressed*, *Accessibility level selection pressed*, *Credits button
pressed*, *Cast button pressed*.  What is kept is what still means something
off an iPhone:

============  ====================================================
Continue      resume at the furthest level unlocked, which is what
              ``PGEGameProgress.lastUnlockedLevel`` is for
Choose level  the accessible level list, read out of the original's
              own ``Papa Sangre_hubList.plist`` and spoken with the
              two formats from ``AccessibleAllLevelsViewController``
Credits       *Developped by Somethin' Else, published by
              Playground* - the string is in the binary, typo and all
Quit          -
============  ====================================================

*Cast* and *More Games* are App Store links and have no meaning here.

**Options is not in the original.**  The only sensitivity control in the whole
binary belongs to ``PGEStepsWithHeightViewController``, an alternative control
scheme Papa Sangre 1 never switches on, and volume was the iOS hardware volume.
It is here because it was asked for, and is recorded in DIVERGENCES.md.

Nothing is drawn.  A menu is a list you move through with up and down, choose
with Enter or A, and leave with Escape or B; the current item is spoken every
time it changes, which is the whole interface.
"""

from __future__ import annotations

from ..assets.hublist import load_hub_list
from ..util.settings import MAX_TURN_RATE, MIN_TURN_RATE

#: -[PGEViewController launchCredits] logs this exact line, typo included.
CREDITS = "Developped by Somethin' Else, published by Playground."


class MenuItem:
    """One row: what to say, and what choosing it does."""

    __slots__ = ('label', 'action', 'value', 'enabled', 'adjust')

    def __init__(self, label: str, action: str, value=None,
                 enabled: bool = True, adjust=None) -> None:
        self.label = label
        self.action = action
        self.value = value
        self.enabled = enabled
        self.adjust = adjust          # callable(delta) -> new spoken label


class Menu:
    """A spoken list.  ``choose`` returns ``(action, value)`` or None."""

    def __init__(self, title: str, items: list[MenuItem]) -> None:
        self.title = title
        self.items = items
        self.index = 0

    # ------------------------------------------------------------------
    @property
    def current(self) -> MenuItem | None:
        if not self.items:
            return None
        return self.items[self.index % len(self.items)]

    def move(self, delta: int) -> str:
        if not self.items:
            return ''
        self.index = (self.index + delta) % len(self.items)
        return self.speak_current()

    def speak_current(self) -> str:
        item = self.current
        if item is None:
            return f'{self.title}. Empty.'
        return item.label

    def announce(self) -> str:
        """Said on entering the menu: its name, then where you are in it."""
        return f'{self.title}. {self.speak_current()}'

    def choose(self):
        item = self.current
        if item is None:
            return None
        if not item.enabled:
            return ('blocked', item)
        return (item.action, item.value)

    def adjust_current(self, delta: float) -> str | None:
        """Left/right on a slider row.  None when the row is not one."""
        item = self.current
        if item is None or item.adjust is None:
            return None
        item.label = item.adjust(delta)
        return item.label


# ---------------------------------------------------------------- builders
def main_menu(progress=None, has_progress: bool = False) -> Menu:
    resume = 'Continue'
    if progress is not None:
        last = progress.last_unlocked_level
        resume = f'Continue, {last}' if has_progress else 'Start the game'
    return Menu('Main menu', [
        MenuItem(resume, 'continue'),
        MenuItem('Choose level', 'levels'),
        MenuItem('Options', 'options'),
        MenuItem('Credits', 'credits'),
        MenuItem('Quit', 'quit'),
    ])


def level_menu(bundle_dir: str, progress=None, titles=None) -> Menu:
    """The accessible level list, in the original's own words."""
    items = []
    for entry in load_hub_list(bundle_dir):
        items.append(MenuItem(
            entry.spoken(progress), 'play', entry.file_name,
            enabled=entry.is_unlocked(progress)))
    if not items:                      # no plist: fall back to what we can play
        for name in sorted(titles or ()):
            items.append(MenuItem(name, 'play', name))
    items.append(MenuItem('Back', 'back'))
    return Menu('Choose level', items)


def options_menu(settings, engine=None) -> Menu:
    """Volume and turn speed.  Left and right change the row you are on.

    Volume is the audio engine's own - it already persists it and applies it on
    start - so this drives that rather than keeping a second copy of it.
    """

    def volume_label() -> str:
        if engine is None:
            return 'Sound volume, unavailable'
        return f'Sound volume, {engine.master_volume_db:+.0f} decibels'

    def turn_label() -> str:
        return f'Turning speed, {settings.turn_rate:.0f} degrees per second'

    def adjust_volume(delta: float) -> str:
        if engine is None:
            return volume_label()
        before = engine.master_volume_db
        engine.adjust_master_volume(2.0 * delta)
        if abs(engine.master_volume_db - before) < 0.01:
            return volume_label() + (', maximum' if delta > 0 else ', minimum')
        return volume_label()

    def adjust_turn(delta: float) -> str:
        settings.adjust('turnRateDegreesPerSecond', 15.0 * delta)
        if settings.turn_rate <= MIN_TURN_RATE:
            return turn_label() + ', slowest'
        if settings.turn_rate >= MAX_TURN_RATE:
            return turn_label() + ', fastest'
        return turn_label()

    return Menu('Options', [
        MenuItem(volume_label(), 'adjust', adjust=adjust_volume),
        MenuItem(turn_label(), 'adjust', adjust=adjust_turn),
        MenuItem('Keys', 'keys'),
        MenuItem('Controller buttons', 'buttons'),
        MenuItem('Back', 'back'),
    ])


#: What the key menu offers, in the order it reads them out.  Papa Sangre 1
#: never enables hands, clapping, jumping or swimming, so those are left out -
#: binding a key to something the game will not do is just a trap.
REBINDABLE = (
    ('foot_left', 'Left foot'),
    ('foot_right', 'Right foot'),
    ('turn_left', 'Turn left'),
    ('turn_right', 'Turn right'),
    ('skip', 'Skip narration'),
    ('pause', 'Pause menu'),
    ('confirm', 'Select'),
    ('cancel', 'Back'),
    ('menu_up', 'Menu up'),
    ('menu_down', 'Menu down'),
    ('menu_left', 'Menu left'),
    ('menu_right', 'Menu right'),
    ('volume_up', 'Volume up'),
    ('volume_down', 'Volume down'),
)


def keys_menu(keymap) -> Menu:
    """Every key, and what it does.  Choosing a row rebinds it."""
    items = []
    for action, label in REBINDABLE:
        keys = keymap.keys_for(action)
        said = ' or '.join(keys) if keys else 'unbound'
        items.append(MenuItem(f'{label}: {said}', 'rebind', action))
    items.append(MenuItem('Restore all keys to their defaults', 'reset_keys'))
    items.append(MenuItem('Back', 'back'))
    return Menu('Keys', items)


#: The pad's rebindable list.  Turning is missing on purpose: it is the right
#: stick, an axis, and there is no second axis to move it to.
PAD_REBINDABLE = (
    ('foot_left', 'Left foot'),
    ('foot_right', 'Right foot'),
    ('skip', 'Skip narration'),
    ('pause', 'Pause menu'),
    ('confirm', 'Select'),
    ('cancel', 'Back'),
    ('menu_up', 'Menu up'),
    ('menu_down', 'Menu down'),
    ('menu_left', 'Menu left'),
    ('menu_right', 'Menu right'),
    ('volume_up', 'Volume up'),
    ('volume_down', 'Volume down'),
)


def pad_menu(padmap) -> Menu:
    """Every controller button, and what it does.  Choosing a row rebinds it.

    The same actions as the keyboard's list, because they *are* the same
    actions - a pad button and a key that do the same thing are one action
    everywhere past the input layer.
    """
    items = []
    for action, label in PAD_REBINDABLE:
        items.append(MenuItem(f'{label}: {padmap.describe(action)}',
                              'rebind_button', action))
    items.append(MenuItem('Restore all buttons to their defaults',
                          'reset_buttons'))
    items.append(MenuItem('Back', 'back'))
    return Menu('Controller buttons', items)


def level_complete_menu(next_level: str | None, level_title: str = '') -> Menu:
    """Shown when a level is finished, instead of diving straight into the next.

    The original chained levels automatically once the win narration ended -
    ``LoadLevelWithName`` fires from the door's ``OnSoundEnd``.  Stopping to ask
    is a **REQUESTED addition**: it is a long game and being dropped into the
    next level with no pause is hard to sit with.  The level's own ambience
    keeps playing underneath, which is what makes it feel like part of the game
    rather than a dialog box.
    """
    items = []
    if next_level:
        items.append(MenuItem('Continue to the next level', 'next', next_level))
    items.append(MenuItem('Play this level again', 'replay'))
    items.append(MenuItem('Choose level', 'levels'))
    items.append(MenuItem('Options', 'options'))
    items.append(MenuItem('Main menu', 'main'))
    items.append(MenuItem('Quit', 'quit'))
    title = f'{level_title} complete' if level_title else 'Level complete'
    return Menu(title, items)


def level_failed_menu(level_title: str = '') -> Menu:
    """The same, for a level you died in."""
    return Menu(f'{level_title} failed' if level_title else 'Level failed', [
        MenuItem('Try again', 'replay'),
        MenuItem('Choose level', 'levels'),
        MenuItem('Options', 'options'),
        MenuItem('Main menu', 'main'),
        MenuItem('Quit', 'quit'),
    ])


def pause_menu() -> Menu:
    return Menu('Paused', [
        MenuItem('Resume', 'resume'),
        MenuItem('Options', 'options'),
        MenuItem('Restart this level', 'restart'),
        MenuItem('Main menu', 'main'),
        MenuItem('Quit', 'quit'),
    ])
