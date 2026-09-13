"""Regression tests for the data importers (Phase A).

Every expectation here is a fact read out of the original bundle or the
disassembled engine, so a failure means the port has drifted from the original.
Run with:  python -m pytest tests -q     (or: python tests/test_dataimport.py)
"""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.assets.sexp import parse_playlist, include_stem      # noqa: E402
from papasangre.assets.tiled import (                                # noqa: E402
    load_level, parse_trigger_statement, message_name, parse_triggers)

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
META = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')


# ---------------------------------------------------------------- messages
def test_message_name_normalisation():
    # -[PGEObjectWithTriggers messageNameFromString:]
    assert message_name('PlaySound') == 'PGE_MESSAGE_PlaySound'
    assert message_name('PGE_MESSAGE_PlaySound') == 'PGE_MESSAGE_PlaySound'


def test_trigger_statement_with_parameters():
    t = parse_trigger_statement(
        'OnCollide',
        'PGE_MESSAGE_ActivateAgentWithName:name=door_castle_living;afterDelay=1')
    assert t.notification_name == 'PGE_MESSAGE_ActivateAgentWithName'
    assert t.parameters == {'name': 'door_castle_living'}
    assert t.after_delay == 1.0
    assert not t.malformed


def test_trigger_statement_without_parameters():
    t = parse_trigger_statement('OnCollide', 'ShutDownLevel')
    assert t.notification_name == 'PGE_MESSAGE_ShutDownLevel'
    assert t.parameters == {}
    assert t.after_delay == 0.0


def test_trigger_count_and_aftercount_are_consumed_by_the_trigger():
    t = parse_trigger_statement('OnStep', 'PlaySound:soundName=x;count=3;afterCount=2')
    assert t.count == 3
    assert t.after_count == 2
    assert t.parameters == {'soundName': 'x'}      # count/afterCount are not params


def test_original_defect_missing_equals_drops_the_pair():
    # ps1_19: "DeactivateAgentWithName:chicken_2;afterDelay=20"
    t = parse_trigger_statement('OnActivate',
                                'DeactivateAgentWithName:chicken_2;afterDelay=20')
    assert t.malformed
    assert t.parameters == {}          # no 'name' -> the message hits nothing
    assert t.after_delay == 20.0


def test_original_defect_second_colon_swallows_the_whole_statement():
    # ps1_19: "ActivateAgentWithName:name=chicken_launcher_3:afterDelay=20"
    t = parse_trigger_statement(
        'OnActivate', 'ActivateAgentWithName:name=chicken_launcher_3:afterDelay=20')
    assert t.malformed
    assert t.notification_name == (
        'PGE_MESSAGE_ActivateAgentWithName:name=chicken_launcher_3:afterDelay=20')
    assert t.parameters == {}


def test_pipe_splits_statements():
    props = {'OnCollide': 'A|B:x=1|C'}
    ts = parse_triggers('Sound', props)
    assert [t.notification_name for t in ts] == [
        'PGE_MESSAGE_A', 'PGE_MESSAGE_B', 'PGE_MESSAGE_C']


# ---------------------------------------------------------------- playlists
def test_every_playlist_parses():
    files = sorted(glob.glob(os.path.join(META, '*.sexp')))
    assert len(files) == 104
    for fp in files:
        parse_playlist(open(fp, encoding='utf-8', errors='replace').read(),
                       os.path.basename(fp))


def test_level_one_playlist_contents():
    fp = os.path.join(META, 'ps1_1.S3DPlayListModel#0.sexp')
    pl = parse_playlist(open(fp, encoding='utf-8').read())
    assert pl.name == 'ps1_1'
    by = pl.by_name()
    assert by['FINAL_ITD_Intro'].path == 'ps1/cutscenes'
    assert by['FINAL_ITD_Intro'].preload is True
    assert by['FINAL_ITD_Intro'].spatialized is False
    assert by['door_castle_living'].spatialized is True
    assert by['door_castle_living'].bundle_path == 'ps1/spatialized/door_castle_living.m4a'
    assert include_stem(pl.includes[0]) == '_footsteps_stone'


def test_playlist_sound_files_exist():
    fp = os.path.join(META, 'ps1_1.S3DPlayListModel#0.sexp')
    pl = parse_playlist(open(fp, encoding='utf-8').read())
    for s in pl.sounds:
        assert os.path.exists(os.path.join(BUNDLE, s.bundle_path)), s.bundle_path


def test_one_sound_form_may_hold_many_bundles():
    """The footstep banks put every variant inside a single (sound ...) form.

    Reading only the first bundle silently drops most of the game's footsteps,
    so this is pinned.
    """
    fp = os.path.join(META, '_footsteps_stone.S3DPlayListModel#0.sexp')
    pl = parse_playlist(open(fp, encoding='utf-8').read())
    names = sorted(s.name for s in pl.sounds)
    assert names == [
        'foot_stone_s1_L_a', 'foot_stone_s1_L_b', 'foot_stone_s1_L_c',
        'foot_stone_s1_R_a', 'foot_stone_s1_R_b', 'foot_stone_s1_R_c',
        'foot_stone_s3_L_a', 'foot_stone_s3_L_b', 'foot_stone_s3_L_c',
        'foot_stone_s3_R_a', 'foot_stone_s3_R_b', 'foot_stone_s3_R_c',
        'foot_stone_shuffle', 'foot_stone_trip',
    ]
    # flags on the (sound ...) form apply to every bundle inside it
    assert all(s.preload for s in pl.sounds)


def test_every_playlist_declaration_resolves_to_a_shipped_file():
    for fp in sorted(glob.glob(os.path.join(META, '*.sexp'))):
        pl = parse_playlist(open(fp, encoding='utf-8', errors='replace').read(),
                            os.path.basename(fp))
        for s in pl.sounds:
            if not s.name:
                continue          # 4 empty declarations in the original data
            if not s.path.startswith('ps1'):
                continue          # Papa Sangre II / Nightjar assets do not ship
            assert os.path.exists(os.path.join(BUNDLE, s.bundle_path)), \
                f'{os.path.basename(fp)}: {s.bundle_path}'


# ---------------------------------------------------------------- levels
def test_every_level_loads():
    files = sorted(glob.glob(os.path.join(EXPORTS, '*.json')))
    assert len(files) == 27
    for fp in files:
        lv = load_level(fp)
        assert lv.room is not None
        assert lv.player is not None, lv.name


def test_toolbar_layer_is_excluded():
    lv = load_level(os.path.join(EXPORTS, 'ps1_1.json'))
    assert 'ToolBar' in lv.skipped_layers
    # The palette holds an NPC and a Monster; neither belongs to the level.
    assert not lv.of_type('NPC')
    assert not lv.of_type('Monster')


def test_level_one_geometry():
    lv = load_level(os.path.join(EXPORTS, 'ps1_1.json'))
    # Room: x=88 y=-187 w=87 h=468
    assert lv.rect == (-43.5, -234.0, 87.0, 468.0)
    assert lv.mid_room_on_tiled == (131.5, 47.0)
    # Player point object at Tiled (121, 250); world Y is negated
    assert lv.player.x == 121 - 131.5
    assert lv.player.y == -(250 - 47.0)
    assert lv.player.properties['pixelsPerStep'] == '5'
    assert lv.player.properties['startAngle'] == '90'


def test_level_one_object_census():
    lv = load_level(os.path.join(EXPORTS, 'ps1_1.json'))
    kinds = sorted(o.type for o in lv.objects)
    assert kinds == ['Collectible', 'Sound', 'Sound', 'Sound', 'Sound', 'Sound', 'Sound']
    names = {o.name for o in lv.objects}
    assert names == {'FINAL_ITD_Intro', 'Atmos_darkrumble_01', 'trigger1',
                     'trigger2', 'trigger3', 'FINAL_ITD_inactive_all',
                     'door_castle_living'}


def test_level_one_exit_collectible():
    lv = load_level(os.path.join(EXPORTS, 'ps1_1.json'))
    door = lv.by_name('door_castle_living')
    assert door.type == 'Collectible'
    assert door.properties['collectSound'] == 'FINAL_ITD_Win'
    types = {t.trigger_type: t.notification_name for t in door.triggers}
    assert types['OnCollide'] == 'PGE_MESSAGE_ShutDownLevel'
    assert types['OnSoundEnd'] == 'PGE_MESSAGE_LoadLevelWithName'
    end = next(t for t in door.triggers if t.trigger_type == 'OnSoundEnd')
    assert end.parameters == {'name': 'ps1_1b'}


def test_world_y_is_negated_so_the_level_runs_the_right_way():
    """Level 1's three notes and its exit must lie *ahead* of the player.

    startAngle 90 gives an orientation of (0, +1), so every objective has to be
    at greater world Y than the start.  Miss the fneg in the engine's position
    maths and the player faces the back wall instead.
    """
    lv = load_level(os.path.join(EXPORTS, 'ps1_1.json'))
    start_y = lv.player.y
    order = ['trigger1', 'trigger2', 'trigger3', 'door_castle_living']
    ys = [lv.by_name(n).y for n in order]
    assert all(y > start_y for y in ys), (start_y, ys)
    assert ys == sorted(ys), 'objectives must be met in order along the corridor'


def test_surface_rectangles_are_flipped_with_the_world():
    """A Surface's rect keeps its extent; only the origin moves."""
    for stem in ('ps1_2', 'ps1_3', 'ps1_4'):
        lv = load_level(os.path.join(EXPORTS, stem + '.json'))
        for s in lv.of_type('Surface'):
            assert s.rect is not None
            rx, ry, rw, rh = s.rect
            assert rw == s.width and rh == s.height
            # the object's stored position is the centre of that rect
            assert abs((rx + rw / 2) - s.x) < 1e-9
            assert abs((ry + rh / 2) - s.y) < 1e-9


def test_wall_containment_matches_cgrectcontainspoint():
    lv = load_level(os.path.join(EXPORTS, 'ps1_1.json'))
    assert lv.contains(0.0, 0.0)
    assert lv.contains(-43.5, -234.0)          # inclusive at the origin corner
    assert not lv.contains(43.5, 0.0)          # exclusive at the far edge
    assert not lv.contains(-43.6, 0.0)


def test_paths_are_polylines_in_world_space():
    found = 0
    for fp in sorted(glob.glob(os.path.join(EXPORTS, '*.json'))):
        lv = load_level(fp)
        for p in lv.of_type('Path'):
            found += 1
            assert len(p.polyline) >= 2, (lv.name, p.name)
    assert found == 6


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
