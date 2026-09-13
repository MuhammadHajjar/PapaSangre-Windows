"""Minimal ctypes binding for OpenAL Soft, including HRTF and EFX.

Only what the port actually needs is bound.  The DLL shipped in ``vendor/openal``
is loaded explicitly so the game never depends on a system-wide OpenAL.

The original engine built, per sound, a CSL graph of
``file -> low-pass -> gain -> fan-out -> {dry -> binaural panner, wet -> reverb}``.
OpenAL Soft expresses the same thing with a source, a direct low-pass filter,
an auxiliary send to a reverb effect slot, and HRTF rendering on the device —
so the bindings below cover sources, buffers, the listener, ``ALC_SOFT_HRTF``
and ``ALC_EXT_EFX``.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import (POINTER, c_char_p, c_float, c_int, c_uint, c_void_p,
                    c_size_t)

from ..util import paths

ROOT = paths.resource_root()
DEFAULT_DLL = paths.openal_dll()

# ---------------------------------------------------------------- constants
AL_NONE = 0
AL_FALSE = 0
AL_TRUE = 1

AL_SOURCE_RELATIVE = 0x0202
AL_PITCH = 0x1003
AL_POSITION = 0x1004
AL_DIRECTION = 0x1005
AL_VELOCITY = 0x1006
AL_LOOPING = 0x1007
AL_BUFFER = 0x1009
AL_GAIN = 0x100A
AL_MIN_GAIN = 0x100D
AL_MAX_GAIN = 0x100E
AL_ORIENTATION = 0x100F
AL_SOURCE_STATE = 0x1010
AL_INITIAL = 0x1011
AL_PLAYING = 0x1012
AL_PAUSED = 0x1013
AL_STOPPED = 0x1014
AL_BUFFERS_QUEUED = 0x1015
AL_BUFFERS_PROCESSED = 0x1016
AL_SEC_OFFSET = 0x1024
AL_SAMPLE_OFFSET = 0x1025
AL_BYTE_OFFSET = 0x1026
AL_SOURCE_TYPE = 0x1027
AL_REFERENCE_DISTANCE = 0x1020
AL_ROLLOFF_FACTOR = 0x1021
AL_CONE_OUTER_GAIN = 0x1022
AL_MAX_DISTANCE = 0x1023

AL_FORMAT_MONO8 = 0x1100
AL_FORMAT_MONO16 = 0x1101
AL_FORMAT_STEREO8 = 0x1102
AL_FORMAT_STEREO16 = 0x1103

AL_FREQUENCY = 0x2001
AL_BITS = 0x2002
AL_CHANNELS = 0x2003
AL_SIZE = 0x2004

AL_NO_ERROR = 0
AL_VENDOR = 0xB001
AL_VERSION = 0xB002
AL_RENDERER = 0xB003
AL_EXTENSIONS = 0xB004

AL_DISTANCE_MODEL = 0xD000
AL_INVERSE_DISTANCE = 0xD001
AL_INVERSE_DISTANCE_CLAMPED = 0xD002
AL_LINEAR_DISTANCE = 0xD003
AL_LINEAR_DISTANCE_CLAMPED = 0xD004
AL_EXPONENT_DISTANCE = 0xD005
AL_EXPONENT_DISTANCE_CLAMPED = 0xD006

ALC_FREQUENCY = 0x1007
ALC_REFRESH = 0x1008
ALC_SYNC = 0x1009
ALC_MONO_SOURCES = 0x1010
ALC_STEREO_SOURCES = 0x1011
ALC_ALL_DEVICES_SPECIFIER = 0x1013

# ALC_SOFT_HRTF
ALC_HRTF_SOFT = 0x1992
ALC_HRTF_STATUS_SOFT = 0x1993
ALC_NUM_HRTF_SPECIFIERS_SOFT = 0x1994
ALC_HRTF_SPECIFIER_SOFT = 0x1995
ALC_HRTF_ID_SOFT = 0x1996
ALC_DONT_CARE_SOFT = 0x0002
HRTF_STATUS = {
    0x0000: 'disabled', 0x0001: 'enabled',
    0x0002: 'denied (device)', 0x0003: 'denied (unsupported format)',
    0x0004: 'headphones detected', 0x0005: 'unsupported',
}

# AL_SOFT_direct_channels / AL_SOFT_direct_channels_remix
# A source with this set bypasses all panning and virtualisation and mixes its
# channels straight to the matching output channels.  This is how a stereo
# sound can be left alone while 3D sources still get HRTF.
AL_DIRECT_CHANNELS_SOFT = 0x1033
AL_DROP_UNMATCHED_SOFT = 0x0000
AL_REMIX_UNMATCHED_SOFT = 0x0001

# AL_SOFT_source_spatialize
AL_SOURCE_SPATIALIZE_SOFT = 0x1214
AL_AUTO_SOFT = 0x0002

# ALC_SOFT_loopback — renders to a buffer instead of a sound card, which lets
# the test suite measure what the HRTF chain actually produces.
ALC_FORMAT_CHANNELS_SOFT = 0x1990
ALC_FORMAT_TYPE_SOFT = 0x1991
ALC_MONO_SOFT = 0x1500
ALC_STEREO_SOFT = 0x1501
ALC_QUAD_SOFT = 0x1503
ALC_BYTE_SOFT = 0x1400
ALC_UNSIGNED_BYTE_SOFT = 0x1401
ALC_SHORT_SOFT = 0x1402
ALC_UNSIGNED_SHORT_SOFT = 0x1403
ALC_INT_SOFT = 0x1404
ALC_UNSIGNED_INT_SOFT = 0x1405
ALC_FLOAT_SOFT = 0x1406

# ALC_EXT_EFX
ALC_EFX_MAJOR_VERSION = 0x20001
ALC_EFX_MINOR_VERSION = 0x20002
ALC_MAX_AUXILIARY_SENDS = 0x20003

AL_DIRECT_FILTER = 0x20005
AL_AUXILIARY_SEND_FILTER = 0x20006
AL_AIR_ABSORPTION_FACTOR = 0x20007
AL_ROOM_ROLLOFF_FACTOR = 0x20008
AL_CONE_OUTER_GAINHF = 0x20009
AL_DIRECT_FILTER_GAINHF_AUTO = 0x2000A
AL_AUXILIARY_SEND_FILTER_GAIN_AUTO = 0x2000B
AL_AUXILIARY_SEND_FILTER_GAINHF_AUTO = 0x2000C

AL_EFFECT_TYPE = 0x8001
AL_EFFECT_NULL = 0x0000
AL_EFFECT_REVERB = 0x0001
AL_EFFECT_EAXREVERB = 0x8000

AL_REVERB_DENSITY = 0x0001
AL_REVERB_DIFFUSION = 0x0002
AL_REVERB_GAIN = 0x0003
AL_REVERB_GAINHF = 0x0004
AL_REVERB_DECAY_TIME = 0x0005
AL_REVERB_DECAY_HFRATIO = 0x0006
AL_REVERB_REFLECTIONS_GAIN = 0x0007
AL_REVERB_REFLECTIONS_DELAY = 0x0008
AL_REVERB_LATE_REVERB_GAIN = 0x0009
AL_REVERB_LATE_REVERB_DELAY = 0x000A
AL_REVERB_AIR_ABSORPTION_GAINHF = 0x000B
AL_REVERB_ROOM_ROLLOFF_FACTOR = 0x000C
AL_REVERB_DECAY_HFLIMIT = 0x000D

AL_FILTER_TYPE = 0x8001
AL_FILTER_NULL = 0x0000
AL_FILTER_LOWPASS = 0x0001
AL_LOWPASS_GAIN = 0x0001
AL_LOWPASS_GAINHF = 0x0002

AL_EFFECTSLOT_EFFECT = 0x0001
AL_EFFECTSLOT_GAIN = 0x0002
AL_EFFECTSLOT_AUXILIARY_SEND_AUTO = 0x0003


class OpenALError(RuntimeError):
    pass


class OpenAL:
    """Loaded OpenAL Soft library plus the extension entry points we use."""

    def __init__(self, dll_path: str | None = None):
        self.path = dll_path or DEFAULT_DLL
        if not os.path.exists(self.path):
            raise OpenALError(f'OpenAL Soft not found at {self.path}')
        # Make sure the DLL's own directory is searched for its dependencies.
        if hasattr(os, 'add_dll_directory') and sys.platform == 'win32':
            try:
                os.add_dll_directory(os.path.dirname(self.path))
            except OSError:
                pass
        self.lib = ctypes.CDLL(self.path)
        self._declare()
        self._efx: dict[str, ctypes._CFuncPtr] = {}

    # ------------------------------------------------------------------
    def _declare(self) -> None:
        L = self.lib
        sig = [
            ('alcOpenDevice', c_void_p, [c_char_p]),
            ('alcCloseDevice', c_int, [c_void_p]),
            ('alcCreateContext', c_void_p, [c_void_p, POINTER(c_int)]),
            ('alcMakeContextCurrent', c_int, [c_void_p]),
            ('alcDestroyContext', None, [c_void_p]),
            ('alcGetError', c_int, [c_void_p]),
            ('alcGetString', c_char_p, [c_void_p, c_int]),
            ('alcGetIntegerv', None, [c_void_p, c_int, c_int, POINTER(c_int)]),
            ('alcIsExtensionPresent', c_int, [c_void_p, c_char_p]),

            ('alGetError', c_int, []),
            ('alGetString', c_char_p, [c_int]),
            ('alIsExtensionPresent', c_int, [c_char_p]),
            ('alGetProcAddress', c_void_p, [c_char_p]),
            ('alDistanceModel', None, [c_int]),
            ('alDopplerFactor', None, [c_float]),
            ('alSpeedOfSound', None, [c_float]),

            ('alGenBuffers', None, [c_int, POINTER(c_uint)]),
            ('alDeleteBuffers', None, [c_int, POINTER(c_uint)]),
            ('alBufferData', None, [c_uint, c_int, c_void_p, c_int, c_int]),
            ('alGetBufferi', None, [c_uint, c_int, POINTER(c_int)]),

            ('alGenSources', None, [c_int, POINTER(c_uint)]),
            ('alDeleteSources', None, [c_int, POINTER(c_uint)]),
            ('alSourcei', None, [c_uint, c_int, c_int]),
            ('alSource3i', None, [c_uint, c_int, c_int, c_int, c_int]),
            ('alSourcef', None, [c_uint, c_int, c_float]),
            ('alSource3f', None, [c_uint, c_int, c_float, c_float, c_float]),
            ('alGetSourcei', None, [c_uint, c_int, POINTER(c_int)]),
            ('alGetSourcef', None, [c_uint, c_int, POINTER(c_float)]),
            ('alSourcePlay', None, [c_uint]),
            ('alSourceStop', None, [c_uint]),
            ('alSourcePause', None, [c_uint]),
            ('alSourceRewind', None, [c_uint]),
            ('alSourceQueueBuffers', None, [c_uint, c_int, POINTER(c_uint)]),
            ('alSourceUnqueueBuffers', None, [c_uint, c_int, POINTER(c_uint)]),

            ('alListenerf', None, [c_int, c_float]),
            ('alListener3f', None, [c_int, c_float, c_float, c_float]),
            ('alListenerfv', None, [c_int, POINTER(c_float)]),
        ]
        for name, restype, argtypes in sig:
            fn = getattr(L, name)
            fn.restype = restype
            fn.argtypes = argtypes
            setattr(self, name, fn)

    # ------------------------------------------------------------------
    def check(self, where: str = '') -> None:
        e = self.alGetError()
        if e != AL_NO_ERROR:
            names = {0xA001: 'INVALID_NAME', 0xA002: 'INVALID_ENUM',
                     0xA003: 'INVALID_VALUE', 0xA004: 'INVALID_OPERATION',
                     0xA005: 'OUT_OF_MEMORY'}
            raise OpenALError(f'AL error {names.get(e, hex(e))} {where}')

    def efx(self, name: str, restype, argtypes):
        """Resolve and cache an EFX entry point."""
        fn = self._efx.get(name)
        if fn is None:
            addr = self.alGetProcAddress(name.encode())
            if not addr:
                raise OpenALError(f'EFX entry point {name} unavailable')
            fn = ctypes.CFUNCTYPE(restype, *argtypes)(addr)
            self._efx[name] = fn
        return fn

    # convenience wrappers for the EFX calls the engine uses
    def gen_effects(self, n: int = 1) -> list[int]:
        arr = (c_uint * n)()
        self.efx('alGenEffects', None, [c_int, POINTER(c_uint)])(n, arr)
        return list(arr)

    def effecti(self, eff: int, param: int, value: int) -> None:
        self.efx('alEffecti', None, [c_uint, c_int, c_int])(eff, param, value)

    def effectf(self, eff: int, param: int, value: float) -> None:
        self.efx('alEffectf', None, [c_uint, c_int, c_float])(eff, param, value)

    def gen_aux_slots(self, n: int = 1) -> list[int]:
        arr = (c_uint * n)()
        self.efx('alGenAuxiliaryEffectSlots', None,
                 [c_int, POINTER(c_uint)])(n, arr)
        return list(arr)

    def aux_sloti(self, slot: int, param: int, value: int) -> None:
        self.efx('alAuxiliaryEffectSloti', None,
                 [c_uint, c_int, c_int])(slot, param, value)

    def aux_slotf(self, slot: int, param: int, value: float) -> None:
        self.efx('alAuxiliaryEffectSlotf', None,
                 [c_uint, c_int, c_float])(slot, param, value)

    def gen_filters(self, n: int = 1) -> list[int]:
        arr = (c_uint * n)()
        self.efx('alGenFilters', None, [c_int, POINTER(c_uint)])(n, arr)
        return list(arr)

    def filteri(self, flt: int, param: int, value: int) -> None:
        self.efx('alFilteri', None, [c_uint, c_int, c_int])(flt, param, value)

    def filterf(self, flt: int, param: int, value: float) -> None:
        self.efx('alFilterf', None, [c_uint, c_int, c_float])(flt, param, value)


# ---------------------------------------------------------------- config
def write_alsoft_config(hrtf_dir: str, path: str, default_hrtf: str | None = None,
                        period_size: int = 512, periods: int = 3) -> str:
    """Write an alsoft.ini that makes our own .mhr discoverable.

    OpenAL Soft reads the file named by ``ALSOFT_CONF``; pointing it at a file
    we generate keeps the game self-contained and leaves the user's own OpenAL
    configuration untouched.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        '# Generated by Papa Sangre (Windows port). Do not edit;',
        '# regenerate with papasangre.audio.openal.write_alsoft_config().',
        '[general]',
        # 'hrtf = true' is deprecated in OpenAL Soft 1.24+; stereo-encoding
        # is the current spelling.  Both are written so older builds still work.
        'stereo-encoding = hrtf',
        'hrtf = true',
        f'hrtf-paths = {hrtf_dir}',
        f'period_size = {period_size}',
        f'periods = {periods}',
        # Catches peaks when the master gain is raised, instead of hard-clipping.
        'output-limiter = true',
        'dither = true',
    ]
    if default_hrtf:
        lines.append(f'default-hrtf = {default_hrtf}')
    lines.append('')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))
    return path


def loopback_device(al: OpenAL, name: bytes | None = None):
    fn = ctypes.CFUNCTYPE(c_void_p, c_char_p)(
        al.alGetProcAddress(b'alcLoopbackOpenDeviceSOFT'))
    if not fn:
        raise OpenALError('ALC_SOFT_loopback unavailable')
    return fn(name)


def render_samples(al: OpenAL, device, nframes: int, channels: int = 2):
    """Render `nframes` of float32 output from a loopback device."""
    fn = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_int)(
        al.alGetProcAddress(b'alcRenderSamplesSOFT'))
    if not fn:
        raise OpenALError('alcRenderSamplesSOFT unavailable')
    buf = (c_float * (nframes * channels))()
    fn(device, buf, nframes)
    return buf


def list_hrtfs(al: OpenAL, device) -> list[str]:
    n = c_int(0)
    al.alcGetIntegerv(device, ALC_NUM_HRTF_SPECIFIERS_SOFT, 1, ctypes.byref(n))
    fn = ctypes.CFUNCTYPE(c_char_p, c_void_p, c_int, c_size_t)(
        al.alGetProcAddress(b'alcGetStringiSOFT'))
    out = []
    for i in range(n.value):
        s = fn(device, ALC_HRTF_SPECIFIER_SOFT, i)
        out.append(s.decode() if s else '')
    return out
