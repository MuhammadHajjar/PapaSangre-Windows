"""Build the standalone Windows executables.

Everything the project hands over should be double-clickable — no terminal, no
Python, no paths to type.  This freezes each app in ``apps/`` into a single
self-contained ``.exe`` in ``Run/``, carrying its own OpenAL Soft, the recovered
HRTF, the NVDA controller client and whatever game audio it needs.

Run:  python tools/build_exes.py            (all apps)
      python tools/build_exes.py listen     (one app, by key)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.join(ROOT, 'apps')
RUN = os.path.join(ROOT, 'Run')
WORK = os.path.join(ROOT, 'build', 'pyinstaller')
BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
HRTF = os.path.join(ROOT, 'build', 'hrtf', 'papa_ircam_1050.mhr')
OPENAL = os.path.join(ROOT, 'vendor', 'openal', 'soft_oal.dll')
NVDA_DIR = os.path.join(ROOT, 'vendor', 'nvda')

SEP = ';'          # PyInstaller's src;dest separator on Windows


def staged_entries(staging: str) -> list[tuple[str, str]]:
    """Turn a staging directory into a handful of ``--add-data`` entries.

    One entry per file blows past Windows' command-line length limit once a
    build carries the whole audio tree, so whole directories are passed instead
    and PyInstaller copies their contents.
    """
    data: list[tuple[str, str]] = []
    for name in sorted(os.listdir(staging)):
        full = os.path.join(staging, name)
        data.append((full, f'gamedata/{name}' if os.path.isdir(full)
                     else 'gamedata'))
    return data


def game_audio(*rel: str) -> tuple[str, str]:
    """(source, dest-inside-exe) for one file from the original bundle."""
    src = os.path.join(BUNDLE, *rel)
    dest = 'gamedata/' + '/'.join(rel[:-1])
    return src, dest


#: key -> (script, exe name, extra data files as (src, dest) pairs)
TARGETS: dict[str, tuple[str, str, list[tuple[str, str]]]] = {
    'listen': (
        'listen_spatial.py',
        'Listen to spatial audio',
        [game_audio('ps1', 'spatialized', 'door_castle_living.m4a'),
         game_audio('ps1', 'monsters', 'monster_hog1_01_dry_chase.m4a')],
    ),
    'verify': (
        'verify_spatial.py',
        'Verify spatial audio',
        [],
    ),
    'content': (
        'check_content.py',
        'Check game content',
        [],          # filled in by prepare_content_data()
    ),
    'walk': (
        'walk_in_the_dark.py',
        'Walk in the dark',
        [],          # filled in by prepare_level_data()
    ),
    'play': (
        'play.py',
        'Play Papa Sangre',
        [],          # filled in by prepare_level_data() with every level
    ),
}

#: Levels carried by the full "Play Papa Sangre" build, in play order.
ALL_LEVELS = (['ps1_1', 'ps1_1b'] + [f'ps1_{i}' for i in range(2, 26)]
              + ['reckoner'])


def prepare_level_data(levels=('ps1_1',)) -> list[tuple[str, str]]:
    """Stage one or more levels: the map, its playlists, and its audio.

    Only the audio those levels actually reference is carried, so a single-level
    build stays small instead of hauling the whole 96 MB tree.
    """
    sys.path.insert(0, ROOT)
    from papasangre.assets.sexp import include_stem, parse_playlist  # noqa: PLC0415

    staging = os.path.join(ROOT, 'build', 'leveldata')
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    meta_src = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')
    meta_dst = os.path.join(staging, 'meta', 'S3DPlayListModel')
    exports_dst = os.path.join(staging, 'Exports', 'Papa Sangre')
    os.makedirs(meta_dst, exist_ok=True)
    os.makedirs(exports_dst, exist_ok=True)

    def playlist_files(stem, seen):
        """Copy a playlist and its includes; return the audio it declares."""
        if stem in seen:
            return []
        seen.add(stem)
        matches = [f for f in os.listdir(meta_src)
                   if f.startswith(stem + '.S3DPlayListModel')]
        if not matches:
            return []
        shutil.copy2(os.path.join(meta_src, matches[0]), meta_dst)
        pl = parse_playlist(open(os.path.join(meta_src, matches[0]),
                                 encoding='utf-8', errors='replace').read())
        audio = [d.bundle_path for d in pl.sounds if d.name]
        for inc in pl.includes:
            audio += playlist_files(include_stem(inc), seen)
        return audio

    wanted: set[str] = set()
    seen: set[str] = set()
    for stem in levels:
        src_map = os.path.join(BUNDLE, 'Exports', 'Papa Sangre', f'{stem}.json')
        if not os.path.exists(src_map):
            raise SystemExit(f'missing level export: {src_map}')
        shutil.copy2(src_map, exports_dst)
        wanted.update(playlist_files(stem, seen))

    # The startup splash is loaded by path, not through a playlist, so nothing
    # above will have picked it up.
    wanted.add('ps1/splash/papa_engine_splash.wav')

    # The level menu is the game's own hub list, so it has to travel with the
    # maps.  It sits beside the per-game folder, not inside it.
    hub = os.path.join(BUNDLE, 'Exports', 'Papa Sangre_hubList.plist')
    if os.path.exists(hub):
        shutil.copy2(hub, os.path.join(staging, 'Exports'))
    else:
        print('    WARNING: no hub list found; the level menu will be empty')

    copied = 0
    for rel in sorted(wanted):
        src = os.path.join(BUNDLE, rel.replace('/', os.sep))
        if not os.path.exists(src):
            continue
        dst = os.path.join(staging, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _d, fs in os.walk(staging) for f in fs)
    print(f'    staged {len(levels)} level(s), {copied} audio files, '
          f'{size / 1e6:.0f} MB')

    return staged_entries(staging)


def prepare_content_data() -> list[tuple[str, str]]:
    """Stage the reference data the content checker needs.

    The checker reads level exports, playlists and the engine's message
    vocabulary, and needs to know which audio files exist - but not their
    contents, so a pre-computed name index is bundled instead of 96 MB of audio.
    """
    sys.path.insert(0, ROOT)
    from papasangre.assets.audit import write_audio_index      # noqa: PLC0415

    staging = os.path.join(ROOT, 'build', 'contentdata')
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)

    shutil.copytree(os.path.join(BUNDLE, 'Exports'),
                    os.path.join(staging, 'Exports'))
    shutil.copytree(os.path.join(BUNDLE, 'meta'),
                    os.path.join(staging, 'meta'))
    for name in ('objectsList.plist', 'messagesList.plist'):
        shutil.copy2(os.path.join(BUNDLE, name), staging)
    shutil.copy2(os.path.join(ROOT, 'tools', 'ps_strings.txt'), staging)
    n = write_audio_index(BUNDLE, os.path.join(staging, 'audio_index.json'))
    print(f'    staged reference data ({n} audio names indexed)')

    return staged_entries(staging)


def build(key: str) -> str:
    script, exe_name, extra = TARGETS[key]
    if key == 'content':
        extra = prepare_content_data()
    elif key == 'walk':
        extra = prepare_level_data(('ps1_1',))
    elif key == 'play':
        extra = prepare_level_data(ALL_LEVELS)
    script_path = os.path.join(APPS, script)
    if not os.path.exists(script_path):
        raise SystemExit(f'missing app script: {script_path}')
    if not os.path.exists(HRTF):
        raise SystemExit(f'missing HRTF: {HRTF}\n'
                         f'run tools/extract_hrtf.py, then makemhr')
    if not os.path.exists(OPENAL):
        raise SystemExit(f'missing OpenAL Soft: {OPENAL}')

    data: list[tuple[str, str]] = [(HRTF, 'hrtf')]
    for name in ('nvdaControllerClient64.dll', 'nvdaControllerClient32.dll'):
        p = os.path.join(NVDA_DIR, name)
        if os.path.exists(p):
            data.append((p, 'nvda'))
    for src, dest in extra:
        if not os.path.exists(src):
            raise SystemExit(f'missing bundled audio: {src}')
        data.append((src, dest))

    # The game is built windowed: a console flashing up beside it is not part
    # of a released game, and its output is a convenience anyway - everything
    # that matters is spoken.  The diagnostic tools keep their console, which
    # is the whole point of them.
    console_flag = '--console' if exe_name != 'Play Papa Sangre' else '--windowed'
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean', '--onefile', console_flag,
        '--name', exe_name,
        '--distpath', RUN,
        '--workpath', WORK,
        '--specpath', WORK,
        '--add-binary', f'{OPENAL}{SEP}.',
        '--hidden-import', 'papasangre',
        '--paths', ROOT,
    ]
    for src, dest in data:
        cmd += ['--add-data', f'{src}{SEP}{dest}']
    cmd.append(script_path)

    print(f'\n=== building {exe_name}.exe ===', flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stdout.write(proc.stdout[-4000:])
        sys.stderr.write(proc.stderr[-4000:])
        raise SystemExit(f'PyInstaller failed for {exe_name}')
    out = os.path.join(RUN, exe_name + '.exe')
    size = os.path.getsize(out) / 1e6
    print(f'    {out}  ({size:.0f} MB, {time.perf_counter() - t0:.0f}s)')
    return out


def main() -> int:
    keys = sys.argv[1:] or list(TARGETS)
    unknown = [k for k in keys if k not in TARGETS]
    if unknown:
        raise SystemExit(f'unknown target(s) {unknown}; '
                         f'choose from {list(TARGETS)}')
    os.makedirs(RUN, exist_ok=True)
    built = [build(k) for k in keys]
    print('\nBuilt:')
    for b in built:
        print('  ', b)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
