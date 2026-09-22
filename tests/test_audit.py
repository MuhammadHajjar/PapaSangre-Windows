"""Regression tests for the content audit as it ships on a fresh clone.

``prepare_content_data`` and ``tools/audit.py`` need the engine's message
vocabulary, whose canonical source (``tools/ps_strings.txt``) is an extraction
of the original binary and is not committed.  These tests pin the assembled
fallback that replaces it: every real message the level data uses is known,
the malformed strings in the shipped data are not, and the two building
blocks the games build depends on resolve without the binary.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.assets import audit                             # noqa: E402


#: The eight strings in the shipped data that are *not* engine messages - the
#: known defects of the original (GAME_STRUCTURE.md section 11), as they
#: actually appear on the triggers:
#: 2x PGE_MESSAGE_AlertAllAgents (only AlertAllEnemies exists) · one each of
#: the lowercase-L ChangeInactivitySoundlist typo, both parameterised
#: ChangeInactivitySoundList strings, the bare FINAL_thefatebell, the
#: malformed ActivateAgentWithName with params in the name, and the
#: quicksand ampersand concatenation.
NOT_MESSAGES = (
    'PGE_MESSAGE_AlertAllAgents',
    'PGE_MESSAGE_ChangeInactivitySoundlist',
    'PGE_MESSAGE_ActivateAgentWithName:name=chicken_launcher_3:afterDelay=20',
    'PGE_MESSAGE_ChangeInactivitySoundList_soundList='
    'FINAL_glasscathedral_inactive_1&FINAL_glasscathedral_inactive_2',
    'PGE_MESSAGE_ChangeInactivitySoundList=soundList='
    'FINAL_thefatebell_inactive_2B',
    'PGE_MESSAGE_FINAL_thefatebell_inactive_2',
    'PGE_MESSAGE_quicksand_edge_atmos1&quicksand_edge_atmos2',
)

#: Real engine messages the level data uses that reach neither the port's own
#: source nor messagesList.plist - the ones the curated list exists to name.
REAL_BUT_UNCITED = (
    'PGE_MESSAGE_ApplyProximityRadiusToPlayer',
    'PGE_MESSAGE_PresentAdiosVC',
    'PGE_MESSAGE_StartFullWheelRotation',
)


def test_known_messages_assembles_without_the_binary():
    vocab = audit.known_messages()
    assert isinstance(vocab, set)
    # No ps_strings.txt here: the vocabulary had to come from the fallback.
    assert not os.path.exists(os.path.join(ROOT, 'tools', 'ps_strings.txt'))
    for names in (REAL_BUT_UNCITED,):
        for m in names:
            assert m in vocab, m


def test_the_known_defects_are_still_unknown():
    vocab = audit.known_messages()
    for bad in NOT_MESSAGES:
        assert bad not in vocab, bad


def test_every_clean_message_the_data_uses_is_known_except_the_defects():
    from papasangre.assets.tiled import load_level                  # noqa: PLC0415
    exports = os.path.join(audit.BUNDLE, 'Exports', 'Papa Sangre')
    used: set[str] = set()
    for name in sorted(os.listdir(exports)):
        stem = os.path.splitext(name)[0]
        lv = load_level(os.path.join(exports, name), stem)
        for o in [lv.room] + lv.objects + ([lv.player] if lv.player else []):
            if o is None:
                continue
            for t in o.triggers:
                if t.notification_name.startswith('PGE_MESSAGE_'):
                    used.add(t.notification_name)
    vocab = audit.known_messages()
    mismatches = (used - vocab) - set(NOT_MESSAGES)
    assert mismatches == set(), sorted(mismatches)


def test_unknown_message_count_is_exactly_the_eight_known_defects():
    """The frozen checker's headline count: 2+1+1+1+1+1+1 = 8."""
    from papasangre.assets.tiled import load_level                  # noqa: PLC0415
    exports = os.path.join(audit.BUNDLE, 'Exports', 'Papa Sangre')
    vocab = audit.known_messages()
    unknown = 0
    for name in sorted(os.listdir(exports)):
        stem = os.path.splitext(name)[0]
        lv = load_level(os.path.join(exports, name), stem)
        for o in [lv.room] + lv.objects + ([lv.player] if lv.player else []):
            if o is None:
                continue
            for t in o.triggers:
                if t.notification_name not in vocab:
                    unknown += 1
    assert unknown == 8, unknown


def test_hrtf_build_step_resolves_on_this_machine():
    import tools.build_exes as be                                    # noqa: PLC0415
    assert be.prepare_hrtf() == be.HRTF
    assert os.path.exists(be.HRTF), be.HRTF


def test_makemhr_points_at_the_platform_binary():
    import tools.build_exes as be                                    # noqa: PLC0415
    if sys.platform == 'darwin':
        assert be.makemhr_binary().endswith('makemhr-mac/makemhr')
        assert os.path.exists(be.makemhr_binary())
    elif sys.platform == 'win32':
        assert be.makemhr_binary().endswith('makemhr.exe')
    elif sys.platform.startswith('linux'):
        import shutil
        assert be.makemhr_binary() == shutil.which('makemhr')


if __name__ == '__main__':
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f'  PASS  {fn.__name__}')
        except Exception as e:                                       # noqa: BLE001
            failed += 1
            print(f'  FAIL  {fn.__name__}: {e}')
    print(f'\n{len(fns) - failed}/{len(fns)} passed')
    raise SystemExit(1 if failed else 0)
