"""Zip up a release for the platform doing the packing.

Takes ``Run/`` and makes the one archive that gets handed to someone else:
**the game, and nothing else** - ``Play Papa Sangre.exe`` on a Windows
machine, ``Papa Sangre.app`` on a Mac.  Diagnostic tools, launchers,
config, recordings and save files all stay behind, for the same reasons the
Windows build always refused them.

    python tools/pack_release.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.util import host                            # noqa: E402

RUN = os.path.join(ROOT, 'Run')
DIST = os.path.join(ROOT, 'dist')

GAME = ('Papa Sangre.app' if host.MAC else 'Play Papa Sangre.exe')

#: The release, in full.
ALWAYS = (GAME,)

#: Never shipped: recordings, generated reports, and anybody's save file.
NEVER_SUFFIX = ('.wav', '.log')
NEVER_NAMES = ('progress.json',)


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
    plat = 'macOS' if host.MAC else 'Windows' if host.WINDOWS else host.PLATFORM
    out = os.path.join(DIST, f'PapaSangre-{plat}-{version()}.zip')

    def _tree(root: str):
        """Every file under root, as (absolute, arcname) pairs."""
        for dp, _d, fs in os.walk(root):
            for f in sorted(fs):
                full = os.path.join(dp, f)
                yield full, os.path.relpath(full, RUN)

    total = 0
    count = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for path, name in files:
            members = _tree(path) if os.path.isdir(path) else [(path, name)]
            for full, arcname in members:
                if os.path.splitext(arcname)[1].lower() in NEVER_SUFFIX:
                    continue
                if os.path.basename(arcname) in NEVER_NAMES:
                    continue
                zf.write(full, arcname)
                total += os.path.getsize(full)
                count += 1

    packed = os.path.getsize(out)
    digest = hashlib.sha256(open(out, 'rb').read()).hexdigest()
    print(f'\n{out}')
    print(f'  {count} files, {total / 1e6:.0f} MB in, '
          f'{packed / 1e6:.0f} MB packed')
    print(f'  sha256 {digest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
