"""Zip up a release of the Windows port.

Takes ``Run/`` and makes the one archive that gets handed to someone else:
**the game executable, and nothing else**.

Nothing else means nothing else.  No readme, no config, no recordings, no save
file - and **none of the diagnostic tools**.  `Listen to spatial audio`,
`Verify spatial audio`, `Check game content` and `Walk in the dark` are how
this port was built and checked; they are not part of the game, and a player
opening the zip should find one thing to double-click.  Same reasoning as the
``Start at level N.cmd`` launchers, which are also not shipped: the game has
"Choose level" in its menu.  They all stay in ``Run/`` for testing here.

    python tools/pack_release.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(ROOT, 'Run')
DIST = os.path.join(ROOT, 'dist')

GAME = 'Play Papa Sangre.exe'

#: The release, in full.
ALWAYS = (GAME,)

#: Never shipped: recordings, generated reports, and anybody's save file.
NEVER_SUFFIX = ('.wav', '.log')
NEVER_NAMES = ('progress.json',)

#: **Nothing from config/ is shipped.**  Every file in there is written on
#: first run - ``keys.json`` by ``KeyMap.load``, ``controller.json`` by
#: ``PadMap.load``, ``settings.json`` by ``Settings``, ``audio.json`` by
#: ``configured_outdoor_profile``, and ``alsoft.ini`` by the audio engine on
#: *every* start.
#:
#: Shipping them is not just redundant, it is harmful: ``alsoft.ini`` holds an
#: absolute ``hrtf-paths`` pointing at the machine that built it, so on anyone
#: else's computer that path does not exist and the recovered HRTF - the whole
#: point of this port - silently fails to load.  It also exposes a local path,
#: and lets HRTF be switched off in a game that is unplayable without it.


def wanted() -> list[tuple[str, str]]:
    """Return ``(absolute path, name inside the zip)`` pairs."""
    out: list[tuple[str, str]] = []
    for name in ALWAYS:
        path = os.path.join(RUN, name)
        if not os.path.exists(path):
            raise SystemExit(f'missing: {path}  (run tools/build_exes.py first)')
        out.append((path, name))
    return out


def check_for_local_paths(files: list[tuple[str, str]]) -> list[str]:
    """Refuse to ship a text file with this machine's paths baked into it.

    The specific thing this exists to catch is ``alsoft.ini``, whose absolute
    ``hrtf-paths`` would send every other machine looking for a directory that
    is not there.  Cheap to run over anything shipped as text.
    """
    home = os.path.expanduser('~')
    needles = [home, ROOT]
    bad = []
    for path, name in files:
        if os.path.splitext(name)[1].lower() not in (
                '.txt', '.ini', '.json', '.cfg', '.md'):
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                body = fh.read()
        except OSError:
            continue
        for needle in needles:
            if needle and needle.lower() in body.lower():
                bad.append(f'{name} contains {needle}')
    return bad


def version() -> str:
    path = os.path.join(ROOT, 'VERSION')
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read().strip() or '0.0.0'
    except OSError:
        return '0.0.0'


def main(argv: list[str]) -> int:
    files = wanted()

    leaks = check_for_local_paths(files)
    if leaks:
        print('REFUSING to pack - this machine\'s paths are in:')
        for line in leaks:
            print(f'  {line}')
        return 1

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f'PapaSangre-Windows-{version()}.zip')

    total = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for path, name in files:
            zf.write(path, name)
            total += os.path.getsize(path)
            print(f'  + {name}  ({os.path.getsize(path) / 1e6:.1f} MB)'
                  if os.path.getsize(path) > 1e6 else f'  + {name}')

    packed = os.path.getsize(out)
    digest = hashlib.sha256(open(out, 'rb').read()).hexdigest()
    print(f'\n{out}')
    print(f'  {len(files)} files, {total / 1e6:.0f} MB in, '
          f'{packed / 1e6:.0f} MB packed')
    print(f'  sha256 {digest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
