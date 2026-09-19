"""Regression tests for level 3 "The Kennel" and the enemy state machine.

Level 3 is the first level with a monster, and it is built entirely around
listening: a hog sleeps in the middle of the room, four concentric floor rings
around it swap your footstep sound so you can tell how close you are, and
touching it kills you.  Nothing ever wakes it - that is the design.
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from papasangre.core.messages import MessageBus                   # noqa: E402
from papasangre.entities.monster import (ALERT_POSITION,          # noqa: E402
                                         AT_POSITION, ATTACK,
                                         CHASE_PLAYER, GO_TO_POSITION,
                                         IDLE, RETURNING, Monster)
from papasangre.input.interpreter import (LEFT, RIGHT,            # noqa: E402
                                          MoveInterpretor)
from papasangre.world.level import Level                          # noqa: E402
from test_level import FakeBank                                   # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')

LEVEL3_SOUNDS = [
    'FINAL_Kennel_Intro', 'atmos_stonepulselow_01', 'atmos_stonebreath_01',
    'FINAL_Kennel_Fail', 'FINAL_Kennel_Win', 'note_appear',
    'note_bone_01_dry_a_living', 'FINAL_thekennel_notecollect_1',
    'door_castle_appear', 'door_castle_living',
    'monster_hog1_01_dry_still', 'monster_hog1_01_dry_aware',
    'monster_hog1_01_dry_chase', 'monster_hog1_01_dry_notthere',
    'FINAL_carefulyouarenearthehog', 'easteregg_FWcareful',
    'easteregg_aroundcaveatmos', 'foot_stone_s1_L_a', 'foot_kennel_s1_L_a',
    'foot_stone-kennelA_s1_L', 'foot_stone-kennelB_s1_L',
    'foot_stone-kennelC_s1_L', 'foot_stone_shuffle', 'foot_kennel_shuffle',
    'foot_stone-kennel_shuffle',
    # Three names containing "trip" reach ps1_3's playlist: two through the
    # nested stone and kennel footstep lists, and the third declared by ps1_3
    # itself.  That is exactly why its surfaces name a `tripSound`.
    'foot_stone_trip', 'foot_kennel_trip', 'foot_stone-kennel_trip',
]


def build():
    bus = MessageBus()
    interp = MoveInterpretor(bus)
    bank = FakeBank(LEVEL3_SOUNDS, clock=lambda: bus.now)
    level = Level(bus, bank).load(os.path.join(EXPORTS, 'ps1_3.json'), 'ps1_3')
    return bus, interp, bank, level


def start(bus, lv, t=0.5):
    lv.start(0.0)
    lv.agent('FINAL_Kennel_Intro').sound.stop()
    for step in (t, t + 0.1):
        bus.now = step
        lv.update(step)
    return t + 0.1


def walk_towards(bus, mi, lv, target, t, limit=200, interval=0.5):
    p = lv.player
    foot = LEFT
    for _ in range(limit):
        dx = target[0] - p.position[0]
        dy = target[1] - p.position[1]
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += interval
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if lv.shutting_down:
            break
    return t


# ---------------------------------------------------------------- loading
def test_level_3_has_a_monster_with_its_recovered_defaults():
    _bus, _mi, _bank, lv = build()
    hog = lv.agent('hog1')
    assert isinstance(hog, Monster)
    assert hog.default_sound == 'monster_hog1_01_dry_still'
    assert hog.chase_sound == 'monster_hog1_01_dry_chase'
    assert hog.aware_sound == 'monster_hog1_01_dry_aware'
    assert hog.not_there_sound == 'monster_hog1_01_dry_notthere'
    assert hog.chase_speed == 30.0
    assert hog.collide_radius == 20.0      # -[PGEGameAgent init]
    assert hog.active is False             # the intro activates it


def test_the_four_floor_rings_are_layered_around_the_hog():
    _bus, _mi, _bank, lv = build()
    rings = {s.footsteps_prefix: s for s in lv.floors if s.footsteps_prefix}
    for name in ('foot_kennel', 'foot_stone-kennelC', 'foot_stone-kennelB',
                 'foot_stone-kennelA'):
        assert name in rings, name
    # each ring is bigger than the one inside it, and all are above the room
    areas = [(rings[n].rect[2] * rings[n].rect[3], n) for n in
             ('foot_kennel', 'foot_stone-kennelC', 'foot_stone-kennelB',
              'foot_stone-kennelA')]
    assert areas == sorted(areas), areas
    assert all(s.z == 2 for s in lv.floors)


# ---------------------------------------------------------------- sleeping
def test_the_hog_sleeps_and_loops_its_own_sound_where_it_stands():
    bus, mi, bank, lv = build()
    start(bus, lv)
    hog = lv.agent('hog1')
    assert hog.active
    assert hog.state == IDLE
    assert hog.sound is not None
    assert hog.sound.name == 'monster_hog1_01_dry_still'
    assert hog.sound.looping
    assert hog.sound.spatialized
    assert hog.sound.planar[:2] == hog.position


def test_nothing_in_the_level_ever_wakes_the_hog():
    """No trigger in ps1_3 sends an alert - the hog is an obstacle, not a hunter."""
    from papasangre.assets.tiled import load_level
    data = load_level(os.path.join(EXPORTS, 'ps1_3.json'), 'ps1_3')
    alerts = [t.notification_name
              for o in ([data.room] + data.objects + [data.player]) if o
              for t in o.triggers if 'Alert' in t.notification_name]
    assert alerts == [], alerts


def test_walking_in_changes_the_footsteps_ring_by_ring():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    banks = []
    p = lv.player
    foot = LEFT
    for _ in range(200):
        dx = hog.position[0] - p.position[0]
        dy = hog.position[1] - p.position[1]
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += 0.5
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if not banks or banks[-1] != p.footsteps_prefix:
            banks.append(p.footsteps_prefix)
        if lv.shutting_down:
            break
    assert banks == ['foot_stone', 'foot_stone-kennelA', 'foot_stone-kennelB',
                     'foot_stone-kennelC', 'foot_kennel'], banks


def test_touching_the_hog_ends_the_level_and_replays_it():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    walk_towards(bus, mi, lv, hog.position, t)
    assert lv.shutting_down, 'walking into the hog should end the level'
    fail = lv.agent('FINAL_Kennel_Fail')
    assert fail.active, 'the failure narration should be playing'
    fail.sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_3', 'failing should restart the same level'


# ------------------------------------------------------- the state machine
def test_an_alert_makes_a_monster_chase_the_player():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    assert hog.state == IDLE

    bus.now = t
    bus.post('PGE_MESSAGE_AlertAllEnemies', {'to': 'player'})
    lv.update(t)
    assert hog.state == CHASE_PLAYER

    before = math.dist(hog.position, lv.player.position)
    for _ in range(30):
        t += 0.1
        bus.now = t
        lv.update(t)
    after = math.dist(hog.position, lv.player.position)
    assert after < before - 50, f'the hog should close in ({before:.0f} -> {after:.0f})'
    assert hog.sound.name == 'monster_hog1_01_dry_chase'
    assert hog.speed == hog.chase_speed


def test_a_chasing_monster_ignores_further_player_alerts():
    """``alertEnemy:`` returns early once it is already after you."""
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    bus.now = t
    bus.post('PGE_MESSAGE_AlertAllEnemies', {'to': 'player'})
    lv.update(t)
    # the chase entry work runs on the following frame, guarded by
    # state_at_previous_frame, so let it happen before planting the marker
    t += 0.1
    bus.now = t
    lv.update(t)
    hog.position_before_chasing = (999.0, 999.0)     # reset only on re-entry

    t += 0.1
    bus.now = t
    bus.post('PGE_MESSAGE_AlertAllEnemies', {'to': 'player'})
    lv.update(t)
    assert hog.state == CHASE_PLAYER
    assert hog.position_before_chasing == (999.0, 999.0),         'a second alert should not restart the chase'


def test_alert_by_name_only_reaches_that_monster():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    bus.now = t
    bus.post('PGE_MESSAGE_AlertEnemyWithName', {'name': 'somebody_else',
                                                'to': 'player'})
    lv.update(t)
    assert hog.state == IDLE
    bus.post('PGE_MESSAGE_AlertEnemyWithName', {'name': 'hog1', 'to': 'player'})
    lv.update(t)
    assert hog.state == CHASE_PLAYER


def test_alert_within_radius_only_reaches_monsters_that_are_close():
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    far = math.dist(hog.position, lv.player.position)

    bus.now = t
    bus.post('PGE_MESSAGE_AlertEnemiesWithinRadius',
             {'radius': str(far / 2), 'to': 'player'})
    lv.update(t)
    assert hog.state == IDLE, 'a distant monster should not hear it'

    bus.post('PGE_MESSAGE_AlertEnemiesWithinRadius',
             {'radius': str(far * 2), 'to': 'player'})
    lv.update(t)
    assert hog.state == CHASE_PLAYER


def test_a_named_trip_sound_is_looked_up_exactly():
    """``-[PGEPlayer trip:]`` has two arms and they are different lookups.

    With a `tripSound` it is `[playlist S3DSound: tripSound]` - exact.  Without
    one it is `anySoundContaining:@"trip"`, which picks at random.  ps1_3's
    four kennel rings all name `foot_stone-kennel_trip`, and the level's
    playlist also pulls in `foot_stone_trip` and `foot_kennel_trip` through its
    nested footstep lists - so the random arm would be wrong two times in
    three, and naming the sound is how the level avoids that.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    rings = [s for s in lv.floors if s.trip_sound]
    assert rings, 'the kennel rings should name a trip sound'
    assert all(s.trip_sound == 'foot_stone-kennel_trip' for s in rings)

    x, y, w, h = rings[0].rect
    lv.player.position = (x + w / 2.0, y + h / 2.0)
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    lv.update(t)
    assert lv.player.trip_sound == 'foot_stone-kennel_trip'

    before = len(bank.played)
    lv.player.trip()
    assert bank.played[before:] == ['foot_stone-kennel_trip'], \
        f'the named sound should be played exactly: {bank.played[before:]}'


def test_a_monster_alerted_to_a_place_goes_to_where_you_were():
    """``to=position`` does not carry a destination - state 4 invents one.

    The notification built by a surface trigger does have a ``position`` key
    (the trigger owner's own position), but ``-[PGEEnemy alertEnemy:]`` never
    reads it on this branch: ``to=position`` jumps straight to the release at
    0x10001e5a4.  It is state 4 that sets the goal, and it sets it to
    ``playerPosition`` (0x10001dabc, ivar 40) - "Going to last player
    position".  So a noise sends the hog to *you*, not to the noise.

    State 4 also schedules ``changeStateTo:5`` with ``afterDelay:1.0``, but
    that second never actually elapses: the same frame latches
    ``hasWantedPosition``, and on the *next* frame the other branch of state 4
    changes the state at once.  The delayed call lands a second later on an
    enemy that has long since moved on.  Reproduced, dead code included.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    hog.distracted_time = 1.0
    lv.player.position = (60.0, 60.0)
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})

    bus.now = t
    # the position in the notification is deliberately nowhere near the player
    bus.post('PGE_MESSAGE_AlertAllEnemies',
             {'to': 'position', 'position': (-300.0, -300.0)})
    lv.update(t)
    assert hog.state == ALERT_POSITION, hog.state_name
    assert hog.wanted_position == (60.0, 60.0),         f'it should head for the player, not the noise: {hog.wanted_position}'
    assert hog.sound.name == 'monster_hog1_01_dry_aware'

    assert hog.has_wanted_position, 'the latch goes up on the first frame'

    # and the next frame takes the other branch of state 4, straight into the
    # chase - it does not wait out the second it just scheduled
    t += 1.0 / 60.0
    bus.now = t
    lv.update(t)
    assert hog.state == GO_TO_POSITION, hog.state_name

    # from here on it is chasing, and further noises must not re-snarl at it
    for _ in range(20):
        t += 1.0 / 60.0
        bus.now = t
        lv.update(t)
    assert hog.sound.name == 'monster_hog1_01_dry_chase'
    for _ in range(10):
        bus.post('PGE_MESSAGE_AlertAllEnemies', {'to': 'position'})
        t += 0.2
        bus.now = t
        lv.update(t)
        assert hog.sound.name == 'monster_hog1_01_dry_chase', \
            'a fresh noise restarted the chase sound'

    goal = hog.wanted_position
    lv.player.position = (-200.0, 200.0)
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    for _ in range(600):
        t += 0.05
        bus.now = t
        lv.update(t)
        if hog.state == IDLE:
            break
    # a state's entry work lands on the frame *after* the change, so give it one
    t += 0.05
    bus.now = t
    lv.update(t)
    assert hog.state == IDLE, f'ended in {hog.state_name}'
    assert math.dist(hog.position, goal) < 25.0, \
        f'it should have gone to where you were: {hog.position} vs {goal}'
    assert hog.sound.name == 'monster_hog1_01_dry_still'


def test_a_monster_already_searching_ignores_further_noises():
    """0x10001e428 - ``to=position`` is dropped unless distractedTimer is -1.

    The timer only leaves -1 when the enemy reaches the place it was sent to,
    so this is what stops a floor that alerts on every step (ps1_7's guts)
    from re-aiming a hog that is already standing there sniffing around.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    hog.distracted_time = 5.0
    lv.player.position = (60.0, 60.0)
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    bus.now = t
    bus.post('PGE_MESSAGE_AlertAllEnemies', {'to': 'position'})
    lv.update(t)

    # wait out the one-second wind-up, then get out of its way so that it
    # arrives at an empty spot rather than walking into you
    for _ in range(75):
        t += 1.0 / 60.0
        bus.now = t
        lv.update(t)
    lv.player.position = (-200.0, 200.0)
    bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': lv.player.position})
    for _ in range(600):
        t += 0.05
        bus.now = t
        lv.update(t)
        if hog.state == AT_POSITION:
            break
    t += 0.05
    bus.now = t
    lv.update(t)                       # the frame that actually starts the timer
    assert hog.state == AT_POSITION, hog.state_name
    assert hog.distracted_timer >= 0.0, 'the timer is running now'

    was = hog.wanted_position
    bus.post('PGE_MESSAGE_AlertAllEnemies', {'to': 'position'})
    t += 0.05
    bus.now = t
    lv.update(t)
    assert hog.state == AT_POSITION, f'the noise should be ignored, got {hog.state_name}'
    assert hog.wanted_position == was


def test_a_chase_records_where_the_enemy_was_standing():
    """State 3 is one of the two states that does record home."""
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    where = hog.position
    bus.now = t
    bus.post('PGE_MESSAGE_AlertAllEnemies', {'to': 'player'})
    lv.update(t)
    t += 0.1
    bus.now = t
    lv.update(t)
    assert hog.position_before_chasing == where


def test_an_enemy_without_a_declared_speed_still_walks():
    """-[PGEEnemy init]: chaseSpeed 15, walkingSpeed 10, distractedTime 10."""
    from papasangre.entities.monster import Monster               # noqa: PLC0415
    m = Monster(MessageBus(), name='x')
    assert m.chase_speed == 15.0
    assert m.walking_speed == 10.0
    assert m.distracted_time == 10.0
    assert m.chasing_radius == 200.0
    assert m.distracted_timer == -1.0
    assert m.state == IDLE


def test_the_hog_only_catches_you_once():
    """The freeze: OnCollide has no latch, so PGEEnemy provides one.

    Without it the hog re-fires ShutDownLevel every frame.  Each ShutDownLevel
    deactivates every agent *except the sender*, so the failure narration is
    switched off again the frame after it starts, never reaches OnSoundEnd, and
    the level never reloads - while the hog, being the sender, keeps looping.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    shutdowns = []
    bus.subscribe('PGE_MESSAGE_ShutDownLevel', lambda n, p: shutdowns.append(bus.now))

    walk_towards(bus, mi, lv, hog.position, t)
    assert lv.shutting_down
    assert len(shutdowns) == 1, f'ShutDownLevel fired {len(shutdowns)} times'
    assert hog.state == ATTACK, 'the hog should latch into its attack state'
    assert hog.speed == 0.0, 'and stop, which also stops it re-checking'

    fail = lv.agent('FINAL_Kennel_Fail')
    assert fail.active
    # hold still on top of the hog: the narration must survive
    t = bus.now
    for _ in range(60):
        t += 1.0 / 60.0
        bus.now = t
        lv.update(t)
    assert len(shutdowns) == 1, 'standing on the hog must not re-trigger it'
    assert fail.active, 'the failure narration must not be switched off again'

    fail.sound.stop()
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.next_level == 'ps1_3', 'and the level should reload'


def test_the_hog_goes_quiet_the_moment_it_has_you():
    """You should not still hear it beside you while the failure plays.

    State 7 stops the current sound **unconditionally** - not only when an
    attackSound exists - and the level spares the sender from its own
    ShutDownLevel, so the hog stays active.  Silent, but active.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    assert hog.sound.playing and hog.sound.name == 'monster_hog1_01_dry_still'

    walk_towards(bus, mi, lv, hog.position, t)
    assert hog.state == ATTACK
    assert not hog.sound.playing, 'the grunt should stop as it catches you'
    assert hog.active, 'but it is the sender, so ShutDownLevel spares it'

    t = bus.now
    for _ in range(120):                    # two seconds of dying
        t += 1.0 / 60.0
        bus.now = t
        lv.update(t)
    assert not hog.sound.playing, 'and it must not start up again'


# ---------------------------------------------------------------- tripping
def test_stepping_anywhere_is_what_lets_you_fall():
    """Where falling actually comes from.

    -[PGEPlayer init] sets tripBPM to 10000, which nobody can reach.  But
    -[PGELevel createObjectFromDict:] gives the Room *and* every Surface a
    default tripBPM of 280 when the level data names none (0x100141d24), and
    playerMovedToPosition: copies the current floor's value onto the player -
    where "the current floor" falls back to the room itself.  So the threshold
    arrives on your first step, wherever you are standing.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    p, hog = lv.player, lv.agent('hog1')
    assert p.trip_bpm == 10000.0, 'nothing applies until the first step'
    assert lv.trip_bpm == 280.0, 'the room carries the loader default'
    assert all(s.trip_bpm == 280.0 for s in lv.floors),         'and so does every kennel ring'

    trips = []
    bus.subscribe('PGE_MESSAGE_PlayerDidTrip', lambda n, _p: trips.append(bus.now))
    foot = LEFT
    for _ in range(120):
        dx = hog.position[0] - p.position[0]
        dy = hog.position[1] - p.position[1]
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += 0.15                      # far quicker than 280 BPM
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if trips or lv.shutting_down:
            break
    assert trips, 'running across the rings should put you on the ground'
    assert p.trip_bpm == 280.0
    assert p.state == 3, 'and leave you tripped'


def test_a_level_with_no_surface_objects_still_trips_you():
    """The room is the floor, so tripping needs no Surface at all.

    ps1_1 has zero Surface objects.  `PGELevel` is a `PGESurface`, and
    `playerMovedToPosition:` begins its search with **self** as the current
    best floor (0x10003231c) - a Surface only takes over by containing you at a
    higher z.  So the room's own tripBPM, 280 from the loader's default, is
    what you carry whenever nothing smaller covers you.
    """
    from papasangre.world.level import Level as _L                # noqa: PLC0415
    bus = MessageBus()
    mi = MoveInterpretor(bus)
    lv = _L(bus, FakeBank(LEVEL3_SOUNDS)).load(
        os.path.join(EXPORTS, 'ps1_1.json'), 'ps1_1')
    assert lv.floors == [], 'ps1_1 has no Surface objects'
    assert lv.trip_bpm == 280.0, 'but the room itself carries the default'

    lv.start(0.0)
    intro = lv.agent('FINAL_ITD_Intro')
    if intro is not None and intro.sound is not None:
        intro.sound.stop()          # ps1_1's own sounds are not in this bank
    bus.post('PGE_MESSAGE_EnableWalk', {})
    bus.now = 1.0
    lv.update(1.0)
    assert lv.player.trip_bpm == 10000.0, 'until the first step, nothing applies'

    mi.foot_pressed(LEFT)
    mi.foot_released(LEFT, 1.1)
    lv.update(1.1)
    assert lv.player.trip_bpm == 280.0, 'one step onto the room is enough'
    assert lv.player.current_surface_id == 0, 'and the room is surface 0'



def test_the_kennel_rings_name_their_own_shuffle_sound():
    """The rings are foot_stone-kennelA/B/C, so "<prefix>_shuffle" would miss.

    Each one carries an explicit shuffleSound instead, and -[PGELevel
    playerMovedToPosition:] copies it onto the player.
    """
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog = lv.agent('hog1')
    p = lv.player
    assert p.shuffle_sound in ('', 'foot_stone_shuffle')

    seen = set()
    foot = LEFT
    for _ in range(200):
        dx = hog.position[0] - p.position[0]
        dy = hog.position[1] - p.position[1]
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += 0.5
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if p.footsteps_prefix.startswith('foot_stone-kennel'):
            seen.add(p.shuffle_sound)
        if lv.shutting_down:
            break
    assert seen == {'foot_stone-kennel_shuffle'}, seen


def test_standing_still_on_a_ring_plays_that_ring_s_shuffle():
    """Stop walking and two seconds later you hear yourself shift your weight."""
    bus, mi, bank, lv = build()
    t = start(bus, lv)
    hog, p = lv.agent('hog1'), lv.player

    foot = LEFT
    for _ in range(200):                       # walk in until we are on a ring
        dx = hog.position[0] - p.position[0]
        dy = hog.position[1] - p.position[1]
        p.rotate_to_fixed_rotation(math.atan2(dy, dx))
        t += 0.5
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if p.shuffle_sound == 'foot_stone-kennel_shuffle':
            break
    assert p.shuffle_sound == 'foot_stone-kennel_shuffle'

    bank.played.clear()
    lv.update(t + 1.5)
    assert 'foot_stone-kennel_shuffle' not in bank.played, 'not yet - 1.5 s'

    lv.update(t + 2.05)
    assert 'foot_stone-kennel_shuffle' in bank.played, bank.played
    shuffle = bank.sounds['foot_stone-kennel_shuffle']
    assert shuffle.spatialized is False, 'it is you, so it is in your head'
    assert shuffle.wet_gain == 0.75


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
