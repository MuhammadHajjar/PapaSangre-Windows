"""Level 5, "Hog Patrol" - the first level with a patrol route.

A single path runs straight down the middle of the room and the hog walks it,
end to end, for ever.  You have to time your crossing.

This is what `followPathWithName:` / `findNextPatrolPoint` were for, and the
level is the reason they had to be built: its hog's own ``OnLoad`` says
``FollowPathWithName:name=path1``, so without the path system it simply stands
still and the level has no obstacle at all.
"""

import glob
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from papasangre.assets.sexp import include_stem, parse_playlist    # noqa: E402
from papasangre.core.messages import MessageBus                    # noqa: E402
from papasangre.entities.monster import ATTACK, IDLE               # noqa: E402
from papasangre.input.interpreter import (LEFT, RIGHT,             # noqa: E402
                                          MoveInterpretor)
from papasangre.world.level import Level                           # noqa: E402
from test_level import FakeBank                                    # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
META = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')


def declared(stem, seen=None, out=None):
    seen = seen if seen is not None else set()
    out = out if out is not None else set()
    if stem in seen:
        return out
    seen.add(stem)
    m = glob.glob(os.path.join(META, f'{stem}.S3DPlayListModel*.sexp'))
    if not m:
        return out
    pl = parse_playlist(open(m[0], encoding='utf-8', errors='replace').read(), stem)
    out |= {s.name for s in pl.sounds}
    for inc in pl.includes:
        declared(include_stem(inc), seen, out)
    return out


def build():
    bus = MessageBus()
    mi = MoveInterpretor(bus)
    bank = FakeBank(sorted(declared('ps1_5')), clock=lambda: bus.now)
    lv = Level(bus, bank).load(os.path.join(EXPORTS, 'ps1_5.json'), 'ps1_5')
    return bus, mi, bank, lv


def start(bus, lv, t=1.0):
    lv.start(0.0)
    for a in lv.agents:
        if 'Intro' in a.name and a.sound is not None:
            a.sound.stop()
    bus.now = t
    lv.update(t)
    return t


def run(bus, lv, t, seconds, step=1.0 / 60.0):
    end = t + seconds
    while t < end:
        t += step
        bus.now = t
        lv.update(t)
    return t


# ---------------------------------------------------------------- loading
def test_the_path_loads_with_its_points_in_world_space():
    """Tiled gives polyline points relative to the object; the world transform
    is the same one every other position gets, Y negation included."""
    _bus, _mi, _bank, lv = build()
    assert 'path1' in lv.paths
    assert lv.paths['path1'] == [(0.0, 240.0), (0.0, -230.0)]
    assert lv.path_with_name('path1') is not None
    assert lv.path_with_name('nope') is None


def test_the_hog_takes_its_speeds_from_the_level_not_the_defaults():
    """`speed` is the patrol speed.  It survives because IDLE never overwrites
    it - only state 13 replaces speed with walkingSpeed."""
    _bus, _mi, _bank, lv = build()
    hog = lv.agent('hog1')
    assert hog.speed == 36.6
    assert hog.chase_speed == 21.6
    assert hog.walking_speed == 10.0       # untouched PGEEnemy init default


# ---------------------------------------------------------------- patrol
def test_on_load_starts_the_patrol():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    assert hog.has_path, 'OnLoad should have handed it path1'
    assert hog.path == lv.paths['path1']
    assert hog.wanted_patrol_point in lv.paths['path1']
    assert hog.state == IDLE


def test_the_hog_walks_the_whole_line_and_turns_round():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    lows, highs, aims = [], [], set()
    for _ in range(3600):                   # a minute of patrolling
        t = run(bus, lv, t, 1.0 / 60.0)
        lows.append(hog.position[1])
        highs.append(hog.position[1])
        aims.add(hog.wanted_patrol_point)
    assert min(lows) < -220.0, f'never reached the far end ({min(lows):.0f})'
    assert max(highs) > 230.0, f'never reached the near end ({max(highs):.0f})'
    assert aims == {(0.0, 240.0), (0.0, -230.0)}, 'it should aim at both ends'
    assert abs(hog.position[0]) < 1.0, 'and stay on the line'


def test_running_off_the_end_of_a_route_fires_on_path_end_and_wraps():
    """findNextPatrolPoint wraps to 0 rather than stopping, so a route loops."""
    from papasangre.assets.tiled import Trigger                    # noqa: PLC0415
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    fired = []
    hog.add_trigger(Trigger('OnPathEnd', 'PGE_MESSAGE_PlaySound', raw=''))
    bus.subscribe('PGE_MESSAGE_PlaySound', lambda n, p: fired.append(bus.now))
    run(bus, lv, t, 40.0)
    assert fired, 'reaching the last point should fire OnPathEnd'
    assert hog.path_current_point < len(hog.path), 'and wrap, not run off'


def test_being_alerted_suspends_the_patrol_and_it_resumes_afterwards():
    """findNextPatrolPoint only runs while idle, so an alerted enemy stops
    patrolling and picks the route back up once it settles."""
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    hog.distracted_time = 0.5
    t = run(bus, lv, t, 2.0)

    bus.now = t
    bus.post('PGE_MESSAGE_AlertAllEnemies',
             {'to': 'position', 'position': (100.0, 100.0)})
    t = run(bus, lv, t, 0.2)
    assert hog.state != IDLE, 'it should break off to investigate'

    # State 4 aims at wherever you are, and keeps re-aiming for its whole
    # one-second wind-up, so stand still and it walks into you.  Wait that
    # second out, then get clear: the goal is locked in by then and the hog
    # searches an empty patch of floor instead of eating the test.
    t = run(bus, lv, t, 1.2)
    lv.player.position = (lv.player.position[0], lv.player.position[1] - 900.0)
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})

    for _ in range(3000):
        t = run(bus, lv, t, 1.0 / 60.0)
        if hog.state == IDLE:
            break
    assert hog.state == IDLE, f'it never settled; {hog.state_name}'
    before = hog.position[1]
    t = run(bus, lv, t, 2.0)
    assert hog.position[1] != before, 'and it should be walking the route again'


def test_stop_following_path_halts_it():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    t = run(bus, lv, t, 2.0)
    bus.now = t
    bus.post('PGE_MESSAGE_StopFollowingPath', {'senderName': 'hog1'})
    lv.update(t)
    assert hog.orientation_vector == (0.0, 0.0)
    assert hog.path is None
    assert hog.state == 0
    where = hog.position
    t = run(bus, lv, t, 2.0)
    assert hog.position == where, 'a stopped patrol should not drift'


def test_a_patrol_message_for_someone_else_is_ignored():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    bus.now = t
    bus.post('PGE_MESSAGE_StopFollowingPath', {'senderName': 'somebody_else'})
    lv.update(t)
    assert hog.path is not None, 'it is addressed by senderName'


# ---------------------------------------------------------------- playing
def test_walking_into_the_patrolling_hog_fails_the_level():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog, p = lv.agent('hog1'), lv.player
    foot = LEFT
    for _ in range(400):
        dx, dy = hog.position[0] - p.position[0], hog.position[1] - p.position[1]
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += 0.4
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if lv.shutting_down:
            break
    assert lv.shutting_down, 'chasing a patrolling hog should end badly'
    assert hog.state == ATTACK
    fail = lv.agent('FINAL_HogPatrol_Fail')
    assert fail.active
    fail.sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_5'


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
    print(f'{len(fns) - failed} of {len(fns)} passed')
    raise SystemExit(1 if failed else 0)


def test_a_hog_that_loses_you_is_only_quiet_for_as_long_as_it_grunts():
    """Reported after 1.0.1: a hog that gives up "is as if it is not there".

    ``playSound:looping:`` returns the duration of what it started, and state 6
    hands that to ``setDistractedTime:`` (0x10001dc20).  So the search lasts
    exactly as long as the "not there" grunt: the grunt ends, the hog gives up
    in the same breath and its patrol loop comes straight back.  Reading the
    level's own ``distractedTime`` instead left it standing silent for the
    balance of that timer - 10 s here, and 90 s in ps1_15 - which is a hog
    deleting itself from the level.
    """
    from papasangre.entities.monster import AT_POSITION, IDLE     # noqa: PLC0415
    bus, _mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    grunt = bank.sounds[hog.not_there_sound].duration

    hog.change_state_to(AT_POSITION)
    t += 1.0 / 60.0
    bus.now = t
    lv.update(t)
    assert hog._current_sound_name == hog.not_there_sound
    assert abs(hog.distracted_time - grunt) < 1e-6, \
        'the search is the length of the grunt, not the map property'

    # still searching while the grunt is running
    t += grunt * 0.5
    bus.now = t
    lv.update(t)
    assert hog.state == AT_POSITION

    # and audible again as soon as it is over
    t += grunt * 0.6
    bus.now = t
    lv.update(t)
    assert hog.state == IDLE
    t += 1.0 / 60.0
    bus.now = t
    lv.update(t)
    assert hog._current_sound_name == hog.default_sound, \
        'the patrol loop has to come back, or the hog is silent and gone'


def test_an_enemy_sent_to_attack_borrows_its_chase_sound_and_keeps_coming():
    """0x10001d518: no attackSound means the chaseSound is copied into it.

    And that branch jumps over ``setDistractedTime:`` (0x10001d588), so an
    enemy on its way to attack never gives up on a timer the way a searching
    one does.
    """
    from papasangre.entities.monster import AT_POSITION           # noqa: PLC0415
    bus, _mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    assert not hog.attack_sound, 'ps1_5 gives its hog no attackSound'
    hog.should_attack_on_wanted_position = True
    hog.change_state_to(AT_POSITION)
    before = hog.distracted_time
    t += 1.0 / 60.0
    bus.now = t
    lv.update(t)
    assert hog.attack_sound == hog.chase_sound, 'it should have borrowed it'
    assert hog._current_sound_name == hog.chase_sound
    assert hog.sound.looping, 'playSound: is the looping one'
    assert hog.distracted_time == before, 'attacking does not start a timer'
