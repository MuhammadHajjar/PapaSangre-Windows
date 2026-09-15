"""``PGEGameProgress`` - what the game remembers between runs.

A singleton over ``NSUserDefaults`` in the original.  There is no
``NSUserDefaults`` here, so the port writes a JSON file next to the executable,
but it keeps the original's **key names**, including their oddities, so the
saved state is a faithful record of what the engine tracks:

===========================  ==================================================
``<level>_completed``        bool - the level has been finished
``<level>_locked``           bool - **true means unlocked.**  The key reads
                             backwards; ``isLevelUnlocked:`` returns the value
                             as-is, so the name is simply wrong in the original
``lastLevelUnlocked``        string - written **only the first time** a level is
                             unlocked, so it records how far you have got rather
                             than the last level you happened to unlock again
``lastPLaylist``             string - the playlist in use.  The capital L is the
                             original's typo and is kept: change it and a save
                             written by the original would not be read back
``<sound name>``             bool - this narration has been heard once and may
                             now be skipped
``<dilemma id>``             bool - the choice made at that dilemma
===========================  ==================================================

``lastUnlockedLevel`` falls back to the first level of whichever game is
running: ``ps1_1`` for Papa Sangre, ``nightJar_1`` for The Nightjar.
"""

from __future__ import annotations

import json
import os
import shutil

from ..util import paths

#: -[PGEGameProgress lastUnlockedLevel] switches on PGEGameParameters.appName.
FIRST_LEVEL = {'Papa Sangre': 'ps1_1', 'The Nightjar': 'nightJar_1'}
DEFAULT_APP = 'Papa Sangre'

LAST_UNLOCKED_KEY = 'lastLevelUnlocked'
LAST_PLAYLIST_KEY = 'lastPLaylist'          # the typo is the original's


class GameProgress:
    """Persistent progression, mirroring the original's defaults keys."""

    def __init__(self, path: str | None = None,
                 app_name: str = DEFAULT_APP) -> None:
        self.path = path or os.path.join(paths.config_dir(), 'progress.json')
        self.app_name = app_name
        self.values: dict[str, object] = {}
        self.load()

    # ------------------------------------------------------------ storage
    def load(self) -> 'GameProgress':
        """Read the save, falling back to the last known-good copy.

        An unreadable save used to mean an empty one, which is a whole
        playthrough gone for a file that may only be half written.  The backup
        is tried first instead, and only when neither can be read does the
        progress start over.
        """
        for candidate in (self.path, self.path + '.bak'):
            try:
                with open(candidate, encoding='utf-8') as fh:
                    stored = json.load(fh)
            except (OSError, ValueError):
                continue          # a corrupt save must never stop the game
            if isinstance(stored, dict):
                self.values = stored
                return self
        self.values = {}
        return self

    def synchronize(self) -> None:
        """``[NSUserDefaults synchronize]`` - write it out now.

        Written beside the save and moved into place, because opening the real
        file for writing truncates it first: anything that stopped the process
        in that window - and until 1.0.1 finishing the game stopped it right
        after a write - left a half-written save behind.  The previous file is
        kept as ``.bak`` so there is always one good copy on disk.
        """
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(self.values, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            if os.path.exists(self.path):
                shutil.copyfile(self.path, self.path + '.bak')
            os.replace(tmp, self.path)
        except OSError:
            pass                  # a read-only install must still be playable

    def _set(self, key: str, value) -> None:
        self.values[key] = value
        self.synchronize()

    def _bool(self, key: str) -> bool:
        return bool(self.values.get(key, False))

    # --------------------------------------------------------- completion
    def player_did_complete_level(self, name: str) -> None:
        self._set(f'{name}_completed', True)

    def is_level_completed(self, name: str) -> bool:
        return self._bool(f'{name}_completed')

    # ------------------------------------------------------------ unlocks
    def player_did_unlock_level(self, name: str) -> None:
        """``-[PGEGameProgress playerDidUnlockLevel:]``

        ``lastLevelUnlocked`` is written only when the level was not already
        unlocked, so replaying an early level does not wind your progress back.
        """
        if not self._bool(f'{name}_locked'):
            self.values[LAST_UNLOCKED_KEY] = name
        self._set(f'{name}_locked', True)

    def is_level_unlocked(self, name: str) -> bool:
        return self._bool(f'{name}_locked')

    @property
    def last_unlocked_level(self) -> str:
        stored = self.values.get(LAST_UNLOCKED_KEY)
        if isinstance(stored, str) and stored:
            return stored
        return FIRST_LEVEL.get(self.app_name, FIRST_LEVEL[DEFAULT_APP])

    # ---------------------------------------------------------- playlists
    def save_last_playlist(self, name: str) -> None:
        self._set(LAST_PLAYLIST_KEY, name)

    def get_last_playlist(self) -> str:
        stored = self.values.get(LAST_PLAYLIST_KEY)
        return stored if isinstance(stored, str) else ''

    # ------------------------------------------------- skippable narration
    def save_skippable_sound(self, key: str) -> None:
        """Heard once, so the player may skip it from now on."""
        if key:
            self._set(key, True)

    def can_skip_sound(self, key: str) -> bool:
        return self._bool(key)

    # ----------------------------------------------------------- dilemmas
    def save_dilemma_status(self, value: bool, dilemma_id: str) -> None:
        self._set(str(dilemma_id), bool(value))

    def get_dilemma_status(self, dilemma_id: str) -> bool:
        return self._bool(str(dilemma_id))

    def __repr__(self) -> str:
        return f'<GameProgress {len(self.values)} keys at {self.path!r}>'
