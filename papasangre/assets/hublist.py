"""``<AppName>_hubList.plist`` - the level menu, as the original shipped it.

``-[AccessibleAllLevelsViewController viewDidLoad]`` loads
``[NSString stringWithFormat:@"%@_hubList", appName]`` from the bundle and
builds its table from it, one row per entry, ordered by ``positionInMenu``.
Each row is spoken with one of the two formats in that class:

* ``"Play Level %i: %@"`` when the level is unlocked
* ``"Level %i: %@; locked"`` when it is not

and the name used is ``altName`` - the short one, "The Kennel" rather than
"Papa Sangre lvl 3: The Kennel", which is what ``title`` holds.

The plist's own ``unlocked`` flag is only the **starting** state: level 1 is
true and every other level is false.  What is actually unlocked at runtime
comes from ``PGEGameProgress``, which is why this module takes a progress
object rather than trusting the file.
"""

from __future__ import annotations

import os
import plistlib

#: ps1_1b is chained out of ps1_1 by the level data itself and is deliberately
#: not a menu entry - the original's hub list does not mention it either.
HIDDEN = ('ps1_1b',)


class LevelEntry:
    """One row of the level menu."""

    __slots__ = ('file_name', 'alt_name', 'title', 'position', 'unlocked_by_default')

    def __init__(self, file_name: str, alt_name: str, title: str,
                 position: int, unlocked_by_default: bool) -> None:
        self.file_name = file_name
        self.alt_name = alt_name
        self.title = title
        self.position = position
        self.unlocked_by_default = unlocked_by_default

    def is_unlocked(self, progress=None) -> bool:
        """Level 1 always; anything else only once progress says so."""
        if self.unlocked_by_default:
            return True
        if progress is None:
            return False
        return bool(progress.is_level_unlocked(self.file_name))

    def spoken(self, progress=None) -> str:
        """Exactly the two formats in AccessibleAllLevelsViewController."""
        if self.is_unlocked(progress):
            return f'Play Level {self.position}: {self.alt_name}'
        return f'Level {self.position}: {self.alt_name}; locked'

    def __repr__(self) -> str:
        return f'<LevelEntry {self.position} {self.file_name} {self.alt_name!r}>'


def load_hub_list(bundle_dir: str, app_name: str = 'Papa Sangre') -> list[LevelEntry]:
    """Read ``Exports/<app_name>_hubList.plist`` into menu order."""
    path = os.path.join(bundle_dir, 'Exports', f'{app_name}_hubList.plist')
    try:
        with open(path, 'rb') as fh:
            raw = plistlib.load(fh)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return []
    entries = []
    for value in (raw or {}).values():
        if not isinstance(value, dict):
            continue
        file_name = str(value.get('fileName', '')).strip()
        if not file_name or file_name in HIDDEN:
            continue
        try:
            position = int(value.get('positionInMenu', 0))
        except (TypeError, ValueError):
            position = 0
        entries.append(LevelEntry(
            file_name=file_name,
            alt_name=str(value.get('altName', file_name)),
            title=str(value.get('title', '')),
            position=position,
            unlocked_by_default=bool(value.get('unlocked', False)),
        ))
    entries.sort(key=lambda e: (e.position, e.file_name))
    return entries
