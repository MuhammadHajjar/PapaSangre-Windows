"""Build the standalone, self-contained applications.

Everything the project hands over should be double-clickable — no terminal, no
Python, no paths to type.  This freezes each app in ``apps/`` into a single
self-contained bundle in ``Run/``, carrying its own OpenAL Soft, the recovered
HRTF and whatever game audio it needs, and it does so **for the platform it
runs on**:

=================  ==========================================  =================
Windows            ``Play Papa Sangre.exe`` — a one-file       ``soft_oal.dll``
                   PyInstaller build, exactly as it has        ``NVDA client``
                   always been.                                ``.mhr``
Mac                ``Play Papa Sangre.app`` — a one-file       ``libopenal.dylib``
                   PyInstaller ``--windowed`` bundle: the      ``.mhr`` only —
                   whole game in one bundle, no runtime,       speech is VoiceOver,
                   no installs, launched like any other        part of macOS.
                   Mac app.
=================  ==========================================  =================

The diagnostic tools stay console programs on both platforms — on the Mac a
plain executable beside the bundles — because their output *is* the point.

Run:  python tools/build_exes.py            (all apps)
      python tools/build_exes.py listen     (one app, by key)
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.util import host                            # noqa: E402

APPS = os.path.join(ROOT, 'apps')
RUN = os.path.join(ROOT, 'Run')
WORK = os.path.join(ROOT, 'build', 'pyinstaller')
BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
HRTF_DIR = os.path.join(ROOT, 'build', 'hrtf')
HRTF = os.path.join(HRTF_DIR, 'papa_ircam_1050.mhr')

#: PyInstaller's src;dest separator: ';' on Windows, ':' everywhere else.
SEP = ';' if host.WINDOWS else ':'

#: The game, as the player receives it on each platform.
GAME_NAME = 'Play Papa Sangre'

#: The Mac bundle's reverse-DNS identity.  PyInstaller's default is just the
#: app name, which is not a sane identifier (and a space, at that): this is
#: what LaunchServices, Spotlight and \"uninstall\" tooling key on.
BUNDLE_ID = 'com.papasangre.port'


def version() -> str:
    """The port's version, from ``VERSION`` at the repository root."""
    try:
        with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as fh:
            return fh.read().strip() or '0.0.0'
    except OSError:
        return '0.0.0'


def openal_library() -> str:
    """The OpenAL Soft library for this platform, from vendor/."""
    if host.MAC:
        p = os.path.join(ROOT, 'vendor', 'openal-mac', 'libopenal.dylib')
    else:
        p = os.path.join(ROOT, 'vendor', 'openal', 'soft_oal.dll')
    if not os.path.exists(p):
        raise SystemExit(
            f'missing OpenAL Soft: {p}\n'
            f'Mac: build it with tools/build_openal_mac.sh and place the '
            'result at vendor/openal-mac/libopenal.dylib.\n'
            f'Windows: it ships as vendor/openal/soft_oal.dll, see README.md.')
    return p


OPENAL = openal_library()
NVDA_DIR = os.path.join(ROOT, 'vendor', 'nvda')


def makemhr_binary() -> str | None:
    """The platform's makemhr: ``makemhr.exe`` on Windows, the Mac build there."""
    if host.MAC:
        p = os.path.join(ROOT, 'vendor', 'makemhr-mac', 'makemhr')
    else:
        p = os.path.join(ROOT, 'vendor', 'makemhr', 'makemhr.exe')
    return p if os.path.exists(p) else None


def prepare_hrtf() -> str:
    """Make sure the built HRTF exists, building it if it does not.

    ``papa_ircam_1050.mhr`` lives in ``build/`` and is therefore not committed:
    it is produced from the committed ``tools/embedded_hrtf.dat`` (the original
    IRCAM 1050 set) by ``tools/extract_hrtf.py`` followed by OpenAL Soft's
    ``makemhr``.  On a machine that has ever built before the file is already
    there and this is a no-op; on a fresh clone it is recreated end to end.
    """
    if os.path.exists(HRTF):
        return HRTF
    os.makedirs(HRTF_DIR, exist_ok=True)
    print('    building HRTF (first build on this machine)...')
    seed = os.path.join(ROOT, 'tools', 'embedded_hrtf.dat')
    if not os.path.exists(seed):
        raise SystemExit(
            f'missing the HRTF source data: {seed}\n'
            'the recovered IRCAM 1050 table should be committed beside '
            'tools/extract_hrtf.py')
    subprocess.run([sys.executable,
                    os.path.join(ROOT, 'tools', 'extract_hrtf.py')],
                   cwd=ROOT, check=True)
    makemhr = makemhr_binary()
    if not makemhr:
        raise SystemExit(
            f'missing makemhr: {makemhr_binary() or "?"}\n'
            f'Windows: it ships in the openal-soft binary zip, see README.md.\n'
            f'Mac: build it with tools/build_openal_mac.sh, or copy the '
            'arm64 makemhr into vendor/makemhr-mac/')
    subprocess.run([makemhr,
                    '-i', os.path.join(HRTF_DIR, 'papa_ircam_1050.def'),
                    '-o', HRTF],
                   cwd=HRTF_DIR, check=True)
    if not os.path.exists(HRTF):
        raise SystemExit(f'makemhr did not produce {HRTF}')
    print(f'    {HRTF}')
    return HRTF


def staged_entries(staging: str) -> list[tuple[str, str]]:
    """Turn a staging directory into a handful of ``--add-data`` entries.

    One entry per file blows past the command-line length limit once a build
    carries the whole audio tree, so whole directories are passed instead and
    PyInstaller copies their contents.
    """
    data: list[tuple[str, str]] = []
    for name in sorted(os.listdir(staging)):
        full = os.path.join(staging, name)
        data.append((full, f'gamedata/{name}' if os.path.isdir(full)
                     else 'gamedata'))
    return data


def game_audio(*rel: str) -> tuple[str, str]:
    """(source, dest-inside-bundle) for one file from the original bundle."""
    src = os.path.join(BUNDLE, *rel)
    dest = 'gamedata/' + '/'.join(rel[:-1])
    return src, dest


#: key -> (script, app name, extra data files as (src, dest) pairs)
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
        GAME_NAME,
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
    from papasangre.assets.audit import (known_messages,        # noqa: PLC0415
                                         write_audio_index)

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
    # The engine message vocabulary.  tools/ps_strings.txt is the canonical
    # extraction of the original binary's string table, but the binary is not
    # committed, so on a fresh clone the vocabulary is assembled from the
    # committed sources instead (see papasangre.assets.audit.known_messages).
    vocab = ' '.join(sorted(known_messages()))
    with open(os.path.join(staging, 'ps_strings.txt'), 'w',
              encoding='utf-8') as fh:
        fh.write(vocab + '\n')
    n = write_audio_index(BUNDLE, os.path.join(staging, 'audio_index.json'))
    print(f'    staged reference data ({n} audio names indexed)')

    return staged_entries(staging)


def _finalize_mac_app(bundle: str) -> None:
    """Make a PyInstaller .app behave like a proper double-clickable bundle.

    PyInstaller's windowed Mac build lays the bundle out correctly but leaves
    the inner executable without the executable bit, and a bundle whose binary
    is not named like its CFBundleExecutable will not open from Finder.  A
    bare-named launcher beside the real binary keeps
    ``open "Run/Play Papa Sangre.app" --args ps1_15`` working from the command
    line too.

    Also stamps the identity a real bundle should carry: a reverse-DNS
    ``CFBundleIdentifier`` (PyInstaller's default is the bare app name) and a
    ``CFBundleShortVersionString``/``CFBundleVersion`` taken from ``VERSION``.
    PyInstaller writes ``0.0.0`` for both, which would otherwise ship even
    though the release zip is named ``1.0.0``.
    """
    macos = os.path.join(bundle, 'Contents', 'MacOS')
    if not os.path.isdir(macos):
        raise SystemExit(f'not a .app bundle: {bundle}')
    exe = os.path.join(macos, GAME_NAME)
    if os.path.exists(exe):
        mode = os.stat(exe).st_mode
        os.chmod(exe, mode | 0o111)
    # PkgInfo is what Finder reads first; PyInstaller does not always write it.
    pkg = os.path.join(bundle, 'Contents', 'PkgInfo')
    if not os.path.exists(pkg):
        with open(pkg, 'w', encoding='ascii') as fh:
            fh.write('APPL????')

    info = os.path.join(bundle, 'Contents', 'Info.plist')
    with open(info, 'rb') as fh:
        plist = plistlib.load(fh)
    plist['CFBundleIdentifier'] = BUNDLE_ID
    plist['CFBundleShortVersionString'] = version()
    plist['CFBundleVersion'] = version()
    with open(info, 'wb') as fh:
        plistlib.dump(plist, fh, sort_keys=True)


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
    hrtf = prepare_hrtf()

    data: list[tuple[str, str]] = [(hrtf, 'hrtf')]
    # Speech travels with the Windows build: the NVDA controller client is a
    # DLL that must sit beside the game.  On the Mac speech is VoiceOver, part
    # of the operating system, so there is nothing to carry — the pyobjc
    # bridge is inside the frozen Python itself.
    if host.WINDOWS:
        for name in ('nvdaControllerClient64.dll',
                     'nvdaControllerClient32.dll'):
            p = os.path.join(NVDA_DIR, name)
            if os.path.exists(p):
                data.append((p, 'nvda'))
    for src, dest in extra:
        if not os.path.exists(src):
            raise SystemExit(f'missing bundled audio: {src}')
        data.append((src, dest))

    # The game is built windowed: a console flashing up beside it is not part
    # of a released game, and its output is a convenience anyway - everything
    # that matters is spoken.  On the Mac --windowed is also what makes
    # PyInstaller produce a .app bundle rather than a bare executable.  The
    # diagnostic tools keep their console, which is the whole point of them.
    windowed = exe_name == GAME_NAME
    console_flag = '--windowed' if windowed else '--console'
    # The one-file bootloader unpacks its payload to a temp dir on every
    # launch, and the game's payload is ~100 MB across six hundred small audio
    # files: that cost seconds on Windows and tens of seconds on the Mac.  The
    # game is therefore a one-dir app on the Mac (files read in place, the
    # bundle stays double-clickable) and stays one-file on Windows, where the
    # old behaviour is proven and the cost is tolerable.  The diagnostics stay
    # one-file everywhere: they are small, and their single-file shape is what
    # makes them drop-in tools.
    mode = '--onedir' if (host.MAC and windowed) else '--onefile'
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean', mode, console_flag,
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
    if host.MAC:
        # pyobjc resolves its frameworks lazily enough that the analyser
        # cannot always see them; the VoiceOver bridge needs both of these
        # inside the frozen build.
        cmd += ['--hidden-import', 'Foundation', '--hidden-import', 'AppKit']
    cmd.append(script_path)

    kind = '.app' if (host.MAC and windowed) else '.exe' if host.WINDOWS else ''
    print(f'\n=== building {exe_name}{kind} ===', flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stdout.write(proc.stdout[-4000:])
        sys.stderr.write(proc.stderr[-4000:])
        raise SystemExit(f'PyInstaller failed for {exe_name}')

    if host.MAC and windowed:
        out = os.path.join(RUN, exe_name + '.app')
        _finalize_mac_app(out)
    elif host.WINDOWS:
        out = os.path.join(RUN, exe_name + '.exe')
    else:
        out = os.path.join(RUN, exe_name)
    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _d, fs in os.walk(out) for f in fs) \
        if os.path.isdir(out) else os.path.getsize(out)
    print(f'    {out}  ({size / 1e6:.0f} MB, {time.perf_counter() - t0:.0f}s)')
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
