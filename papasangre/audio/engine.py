"""The port's equivalent of Papa Engine's ``S3D`` audio layer.

The original built, per sound, a CSL graph of
``CASoundFile -> Butter low-pass -> gain Mixer -> FanOut -> {dry -> binaural
panner, wet -> Stereoverb} -> master Mixer``, with spatialised sounds routed
through ``csl::Spatializer(kBinaural)`` and a ``csl::DistanceSimulator``.
OpenAL Soft expresses the same graph with a source, a direct low-pass filter,
an auxiliary reverb send, and device-level HRTF rendering.

Constants recovered from ``-[S3DEngine init]`` and
``-[PGELevel initSoundEngine]``:

===========================  ==========  ============================
value                        Papa Sangre  source
===========================  ==========  ============================
``distanceScale``            0.008       ``initSoundEngine`` (0.015625 for The Nightjar)
``maxSpatialGain``           100.0       ``-[S3DEngine init]``
``masterGain``               1.0         ``-[S3DEngine init]``
``reverbRoomSize``           2.2         ``-[PGEngine init]``, then clamped
``reverbVolume``             1.0         ``-[PGEngine init]``
``reverbDampening``          5.0         ``-[PGEngine init]``
===========================  ==========  ============================

Reverb
------
There is **one** reverb for the whole game and nothing ever changes it. No
playlist carries a reverb field, no level property names one, and the only two
writers of the three parameters are ``-[S3DEngine init]`` (1.5 / 1.0 / 50) and
``-[PGEngine init]`` (2.1 / 1.0 / 5), which runs after it and wins. So the
island in ps1_8 is reverberated exactly like the cellar in ps1_1 - that is the
original's behaviour, not a shortcut here.

The setters clamp, which is why the table above says 2.2 and not 2.1:

* ``setReverbRoomSize:`` clamps to **[2.2, 2.3]** (0x1002bb334 / 0x1002bb340),
  so the 2.1 that is passed in comes back up to 2.2 and the 1.5 from
  ``S3DEngine`` could never have applied either;
* ``setReverbDampening:`` clamps to [0, 100];
* ``setReverbVolume:`` clamps to [0, 8].

All three also return early when ``[self reverb]`` is nil, which is how
``disableReverb`` works. That is called from ``-[PGEngine init]`` behind a
hardware test whose log line reads "Disabling reverb for Papa Engine - because
hardware is less than 4th Gen", so on any machine this port will ever run on,
reverb is **on**.

Coordinate frames
-----------------
Level data is in Tiled pixels, centred on the room (see GAME_STRUCTURE.md §4).
``-[S3DEngine normalizeToHeadPosition:]`` turns a world point into a
listener-relative one::

    d     = source - headPosition
    a     = -headOrientation
    out.x = (d.x*cos(a) - d.y*sin(a)) * distanceScale
    out.y = (d.x*sin(a) + d.y*cos(a)) * distanceScale

with a guard that nudges a coincident source 5 cm aside.  CSL's Cartesian
convention (recovered from the HRTF direction loader, which builds
``x = cos(el)cos(az), y = sin(az)cos(el), z = sin(el)`` with IRCAM azimuth 90
being the left ear) is **+X forward, +Y left, +Z up**.

OpenAL uses **+X right, +Y up, -Z forward**, so the mapping is::

    al = (-csl.y, csl.z, -csl.x)

Because the engine does its own listener transform, every source is marked
``AL_SOURCE_RELATIVE`` and the OpenAL listener is left at the origin with the
identity orientation — exactly mirroring the original's structure.
"""

from __future__ import annotations

import ctypes
import math
import os
from ctypes import c_float, c_int, c_uint, byref
from dataclasses import dataclass

import numpy as np

from ..util import paths
from . import openal as OA
from .loader import Pcm, decode

ROOT = paths.resource_root()

# --- recovered defaults ---------------------------------------------------
DISTANCE_SCALE = 0.008          # -[PGELevel initSoundEngine], Papa Sangre branch
MAX_SPATIAL_GAIN = 100.0        # -[S3DEngine init]
MASTER_GAIN = 1.0               # -[S3DEngine init]
#: -[PGEngine init] overrides all three of S3DEngine's own init values; these
#: are what the game actually runs with.  See the Reverb note in the docstring.
REVERB_ROOM_SIZE = 2.2          # 2.1 passed in, clamped up to the 2.2 floor
REVERB_VOLUME = 1.0             # -[PGEngine init]
REVERB_DAMPENING = 5.0          # -[PGEngine init]  (S3DEngine's 50 never lands)

#: EFX reverb parameter sets.
#:
#: ``indoor`` is the original's single global reverb, mapped onto EFX.  It is
#: what Papa Sangre used on **every** level, the island included.
#:
#: ``outdoor`` and ``dry`` are **not in the original** - there is no indoor or
#: outdoor concept anywhere in that binary.  They were asked for because an
#: island that sounds like a cellar is hard to listen to, and they are recorded
#: as a deliberate divergence in DIVERGENCES.md.  ``outdoor`` is the standard
#: EAX "plain" character: sparse, low density, almost no early reflection, so
#: the tail reads as distance rather than as walls.
REVERB_PROFILES = {
    'indoor': {
        'DECAY_TIME': max(0.1, min(20.0, REVERB_ROOM_SIZE)),
        'GAIN': min(1.0, REVERB_VOLUME * 0.32),
        'GAINHF': max(0.0, min(1.0, 1.0 - REVERB_DAMPENING / 100.0)),
        'DIFFUSION': 1.0,
        'DENSITY': 1.0,
        'DECAY_HFRATIO': 1.0,
        'REFLECTIONS_GAIN': 0.05,
        'REFLECTIONS_DELAY': 0.007,
        'LATE_REVERB_GAIN': 1.26,
        'LATE_REVERB_DELAY': 0.011,
        'AIR_ABSORPTION_GAINHF': 0.994,
        'ROOM_ROLLOFF_FACTOR': 0.0,
        'DECAY_HFLIMIT': 1,
    },
    'outdoor': {
        'DECAY_TIME': 1.65,
        'GAIN': 0.3162,
        'GAINHF': 0.5012,
        'DIFFUSION': 0.5,
        'DENSITY': 0.2187,
        'DECAY_HFRATIO': 1.5,
        'REFLECTIONS_GAIN': 0.0562,
        'REFLECTIONS_DELAY': 0.179,
        'LATE_REVERB_GAIN': 0.1,
        'LATE_REVERB_DELAY': 0.1,
        'AIR_ABSORPTION_GAINHF': 0.994,
        'ROOM_ROLLOFF_FACTOR': 0.0,
        'DECAY_HFLIMIT': 1,
    },
    #: The fallback he asked for if a convincing outdoor reverb is not on:
    #: open air with no tail at all.
    'dry': {
        'DECAY_TIME': 0.1,
        'GAIN': 0.0,
        'GAINHF': 1.0,
        'DIFFUSION': 0.0,
        'DENSITY': 0.0,
        'DECAY_HFRATIO': 1.0,
        'REFLECTIONS_GAIN': 0.0,
        'REFLECTIONS_DELAY': 0.0,
        'LATE_REVERB_GAIN': 0.0,
        'LATE_REVERB_DELAY': 0.0,
        'AIR_ABSORPTION_GAINHF': 1.0,
        'ROOM_ROLLOFF_FACTOR': 0.0,
        'DECAY_HFLIMIT': 0,
    },
}
COINCIDENT_EPSILON = 0.00999999977   # -[S3DEngine normalizeToHeadPosition:]
COINCIDENT_OFFSET = 0.05             # ditto

#: Output volume. [N] - a port-side control with no original counterpart.
#: Papa Sangre is mixed with a wide dynamic range: narration peaks near -4 dBFS
#: while footsteps sit around -18 and the ambience near -24, and the engine
#: plays footsteps at half gain on top.  Scaling everything equally preserves
#: the mix the original authored - it is a volume knob, not a remix - and
#: OpenAL Soft's output limiter is on so raising it cannot clip.
#:
#: This was 2.5 while un-spatialised sound was still going through the HRTF and
#: losing 2.6 to 9.8 dB on the way.  With that fixed every sound reaches the
#: output at its source level, so only a small lift is wanted.
DEFAULT_MASTER_VOLUME = 1.4
MIN_MASTER_VOLUME = 0.25
MAX_MASTER_VOLUME = 8.0


def _volume_path() -> str:
    d = os.path.join(paths.writable_root(), 'config')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'audio.json')


def load_master_volume() -> float:
    try:
        import json
        with open(_volume_path(), encoding='utf-8') as fh:
            v = float(json.load(fh).get('master_volume', DEFAULT_MASTER_VOLUME))
        return max(MIN_MASTER_VOLUME, min(MAX_MASTER_VOLUME, v))
    except (OSError, ValueError, TypeError):
        return DEFAULT_MASTER_VOLUME


def save_master_volume(value: float) -> None:
    """Write the volume back, **keeping whatever else is in the file**.

    ``config/audio.json`` also holds the outdoor reverb choice, so this cannot
    just dump one key over the top of it.
    """
    import json
    path = _volume_path()
    stored = {}
    try:
        with open(path, encoding='utf-8') as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            stored = loaded
    except (OSError, ValueError):
        stored = {}
    stored['master_volume'] = round(float(value), 4)
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(stored, fh, indent=2, sort_keys=True)
    except OSError:
        pass


def normalize_to_head(px: float, py: float, pz: float,
                      hx: float, hy: float, hz: float,
                      orientation_deg: float,
                      distance_scale: float = DISTANCE_SCALE
                      ) -> tuple[float, float, float]:
    """Faithful port of ``-[S3DEngine normalizeToHeadPosition:]``."""
    dx = px - hx
    dy = py - hy
    dz = pz - hz
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    a = math.radians(-orientation_deg)
    sa, ca = math.sin(a), math.cos(a)
    y = COINCIDENT_OFFSET if dist < COINCIDENT_EPSILON else dy
    return ((dx * ca - y * sa) * distance_scale,
            (dx * sa + y * ca) * distance_scale,
            dz * distance_scale)


def csl_to_openal(x: float, y: float, z: float) -> tuple[float, float, float]:
    """CSL (+X front, +Y left, +Z up) -> OpenAL (+X right, +Y up, -Z front)."""
    return (-y, z, -x)


@dataclass
class SoundSpec:
    """What a playlist declares about one sound."""
    name: str
    path: str                    # absolute path to the audio file
    spatialized: bool = False
    preload: bool = False
    unload_on_stop: bool = False
    gain: float | None = None


class Sound:
    """One playable sound — the port's ``S3DSound``."""

    __slots__ = ('engine', 'spec', 'name', 'buffer', 'source', '_gain',
                 '_looping', '_spatialized', '_planar', 'duration',
                 '_send_to_reverb', '_wet_gain', '_channels', '_started',
                 '_send_filter')

    def __init__(self, engine: 'AudioEngine', spec: SoundSpec,
                 buffer_id: int, duration: float, channels: int):
        self.engine = engine
        self.spec = spec
        self.name = spec.name
        self.buffer = buffer_id
        self.duration = duration
        self._channels = channels
        self.source: int | None = None
        self._gain = 1.0 if spec.gain is None else spec.gain
        self._looping = False
        self._spatialized = spec.spatialized
        self._planar = (0.0, 0.0, 0.0)
        self._send_to_reverb = False
        self._wet_gain = 0.0
        self._started = False
        #: The lowpass filter on this source's auxiliary send.  OpenAL has no
        #: plain "send gain", so the only way to ask for less than all of a
        #: sound in the reverb is to put a filter on the send and turn its
        #: gain down.  Made once, on demand, and kept for the sound's life.
        self._send_filter: int | None = None

    # -- source lifetime ------------------------------------------------
    def _ensure_source(self) -> int:
        if self.source is None:
            self.source = self.engine._acquire_source()
            al = self.engine.al
            al.alSourcei(self.source, OA.AL_BUFFER, self.buffer)
            al.alSourcei(self.source, OA.AL_SOURCE_RELATIVE, OA.AL_TRUE)
            al.alSourcef(self.source, OA.AL_REFERENCE_DISTANCE,
                         self.engine.reference_distance)
            al.alSourcef(self.source, OA.AL_ROLLOFF_FACTOR,
                         self.engine.rolloff_factor if self._spatialized else 0.0)
            al.alSourcef(self.source, OA.AL_MAX_DISTANCE,
                         self.engine.max_distance)
            self._apply_direct_channels()
            self._apply_gain()
            self._apply_position()
            al.alSourcei(self.source, OA.AL_LOOPING,
                         OA.AL_TRUE if self._looping else OA.AL_FALSE)
        return self.source

    def _release_source(self) -> None:
        if self.source is not None:
            self.engine._release_source(self.source)
            self.source = None

    # -- properties -----------------------------------------------------
    @property
    def gain(self) -> float:
        return self._gain

    @gain.setter
    def gain(self, v: float) -> None:
        self._gain = float(v)
        self._apply_gain()

    def _apply_gain(self) -> None:
        if self.source is not None:
            self.engine.al.alSourcef(self.source, OA.AL_GAIN, self._gain)

    @property
    def looping(self) -> bool:
        return self._looping

    @looping.setter
    def looping(self, v: bool) -> None:
        self._looping = bool(v)
        if self.source is not None:
            self.engine.al.alSourcei(self.source, OA.AL_LOOPING,
                                     OA.AL_TRUE if v else OA.AL_FALSE)

    @property
    def spatialized(self) -> bool:
        return self._spatialized

    @spatialized.setter
    def spatialized(self, v: bool) -> None:
        self._spatialized = bool(v)
        if self.source is not None:
            self.engine.al.alSourcef(
                self.source, OA.AL_ROLLOFF_FACTOR,
                self.engine.rolloff_factor if v else 0.0)
            self._apply_direct_channels()
            self._apply_position()

    def _apply_direct_channels(self) -> None:
        """Keep un-spatialised sound out of the HRTF entirely.

        The original has two separate paths.  ``-[S3DSound setupSpatialized]``
        builds a binaural spatialiser; ``setupPlain`` builds an ordinary
        ``csl::Panner`` and mixes straight to the output.  Only the first is
        ever convolved with head-related filters.

        OpenAL Soft, with HRTF switched on, virtualises *everything* - a stereo
        source becomes a pair of virtual loudspeakers convolved with the HRIRs.
        Measured on the shipped assets, that collapsed the ambience from an
        inter-channel correlation of 0.011 to 0.879 (a wide stereo bed squashed
        almost to mono), flattened the deliberate 1.4 dB left/right lean that
        distinguishes the left and right footstep samples to 0.01 dB, cost about
        10 dB of level, and coloured everything with a head that is not yours.

        ``AL_DIRECT_CHANNELS_SOFT`` restores the original's split: an
        un-spatialised source is mixed to the output channels untouched, while
        3D sources still get the recovered HRTF.  ``AL_REMIX_UNMATCHED_SOFT`` is
        used rather than plain ``AL_TRUE`` so that a *mono* un-spatialised sound
        is spread across both channels instead of being dropped.
        """
        if self.source is None:
            return
        mode = (OA.AL_FALSE if self._spatialized
                else self.engine.direct_channels_mode)
        self.engine.al.alSourcei(self.source, OA.AL_DIRECT_CHANNELS_SOFT, mode)

    @property
    def planar(self) -> tuple[float, float, float]:
        return self._planar

    @planar.setter
    def planar(self, p) -> None:
        """World position in Tiled pixels (x, y[, z])."""
        if len(p) == 2:
            p = (p[0], p[1], 0.0)
        self._planar = (float(p[0]), float(p[1]), float(p[2]))
        self._apply_position()

    def _apply_position(self) -> None:
        if self.source is None:
            return
        if not self._spatialized:
            self.engine.al.alSource3f(self.source, OA.AL_POSITION, 0.0, 0.0, 0.0)
            return
        e = self.engine
        c = normalize_to_head(*self._planar, *e.head_position,
                              e.head_orientation, e.distance_scale)
        x, y, z = csl_to_openal(*c)
        e.al.alSource3f(self.source, OA.AL_POSITION, x, y, z)

    @property
    def send_to_reverb(self) -> bool:
        return self._send_to_reverb

    @send_to_reverb.setter
    def send_to_reverb(self, v: bool) -> None:
        self._send_to_reverb = bool(v)
        self._apply_send()

    @property
    def wet_gain(self) -> float:
        return self._wet_gain

    @wet_gain.setter
    def wet_gain(self, v: float) -> None:
        self._wet_gain = float(v)
        self._apply_send()

    def _ensure_send_filter(self) -> int | None:
        """A lowpass filter to scale this source's reverb send, or None.

        None means the driver would not give us one, which is possible on old
        or minimal OpenAL implementations.  The caller then sends at full gain
        rather than not at all: too much reverb is a poor sound, no reverb is
        a missing one.
        """
        if self._send_filter is not None:
            return self._send_filter
        try:
            flt = self.engine.al.gen_filters(1)[0]
            self.engine.al.filteri(flt, OA.AL_FILTER_TYPE, OA.AL_FILTER_LOWPASS)
        except Exception:                                    # noqa: BLE001
            return None
        self._send_filter = flt
        return flt

    def _apply_send(self) -> None:
        """Route this source to the reverb, **at the gain it asked for**.

        The gain is the part that was missing.  ``wetGain`` was stored and then
        thrown away here, so every sound that went to the reverb went in at
        OpenAL's default send gain of 1.0 - the whole game at full wet, and
        every per-sound mix the original specifies (0.05 for a collectible's
        loop, 0.5 for a footstep, 0.75 for the shuffle) inert.  Reported as
        ps1_2's flies easter egg drowning in room reverb: it asks for the
        driest mix in the game, 0.05, and you walk right into it.

        ``AL_LOWPASS_GAINHF`` stays at 1.0 so this only scales the level and
        does not colour what reaches the reverb.
        """
        if self.source is None or self.engine.reverb_slot is None:
            return
        al = self.engine.al
        if not self._send_to_reverb:
            al.alSource3i(self.source, OA.AL_AUXILIARY_SEND_FILTER,
                          0, 0, OA.AL_FILTER_NULL)
            return
        flt = self._ensure_send_filter()
        if flt is None:
            al.alSource3i(self.source, OA.AL_AUXILIARY_SEND_FILTER,
                          self.engine.reverb_slot, 0, OA.AL_FILTER_NULL)
            return
        al.filterf(flt, OA.AL_LOWPASS_GAIN,
                   max(0.0, min(1.0, self._wet_gain)))
        al.filterf(flt, OA.AL_LOWPASS_GAINHF, 1.0)
        al.alSource3i(self.source, OA.AL_AUXILIARY_SEND_FILTER,
                      self.engine.reverb_slot, 0, flt)

    # -- transport ------------------------------------------------------
    @property
    def playing(self) -> bool:
        if self.source is None:
            return False
        st = c_int(0)
        self.engine.al.alGetSourcei(self.source, OA.AL_SOURCE_STATE, byref(st))
        return st.value == OA.AL_PLAYING

    @property
    def paused(self) -> bool:
        if self.source is None:
            return False
        st = c_int(0)
        self.engine.al.alGetSourcei(self.source, OA.AL_SOURCE_STATE, byref(st))
        return st.value == OA.AL_PAUSED

    @property
    def offset(self) -> float:
        """Playback position in seconds."""
        if self.source is None:
            return 0.0
        v = c_float(0.0)
        self.engine.al.alGetSourcef(self.source, OA.AL_SEC_OFFSET, byref(v))
        return v.value

    def play(self) -> None:
        s = self._ensure_source()
        self._apply_send()
        self.engine.al.alSourcePlay(s)
        self._started = True

    def stop(self) -> None:
        if self.source is not None:
            self.engine.al.alSourceStop(self.source)
            self._release_source()
        self._started = False

    def pause(self) -> None:
        if self.source is not None:
            self.engine.al.alSourcePause(self.source)

    def resume(self) -> None:
        if self.source is not None:
            self.engine.al.alSourcePlay(self.source)

    def __repr__(self) -> str:
        return (f'<Sound {self.name!r} {self.duration:.2f}s '
                f'{"3D" if self._spatialized else "flat"}>')


class AudioEngine:
    """Device, context, listener state and the sound cache."""

    def __init__(self, hrtf_dir: str | None = None, dll_path: str | None = None,
                 sample_rate: int = 44100, hrtf_name: str = 'papa_ircam_1050',
                 period_size: int = 512, want_reverb: bool = True):
        self.hrtf_dir = hrtf_dir or paths.hrtf_dir()
        self.hrtf_name = hrtf_name
        self.sample_rate = sample_rate
        self.period_size = period_size
        self.want_reverb = want_reverb

        # OpenAL Soft reads its configuration once, when the library
        # initialises.  The config must therefore be written and ALSOFT_CONF
        # set *before* the DLL is loaded, or the custom HRTF is never found
        # and the device silently falls back to the built-in one.
        conf = paths.config_path()
        OA.write_alsoft_config(self.hrtf_dir, conf, period_size=self.period_size)
        os.environ['ALSOFT_CONF'] = conf

        self.al = OA.OpenAL(dll_path)
        self.device = None
        self.loopback = False
        self.context = None
        self.hrtf_status = 'not opened'
        self.reverb_slot: int | None = None
        self._effect: int | None = None
        self.reverb_profile = 'indoor'

        # listener, in Tiled pixels / degrees, matching the original
        self.head_position = (0.0, 0.0, 0.0)
        self.head_orientation = 0.0
        self.distance_scale = DISTANCE_SCALE
        self.max_spatial_gain = MAX_SPATIAL_GAIN
        #: The engine's own master gain (recovered as 1.0), times the player's
        #: volume setting.
        self.master_gain = MASTER_GAIN
        self.master_volume = load_master_volume()

        # OpenAL distance model parameters (see PORTING_STATUS open question 9).
        #
        # These are **port-side**: CSL's `DistanceSimulator` is the original's
        # attenuator and its methods are stripped from the binary, so its curve
        # is not recoverable.  What is recoverable is every sound's own gain,
        # and those are honoured untouched - the shape of the falloff is the
        # only thing chosen here.
        #
        # `reference_distance` was 1.0, which combined with a distance scale of
        # 0.008 means **nothing within 125 px attenuated at all**.  Every
        # spatialised source sat pinned at its full gain across most of a room,
        # so a beacon (gain 1.0) ran 6 dB above your own footsteps (0.5) no
        # matter how close or far it was, and the mix ran into the ceiling.
        # 0.5 puts the flat near field at ~62 px and lets the falloff work over
        # the rest of the room; a beacon is still clearly audible from the far
        # wall, just no longer the loudest thing in the game.
        self.reference_distance = 0.5
        self.rolloff_factor = 1.0
        self.max_distance = 1000.0

        #: How a stereo asset is collapsed for spatialised playback.
        #: 'average' keeps both channels' content, 'first' takes channel 0.
        self.mono_policy = 'average'

        #: Set on every un-spatialised source so it bypasses HRTF entirely.
        #: Resolved in open() once we know which extensions the driver has.
        self.direct_channels_mode = OA.AL_TRUE

        self._buffers: dict[tuple[str, bool], tuple[int, float, int]] = {}
        self._free_sources: list[int] = []
        self._all_sources: list[int] = []

    # ------------------------------------------------------------------
    def open(self, require_hrtf: bool = True,
             loopback: bool = False) -> 'AudioEngine':
        """Open the sound card, or a loopback device for offline rendering.

        ``loopback=True`` renders into memory instead of playing, which is how
        a scripted run of the game can be captured to a file and listened to -
        the only way to check "is this sound actually in the output" without
        sitting at the machine.  Pair it with :meth:`render`.
        """
        al = self.al
        self.loopback = loopback
        self.device = (OA.loopback_device(al) if loopback
                       else al.alcOpenDevice(None))
        if not self.device:
            raise OA.OpenALError('could not open an OpenAL device')

        hrtf_index = self._find_hrtf()
        if hrtf_index is None and require_hrtf:
            raise OA.OpenALError(
                f'the recovered HRTF {self.hrtf_name!r} was not found by '
                f'OpenAL Soft (it offered {self.available_hrtfs}). '
                f'Check that {self.hrtf_dir} contains {self.hrtf_name}.mhr — '
                f'run tools/extract_hrtf.py then makemhr. Falling back to the '
                f'built-in HRTF would not reproduce the original spatial sound.')
        attrs = [OA.ALC_FREQUENCY, self.sample_rate,
                 OA.ALC_HRTF_SOFT, OA.AL_TRUE,
                 OA.ALC_MONO_SOURCES, 128,
                 OA.ALC_STEREO_SOURCES, 32]
        if loopback:
            attrs += [OA.ALC_FORMAT_CHANNELS_SOFT, OA.ALC_STEREO_SOFT,
                      OA.ALC_FORMAT_TYPE_SOFT, OA.ALC_FLOAT_SOFT]
        if hrtf_index is not None:
            attrs += [OA.ALC_HRTF_ID_SOFT, hrtf_index]
        attrs.append(0)
        arr = (c_int * len(attrs))(*attrs)

        self.context = al.alcCreateContext(self.device, arr)
        if not self.context:
            raise OA.OpenALError('could not create an OpenAL context')
        al.alcMakeContextCurrent(self.context)

        st = c_int(0)
        al.alcGetIntegerv(self.device, OA.ALC_HRTF_STATUS_SOFT, 1, byref(st))
        self.hrtf_status = OA.HRTF_STATUS.get(st.value, str(st.value))
        name = al.alcGetString(self.device, OA.ALC_ALL_DEVICES_SPECIFIER)
        self.device_name = name.decode(errors='replace') if name else '(unknown)'

        # AL_SOFT_direct_channels_remix adds AL_REMIX_UNMATCHED_SOFT, which
        # keeps a mono un-spatialised sound audible instead of dropping it.
        if al.alIsExtensionPresent(b'AL_SOFT_direct_channels_remix'):
            self.direct_channels_mode = OA.AL_REMIX_UNMATCHED_SOFT
        elif al.alIsExtensionPresent(b'AL_SOFT_direct_channels'):
            self.direct_channels_mode = OA.AL_TRUE
        else:
            self.direct_channels_mode = OA.AL_FALSE

        al.alDistanceModel(OA.AL_INVERSE_DISTANCE_CLAMPED)
        al.alListener3f(OA.AL_POSITION, 0.0, 0.0, 0.0)
        orient = (c_float * 6)(0.0, 0.0, -1.0, 0.0, 1.0, 0.0)
        al.alListenerfv(OA.AL_ORIENTATION, orient)
        self._apply_master_volume()
        al.check('after context setup')

        if self.want_reverb:
            self._setup_reverb()
        return self

    # ------------------------------------------------------------- volume
    def _apply_master_volume(self) -> None:
        if self.context:
            self.al.alListenerf(OA.AL_GAIN,
                                self.master_gain * self.master_volume)

    def set_master_volume(self, value: float, save: bool = True) -> float:
        self.master_volume = max(MIN_MASTER_VOLUME,
                                 min(MAX_MASTER_VOLUME, float(value)))
        self._apply_master_volume()
        if save:
            save_master_volume(self.master_volume)
        return self.master_volume

    def adjust_master_volume(self, db: float) -> float:
        """Nudge the volume by a number of decibels."""
        return self.set_master_volume(self.master_volume * (10.0 ** (db / 20.0)))

    @property
    def master_volume_db(self) -> float:
        return 20.0 * math.log10(max(self.master_volume, 1e-6))

    def _find_hrtf(self) -> int | None:
        names = OA.list_hrtfs(self.al, self.device)
        self.available_hrtfs = names
        for i, n in enumerate(names):
            if n == self.hrtf_name:
                return i
        return None

    def _apply_reverb_profile(self, eff: int, profile: dict) -> None:
        """Write one profile's parameters onto an existing EFX reverb effect."""
        al = self.al
        for key, value in profile.items():
            enum = getattr(OA, f'AL_REVERB_{key}', None)
            if enum is None:
                continue
            if key == 'DECAY_HFLIMIT':
                al.effecti(eff, enum, int(value))
            else:
                al.effectf(eff, enum, float(value))

    def set_reverb_profile(self, name: str) -> bool:
        """Switch the single reverb slot to a named profile.

        ``indoor`` is the original's, and is what every level got on iOS.
        ``outdoor`` and ``dry`` are **deliberate additions** for the open-air
        levels - see DIVERGENCES.md.  Returns False when there is no reverb to
        configure, which is the normal case in a test or on a device without
        EFX, so callers can ignore the result.
        """
        profile = REVERB_PROFILES.get(name)
        if profile is None or self._effect is None or self.reverb_slot is None:
            return False
        try:
            self._apply_reverb_profile(self._effect, profile)
            # The slot caches the effect's state, so it has to be re-attached
            # for edited parameters to take.
            al = self.al
            al.aux_sloti(self.reverb_slot, OA.AL_EFFECTSLOT_EFFECT, self._effect)
            al.check(f'reverb profile {name}')
        except OA.OpenALError:
            return False
        self.reverb_profile = name
        return True

    def _setup_reverb(self) -> None:
        al = self.al
        if not al.alcIsExtensionPresent(self.device, b'ALC_EXT_EFX'):
            self.want_reverb = False
            return
        try:
            eff = al.gen_effects(1)[0]
            al.effecti(eff, OA.AL_EFFECT_TYPE, OA.AL_EFFECT_REVERB)
            self._apply_reverb_profile(eff, REVERB_PROFILES['indoor'])
            slot = al.gen_aux_slots(1)[0]
            al.aux_sloti(slot, OA.AL_EFFECTSLOT_EFFECT, eff)
            al.aux_slotf(slot, OA.AL_EFFECTSLOT_GAIN, 1.0)
            al.check('reverb setup')
            self._effect, self.reverb_slot = eff, slot
            self.reverb_profile = 'indoor'
        except OA.OpenALError:
            self.want_reverb = False
            self.reverb_slot = None

    def render(self, nframes: int):
        """Pull `nframes` of stereo float32 out of a loopback device."""
        if not getattr(self, 'loopback', False):
            raise OA.OpenALError('render() needs open(loopback=True)')
        return OA.render_samples(self.al, self.device, nframes)

    def close(self) -> None:
        al = self.al
        if self._all_sources:
            arr = (c_uint * len(self._all_sources))(*self._all_sources)
            al.alSourceStop(self._all_sources[0])
            al.alDeleteSources(len(self._all_sources), arr)
            self._all_sources.clear()
            self._free_sources.clear()
        for key, (buf, _, _) in list(self._buffers.items()):
            arr = (c_uint * 1)(buf)
            al.alDeleteBuffers(1, arr)
        self._buffers.clear()
        if self.context:
            al.alcMakeContextCurrent(None)
            al.alcDestroyContext(self.context)
            self.context = None
        if self.device:
            al.alcCloseDevice(self.device)
            self.device = None

    def __enter__(self) -> 'AudioEngine':
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _acquire_source(self) -> int:
        if self._free_sources:
            return self._free_sources.pop()
        arr = (c_uint * 1)()
        self.al.alGenSources(1, arr)
        self.al.check('alGenSources')
        self._all_sources.append(arr[0])
        return arr[0]

    def _release_source(self, src: int) -> None:
        self.al.alSourcei(src, OA.AL_BUFFER, 0)
        self._free_sources.append(src)

    # ------------------------------------------------------------------
    def load(self, spec: SoundSpec) -> Sound:
        """Decode (once) and wrap a declared sound.

        A spatialised sound is forced to mono.  OpenAL — like the binaural
        panner the original used — only applies a head-related transfer
        function to a single-channel source; a stereo buffer is routed straight
        to the two output channels and its position is ignored completely.  Most
        of the original's positioned assets ship as stereo, so without this the
        game's directional audio silently plays flat.
        """
        key = (spec.path, bool(spec.spatialized))
        entry = self._buffers.get(key)
        if entry is None:
            pcm: Pcm = decode(spec.path, mono=spec.spatialized,
                              mono_policy=self.mono_policy)
            arr = (c_uint * 1)()
            self.al.alGenBuffers(1, arr)
            fmt = OA.AL_FORMAT_MONO16 if pcm.channels == 1 else OA.AL_FORMAT_STEREO16
            raw = pcm.tobytes()
            self.al.alBufferData(arr[0], fmt, raw, len(raw), pcm.sample_rate)
            self.al.check(f'alBufferData for {spec.name}')
            entry = (arr[0], pcm.duration, pcm.channels)
            self._buffers[key] = entry
        buf, dur, ch = entry
        if spec.spatialized and ch != 1:
            raise OA.OpenALError(
                f'{spec.name!r} is marked spatialized but ended up with {ch} '
                f'channels; OpenAL would ignore its position')
        return Sound(self, spec, buf, dur, ch)

    def set_listener(self, position, orientation_deg: float) -> None:
        """Move the head; every live spatial source is re-projected."""
        if len(position) == 2:
            position = (position[0], position[1], 0.0)
        self.head_position = (float(position[0]), float(position[1]),
                              float(position[2]))
        self.head_orientation = float(orientation_deg)

    def update_positions(self, sounds) -> None:
        for s in sounds:
            if s.source is not None and s.spatialized:
                s._apply_position()
