"""Decode the original ``.m4a`` assets straight from the game bundle.

The port ships the iOS audio untouched (see PORTING_STATUS.md, Phase B) and
decodes it with PyAV, which bundles FFmpeg's AAC decoder.  Output is verified
bit-identical to the FFmpeg command line decoder.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import av
import numpy as np


@dataclass
class Pcm:
    """Decoded audio ready to hand to OpenAL."""
    samples: np.ndarray          # int16, shape (frames, channels)
    sample_rate: int

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def duration(self) -> float:
        return self.frames / float(self.sample_rate)

    def tobytes(self) -> bytes:
        return self.samples.tobytes()


def to_mono(pcm: Pcm, policy: str = 'average') -> Pcm:
    """Collapse a multi-channel clip to one channel.

    A positioned sound *must* be mono: an HRTF renders one stream into two ears,
    and a stereo buffer bypasses spatialisation entirely.  Most of the original's
    positioned assets ship as stereo, so this runs on 69 of the 88 sounds the
    playlists mark ``spatialized``.

    ``policy`` is ``'average'`` (keeps the content of both channels; 49 of those
    69 are effectively dual-mono so it changes nothing, and the worst measured
    level change on the rest is -3.7 dB) or ``'first'`` (takes channel 0, which
    can never cancel but discards the other channel).  See PORTING_STATUS.md,
    open question 11.
    """
    if pcm.channels == 1:
        return pcm
    if policy == 'first':
        out = pcm.samples[:, :1]
    else:
        acc = pcm.samples.astype(np.int32).mean(axis=1)
        out = np.rint(acc).clip(-32768, 32767).astype(np.int16).reshape(-1, 1)
    return Pcm(np.ascontiguousarray(out), pcm.sample_rate)


def decode(path: str, mono: bool = False, mono_policy: str = 'average') -> Pcm:
    """Decode any file the bundled FFmpeg understands to interleaved int16.

    Set ``mono`` for sounds that will be spatialised.
    """
    container = av.open(path)
    try:
        stream = container.streams.audio[0]
        ctx = stream.codec_context
        layout = ctx.layout
        rate = ctx.sample_rate
        resampler = av.audio.resampler.AudioResampler(
            format='s16', layout=layout, rate=rate)
        parts: list[np.ndarray] = []
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                parts.append(out.to_ndarray().reshape(-1))
        # flush
        for out in resampler.resample(None):
            parts.append(out.to_ndarray().reshape(-1))
    finally:
        container.close()

    nch = layout.nb_channels
    flat = np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)
    if flat.size % nch:
        flat = flat[:flat.size - (flat.size % nch)]
    pcm = Pcm(flat.reshape(-1, nch), rate)
    return to_mono(pcm, mono_policy) if mono else pcm


def probe_duration(path: str) -> float:
    container = av.open(path)
    try:
        s = container.streams.audio[0]
        if s.duration is not None and s.time_base is not None:
            return float(s.duration * s.time_base)
        if container.duration is not None:
            return container.duration / 1_000_000.0
    finally:
        container.close()
    return 0.0
