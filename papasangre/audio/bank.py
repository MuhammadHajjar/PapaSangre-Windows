"""A level's sound bank - the port's ``S3DPlayList``.

Loads every sound a level's ``.sexp`` playlist declares (including the shared
footstep banks it includes) and hands out :class:`~papasangre.audio.engine.Sound`
instances.

Two lookups mirror the original's, spelling and all:

``any_sound_with_prefix``
    ``anySoundWihPrefix:`` - a **random** choice among sounds whose name starts
    with the prefix.  This is how the ``_a`` / ``_b`` / ``_c`` footstep variants
    are used, and it is why every step sounds slightly different.

``any_sound_containing``
    ``anySoundContaining:`` - a random choice among sounds whose name *contains*
    the string.  Used for trip sounds.
"""

from __future__ import annotations

import glob
import os
import random

from ..assets.sexp import PlayList, include_stem, parse_playlist
from .engine import AudioEngine, Sound, SoundSpec


class SoundBank:
    """Every sound one level can play."""

    def __init__(self, engine: AudioEngine, bundle_dir: str,
                 meta_dir: str | None = None,
                 rng: random.Random | None = None) -> None:
        self.engine = engine
        self.bundle_dir = bundle_dir
        self.meta_dir = meta_dir or os.path.join(bundle_dir, 'meta',
                                                 'S3DPlayListModel')
        self.rng = rng or random.Random()
        self.specs: dict[str, SoundSpec] = {}
        self._cache: dict[str, Sound] = {}
        self._playlists: dict[str, PlayList] = {}
        self.name = ''

    # ------------------------------------------------------------------
    def _playlist(self, stem: str) -> PlayList | None:
        if stem in self._playlists:
            return self._playlists[stem]
        matches = glob.glob(os.path.join(self.meta_dir, f'{stem}.S3DPlayListModel*.sexp'))
        if not matches:
            self._playlists[stem] = None
            return None
        pl = parse_playlist(open(matches[0], encoding='utf-8', errors='replace').read(),
                            os.path.basename(matches[0]))
        self._playlists[stem] = pl
        return pl

    def load_playlist(self, stem: str, _seen: set[str] | None = None) -> int:
        """Load a playlist and everything it includes.  Returns sounds added."""
        seen = _seen if _seen is not None else set()
        if stem in seen:
            return 0
        seen.add(stem)
        pl = self._playlist(stem)
        if pl is None:
            return 0
        if not self.name:
            self.name = pl.name or stem
        added = 0
        for decl in pl.sounds:
            if not decl.name:
                continue          # four empty declarations exist in the original
            path = os.path.join(self.bundle_dir, decl.bundle_path)
            if not os.path.exists(path):
                continue
            self.specs[decl.name] = SoundSpec(
                name=decl.name, path=path, spatialized=decl.spatialized,
                preload=decl.preload, unload_on_stop=decl.unload_on_stop,
                gain=decl.gain)
            added += 1
        for inc in pl.includes:
            added += self.load_playlist(include_stem(inc), seen)
        return added

    def preload(self) -> int:
        """Decode everything the playlist flags ``preload``."""
        n = 0
        for name, spec in self.specs.items():
            if spec.preload:
                self.sound(name)
                n += 1
        return n

    def preload_all(self) -> int:
        for name in list(self.specs):
            self.sound(name)
        return len(self.specs)

    # ------------------------------------------------------------------
    def sound(self, name: str) -> Sound | None:
        """One shared instance per name, decoded on first use."""
        if not name:
            return None
        s = self._cache.get(name)
        if s is not None:
            return s
        spec = self.specs.get(name)
        if spec is None:
            return None
        s = self.engine.load(spec)
        self._cache[name] = s
        return s

    def ensure(self, name: str, rel_path: str, spatialized: bool = True) -> bool:
        """Make one sound available even though this level never declared it.

        Used for the telephone door: only ps1_7's playlist lists it, and the
        other three dilemma levels have to be able to play it too.  Returns
        False if the file is not there, so a caller can leave well alone.
        """
        if name in self.specs:
            return True
        path = os.path.join(self.bundle_dir, *rel_path.split('/'))
        if not os.path.exists(path):
            return False
        self.specs[name] = SoundSpec(name=name, path=path,
                                     spatialized=spatialized)
        return True

    def has(self, name: str) -> bool:
        """Is this name declared?  Without decoding it to find out."""
        return bool(name) and name in self.specs

    def new_sound(self, name: str) -> Sound | None:
        """A fresh instance, for sounds that must overlap with themselves."""
        spec = self.specs.get(name)
        return self.engine.load(spec) if spec else None

    def names_with_prefix(self, prefix: str) -> list[str]:
        return sorted(n for n in self.specs if n.startswith(prefix))

    def any_sound_with_prefix(self, prefix: str) -> Sound | None:
        """``anySoundWihPrefix:`` - random among matching names."""
        names = self.names_with_prefix(prefix)
        return self.sound(self.rng.choice(names)) if names else None

    def any_sound_containing(self, needle: str) -> Sound | None:
        """``anySoundContaining:`` - random among names containing the string."""
        names = sorted(n for n in self.specs if needle in n)
        return self.sound(self.rng.choice(names)) if names else None

    def from_sound_list(self, sound_list: str) -> Sound | None:
        """Pick one name out of an ``&``-separated soundList property."""
        names = [n for n in (sound_list or '').split('&') if n]
        if not names:
            return None
        return self.sound(self.rng.choice(names))

    def live_sounds(self):
        """Every decoded sound, for the per-frame listener re-projection."""
        return list(self._cache.values())

    def stop_all(self) -> None:
        for s in self._cache.values():
            s.stop()

    def __contains__(self, name: str) -> bool:
        return name in self.specs

    def __len__(self) -> int:
        return len(self.specs)

    def __repr__(self) -> str:
        return f'<SoundBank {self.name!r} {len(self.specs)} sounds>'
