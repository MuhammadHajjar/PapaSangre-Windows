"""Levels 11 to 25 - the back half of the game.

Levels 1 to 10 have a file each, because each one introduced something.  From
11 on the engine stops growing: every mechanic these levels use was already
built, and what changes is the arrangement.  So they are covered together,
one test per level for whatever that level is actually *for*, plus a sweep at
the end that walks the whole game from ps1_2 to the ending.

What the back half adds is not new code but new **mistakes in the shipped map
data** - six of them, none of which stop the game, all reproduced:

===========  ====================================================
ps1_11       a Surface's ``OnEnter`` is a bare sound list with no
             ``PlaySound:soundName=`` in front of it, so the two
             quicksand-edge atmospheres never play
ps1_19       ``AlertAllAgents:to=position`` - a message that does
             not exist in the binary at all (only ``AlertAllEnemies``
             does), so that trigger does nothing
ps1_21       ``ChangeInactivitySoundList_soundList=...`` - underscore
             where a colon belongs
ps1_24       ``ChangeInactivitySoundList=soundList=...`` - equals
             where a colon belongs, and a second note whose
             ``OnCollide`` is just a sound name
ps1_25       the intro activates ``note1``, which this level does
             not have
===========  ====================================================
"""

import glob
import json
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import autoplay                                                    # noqa: E402
from papasangre.assets.tiled import load_level                     # noqa: E402
from papasangre.entities.dilemma import Dilemma, THANKED           # noqa: E402
from papasangre.save import GameProgress                           # noqa: E402

EXPORTS = autoplay.EXPORTS

#: every level's successor, read from the data rather than assumed
CHAIN = [('ps1_2', 'ps1_3'), ('ps1_3', 'ps1_4'), ('ps1_4', 'ps1_5'),
         ('ps1_5', 'ps1_6'), ('ps1_6', 'ps1_7'), ('ps1_7', 'ps1_8'),
         ('ps1_8', 'ps1_9'), ('ps1_9', 'ps1_10'), ('ps1_10', 'ps1_11'),
         ('ps1_11', 'ps1_12'), ('ps1_12', 'ps1_13'), ('ps1_13', 'ps1_14'),
         ('ps1_14', 'ps1_15'), ('ps1_15', 'ps1_16'), ('ps1_16', 'ps1_17'),
         ('ps1_17', 'ps1_18'), ('ps1_18', 'ps1_19'), ('ps1_19', 'ps1_20'),
         ('ps1_20', 'ps1_21'), ('ps1_21', 'ps1_22'), ('ps1_22', 'ps1_23'),
         ('ps1_23', 'ps1_24'), ('ps1_24', 'ps1_25')]


def build(stem, progress=None):
    return autoplay.build(stem, progress)


def started(stem, progress=None):
    """Load, run the intro, and hand back everything with the level going."""
    bus, mi, bank, lv = build(stem, progress)
    lv.start(0.0)
    for a in lv.agents:
        if a.active and a.sound is not None:
            a.sound.stop()
    t = 1.0
    for s in (t, t + 0.1):
        bus.now = s
        lv.update(s)
    return bus, mi, bank, lv, t + 0.1


def collect(bus, lv, t, name):
    """Walk onto a thing and let its OnCollide land."""
    lv.player.position = lv.agent(name).position
    bus.post('PGE_MESSAGE_PlayerMovedToPosition',
             {'position': lv.player.position})
    for _ in range(6):
        t += 0.1
        bus.now = t
        lv.update(t)
    return t


def raw_triggers(stem):
    out = []
    d = json.load(open(os.path.join(EXPORTS, f'{stem}.json'),
                       encoding='utf-8', errors='replace'))
    for layer in d['layers']:
        if layer.get('name') == 'ToolBar':
            continue
        for o in layer.get('objects', []) or []:
            for k, v in (o.get('properties') or {}).items():
                if k.startswith('On'):
                    for part in str(v).split('|'):
                        if part:
                            out.append((o.get('name'), k, part))
    return out


# ------------------------------------------------------------------ 11
def test_ps1_11_quicksand_is_where_the_tripping_finally_bites():
    """The first level that caps your tempo hard, and names its own trip sound.

    ps1_11's surfaces set ``tripBPM`` 65 and 120 where everything before it ran
    at the loader's default of 280, and two of them name
    ``foot_sand-water_trip``.  65 is a genuine creep: the BPM counter reads
    75/interval, so it means better than a second between steps.
    """
    _bus, _mi, _bank, lv = build('ps1_11')
    bpms = sorted({s.trip_bpm for s in lv.floors})
    assert 65.0 in bpms and 120.0 in bpms, bpms
    named = [s.trip_sound for s in lv.floors if s.trip_sound]
    assert named and all(n == 'foot_sand-water_trip' for n in named), named
    assert lv.reverb_profile == 'outdoor'


def test_ps1_11_has_two_quicksand_edges_and_only_one_of_them_speaks():
    """The same line, typed twice, once correctly.

    One edge says ``PlaySound:soundName=quicksand_edge_atmos1&...``.  The other
    says just ``quicksand_edge_atmos1&quicksand_edge_atmos2`` - the sound list
    where the message name belongs, so nothing observes it.  Walk onto the
    first edge and you are warned; walk onto the second and you are not.
    """
    edges = [t for t in raw_triggers('ps1_11') if 'quicksand_edge' in t[2]]
    assert len(edges) == 2, edges
    good = [t for t in edges if t[2].startswith('PlaySound:')]
    bad = [t for t in edges if not t[2].startswith('PlaySound:')]
    assert len(good) == 1 and len(bad) == 1

    bus, _mi, bank, lv, t = started('ps1_11')
    quiet = [s for s in lv.floors
             if any('quicksand_edge' in str(tr.notification_name)
                    for tr in s.triggers)]
    assert len(quiet) == 1, 'exactly one surface carries the malformed trigger'
    before = len(bank.played)
    quiet[0].trigger_on_enter()                     # must not raise
    for _ in range(4):
        t += 0.1
        bus.now = t
        lv.update(t)
    assert not any('quicksand_edge' in n for n in bank.played[before:]), \
        'the malformed one must be silent'


# ------------------------------------------------------------------ 12
def test_ps1_12_the_old_man_slows_you_down_and_is_remembered():
    """dilemma_2.  Carrying him costs you 50 BPM off your top speed."""
    bus, _mi, bank, lv, t = started('ps1_12')
    old = lv.agent('oldman')
    assert isinstance(old, Dilemma) and old.dilemma_id == 'dilemma_2'
    assert lv.player.bpm_constraint == 0.0
    t = collect(bus, lv, t, 'oldman')
    assert old.collected and old.state == THANKED
    assert old.sound.looping, 'his voice loops like the baby s'
    assert lv.player.bpm_constraint == 50.0
    assert lv.progress.get_dilemma_status('dilemma_2') is False, \
        'not written until the exit solves the level'
    # two dilemmas deep by now, so the ending has two digits
    assert lv.solve_dilemmas() == 'dilemmaOutcome_0_1'
    assert 'dilemmaOutcome_0_1' in bank.sounds


# ------------------------------------------------------------------ 13-17
def test_ps1_13_and_14_are_the_wooden_decks():
    for stem, floors in (('ps1_13', 4), ('ps1_14', 50)):
        _bus, _mi, _bank, lv = build(stem)
        assert len(lv.floors) == floors, f'{stem} has {len(lv.floors)}'
        assert lv.reverb_profile == 'indoor'
    # ps1_14's fifty surfaces are the widest floor plan in the game
    _bus, _mi, _bank, lv = build('ps1_14')
    prefixes = {s.footsteps_prefix for s in lv.floors}
    assert prefixes <= {'foot_wood', 'foot_metalsolid', ''}, prefixes


def test_ps1_15_carries_a_chicken_that_is_not_part_of_the_chain():
    """``chicken_launcher_1`` is a Collectible the intro activates directly.

    It is not in the note chain and leads nowhere - an easter egg you can walk
    into or never find.  ps1_19, 21 and 23 have them too.
    """
    _bus, _mi, _bank, lv = build('ps1_15')
    chick = lv.agent('chicken_launcher_1')
    assert chick is not None
    assert not chick.next_collectible
    order = autoplay.chain(lv)
    assert order[:4] == ['note1', 'note2', 'note3', 'exit'], order
    assert 'chicken_launcher_1' in order


def test_ps1_16_is_a_xylophone_and_its_door_is_against_the_wall():
    """Fifteen surfaces, each a different melodic step, and an exit that sits
    exactly on the level boundary - which is how the autoplay harness found its
    own bug, not the game's."""
    _bus, _mi, _bank, lv = build('ps1_16')
    assert len(lv.floors) == 15
    melodic = {s.footsteps_prefix for s in lv.floors}
    assert len(melodic) >= 10, melodic
    assert all(p.startswith('foot_metalmelodic') or p.startswith('foot_melodicbum')
               for p in melodic if p), melodic
    x0, _y0, _w, _h = lv.rect
    assert abs(lv.agent('exit').position[0] - x0) < 1.0, 'the door is on the edge'


def test_ps1_17_has_a_chain_of_thirteen_summoners():
    """The longest collectible chain in the game, and it runs beside the notes."""
    _bus, _mi, _bank, lv = build('ps1_17')
    chain, name = [], 'summoner0'
    while name and lv.agent(name) is not None and name not in chain:
        chain.append(name)
        name = lv.agent(name).next_collectible
    assert chain == [f'summoner{i}' for i in range(13)], chain
    assert not lv.agent('summoner12').next_collectible


# ------------------------------------------------------------------ 18
def test_ps1_18_the_girl_gives_you_away():
    """dilemma_3.  Carrying her puts a 40 px radius on you that enemies hear."""
    bus, _mi, bank, lv, t = started('ps1_18')
    girl = lv.agent('girl')
    assert isinstance(girl, Dilemma) and girl.dilemma_id == 'dilemma_3'
    assert lv.player.proximity_radius == 0.0
    t = collect(bus, lv, t, 'girl')
    assert girl.collected and girl.sound.looping
    assert lv.player.proximity_radius == 40.0
    assert lv.player.bpm_constraint == 0.0, 'she costs a radius, not tempo'
    assert lv.solve_dilemmas() == 'dilemmaOutcome_0_0_1'
    assert 'dilemmaOutcome_0_0_1' in bank.sounds


def test_the_ending_tree_is_exactly_fourteen_sounds_deep():
    """Three levels ask: ps1_7 one deep, ps1_12 two, ps1_18 three.

    2 + 4 + 8 = 14 recorded endings, and every one of them must exist.
    """
    for stem, depth in (('ps1_7', 1), ('ps1_12', 2), ('ps1_18', 3)):
        _bus, _mi, bank, lv = build(stem)
        assert lv.agent('exit').collect_sound == 'dilemmaOutcome'
        assert len(lv.solve_dilemmas().split('_')) == depth + 1
        import itertools                                         # noqa: PLC0415
        for bits in itertools.product((0, 1), repeat=depth):
            name = 'dilemmaOutcome_' + '_'.join(str(b) for b in bits)
            assert name in bank.sounds, f'{stem}: {name} missing'


# ------------------------------------------------------------------ 19-22
def test_ps1_19_alerts_nobody_because_the_message_does_not_exist():
    """``AlertAllAgents:to=position``.

    The binary contains ``PGE_MESSAGE_AlertAllEnemies`` and nothing else of
    that shape - ``AlertAllAgents`` appears zero times.  So this trigger, which
    reads like it should wake the hog, does nothing at all.  Reproduced.
    """
    bad = [t for t in raw_triggers('ps1_19') if t[2].startswith('AlertAllAgents')]
    assert len(bad) == 2, bad        # two surfaces, both misspelt the same way
    from papasangre.entities.monster import IDLE                 # noqa: PLC0415
    bus, _mi, _bank, lv, t = started('ps1_19')
    hog = lv.agent('hog1')
    assert hog.state == IDLE
    bus.post('PGE_MESSAGE_AlertAllAgents', {'to': 'position'})
    for _ in range(6):
        t += 0.1
        bus.now = t
        lv.update(t)
    assert hog.state == IDLE, 'nothing observes that message'


def test_ps1_19_slowing_down_for_the_ice_actually_saves_you():
    """The ice bug: ``setTripBPM:`` throws the tempo history away.

    ps1_19's first ice band starts four steps from where you are put down, and
    it caps you at ``tripBPM`` 80 where the snow around it runs at the loader's
    280.  ``checkStepBPM`` runs **before** the new step is recorded and averages
    the last four intervals, so the reading you are judged on as you take your
    second step on the ice was built entirely out of the snow steps behind you.

    ``-[PGEPlayer setTripBPM:]`` (0x100025e38) is what makes that survivable:
    the value changing calls ``resetBPM``, so the ice is measured only from
    steps taken on the ice.  Without it, walking the snow at a normal pace and
    then creeping across the ice read 113 BPM against a limit of 80 and put you
    down every single time, however slowly you went - reported from ps1_19 and
    ps1_23 as six slow steps and then a random fall.
    """
    from papasangre.input.interpreter import LEFT, RIGHT          # noqa: PLC0415
    ice = [s for s in build('ps1_19')[3].floors if s.trip_bpm == 80.0]
    assert len(ice) == 2, 'two bands, both at 80'
    lo, hi = ice[1].rect[1], ice[1].rect[1] + ice[1].rect[3]
    assert lo < 0 < hi + 200, (lo, hi)

    bus, mi, _bank, lv, t = started('ps1_19')
    mi.player_can_walk = True
    mi.feet = {LEFT: 'on', RIGHT: 'on'}
    p, foot, tripped, on_ice_steps = lv.player, LEFT, [], 0
    for _ in range(14):
        on_ice = any(s.contains(*p.position) for s in ice)
        t += 1.20 if on_ice else 0.70    # brisk on the snow, a crawl on the ice
        bus.now = t
        if mi.foot_pressed(foot):
            mi.foot_released(foot, t)
            on_ice_steps += any(s.contains(*p.position) for s in ice)
            if p.state == 3:
                tripped.append((round(t, 2), round(p.position[1], 1),
                                round(p.walk_bpm, 1)))
            foot = RIGHT if foot is LEFT else LEFT
        lv.update(t)
    assert not tripped, f'creeping across the ice still fell: {tripped}'
    assert on_ice_steps >= 5, f'only {on_ice_steps} steps landed on the ice'


def test_ps1_19_the_ice_can_be_walked_at_the_tempo_its_data_allows():
    """The softlock: three free steps, a fall, three free steps, a fall.

    ps1_19's ice says ``tripBPM`` 80, which is 0.75 s a step. Under the
    original's fencepost the three-stamp reading was 50% high, so it actually
    tripped you above 53 BPM - and ``resetBPM`` runs on **every trip**, so going
    down put you back at three stamps with the threshold at its strictest. Seven
    steps to cross a band and a fall every fourth step is a band you never
    leave: "even if I walk very very slowly... like a softlock".

    0.9 s a step is 67 BPM, comfortably inside what the level authorises, so it
    must cross both bands without a single fall.
    """
    from papasangre.input.interpreter import LEFT, RIGHT          # noqa: PLC0415
    bus, mi, _bank, lv, t = started('ps1_19')
    ice = [s for s in lv.floors if s.trip_bpm == 80.0]
    mi.player_can_walk = True
    mi.feet = {LEFT: 'on', RIGHT: 'on'}
    p, foot, tripped, on_ice = lv.player, LEFT, [], 0
    for _ in range(40):
        t += 0.90
        bus.now = t
        judged = p.walk_bpm           # what checkStepBPM will compare
        if mi.foot_pressed(foot):
            mi.foot_released(foot, t)
            on_ice += any(s.contains(*p.position) for s in ice)
            if p.state == 3:
                tripped.append((round(p.position[1], 1), round(judged, 1)))
            foot = RIGHT if foot is LEFT else LEFT
        lv.update(t)
    assert not tripped, f'67 BPM fell on ground authored for 80: {tripped}'
    assert on_ice >= 12, f'only {on_ice} steps landed on ice, expected both bands'


def test_tripbpm_only_resets_the_tempo_when_the_ground_really_changes():
    """The other half of ``setTripBPM:`` - the equality test at 0x100025e44.

    ``playerMovedToPosition:`` sends it on every step, so without that test the
    history would be wiped on every step and nothing could ever trip.
    """
    from papasangre.core.messages import MessageBus               # noqa: PLC0415
    from papasangre.entities.player import Player                 # noqa: PLC0415
    p = Player(MessageBus())
    p.walk_times = [0.0, 1.0, 2.0]
    p.trip_bpm = 10000.0                 # what it already is
    assert p.walk_times == [0.0, 1.0, 2.0], 'no change, no reset'
    p.trip_bpm = 80.0
    assert p.walk_times == [], 'crossing onto different ground clears it'


def test_a_bpm_constraint_locks_out_every_surface_for_the_rest_of_the_level():
    """ps1_23's siren, and ps1_12's old man: 0x100025e58.

    ``ApplyBpmConstraint:value=50`` stores the constraint, and from then on
    ``setTripBPM:`` returns without doing anything - so the surface you step on
    next cannot hand your old tempo back.  A plain assignment let the very next
    step undo the dilemma, which meant carrying them cost nothing.
    """
    from papasangre.entities.dilemma import Dilemma               # noqa: PLC0415
    bus, _mi, _bank, lv, t = started('ps1_23')
    siren = [a for a in lv.agents if isinstance(a, Dilemma) and a.name == 'siren']
    assert siren, 'ps1_23 carries the siren'
    t = collect(bus, lv, t, 'siren')
    assert lv.player.bpm_constraint == 50.0
    assert lv.player.trip_bpm == 50.0
    # now stand on the ice, whose surfaces carry the loader's 280
    lv.player.position = (0.0, -100.0)
    bus.post('PGE_MESSAGE_PlayerMovedToPosition',
             {'position': lv.player.position})
    assert lv.player.trip_bpm == 50.0, 'the constraint outlasts the ground'


def test_ps1_20_and_22_are_the_snowfields():
    for stem in ('ps1_20', 'ps1_22'):
        _bus, _mi, _bank, lv = build(stem)
        grounds = {s.footsteps_prefix for s in lv.floors} | {lv.footsteps_prefix}
        assert grounds & {'foot_snow', 'foot_icethin'}, grounds
        assert lv.reverb_profile == 'outdoor', stem


def test_ps1_21_has_a_note_that_reorders_nothing():
    """``ChangeInactivitySoundList_soundList=`` - underscore, not colon."""
    bad = [t for t in raw_triggers('ps1_21') if '_soundList=' in t[2]]
    assert len(bad) == 1 and bad[0][0] == 'note2', bad
    bus, _mi, _bank, lv, t = started('ps1_21')
    lv.agent('note2').active = True
    before = list(lv.inactivity_sounds)
    t = collect(bus, lv, t, 'note2')
    assert lv.agent('note2').was_collected
    assert lv.inactivity_sounds == before, 'the misspelt message must do nothing'
    assert lv.reverb_profile == 'indoor', 'the glass cathedral is a building'


# ------------------------------------------------------------------ 23-24
def test_ps1_23_the_siren_is_recorded_but_never_spoken_of():
    """dilemma_4 - the last choice, and the only one no level ever reads.

    ps1_23's own door plays a fixed ``FINAL_IceLake_Win``, not the tree, and
    ps1_25's two endings are fixed as well.  So the siren is written to the
    save file and nothing ever asks about it again.  Faithful: the tree only
    goes three deep because only three levels ask.
    """
    bus, _mi, bank, lv, t = started('ps1_23')
    siren = lv.agent('siren')
    assert isinstance(siren, Dilemma) and siren.dilemma_id == 'dilemma_4'
    t = collect(bus, lv, t, 'siren')
    assert siren.collected
    assert lv.player.bpm_constraint == 50.0, 'she costs tempo, like the old man'
    assert lv.agent('exit').collect_sound == 'FINAL_IceLake_Win'
    assert lv.agent('exit').collect_sound != 'dilemmaOutcome'
    assert 'dilemmaOutcome_0_0_0_1' not in bank.sounds, \
        'a four-deep ending was never recorded, because nothing asks'


def test_ps1_24_note_one_is_misspelt_and_note_two_is_not():
    """The fate bell's data has the worst of the six mistakes, and a near miss.

    note1 says ``ChangeInactivitySoundList=soundList=...`` - equals where a
    colon belongs, so it is never understood.  note2 carries *two* messages:
    one spelt correctly and one that is simply a sound name.  So the first note
    changes nothing and the second one works.
    """
    broken = [t for t in raw_triggers('ps1_24')
              if t[2].startswith('ChangeInactivitySoundList=')
              or t[2].startswith('FINAL_thefatebell')]
    assert {b[0] for b in broken} == {'note1', 'note2'}, broken
    good = {t[0] for t in raw_triggers('ps1_24')
            if t[2].startswith('ChangeInactivitySoundList:')}
    assert good == {'note2', 'note3'}, good
    assert 'note1' not in good, 'the first note is the one that never works'

    bus, _mi, _bank, lv, t = started('ps1_24')
    before = list(lv.inactivity_sounds)
    lv.agent('note1').active = True
    t = collect(bus, lv, t, 'note1')
    assert lv.agent('note1').was_collected
    assert lv.inactivity_sounds == before, 'note1 is not understood at all'

    lv.agent('note2').active = True
    t = collect(bus, lv, t, 'note2')
    assert lv.agent('note2').was_collected
    assert lv.inactivity_sounds == ['FINAL_thefatebell_inactive_1_C'], \
        'note2 has one message that does parse'


# ------------------------------------------------------------------ 25
def test_ps1_25_offers_two_doors_and_either_one_ends_the_game():
    """Elysium.  A field, Papa talking as you cross it, and a choice.

    ``elysium_goodDoor`` plays *You Die* and ``elysium_badDoor`` plays *She
    Dies* - and both of them finish with ``PresentAdiosVC``, which in the
    original puts up the goodbye screen and starts the menu atmosphere.  Here
    it means: there is no next level, the game is over.
    """
    for door, sound in (('elysium_goodDoor', 'FINAL_Elysium_Win_YouDie'),
                        ('elysium_badDoor', 'FINAL_Elysium_Fail_SheDies')):
        bus, _mi, bank, lv, t = started('ps1_25')
        assert not lv.game_complete
        assert lv.agent(door).collect_sound == sound
        t = collect(bus, lv, t, door)
        assert lv.agent(door).was_collected
        for a in lv.agents:
            if a.sound is not None:
                a.sound.stop()
        for _ in range(8):
            t += 0.5
            bus.now = t
            lv.update(t)
        assert lv.game_complete, f'{door} should end the game'
        assert lv.finished and lv.next_level is None
        assert sound in bank.played


def test_ps1_25_papa_speaks_from_four_patches_of_field():
    _bus, _mi, bank, lv = build('ps1_25')
    assert len(lv.floors) == 4
    said = set()
    for s in lv.floors:
        assert s.footsteps_prefix == 'foot_field'
        for tr in s.triggers:
            said.add(tr.parameters.get('soundName'))
    assert said == {f'FINAL_Elysium_papa{i}' for i in range(1, 5)}, said
    for name in said:
        assert name in bank.sounds


def test_ps1_25_intro_activates_a_note_that_is_not_there():
    """The last of the six data mistakes, and the most harmless."""
    data = load_level(os.path.join(EXPORTS, 'ps1_25.json'), 'ps1_25')
    intro = [o for o in data.objects if o.name == 'FINAL_Elysium_Intro'][0]
    wanted = {t.parameters.get('name') for t in intro.triggers
              if 'ActivateAgentWithName' in t.notification_name}
    assert 'note1' in wanted
    assert not any(o.name == 'note1' for o in data.objects)
    _bus, _mi, _bank, lv, _t = started('ps1_25')    # must not raise
    assert lv.agent('elysium_goodDoor').active, 'the rest of the chain ran'
    assert lv.agent('elysium_badDoor').active


# --------------------------------------------------------- the whole game
def test_every_level_hands_on_to_the_next_one():
    """Walk the game end to end and check the chain is unbroken.

    Hunters are off: this is checking that every level's collectible chain,
    doors and exit work and lead where they should, not whether a bot can
    outrun a hog at 30 px/s.  The hunters have their own tests.
    """
    for stem, expected in CHAIN:
        r = autoplay.play(stem, peaceful=True)
        assert r['error'] is None, f'{stem}: {r["error"]}'
        assert r['complete'], f'{stem} did not finish (got {r["collected"]})'
        assert r['next'] == expected, \
            f'{stem} handed on to {r["next"]}, expected {expected}'


def test_the_last_level_ends_the_game_rather_than_loading_another():
    r = autoplay.play('ps1_25', peaceful=True)
    assert r['error'] is None
    assert r['game_complete'], 'ps1_25 should finish the game'
    assert r['next'] is None


def test_no_level_anywhere_fails_to_load():
    stems = ['ps1_1', 'ps1_1b'] + [f'ps1_{i}' for i in range(2, 26)]
    for stem in stems:
        _bus, _mi, _bank, lv = build(stem)
        assert lv.player is not None, f'{stem} has no player'
        assert lv.rect[2] > 0 and lv.rect[3] > 0, f'{stem} has no room'
        assert lv.agents, f'{stem} has no agents'


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


def test_the_girl_screams_when_something_comes_near_and_only_once():
    """Reported after 1.0.1: "the little girl's scream mechanic doesn't work
    at all... when I got really close to the hog, she didn't scream".

    It did not, and the reason it was missed is that **no level mentions the
    sound**.  ``dilemma_girl_monsterprox`` is hardcoded in ``alertEnemy:``
    at 0x10001e274; ps1_18 only gives the girl an
    ``ApplyProximityRadiusToPlayer:value=40`` on collide, and the scream comes
    out of the enemy that walks into that radius.  ``withinRadius`` is the
    edge: she gives you away once per approach, not once per step.
    """
    from papasangre.entities.monster import GIRL_PROXIMITY_SOUND  # noqa: PLC0415
    bus, _mi, bank, lv, t = started('ps1_18')
    for n in ('note1', 'hog1', 'girl'):
        bus.post('PGE_MESSAGE_ActivateAgentWithName', {'name': n})
    t += 0.1
    bus.now = t
    lv.update(t)
    hog = lv.agent('hog1')

    t = collect(bus, lv, t, 'girl')
    assert lv.agent('girl').collected, 'she has to be carried first'
    assert lv.player.proximity_radius == 40.0

    bank.played.clear()
    hog.position = (lv.player.position[0] + 10.0, lv.player.position[1])
    hog.player_position = lv.player.position
    bus.post('PGE_MESSAGE_AlertEnemiesWithinRadius',
             {'radius': str(lv.player.proximity_radius), 'to': 'player'})
    t += 0.1
    bus.now = t
    lv.update(t)
    assert GIRL_PROXIMITY_SOUND in bank.played, 'she never gave you away'
    assert hog.within_radius

    # a second step with the hog still on top of you must not scream again
    bank.played.clear()
    bus.post('PGE_MESSAGE_AlertEnemiesWithinRadius',
             {'radius': str(lv.player.proximity_radius), 'to': 'player'})
    t += 0.1
    bus.now = t
    lv.update(t)
    assert GIRL_PROXIMITY_SOUND not in bank.played, 'once per approach'

    # walk away, come back, and she gives you away again
    hog.player_position = (lv.player.position[0] + 500.0, lv.player.position[1])
    bus.post('PGE_MESSAGE_AlertEnemiesWithinRadius',
             {'radius': str(lv.player.proximity_radius), 'to': 'player'})
    t += 0.1
    bus.now = t
    lv.update(t)
    assert not hog.within_radius, 'leaving has to clear the latch'
    bank.played.clear()
    hog.player_position = lv.player.position
    bus.post('PGE_MESSAGE_AlertEnemiesWithinRadius',
             {'radius': str(lv.player.proximity_radius), 'to': 'player'})
    t += 0.1
    bus.now = t
    lv.update(t)
    assert GIRL_PROXIMITY_SOUND in bank.played


def test_nothing_is_still_playing_after_a_level_shuts_down():
    """Reported after 1.0.1: "in certain moments, sounds keep playing... in
    level 23 when you go to the exit, if the chickens haven't been released,
    the cage loop will keep playing".

    ``deactivate`` fires ``OnDeactivate`` whether or not the agent was ever
    active, and ps1_23's ``chicken_1`` answers that by re-arming the cage
    launcher.  Landing behind the shutdown sweep, the launcher came back to
    life with its alarm looping and nothing left to stop it.  The condition
    the player spotted is exact: it only happens with the chickens still
    caged, because a released ``chicken_1`` has already re-armed the launcher
    earlier and the sweep then finds it in the ordinary way.
    """
    for stem in ('ps1_23', 'ps1_7', 'ps1_17', 'ps1_25'):
        bus, _mi, bank, lv = build(stem)
        lv.start(0.0)
        t = 0.5
        bus.now = t
        lv.update(t)
        for _ in range(20):
            t += 0.1
            bus.now = t
            lv.update(t)
        bus.post('PGE_MESSAGE_ShutDownLevel', {'name': 'exit'})
        for _ in range(5):
            t += 0.1
            bus.now = t
            lv.update(t)
        still = [n for n, s in bank.sounds.items() if getattr(s, 'playing', False)]
        assert not still, f'{stem} left {still} playing past the exit'


def test_the_third_note_of_papa_sangre_says_can_be_heard():
    """Reported after 1.0.1: "the third note in the papa says level doesn't
    spawn properly. You can still collect it by following the guide's voice,
    but you never actually hear it".

    Exactly right, and it is the original's own data: ps1_17's ``note3`` is
    the only collectible in the game with an empty ``loopSound``, and ps1_17's
    playlist is the only one of the five brass levels that does not carry the
    d note.  Every sibling - 13, 14, 15, 16, 18 - gives its third note
    ``note_brass_01_dry_d_living_+5``.  Filling it in is a **divergence**, not
    a recovery.
    """
    bus, _mi, bank, lv = build('ps1_17')
    note3 = lv.agent('note3')
    assert note3.loop_sound == lv.THIRD_NOTE
    # and the levels that were never broken are untouched
    for stem in ('ps1_13', 'ps1_16', 'ps1_18'):
        _b, _m, _bk, other = build(stem)
        assert other.agent('note3').loop_sound == 'note_brass_01_dry_d_living_+5'


def test_the_siren_does_not_fall_silent_after_you_walk_away():
    """ps1_23 is the one level where this could go wrong.

    Every other lost soul has three different files; the siren's
    ``abandonSound`` **is** her ``restSound`` - `dilemma_siren_living` both
    times.  So walking away plays that file once, and settling back to resting
    asks ``play_sound`` for the name it already has.  Guarded on the name
    alone, it would return without restoring the loop, and she would go quiet
    for the rest of the level the moment the one-shot ended.
    """
    from papasangre.entities.dilemma import ALERT, ABANDONED, REST  # noqa: PLC0415
    bus, _mi, bank, lv = build('ps1_23')
    lv.start(0.0)
    t = 0.5
    bus.now = t
    lv.update(t)
    bus.post('PGE_MESSAGE_ActivateAgentWithName', {'name': 'siren'})
    t += 0.1
    bus.now = t
    lv.update(t)
    siren = lv.agent('siren')
    assert siren.abandon_sound == siren.rest_sound, 'the whole point of this test'

    def stand(dx, when):
        lv.player.position = (siren.position[0] + dx, siren.position[1])
        bus.post('PGE_MESSAGE_PlayerMovedToPosition',
                 {'position': lv.player.position})
        bus.now = when
        lv.update(when)

    stand(30.0, t + 0.1)
    assert siren.state == ALERT
    stand(600.0, t + 0.2)
    assert siren.state == ABANDONED
    assert not siren.sound.looping, 'the line gets one play'

    line = bank.sounds[siren.abandon_sound].duration
    stand(600.0, t + 0.2 + line + 0.1)
    assert siren.state == REST
    assert siren.sound.looping, 'she has to be back on a loop, not silent'
    assert siren.sound.playing


def test_the_ice_lake_cage_runs_its_whole_cycle_and_leaves_nothing_hanging():
    """ps1_23's cage, from springing it to being ready again.

    Only testable since the fake sounds began ending on their own: every step
    of this is driven by a sound finishing or a timer expiring.  Walking into
    ``chicken_launcher_1`` plays its collect sound and activates ``chicken_1``,
    whose ``OnActivate`` alerts the hog and schedules its own deactivation 20
    seconds later; that deactivation re-arms the launcher.  Reported after
    1.0.5 as the chickens still being heard once the hog had settled, so what
    this pins is that nothing is left running at either end.
    """
    bus, _mi, _bank, lv = build('ps1_23')
    lv.start(0.0)
    t = 0.5
    bus.now = t
    lv.update(t)
    for n in ('chicken_launcher_1', 'hog1'):
        bus.post('PGE_MESSAGE_ActivateAgentWithName', {'name': n})
    for _ in range(10):
        t += 0.1
        bus.now = t
        lv.update(t)
    launcher = lv.agent('chicken_launcher_1')
    chicken = lv.agent('chicken_1')

    def playing(agent):
        s = getattr(agent, 'sound', None)
        return s is not None and s.playing

    lv.player.position = launcher.position
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    for _ in range(6):
        t += 0.1
        bus.now = t
        lv.update(t)
    assert chicken.active, 'springing the cage lets the chickens out'
    assert playing(chicken)

    # stand well clear so the hog cannot reach the player and end the level
    far = (launcher.position[0] + 4000.0, launcher.position[1] + 4000.0)
    lv.player.position = far
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': far})
    for a in lv.agents:
        a.player_position = far

    while t < 5.0:                       # the collect sound is long over
        t += 0.1
        bus.now = t
        lv.update(t)
    assert not launcher.collected, 'the collect sound ending re-arms the cage'
    assert launcher._phase == 'idle'

    while t < 25.0:                      # past chicken_1's 20 second timer
        t += 0.1
        bus.now = t
        lv.update(t)
    assert not chicken.active, 'the chickens stop on their own timer'
    assert not playing(chicken), 'and they are not left squawking'
    assert launcher.active, 'the cage comes back ready to be sprung again'
