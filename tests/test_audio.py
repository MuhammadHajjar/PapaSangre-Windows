"""Regression tests for the audio layer (Phase C).

The listener transform is checked against the arithmetic recovered from
``-[S3DEngine normalizeToHeadPosition:]``, and the whole binaural chain is
checked by rendering through OpenAL Soft's loopback device and measuring the
result — so a broken HRTF, a flipped axis or a lost .mhr fails the suite
instead of quietly sounding wrong.
"""

import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.audio.engine import (                         # noqa: E402
    COINCIDENT_OFFSET, DISTANCE_SCALE, MASTER_GAIN, MAX_SPATIAL_GAIN,
    csl_to_openal, normalize_to_head)
from papasangre.audio.loader import decode                    # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
HRTF_MHR = os.path.join(ROOT, 'build', 'hrtf', 'papa_ircam_1050.mhr')


# ------------------------------------------------------- recovered constants
def test_recovered_constants():
    # -[PGELevel initSoundEngine] (Papa Sangre branch) and -[S3DEngine init]
    assert DISTANCE_SCALE == 0.008
    assert MAX_SPATIAL_GAIN == 100.0
    assert MASTER_GAIN == 1.0


# ------------------------------------------------------- listener transform
def test_source_at_head_is_nudged_aside():
    """normalizeToHeadPosition guards against a coincident source."""
    out = normalize_to_head(10.0, 10.0, 0.0, 10.0, 10.0, 0.0, 0.0)
    assert out[1] == COINCIDENT_OFFSET * DISTANCE_SCALE
    assert out[0] == 0.0


def test_forward_is_plus_x_in_csl_space():
    # listener at the origin facing 0 degrees, source 100 px along +x
    out = normalize_to_head(100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert abs(out[0] - 100.0 * DISTANCE_SCALE) < 1e-9
    assert abs(out[1]) < 1e-9


def test_left_is_plus_y_in_csl_space():
    out = normalize_to_head(0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert abs(out[0]) < 1e-6
    assert abs(out[1] - 100.0 * DISTANCE_SCALE) < 1e-9


def test_turning_rotates_the_world_the_other_way():
    """Facing 90 degrees, a source at world +y is straight ahead."""
    out = normalize_to_head(0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 90.0)
    assert abs(out[0] - 100.0 * DISTANCE_SCALE) < 1e-6   # now forward
    assert abs(out[1]) < 1e-6


def test_distance_scale_is_applied():
    out = normalize_to_head(125.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert abs(out[0] - 1.0) < 1e-9        # 125 px == 1 unit at scale 0.008


def test_axis_mapping_to_openal():
    # CSL +X forward -> OpenAL -Z ; CSL +Y left -> OpenAL -X ; +Z up -> +Y
    assert csl_to_openal(1.0, 0.0, 0.0) == (0.0, 0.0, -1.0)
    assert csl_to_openal(0.0, 1.0, 0.0) == (-1.0, 0.0, 0.0)
    assert csl_to_openal(0.0, 0.0, 1.0) == (0.0, 1.0, 0.0)


# ------------------------------------------------------- asset decoding
def test_decoded_audio_matches_the_original_bit_for_bit():
    """The port must not alter the shipped audio in any way."""
    import subprocess
    rel = os.path.join('ps1', 'spatialized', 'door_castle_living.m4a')
    path = os.path.join(BUNDLE, rel)
    pcm = decode(path)
    ref = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', path, '-f', 's16le', '-acodec',
         'pcm_s16le', '-'], capture_output=True, check=True).stdout
    got = pcm.samples.reshape(-1)
    exp = np.frombuffer(ref, dtype='<i2')
    assert got.shape == exp.shape
    assert np.array_equal(got, exp)
    assert pcm.sample_rate == 44100
    assert abs(pcm.duration - 4.806531) < 0.001


def test_monster_loops_are_mono_so_they_can_be_spatialised():
    pcm = decode(os.path.join(BUNDLE, 'ps1', 'monsters',
                              'monster_hog1_01_dry_chase.m4a'))
    assert pcm.channels == 1


# ------------------------------------------------------- rendered output
def test_recovered_hrtf_was_built():
    assert os.path.exists(HRTF_MHR), (
        'run tools/extract_hrtf.py then makemhr to build the HRTF')


def test_rendered_binaural_cues_are_physically_correct():
    """End-to-end: render through OpenAL and measure what comes out.

    Catches a lost .mhr, a flipped axis, swapped ears, or HRTF being bypassed.
    """
    from papasangre.audio.measure import LoopbackRenderer, check, sweep
    r = LoopbackRenderer()
    try:
        assert r.hrtf_status == 'enabled', f'HRTF status {r.hrtf_status}'
        assert 'papa_ircam_1050' in r.available, (
            f'the recovered HRTF is not installed; OpenAL offered {r.available}')
        rows = sweep(r)
        failures = check(rows)
        assert not failures, '; '.join(failures)
        lateral = max(abs(itd) for b, itd, _ in rows if b in (90.0, 270.0))
        # A human head gives roughly 0.6-0.8 ms of interaural delay at 90 deg.
        assert 0.5 < lateral / r.rate * 1000 < 1.0, (
            f'peak lateral ITD {lateral / r.rate * 1000:.2f} ms is not head-sized')
    finally:
        r.close()


# ---------------------------------------- real assets, not synthetic signals
#
# The synthetic-click sweep above passed while the game's own positioned audio
# played completely flat, because most of it ships as stereo and OpenAL only
# spatialises mono sources.  These tests use the actual shipped files.

SPATIAL_SAMPLES = [
    ('ps1/spatialized/door_castle_living.m4a', 2),    # stereo on disk
    ('ps1/spatialized/note_glass_01_dry_a_living.m4a', 2),   # widely decorrelated
    ('ps1/monsters/monster_hog1_01_dry_chase.m4a', 1),       # already mono
]


def test_spatialised_assets_are_forced_to_mono():
    """A stereo buffer bypasses HRTF entirely, so this must never regress."""
    from papasangre.audio.loader import decode as dec
    for rel, expect_src in SPATIAL_SAMPLES:
        path = os.path.join(BUNDLE, *rel.split('/'))
        assert dec(path).channels == expect_src, rel
        assert dec(path, mono=True).channels == 1, rel


def test_mono_downmix_preserves_length_and_level():
    from papasangre.audio.loader import decode as dec
    path = os.path.join(BUNDLE, 'ps1', 'spatialized', 'door_castle_living.m4a')
    stereo = dec(path)
    mono = dec(path, mono=True)
    assert mono.frames == stereo.frames
    a = stereo.samples.astype(np.float64).mean(axis=1)
    b = mono.samples.astype(np.float64).reshape(-1)
    assert np.max(np.abs(a - b)) <= 1.0        # rounding only


def test_real_game_audio_is_actually_spatialised():
    """Render the shipped assets and confirm the direction reaches the ears.

    Regression guard for the stereo-buffer bug: before the fix, the door gave
    identical interaural cues at 90 and 270 degrees - its position was ignored.
    """
    from ctypes import c_uint
    import math as _math
    from papasangre.audio import openal as OA
    from papasangre.audio.engine import (DISTANCE_SCALE, csl_to_openal,
                                         normalize_to_head)
    from papasangre.audio.loader import decode as dec
    from papasangre.audio.measure import LoopbackRenderer, interaural

    r = LoopbackRenderer()
    try:
        assert r.hrtf_status == 'enabled'
        al = r.al
        for rel, _ in SPATIAL_SAMPLES:
            path = os.path.join(BUNDLE, *rel.split('/'))
            pcm = dec(path, mono=True)
            buf = (c_uint * 1)()
            al.alGenBuffers(1, buf)
            raw = pcm.tobytes()
            al.alBufferData(buf[0], OA.AL_FORMAT_MONO16, raw, len(raw),
                            pcm.sample_rate)
            al.check('buffer')
            got = {}
            for bearing in (90, 270):
                src = (c_uint * 1)()
                al.alGenSources(1, src)
                s = src[0]
                al.alSourcei(s, OA.AL_BUFFER, buf[0])
                al.alSourcei(s, OA.AL_SOURCE_RELATIVE, OA.AL_TRUE)
                al.alSourcef(s, OA.AL_ROLLOFF_FACTOR, 0.0)
                rad = _math.radians(bearing)
                c = normalize_to_head(250 * _math.cos(rad), 250 * _math.sin(rad),
                                      0, 0, 0, 0, 0.0, DISTANCE_SCALE)
                al.alSource3f(s, OA.AL_POSITION, *csl_to_openal(*c))
                al.alSourcePlay(s)
                out = OA.render_samples(al, r.device, 22050, 2)
                data = np.ctypeslib.as_array(out).reshape(-1, 2).copy()
                got[bearing] = interaural(data)
                al.alSourceStop(s)
                al.alDeleteSources(1, src)

            itd90, ild90 = got[90]
            itd270, ild270 = got[270]
            assert itd90 > 10, f'{rel}: left bearing ITD only {itd90}'
            assert itd270 < -10, f'{rel}: right bearing ITD only {itd270}'
            assert ild90 > ild270, f'{rel}: level does not follow direction'
            # the decisive one: the two bearings must not render the same
            assert abs(itd90 - itd270) > 20, (
                f'{rel}: 90 and 270 degrees render almost identically '
                f'({itd90} vs {itd270}) - the source position is being ignored')
    finally:
        r.close()


# ------------------------------------- un-spatialised sound bypasses HRTF
def test_unspatialised_sound_passes_through_untouched():
    """The original never puts flat sound through a head-related filter.

    ``-[S3DSound setupPlain]`` builds an ordinary csl::Panner; only
    ``setupSpatialized`` builds the binaural one.  OpenAL Soft with HRTF on
    virtualises everything unless a source is marked AL_DIRECT_CHANNELS_SOFT,
    and that virtualisation squashed the game's wide stereo ambience from an
    inter-channel correlation of 0.011 to 0.879, flattened the deliberate
    left/right lean of the footstep samples, and cost up to 10 dB.
    """
    from ctypes import c_uint
    from papasangre.audio import openal as OA
    from papasangre.audio.loader import decode as dec
    from papasangre.audio.measure import LoopbackRenderer

    def stats(a):
        L, R = a[:, 0], a[:, 1]
        import math as _m
        bal = (10 * _m.log10(max((L ** 2).mean(), 1e-20))
               - 10 * _m.log10(max((R ** 2).mean(), 1e-20)))
        corr = float(np.corrcoef(L, R)[0, 1]) if L.std() > 0 and R.std() > 0 else 1.0
        return bal, corr

    r = LoopbackRenderer()
    try:
        al = r.al
        assert al.alIsExtensionPresent(b'AL_SOFT_direct_channels'),             'AL_SOFT_direct_channels is required to keep flat sound out of the HRTF'
        mode = (OA.AL_REMIX_UNMATCHED_SOFT
                if al.alIsExtensionPresent(b'AL_SOFT_direct_channels_remix')
                else OA.AL_TRUE)
        for rel in (('ps1', 'atmos', 'Atmos_darkrumble_01.m4a'),
                    ('ps1', 'footsteps', 'foot_stone_s1_L_a.m4a'),
                    ('ps1', 'footsteps', 'foot_stone_s1_R_a.m4a')):
            pcm = dec(os.path.join(BUNDLE, *rel))
            assert pcm.channels == 2
            n = pcm.frames
            src = pcm.samples.astype(np.float64) / 32768.0
            buf = (c_uint * 1)()
            al.alGenBuffers(1, buf)
            raw = pcm.tobytes()
            al.alBufferData(buf[0], OA.AL_FORMAT_STEREO16, raw, len(raw),
                            pcm.sample_rate)
            s = (c_uint * 1)()
            al.alGenSources(1, s)
            sid = s[0]
            al.alSourcei(sid, OA.AL_BUFFER, buf[0])
            al.alSourcei(sid, OA.AL_SOURCE_RELATIVE, OA.AL_TRUE)
            al.alSourcef(sid, OA.AL_ROLLOFF_FACTOR, 0.0)
            al.alSource3f(sid, OA.AL_POSITION, 0.0, 0.0, 0.0)
            al.alSourcei(sid, OA.AL_DIRECT_CHANNELS_SOFT, mode)
            al.alSourcePlay(sid)
            out = OA.render_samples(al, r.device, n, 2)
            d = np.ctypeslib.as_array(out).reshape(-1, 2).copy()
            al.alSourceStop(sid)
            al.alDeleteSources(1, s)

            sb, sc = stats(src)
            ob, oc = stats(d)
            name = rel[-1]
            assert abs(ob - sb) < 0.2, f'{name}: balance moved {sb:+.2f} -> {ob:+.2f}'
            assert abs(oc - sc) < 0.05, f'{name}: width changed {sc:.3f} -> {oc:.3f}'
    finally:
        r.close()


def test_footstep_banks_carry_their_own_left_right_lean():
    """The engine never pans footsteps; the samples themselves are placed."""
    from papasangre.audio.loader import decode as dec
    import math as _m
    left = dec(os.path.join(BUNDLE, 'ps1', 'footsteps', 'foot_stone_s1_L_a.m4a'))
    right = dec(os.path.join(BUNDLE, 'ps1', 'footsteps', 'foot_stone_s1_R_a.m4a'))

    def bal(p):
        a = p.samples.astype(np.float64)
        return (10 * _m.log10(max((a[:, 0] ** 2).mean(), 1e-20))
                - 10 * _m.log10(max((a[:, 1] ** 2).mean(), 1e-20)))

    assert bal(left) > 1.0, 'the left foot sample should lean left'
    assert bal(right) < -1.0, 'the right foot sample should lean right'


def test_spatialised_sources_are_not_direct_channelled():
    """3D sound must still reach the HRTF."""
    from papasangre.audio.engine import AudioEngine, SoundSpec
    from papasangre.audio import openal as OA
    eng = AudioEngine()
    eng.open()
    try:
        flat = eng.load(SoundSpec('flat', os.path.join(
            BUNDLE, 'ps1', 'atmos', 'Atmos_darkrumble_01.m4a'), spatialized=False))
        spatial = eng.load(SoundSpec('spatial', os.path.join(
            BUNDLE, 'ps1', 'spatialized', 'door_castle_living.m4a'),
            spatialized=True))
        flat.play()
        spatial.play()
        from ctypes import c_int, byref
        v = c_int(0)
        eng.al.alGetSourcei(flat.source, OA.AL_DIRECT_CHANNELS_SOFT, byref(v))
        assert v.value != OA.AL_FALSE, 'flat sound should bypass the HRTF'
        eng.al.alGetSourcei(spatial.source, OA.AL_DIRECT_CHANNELS_SOFT, byref(v))
        assert v.value == OA.AL_FALSE, 'spatial sound must go through the HRTF'
        flat.stop()
        spatial.stop()
    finally:
        eng.close()


# ------------------------------------------------- reverb (a divergence)
def test_the_original_has_exactly_one_reverb():
    """Guard on the values -[PGEngine init] actually leaves in place.

    S3DEngine's own init says 1.5 / 1.0 / 50 and is then overridden by
    PGEngine's 2.1 / 1.0 / 5; the roomSize setter clamps to [2.2, 2.3], so
    2.2 is what the engine runs.  The port used the S3DEngine row for a while
    and every level was drier and duller than the original.
    """
    from papasangre.audio.engine import (REVERB_DAMPENING, REVERB_ROOM_SIZE,
                                         REVERB_VOLUME)
    assert REVERB_ROOM_SIZE == 2.2
    assert REVERB_VOLUME == 1.0
    assert REVERB_DAMPENING == 5.0


def test_which_levels_count_as_outdoors():
    """The classification reads the ground, not a list of level names."""
    from papasangre.world.ambience import ground_family, is_outdoor
    assert is_outdoor(['foot_reeds', 'foot_sand-waterB', 'foot_stonepath'])
    assert is_outdoor(['foot_snow', 'foot_icethin'])
    assert is_outdoor(['foot_cornfield'])
    assert is_outdoor(['foot_field'])
    # one indoor floor is enough to make it a building
    assert not is_outdoor(['foot_guts', 'foot_stone'])
    assert not is_outdoor(['foot_reeds', 'foot_wood'])
    assert not is_outdoor(['foot_metalmelodicK'])
    # a level that names no ground at all is not outdoors (ps1_1b)
    assert not is_outdoor([])
    assert not is_outdoor([''])
    # the lettered variants collapse onto their stem
    assert ground_family('foot_reeds-waterD') == 'foot_reeds-water'
    assert ground_family('foot_metalmelodicP') == 'foot_metalmelodic'


def test_every_level_in_the_game_classifies():
    """No ground anywhere in the 27 maps is left unclassified."""
    import glob
    import json
    from papasangre.world.ambience import (INDOOR_GROUNDS, OUTDOOR_GROUNDS,
                                           ground_family, is_outdoor)
    known = INDOOR_GROUNDS | OUTDOOR_GROUNDS
    outdoors = set()
    for path in glob.glob(os.path.join(EXPORTS, 'ps1_*.json')):
        stem = os.path.basename(path)[:-5]
        d = json.load(open(path, encoding='utf-8', errors='replace'))
        prefixes = set()
        for layer in d.get('layers', []):
            if layer.get('name') == 'ToolBar':
                continue
            for o in layer.get('objects', []) or []:
                pref = (o.get('properties') or {}).get('footstepsPrefix')
                if pref:
                    prefixes.add(pref)
        for pref in prefixes:
            assert ground_family(pref) in known, f'{stem}: {pref} unclassified'
        if is_outdoor(prefixes):
            outdoors.add(stem)
    assert outdoors == {'ps1_8', 'ps1_9', 'ps1_10', 'ps1_11', 'ps1_12',
                        'ps1_19', 'ps1_20', 'ps1_22', 'ps1_23', 'ps1_25'}, outdoors


def test_the_engine_can_switch_profiles_and_it_changes_the_tail():
    """Not just that the call succeeds - that the reverb actually differs."""
    from papasangre.audio.engine import AudioEngine, SoundSpec
    snd = os.path.join(BUNDLE, 'ps1', 'footsteps', 'hitwall.m4a')

    def tail(profile):
        eng = AudioEngine()
        eng.open(loopback=True)
        try:
            if eng.reverb_slot is None:
                return None
            assert eng.set_reverb_profile(profile)
            s = eng.load(SoundSpec('t', snd, spatialized=True))
            s.send_to_reverb = True
            s.wet_gain = 1.0
            s.planar = (0.0, 40.0)
            s.play()
            frames, energy = 0, 0.0
            while frames < 44100 * 2:
                buf = eng.render(2048)
                if frames >= 22050:          # after the sound itself is done
                    energy += sum(v * v for v in buf)
                frames += len(buf) // 2
            return energy
        finally:
            eng.close()

    wet = tail('indoor')
    if wet is None:
        return                                # no EFX on this machine
    assert tail('outdoor') < wet * 0.5, 'outdoors should be much sparser'
    assert tail('dry') < wet * 0.25, 'dry should have almost no tail'


def test_a_level_picks_its_profile_from_its_ground():
    from papasangre.core.messages import MessageBus
    from papasangre.world.level import Level
    sys.path.insert(0, os.path.join(ROOT, 'tests'))
    from test_level import FakeBank                            # noqa: PLC0415
    for stem, expected in (('ps1_7', 'indoor'), ('ps1_8', 'outdoor')):
        lv = Level(MessageBus(), FakeBank([])).load(
            os.path.join(EXPORTS, f'{stem}.json'), stem)
        assert lv.reverb_profile == expected, f'{stem} got {lv.reverb_profile}'


def test_the_outdoor_choice_can_be_turned_down_to_dry():
    from papasangre.core.messages import MessageBus
    from papasangre.world.level import Level
    sys.path.insert(0, os.path.join(ROOT, 'tests'))
    from test_level import FakeBank                            # noqa: PLC0415
    lv = Level(MessageBus(), FakeBank([]))
    lv.outdoor_reverb = 'dry'
    lv.load(os.path.join(EXPORTS, 'ps1_8.json'), 'ps1_8')
    assert lv.reverb_profile == 'dry'


def test_the_audio_config_is_written_out_and_survives_being_broken():
    """Same discoverability trick as config/keys.json, and just as forgiving."""
    import json
    import tempfile
    from papasangre.world.ambience import configured_outdoor_profile
    d = tempfile.mkdtemp()
    path = os.path.join(d, 'audio.json')
    assert configured_outdoor_profile(path) == 'outdoor'
    assert os.path.exists(path), 'a missing config should write its defaults'
    for value, expected in (('dry', 'dry'), ('indoor', 'indoor'),
                            ('nonsense', 'outdoor')):
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'outdoorReverb': value}, fh)
        assert configured_outdoor_profile(path) == expected
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{ not json')
    assert configured_outdoor_profile(path) == 'outdoor',         'a corrupt config must never stop the game'


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


# ------------------------------------------------- the reverb send gain
class _RecordingAL:
    """Just enough OpenAL to see what the send was set to."""

    def __init__(self, filters=True):
        self.calls = []
        self._filters = filters
        self._next = 100

    def gen_filters(self, n=1):
        if not self._filters:
            raise RuntimeError('this driver has no EFX filters')
        out = list(range(self._next, self._next + n))
        self._next += n
        return out

    def filteri(self, flt, param, value):
        self.calls.append(('filteri', flt, param, value))

    def filterf(self, flt, param, value):
        self.calls.append(('filterf', flt, param, value))

    def alSource3i(self, src, param, a, b, c):
        self.calls.append(('send', src, param, a, b, c))


def _sound_with(al, wet, send=True):
    """A Sound wired to a recording AL, with a source already in hand."""
    import types                                                 # noqa: PLC0415
    from papasangre.audio.engine import Sound, SoundSpec         # noqa: PLC0415
    engine = types.SimpleNamespace(al=al, reverb_slot=7)
    s = Sound(engine, SoundSpec('x', 'x.m4a'), buffer_id=1, duration=1.0,
              channels=1)
    s.source = 42
    s.send_to_reverb = send
    s.wet_gain = wet
    return s


def test_a_sound_reaches_the_reverb_at_the_gain_it_asked_for():
    """Reported after 1.0.5: ps1_2's flies easter egg drowning in reverb.

    ``wetGain`` was stored and then ignored by ``_apply_send``, so everything
    routed to the reverb went in at OpenAL's default send gain of 1.0.  The
    flies ask for 0.05 - the driest mix in the game - and you walk right into
    them, so they were the clearest case of a fault the whole game had.
    """
    import papasangre.audio.openal as OA                         # noqa: PLC0415
    al = _RecordingAL()
    _sound_with(al, 0.05)
    gains = [c for c in al.calls if c[0] == 'filterf'
             and c[2] == OA.AL_LOWPASS_GAIN]
    assert gains, 'the send gain was never set'
    assert abs(gains[-1][3] - 0.05) < 1e-6, gains[-1]
    # and the filter, not FILTER_NULL, is what the send is given
    send = [c for c in al.calls if c[0] == 'send'][-1]
    assert send[3] == 7, 'should go to the reverb slot'
    assert send[5] != OA.AL_FILTER_NULL, 'sent without its gain filter'
    # the tone is untouched: only the level is scaled
    hf = [c for c in al.calls if c[0] == 'filterf'
          and c[2] == OA.AL_LOWPASS_GAINHF]
    assert hf and abs(hf[-1][3] - 1.0) < 1e-6


def test_the_wet_mixes_the_original_specifies_are_all_distinct():
    """0.05, 0.5 and 0.75 have to arrive as three different gains."""
    import papasangre.audio.openal as OA                         # noqa: PLC0415
    seen = []
    for wet in (0.05, 0.5, 0.75):
        al = _RecordingAL()
        _sound_with(al, wet)
        g = [c for c in al.calls if c[0] == 'filterf'
             and c[2] == OA.AL_LOWPASS_GAIN][-1][3]
        seen.append(round(g, 4))
    assert seen == [0.05, 0.5, 0.75], seen


def test_a_sound_not_sent_to_reverb_is_detached_from_the_slot():
    import papasangre.audio.openal as OA                         # noqa: PLC0415
    al = _RecordingAL()
    _sound_with(al, 0.5, send=False)
    send = [c for c in al.calls if c[0] == 'send'][-1]
    assert send[3] == 0 and send[5] == OA.AL_FILTER_NULL


def test_a_driver_with_no_filters_still_gets_its_reverb():
    """Too much reverb is a poor sound; no reverb is a missing one."""
    import papasangre.audio.openal as OA                         # noqa: PLC0415
    al = _RecordingAL(filters=False)
    _sound_with(al, 0.05)
    send = [c for c in al.calls if c[0] == 'send'][-1]
    assert send[3] == 7, 'it must still reach the reverb'
    assert send[5] == OA.AL_FILTER_NULL
