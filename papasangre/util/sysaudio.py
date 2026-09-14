"""Audio settings, per platform, that can silently defeat binaural rendering.

Worth checking before anyone concludes the spatialisation is broken: if the
system is mixing everything to mono, or the output is a virtual cable, no HRTF
in the world will produce a direction.

The Windows checks read the registry; the Mac one reads the universal-access
default (see :mod:`.host`, which decides which applies).  The device-name
suspicion list is shared: a virtual cable defeats HRTF on every platform.
"""

from __future__ import annotations

import sys

#: Device names that are not a real pair of headphones and will not give
#: binaural results, even when everything else is correct.  Kept platform-
#: agnostic: BlackHole and Loopback are the Mac's virtual cables, VoiceMeeter
#: and VB-Cable are Windows', and the rest are either's.
SUSPECT_DEVICE_HINTS = (
    'virtual audio cable', 'vb-audio', 'voicemeeter', 'screaming bee',
    'morphvox', 'nvidia virtual', 'cable output', 'cable input',
    'blackhole', 'loopback', 'aggregate', 'multi-output device',
)


def mono_mix_enabled() -> bool | None:
    """True/False if the OS is mixing both channels into one.

    Dispatches on the platform: the Windows registry on Windows (this
    function's original body, kept for the Windows build), the universal-
    access default on the Mac.  Returns None when it cannot be determined.
    """
    from . import host                                       # noqa: PLC0415
    if host.WINDOWS:
        return _mono_mix_enabled_windows()
    if host.MAC:
        return _mono_audio_enabled_mac()
    return None


def _mono_mix_enabled_windows() -> bool | None:
    """Windows' 'Mono audio' accessibility toggle, from the registry."""
    if sys.platform != 'win32':
        return None
    try:
        import winreg                                          # noqa: PLC0415
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Multimedia\Audio') as k:
            value, _ = winreg.QueryValueEx(k, 'AccessibilityMonoMixState')
            return bool(value)
    except (OSError, FileNotFoundError, ImportError):
        return None


def _mono_audio_enabled_mac() -> bool | None:
    """macOS 'Mono audio' - com.apple.universalaccess monoAudioEnabled.

    Read with ``defaults``, which needs no permission, unlike the APIs that
    read this preference in place.  Some macOS versions store the value as a
    plist fragment rather than a plain integer, so both shapes are accepted.
    """
    import plistlib
    import subprocess
    try:
        proc = subprocess.run(
            ['/usr/bin/defaults', 'read', 'com.apple.universalaccess',
             'monoAudioEnabled'], capture_output=True, text=True, timeout=2)
        out = proc.stdout.strip()
        if proc.returncode == 0 and out.isdigit():
            return out != '0'
        if proc.returncode == 0 and out:
            try:
                blob = plistlib.loads(proc.stdout.encode())
                if isinstance(blob, bool):
                    return blob
            except Exception:                              # noqa: BLE001
                pass
    except Exception:                                      # noqa: BLE001
        pass
    return None


def device_looks_virtual(device_name: str) -> bool:
    low = (device_name or '').lower()
    return any(h in low for h in SUSPECT_DEVICE_HINTS)


def warnings_for(device_name: str) -> list[str]:
    """Things that would make correct spatial audio sound centred anyway."""
    from . import host                                       # noqa: PLC0415
    out: list[str] = []
    mono = mono_mix_enabled()
    if mono:
        if host.MAC:
            out.append('System mono audio is switched on, which mixes both '
                       'ears together. Turn it off in System Settings, '
                       'Accessibility, Audio.')
        else:
            out.append('Windows mono audio is switched on, which mixes both '
                       'ears together. Turn it off in Settings, '
                       'Accessibility, Audio.')
    if device_looks_virtual(device_name):
        out.append(f'Output is going to {device_name}, which looks like a '
                   f'virtual or routing device rather than headphones.')
    return out
