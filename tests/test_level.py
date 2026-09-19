"""Regression tests for the level runtime (Phases F-H).

These run the real level data and the real engine logic against a stub sound
bank, so they need no audio hardware.  The headline test walks level 1 from its
start position to the exit exactly as a player would and checks that every
scripted beat fires in the right order.
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.core.messages import MessageBus                   # noqa: E402
from papasangre.input.interpreter import (LEFT, RIGHT,            # noqa: E402
                                          MoveInterpretor)
from papasangre.world.level import Level                          # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')


# --------------------------------------------------------------- stub audio
class FakeSound:
    """A stand-in for one sound - and, given a clock, one that **ends**.

    These used to report ``playing`` forever until something stopped them,
    which made a whole class of bug invisible to the suite: anything whose
    logic hangs off a one-shot *finishing* could not be exercised at all.
    A collectible completing its collect sound and re-arming, a lost soul
    settling back to resting when its abandoned line is over, an enemy timing
    its search by the length of its own grunt - every one of those is driven
    by a sound ending, and three real bugs reached players through that gap.

    With a ``clock`` (any callable returning the current time - the tests pass
    ``lambda: bus.now``) a non-looping sound stops on its own once its
    duration is up.  Without one the old always-playing behaviour is kept, so
    a test that never advances a clock still behaves as it did.
    """

    def __init__(self, name, duration=1.0, clock=None):
        self.name = name
        self.duration = duration
        self.looping = False
        self.spatialized = False
        self.send_to_reverb = False
        self.wet_gain = 0.0
        self.gain = 1.0
        self.planar = (0.0, 0.0, 0.0)
        self.plays = 0
        self._clock = clock
        self._playing = False
        self._started_at = 0.0
        self._paused_at = None

    def _now(self):
        return float(self._clock()) if self._clock is not None else 0.0

    @property
    def playing(self):
        if not self._playing:
            return False
        if self.looping or self._clock is None:
            return True
        return (self._now() - self._started_at) < self.duration

    @playing.setter
    def playing(self, v):
        self._playing = bool(v)
        if v:
            self._started_at = self._now()
        self._paused_at = None

    def play(self):
        self._playing = True
        self._started_at = self._now()
        self._paused_at = None
        self.plays += 1

    def stop(self):
        self._playing = False
        self._paused_at = None

    def pause(self):
        if self._playing and self._paused_at is None:
            self._paused_at = self._now() - self._started_at
        self._playing = False

    def resume(self):
        self._playing = True
        # Carry on from where it was, rather than starting the sound again.
        self._started_at = self._now() - (self._paused_at or 0.0)
        self._paused_at = None


class FakeBank:
    """Enough of SoundBank for the level logic, with no audio device."""

    def __init__(self, names, durations=None, clock=None):
        self.durations = durations or {}
        self.clock = clock
        self.sounds = {n: FakeSound(n, self.durations.get(n, 1.0), clock)
                       for n in names}
        self.played = []

    def set_clock(self, clock):
        """Give every sound a clock after the fact."""
        self.clock = clock
        for s in self.sounds.values():
            s._clock = clock
        return self

    def sound(self, name):
        s = self.sounds.get(name)
        if s is not None:
            self.played.append(name)
        return s

    def has(self, name):
        """Declared?  Without counting as a play - the real bank has this too."""
        return bool(name) and name in self.sounds

    def ensure(self, name, rel_path, spatialized=True):
        """Make a sound available that this level never declared.

        The real bank checks the file is on disk; so does this, so a test
        cannot pass on a sound the game could not actually play.
        """
        if name in self.sounds:
            return True
        full = os.path.join(BUNDLE, *rel_path.split('/'))
        if not os.path.exists(full):
            return False
        self.sounds[name] = FakeSound(name, self.durations.get(name, 1.0),
                                      self.clock)
        return True

    def any_sound_with_prefix(self, prefix):
        for n in sorted(self.sounds):
            if n.startswith(prefix):
                return self.sound(n)
        return None

    def any_sound_containing(self, needle):
        for n in sorted(self.sounds):
            if needle in n:
                return self.sound(n)
        return None

    def from_sound_list(self, sound_list):
        names = [n for n in (sound_list or '').split('&') if n]
        return self.sound(names[0]) if names else None

    def live_sounds(self):
        return list(self.sounds.values())

    def stop_all(self):
        for s in self.sounds.values():
            s.stop()


LEVEL1_SOUNDS = [
    'foot_stone_shuffle',
    'FINAL_ITD_Intro', 'Atmos_darkrumble_01', 'FINAL_ITD_notecollect_1',
    'FINAL_ITD_notecollect_2', 'FINAL_ITD_notecollect_3', 'door_castle_appear',
    'door_castle_living', 'FINAL_ITD_inactive_1', 'FINAL_ITD_inactive_2',
    'FINAL_ITD_inactive_3', 'FINAL_ITD_Win', 'FINAL_ITD_trip',
    'foot_stone_s1_L_a', 'foot_stone_s1_R_a', 'foot_stone_s3_L_a',
    'foot_stone_s3_R_a', 'foot_stone_trip', 'foot_stone_shuffle',
]


def build(stem='ps1_1', durations=None, names=None):
    bus = MessageBus()
    interp = MoveInterpretor(bus)
    bank = FakeBank(names or LEVEL1_SOUNDS, durations, clock=lambda: bus.now)
    level = Level(bus, bank).load(os.path.join(EXPORTS, f'{stem}.json'), stem)
    return bus, interp, bank, level


# ------------------------------------------------------------------ loading
def test_level_one_loads_its_room_and_agents():
    _bus, _mi, _bank, lv = build()
    assert lv.footsteps_prefix == 'foot_stone'
    assert lv.inactivity_sounds == ['FINAL_ITD_inactive_1',
                                    'FINAL_ITD_inactive_2',
                                    'FINAL_ITD_inactive_3']
    assert {a.name for a in lv.agents} == {
        'FINAL_ITD_Intro', 'Atmos_darkrumble_01', 'trigger1', 'trigger2',
        'trigger3', 'FINAL_ITD_inactive_all', 'door_castle_living'}
    assert lv.floors == []          # level 1 is a bare room


def test_player_starts_where_the_data_says_facing_the_corridor():
    _bus, _mi, _bank, lv = build()
    assert lv.player.position == (-10.5, -203.0)
    assert round(lv.player.bearing_degrees, 3) == 90.0
    assert round(lv.player.orientation_vector[1], 6) == 1.0
    assert lv.player.pixels_per_step == 5.0
    assert lv.player.footsteps_prefix == 'foot_stone'


def test_agent_properties_come_through():
    _bus, _mi, _bank, lv = build()
    t1 = lv.agent('trigger1')
    assert t1.collide_radius == 20.0
    assert t1.active is True
    door = lv.agent('door_castle_living')
    assert door.intro_sound == 'door_castle_living'
    assert door.collect_sound == 'FINAL_ITD_Win'
    assert door.active is False


# ------------------------------------------------------------------ scripted
def test_room_on_enter_locks_the_controls():
    bus, mi, _bank, lv = build()
    lv.start(0.0)
    assert not mi.player_can_walk
    assert not mi.player_can_rotate


def test_intro_ending_unlocks_walking_and_starts_the_atmosphere():
    bus, mi, bank, lv = build()
    lv.start(0.0)
    intro = lv.agent('FINAL_ITD_Intro')
    assert intro.sound.playing
    intro.sound.stop()               # stand in for the narration finishing
    bus.now = 1.0
    lv.update(1.0)
    assert mi.player_can_walk
    assert lv.agent('Atmos_darkrumble_01').active
    assert lv.agent('FINAL_ITD_inactive_all').active
    assert lv.inactivity_time == 18.0


def _walk_to_exit(bus, mi, lv, steps=90, interval=0.45):
    t = 1.0
    foot = LEFT
    for _ in range(steps):
        t += interval
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if lv.shutting_down:
            break
    return t


def test_hammering_one_foot_gets_you_exactly_one_step():
    """The bug this pins: repeating a foot used to walk you at any speed.

    The alternation gate lives in -[PGEMoveInterpretor updateFeetView:], which
    puts the foot you just used "off" for two seconds.
    """
    bus, mi, bank, lv = build()
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)

    start_pos = lv.player.position
    t = 1.0
    for _ in range(20):                      # twenty presses of the same foot
        t += 0.1
        bus.now = t
        mi.foot_pressed(LEFT)
        mi.foot_released(LEFT, t)
        lv.update(t)
    one_step = lv.player.position
    assert one_step != start_pos, 'the first press should still step'
    moved = math.dist(one_step, start_pos)
    assert moved <= lv.player.pixels_per_step + 1e-6,         f'twenty presses of one foot moved {moved:.1f}px, not one step'

    foot = RIGHT                              # now alternate from where we are
    for _ in range(6):
        t += 0.4
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
    assert math.dist(lv.player.position, one_step) > lv.player.pixels_per_step


def test_standing_still_plays_the_rooms_shuffle():
    bus, mi, bank, lv = build()
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)

    bus.now = 1.5
    mi.foot_pressed(LEFT)
    mi.foot_released(LEFT, 1.5)
    lv.update(1.5)
    bank.played.clear()

    lv.update(3.0)
    assert 'foot_stone_shuffle' not in bank.played
    lv.update(3.6)
    assert 'foot_stone_shuffle' in bank.played, bank.played


def test_walking_the_corridor_fires_every_beat_in_order():
    bus, mi, bank, lv = build()
    seen = []
    bus.subscribe('PGE_MESSAGE_PlaySound',
                  lambda n, p: seen.append(p.get('soundName')))
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)

    _walk_to_exit(bus, mi, lv)

    assert seen[:3] == ['FINAL_ITD_notecollect_1',
                        'FINAL_ITD_notecollect_2',
                        'FINAL_ITD_notecollect_3'], seen
    assert 'door_castle_appear' in seen
    assert lv.agent('door_castle_living').was_collected
    assert lv.shutting_down


def test_the_three_note_triggers_deactivate_themselves():
    bus, mi, bank, lv = build()
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)
    _walk_to_exit(bus, mi, lv)
    for name in ('trigger1', 'trigger2', 'trigger3'):
        assert not lv.agent(name).active, name


def test_the_exit_door_only_appears_after_the_third_note():
    bus, mi, bank, lv = build()
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)
    door = lv.agent('door_castle_living')
    t = 1.0
    foot = LEFT
    for _ in range(60):
        t += 0.45
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        third_done = not lv.agent('trigger3').active
        if not third_done:
            assert not door.active, 'the door appeared before the third note'
        if door.active:
            break
    assert door.active, 'the door never appeared'


def test_finishing_the_level_asks_for_the_next_one():
    bus, mi, bank, lv = build()
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)
    t = _walk_to_exit(bus, mi, lv)
    door = lv.agent('door_castle_living')
    assert door.was_collected
    door.sound.stop()                 # the win sound finishes
    t += 0.5
    bus.now = t
    lv.update(t)
    assert lv.finished
    assert lv.next_level == 'ps1_1b'


def test_walking_into_the_far_wall_does_not_leave_the_room():
    """With the exit out of the way, the room rectangle still stops you."""
    bus, mi, bank, lv = build()
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)
    # trigger3 is what summons the exit, so silence it too - otherwise the
    # door reappears, the player walks into it and the level shuts down.
    lv.agent('trigger3').deactivate()
    lv.agent('door_castle_living').deactivate()
    walls = []
    bus.subscribe('PGE_MESSAGE_PlayerDidCollideAWall', lambda n, p: walls.append(p))
    t = 1.0
    foot = LEFT
    for _ in range(200):
        t += 0.45
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
    assert walls, 'the player should have run into the far wall'
    assert lv.contains(*lv.player.position)


def test_a_surface_fires_on_enter_only_once_ever():
    """-[PGESurface triggerOnEnter] latches on `entered`, not on the visit.

    Cross a trigger line, walk back off it, cross it again: the second crossing
    is silent.  `multipleOnEnter` is the only thing that lifts it, and it lifts
    OnExit with it.
    """
    from papasangre.assets.tiled import Trigger                  # noqa: PLC0415
    from papasangre.world.surface import Surface                 # noqa: PLC0415

    bus = MessageBus()
    fired = []
    bus.subscribe(None, lambda n, p: fired.append(n))
    s = Surface(bus, (0.0, 0.0, 10.0, 10.0), surface_id=1)
    s.add_trigger(Trigger('OnEnter', 'PGE_MESSAGE_PlaySound', raw=''))
    s.add_trigger(Trigger('OnExit', 'PGE_MESSAGE_PlaySpatialSound', raw=''))

    for _ in range(3):
        s.trigger_on_enter()
        s.trigger_on_exit()
    bus.update(0.0)
    assert fired.count('PGE_MESSAGE_PlaySound') == 1, fired
    assert fired.count('PGE_MESSAGE_PlaySpatialSound') == 1, fired

    fired.clear()
    s.multiple_on_enter = True
    for _ in range(3):
        s.trigger_on_enter()
        s.trigger_on_exit()
    bus.update(0.0)
    assert fired.count('PGE_MESSAGE_PlaySound') == 3, fired


def test_re_activating_an_active_agent_does_nothing():
    """setActive: acts on a transition, so a second Activate is not a replay."""
    bus, mi, bank, lv = build()
    lv.start(0.0)
    intro = lv.agent('FINAL_ITD_Intro')
    assert intro.active
    plays = intro.sound.plays

    bus.now = 0.5
    bus.post('PGE_MESSAGE_ActivateAgentWithName', {'name': 'FINAL_ITD_Intro'})
    lv.update(0.5)
    assert intro.sound.plays == plays, 'the intro should not start again'


def test_on_load_fires_for_every_agent_when_the_level_is_built():
    """-[PGEGameAgent levelInited:] fires OnLoad; 8 monsters depend on it."""
    from papasangre.assets.tiled import Trigger                  # noqa: PLC0415

    bus = MessageBus()
    MoveInterpretor(bus)
    bank = FakeBank(LEVEL1_SOUNDS, clock=lambda: bus.now)
    seen = []
    bus.subscribe('PGE_MESSAGE_AlertAllEnemies', lambda n, p: seen.append(p))
    lv = Level(bus, bank)
    lv.load(os.path.join(EXPORTS, 'ps1_1.json'), 'ps1_1')
    a = lv.agent('trigger1')
    a.add_trigger(Trigger('OnLoad', 'PGE_MESSAGE_AlertAllEnemies', raw=''))

    bus.post('PGE_MESSAGE_LevelInited', {'name': 'ps1_1'})
    bus.update(0.0)
    assert seen, 'OnLoad should have fired'


def test_hitting_a_wall_plays_the_default_thump():
    """No level sets hitWallSound, so "hitwall" is what you actually hear.

    ps1_2 declares it; ps1_1 does not, and is silent here in the original too.
    """
    bus, mi, bank, lv = build('ps1_2', names=['hitwall'])
    assert lv.hit_wall_sound == '', 'the level data does not name one'
    bank.played.clear()
    bus.now = 1.0
    bus.post('PGE_MESSAGE_PlayerDidCollideAWall', {})
    assert 'hitwall' in bank.played, bank.played
    thump = bank.sounds['hitwall']
    assert thump.send_to_reverb is True
    assert thump.wet_gain == 0.5


# ---------------------------------------------------------------- shutdown
def test_shutting_down_silences_everything_except_the_sender():
    """The closing narration must not be talked over.

    ``-[PGELevel shutDownLevel:]`` deactivates every agent *except* the one that
    sent the message, stops the inactivity sound and empties its list. Without
    that, the "are you still there" nag fires eighteen seconds into the twenty
    four second win narration, because collecting the exit means you stop moving.
    """
    bus, mi, bank, lv = build(durations={'FINAL_ITD_Win': 24.0,
                                         'FINAL_ITD_inactive_1': 8.6})
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)
    assert lv.inactivity_time == 18.0

    t = _walk_to_exit(bus, mi, lv)
    door = lv.agent('door_castle_living')
    assert door.was_collected
    assert lv.shutting_down

    # the exit keeps talking; everything else is off
    assert bank.sounds['FINAL_ITD_Win'].playing
    assert not lv.agent('Atmos_darkrumble_01').active
    assert not lv.agent('FINAL_ITD_inactive_all').active
    assert lv.inactivity_sounds == []

    # and no nag can start during the closing narration
    for extra in (10.0, 20.0, 30.0, 60.0):
        lv.update(t + extra)
    assert bank.sounds['FINAL_ITD_inactive_1'].plays == 0,         'the inactivity nag talked over the closing narration'


def test_shutting_down_freezes_the_player():
    bus, mi, bank, lv = build()
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)
    assert mi.player_can_walk
    _walk_to_exit(bus, mi, lv)
    assert not mi.player_can_walk


# --------------------------------------------------------------- inactivity
def test_standing_still_eventually_nags_and_cycles_the_sounds():
    bus, mi, bank, lv = build(durations={'FINAL_ITD_inactive_1': 3.0,
                                         'FINAL_ITD_inactive_2': 3.0})
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)                      # sets inactivityTime to 18
    assert lv.inactivity_time == 18.0

    lv.update(10.0)
    assert bank.sounds['FINAL_ITD_inactive_1'].plays == 0
    lv.update(20.0)
    assert bank.sounds['FINAL_ITD_inactive_1'].plays == 1
    # the clock is pushed past the end of the sound, so it cannot retrigger
    lv.update(21.0)
    assert bank.sounds['FINAL_ITD_inactive_2'].plays == 0
    lv.update(45.0)
    assert bank.sounds['FINAL_ITD_inactive_2'].plays == 1


def test_moving_resets_the_inactivity_clock():
    bus, mi, bank, lv = build()
    lv.start(0.0)
    lv.agent('FINAL_ITD_Intro').sound.stop()
    bus.now = 1.0
    lv.update(1.0)
    t = 1.0
    foot = LEFT
    for _ in range(30):                 # keep walking for well over 18 seconds
        t += 1.0
        bus.now = t
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
        foot = RIGHT if foot == LEFT else LEFT
        lv.update(t)
        if lv.shutting_down:
            break
    assert bank.sounds['FINAL_ITD_inactive_1'].plays == 0


# ----------------------------------------------------------------- surfaces
def test_surfaces_override_the_room_footsteps_and_highest_z_wins():
    """ps1_4 'Bed of Bones' layers surfaces over its room."""
    bus, mi, bank, lv = build('ps1_4')
    assert lv.floors, 'ps1_4 should have surfaces'
    prefixes = {s.footsteps_prefix for s in lv.floors if s.footsteps_prefix}
    assert prefixes, 'at least one surface names a footstep bank'
    # every surface rectangle should sit inside the room
    rx, ry, rw, rh = lv.rect
    for s in lv.floors:
        sx, sy, sw, sh = s.rect
        assert sw > 0 and sh > 0
        assert sx + sw > rx and sx < rx + rw


def test_every_level_builds_without_error():
    import glob
    for fp in sorted(glob.glob(os.path.join(EXPORTS, '*.json'))):
        stem = os.path.splitext(os.path.basename(fp))[0]
        bus = MessageBus()
        MoveInterpretor(bus)
        bank = FakeBank(LEVEL1_SOUNDS, clock=lambda: bus.now)
        lv = Level(bus, bank).load(fp, stem)
        assert lv.player is not None, stem
        assert lv.rect[2] > 0 and lv.rect[3] > 0, stem


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
