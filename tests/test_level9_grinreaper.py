"""Level 9, "The Grin Reaper" - one room, one enemy, and no hiding place.

The simplest level in the game to describe and the hardest so far to survive.
There is nothing in it but a cornfield, two notes, a door and the reaper, and
the reaper is set on you by the intro itself: its ``OnSoundEnd`` ends with
``AlertAllEnemies:to=player``, which is the branch that goes straight to
``CHASE_PLAYER``. Nothing in the level ever calls it off. From the moment the
narration stops until you are out of the door it is walking at you.

Two details make it work as audio:

* **The reaper has one voice.** ``defaultSound``, ``awareSound``, ``chaseSound``
  and ``notThereSound`` are all ``monster_reaper1_01_dry_chase``. Since
  ``playSound:`` refuses a name it is already playing, whatever the state
  machine does the sound never restarts - you get one unbroken tone that only
  ever changes position. That is the whole level: you navigate by how far away
  it is.
* **It is slower than you.** 8.3 against roughly 22 pixels a second at a normal
  walking tempo, so it is escapable, but only by keeping moving.

It is also the first level with **no ``Surface`` objects at all** - the Room is
the only ground there is, which only works because ``PGELevel`` is a
``PGESurface``.
"""

import glob
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from papasangre.assets.sexp import include_stem, parse_playlist    # noqa: E402
from papasangre.core.messages import MessageBus                    # noqa: E402
from papasangre.entities.monster import (ATTACK, CHASE_PLAYER,     # noqa: E402
                                         IDLE)
from papasangre.input.interpreter import (LEFT, RIGHT,             # noqa: E402
                                          MoveInterpretor)
from papasangre.save import GameProgress                           # noqa: E402
from papasangre.world.level import Level                           # noqa: E402
from test_level import FakeBank                                    # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
META = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')

REAPER_VOICE = 'monster_reaper1_01_dry_chase'
NAGS = ['FINAL_grinreaper_inactive_1', 'FINAL_grinreaper_inactive_2',
        'FINAL_grinreaper_inactive_3']


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
    bank = FakeBank(sorted(declared('ps1_9')))
    progress = GameProgress(path=os.path.join(tempfile.mkdtemp(), 'p.json'))
    lv = Level(bus, bank, progress=progress).load(
        os.path.join(EXPORTS, 'ps1_9.json'), 'ps1_9')
    return bus, mi, bank, lv


def start(bus, lv, t=1.0):
    lv.start(0.0)
    lv.agent('FINAL_GrinReaper_Intro').sound.stop()
    for step in (t, t + 0.1):
        bus.now = step
        lv.update(step)
    return t + 0.1


def evade(bus, mi, lv, steps=900, keep=70.0, interval=0.45, t=1.1):
    """Walk the level the way it has to be walked: towards the next thing,
    bending away from the reaper whenever it gets close, staying off the walls.
    """
    p, reaper = lv.player, lv.agent('reaper1')
    x0, y0, w, h = lv.rect
    foot = LEFT
    collected = []
    for _ in range(steps):
        goal = None
        for name in ('note1', 'note2', 'exit'):
            a = lv.agent(name)
            if a.active and not a.was_collected:
                goal = a.position
                break
        if goal is None:
            goal = lv.agent('exit').position
        gx, gy = goal[0] - p.position[0], goal[1] - p.position[1]
        n = math.hypot(gx, gy) or 1.0
        vx, vy = gx / n, gy / n
        rx, ry = p.position[0] - reaper.position[0], p.position[1] - reaper.position[1]
        d = math.hypot(rx, ry) or 1.0
        if d < keep:
            flee = (keep - d) / keep * 2.5
            vx += rx / d * flee
            vy += ry / d * flee
        if p.position[0] < x0 + 30:
            vx += 1.0
        if p.position[0] > x0 + w - 30:
            vx -= 1.0
        if p.position[1] < y0 + 30:
            vy += 1.0
        if p.position[1] > y0 + h - 30:
            vy -= 1.0
        p.rotate_to_fixed_rotation(math.atan2(vy, vx))
        t += interval
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        for a in lv.agents:
            if getattr(a, '_phase', None) == 'collect' and a.sound is not None:
                a.sound.stop()
        for name in ('note1', 'note2', 'exit'):
            if lv.agent(name).was_collected and name not in collected:
                collected.append(name)
        if lv.shutting_down:
            break
    return t, collected


# ---------------------------------------------------------------- loading
def test_level_9_builds_completely():
    _bus, _mi, _bank, lv = build()
    assert lv.rect == (-240.0, -240.0, 480.0, 480.0)
    assert lv.player.position == (-110.0, -180.0)
    assert lv.player.pixels_per_step == 10.0
    assert round(lv.player.bearing_degrees, 1) == 45.0
    assert {a.name for a in lv.agents} == {
        'FINAL_GrinReaper_Intro', 'FINAL_GrinReaper_Fail', 'atmos_crickets_01',
        'atmos_reedbed_01', 'note1', 'note2', 'exit', 'reaper1'}


def test_the_room_is_the_only_ground_there_is():
    """No Surface objects at all - the first level like it.

    This only works because ``PGELevel`` is a ``PGESurface``: the depth search
    starts from the level itself, so the Room's own ``footstepsPrefix`` is what
    reaches the player.
    """
    _bus, _mi, _bank, lv = build()
    assert lv.floors == []
    assert lv.z == 1
    assert lv.footsteps_prefix == 'foot_cornfield'
    assert lv.player.footsteps_prefix == 'foot_cornfield'


def test_the_reaper_speaks_with_one_voice():
    """All four sounds are the same name, so it never restarts or falls quiet.

    ``playSound:`` guards on the name alone, so no state change can interrupt
    it - the reaper is one unbroken tone that only ever moves.
    """
    _bus, _mi, bank, lv = build()
    r = lv.agent('reaper1')
    assert r.default_sound == REAPER_VOICE
    assert r.aware_sound == REAPER_VOICE
    assert r.chase_sound == REAPER_VOICE
    assert r.not_there_sound == REAPER_VOICE
    assert REAPER_VOICE in bank.sounds
    assert r.speed == 8.3 and r.chase_speed == 8.3


# --------------------------------------------------------------- the hunt
def test_the_intro_sets_the_reaper_on_you():
    bus, _mi, _bank, lv = build()
    r = lv.agent('reaper1')
    assert not r.active and r.state == IDLE
    t = start(bus, lv)
    assert r.active
    for _ in range(4):
        t += 0.1
        bus.now = t
        lv.update(t)
    assert r.state == CHASE_PLAYER, \
        f'the intro should hand you straight to it, got {r.state_name}'
    assert lv.inactivity_time == 18.0


def test_the_reaper_never_gives_up_and_never_changes_its_note():
    """Half a minute of running and it is still coming, still on one sound."""
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    r = lv.agent('reaper1')
    for _ in range(4):
        t += 0.1
        bus.now = t
        lv.update(t)
    assert r.state == CHASE_PLAYER
    before = len(bank.played)
    t, _got = evade(bus, mi, lv, steps=60, t=t)
    starts = [s for s in bank.played[before:] if s.startswith('monster')]
    assert r.state in (CHASE_PLAYER, ATTACK), r.state_name
    assert len(starts) <= 1, f'its voice restarted: {starts}'


def test_keeping_away_from_it_wins_the_level_and_leads_to_ten():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    t, got = evade(bus, mi, lv, t=t)
    assert got == ['note1', 'note2', 'exit'], f'only got {got}'
    assert lv.shutting_down
    lv.agent('exit').sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_10'


def test_walking_into_it_fails_the_level_back_to_itself():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    r = lv.agent('reaper1')
    p = lv.player
    foot = LEFT
    for _ in range(200):
        dx, dy = r.position[0] - p.position[0], r.position[1] - p.position[1]
        if math.hypot(dx, dy) < 12.0:
            break
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += 0.45
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if lv.shutting_down:
            break
    assert lv.shutting_down
    assert r.state == ATTACK
    fail = lv.agent('FINAL_GrinReaper_Fail')
    assert fail.active
    fail.sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_9'


# ------------------------------------------------------------- the nagging
def test_the_notes_reorder_the_nagging():
    """``ChangeInactivitySoundList`` on each note's ``OnCollide``.

    The same three lines in a different order each time, so being told twice
    does not sound like a repeat.
    """
    bus, _mi, _bank, lv = build()
    t = start(bus, lv)
    assert lv.inactivity_sounds == NAGS
    n1 = lv.agent('note1')
    lv.player.position = n1.position
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    for _ in range(4):
        t += 0.1
        bus.now = t
        lv.update(t)
    assert n1.was_collected
    assert lv.inactivity_sounds == [NAGS[1], NAGS[0], NAGS[2]]


def test_standing_still_works_through_the_list_and_wraps():
    bus, _mi, bank, lv = build()
    t = start(bus, lv)
    lv.agent('reaper1').active = False       # isolate the nag from the chase
    lv.last_activity = t
    before = len(bank.played)
    for _ in range(700):
        t += 0.1
        bus.now = t
        lv.update(t)
    heard = [s for s in bank.played[before:] if 'inactive' in s]
    assert heard[:3] == NAGS, heard
    assert lv.current_inactivity_sound == 0, 'and it wraps back to the start'


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
