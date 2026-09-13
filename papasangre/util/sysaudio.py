"""Windows audio settings that can silently defeat binaural rendering.

Worth checking before anyone concludes the spatialisation is broken: if the
system is mixing everything to mono, or the output is a virtual cable, no HRTF
in the world will produce a direction.
"""

from __future__ import annotations

import sys

#: Device names that are not a real pair of headphones and will not give
#: binaural results, even when everything else is correct.
SUSPECT_DEVICE_HINTS = (
    'virtual audio cable', 'vb-audio', 'voicemeeter', 'screaming bee',
    'morphvox', 'nvidia virtual', 'cable output', 'cable input',
)


def mono_mix_enabled() -> bool | None:
    """True/False if Windows' 'Mono audio' accessibility setting is on/off.

    Returns None when it cannot be determined (non-Windows, or no such key).
    """
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


def device_looks_virtual(device_name: str) -> bool:
    low = (device_name or '').lower()
    return any(h in low for h in SUSPECT_DEVICE_HINTS)


def warnings_for(device_name: str) -> list[str]:
    """Things that would make correct spatial audio sound centred anyway."""
    out: list[str] = []
    mono = mono_mix_enabled()
    if mono:
        out.append('Windows mono audio is switched on, which mixes both ears '
                   'together. Turn it off in Settings, Accessibility, Audio.')
    if device_looks_virtual(device_name):
        out.append(f'Output is going to {device_name}, which looks like a '
                   f'virtual or routing device rather than headphones.')
    return out
