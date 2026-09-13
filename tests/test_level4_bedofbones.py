"""Level 4, "Bed of Bones" - the first level where the hog actually hunts you.

Levels 1-3 never alert an enemy.  Here the floor does it: a band of bones lies
across the room between you and the notes, and stepping on it fires
``AlertAllEnemies:to=position``.  So this is the first level that exercises the
enemy's alerted states (4 -> 5 -> 6 -> 13) rather than leaving the hog asleep.
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
from papasangre.entities.monster import (ALERT_POSITION,           # noqa: E402
                                         AT_POSITION, GO_TO_POSITION,
                                         IDLE, RETURNING)
from papasangre.input.interpreter import (LEFT, RIGHT,             # noqa: E402
                                          MoveInterpretor)
from papasangre.world.level import Level                           # noqa: E402
from test_level import FakeBank                                    # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
META = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')

NOTE1, NOTE2, EXIT = (80.0, 40.0), (-41.0, 160.0), (10.0, 301.0)


def declared(stem, seen=None, out=None):
    """Every sound the level's playlist offers, includes and all."""
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
    bank = FakeBank(sorted(declared('ps1_4')))
    lv = Level(bus, bank).load(os.path.join(EXPORTS, 'ps1_4.json'), 'ps1_4')
    return bus, mi, bank, lv


def start(bus, lv, t=1.0):
    lv.start(0.0)
    lv.agent('FINAL_BedofBones_Intro').sound.stop()
    bus.now = t
    lv.update(t)
    return t


def walk_to(bus, mi, lv, goal, t, limit=300, interval=0.5):
    """Walk at an ordinary pace, letting collect sounds finish as they would."""
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
        # the stub bank never ends a sound by itself; a collectible waits on
        # that to hand over to the next one, so retire finished narration here
        for a in lv.agents:
            if getattr(a, '_phase', None) == 'collect' and a.sound is not None:
                a.sound.stop()
        if lv.shutting_down:
            return t, False
    return t, False


# ---------------------------------------------------------------- loading
def test_level_4_builds_completely():
    _bus, _mi, _bank, lv = build()
    assert lv.rect == (-240.0, -330.0, 480.0, 660.0)
    assert lv.player.position == (-10.0, -300.0)
    assert lv.player.pixels_per_step == 10.0
    assert round(lv.player.bearing_degrees, 1) == 90.0
    assert {a.name for a in lv.agents} == {
        'FINAL_BedofBones_Intro', 'atmos_stonepulselow_01', 'note1', 'note2',
        'exit', 'FINAL_BedofBones_Fail', 'hog1', 'atmos_stoneres_01'}
    assert len(lv.floors) == 10


def test_every_sound_the_level_names_is_in_its_playlist():
    _bus, _mi, bank, lv = build()
    for a in lv.agents:
        for name in (getattr(a, 'intro_sound', ''), getattr(a, 'loop_sound', ''),
                     getattr(a, 'collect_sound', ''),
                     getattr(a, 'default_sound', ''), getattr(a, 'chase_sound', ''),
                     getattr(a, 'aware_sound', ''), getattr(a, 'not_there_sound', '')):
            if name:
                assert name in bank.sounds, f'{a.name} wants {name}'


def test_the_hog_carries_its_own_speeds():
    _bus, _mi, _bank, lv = build()
    hog = lv.agent('hog1')
    assert hog.speed == 21.6            # the level's own `speed`, untouched
    assert hog.walking_speed == 10.0    # only state 13 uses this
    assert hog.chase_speed == 36.6
    assert hog.active is False, 'the intro wakes it'


def test_the_bone_floor_is_a_band_across_the_room():
    """You cannot reach the notes without crossing it - that is the level."""
    _bus, _mi, _bank, lv = build()
    bone = [s for s in lv.floors if s.footsteps_prefix == 'foot_bone']
    assert len(bone) == 5
    wide = [s for s in bone if s.rect[2] >= 480.0]
    assert wide, 'at least one spans the full width'
    assert all(s.z == 2 for s in lv.floors)


# --------------------------------------------------------------- playing
def test_stepping_on_the_bones_wakes_the_hog():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    assert hog.active and hog.state == IDLE

    alerts = []
    bus.subscribe('PGE_MESSAGE_AlertAllEnemies',
                  lambda n, p: alerts.append(p.get('to')))
    seen = []
    home = hog.position
    p = lv.player
    foot = LEFT
    for _ in range(300):
        dx, dy = NOTE1[0] - p.position[0], NOTE1[1] - p.position[1]
        if math.hypot(dx, dy) < 12.0:
            break
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += 0.5
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if not seen or seen[-1] != hog.state:
            seen.append(hog.state)
        for a in lv.agents:
            if getattr(a, '_phase', None) == 'collect' and a.sound is not None:
                a.sound.stop()

    assert alerts, 'crossing the bones should alert it'
    assert alerts[0] == 'position', 'a noise, not a sighting'
    # State 4 is a real state that lasts a whole second before it moves - that
    # wind-up is the head start the bones give you.
    assert seen[:3] == [IDLE, ALERT_POSITION, GO_TO_POSITION], \
        f'it should wind up, then walk to where you were; saw {seen}'
    assert hog.position != home, 'and it should have moved'

    # It searches for distractedTime, then goes straight back to IDLE where it
    # stands - the expiry at 0x10001dd18 changes state to 1 on both branches,
    # so a hog alerted to a place never walks home.
    for _ in range(6000):
        t += 1.0 / 60.0
        bus.now = t
        lv.update(t)
        if not seen or seen[-1] != hog.state:
            seen.append(hog.state)
        if AT_POSITION in seen and seen[-1] == IDLE:
            break
    assert AT_POSITION in seen, f'it never searched; saw {seen}'
    assert RETURNING not in seen, f'it should not walk home from a noise; saw {seen}'
    assert seen[-1] == IDLE, f'and never settled; saw {seen}'


def test_the_note_chain_runs_and_the_exit_leads_to_level_5():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    for goal, name in ((NOTE1, 'note1'), (NOTE2, 'note2'), (EXIT, 'exit')):
        t, reached = walk_to(bus, mi, lv, goal, t)
        assert reached or lv.shutting_down, f'could not reach {name}'
        assert lv.agent(name).was_collected, f'{name} was not collected'
    assert lv.shutting_down
    lv.agent('exit').sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_5'


def test_walking_into_the_hog_fails_the_level_back_to_itself():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    t, _ = walk_to(bus, mi, lv, hog.position, t)
    assert lv.shutting_down
    fail = lv.agent('FINAL_BedofBones_Fail')
    assert fail.active
    fail.sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_4'


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
