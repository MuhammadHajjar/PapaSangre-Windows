"""Regression tests for level 1b (the turning puzzle) and level 2 (Soul Music).

Level 1b introduces the "face the sound" mechanic - the engine's shooting-range
test - and level 2 is the first level with walking *and* turning, chained
collectibles, and surfaces layered over the room.
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from papasangre.core.messages import MessageBus                   # noqa: E402
from papasangre.entities.agent import FACING_DOT_THRESHOLD        # noqa: E402
from papasangre.input.interpreter import (LEFT, RIGHT,            # noqa: E402
                                          MoveInterpretor)
from papasangre.world.level import Level                          # noqa: E402
from test_level import FakeBank                                   # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')


def _build(stem, sounds):
    bus = MessageBus()
    interp = MoveInterpretor(bus)
    bank = FakeBank(sounds, clock=lambda: bus.now)
    level = Level(bus, bank).load(os.path.join(EXPORTS, f'{stem}.json'), stem)
    return bus, interp, bank, level


# ---------------------------------------------- level 1b: turn to the voice
LEVEL1B_SOUNDS = [
    'FINAL_SWYE_Intro', 'Atmos_darkrumble_01', 'FINAL_SWYE_Win', 'clock_15sec',
    'churchbell_training', 'FINAL_SWYE_summoner_B', 'FINAL_PSS_imoverhere_all',
]


def build_1b():
    return _build('ps1_1b', LEVEL1B_SOUNDS)


def _reach_the_voice(bus, lv, t=0.5):
    """Advance to the point where the "I'm over here" voice is calling."""
    lv.start(0.0)
    lv.agent('FINAL_SWYE_Intro').sound.stop()
    bus.now = t
    lv.update(t)
    for _ in range(80):                     # the summoner is delayed 15 seconds
        t += 0.5
        bus.now = t
        lv.update(t)
        s = lv.agent('FINAL_SWYE_summoner_B')
        if s.active and s.sound is not None and s.sound.playing:
            s.sound.stop()
    return t


def _bearing_to(lv, agent):
    p = lv.player
    dx = agent.position[0] - p.position[0]
    dy = agent.position[1] - p.position[1]
    return math.degrees(math.atan2(dy, dx)) % 360


def test_level_1b_is_a_turning_puzzle_with_no_walking():
    bus, mi, bank, lv = build_1b()
    lv.start(0.0)
    lv.agent('FINAL_SWYE_Intro').sound.stop()
    bus.now = 0.5
    lv.update(0.5)
    assert mi.player_can_rotate, 'level 1b must let you turn'
    assert not mi.player_can_walk, 'level 1b never enables walking'


def test_the_voice_only_answers_when_you_face_it():
    """The facing cone is about +/-11.5 degrees (dot product 0.98)."""
    bus, mi, bank, lv = build_1b()
    t = _reach_the_voice(bus, lv)
    voice = lv.agent('FINAL_PSS_imoverhere_all')
    assert voice.active, 'the voice should be calling by now'
    bearing = _bearing_to(lv, voice)

    lv.player.rotate_to_fixed_rotation(math.radians(bearing + 30))
    t += 0.1
    bus.now = t
    lv.update(t)
    assert not voice.is_in_shooting_range
    assert not lv.shutting_down

    lv.player.rotate_to_fixed_rotation(math.radians(bearing))
    t += 0.1
    bus.now = t
    lv.update(t)
    assert voice.is_in_shooting_range
    for _ in range(20):
        t += 0.1
        bus.now = t
        lv.update(t)
    assert lv.agent('FINAL_SWYE_Win').active, 'facing the voice should win'
    assert lv.shutting_down


def test_the_facing_cone_is_the_recovered_width():
    bus, mi, bank, lv = build_1b()
    t = _reach_the_voice(bus, lv)
    voice = lv.agent('FINAL_PSS_imoverhere_all')
    bearing = _bearing_to(lv, voice)
    half = math.degrees(math.acos(FACING_DOT_THRESHOLD))
    assert 11.0 < half < 12.0, half

    # just inside the cone answers, just outside does not
    for offset, expected in ((half - 2.0, True), (half + 2.0, False)):
        voice._is_in_shooting_range = False
        lv.player.rotate_to_fixed_rotation(math.radians(bearing + offset))
        t += 0.1
        bus.now = t
        lv.update(t)
        assert voice.is_in_shooting_range is expected, (offset, expected)


def test_level_1b_leads_to_level_2():
    bus, mi, bank, lv = build_1b()
    t = _reach_the_voice(bus, lv)
    voice = lv.agent('FINAL_PSS_imoverhere_all')
    lv.player.rotate_to_fixed_rotation(math.radians(_bearing_to(lv, voice)))
    for _ in range(20):
        t += 0.1
        bus.now = t
        lv.update(t)
    win = lv.agent('FINAL_SWYE_Win')
    assert win.sound is not None
    assert win.sound.plays >= 1, 'the win narration should have started'
    # It ends on its own now, the way the engine's does, and **that ending is
    # what fires OnSoundEnd -> LoadLevelWithName**.  This used to stop the
    # sound by hand, because the fake never finished on its own - which meant
    # the chain between levels was only ever tested against a simulated end.
    for _ in range(6):
        t += 0.2
        bus.now = t
        lv.update(t)
    assert not win.sound.playing, 'the narration should have finished by now'
    assert lv.finished
    assert lv.next_level == 'ps1_2'


# --------------------------------------------------- level 2: Soul Music
LEVEL2_SOUNDS = [
    'FINAL_SoulMusic_Intro', 'atmos_stonepulselow_01', 'note_appear',
    'note_bone_01_dry_a_living', 'note_bone_01_dry_b_living',
    'FINAL_soulmusic_notecollect_1', 'FINAL_soulmusic_notecollect_2',
    'door_castle_appear', 'door_castle_living', 'FINAL_SoulMusic_Win',
    'music_badthingcoming_1', 'easteregg_rattlesnake', 'easteregg_flies',
    'easteregg_flies_away', 'FINAL_soulmusic_tripped_1',
    'FINAL_soulmusic_inactive_1', 'FINAL_soulmusic_inactive_2',
    'FINAL_soulmusic_inactive_3', 'FINAL_soulmusic_inactive_4',
    'foot_stone_s1_L_a', 'foot_stone_s1_R_a', 'foot_stone_trip',
]


def build_2():
    return _build('ps1_2', LEVEL2_SOUNDS)


def _start_2(bus, lv):
    lv.start(0.0)
    lv.agent('FINAL_SoulMusic_Intro').sound.stop()
    bus.now = 0.5
    lv.update(0.5)
    return 0.5


def _walk_towards(bus, mi, lv, target, t, limit=400, interval=0.5):
    p = lv.player
    foot = LEFT
    for _ in range(limit):
        dx = target.position[0] - p.position[0]
        dy = target.position[1] - p.position[1]
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += interval
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if getattr(target, 'collected', False) or lv.shutting_down:
            break
    return t


def test_level_2_has_bigger_steps_and_a_trip_sound():
    _bus, _mi, _bank, lv = build_2()
    _bank.played.clear()
    assert lv.player.pixels_per_step == 10.0        # twice level 1's stride
    assert lv.trip_sound == 'FINAL_soulmusic_tripped_1'
    # The Room's tripSound never reaches the player: playerMovedToPosition:
    # only ever copies a *Surface*'s.  It does not need to - trip: looks the
    # sound up with anySoundContaining:@"trip", which finds it anyway.
    assert lv.player.trip_sound == ''
    lv.player.trip()
    assert 'FINAL_soulmusic_tripped_1' in _bank.played, _bank.played
    assert len(lv.floors) == 2


def test_level_2_enables_both_walking_and_turning():
    bus, mi, bank, lv = build_2()
    _start_2(bus, lv)
    assert mi.player_can_walk and mi.player_can_rotate


def test_level_2_note_chain_runs_in_order():
    bus, mi, bank, lv = build_2()
    t = _start_2(bus, lv)
    note1, note2, ex = lv.agent('note1'), lv.agent('note2'), lv.agent('exit')
    assert note1.active and not note2.active and not ex.active

    t = _walk_towards(bus, mi, lv, note1, t)
    assert note1.was_collected
    note1.sound.stop()                     # its collect sting finishes
    t += 0.2
    bus.now = t
    lv.update(t)
    assert note2.active, 'note1 should hand over to note2'

    t = _walk_towards(bus, mi, lv, note2, t)
    assert note2.was_collected
    note2.sound.stop()
    t += 0.2
    bus.now = t
    lv.update(t)
    assert ex.active, 'note2 should summon the exit'

    t = _walk_towards(bus, mi, lv, ex, t)
    assert ex.was_collected
    assert lv.shutting_down
    ex.sound.stop()
    t += 0.2
    bus.now = t
    lv.update(t)
    assert lv.finished and lv.next_level == 'ps1_3'


def test_level_2_trip_lines_sound_when_crossed():
    """Two full-width strips at z = 2, each playing a sound on entry."""
    bus, mi, bank, lv = build_2()
    played = []
    bus.subscribe('PGE_MESSAGE_PlaySound',
                  lambda n, p: played.append(p.get('soundName')))
    t = _start_2(bus, lv)
    _walk_towards(bus, mi, lv, lv.agent('exit'), t, limit=400)
    assert 'music_badthingcoming_1' in played
    assert 'easteregg_rattlesnake' in played


def test_collecting_a_note_changes_the_nag_list():
    bus, mi, bank, lv = build_2()
    t = _start_2(bus, lv)
    before = list(lv.inactivity_sounds)
    _walk_towards(bus, mi, lv, lv.agent('note1'), t)
    assert lv.inactivity_sounds != before
    assert lv.inactivity_sounds[0] == 'FINAL_soulmusic_inactive_2'


def test_the_easter_egg_flies_are_present_and_collectable():
    bus, mi, bank, lv = build_2()
    t = _start_2(bus, lv)
    flies = lv.agent('flies')
    assert flies is not None and flies.active
    t = _walk_towards(bus, mi, lv, flies, t)
    assert flies.was_collected


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
