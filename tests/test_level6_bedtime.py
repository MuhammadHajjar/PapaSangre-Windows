"""Level 6, "Bedtime" - two sleeping hogs, and the first real chase.

Every earlier level either leaves its hog asleep (ps1_3) or alerts it to a
*place* (ps1_4, `to=position`), which sends it to investigate a noise.  Here the
bone strip guarding the exit fires ``AlertAllEnemies:to=player``, and that is
the branch that puts an enemy into ``CHASE_PLAYER``.  So ps1_6 is the first
level in the game where something actually comes after you, and the first to
exercise states 2 and 3 outside a unit test.

The shape of it: two notes lie west with a hog asleep between them, a second
hog sleeps in the middle, and the exit sits behind a strip of bones down the
east wall.  You cannot reach the door without stepping on the bones, and the
moment you do, both hogs wake up and run at you.
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
from papasangre.entities.monster import (ATTACK, CHASE_PLAYER,     # noqa: E402
                                         IDLE)
from papasangre.input.interpreter import (LEFT, RIGHT,             # noqa: E402
                                          MoveInterpretor)
from papasangre.world.level import Level                           # noqa: E402
from test_level import FakeBank                                    # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
META = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')

NOTE1 = (-130.0, 140.0)
NOTE2 = (-50.0, 140.0)
EXIT = (210.0, 10.0)
#: hog1 sits squarely between the two notes, so the way across is round the top.
ROUND_HOG1 = (-90.0, 200.0)
#: far enough east to be on the bones, far enough north to miss hog2.
ONTO_THE_BONES = (110.0, 170.0)


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
    bank = FakeBank(sorted(declared('ps1_6')), clock=lambda: bus.now)
    lv = Level(bus, bank).load(os.path.join(EXPORTS, 'ps1_6.json'), 'ps1_6')
    return bus, mi, bank, lv


def start(bus, lv, t=1.0):
    lv.start(0.0)
    lv.agent('FINAL_Bedtime_Intro').sound.stop()
    bus.now = t
    lv.update(t)
    return t


def walk_to(bus, mi, lv, goal, t, limit=300, interval=0.45):
    p = lv.player
    foot = LEFT
    for _ in range(limit):
        dx, dy = goal[0] - p.position[0], goal[1] - p.position[1]
        if math.hypot(dx, dy) < 12.0:
            return t, True
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += interval
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        for a in lv.agents:
            if getattr(a, '_phase', None) == 'collect' and a.sound is not None:
                a.sound.stop()
        if lv.shutting_down:
            return t, False
    return t, False


# ---------------------------------------------------------------- loading
def test_level_6_builds_completely():
    _bus, _mi, _bank, lv = build()
    assert lv.rect == (-240.0, -240.0, 480.0, 480.0)
    assert lv.player.position == (-220.0, 10.0)
    assert lv.player.pixels_per_step == 10.0
    assert {a.name for a in lv.agents} == {
        'FINAL_Bedtime_Intro', 'atmos_stonepulselow_01', 'note1', 'note2',
        'exit', 'FINAL_Bedtime_Fail', 'hog1', 'hog2', 'atmos_stonedripping_01'}
    assert len(lv.floors) == 1


def test_two_hogs_each_with_their_own_voice_and_speeds():
    """The first level with more than one monster, and they are not the same."""
    _bus, _mi, bank, lv = build()
    h1, h2 = lv.agent('hog1'), lv.agent('hog2')
    assert h1.speed == 50.8 and h1.chase_speed == 33.3
    assert h2.speed == 5.0 and h2.chase_speed == 26.6
    assert h1.default_sound == 'monster_hog1_01_dry_still'
    assert h2.default_sound == 'monster_hog2_01_dry_still'
    for h in (h1, h2):
        for name in (h.default_sound, h.chase_sound, h.aware_sound,
                     h.not_there_sound):
            assert name in bank.sounds, f'{h.name} wants {name}'


def test_the_bones_are_a_strip_down_the_east_wall_in_front_of_the_exit():
    _bus, _mi, _bank, lv = build()
    strip = lv.floors[0]
    assert strip.footsteps_prefix == 'foot_bone'
    assert strip.z == 2
    x, y, w, h = strip.rect
    assert w == 150.0 and h == 480.0, 'a tall narrow band'
    assert x <= EXIT[0] <= x + w, 'and the exit is inside it'
    assert not (x <= lv.player.position[0] <= x + w), 'you start outside it'


def test_the_alert_is_to_the_player_not_to_a_position():
    """This is what makes ps1_6 different from ps1_4."""
    from papasangre.assets.tiled import load_level                 # noqa: PLC0415
    data = load_level(os.path.join(EXPORTS, 'ps1_6.json'), 'ps1_6')
    alerts = [t for o in data.objects for t in o.triggers
              if 'Alert' in t.notification_name]
    assert alerts, 'the level should alert its enemies'
    assert all(t.parameters.get('to') == 'player' for t in alerts), \
        'to=player is the branch that starts a chase'


# --------------------------------------------------------------- playing
def test_the_hogs_sleep_until_you_touch_the_bones():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    h1, h2 = lv.agent('hog1'), lv.agent('hog2')
    assert h1.active and h2.active
    assert h1.state == IDLE and h2.state == IDLE

    t, ok = walk_to(bus, mi, lv, NOTE1, t)
    assert ok, 'the first note is a clear walk'
    assert h1.state == IDLE and h2.state == IDLE, 'nothing has woken them yet'
    assert lv.player.footsteps_prefix == 'foot_stone'


def test_stepping_on_the_bones_sets_both_hogs_chasing_you():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    h1, h2 = lv.agent('hog1'), lv.agent('hog2')
    t, _ = walk_to(bus, mi, lv, NOTE1, t)
    t, _ = walk_to(bus, mi, lv, ROUND_HOG1, t)
    t, _ = walk_to(bus, mi, lv, NOTE2, t)
    assert lv.agent('note2').was_collected, 'both notes should be in hand'

    t, _ = walk_to(bus, mi, lv, ONTO_THE_BONES, t)
    assert lv.player.footsteps_prefix == 'foot_bone', 'you are on the bones'
    assert h1.state == CHASE_PLAYER, f'hog1 is {h1.state_name}'
    assert h2.state == CHASE_PLAYER, f'hog2 is {h2.state_name}'
    assert h1.speed == h1.chase_speed, 'and running at its chase speed'
    assert h1.sound.name == 'monster_hog1_01_dry_chase'
    assert h2.sound.name == 'monster_hog2_01_dry_chase'

    # a chase closes the distance, which is the whole tension of the level
    d1 = math.dist(h1.position, lv.player.position)
    for _ in range(120):
        t += 1.0 / 60.0
        bus.now = t
        lv.update(t)
    closed = d1 - math.dist(h1.position, lv.player.position)
    assert closed > 20.0, f'stood still for 2 s and it only gained {closed:.0f}px'


def test_the_note_chain_runs_and_the_exit_leads_to_level_7():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    for goal, name in ((NOTE1, 'note1'), (ROUND_HOG1, None), (NOTE2, 'note2'),
                       (ONTO_THE_BONES, None), (EXIT, 'exit')):
        t, _ = walk_to(bus, mi, lv, goal, t)
        if name:
            assert lv.agent(name).was_collected, f'{name} was not collected'
        if lv.shutting_down:
            break
    assert lv.shutting_down
    lv.agent('exit').sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_7'


def test_being_caught_fails_the_level_back_to_itself():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    h1 = lv.agent('hog1')
    t, _ = walk_to(bus, mi, lv, h1.position, t)
    assert lv.shutting_down
    assert h1.state == ATTACK
    fail = lv.agent('FINAL_Bedtime_Fail')
    assert fail.active
    fail.sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_6'


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
