"""Parser for the original engine's ``.sexp`` S3DPlayListModel files.

The iOS build stores one playlist per level under
``meta/S3DPlayListModel/<name>.S3DPlayListModel#0.sexp``.  A playlist declares
every sound a level may play, where its audio file lives inside the bundle, and
whether the sound is spatialised.  Nested ``(playlist (name "..."))`` forms pull
in a shared sub-playlist (the per-surface footstep banks).

Grammar (as emitted by the original tooling)::

    (playlist
      (name "ps1_1")
      (repeat none)
      (sound
        (spatialized false)
        (preload true)
        (unloadonstop true)
        (bundle
          (path "ps1/cutscenes")
          (name "FINAL_ITD_Intro")
          (extension "m4a")))
      (playlist
        (name "_footsteps_stone.S3DPlayListModel#0")))

Atoms are bare words or double-quoted strings; there are no escapes in the
shipped data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator

_TOKEN = re.compile(r'\(|\)|"[^"]*"|;[^\n]*|[^\s()";]+')


def tokenize(text: str) -> Iterator[str]:
    for m in _TOKEN.finditer(text):
        tok = m.group()
        if tok.startswith(';'):
            continue
        yield tok


def parse(text: str) -> list:
    """Parse a whole file into nested Python lists; strings keep their value."""
    stack: list[list] = [[]]
    for tok in tokenize(text):
        if tok == '(':
            new: list = []
            stack[-1].append(new)
            stack.append(new)
        elif tok == ')':
            if len(stack) == 1:
                raise ValueError('unbalanced ) in sexp')
            stack.pop()
        elif tok.startswith('"'):
            stack[-1].append(tok[1:-1])
        else:
            stack[-1].append(tok)
    if len(stack) != 1:
        raise ValueError('unbalanced ( in sexp')
    return stack[0]


def _bool(v: str) -> bool:
    return str(v).lower() in ('true', 'yes', '1')


def _fields(node: list) -> dict:
    """Turn ``[(a "1") (b "2")]`` style children into ``{'a': '1', 'b': '2'}``.

    Only single-value children are collected; nested forms are left to callers.
    """
    out: dict[str, Any] = {}
    for child in node:
        if isinstance(child, list) and child and isinstance(child[0], str):
            if len(child) == 2 and not isinstance(child[1], list):
                out[child[0]] = child[1]
    return out


@dataclass
class SoundDecl:
    """One ``(sound ...)`` entry: a named sound and the file that backs it."""
    name: str
    path: str                    # bundle-relative directory, e.g. "ps1/atmos"
    extension: str = 'm4a'
    spatialized: bool = False
    preload: bool = False
    unload_on_stop: bool = False
    gain: float | None = None
    source_playlist: str = ''    # which playlist file declared it

    @property
    def bundle_path(self) -> str:
        return f'{self.path}/{self.name}.{self.extension}'

    @property
    def key(self) -> str:
        return self.name


@dataclass
class PlayList:
    name: str
    repeat: str = 'none'
    sounds: list[SoundDecl] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)   # nested playlist names

    def by_name(self) -> dict[str, SoundDecl]:
        return {s.name: s for s in self.sounds}


def parse_playlist(text: str, source: str = '') -> PlayList:
    forms = parse(text)
    top = None
    for f in forms:
        if isinstance(f, list) and f and f[0] == 'playlist':
            top = f
            break
    if top is None:
        raise ValueError(f'no (playlist ...) form in {source!r}')

    pl = PlayList(name='')
    for child in top[1:]:
        if not isinstance(child, list) or not child:
            continue
        head = child[0]
        if head == 'name' and len(child) > 1 and not isinstance(child[1], list):
            pl.name = child[1]
        elif head == 'repeat' and len(child) > 1:
            pl.repeat = child[1]
        elif head == 'sound':
            # One (sound ...) form may declare SEVERAL (bundle ...) entries.
            # That is how the footstep banks are written: a single sound form
            # lists every left/right/variant file, and they share the form's
            # flags.  Each bundle becomes its own addressable sound.
            f = _fields(child[1:])
            for bundle in child[1:]:
                if not (isinstance(bundle, list) and bundle and bundle[0] == 'bundle'):
                    continue
                bf = _fields(bundle[1:])
                pl.sounds.append(SoundDecl(
                    name=bf.get('name', ''),
                    path=bf.get('path', ''),
                    extension=bf.get('extension', 'm4a'),
                    spatialized=_bool(f.get('spatialized', 'false')),
                    preload=_bool(f.get('preload', 'false')),
                    unload_on_stop=_bool(f.get('unloadonstop', 'false')),
                    gain=float(f['gain']) if 'gain' in f else None,
                    source_playlist=source,
                ))
        elif head == 'playlist':
            nf = _fields(child[1:])
            if 'name' in nf:
                pl.includes.append(nf['name'])
    return pl


# The nested include names carry the original model suffix; strip it to get the
# file stem used on disk.
_SUFFIX = '.S3DPlayListModel#0'


def include_stem(include_name: str) -> str:
    return include_name[:-len(_SUFFIX)] if include_name.endswith(_SUFFIX) else include_name
