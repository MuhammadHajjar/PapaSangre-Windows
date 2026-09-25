"""Which platform the port is running on, decided once.

The port was Windows-only, and every Windows-specific choice — the OpenAL
DLL, the NVDA controller client, SAPI, ``winreg``, ``ctypes.windll``, the
PyInstaller ``;`` separator, the ``.exe``/``.app`` shapes — now sits behind
this module, so gameplay code never branches on ``sys.platform`` itself.  A
new platform means touching this file and whatever it names, not the engine.

Mac equivalents, one for one:

=================================  ==========================================
Windows                            Mac
=================================  ==========================================
``soft_oal.dll``                   ``libopenal.dylib`` (same OpenAL Soft)
``nvdaControllerClient64.dll``     VoiceOver through pyobjc, after the
                                   ``VoiceOverOutput`` pattern
SAPI 5 fallback                    (VoiceOver is always present on macOS)
``AccessibilityMonoMixState``      ``com.apple.universalaccess
(winreg mono check)                monoAudioEnabled``, via ``defaults``
``Play Papa Sangre.exe``           ``Play Papa Sangre.app`` bundle
``Start at level N.cmd``           ``Start at level N.command``
``;`` in ``--add-data``            ``:`` in ``--add-data``
``alt+F4``                         ``Cmd+Q``
=================================  ==========================================

Linux equivalents:

=================================  ==========================================
Windows                            Linux
=================================  ==========================================
``soft_oal.dll``                   ``libopenal.so`` (same OpenAL Soft,
                                   built and committed in vendor/openal-linux)
``nvdaControllerClient64.dll``     speech-dispatcher (``speechd`` Python
                                   client), falling back to bundled espeak-ng
SAPI 5 fallback                    bundled espeak-ng binary + voice data
``Play Papa Sangre.exe``           ``Play Papa Sangre`` (one-dir, executable)
``%LOCALAPPDATA%\\Papa Sangre``    ``~/.local/share/Papa Sangre`` (XDG)
``;`` in ``--add-data``            ``:`` in ``--add-data``
``Alt+F4``                         ``Alt+F4``
=================================  ==========================================
"""

from __future__ import annotations

import platform
import sys

WINDOWS = sys.platform == 'win32'
MAC = sys.platform == 'darwin'
LINUX = sys.platform.startswith('linux')

#: The one name the rest of the port tests against.  'windows' | 'mac' | 'linux' | 'other'
PLATFORM = ('mac' if MAC else 'windows' if WINDOWS else 'linux' if LINUX else 'other')

if PLATFORM == 'other':                                    # pragma: no cover
    import warnings
    warnings.warn(f'papasangre has not been ported to {sys.platform!r}; '
                  'some features will quietly do nothing.', stacklevel=2)

IS_FROZEN = getattr(sys, 'frozen', False)
#: True when a frozen mac build is running inside a .app bundle layout
#: (executable under ``Contents/MacOS``).  Decided by looking, not assumed.
IS_MAC_APP_BUNDLE = False
if MAC and IS_FROZEN:
    import os
    meipass = getattr(sys, '_MEIPASS', '') or ''
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    IS_MAC_APP_BUNDLE = (os.path.basename(meipass) in ('MacOS', 'Frameworks')
                         or os.path.basename(exe_dir) == 'MacOS')

#: Architecture tag for Mac file names; '' on Windows, whose names stay
#: exactly as they have always been.
_arch = platform.machine() or ''
ARCH_TAG = '' if WINDOWS else ('arm64' if _arch == 'arm64' else
                               'x86_64' if _arch == 'x86_64' else 'mac')


def quit_hint() -> str:
    """How you leave the game, which no in-game key does on any platform."""
    return 'Cmd+Q' if MAC else 'Alt+F4'


#: How the port names itself in banners and reports.
PORT_NAME = 'Mac' if MAC else 'Windows' if WINDOWS else 'Linux' if LINUX else PLATFORM.capitalize()


def mono_audio_setting() -> bool | None:
    """Is the OS mixing both channels together?

    Windows: the 'Mono audio' accessibility toggle, from the registry
    (``sysaudio.mono_mix_enabled``).
    Mac:     the ``com.apple.universalaccess monoAudioEnabled`` default, read
             with ``defaults`` - no permissions needed, present since 10.9.
    Neither: None.
    """
    if WINDOWS:
        from . import sysaudio                              # noqa: PLC0415
        return sysaudio.mono_mix_enabled()
    if MAC:
        try:
            import plistlib
            import subprocess
            proc = subprocess.run(
                ['/usr/bin/defaults', 'read', 'com.apple.universalaccess',
                 'monoAudioEnabled'],
                capture_output=True, text=True, timeout=2)
            out = proc.stdout.strip()
            if proc.returncode == 0 and out.isdigit():
                return out != '0'
            if proc.returncode == 0 and out:
                try:                # some macOS versions write a plist fragment
                    blob = plistlib.loads(proc.stdout.encode())
                    if isinstance(blob, bool):
                        return blob
                except Exception:                          # noqa: BLE001
                    pass
        except Exception:                                  # noqa: BLE001
            pass
        return None
    return None


def speech_backend_order() -> list[str]:
    """Which screen-reader backends to try, best first."""
    if MAC:
        return ['voiceover', 'null']
    if LINUX:
        return ['speechd', 'espeak', 'null']
    return ['nvda', 'sapi', 'null']
