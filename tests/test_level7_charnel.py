"""Level 7, "The Charnel House" - the first dilemma.

A baby lies calling in the dark and you choose whether to carry it out.  Picking
it up costs you: its ``OnCollide`` is ``AlertAllEnemies:to=player``, so the hog
comes after you for the rest of the level.  Leave it and you walk out quietly.

The choice is remembered, and the exit says so: its ``collectSound`` is the
literal string ``dilemmaOutcome``, which the level resolves at the moment you
touch the door into one of the fourteen recorded endings.  ps1_7 asks about one
choice, ps1_12 about two, ps1_18 about three - the earlier answers coming from
levels you played before.
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
from papasangre.entities.dilemma import (ABANDONED, ALERT,         # noqa: E402
                                         Dilemma, REST, THANKED)
from papasangre.entities.monster import (AT_POSITION,              # noqa: E402
                                         CHASE_PLAYER, IDLE)
from papasangre.input.interpreter import (LEFT, RIGHT,             # noqa: E402
                                          MoveInterpretor)
from papasangre.save import GameProgress                           # noqa: E402
from papasangre.world.level import Level                           # noqa: E402
from test_level import FakeBank                                    # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
META = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')

NOTE1 = (-254.0, 54.0)
NOTE2 = (-84.0, -36.0)
BABY = (226.0, 34.0)
EXIT = (296.0, 94.0)
#: well clear of the baby's 100 px alert radius, on the way to the door
PAST_THE_BABY = (250.0, 200.0)


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
    bank = FakeBank(sorted(declared('ps1_7')), clock=lambda: bus.now)
    progress = GameProgress(path=os.path.join(tempfile.mkdtemp(), 'p.json'))
    lv = Level(bus, bank, progress=progress).load(
        os.path.join(EXPORTS, 'ps1_7.json'), 'ps1_7')
    return bus, mi, bank, lv


def start(bus, lv, t=1.0):
    lv.start(0.0)
    lv.agent('FINAL_Charnel_Intro').sound.stop()
    # the intro's OnSoundEnd is drained at the end of that update, so the agents
    # it activates only get their first frame on the one after
    for step in (t, t + 0.1):
        bus.now = step
        lv.update(step)
    return t + 0.1


def walk_to(bus, mi, lv, goal, t, limit=400, interval=0.45):
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
def test_level_7_builds_including_its_dilemma():
    _bus, _mi, _bank, lv = build()
    baby = lv.agent('baby')
    assert isinstance(baby, Dilemma)
    assert baby.dilemma_id == 'dilemma_1'
    assert baby.rest_sound == 'dilemma_baby_living'
    assert baby.alert_sound == 'dilemma_baby_aware'
    assert baby.thanks_sound == 'dilemma_baby_collect'
    assert baby.abandon_sound == 'dilemma_baby_abandon'
    assert baby.alert_distance == 100.0, 'the PGEDilemma init default'
    assert baby.collected is False


def test_the_editor_leftovers_in_the_hidden_layer_are_ignored():
    """ps1_7 carries a copy of level 2's objects in an invisible ToolBar layer.

    Both the original and the port skip that layer by name, which matters:
    it holds a second `note1` and `note2` that would otherwise answer the
    level's own ActivateAgentWithName messages.
    """
    from papasangre.assets.tiled import load_level                 # noqa: PLC0415
    data = load_level(os.path.join(EXPORTS, 'ps1_7.json'), 'ps1_7')
    assert 'ToolBar' in data.skipped_layers
    names = [o.name for o in data.objects if o.type == 'Collectible']
    assert sorted(names) == ['exit', 'note1', 'note2'], names
    assert 'castle_door' not in names


def test_the_exit_asks_the_level_for_an_ending():
    _bus, _mi, _bank, lv = build()
    assert lv.agent('exit').collect_sound == 'dilemmaOutcome'


def test_the_guts_patches_are_the_noisy_ones():
    """Each patch of guts sits inside a ring of stone that warns you first."""
    _bus, _mi, _bank, lv = build()
    guts = [s for s in lv.floors if s.footsteps_prefix == 'foot_guts']
    stone = [s for s in lv.floors if s.footsteps_prefix == 'foot_stone']
    assert len(guts) == 3 and len(stone) == 3
    for g in guts:
        assert any(t.trigger_type == 'OnStep' and 'Alert' in t.notification_name
                   for t in g.triggers), 'every step on guts should alert'


# --------------------------------------------------------------- dilemma
def test_the_baby_rests_calls_out_and_cries_after_you():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    baby = lv.agent('baby')
    assert baby.state == REST
    assert baby.sound.name == 'dilemma_baby_living'

    # step inside the alert radius without touching it
    lv.player.position = (BABY[0] - 60.0, BABY[1])
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    lv.update(t + 0.1)
    assert baby.state == ALERT, 'it should call out when you come near'
    assert baby.sound.name == 'dilemma_baby_aware'

    lv.player.position = (BABY[0] - 400.0, BABY[1])
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    lv.update(t + 0.2)
    assert baby.state == ABANDONED, 'and cry after you when you walk away'
    assert baby.sound.name == 'dilemma_baby_abandon'


def test_a_baby_you_never_approached_never_cries():
    """ABANDONED is only reachable from ALERT."""
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    baby = lv.agent('baby')
    lv.player.position = (BABY[0] - 400.0, BABY[1])
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    lv.update(t + 0.1)
    assert baby.state == REST


def test_carrying_the_baby_wakes_the_hog_and_is_remembered():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    baby, hog = lv.agent('baby'), lv.agent('hog1')
    assert hog.state == IDLE

    t, _ = walk_to(bus, mi, lv, BABY, t)
    assert baby.collected, 'walking into it picks it up'
    assert baby.state == THANKED
    assert baby.sound.name == 'dilemma_baby_collect'
    # OnCollide is enqueued, so the alert lands on the following frame and the
    # chase entry work on the one after that
    for _ in range(16):          # past the one second roar before the charge
        t += 0.1
        bus.now = t
        lv.update(t)
    assert hog.state == CHASE_PLAYER, f'and that is what it costs you ({hog.state_name})'

    assert lv.solve_dilemmas() == 'dilemmaOutcome_1'
    assert lv.progress.get_dilemma_status('dilemma_1') is True


def test_leaving_the_baby_behind_is_remembered_too():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    baby = lv.agent('baby')
    t, _ = walk_to(bus, mi, lv, PAST_THE_BABY, t)
    assert not baby.collected
    assert lv.solve_dilemmas() == 'dilemmaOutcome_0'
    assert lv.progress.get_dilemma_status('dilemma_1') is False


def test_a_carried_baby_stops_reacting_to_you():
    """state 11 makes checkCollisionsWithPlayer return before anything else."""
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    baby = lv.agent('baby')
    t, _ = walk_to(bus, mi, lv, BABY, t)
    assert baby.state == THANKED
    lv.player.position = (BABY[0] - 400.0, BABY[1])
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    lv.update(t + 0.5)
    assert baby.state == THANKED, 'it does not go back to crying'


# --------------------------------------------------------------- endings
def test_the_ending_depends_only_on_the_dilemmas_this_level_knows_about():
    """ps1_7 holds dilemma_1, so its ending is one digit deep whatever else
    is in saved progress."""
    bus, mi, bank, lv = build()
    lv.progress.save_dilemma_status(True, 'dilemma_2')
    lv.progress.save_dilemma_status(True, 'dilemma_3')
    assert lv.solve_dilemmas() == 'dilemmaOutcome_0'


def test_every_ending_the_tree_can_produce_is_a_real_sound():
    _bus, _mi, bank, lv = build()
    for a in (0, 1):
        assert f'dilemmaOutcome_{a}' in bank.sounds
        for b in (0, 1):
            assert f'dilemmaOutcome_{a}_{b}' in bank.sounds
            for c in (0, 1):
                assert f'dilemmaOutcome_{a}_{b}_{c}' in bank.sounds


def test_the_door_plays_the_ending_and_leads_to_level_8():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    for goal, name in ((NOTE1, 'note1'), (NOTE2, 'note2'),
                       (PAST_THE_BABY, None), (EXIT, 'exit')):
        t, _ = walk_to(bus, mi, lv, goal, t)
        if name:
            assert lv.agent(name).was_collected, f'{name} was not collected'
        if lv.shutting_down:
            break
    assert lv.shutting_down
    exit_door = lv.agent('exit')
    assert exit_door.collect_sound == 'dilemmaOutcome_0', \
        'the literal should have been resolved into an ending'
    assert 'dilemmaOutcome_0' in bank.played
    exit_door.sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_8'


# ------------------------------------------------------- reported bugs
def test_every_dilemma_sound_loops_except_the_abandoned_line():
    """-[PGEDilemma playSound:] ends in ``play:`` with ``mov w2, #1``.

    The baby calls until its state changes; it does not call once and go quiet.
    **The abandoned line is a REQUESTED exception** - it plays once and they
    settle back to resting, so the crying does not follow you round the level.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    baby = lv.agent('baby')
    assert baby.sound.looping, 'the resting call should loop'

    lv.player.position = (BABY[0] - 60.0, BABY[1])
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    lv.update(t + 0.1)
    assert baby.state == ALERT
    assert baby.sound.looping, 'and so should the one it calls out with'

    lv.player.position = (BABY[0] - 400.0, BABY[1])
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    lv.update(t + 0.2)
    assert baby.state == ABANDONED
    assert not baby.sound.looping, 'the crying after you gets one play'


def test_walking_away_from_a_lost_soul_leaves_them_resting_again():
    """REQUESTED 2026-09-15: the aware loop belongs inside the radius.

    The original has no way out of state 8 - ``checkCollisionsWithPlayer``
    only ever moves 9 -> 8 and every sound loops - so once you had been near
    someone, they called after you for the rest of the level.  Here the
    abandoned line is given one play and then they go back to the loop they
    started on.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    baby = lv.agent('baby')
    resting = baby._current_sound_name
    assert resting == baby.rest_sound

    def stand(x, when):
        lv.player.position = (x, BABY[1])
        bus.post('PGE_MESSAGE_PlayerMovedToPosition',
                 {'position': lv.player.position})
        lv.update(when)

    stand(BABY[0] - 60.0, t + 0.1)
    assert baby.state == ALERT
    assert baby._current_sound_name == baby.alert_sound

    stand(BABY[0] - 400.0, t + 0.2)
    assert baby.state == ABANDONED
    assert baby._current_sound_name == baby.abandon_sound

    # still saying its piece
    stand(BABY[0] - 400.0, t + 0.3)
    assert baby.state == ABANDONED, 'it should not be cut short'

    # and once the line is over, back to the loop it started on
    line = bank.sounds[baby.abandon_sound].duration
    stand(BABY[0] - 400.0, t + 0.2 + line + 0.05)
    assert baby.state == REST
    stand(BABY[0] - 400.0, t + 0.2 + line + 0.1)
    assert baby._current_sound_name == resting, 'back to the resting call'
    assert baby.sound.looping

    # coming back interrupts it the ordinary way
    stand(BABY[0] - 60.0, t + 0.2 + line + 0.2)
    assert baby.state == ALERT
    assert baby._current_sound_name == baby.alert_sound


def test_a_hog_standing_over_a_noise_ignores_the_guts_underfoot():
    """The guts alert on *every* step, and the hog must not restart on each.

    ``-[PGEEnemy alertEnemy:]`` drops a ``to=position`` alert whenever
    ``distractedTimer`` is not -1 (0x10001e428), and the timer runs for the
    whole time the enemy is standing at the place it was sent to.  Without
    that guard every footstep re-enters state 4 and the roar starts again.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    guts = [s for s in lv.floors if s.footsteps_prefix == 'foot_guts'][0]
    x, y, w, h = guts.rect
    lv.player.position = (x + w / 2.0, y + h / 2.0)

    # walk it into the searching state
    hog.change_state_to(AT_POSITION)
    for _ in range(2):
        t += 1.0 / 60.0
        bus.now = t
        lv.update(t)
    assert hog.distracted_timer >= 0.0

    quiet = hog._current_sound_name
    # The search lasts exactly as long as the "not there" grunt, because
    # state 6 overwrites distractedTime with that sound's own duration
    # (0x10001dc20) - 1 s in the fake bank.  Stay inside it.
    for _ in range(8):
        t += 0.1
        bus.now = t
        bus.post('PGE_MESSAGE_AlertAllEnemies',
                 {'to': 'position', 'position': lv.player.position})
        lv.update(t)
        if hog.state != AT_POSITION:
            break
    assert hog.state == AT_POSITION, \
        f'stepping on the guts re-alerted a busy hog ({hog.state_name})'
    assert hog._current_sound_name == quiet, 'and it changed its voice'


def test_walking_the_guts_snarls_once_and_then_just_chases():
    """The reported bug: the roar restarting under every footstep.

    ps1_7's guts fire ``AlertAllEnemies:to=position`` on every step, so the hog
    is re-alerted a dozen times crossing one patch.  What stops that being
    audible is ``hasWantedPosition`` (latched at 0x10001dbb4): the first alert
    snarls and starts the chase, and every alert after it takes the *other*
    branch of state 4, which re-aims silently.  State 5 then asks for the chase
    sound again on a name it is already playing, and ``playSound:`` refuses.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    guts = [s for s in lv.floors if s.footsteps_prefix == 'foot_guts'][0]
    x, y, w, h = guts.rect
    cx, cy = x + w / 2.0, y + h / 2.0

    dt = 1.0 / 60.0
    next_step = t + 0.45
    foot, n = LEFT, 0
    starts = []
    while t < 9.0:
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

    assert n >= 12, f'the walk should be a good dozen steps, was {n}'
    assert starts.count('monster_hog1_01_dry_chase') == 1, \
        f'the roar restarted: {starts}'
    assert starts.count('monster_hog1_01_dry_aware') == 1, \
        f'it snarled more than once: {starts}'


def test_going_down_snarls_even_when_the_hog_is_already_hunting():
    """[REQUESTED] The fall has to be answered by a sound.

    The latch in the test above is right, and on the guts it is what keeps the
    roar from restarting under every footstep.  But it also swallowed the one
    alert you most need to hear: trip while the hog is already on its way to a
    noise and ``hasWantedPosition`` is up, so state 4 re-aimed it in silence and
    the thing simply arrived.  Reported as "when I fall the hog follows
    immediately instead of sounding first".

    ``Player.trip`` now marks its alert, and a marked alert takes the
    fresh-alert arm whatever the latch says: the snarl, then the second's
    wind-up, then the chase.  DIVERGENCES 4c.
    """
    from papasangre.entities.monster import (ALERT_POSITION,       # noqa: PLC0415
                                             GO_TO_POSITION)
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    guts = [s for s in lv.floors if s.footsteps_prefix == 'foot_guts'][0]
    x, y, w, h = guts.rect
    cx, cy = x + w / 2.0, y + h / 2.0

    dt = 1.0 / 60.0
    foot = LEFT
    for n in range(4):                   # get it latched and on its way
        t += 0.6
        bus.now = t
        lv.player.position = (cx + (6 if n % 2 else -6), cy)
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        for _ in range(6):
            t += dt
            bus.now = t
            lv.update(t)
    assert hog.has_wanted_position or hog.state == GO_TO_POSITION,         f'the hog should already be hunting, it is {hog.state_name}'

    before = len(bank.played)
    lv.player.trip()
    t += dt
    bus.now = t
    lv.update(t)
    heard = [s for s in bank.played[before:] if s.startswith('monster')]
    assert 'monster_hog1_01_dry_aware' in heard,         f'falling brought it on in silence: {heard}'
    assert hog.state == ALERT_POSITION, hog.state_name

    for _ in range(30):                  # half a second in - still snarling
        t += dt
        bus.now = t
        lv.update(t)
    assert hog.state == ALERT_POSITION,         f'the snarl was cut short ({hog.state_name})'
    assert hog._current_sound_name == 'monster_hog1_01_dry_aware'

    for _ in range(45):                  # past the second, it comes for you
        t += dt
        bus.now = t
        lv.update(t)
    assert hog.state == GO_TO_POSITION, hog.state_name
    assert hog._current_sound_name == 'monster_hog1_01_dry_chase'


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
