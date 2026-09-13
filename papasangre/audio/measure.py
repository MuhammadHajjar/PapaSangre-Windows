"""Measure what the binaural chain actually renders.

Uses OpenAL Soft's loopback device to render to memory instead of a sound card,
so the HRTF, the coordinate mapping and OpenAL's renderer can be checked
together without anyone having to listen.  Shared by ``tools/verify_spatial.py``
and the regression tests.
"""

from __future__ import annotations

import math
import os
from ctypes import c_float, c_int, c_uint, byref

import numpy as np

from ..util import paths
from . import openal as OA
from .engine import DISTANCE_SCALE, csl_to_openal, normalize_to_head

ROOT = paths.resource_root()
DEFAULT_HRTF_DIR = paths.hrtf_dir()
RATE = 44100


class LoopbackRenderer:
    """An OpenAL context that renders into a numpy array."""

    def __init__(self, hrtf_dir: str | None = None,
                 hrtf_name: str = 'papa_ircam_1050', rate: int = RATE):
        hrtf_dir = hrtf_dir or paths.hrtf_dir()
        conf = paths.config_path()
        OA.write_alsoft_config(hrtf_dir, conf)
        os.environ['ALSOFT_CONF'] = conf          # must precede the DLL load
        self.al = OA.OpenAL()
        self.rate = rate
        self.device = OA.loopback_device(self.al)
        if not self.device:
            raise OA.OpenALError('no loopback device')
        self.available = OA.list_hrtfs(self.al, self.device)
        attrs = [OA.ALC_FREQUENCY, rate,
                 OA.ALC_FORMAT_CHANNELS_SOFT, OA.ALC_STEREO_SOFT,
                 OA.ALC_FORMAT_TYPE_SOFT, OA.ALC_FLOAT_SOFT,
                 OA.ALC_HRTF_SOFT, OA.AL_TRUE]
        if hrtf_name in self.available:
            attrs += [OA.ALC_HRTF_ID_SOFT, self.available.index(hrtf_name)]
        attrs.append(0)
        arr = (c_int * len(attrs))(*attrs)
        self.ctx = self.al.alcCreateContext(self.device, arr)
        self.al.alcMakeContextCurrent(self.ctx)
        st = c_int(0)
        self.al.alcGetIntegerv(self.device, OA.ALC_HRTF_STATUS_SOFT, 1, byref(st))
        self.hrtf_status = OA.HRTF_STATUS.get(st.value, str(st.value))
        self.al.alListener3f(OA.AL_POSITION, 0.0, 0.0, 0.0)
        orient = (c_float * 6)(0.0, 0.0, -1.0, 0.0, 1.0, 0.0)
        self.al.alListenerfv(OA.AL_ORIENTATION, orient)
        self._click = self._make_click()

    def _make_click(self) -> int:
        click = np.zeros(2048, dtype=np.int16)
        click[8] = 32000
        bufs = (c_uint * 1)()
        self.al.alGenBuffers(1, bufs)
        raw = click.tobytes()
        self.al.alBufferData(bufs[0], OA.AL_FORMAT_MONO16, raw, len(raw), self.rate)
        self.al.check('click buffer')
        return bufs[0]

    def render_bearing(self, bearing_deg: float, radius_px: float = 200.0,
                       nframes: int = 4096,
                       head_orientation: float = 0.0) -> np.ndarray:
        al = self.al
        src = (c_uint * 1)()
        al.alGenSources(1, src)
        s = src[0]
        al.alSourcei(s, OA.AL_BUFFER, self._click)
        al.alSourcei(s, OA.AL_SOURCE_RELATIVE, OA.AL_TRUE)
        al.alSourcef(s, OA.AL_ROLLOFF_FACTOR, 0.0)   # direction only, no distance
        al.alSourcef(s, OA.AL_GAIN, 1.0)
        r = math.radians(bearing_deg)
        c = normalize_to_head(radius_px * math.cos(r), radius_px * math.sin(r),
                              0.0, 0.0, 0.0, 0.0, head_orientation,
                              DISTANCE_SCALE)
        al.alSource3f(s, OA.AL_POSITION, *csl_to_openal(*c))
        al.alSourcePlay(s)
        out = OA.render_samples(al, self.device, nframes, 2)
        data = np.ctypeslib.as_array(out).reshape(-1, 2).copy()
        al.alSourceStop(s)
        al.alDeleteSources(1, src)
        return data

    def close(self) -> None:
        self.al.alcMakeContextCurrent(None)
        self.al.alcDestroyContext(self.ctx)
        self.al.alcCloseDevice(self.device)


def interaural(data: np.ndarray) -> tuple[float, float]:
    """(ITD in samples, positive = left ear leads; ILD in dB, + = left louder)."""
    L, R = data[:, 0], data[:, 1]
    eL, eR = float(np.sum(L ** 2)), float(np.sum(R ** 2))
    ild = 10 * math.log10(eL / eR) if eR > 1e-20 else float('inf')
    n = len(L)
    corr = np.correlate(R, L, mode='full')
    lag = int(np.argmax(np.abs(corr))) - (n - 1)
    return float(lag), ild


BEARINGS = (0, 45, 90, 135, 180, 225, 270, 315)


def sweep(renderer: LoopbackRenderer, bearings=BEARINGS,
          radius_px: float = 200.0) -> list[tuple[float, float, float]]:
    """Render each bearing and return (bearing, ITD, ILD)."""
    rows = []
    for b in bearings:
        itd, ild = interaural(renderer.render_bearing(b, radius_px))
        rows.append((float(b), itd, ild))
    return rows


def check(rows) -> list[str]:
    """Return a list of physical-plausibility failures (empty means good).

    The median-plane tolerance is expressed relative to the peak lateral delay
    rather than as an absolute sample count: IRCAM 1050 is a real human subject
    and is not perfectly symmetric, and makemhr's minimum-phase-plus-delay model
    quantises the delay further.  What must hold is that front and back stay
    near the centre compared with a genuinely lateral source — a mirrored or
    ear-swapped set would show a full-sized delay there.
    """
    failures: list[str] = []
    lateral = max((abs(itd) for b, itd, _ in rows if b in (90.0, 270.0)),
                  default=0.0)
    for bearing, itd, ild in rows:
        if bearing in (0.0, 180.0):
            if abs(ild) > 3.0 or abs(itd) > 0.25 * lateral:
                failures.append(f'{bearing:g} deg should image centrally '
                                f'(ITD {itd:.1f}, ILD {ild:.2f}, '
                                f'lateral peak {lateral:.0f})')
        elif 0 < bearing < 180:
            if ild <= 0 or itd <= 0:
                failures.append(f'{bearing:g} deg should favour the left ear '
                                f'(ITD {itd:.1f}, ILD {ild:.2f})')
        else:
            if ild >= 0 or itd >= 0:
                failures.append(f'{bearing:g} deg should favour the right ear '
                                f'(ITD {itd:.1f}, ILD {ild:.2f})')
        if abs(itd) > 45:
            failures.append(f'{bearing:g} deg ITD {itd:.1f} samples exceeds '
                            f'any head-sized path difference')
    if lateral < 15:
        failures.append(f'peak lateral ITD only {lateral:.1f} samples — '
                        f'the HRTF is probably not being applied')
    return failures
