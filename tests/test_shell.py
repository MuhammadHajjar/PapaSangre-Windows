"""The menus, the settings behind them, and the controller.

None of this is in the original in the form it takes here - it had a
touchscreen and a set of nibs - so what these tests pin down is (a) that the
parts which *are* recovered stay recovered, above all the level list, which is
read out of the game's own ``Papa Sangre_hubList.plist`` and spoken with the
two formats from ``AccessibleAllLevelsViewController``, and (b) that the parts
which are additions behave themselves: clamped, persisted, and impossible to
get stuck in.
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.assets.hublist import load_hub_list                # noqa: E402
from papasangre.save import GameProgress                           # noqa: E402
from papasangre.shell import (CREDITS, level_menu, main_menu,      # noqa: E402
                              options_menu, pause_menu)
from papasangre.util.settings import (DEFAULT_TURN_RATE,           # noqa: E402
                                      MAX_TURN_RATE, MIN_TURN_RATE,
                                      Settings)

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')


def temp_progress():
    return GameProgress(path=os.path.join(tempfile.mkdtemp(), 'p.json'))


def temp_settings():
    return Settings(path=os.path.join(tempfile.mkdtemp(), 's.json'))


class FakeEngine:
    """Just enough of AudioEngine for the volume row."""

    def __init__(self, db=3.0):
        self._db = db

    @property
    def master_volume_db(self):
        return self._db

    def adjust_master_volume(self, db):
        self._db = max(-20.0, min(20.0, self._db + db))
        return self._db


# ------------------------------------------------------------- the hub list
def test_the_level_list_is_the_games_own():
    """25 entries, in menu order, with the original's short names."""
    entries = load_hub_list(BUNDLE)
    assert len(entries) == 25
    assert [e.position for e in entries] == list(range(1, 26))
    assert entries[0].file_name == 'ps1_1'
    assert entries[0].alt_name == 'In the Dark'
    assert entries[2].alt_name == 'The Kennel'
    assert entries[24].alt_name == 'Elysium'
    # ps1_1b is chained out of ps1_1 by the level data and is not a menu row,
    # in the original's list either
    assert not any(e.file_name == 'ps1_1b' for e in entries)


def test_only_the_first_level_starts_unlocked():
    entries = load_hub_list(BUNDLE)
    assert entries[0].unlocked_by_default
    assert not any(e.unlocked_by_default for e in entries[1:])


def test_the_two_spoken_formats_are_the_originals():
    """``Play Level %i: %@`` and ``Level %i: %@; locked``."""
    progress = temp_progress()
    entries = load_hub_list(BUNDLE)
    assert entries[0].spoken(progress) == 'Play Level 1: In the Dark'
    assert entries[2].spoken(progress) == 'Level 3: The Kennel; locked'
    progress.player_did_unlock_level('ps1_3')
    assert entries[2].spoken(progress) == 'Play Level 3: The Kennel'


def test_a_missing_plist_does_not_explode():
    assert load_hub_list(tempfile.mkdtemp()) == []


# --------------------------------------------------------------- settings
def test_settings_are_written_on_first_run_and_read_back():
    path = os.path.join(tempfile.mkdtemp(), 's.json')
    s = Settings(path=path)
    assert s.turn_rate == DEFAULT_TURN_RATE
    assert os.path.exists(path), 'defaults should be written out to be found'
    s.turn_rate = 200.0
    assert Settings(path=path).turn_rate == 200.0


def test_settings_clamp_rather_than_accept_nonsense():
    s = temp_settings()
    s.turn_rate = 10_000.0
    assert s.turn_rate == MAX_TURN_RATE
    s.turn_rate = -5.0
    assert s.turn_rate == MIN_TURN_RATE
    s.set('turnRateDegreesPerSecond', 'not a number')
    assert s.turn_rate == DEFAULT_TURN_RATE


def test_a_corrupt_settings_file_is_ignored_not_fatal():
    path = os.path.join(tempfile.mkdtemp(), 's.json')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{ broken')
    assert Settings(path=path).turn_rate == DEFAULT_TURN_RATE


def test_saving_the_volume_keeps_the_reverb_choice():
    """Both live in config/audio.json, so one must not overwrite the other."""
    import papasangre.audio.engine as engine_mod                   # noqa: PLC0415
    from papasangre.util import paths                              # noqa: PLC0415
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, 'config'), exist_ok=True)
    path = os.path.join(d, 'config', 'audio.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'outdoorReverb': 'dry'}, fh)
    original = paths.writable_root
    try:
        paths.writable_root = lambda: d
        engine_mod.save_master_volume(1.41)
    finally:
        paths.writable_root = original
    after = json.load(open(path, encoding='utf-8'))
    assert after['outdoorReverb'] == 'dry', 'the reverb choice was wiped'
    assert after['master_volume'] == 1.41


# ------------------------------------------------------------------ menus
def test_the_main_menu_offers_what_the_original_offered():
    progress = temp_progress()
    m = main_menu(progress, has_progress=False)
    assert [i.action for i in m.items] == ['continue', 'levels', 'options',
                                           'credits', 'quit']
    assert m.current.label == 'Start the game', 'nothing to continue yet'
    progress.player_did_unlock_level('ps1_5')
    m2 = main_menu(progress, has_progress=True)
    assert 'ps1_5' in m2.current.label


def test_the_credits_line_is_the_one_in_the_binary():
    assert CREDITS.startswith("Developped by Somethin' Else")


def test_moving_through_a_menu_wraps_both_ways():
    m = main_menu(temp_progress())
    first = m.speak_current()
    for _ in range(len(m.items)):
        m.move(1)
    assert m.speak_current() == first, 'down should come back round'
    m.move(-1)
    assert m.speak_current() == m.items[-1].label, 'and up from the top wraps'


def test_a_locked_level_cannot_be_chosen():
    progress = temp_progress()
    m = level_menu(BUNDLE, progress)
    assert m.choose() == ('play', 'ps1_1'), 'level 1 is always open'
    m.move(1)
    action, _ = m.choose()
    assert action == 'blocked'
    progress.player_did_unlock_level('ps1_2')
    m2 = level_menu(BUNDLE, progress)
    m2.move(1)
    assert m2.choose() == ('play', 'ps1_2')


def test_the_level_menu_always_has_a_way_out():
    m = level_menu(BUNDLE, temp_progress())
    assert m.items[-1].action == 'back'


def test_the_options_rows_adjust_and_persist():
    path = os.path.join(tempfile.mkdtemp(), 's.json')
    s = Settings(path=path)
    eng = FakeEngine()
    m = options_menu(s, eng)
    assert 'Sound volume' in m.speak_current()
    assert m.adjust_current(+1) == 'Sound volume, +5 decibels'
    assert eng.master_volume_db == 5.0

    m.move(1)
    assert 'Turning speed' in m.speak_current()
    m.adjust_current(+1)
    assert s.turn_rate == DEFAULT_TURN_RATE + 15.0
    assert Settings(path=path).turn_rate == DEFAULT_TURN_RATE + 15.0, \
        'the setting should already be on disk'

    m.move(1)
    assert m.current.action == 'keys', 'rebinding lives under Options'
    m.move(1)
    assert m.current.action == 'buttons', 'and so does the controller'
    m.move(1)
    assert m.current.action == 'back'
    assert m.adjust_current(+1) is None, 'Back is not a slider'


def test_the_options_rows_say_when_they_run_out():
    s = temp_settings()
    m = options_menu(s, FakeEngine())
    m.move(1)                                  # turning speed
    for _ in range(40):
        said = m.adjust_current(+1)
    assert said.endswith('fastest'), said
    for _ in range(40):
        said = m.adjust_current(-1)
    assert said.endswith('slowest'), said


def test_enter_on_a_slider_does_not_leave_the_options_menu():
    """The row is changed with left and right; Enter must not pick it."""
    m = options_menu(temp_settings(), FakeEngine())
    action, _ = m.choose()
    assert action == 'adjust', 'the runner treats this as "stay here"'


def test_the_pause_menu_can_resume_restart_or_leave():
    m = pause_menu()
    assert [i.action for i in m.items] == ['resume', 'options', 'restart',
                                           'main', 'quit']


# -------------------------------------------------------------- controller
def fake_pad(axis_value=0.0):
    """An *unrecognised* pad: the raw joystick fallback path."""
    import types                                                 # noqa: PLC0415
    from papasangre.input.gamepad import Gamepad, _button_names  # noqa: PLC0415
    from papasangre.input.padmap import PadMap                   # noqa: PLC0415
    g = Gamepad.__new__(Gamepad)
    g.controller = None
    g.joystick = types.SimpleNamespace(
        get_axis=lambda i, v=axis_value: v if i == 2 else 0.0)
    g.held = set()
    g._hat = (0, 0)
    g._names = _button_names()
    g.padmap = PadMap()
    g.name = 'test pad'
    return g


def fake_controller(axis_value=0):
    """A pad SDL *does* know: the normalised game controller path."""
    import types                                                 # noqa: PLC0415
    from papasangre.input.gamepad import Gamepad, _button_names  # noqa: PLC0415
    from papasangre.input.padmap import PadMap                   # noqa: PLC0415
    g = Gamepad.__new__(Gamepad)
    g.controller = types.SimpleNamespace(
        get_axis=lambda a, v=axis_value: v, name='test controller',
        quit=lambda: None)
    g.joystick = None
    g.held = set()
    g._hat = (0, 0)
    g._names = _button_names()
    g.padmap = PadMap()
    g.name = 'test controller'
    return g


def cbutton(down, const):
    import types                                                 # noqa: PLC0415
    import pygame                                                # noqa: PLC0415
    return types.SimpleNamespace(
        type=pygame.CONTROLLERBUTTONDOWN if down else pygame.CONTROLLERBUTTONUP,
        button=const)


def hat(value):
    import types                                                 # noqa: PLC0415
    import pygame                                                # noqa: PLC0415
    return types.SimpleNamespace(type=pygame.JOYHATMOTION, value=value)


def button(down, number):
    import types                                                 # noqa: PLC0415
    import pygame                                                # noqa: PLC0415
    return types.SimpleNamespace(
        type=pygame.JOYBUTTONDOWN if down else pygame.JOYBUTTONUP,
        button=number)


def test_the_dpad_gives_a_press_and_a_release_per_foot():
    """Walking is timed on the *release*, so both edges have to be reported.

    This is why the feet are on the hat and not on a stick: a foot is a
    discrete press, and the whole movement system is built on the interval
    between them.
    """
    g = fake_pad()
    out = [(a, p) for a, p, _ in g.handle(hat((1, 0)))]
    assert ('foot_right', 'down') in out
    out = [(a, p) for a, p, _ in g.handle(hat((0, 0)))]
    assert ('foot_right', 'up') in out
    out = [(a, p) for a, p, _ in g.handle(hat((-1, 0)))]
    assert ('foot_left', 'down') in out


def test_the_dpad_is_feet_in_play_and_a_slider_in_a_menu():
    """Left and right send both meanings; each context ignores the other.

    That is what lets the d-pad be your feet while walking *and* change a
    setting in the options, without the keyboard's A and D doing the latter -
    which is the whole point of having separate menu actions.
    """
    g = fake_pad()
    out = [a for a, p, _ in g.handle(hat((1, 0))) if p == 'down']
    assert set(out) == {'foot_right', 'menu_right'}
    g.handle(hat((0, 0)))
    out = [a for a, p, _ in g.handle(hat((-1, 0))) if p == 'down']
    assert set(out) == {'foot_left', 'menu_left'}


def test_only_the_arrow_keys_change_a_setting_never_the_feet():
    """A and D are feet and only feet; the arrows adjust."""
    from papasangre.input.keymap import Action, KeyMap             # noqa: PLC0415
    km = KeyMap()
    assert Action.MENU_LEFT.value in km.actions_for('left')
    assert Action.MENU_RIGHT.value in km.actions_for('right')
    assert Action.MENU_LEFT.value not in km.actions_for('a')
    assert Action.MENU_RIGHT.value not in km.actions_for('d')
    assert km.actions_for('a') == [Action.FOOT_LEFT.value]
    assert km.actions_for('d') == [Action.FOOT_RIGHT.value]


def test_rolling_the_dpad_releases_the_foot_it_leaves():
    """Going straight from left to up must not leave a foot stuck down."""
    g = fake_pad()
    g.handle(hat((-1, 0)))
    assert g.is_held('foot_left')
    out = [(a, p) for a, p, _ in g.handle(hat((0, 1)))]
    assert ('foot_left', 'up') in out
    assert ('menu_left', 'up') in out
    assert ('menu_up', 'down') in out
    assert not g.is_held('foot_left')


def test_a_and_b_are_select_and_back():
    g = fake_pad()
    assert set(a for a, _p, _t in g.handle(button(True, 0))) == {'confirm',
                                                                 'skip'}
    assert [a for a, _p, _t in g.handle(button(True, 1))] == ['cancel']
    g.handle(button(False, 0))
    assert not g.is_held('confirm')


def test_the_right_stick_is_a_rate_with_a_dead_zone():
    from papasangre.input.gamepad import DEAD_ZONE                # noqa: PLC0415
    assert fake_pad(0.0).turn_rate() == 0.0
    assert fake_pad(DEAD_ZONE - 0.01).turn_rate() == 0.0, 'resting stick'
    # and it ramps from zero at the edge rather than jumping
    just_past = fake_pad(DEAD_ZONE + 0.001).turn_rate()
    assert 0.0 < just_past < 0.05, just_past
    assert abs(fake_pad(1.0).turn_rate() - 1.0) < 1e-9
    assert abs(fake_pad(-1.0).turn_rate() + 1.0) < 1e-9


def test_no_controller_is_not_an_error():
    import types                                                 # noqa: PLC0415
    from papasangre.input.gamepad import Gamepad                 # noqa: PLC0415
    g = Gamepad.__new__(Gamepad)
    g.controller = None
    g.joystick = None
    from papasangre.input.padmap import PadMap                   # noqa: PLC0415
    g.held = set()
    g._hat = (0, 0)
    g._names = {}
    g.padmap = PadMap()
    g.name = ''
    assert not g.connected
    assert g.turn_rate() == 0.0
    assert g.handle(types.SimpleNamespace(type=0)) == []
    assert 'No controller' in g.describe()


# ------------------------------------------------------- keys and plumbing
def test_escape_pauses_in_play_and_backs_out_of_a_menu():
    """One key, two jobs, and they never collide.

    In play the pause handler runs and CANCEL is ignored; in a menu CANCEL
    backs out and PAUSE is ignored.
    """
    from papasangre.input.keymap import Action, KeyMap             # noqa: PLC0415
    km = KeyMap()
    assert set(km.actions_for('escape')) == {Action.PAUSE.value,
                                             Action.CANCEL.value}
    assert km.actions_for('backspace') == [Action.CANCEL.value]


def test_nothing_on_the_keyboard_quits_the_game():
    """Quitting is alt+F4 or the menu.  Escape used to kill the run."""
    source = open(os.path.join(ROOT, 'apps', 'play.py'), encoding='utf-8').read()
    body = source[source.index('def main('):]
    # CANCEL must not be followed by a quit anywhere in the play loop
    for chunk in body.split('Action.CANCEL.value')[1:]:
        assert 'running = False' not in chunk.split('elif')[0], \
            'cancel still quits the game'
    # the only quits left are the menu, the window closing, and the ending
    assert 'if src.quit_requested:' in body


def test_the_openal_config_is_not_written_next_to_the_game():
    """It is plumbing, rewritten every start, with an absolute path in it.

    Left beside the executable it would be both a stale path on anyone else's
    machine and an invitation to switch HRTF off, which this game cannot do
    without.
    """
    from papasangre.util import paths                              # noqa: PLC0415
    conf = paths.config_path()
    assert os.path.basename(conf) == 'alsoft.ini'
    assert tempfile.gettempdir().lower() in conf.lower(), conf
    assert os.path.dirname(conf) != paths.config_dir()


def test_the_players_own_settings_do_live_next_to_the_game():
    from papasangre.util import paths                              # noqa: PLC0415
    d = paths.config_dir()
    assert d.endswith('config')
    assert tempfile.gettempdir().lower() not in d.lower()
    assert GameProgress().path.startswith(d)


def test_output_survives_having_no_console():
    """The game is built windowed, so sys.stdout is None."""
    import sys as _sys                                             # noqa: PLC0415
    from papasangre.util import console                            # noqa: PLC0415
    rep = console.Reporter(speak_all=False)
    real = _sys.stdout
    _sys.stdout = None
    try:
        rep.show('this must not raise')
        rep.say('nor this')
        rep.hold()          # must return rather than wait for a console
    finally:
        _sys.stdout = real


def test_buttons_come_from_sdls_layout_not_raw_numbers():
    """The reason this matters: raw numbering is per-device.

    On an Xbox pad raw button 0 is A and 7 is Start; on a DualShock 4 raw 0 is
    Square and 7 is R2.  Going through SDL's controller database means ``A``
    is *the bottom face button* - Cross on a PlayStation pad - and ``Start`` is
    Options, without this code knowing which pad is plugged in.
    """
    import pygame                                                # noqa: PLC0415
    g = fake_controller()
    assert g.recognised
    cases = {
        # A both confirms and skips, exactly as Enter does on the keyboard.
        pygame.CONTROLLER_BUTTON_A: {'confirm', 'skip'},
        pygame.CONTROLLER_BUTTON_B: {'cancel'},
        pygame.CONTROLLER_BUTTON_X: {'skip'},
        pygame.CONTROLLER_BUTTON_BACK: {'cancel'},
        pygame.CONTROLLER_BUTTON_START: {'pause'},
    }
    for const, expected in cases.items():
        out = [a for a, p, _ in g.handle(cbutton(True, const)) if p == 'down']
        assert set(out) == expected, f'{const} gave {out}, wanted {expected}'
        g.handle(cbutton(False, const))


def test_start_opens_the_pause_menu():
    """Options on a PlayStation pad, Start/Menu on an Xbox one."""
    import pygame                                                # noqa: PLC0415
    from papasangre.input.keymap import Action                   # noqa: PLC0415
    g = fake_controller()
    out = [(a, p) for a, p, _ in g.handle(
        cbutton(True, pygame.CONTROLLER_BUTTON_START))]
    assert out == [(Action.PAUSE.value, 'down')]
    assert g.is_held(Action.PAUSE)
    g.handle(cbutton(False, pygame.CONTROLLER_BUTTON_START))
    assert not g.is_held(Action.PAUSE)


def test_the_dpad_is_buttons_on_a_recognised_pad():
    """Not a hat - the controller API reports each direction as a button."""
    import pygame                                                # noqa: PLC0415
    g = fake_controller()
    down = [a for a, p, _ in g.handle(
        cbutton(True, pygame.CONTROLLER_BUTTON_DPAD_LEFT)) if p == 'down']
    assert set(down) == {'foot_left', 'menu_left'}
    up = [a for a, p, _ in g.handle(
        cbutton(False, pygame.CONTROLLER_BUTTON_DPAD_LEFT)) if p == 'up']
    assert set(up) == {'foot_left', 'menu_left'}
    assert not g.is_held('foot_left'), 'the foot must be released'


def test_the_controller_stick_is_sixteen_bit_and_still_normalised():
    """The controller API reports -32768..32767 where a joystick gives -1..1."""
    assert fake_controller(0).turn_rate() == 0.0
    assert fake_controller(8000).turn_rate() == 0.0, 'inside the dead zone'
    assert abs(fake_controller(32767).turn_rate() - 1.0) < 1e-3
    assert abs(fake_controller(-32767).turn_rate() + 1.0) < 1e-3
    mid = fake_controller(16384).turn_rate()
    assert 0.0 < mid < 1.0, mid


def test_an_unknown_pad_says_so():
    g = fake_pad()
    assert not g.recognised
    assert 'best guess' in g.describe()
    assert 'best guess' not in fake_controller().describe()


# ------------------------------------------------- keys, endings, ambience
def test_the_keys_menu_lists_only_what_this_game_uses():
    """Hands, clapping, jump and swim are never enabled by Papa Sangre 1.

    Offering a binding for something the game will not do is a trap, so they
    are left out.
    """
    from papasangre.input.keymap import KeyMap                   # noqa: PLC0415
    from papasangre.shell import keys_menu                       # noqa: PLC0415
    from papasangre.shell.menu import REBINDABLE                 # noqa: PLC0415
    offered = {a for a, _label in REBINDABLE}
    assert 'foot_left' in offered and 'turn_left' in offered
    for never in ('hand_left', 'hand_right', 'clap', 'jump', 'swim'):
        assert never not in offered, never
    m = keys_menu(KeyMap())
    assert m.items[0].label == 'Left foot: a'
    assert m.items[-1].action == 'back'
    assert m.items[-2].action == 'reset_keys'


def test_rebinding_a_key_survives_and_resets():
    from papasangre.input.keymap import KeyMap                   # noqa: PLC0415
    from papasangre.shell import keys_menu                       # noqa: PLC0415
    path = os.path.join(tempfile.mkdtemp(), 'keys.json')
    km = KeyMap()
    km.bind('foot_left', ['z'])
    km.save(path)
    assert keys_menu(km).items[0].label == 'Left foot: z'
    assert KeyMap.load(path).keys_for('foot_left') == ['z']
    km.reset()
    assert km.keys_for('foot_left') == ['a']


def test_the_level_complete_menu_offers_a_way_on_and_a_way_back():
    from papasangre.shell import (level_complete_menu,           # noqa: PLC0415
                                  level_failed_menu)
    m = level_complete_menu('ps1_8', 'The Charnel House')
    assert m.title.startswith('The Charnel House')
    actions = [i.action for i in m.items]
    assert actions[0] == 'next' and m.items[0].value == 'ps1_8'
    assert 'replay' in actions and 'main' in actions and 'quit' in actions
    # the last level has nowhere to continue to
    last = level_complete_menu(None, 'Elysium')
    assert 'next' not in [i.action for i in last.items]
    # and a failed level offers a retry, not a continue
    failed = level_failed_menu('The Kennel')
    assert [i.action for i in failed.items][0] == 'replay'
    assert 'next' not in [i.action for i in failed.items]


def test_every_dilemma_level_gets_the_telephone_door():
    """The beacon you walk towards to leave a level where you saved someone.

    ps1_7's exit loops ``door_telephone_living`` - the door *is* a ringing
    phone.  ps1_12, 18 and 23 shipped with ordinary doors instead (a balloon, a
    vacuum, a castle), which reads as an oversight rather than a design.
    REQUESTED: make all four ring.  Only ps1_7's playlist declares the sound,
    so the others are handed the file directly.
    """
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import autoplay                                              # noqa: PLC0415
    for stem in ('ps1_7', 'ps1_12', 'ps1_18', 'ps1_23'):
        _bus, _mi, bank, lv = autoplay.build(stem)
        door = lv.agent('exit')
        assert door.loop_sound == 'door_telephone_living',             f'{stem} exit loops {door.loop_sound}'


def test_only_dilemma_levels_get_it():
    """A level with nobody to save keeps its own door."""
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import autoplay                                              # noqa: PLC0415
    for stem in ('ps1_8', 'ps1_9', 'ps1_2'):
        _bus, _mi, _bank, lv = autoplay.build(stem)
        door = lv.agent('exit')
        if door is not None:
            assert door.loop_sound != 'door_telephone_living', stem


def test_the_telephone_is_declared_by_only_one_level():
    """Which is why the bank has to be handed the file for the other three."""
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import autoplay                                              # noqa: PLC0415
    declares = {stem for stem in ('ps1_7', 'ps1_12', 'ps1_18', 'ps1_23')
                if 'door_telephone_living' in autoplay.declared(stem)}
    assert declares == {'ps1_7'}, declares


def test_the_splash_the_intro_uses_is_really_there():
    from papasangre.util import paths                            # noqa: PLC0415
    sys.path.insert(0, os.path.join(ROOT, 'apps'))
    path = paths.game_audio('ps1', 'splash', 'papa_engine_splash.wav')
    assert os.path.exists(path), path


def test_a_keymap_from_an_older_build_is_replaced_not_obeyed():
    """A stored binding overrides the default, which broke escape.

    Escape moved from "quit" to "open the pause menu", but anyone who had
    already run the game had ``pause: ["p"]`` on disk, and the stored value
    won.  The file carries a version now, and a mismatch resets it.
    """
    import json as _json                                         # noqa: PLC0415
    from papasangre.input.keymap import Action, KeyMap           # noqa: PLC0415
    path = os.path.join(tempfile.mkdtemp(), 'keys.json')
    with open(path, 'w', encoding='utf-8') as fh:
        _json.dump({'pause': ['p'], 'cancel': ['escape', 'backspace']}, fh)
    km = KeyMap.load(path)
    assert km.was_reset, 'an unversioned file should be replaced'
    assert Action.PAUSE.value in km.actions_for('escape')
    # and once rewritten it is left alone, customisations included
    km.bind('foot_left', ['z'])
    km.save(path)
    again = KeyMap.load(path)
    assert not again.was_reset
    assert again.keys_for('foot_left') == ['z']


def test_the_ambience_is_fetched_again_rather_than_resumed():
    """``deactivate`` drops the sound, so there is nothing left to restart.

    ShutDownLevel deactivates every agent, and ``GameAgent.deactivate`` sets
    ``self.sound = None``.  Restarting ``agent.sound`` for the level-complete
    menu therefore did nothing at all - it has to come from the bank by name.
    """
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import autoplay                                              # noqa: PLC0415
    bus, _mi, bank, lv = autoplay.build('ps1_9')
    lv.start(0.0)
    bus.now = 1.0
    lv.update(1.0)
    atmos = [a for a in lv.agents if a.name.startswith('atmos')]
    assert atmos, 'ps1_9 has atmospheres'
    for a in atmos:
        a.activate()
    bus.post('PGE_MESSAGE_ShutDownLevel', {'senderName': 'exit'})
    bus.now = 1.1
    lv.update(1.1)
    assert all(a.sound is None for a in atmos),         'shutdown drops the sound - this is the thing that broke it'
    # but the bank can still produce it by name, which is what the fix does
    for a in atmos:
        assert bank.from_sound_list(a.sound_list) is not None, a.name


def test_a_collectible_can_be_sprung_again_after_it_is_deactivated():
    """``-[PGECollectible deactivate]`` clears ``collected`` (0x10001bb04).

    ``collected`` is a *latch against re-collecting while the collect sound is
    still playing*, not a record that something was ever picked up - and the
    original ends that sound with ``setActive:NO``, which routes through
    ``deactivate`` (0x10001fe30) and clears it again.

    ps1_23's chicken cage is built entirely on this: the launcher is
    re-activated 20 seconds later by ``chicken_1``'s ``OnDeactivate``, and
    without the clear it comes back but can never be sprung a second time.
    """
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import autoplay                                              # noqa: PLC0415
    bus, _mi, _bank, lv = autoplay.build('ps1_23')
    lv.start(0.0)
    for a in lv.agents:
        if a.sound is not None:
            a.sound.stop()
    t = 1.0
    for step in (t, t + 0.1):
        bus.now = step
        lv.update(step)
    t += 0.1
    launcher = lv.agent('chicken_launcher_1')
    chicken = lv.agent('chicken_1')
    away = (launcher.position[0] + 300, launcher.position[1])

    def stand(pos, secs, t):
        lv.player.position = pos
        bus.post('PGE_MESSAGE_PlayerMovedToPosition', {'position': pos})
        for _ in range(int(secs / 0.1)):
            t += 0.1
            bus.now = t
            lv.update(t)
            if launcher.sound is not None and launcher._phase == 'collect':
                launcher.sound.stop()
        return t

    for visit in (1, 2, 3):
        t = stand(launcher.position, 1.0, t)
        assert chicken.active, f'the cage did not spring on visit {visit}'
        t = stand(away, 25.0, t)          # walk off and wait out the re-arm
        assert launcher.active, f'it did not re-arm after visit {visit}'
        assert not launcher.collected, f'still latched after visit {visit}'


def test_collected_is_a_latch_and_was_collected_is_the_record():
    """The two are deliberately different, because the original's is transient."""
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import autoplay                                              # noqa: PLC0415
    bus, _mi, _bank, lv = autoplay.build('ps1_9')
    note = lv.agent('note1')
    note.active = True
    note.collides_with_player()
    assert note.collected and note.was_collected
    note.deactivate()
    assert not note.collected, 'the latch is released'
    assert note.was_collected, 'but the record is kept'


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


# ------------------------------------------------- rebinding the controller
def temp_padmap():
    from papasangre.input.padmap import PadMap                   # noqa: PLC0415
    return PadMap.load(os.path.join(tempfile.mkdtemp(), 'c.json'))


def test_the_controller_map_is_written_out_and_read_back():
    from papasangre.input.padmap import PadMap                   # noqa: PLC0415
    path = os.path.join(tempfile.mkdtemp(), 'c.json')
    pm = PadMap.load(path)
    assert os.path.exists(path), 'defaults should be written out to be found'
    pm.bind('foot_left', ['x'])
    pm.save(path)
    assert PadMap.load(path).buttons_for('foot_left') == ['x']


def test_rebinding_a_button_changes_what_the_pad_sends():
    """The binding is what the gamepad reads - not a table inside it."""
    import pygame                                                # noqa: PLC0415
    g = fake_controller()
    g.padmap.bind('foot_left', ['y'])
    out = [a for a, p, _ in g.handle(
        cbutton(True, pygame.CONTROLLER_BUTTON_Y)) if p == 'down']
    assert out == ['foot_left']
    out = [a for a, p, _ in g.handle(
        cbutton(True, pygame.CONTROLLER_BUTTON_DPAD_LEFT)) if p == 'down']
    assert 'foot_left' not in out, 'the old button should have let go of it'


def test_a_binding_survives_the_raw_fallback_path():
    """A pad SDL does not know still honours a binding made by name."""
    g = fake_pad()
    g.padmap.bind('pause', ['y'])
    assert [a for a, _p, _t in g.handle(button(True, 3))] == ['pause']


def test_the_controller_map_can_be_restored_to_its_defaults():
    pm = temp_padmap()
    pm.bind('confirm', ['y'])
    pm.reset()
    assert pm.buttons_for('confirm') == ['a']


def test_an_old_controller_file_is_replaced_not_obeyed():
    """Same contract as keys.json: a stale file must not override a new default."""
    from papasangre.input.padmap import PadMap, VERSION_KEY      # noqa: PLC0415
    path = os.path.join(tempfile.mkdtemp(), 'c.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({VERSION_KEY: 0, 'confirm': ['start']}, fh)
    pm = PadMap.load(path)
    assert pm.was_reset
    assert pm.buttons_for('confirm') == ['a']


def test_a_corrupt_controller_file_is_ignored_not_fatal():
    from papasangre.input.padmap import PadMap                   # noqa: PLC0415
    path = os.path.join(tempfile.mkdtemp(), 'c.json')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{ broken')
    assert PadMap.load(path).buttons_for('confirm') == ['a']


def test_the_button_menu_reads_every_binding_and_offers_a_reset():
    from papasangre.shell import pad_menu                        # noqa: PLC0415
    m = pad_menu(temp_padmap())
    assert m.items[0].label == 'Left foot: D-pad left'
    assert m.items[-1].action == 'back'
    assert m.items[-2].action == 'reset_buttons'
    assert all(i.action == 'rebind_button' for i in m.items[:-2])


def test_the_pad_describes_itself_from_its_bindings():
    """After a rebind the spoken help has to say the new button, not the old."""
    g = fake_controller()
    g.padmap.bind('pause', ['back'])
    assert 'Back, or share' in g.describe()


# --------------------------------------------- the menu runner in apps/play
class FakeRep:
    """Stands in for the console reporter: remembers what was spoken."""

    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(str(text))

    def show(self, text=''):
        pass


class FakeClock:
    def tick(self, _fps=60):
        return 16


class FakeSource:
    """Feeds run_menu a script of actions, then whatever capture returns."""

    def __init__(self, script, key=None, button=None, pad_connected=True):
        self.script = list(script)
        self.key = key
        self.button = button
        self.quit_requested = False
        self.captured = 0
        import types                                             # noqa: PLC0415
        self.pad = types.SimpleNamespace(connected=pad_connected)

    def poll(self):
        if not self.script:
            return []
        return [(self.script.pop(0), 'down', 0.0)]

    def capture_key(self, _timeout=10.0):
        self.captured += 1
        return self.key

    def capture_button(self, _timeout=10.0):
        self.captured += 1
        return self.button


def load_play():
    """Import apps/play.py as a module without running it."""
    import importlib.util                                        # noqa: PLC0415
    path = os.path.join(ROOT, 'apps', 'play.py')
    spec = importlib.util.spec_from_file_location('ps_play_for_tests', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_choosing_a_key_row_really_rebinds_it():
    """Every action the key menu emits must have a handler in run_menu.

    It did not: ``rebind`` was called and never defined, so choosing a row
    raised NameError - and nothing caught it because no test had ever driven
    the menu itself, only built it.
    """
    from papasangre.input.keymap import Action, KeyMap            # noqa: PLC0415
    from papasangre.shell import keys_menu                        # noqa: PLC0415
    play = load_play()
    km = KeyMap.load(os.path.join(tempfile.mkdtemp(), 'k.json'))
    src = FakeSource([Action.CONFIRM.value, Action.CANCEL.value], key='z')
    rep = FakeRep()
    act, _ = play.run_menu(keys_menu(km), src, rep, FakeClock(), None, None, km)
    assert act == 'back'
    assert src.captured == 1, 'it should have waited for a key'
    assert km.keys_for('foot_left') == ['z']
    assert any('now z' in s for s in rep.said)


def test_choosing_a_button_row_really_rebinds_it():
    from papasangre.input.keymap import Action                    # noqa: PLC0415
    from papasangre.shell import pad_menu                         # noqa: PLC0415
    play = load_play()
    pm = temp_padmap()
    src = FakeSource([Action.CONFIRM.value, Action.CANCEL.value], button='y')
    rep = FakeRep()
    act, _ = play.run_menu(pad_menu(pm), src, rep, FakeClock(), None, None,
                           None, pm)
    assert act == 'back'
    assert pm.buttons_for('foot_left') == ['y']
    assert any('Y, or triangle' in s for s in rep.said)


def test_cancelling_a_rebind_leaves_the_binding_alone():
    from papasangre.input.keymap import Action, KeyMap            # noqa: PLC0415
    from papasangre.shell import keys_menu                        # noqa: PLC0415
    play = load_play()
    km = KeyMap.load(os.path.join(tempfile.mkdtemp(), 'k.json'))
    src = FakeSource([Action.CONFIRM.value, Action.CANCEL.value], key=None)
    play.run_menu(keys_menu(km), src, FakeRep(), FakeClock(), None, None, km)
    assert km.keys_for('foot_left') == ['a'], 'escape must change nothing'


def test_rebinding_with_no_controller_says_so_instead_of_waiting():
    from papasangre.input.keymap import Action                    # noqa: PLC0415
    from papasangre.shell import pad_menu                         # noqa: PLC0415
    play = load_play()
    pm = temp_padmap()
    src = FakeSource([Action.CONFIRM.value, Action.CANCEL.value],
                     button='y', pad_connected=False)
    rep = FakeRep()
    play.run_menu(pad_menu(pm), src, rep, FakeClock(), None, None, None, pm)
    assert src.captured == 0, 'nothing to press: it must not sit there waiting'
    assert pm.buttons_for('foot_left') == ['dpleft']
    assert any('No controller' in s for s in rep.said)


def test_resetting_the_buttons_from_the_menu():
    from papasangre.input.keymap import Action                    # noqa: PLC0415
    from papasangre.shell import pad_menu                         # noqa: PLC0415
    play = load_play()
    pm = temp_padmap()
    pm.bind('confirm', ['start'])
    menu = pad_menu(pm)
    for _ in range(len(menu.items) - 2):
        menu.move(1)
    assert menu.current.action == 'reset_buttons'
    src = FakeSource([Action.CONFIRM.value, Action.CANCEL.value])
    play.run_menu(menu, src, FakeRep(), FakeClock(), None, None, None, pm)
    assert pm.buttons_for('confirm') == ['a']


def test_one_press_of_enter_only_chooses_once():
    """Enter is bound to confirm *and* skip, so it arrives as two actions.

    On a rebinding row that meant being asked for a key twice for one press.
    """
    from papasangre.input.keymap import Action, KeyMap             # noqa: PLC0415
    from papasangre.shell import keys_menu                         # noqa: PLC0415
    play = load_play()

    class BothAtOnce(FakeSource):
        def poll(self):
            if not self.script:
                return []
            first = self.script.pop(0)
            if first == Action.CONFIRM.value:
                return [(Action.CONFIRM.value, 'down', 0.0),
                        (Action.SKIP.value, 'down', 0.0)]
            return [(first, 'down', 0.0)]

    km = KeyMap.load(os.path.join(tempfile.mkdtemp(), 'k.json'))
    src = BothAtOnce([Action.CONFIRM.value, Action.CANCEL.value], key='z')
    play.run_menu(keys_menu(km), src, FakeRep(), FakeClock(), None, None, km)
    assert src.captured == 1, f'asked for a key {src.captured} times'
