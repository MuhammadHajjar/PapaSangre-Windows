"""Level 8, "The Island" - wading, and the first surface that retriggers.

The island is six rectangles nested inside one another, each one a little
smaller and a little wetter: stone path, reeds, reed-water, open water, wet
sand, dry sand.  Walking towards the middle takes you through all of them in
order, and the footstep sound under you is the only thing that tells you how
deep you are.  There is no map and no light; the depth *is* the map.

Two things here that no earlier level has:

* **``multipleOnEnter``**.  A surface normally fires ``OnEnter`` once in the
  life of the level and never again - the ``entered`` latch is never cleared.
  The three stone strips along the edges set this flag, which governs both
  ``OnEnter`` and ``OnExit``, so their birds call every single time you cross.
  They are the boundary markers of the island, and they would be useless once-
  only.
* **``ChangeInactivityTime``**.  The intro's ``OnSoundEnd`` sets the nag clock
  to 18 seconds, so standing still on the island prompts you where earlier
  levels left you alone.

In the middle, on the dry sand, ``OnStep`` alerts the bird - on *every* step,
the same shape as ps1_7's guts.
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
from papasangre.entities.monster import (ATTACK, GO_TO_POSITION,   # noqa: E402
                                         IDLE)
from papasangre.input.interpreter import (LEFT, RIGHT,             # noqa: E402
                                          MoveInterpretor)
from papasangre.save import GameProgress                           # noqa: E402
from papasangre.world.level import Level                           # noqa: E402
from test_level import FakeBank                                    # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
META = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')

NOTE1 = (-50.0, -160.0)
NOTE2 = (-126.0, 12.0)
NOTE3 = (-230.0, -30.0)
EXIT = (70.0, 280.0)

#: the innermost dry sand, where every step calls the bird
SAND_CENTRE = (20.0, 25.0)
#: on the southern stone strip but clear of the reed bank, which shares its z
ON_THE_STRIP = (-310.0, -195.0)
#: bare level floor, outside every surface
OFF_EVERY_SURFACE = (-330.0, 380.0)


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
    bank = FakeBank(sorted(declared('ps1_8')), clock=lambda: bus.now)
    progress = GameProgress(path=os.path.join(tempfile.mkdtemp(), 'p.json'))
    lv = Level(bus, bank, progress=progress).load(
        os.path.join(EXPORTS, 'ps1_8.json'), 'ps1_8')
    return bus, mi, bank, lv


def start(bus, lv, t=1.0):
    lv.start(0.0)
    lv.agent('FINAL_Island_Intro').sound.stop()
    # the intro's OnSoundEnd is drained at the end of that update, so what it
    # activates only gets its first frame on the one after
    for step in (t, t + 0.1):
        bus.now = step
        lv.update(step)
    return t + 0.1


def walk_to(bus, mi, lv, goal, t, limit=500, interval=0.45):
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


def stand(bus, lv, pos, t, interval=0.45):
    """Put the player somewhere and let the level notice."""
    t += interval
    bus.now = t
    lv.player.position = pos
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': pos})
    lv.update(t)
    return t


# ---------------------------------------------------------------- loading
def test_level_8_builds_completely():
    _bus, _mi, _bank, lv = build()
    assert lv.rect == (-340.0, -390.0, 680.0, 780.0)
    assert lv.player.position == (20.0, -360.0)
    assert lv.player.pixels_per_step == 10.0
    assert round(lv.player.bearing_degrees, 1) == 90.0, 'startAngle faces you north'
    assert {a.name for a in lv.agents} == {
        'FINAL_Island_Intro', 'FINAL_Island_Fail', 'FINAL_theisland_inactive_18sec',
        'atmos_reedbed_01', 'note1', 'note2', 'note3', 'exit', 'bird1'}
    assert len(lv.floors) == 8


def test_the_island_is_six_depths_of_ground():
    """The level itself is the outermost, at z 1 - it is a Surface too."""
    _bus, _mi, _bank, lv = build()
    assert lv.z == 1 and lv.footsteps_prefix == 'foot_stonepath'
    by_z = {}
    for s in lv.floors:
        by_z.setdefault(s.z, set()).add(s.footsteps_prefix)
    assert by_z[2] == {'foot_stonepath', 'foot_reeds'}
    assert by_z[3] == {'foot_reeds-waterB'}
    assert by_z[4] == {'foot_waterswim'}
    assert by_z[5] == {'foot_sand-waterB'}
    assert by_z[6] == {'foot_sand'}
    # nested, each strictly inside the last
    for lo, hi in ((3, 4), (4, 5), (5, 6)):
        a = [s for s in lv.floors if s.z == lo][0].rect
        b = [s for s in lv.floors if s.z == hi][0].rect
        assert a[0] < b[0] and a[1] < b[1], f'z{hi} should sit inside z{lo}'


def test_wading_in_changes_the_ground_under_you():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    seen = []
    for pos in (OFF_EVERY_SURFACE, (-250.0, -250.0), (-200.0, -200.0),
                (-150.0, -150.0), (-110.0, -110.0), SAND_CENTRE):
        t = stand(bus, lv, pos, t)
        if not seen or seen[-1] != lv.player.footsteps_prefix:
            seen.append(lv.player.footsteps_prefix)
    assert seen == ['foot_stonepath', 'foot_reeds', 'foot_reeds-waterB',
                    'foot_waterswim', 'foot_sand-waterB', 'foot_sand'], seen


# ------------------------------------------------------- multipleOnEnter
def test_the_stone_strips_call_their_birds_every_crossing():
    """``multipleOnEnter`` is the only thing that clears the ``entered`` latch.

    Three strips set it; the reed banks do not.  Cross a strip three times and
    you should be told three times.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    strips = [s for s in lv.floors if s.multiple_on_enter]
    assert len(strips) == 3, 'the three stone edges'
    assert all(s.footsteps_prefix == 'foot_stonepath' for s in strips)

    for n in (1, 2, 3):
        t = stand(bus, lv, OFF_EVERY_SURFACE, t)
        t = stand(bus, lv, ON_THE_STRIP, t)
        played = sum(1 for s in bank.played if s.startswith('easteregg_birds'))
        assert played == n, f'crossing {n} played {played} bird calls'


def test_the_reed_banks_only_speak_once():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    reeds = [s for s in lv.floors if s.footsteps_prefix == 'foot_reeds'][0]
    assert not reeds.multiple_on_enter
    rx, ry, _w, _h = reeds.rect
    for _ in range(3):
        t = stand(bus, lv, OFF_EVERY_SURFACE, t)
        t = stand(bus, lv, (rx + 20.0, ry + 20.0), t)
    assert bank.played.count('easteregg_wind') == 1


def test_an_or_list_of_easter_eggs_picks_one_name():
    """``PlaySound:soundName=a&b&c`` is three candidates, not one name."""
    from papasangre.assets.tiled import load_level                 # noqa: PLC0415
    data = load_level(os.path.join(EXPORTS, 'ps1_8.json'), 'ps1_8')
    names = [t.parameters.get('soundName', '') for o in data.objects
             for t in o.triggers if 'PlaySound' in t.notification_name]
    joined = [n for n in names if '&' in n]
    assert joined, 'the bird strips use the & form'
    bus, mi, bank, lv = build()
    for n in joined[0].split('&'):
        assert n in bank.sounds, f'{n} should be a real sound'


# ------------------------------------------------------------- the intro
def test_the_intro_hands_the_island_over():
    bus, mi, bank, lv = build()
    assert lv.inactivity_time == 0.0
    t = start(bus, lv)
    assert lv.inactivity_time == 18.0, 'ChangeInactivityTime:value=18'
    assert lv.inactivity_sounds == ['FINAL_theisland_inactive_note']
    for name in ('atmos_reedbed_01', 'note1', 'bird1'):
        assert lv.agent(name).active, f'{name} should be awake'
    assert not lv.agent('note2').active, 'the chain hands on one at a time'


def test_the_18_second_nag_sound_is_dead_content():
    """The level carries a sound agent named for the 18 second timer that
    nothing ever activates, and that its playlist does not even declare.  The
    nag you actually hear is the Room's ``inactivitySounds``.  Reproduced."""
    _bus, _mi, bank, lv = build()
    dead = lv.agent('FINAL_theisland_inactive_18sec')
    assert dead is not None and not dead.active
    assert 'FINAL_theisland_inactive_18sec' not in bank.sounds, \
        'not in the level playlist, so silent even if something did fire it'
    assert lv.inactivity_sounds == ['FINAL_theisland_inactive_note']


# -------------------------------------------------------------- the bird
def test_the_dry_sand_calls_the_bird_and_keeps_calling_it_silently():
    """Same shape as ps1_7's guts: ``OnStep = AlertAllEnemies:to=position``.

    The first step snarls and starts the chase; every step after it re-aims the
    bird without touching its voice, because state 4 latches
    ``hasWantedPosition``.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    bird = lv.agent('bird1')
    assert bird.state == IDLE
    sand = [s for s in lv.floors if s.footsteps_prefix == 'foot_sand'][0]
    assert any(tr.trigger_type == 'OnStep' and 'Alert' in tr.notification_name
               for tr in sand.triggers)

    # start in the corner of the sand furthest from the bird, so there are a
    # good many steps before it reaches us and ends the level
    x, y, w, h = sand.rect
    cx, cy = x + 20.0, y + 20.0
    assert math.dist((cx, cy), bird.position) > 150.0
    dt = 1.0 / 60.0
    next_step = t + 0.45
    foot, n, starts = LEFT, 0, []
    while t < 8.0:
        t += dt
        bus.now = t
        if t >= next_step:
            next_step += 0.45
            n += 1
            lv.player.position = (cx + (6 if n % 2 else -6), cy)
            mi.foot_pressed(foot)
            mi.foot_released(foot, t)
            foot = RIGHT if foot == LEFT else LEFT
        before = len(bank.played)
        lv.update(t)
        starts += [s for s in bank.played[before:] if s.startswith('monster')]
        if lv.shutting_down:
            break

    assert n >= 8, f'that should be a good few steps, was {n}'
    assert bird.state != IDLE, 'the sand should have woken it'
    assert starts.count('monster_bird_01_dry_chase') <= 1, \
        f'the chase sound restarted: {starts}'
    assert starts.count('monster_bird_01_dry_aware') <= 1, \
        f'it snarled more than once: {starts}'


def test_being_caught_fails_the_island_back_to_itself():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    bird = lv.agent('bird1')
    t, _ = walk_to(bus, mi, lv, bird.position, t)
    assert lv.shutting_down
    assert bird.state == ATTACK
    fail = lv.agent('FINAL_Island_Fail')
    assert fail.active
    fail.sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_8'


# --------------------------------------------------------------- the run
def test_the_note_chain_runs_and_the_exit_leads_to_level_9():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    for goal, name in ((NOTE1, 'note1'), (NOTE2, 'note2'),
                       (NOTE3, 'note3'), (EXIT, 'exit')):
        t, _ = walk_to(bus, mi, lv, goal, t)
        assert lv.agent(name).was_collected, f'{name} was not collected'
        if lv.shutting_down:
            break
    assert lv.shutting_down
    lv.agent('exit').sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_9'


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
