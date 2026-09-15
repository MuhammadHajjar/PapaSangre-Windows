"""PGEGameProgress and the pause/resume path (the last two classes audited)."""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from papasangre.core.messages import MessageBus                   # noqa: E402
from papasangre.input.interpreter import (LEFT, RIGHT,            # noqa: E402
                                          MoveInterpretor)
from papasangre.save import GameProgress                          # noqa: E402
from papasangre.world.level import Level                          # noqa: E402
from test_level import FakeBank, LEVEL1_SOUNDS                    # noqa: E402

EXPORTS = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app',
                       'Exports', 'Papa Sangre')


def fresh():
    return GameProgress(path=os.path.join(tempfile.mkdtemp(), 'progress.json'))


# ------------------------------------------------------------------ progress
def test_the_first_level_is_the_default_when_nothing_is_saved():
    assert fresh().last_unlocked_level == 'ps1_1'
    other = GameProgress(path=os.path.join(tempfile.mkdtemp(), 'p.json'),
                         app_name='The Nightjar')
    assert other.last_unlocked_level == 'nightJar_1'


def test_completion_and_unlocking_round_trip_through_the_file():
    g = fresh()
    g.player_did_complete_level('ps1_1')
    g.player_did_unlock_level('ps1_1b')
    again = GameProgress(path=g.path)
    assert again.is_level_completed('ps1_1')
    assert again.is_level_unlocked('ps1_1b')
    assert not again.is_level_unlocked('ps1_9')


def test_unlocking_a_level_twice_does_not_wind_progress_back():
    """playerDidUnlockLevel: writes lastLevelUnlocked only on the first unlock."""
    g = fresh()
    g.player_did_unlock_level('ps1_2')
    g.player_did_unlock_level('ps1_3')
    assert g.last_unlocked_level == 'ps1_3'
    g.player_did_unlock_level('ps1_2')          # replaying an earlier level
    assert g.last_unlocked_level == 'ps1_3'


def test_the_saved_keys_are_the_originals_including_its_typo():
    g = fresh()
    g.player_did_complete_level('ps1_1')
    g.player_did_unlock_level('ps1_2')
    g.save_last_playlist('ps1_2')
    assert 'ps1_1_completed' in g.values
    assert 'ps1_2_locked' in g.values, 'the key reads backwards in the original'
    assert 'lastPLaylist' in g.values, 'the capital L is the original spelling'
    assert 'lastLevelUnlocked' in g.values


def test_a_heard_narration_becomes_skippable_and_stays_so():
    g = fresh()
    assert not g.can_skip_sound('FINAL_ITD_Intro')
    g.save_skippable_sound('FINAL_ITD_Intro')
    assert GameProgress(path=g.path).can_skip_sound('FINAL_ITD_Intro')


def test_a_corrupt_save_does_not_stop_the_game():
    path = os.path.join(tempfile.mkdtemp(), 'progress.json')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{ this is not json')
    g = GameProgress(path=path)
    assert g.last_unlocked_level == 'ps1_1'


def test_a_torn_save_falls_back_to_the_backup_instead_of_starting_over():
    """Reported after 1.0.0: "the game crashes, and all of your progress is
    lost".  A save is rewritten on every unlock, and opening it for writing
    truncates it first, so anything that killed the process around that moment
    left a file that would not parse - and an unparseable save was treated as
    no save at all."""
    path = os.path.join(tempfile.mkdtemp(), 'progress.json')
    g = GameProgress(path=path)
    for i in range(1, 6):
        g.player_did_unlock_level(f'ps1_{i}')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('{"ps1_1_locked": tr')          # a write that did not finish
    back = GameProgress(path=path)
    # The backup is the file as it was one write ago, so the guarantee is that
    # you lose at most the last thing you did - not the playthrough.
    assert back.last_unlocked_level == 'ps1_4'
    assert back.is_level_unlocked('ps1_3')


def test_the_save_is_never_left_half_written():
    """The real file is only ever replaced by a complete one."""
    import json                                                  # noqa: PLC0415
    path = os.path.join(tempfile.mkdtemp(), 'progress.json')
    g = GameProgress(path=path)
    for i in range(1, 4):
        g.player_did_unlock_level(f'ps1_{i}')
        json.load(open(path, encoding='utf-8'))   # parses after every write
    assert not os.path.exists(path + '.tmp'), 'no scratch file left behind'


# --------------------------------------------------------------- pause
def build():
    bus = MessageBus()
    mi = MoveInterpretor(bus)
    bank = FakeBank(LEVEL1_SOUNDS)
    lv = Level(bus, bank).load(os.path.join(EXPORTS, 'ps1_1.json'), 'ps1_1')
    return bus, mi, bank, lv


def test_pausing_holds_the_sounds_and_the_clock():
    bus, mi, bank, lv = build()
    lv.start(0.0)
    intro = lv.agent('FINAL_ITD_Intro')
    assert intro.sound.playing

    lv.pause()
    assert lv.paused
    assert not intro.sound.playing, 'the narration should be held, not stopped'
    assert intro.sound_was_paused

    where = lv.player.position
    bus.now = 5.0
    lv.update(5.0)                       # the world must not move on
    assert lv.player.position == where

    lv.resume(5.0)
    assert not lv.paused
    assert intro.sound.playing, 'and it should carry on where it left off'
    assert lv.last_activity == 5.0, 'the paused time must not count as idling'


def test_resume_only_restarts_what_the_pause_actually_stopped():
    bus, mi, bank, lv = build()
    lv.start(0.0)
    quiet = lv.agent('Atmos_darkrumble_01')
    quiet.sound = bank.sound('Atmos_darkrumble_01')
    quiet.sound.stop()
    lv.pause()
    lv.resume(1.0)
    assert not quiet.sound.playing


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
