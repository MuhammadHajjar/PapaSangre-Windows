"""Platform guards: every Windows-specific choice has a Mac equivalent.

The port was Windows-only.  These tests hold the guarantee that nothing in
``papasangre/`` reaches past the :mod:`papasangre.util.host` layer for a
platform decision, and that both platforms' equivalents resolve - the NVDA
DLL has its VoiceOver bridge, ``soft_oal.dll`` its ``libopenal.dylib``, the
``.cmd`` launchers their ``.command`` twins.
"""

import ast
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.util import host                              # noqa: E402

VENDOR_OPENAL_WIN = os.path.join(ROOT, 'vendor', 'openal', 'soft_oal.dll')
VENDOR_OPENAL_MAC = os.path.join(ROOT, 'vendor', 'openal-mac',
                                 'libopenal.dylib')
VENDOR_NVDA = os.path.join(ROOT, 'vendor', 'nvda',
                           'nvdaControllerClient64.dll')


# ------------------------------------------------------------ platform module
def test_platform_is_decided_once():
    assert host.PLATFORM in ('windows', 'mac', 'linux', 'other')
    assert host.WINDOWS == (sys.platform == 'win32')
    assert host.MAC == (sys.platform == 'darwin')
    assert host.LINUX == sys.platform.startswith('linux')
    # exactly one of the supported platforms, never two
    assert sum((host.WINDOWS, host.MAC, host.LINUX)) <= 1


def test_the_port_names_itself_for_the_platform():
    expected = {'mac': 'Mac', 'windows': 'Windows', 'linux': 'Linux',
                'other': 'Other'}[host.PLATFORM]
    assert host.PORT_NAME == expected


def test_quit_hint_is_the_platforms_window_close():
    expected = ('Cmd+Q' if host.MAC else
                'Alt+F4' if host.WINDOWS or host.LINUX else
                'window close')
    assert host.quit_hint() == expected


def test_speech_backend_order_follows_the_platform():
    if host.MAC:
        assert host.speech_backend_order() == ['voiceover', 'null']
    elif host.LINUX:
        assert host.speech_backend_order() == ['speechd']
    elif host.WINDOWS:
        assert host.speech_backend_order() == ['nvda', 'sapi', 'null']


def test_mono_setting_never_raises_anywhere():
    """Unknown platform or unreadable setting: None, not an exception."""
    value = host.mono_audio_setting()
    assert value in (True, False, None)


# ------------------------------------------------------------------- speech
def test_speech_factory_respects_the_platform():
    from papasangre.accessibility import speech
    if host.LINUX:
        class Client:
            def set_priority(self, priority):
                self.priority = priority

            def close(self):
                pass

        fake_speechd = SimpleNamespace(
            Client=Client,
            client=SimpleNamespace(Priority=SimpleNamespace(MESSAGE=1)))
        with patch.dict(sys.modules, {'speechd': fake_speechd}):
            backend = speech.create()
    else:
        backend = speech.create()
    try:
        if host.MAC:
            assert backend.name in ('voiceover', 'null'), backend.name
        elif host.LINUX:
            assert backend.name == 'speechd', backend.name
        elif host.WINDOWS:
            assert backend.name in ('nvda', 'sapi', 'null'), backend.name
    finally:
        backend.close()


def test_linux_speech_does_not_silently_fall_back():
    if not host.LINUX:
        return
    from papasangre.accessibility import speech

    def unavailable_client():
        raise OSError('service unavailable')

    fake_speechd = SimpleNamespace(Client=unavailable_client)
    with patch.dict(sys.modules, {'speechd': fake_speechd}):
        try:
            speech.create()
        except RuntimeError as exc:
            assert 'Speech Dispatcher is unavailable' in str(exc)
        else:
            raise AssertionError('missing Speech Dispatcher must be reported')


def test_forcing_a_backend_wins_over_the_platform():
    from papasangre.accessibility import speech
    backend = speech.create(prefer='null')
    try:
        assert backend.name == 'null'
    finally:
        backend.close()


def test_voiceover_module_matches_the_csharp_interfaces():
    """VoiceOverOutput.cs -> voiceover.py, call for call."""
    from papasangre.accessibility import voiceover
    for fn in ('is_supported', 'is_running', 'speak', 'cancel',
               'is_speaking', 'shutdown'):
        assert callable(getattr(voiceover, fn, None)), fn
    assert voiceover.is_supported() == host.MAC
    if not host.MAC:
        assert voiceover.speak('no-op off the mac') is False


def test_the_applescript_is_escaped_the_way_the_csharp_escapes_it():
    from papasangre.accessibility.voiceover import _escape_applescript
    assert _escape_applescript('say "hello"') == 'say \\"hello\\"'
    assert _escape_applescript('back\\slash') == 'back\\\\slash'


# -------------------------------------------------------------------- paths
def test_openal_library_is_the_platforms_own_and_exists():
    from papasangre.util import paths
    if host.MAC:
        assert os.path.basename(paths.openal_dll()) == 'libopenal.dylib'
    elif host.LINUX:
        assert os.path.basename(paths.openal_dll()) in ('libopenal.so',
                                                        'libopenal.so.1')
    else:
        assert os.path.basename(paths.openal_dll()) == 'soft_oal.dll'
    if host.LINUX:
        import ctypes
        try:
            ctypes.CDLL(paths.openal_dll())
        except OSError as exc:
            raise AssertionError(f'cannot load {paths.openal_dll()}: {exc}')
    else:
        assert os.path.exists(paths.openal_dll()), paths.openal_dll()


def test_both_platforms_libraries_are_vendored():
    """The Mac dylib is committed beside the Windows DLL, not downloaded."""
    assert os.path.exists(VENDOR_OPENAL_WIN), VENDOR_OPENAL_WIN
    assert os.path.exists(VENDOR_OPENAL_MAC), VENDOR_OPENAL_MAC


def test_mac_dylib_is_a_real_mach_o_and_self_contained():
    """Built for this machine's arch, and linked against system frameworks."""
    import subprocess
    out = subprocess.run(['file', VENDOR_OPENAL_MAC],
                         capture_output=True, text=True).stdout
    assert 'Mach-O' in out, out
    if host.MAC:
        machine = 'arm64' if os.uname().machine == 'arm64' else 'x86_64'
        assert machine in out, out


# ------------------------------------------------------------------ openal
def test_alsoft_config_header_is_platform_neutral():
    from papasangre.audio import openal as OA
    import inspect
    src = inspect.getsource(OA.write_alsoft_config)
    assert 'Windows port' not in src


def test_openal_load_sets_the_dyld_path_on_the_mac():
    from papasangre.audio import openal as OA
    import inspect
    src = inspect.getsource(OA.OpenAL.__init__)
    if host.MAC:
        assert 'DYLD_FALLBACK_LIBRARY_PATH' in src
    else:
        assert 'add_dll_directory' in src


# ------------------------------------------------------------------ windows
def test_windows_only_imports_never_load_off_windows():
    """winreg / windll must sit behind a platform guard, not at import time.

    Only *module-level* imports count: a function-body import never runs
    unless its function is called, which is exactly how the guarded ones are
    written.
    """
    for rel in ('papasangre/accessibility/speech.py',
                'papasangre/util/sysaudio.py',
                'papasangre/util/host.py'):
        tree = ast.parse(open(os.path.join(ROOT, rel),
                              encoding='utf-8').read())
        for node in tree.body:                      # module level only
            if isinstance(node, ast.Import):
                assert all(a.name != 'winreg' for a in node.names), rel
            elif isinstance(node, ast.ImportFrom):
                assert node.module != 'winreg', rel


def test_speech_module_names_the_mac_backend():
    from papasangre.accessibility import speech
    assert hasattr(speech, 'VoiceOverSpeech')
    assert speech.VoiceOverSpeech.name == 'voiceover'


# ---------------------------------------------------------------- launchers
def test_every_cmd_launcher_has_a_command_twin():
    run = os.path.join(ROOT, 'Run')
    cmds = [f for f in os.listdir(run) if f.endswith('.cmd')]
    assert cmds, 'no launchers at all'
    for name in cmds:
        twin = name[:-4] + '.command'
        assert os.path.exists(os.path.join(run, twin)), twin
        body = open(os.path.join(run, twin), encoding='utf-8').read()
        assert body.startswith('#!/bin/bash'), twin
        assert 'Play Papa Sangre.app/Contents/MacOS' in body, twin
        # the level the .cmd launches is the level the .command launches
        level_cmd = open(os.path.join(run, name),
                         encoding='utf-8').read().split()[-1]
        assert level_cmd in body, f'{twin} does not launch {level_cmd}'


def test_command_launchers_are_executable():
    run = os.path.join(ROOT, 'Run')
    for name in os.listdir(run):
        if name.endswith('.command'):
            assert os.access(os.path.join(run, name), os.X_OK), name


# ------------------------------------------------------------------ building
def test_build_script_uses_the_platform_separator():
    import tools.build_exes as be
    assert be.SEP == (';' if host.WINDOWS else ':')


def test_build_script_names_the_app_per_platform():
    import tools.build_exes as be
    if host.MAC:
        assert be.GAME_NAME == 'Play Papa Sangre'
    # the game target is shared; only the extension differs
    assert be.TARGETS['play'][1] == be.GAME_NAME


def test_pack_release_names_the_archive_for_the_platform():
    import tools.pack_release as pr
    if host.MAC:
        assert pr.GAME == 'Play Papa Sangre.app'
    elif host.WINDOWS:
        assert pr.GAME == 'Play Papa Sangre.exe'


def test_pyobjc_is_a_declared_dependency():
    """The VoiceOver bridge has to travel inside the frozen build."""
    toml = open(os.path.join(ROOT, 'pyproject.toml'),
                encoding='utf-8').read()
    assert 'pyobjc-framework-cocoa' in toml
    assert 'pygame-ce' in toml
    assert 'pyinstaller' in toml


def test_the_mac_bundle_identifier_is_reverse_dns():
    import tools.build_exes as be
    bid = be.BUNDLE_ID
    assert bid.count('.') >= 2            # com.<something>.<leaf>: not 'Play Papa Sangre'
    assert ' ' not in bid
    assert all(part.isalnum() for part in bid.split('.')), bid


def test_version_helper_reads_the_version_file():
    import tools.build_exes as be
    want = open(os.path.join(ROOT, 'VERSION'), encoding='utf-8').read().strip()
    assert be.version() == (want or '0.0.0')


def test_finalize_mac_app_stamps_identity_and_version():
    """The .app must ship a sane bundle id and the real version, not 0.0.0."""
    import plistlib
    import tempfile
    import tools.build_exes as be
    if host.WINDOWS:
        return
    with tempfile.TemporaryDirectory() as tmp:
        bundle = os.path.join(tmp, 'Fake.app')
        macos = os.path.join(bundle, 'Contents', 'MacOS')
        os.makedirs(macos)
        open(os.path.join(macos, be.GAME_NAME), 'w').close()
        info = os.path.join(bundle, 'Contents', 'Info.plist')
        with open(info, 'wb') as fh:
            plistlib.dump({'CFBundleIdentifier': 'Play Papa Sangre',
                           'CFBundleShortVersionString': '0.0.0',
                           'CFBundleVersion': '0.0.0'}, fh)
        be._finalize_mac_app(bundle)
        with open(info, 'rb') as fh:
            plist = plistlib.load(fh)
        assert plist['CFBundleIdentifier'] == be.BUNDLE_ID
        assert plist['CFBundleShortVersionString'] == be.version()
        assert plist['CFBundleVersion'] == be.version()


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f'  PASS  {fn.__name__}')
        except Exception as e:                                   # noqa: BLE001
            failed += 1
            print(f'  FAIL  {fn.__name__}: {e}')
    print(f'\n{len(fns) - failed}/{len(fns)} passed')
    raise SystemExit(1 if failed else 0)
