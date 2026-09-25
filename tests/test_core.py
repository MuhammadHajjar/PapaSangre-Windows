"""Regression tests for the message bus, triggers, input and player (Phases D-E).

Expectations are the arithmetic and branches recovered from the arm64 binary;
a failure means the port has drifted from the original engine.
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.assets.tiled import parse_trigger_statement       # noqa: E402
from papasangre.core.messages import MessageBus                   # noqa: E402
from papasangre.core.triggers import TriggerHost, addressed_to    # noqa: E402
from papasangre.entities.player import (                          # noqa: E402
    STATE_RUNNING, STATE_STILL, STATE_TRIPPED, STATE_WALKING, Player)
from papasangre.input.interpreter import (LEFT, RIGHT,            # noqa: E402
                                          MoveInterpretor)
from papasangre.input.keymap import Action, KeyMap                # noqa: E402


class Recorder:
    def __init__(self, bus, name=None):
        self.seen = []
        bus.subscribe(name, self._on)

    def _on(self, name, params):
        self.seen.append((name, dict(params)))

    def names(self):
        return [n for n, _ in self.seen]


# ------------------------------------------------------------- message bus
def test_post_is_immediate_and_enqueue_is_not():
    bus = MessageBus()
    r = Recorder(bus)
    bus.post('A')
    assert r.names() == ['A']
    bus.enqueue('B')
    assert r.names() == ['A']          # not yet
    bus.drain()
    assert r.names() == ['A', 'B']


def test_enqueued_messages_keep_their_order():
    bus = MessageBus()
    r = Recorder(bus)
    for n in 'ABCD':
        bus.enqueue(n)
    bus.drain()
    assert r.names() == list('ABCD')


def test_drain_keeps_going_for_messages_raised_during_the_drain():
    bus = MessageBus()
    r = Recorder(bus)

    def chain(name, params):
        if name == 'A':
            bus.enqueue('B')
        elif name == 'B':
            bus.enqueue('C')

    bus.subscribe(None, chain)
    bus.enqueue('A')
    bus.drain()
    assert r.names() == ['A', 'B', 'C']


def test_delayed_messages_fire_at_their_time():
    bus = MessageBus()
    r = Recorder(bus)
    bus.post_after(1.0, 'LATER')
    bus.update(0.5)
    assert r.names() == []
    bus.update(1.0)
    assert r.names() == ['LATER']


def test_a_delayed_message_is_delivered_directly_not_queued():
    """The two trigger paths do not agree, and the port has to match both.

    -[PGEObjectWithTriggers triggerWithType:] ends an immediate trigger in
    enqueueNotification:postingStyle:NSPostWhenIdle, but a delayed one goes
    through startTriggerAfterDelay:, which ends in postNotificationName:object:.
    So a delayed message overtakes anything already sitting on the queue.
    """
    bus = MessageBus()
    order = []
    bus.subscribe(None, lambda n, p: order.append(n))
    bus.post_after(1.0, 'DELAYED')
    bus.enqueue('QUEUED')
    bus.update(1.0)
    assert order == ['DELAYED', 'QUEUED'], order


def test_delayed_messages_can_be_cancelled():
    bus = MessageBus()
    r = Recorder(bus)
    bus.post_after(1.0, 'LATER', token='t')
    assert bus.cancel('t') == 1
    bus.update(2.0)
    assert r.names() == []


def test_broadcast_reaches_everyone_and_names_are_filtered_by_the_receiver():
    """This is why triggers naming a missing agent quietly do nothing."""
    bus = MessageBus()
    hits = []
    for who in ('door', 'note1'):
        def make(w):
            def h(name, params):
                if addressed_to(params, w):
                    hits.append(w)
            return h
        bus.subscribe('PGE_MESSAGE_ActivateAgentWithName', make(who))
    bus.post('PGE_MESSAGE_ActivateAgentWithName', {'name': 'door'})
    bus.post('PGE_MESSAGE_ActivateAgentWithName', {'name': 'nobody'})
    assert hits == ['door']


# ---------------------------------------------------------------- triggers
def _host(bus, statements, trigger_type='OnCollide', name='thing'):
    h = TriggerHost(bus, name=name, position=(3.0, 4.0))
    for s in statements:
        h.add_trigger(parse_trigger_statement(trigger_type, s))
    return h


def test_trigger_fires_and_adds_sender_and_position():
    bus = MessageBus()
    r = Recorder(bus)
    h = _host(bus, ['PlaySound:soundName=ping'])
    h.trigger('OnCollide')
    bus.drain()
    assert r.seen[0][0] == 'PGE_MESSAGE_PlaySound'
    assert r.seen[0][1]['soundName'] == 'ping'
    assert r.seen[0][1]['senderName'] == 'thing'
    assert r.seen[0][1]['position'] == (3.0, 4.0)


def test_trigger_type_match_is_case_insensitive():
    bus = MessageBus()
    r = Recorder(bus)
    h = _host(bus, ['ShutDownLevel'], trigger_type='OnCollide')
    h.trigger('oncollide')
    bus.drain()
    assert r.names() == ['PGE_MESSAGE_ShutDownLevel']


def test_count_limits_how_often_a_trigger_may_fire():
    bus = MessageBus()
    r = Recorder(bus)
    h = _host(bus, ['PlaySound:soundName=x;count=2'])
    for _ in range(5):
        h.trigger('OnCollide')
    bus.drain()
    assert len(r.seen) == 2


def test_aftercount_delays_the_first_firing():
    bus = MessageBus()
    r = Recorder(bus)
    h = _host(bus, ['PlaySound:soundName=x;afterCount=3'])
    h.trigger('OnCollide')
    h.trigger('OnCollide')
    bus.drain()
    assert len(r.seen) == 0        # skipped twice
    h.trigger('OnCollide')
    h.trigger('OnCollide')
    bus.drain()
    assert len(r.seen) == 2        # fires from the third onwards


def test_afterdelay_schedules_instead_of_enqueueing():
    bus = MessageBus()
    r = Recorder(bus)
    h = _host(bus, ['ActivateAgentWithName:name=door;afterDelay=1'])
    h.trigger('OnCollide')
    bus.update(0.5)
    assert r.names() == []
    bus.update(1.0)
    assert r.names() == ['PGE_MESSAGE_ActivateAgentWithName']


def test_original_defect_missing_name_still_fires_but_hits_nothing():
    """ps1_19: DeactivateAgentWithName:chicken_1;afterDelay=20"""
    bus = MessageBus()
    r = Recorder(bus)
    h = _host(bus, ['DeactivateAgentWithName:chicken_1;afterDelay=20'],
              trigger_type='OnActivate')
    h.trigger('OnActivate')
    bus.update(20.0)
    assert r.names() == ['PGE_MESSAGE_DeactivateAgentWithName']
    assert 'name' not in r.seen[0][1]        # nothing to address, so a no-op


# ------------------------------------------------------------- interpreter
def _walker():
    bus = MessageBus()
    mi = MoveInterpretor(bus)
    mi.set_settings_to_default()
    return bus, mi


def test_controls_start_locked():
    bus = MessageBus()
    mi = MoveInterpretor(bus)
    assert not mi.player_can_walk
    assert not mi.player_can_rotate
    assert mi.foot_pressed(LEFT) is False


def test_enable_walk_message_unlocks_walking():
    bus = MessageBus()
    mi = MoveInterpretor(bus)
    bus.post('PGE_MESSAGE_EnableWalk')
    assert mi.player_can_walk


def test_step_fires_on_release_not_press():
    bus, mi = _walker()
    r = Recorder(bus, 'PGE_ACTION_OneStep')
    mi.foot_pressed(LEFT)
    assert r.names() == []
    mi.foot_released(LEFT, 1.0)
    assert r.names() == ['PGE_ACTION_OneStep']
    assert r.seen[0][1]['lastFoot'] == 'L'


def test_alternating_feet_never_trips():
    bus, mi = _walker()
    trips = Recorder(bus, 'PGE_ACTION_Trip')
    steps = Recorder(bus, 'PGE_ACTION_OneStep')
    t = 0.0
    for foot in (LEFT, RIGHT, LEFT, RIGHT, LEFT, RIGHT):
        t += 0.4
        mi.foot_pressed(foot)
        mi.foot_released(foot, t)
    assert trips.names() == []
    assert len(steps.seen) == 6


def _step(bus, mi, foot, t):
    """Press and release one foot at time ``t``, letting the clock reach it."""
    bus.update(t)
    mi.foot_pressed(foot)
    return mi.foot_released(foot, t)


def test_repeating_a_foot_does_nothing_at_all():
    """The foot you just used is "off", and both press and release ignore it.

    This is the alternation rule, and it is why you cannot run by hammering one
    key.  Recovered from -[PGEMoveInterpretor updateFeetView:].
    """
    bus, mi = _walker()
    trips = Recorder(bus, 'PGE_ACTION_Trip')
    steps = Recorder(bus, 'PGE_ACTION_OneStep')

    assert _step(bus, mi, LEFT, 1.0) is True
    assert mi.feet[LEFT] == 'off', 'the foot you just used goes off'
    assert mi.feet[RIGHT] == 'on'

    assert mi.foot_pressed(LEFT) is False
    assert _step(bus, mi, LEFT, 1.2) is False
    assert _step(bus, mi, LEFT, 1.4) is False

    assert len(steps.seen) == 1, 'hammering one foot gives you one step'
    assert trips.names() == [], 'and it certainly does not trip you'


def test_you_walk_by_alternating():
    bus, mi = _walker()
    steps = Recorder(bus, 'PGE_ACTION_OneStep')
    trips = Recorder(bus, 'PGE_ACTION_Trip')
    foot, t = LEFT, 0.0
    for _ in range(6):
        t += 0.4
        assert _step(bus, mi, foot, t) is True, f'{foot} at {t}'
        foot = RIGHT if foot == LEFT else LEFT
    assert len(steps.seen) == 6
    assert trips.names() == []


def test_the_used_foot_comes_back_after_two_seconds_with_a_shuffle():
    """Stand still and the engine frees the foot and plays you shuffling."""
    bus, mi = _walker()
    shuffles = Recorder(bus, 'PGE_ACTION_Shuffle')

    _step(bus, mi, LEFT, 1.0)
    bus.update(2.9)                       # 1.9 s later: still locked, still quiet
    assert mi.feet[LEFT] == 'off'
    assert shuffles.names() == []

    bus.update(3.05)                      # the 2.0 s re-evaluation lands
    assert len(shuffles.seen) == 1, 'you hear yourself shift your weight'
    assert mi.feet[LEFT] == 'on'
    assert mi.last_foot_button_pressed == 'N', 'either foot may start again'
    assert _step(bus, mi, LEFT, 3.1) is True


def test_the_shuffle_survives_a_key_stamp_ahead_of_the_frame_clock():
    """The bug that made the shuffle fire only sometimes.

    In the real loop the key-release stamp is read from the input event and is
    a few ms *ahead* of bus.now, which is last frame's time.  Scheduling the
    2 s re-check off bus.now made it land early, gap came out just under 2.0,
    the foot stayed "off" and the shuffle never played.  There is no second
    chance: nothing else re-evaluates once you stop.
    """
    for lag in (0.0, 0.001, 0.004, 0.008):
        bus = MessageBus()
        mi = MoveInterpretor(bus)
        mi.set_settings_to_default()
        shuffles = []
        bus.subscribe('PGE_ACTION_Shuffle', lambda n, p: shuffles.append(bus.now))
        frame, t, foot, nxt = 1.0 / 120.0, 0.0, LEFT, 0.5
        while t < 6.0:
            t += frame
            bus.update(t)
            if nxt and t >= nxt:
                mi.foot_pressed(foot)
                mi.foot_released(foot, t + lag)     # stamp ahead of the frame
                foot = RIGHT if foot == LEFT else LEFT
                nxt = nxt + 0.45 if nxt < 2.0 else None
        assert len(shuffles) == 1, f'lag {lag}: got {len(shuffles)} shuffles'


def test_the_shuffle_does_not_repeat_while_you_stand_there():
    bus, mi = _walker()
    shuffles = Recorder(bus, 'PGE_ACTION_Shuffle')
    _step(bus, mi, LEFT, 1.0)
    for t in (3.05, 5.0, 9.0, 20.0):
        bus.update(t)
    assert len(shuffles.seen) == 1


def test_the_same_foot_trip_branch_is_kept_but_cannot_be_reached():
    """The binary posts PGE_ACTION_Trip here; the "off" gate means it never can.

    The rule itself is still exact - the port keeps it because the disassembly
    has it - but no sequence of presses can get a release past the gate while
    the one-second window is still open.  See SAME_FOOT_TRIP_WINDOW.
    """
    bus, mi = _walker()
    trips = Recorder(bus, 'PGE_ACTION_Trip')

    _step(bus, mi, LEFT, 1.0)
    _step(bus, mi, RIGHT, 1.4)
    # the rule itself says yes: right was used last, 0.4 s ago
    assert mi.trip_would_fire(RIGHT, 1.8) is True
    assert mi.trip_would_fire(RIGHT, 1.4 + 1.01) is False    # the 1.0 s window
    # but the gate refuses the release before the rule is ever consulted
    assert _step(bus, mi, RIGHT, 1.8) is False
    assert trips.names() == []

    # and by the time the foot is free again the window has long closed
    bus.update(3.5)
    assert mi.feet[RIGHT] == 'on'
    assert mi.trip_would_fire(RIGHT, 3.5) is False


def test_locking_the_controls_puts_both_feet_off():
    bus, mi = _walker()
    _step(bus, mi, LEFT, 1.0)
    mi.lock_controls()
    assert mi.feet == {'L': 'off', 'R': 'off'}
    assert mi.foot_pressed(RIGHT) is False


def test_tripped_player_cannot_step():
    bus, mi = _walker()
    mi.player_state = STATE_TRIPPED
    assert mi.foot_pressed(LEFT) is False
    assert mi.foot_released(LEFT, 1.0) is False


# ------------------------------------------------------------------ player
class _Level:
    def __init__(self, rect):
        self.rect = rect

    def contains(self, x, y):
        rx, ry, rw, rh = self.rect
        return rx <= x < rx + rw and ry <= y < ry + rh


def test_orientation_vector_is_unit_and_follows_the_angle():
    p = Player(MessageBus())
    p.rotate_to_fixed_rotation(0.0)
    assert abs(p.orientation_vector[0] - 1.0) < 1e-9
    assert abs(p.orientation_vector[1]) < 1e-9
    p.rotate_to_fixed_rotation(math.pi / 2)
    assert abs(p.orientation_vector[0]) < 1e-9
    assert abs(p.orientation_vector[1] - 1.0) < 1e-9


def test_start_angle_is_degrees_converted_to_radians():
    p = Player(MessageBus())
    p.set_start_angle(90)          # ps1_1's Player object
    assert abs(p.player_angle - math.pi / 2) < 1e-9


def test_angle_wrap_is_a_single_correction():
    """The original corrects once; it does not take a modulo."""
    p = Player(MessageBus())
    p.rotate_to_fixed_rotation(0.1)
    p.rotate_player_from_angle(-0.2)
    assert abs(p.player_angle - (0.1 - 0.2 + 2 * math.pi)) < 1e-6
    p.rotate_to_fixed_rotation(0.0)
    p.rotate_player_from_angle(10 * math.pi)      # far more than one turn
    assert p.player_angle > 2 * math.pi           # still out of range, as original


def test_step_moves_by_pixels_per_step_along_the_bearing():
    bus = MessageBus()
    p = Player(bus, level=_Level((-100, -100, 200, 200)))
    p.pixels_per_step = 5.0
    p.rotate_to_fixed_rotation(0.0)
    p.position = (0.0, 0.0)
    assert p.move_forward_one_step('L', 1.0)
    assert abs(p.position[0] - 5.0) < 1e-9
    assert abs(p.position[1]) < 1e-9


def test_walking_into_the_room_edge_reports_a_wall_and_does_not_move():
    bus = MessageBus()
    r = Recorder(bus, 'PGE_MESSAGE_PlayerDidCollideAWall')
    p = Player(bus, level=_Level((-10, -10, 20, 20)))
    p.pixels_per_step = 5.0
    p.rotate_to_fixed_rotation(0.0)
    p.position = (8.0, 0.0)
    assert p.move_forward_one_step('L', 1.0) is False
    assert p.position == (8.0, 0.0)
    assert len(r.seen) == 1


def test_bpm_reads_the_tempo_and_not_the_history_length():
    """[REQUESTED] The original's fencepost, and why it could not stay.

    `updateBPMCounter` divides the summed gaps by `[walkTimes count]`
    (0x100025d64) rather than by the number of gaps, so five stamps spanning
    four gaps read 25% high and three stamps read 50% high. The reading was
    therefore not your tempo but your tempo times `count / (count - 1)`, and
    since the array fills from empty after every `resetBPM` - which runs on a
    trip and on crossing onto ground with a different `tripBPM` - the threshold
    moved under you. On ps1_19's seven-step ice band that meant three free
    steps, a fall, three free steps, a fall, with no way off the ice.

    Corrected, the reading is exactly 60 / interval at every history length, so
    every authored `tripBPM` means real beats per minute. DIVERGENCES 4c.
    """
    p = Player(MessageBus())
    for t in (0.0, 0.5, 1.0):        # two intervals of half a second
        p.update_bpm_counter(t)
    assert abs(p.walk_bpm - 120.0) < 1e-6, 'two steps a second is 120 BPM'
    # and it stays 120 as the history fills, which is the whole point
    for t in (1.5, 2.0, 2.5, 3.0):
        p.update_bpm_counter(t)
        assert abs(p.walk_bpm - 120.0) < 1e-6,             f'{len(p.walk_times)} stamps read {p.walk_bpm:.1f}, not 120'


def test_walk_times_are_capped_at_five():
    p = Player(MessageBus())
    for i in range(12):
        p.update_bpm_counter(i * 0.5)
    assert len(p.walk_times) == 5


def test_speed_bank_switches_at_two_hundred_bpm():
    p = Player(MessageBus())
    for t in (0.0, 0.5, 1.0):
        p.update_bpm_counter(t)      # 120 BPM
    assert p.speed == 's1'
    p.walk_times.clear()
    for t in (0.0, 0.2, 0.4):
        p.update_bpm_counter(t)      # 60 / 0.2 = 300 BPM
    assert p.speed == 's3'


def test_check_step_bpm_is_a_no_op_without_thresholds():
    p = Player(MessageBus())
    p.trip_bpm = 0.0
    assert p.check_step_bpm() is True
    assert p.state == STATE_STILL


def test_too_fast_trips_and_between_thresholds_runs():
    p = Player(MessageBus())
    p.trip_bpm, p.run_bpm = 300.0, 150.0
    p.walk_times = [0.0, 0.1, 0.2]
    p.walk_bpm = 400.0                       # above trip
    p.check_step_bpm()
    assert p.state == STATE_TRIPPED

    p2 = Player(MessageBus())
    p2.trip_bpm, p2.run_bpm = 300.0, 150.0
    p2.walk_times = [0.0, 0.3, 0.6]
    p2.walk_bpm = 200.0                      # between run and trip
    p2.check_step_bpm()
    assert p2.state == STATE_RUNNING
    assert p2.walk_bpm == 30.0               # the original's reset


def test_going_still_clears_the_tempo_history():
    p = Player(MessageBus())
    for t in (0.0, 0.4, 0.8):
        p.update_bpm_counter(t)
    p.change_state(STATE_STILL)
    assert p.walk_times == []
    assert p.walk_bpm == 0.0


def test_footstep_name_follows_the_originals_format():
    p = Player(MessageBus())
    p.footsteps_prefix = 'foot_stone'
    p.speed = 's1'
    p.last_foot = 'L'
    assert p.footstep_sound_name() == 'foot_stone_s1_L'


def test_silent_foot_plays_no_footstep():
    bus = MessageBus()
    played = []

    class Bank:
        def any_sound_with_prefix(self, prefix):
            played.append(prefix)
            return None

    p = Player(bus, level=_Level((-100, -100, 200, 200)))
    p.playlist = Bank()
    p.rotate_to_fixed_rotation(0.0)
    p.move_forward_one_step('N', 1.0)
    assert played == []


# ------------------------------------------------------------------ keymap
def test_default_bindings_cover_every_action_this_game_can_use():
    """ACTION is the exception: PGEActionSurface exists in the engine but no
    level in Papa Sangre 1 contains one, so binding it would only take Enter
    away from skipping narration for a button nothing can press."""
    km = KeyMap()
    for action in Action:
        if action is Action.ACTION:
            assert km.keys_for(action) == [], 'ACTION should stay unbound'
            continue
        assert km.keys_for(action), f'{action} has no default binding'


def test_enter_skips_narration_and_clashes_with_nothing():
    km = KeyMap()
    assert 'return' in km.keys_for(Action.SKIP)
    assert km.conflicts() == {}


def test_walking_and_turning_use_different_hands():
    """Walking is a constant alternation, so it cannot share a hand with turning.

    Both feet on one side of the keyboard (A and L, say) leaves nothing to steer
    with. The feet must be reachable by one hand and the turn keys by the other.
    """
    km = KeyMap()
    left_hand = set('qwertasdfgzxcvb')
    feet = km.keys_for(Action.FOOT_LEFT) + km.keys_for(Action.FOOT_RIGHT)
    assert feet, 'the feet must be bound'
    assert all(len(k) == 1 and k in left_hand for k in feet), feet
    turns = km.keys_for(Action.TURN_LEFT) + km.keys_for(Action.TURN_RIGHT)
    assert turns == ['left', 'right'], turns


def test_there_is_no_snap_turn():
    """The original turned by swiping; it had no 180 degree snap."""
    assert not hasattr(Action, 'TURN_AROUND')
    assert 'turn_around' not in KeyMap().bindings


def test_no_two_gameplay_actions_share_a_key():
    assert KeyMap().conflicts() == {}


def test_rebinding_and_lookup_round_trip(tmp_path=None):
    km = KeyMap()
    km.bind(Action.FOOT_LEFT, ['z'])
    assert km.keys_for(Action.FOOT_LEFT) == ['z']
    assert Action.FOOT_LEFT in km.actions_for('z')
    km.reset()
    assert 'a' in km.keys_for(Action.FOOT_LEFT)


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
