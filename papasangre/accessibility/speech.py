"""Screen-reader output.

Papa Sangre itself never spoke — it is an audio game and every cue is a sound.
Speech here is for the things the iOS build put on screen or in VoiceOver:
menus, level names, status, and the settings UI.  In-game it stays quiet unless
the player asks for it, so the soundscape is never talked over.

Backends, tried in order — decided by the platform, never by what happens to
be importable:

* **macOS**
  1. VoiceOver through pyobjc (``voiceover.py``, a port of the accessibility
     mod's ``VoiceOverOutput.cs``): ``tell application "VoiceOver" to output
     "…"`` via ``NSAppleScript``, falling back to an
     ``NSAccessibilityPostNotificationWithUserInfo`` announcement on the key
     window.  VoiceOver is part of macOS, so there is nothing to detect
     beyond it being switched on.
  2. A null backend that records what would have been said (for tests).

* **Windows**
  1. ``nvdaControllerClient64.dll`` — direct, no COM, lowest latency.
  2. SAPI 5 through ``win32com``/``comtypes`` — always available on Windows.
  3. A null backend that records what would have been said (for tests).
"""

from __future__ import annotations

import ctypes
import os
import sys

from ..util import host, paths

_NVDA_DLL_NAMES = ('nvdaControllerClient64.dll', 'nvdaControllerClient32.dll')


def _nvda_search_dirs() -> list[str]:
    """Where to look for an NVDA controller client, best first.

    The client is meant to be shipped with the application, so the copy that
    travels inside the build wins.  The rest are fallbacks for running from
    source on a machine that happens to have one of these programs installed.
    """
    return [
        paths.resource('nvda'),
        paths.resource('vendor', 'nvda'),
        r'C:\Program Files\TeamTalk5',
        r'C:\Program Files\twblue\accessible_output2\lib',
        r'C:\Program Files\twblue\lib\accessible_output2\lib',
        r'C:\Program Files (x86)\TeamTalk5',
    ]

class SpeechBackend:
    name = 'null'

    def speak(self, text: str, interrupt: bool = False) -> bool:
        return False

    def braille(self, text: str) -> bool:
        return False

    def cancel(self) -> bool:
        return False

    def close(self) -> None:
        pass


class NullSpeech(SpeechBackend):
    """Records output instead of speaking it; used by the test suite."""
    name = 'null'

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text: str, interrupt: bool = False) -> bool:
        self.spoken.append(text)
        return True

    def cancel(self) -> bool:
        return True


class NvdaSpeech(SpeechBackend):
    name = 'nvda'

    def __init__(self, dll_path: str):
        self.dll_path = dll_path
        self.lib = ctypes.windll.LoadLibrary(dll_path)
        self.lib.nvdaController_testIfRunning.restype = ctypes.c_ulong
        self.lib.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
        self.lib.nvdaController_brailleMessage.argtypes = [ctypes.c_wchar_p]
        if self.lib.nvdaController_testIfRunning() != 0:
            raise OSError('NVDA is not running')

    def speak(self, text: str, interrupt: bool = False) -> bool:
        if interrupt:
            self.lib.nvdaController_cancelSpeech()
        return self.lib.nvdaController_speakText(text) == 0

    def braille(self, text: str) -> bool:
        return self.lib.nvdaController_brailleMessage(text) == 0

    def cancel(self) -> bool:
        return self.lib.nvdaController_cancelSpeech() == 0


class SapiSpeech(SpeechBackend):
    name = 'sapi'

    def __init__(self) -> None:
        import comtypes.client            # noqa: PLC0415
        self._voice = comtypes.client.CreateObject('SAPI.SpVoice')
        self._SVSFlagsAsync = 1
        self._SVSFPurgeBeforeSpeak = 2

    def speak(self, text: str, interrupt: bool = False) -> bool:
        flags = self._SVSFlagsAsync
        if interrupt:
            flags |= self._SVSFPurgeBeforeSpeak
        self._voice.Speak(text, flags)
        return True

    def cancel(self) -> bool:
        self._voice.Speak('', self._SVSFlagsAsync | self._SVSFPurgeBeforeSpeak)
        return True


class VoiceOverSpeech(SpeechBackend):
    """VoiceOver through pyobjc — the Mac's counterpart to NvdaSpeech.

    The real work is in :mod:`.voiceover`, a port of the accessibility mod's
    ``VoiceOverOutput.cs``; this wrapper exists so the rest of the game sees
    the same three-method backend NVDA and SAPI present.  ``braille`` routes
    through the same ``output`` command because VoiceOver renders what it
    speaks onto a connected braille display itself.
    """

    name = 'voiceover'

    def __init__(self) -> None:
        from . import voiceover                              # noqa: PLC0415
        if not voiceover.is_supported():
            raise OSError('VoiceOver output is unavailable')
        self._vo = voiceover

    def speak(self, text: str, interrupt: bool = False) -> bool:
        return self._vo.speak(text, interrupt=interrupt)

    def braille(self, text: str) -> bool:
        return self._vo.speak(text)

    def cancel(self) -> bool:
        return self._vo.cancel()


def _find_nvda_dll() -> str | None:
    want = _NVDA_DLL_NAMES[0] if sys.maxsize > 2 ** 32 else _NVDA_DLL_NAMES[1]
    for d in _nvda_search_dirs():
        p = os.path.join(d, want)
        if os.path.exists(p):
            return p
    return None


def create(prefer: str | None = None) -> SpeechBackend:
    """Pick the best available backend for this platform.

    ``prefer`` forces one: 'voiceover', 'nvda', 'sapi' or 'null'.  The default
    order is the platform's (``host.speech_backend_order()``): VoiceOver on
    the Mac, NVDA then SAPI on Windows.
    """
    order = [prefer] if prefer else host.speech_backend_order()
    for kind in order:
        try:
            if kind == 'voiceover':
                return VoiceOverSpeech()
            elif kind == 'nvda':
                dll = _find_nvda_dll()
                if dll:
                    return NvdaSpeech(dll)
            elif kind == 'sapi':
                return SapiSpeech()
            elif kind == 'null':
                return NullSpeech()
        except Exception:                                    # noqa: BLE001
            continue
    return NullSpeech()
