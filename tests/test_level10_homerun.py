"""Level 10, "Home Run" - the reaper again, twice, with five notes to fetch.

Structurally ps1_9 with the difficulty moved from speed to arithmetic: two
hunters instead of one, five notes instead of two, and both reapers much slower
to compensate - 3.6 and 2.5 pixels a second against the 8.3 of the single one
in ps1_9.  They have a voice each (``monster_reaper1_*`` and
``monster_reaper2_*``), which is the only way to tell which is which, and like
ps1_9 each uses its one sound for all four states so neither ever restarts or
falls silent.  The Room is again the only ground.

The level data carries two mistakes, both reproduced:

* **note3's ``OnCollide`` is spelt ``ChangeInactivitySoundlist``** - lowercase
  L.  Nothing observes that message, so of the five notes, the third is the one
  that does not reorder the nagging.  It is the only place in all 27 maps where
  the name is spelt that way.
* **the intro activates ``atmos_crickets_01``, which this level does not
  have.**  ps1_9's intro did, and this one was copied from it; the crickets are
  never heard here.

The intro also contains a stray empty message (``...name=note1||Activate...``),
which is harmless but has to be tolerated.
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

NOTES = ('note1', 'note2', 'note3', 'note4', 'note5')
ORDER = NOTES + ('exit',)
NAG = 'FINAL_grinreaper_inactive_'


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
    bank = FakeBank(sorted(declared('ps1_10')), clock=lambda: bus.now)
    progress = GameProgress(path=os.path.join(tempfile.mkdtemp(), 'p.json'))
    lv = Level(bus, bank, progress=progress).load(
        os.path.join(EXPORTS, 'ps1_10.json'), 'ps1_10')
    return bus, mi, bank, lv


def start(bus, lv, t=1.0):
    lv.start(0.0)
    lv.agent('FINAL_HomeRun_Intro').sound.stop()
    for step in (t, t + 0.1):
        bus.now = step
        lv.update(step)
    return t + 0.1


def evade(bus, mi, lv, steps=1200, keep=60.0, interval=0.45, t=1.1):
    """Fetch each note in turn, bending away from either reaper when near."""
    p = lv.player
    reapers = [lv.agent('reaper1'), lv.agent('reaper2')]
    x0, y0, w, h = lv.rect
    foot = LEFT
    collected = []
    for _ in range(steps):
        goal = None
        for name in ORDER:
            a = lv.agent(name)
            if a.active and not a.was_collected:
                goal = a.position
                break
        if goal is None:
            goal = lv.agent('exit').position
        gx, gy = goal[0] - p.position[0], goal[1] - p.position[1]
        n = math.hypot(gx, gy) or 1.0
        vx, vy = gx / n, gy / n
        for r in reapers:
            rx, ry = p.position[0] - r.position[0], p.position[1] - r.position[1]
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
        for name in ORDER:
            if lv.agent(name).was_collected and name not in collected:
                collected.append(name)
        if lv.shutting_down:
            break
    return t, collected


# ---------------------------------------------------------------- loading
def test_level_10_builds_completely():
    _bus, _mi, _bank, lv = build()
    assert lv.rect == (-240.0, -240.0, 480.0, 480.0)
    assert lv.player.position == (-10.0, -210.0)
    assert round(lv.player.bearing_degrees, 1) == 135.0
    assert {a.name for a in lv.agents} == {
        'FINAL_HomeRun_Intro', 'FINAL_HomeRun_Fail', 'atmos_reedbed_01',
        'note1', 'note2', 'note3', 'note4', 'note5', 'exit',
        'reaper1', 'reaper2'}
    assert lv.floors == [], 'the Room is the only ground again'
    assert lv.footsteps_prefix == 'foot_stonepath'


def test_two_reapers_each_with_their_own_voice_and_pace():
    _bus, _mi, bank, lv = build()
    r1, r2 = lv.agent('reaper1'), lv.agent('reaper2')
    assert r1.speed == 3.6 and r1.chase_speed == 3.6
    assert r2.speed == 2.5 and r2.chase_speed == 2.5
    assert r1.chase_sound == 'monster_reaper1_01_dry_chase'
    assert r2.chase_sound == 'monster_reaper2_01_dry_chase'
    # one sound each, in all four slots, so neither ever restarts
    for r in (r1, r2):
        voices = {r.default_sound, r.aware_sound, r.chase_sound,
                  r.not_there_sound}
        assert len(voices) == 1, f'{r.name} has more than one voice: {voices}'
        assert voices.pop() in bank.sounds
    # and slower than the single reaper of ps1_9, which ran at 8.3
    assert r1.speed < 8.3 and r2.speed < r1.speed


def test_the_note_chain_is_five_long():
    _bus, _mi, _bank, lv = build()
    chain, name = [], 'note1'
    while name and name not in chain:
        chain.append(name)
        name = lv.agent(name).next_collectible
    assert chain == list(ORDER), chain


# --------------------------------------------------------------- the hunt
def test_the_intro_sets_both_of_them_on_you():
    bus, _mi, _bank, lv = build()
    r1, r2 = lv.agent('reaper1'), lv.agent('reaper2')
    assert r1.state == IDLE and r2.state == IDLE
    t = start(bus, lv)
    for _ in range(16):          # past the one second roar before the charge
        t += 0.1
        bus.now = t
        lv.update(t)
    assert r1.state == CHASE_PLAYER and r2.state == CHASE_PLAYER
    assert lv.inactivity_time == 18.0
    assert lv.agent('note1').active
    assert lv.agent('atmos_reedbed_01').active


def test_the_intro_survives_its_own_mistakes():
    """It names an agent this level does not have, and has an empty message.

    ``atmos_crickets_01`` exists in ps1_9, which this intro was copied from.
    Neither mistake may stop the rest of the chain running.
    """
    from papasangre.assets.tiled import load_level                 # noqa: PLC0415
    data = load_level(os.path.join(EXPORTS, 'ps1_10.json'), 'ps1_10')
    intro = [o for o in data.objects if o.name == 'FINAL_HomeRun_Intro'][0]
    wanted = [t.parameters.get('name') for t in intro.triggers
              if 'ActivateAgentWithName' in t.notification_name]
    assert 'atmos_crickets_01' in wanted
    assert not any(o.name == 'atmos_crickets_01' for o in data.objects)

    bus, _mi, _bank, lv = build()
    t = start(bus, lv)                      # must not raise
    for _ in range(4):
        t += 0.1
        bus.now = t
        lv.update(t)
    assert lv.agent('reaper1').active, 'the rest of the chain still ran'
    assert lv.agent('reaper2').active


def test_fetching_all_five_wins_the_level_and_leads_to_eleven():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    t, got = evade(bus, mi, lv, t=t)
    assert got == list(ORDER), f'only got {got}'
    assert lv.shutting_down
    lv.agent('exit').sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_11'


def test_neither_reaper_ever_restarts_its_voice():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    for _ in range(4):
        t += 0.1
        bus.now = t
        lv.update(t)
    before = len(bank.played)
    t, _got = evade(bus, mi, lv, steps=80, t=t)
    starts = [s for s in bank.played[before:] if s.startswith('monster')]
    assert len(starts) <= 2, f'a reaper restarted: {starts}'


def test_walking_into_one_fails_the_level_back_to_itself():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    r1 = lv.agent('reaper1')
    p = lv.player
    foot = LEFT
    for _ in range(200):
        dx, dy = r1.position[0] - p.position[0], r1.position[1] - p.position[1]
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
    assert ATTACK in (lv.agent('reaper1').state, lv.agent('reaper2').state)
    fail = lv.agent('FINAL_HomeRun_Fail')
    assert fail.active
    fail.sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_10'


# ------------------------------------------------------- the note3 typo
def test_note_three_is_the_one_that_does_not_reorder_the_nagging():
    """``ChangeInactivitySoundlist`` - lowercase L, so nothing hears it.

    The other four notes each reorder the list; the third silently does not.
    Reproduced rather than corrected: it is in the shipped map data.
    """
    from papasangre.assets.tiled import load_level                 # noqa: PLC0415
    data = load_level(os.path.join(EXPORTS, 'ps1_10.json'), 'ps1_10')
    spelt = {}
    for o in data.objects:
        for tr in o.triggers:
            if 'ChangeInactivitySound' in tr.notification_name:
                spelt[o.name] = tr.notification_name
    assert len(spelt) == 5, spelt
    assert spelt['note3'].endswith('Soundlist'), spelt['note3']
    for name in ('note1', 'note2', 'note4', 'note5'):
        assert spelt[name].endswith('SoundList'), spelt[name]

    # At runtime each note should leave the list exactly as it asked - except
    # the third, which asks in a language nothing speaks.  (note4 happens to
    # ask for the same order note2 did, so "did it change" is not the test;
    # "is it what this note wanted" is.)
    asked = {}
    for o in data.objects:
        for tr in o.triggers:
            if 'ChangeInactivitySound' in tr.notification_name:
                asked[o.name] = [n for n in
                                 tr.parameters.get('soundList', '').split('&') if n]
    bus, _mi, _bank, lv = build()
    t = start(bus, lv)
    for name in NOTES:
        lv.agent(name).active = True
        before = list(lv.inactivity_sounds)
        lv.player.position = lv.agent(name).position
        bus.post('PGE_MESSAGE_PlayerMovedToPosition',
                 {'position': lv.player.position})
        for _ in range(4):
            t += 0.1
            bus.now = t
            lv.update(t)
        assert lv.agent(name).was_collected, name
        if name == 'note3':
            assert lv.inactivity_sounds == before, \
                'the misspelt message must do nothing'
            assert lv.inactivity_sounds != asked['note3'], \
                'and what it asked for must never have been applied'
        else:
            assert lv.inactivity_sounds == asked[name], \
                f'{name} wanted {asked[name]}, got {lv.inactivity_sounds}'


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
