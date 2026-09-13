"""Cross-validate the recovered Papa Sangre data set.

Used by ``apps/check_content.py`` and ``tools/audit.py``.

Loads every level export and every playlist from the untouched reference bundle
and checks that the port has an account of *all* content:

  * every object type and property is one the engine knows about
  * every message name used by a trigger exists in the engine's vocabulary
  * every sound name referenced by an object resolves to a real audio file
  * every ``LoadLevelWithName`` target level exists
  * every ``ActivateAgentWithName``/``DeactivateAgentWithName``/
    ``FollowPathWithName``/``AlertEnemyWithName`` target exists in that level
  * every footstep prefix has matching footstep assets

Writes ``docs/CONTENT_INVENTORY.md`` (the porting checklist) and prints a
summary.  Run:  ``python tools/audit.py``
"""

from __future__ import annotations

import collections
import glob
import json
import os
import plistlib
import re
import sys

from ..util import paths
from .tiled import load_level, LevelData, Trigger
from .sexp import parse_playlist, include_stem


def _data_root() -> str:
    """Where the reference data lives: bundled inside a build, or in reference/."""
    for c in (paths.resource('gamedata'),
              paths.resource('reference', 'Payload', 'Papa Sangre.app')):
        if os.path.isdir(os.path.join(c, 'Exports')):
            return c
    return paths.resource('reference', 'Payload', 'Papa Sangre.app')


BUNDLE = _data_root()
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
META = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')
DOCS = os.path.join(paths.writable_root(), 'docs')

LEVEL_ORDER = [f'ps1_{i}' for i in range(1, 26)]


# --------------------------------------------------------------------------
# engine vocabulary
# --------------------------------------------------------------------------
def known_messages() -> set[str]:
    """Message names the engine listens for (from the binary's string table)."""
    for path in (os.path.join(BUNDLE, 'ps_strings.txt'),
                 paths.resource('tools', 'ps_strings.txt')):
        if os.path.exists(path):
            text = open(path, encoding='utf-8', errors='replace').read()
            return set(re.findall(r'PGE_MESSAGE_[A-Za-z]+', text))
    raise FileNotFoundError('ps_strings.txt (the engine message vocabulary)')


def message_params() -> dict[str, set[str]]:
    with open(os.path.join(BUNDLE, 'messagesList.plist'), 'rb') as fh:
        d = plistlib.load(fh)
    return {k: set(v.get('parameters', [])) for k, v in d.items()}


def object_params() -> dict[str, set[str]]:
    with open(os.path.join(BUNDLE, 'objectsList.plist'), 'rb') as fh:
        d = plistlib.load(fh)
    return {k: set(v.get('parameters', [])) for k, v in d.items()}


def hub_list() -> dict:
    with open(os.path.join(BUNDLE, 'Exports', 'Papa Sangre_hubList.plist'), 'rb') as fh:
        return plistlib.load(fh)


#: Properties handled by the generic ``set<Key>:`` applicator, gathered from the
#: class dump (ivar/property names of PGE* classes) plus objectsList.plist.
SETTABLE = {
    # PGEGameAgent / PGEObjectWithTriggers
    'name', 'active', 'soundList', 'collideRadius', 'chasingRadius', 'shootRange',
    'speed', 'chaseSpeed', 'playlistName',
    # PGESound
    'looping', 'spatialized', 'skippable', 'gain', 'onXrail', 'onYrail',
    # PGECollectible
    'introSound', 'collectSound', 'loopSound', 'nextCollectible',
    # PGEEnemy
    'walkingSpeed', 'distractedTime', 'walkingPauseSound', 'awareSound',
    'defaultSound', 'chaseSound', 'notThereSound', 'attackSound',
    # PGEBeatable
    'onRangeSound',
    # PGEDilemma
    'restSound', 'alertSound', 'thanksSound', 'abandonSound', 'dilemmaID',
    'bpmMalus', 'alertDistance', 'collected',
    # PGESurface / PGELevel / PGERoom
    'footstepsPrefix', 'surfaceId', 'z', 'tripBPM', 'runBPM', 'tripSound',
    'shuffleSound', 'multipleOnEnter', 'inactivitySounds', 'inactivityTime',
    'isInfinite', 'hitWallSound', 'levelImage', 'buttonLabel',
    # PGEPlayer
    'pixelsPerStep', 'startAngle', 'shootSound', 'tripTimePenality',
    # PGENPC
    'hailSounds', 'briefingSound', 'levelName', 'hailInterval',
}

#: Property keys that appear in the shipped data but that no setter accepts.
#: The original engine logs these through PSObjectsChecker and ignores them.
KNOWN_DATA_TYPOS = {'foostepsPrefix'}   # ps1_1b Room; no setter matches, silently ignored


# --------------------------------------------------------------------------
# audio index
# --------------------------------------------------------------------------
def _scan_audio(bundle: str) -> dict[str, str]:
    idx: dict[str, str] = {}
    for ext in ('m4a', 'wav'):
        for p in glob.glob(os.path.join(bundle, '**', f'*.{ext}'), recursive=True):
            rel = os.path.relpath(p, bundle).replace('\\', '/')
            idx.setdefault(os.path.splitext(os.path.basename(p))[0], rel)
    return idx


def audio_index() -> dict[str, str]:
    """Map bare sound name -> bundle-relative path, for every shipped audio file.

    A frozen build carries a pre-computed index because the 96 MB audio tree is
    not shipped with the content checker - only the names matter here.
    """
    cached = os.path.join(BUNDLE, 'audio_index.json')
    if os.path.exists(cached):
        with open(cached, encoding='utf-8') as fh:
            return json.load(fh)
    return _scan_audio(BUNDLE)


def write_audio_index(bundle: str, dest: str) -> int:
    """Build the cached index from a real bundle (used by the exe builder)."""
    idx = _scan_audio(bundle)
    with open(dest, 'w', encoding='utf-8') as fh:
        json.dump(idx, fh, indent=0, sort_keys=True)
    return len(idx)


def playlists() -> dict[str, object]:
    out = {}
    for fp in glob.glob(os.path.join(META, '*.sexp')):
        base = os.path.basename(fp)
        stem = base.split('.S3DPlayListModel')[0]
        out[stem] = parse_playlist(open(fp, encoding='utf-8', errors='replace').read(), base)
    return out


def playlist_sounds(pls: dict, stem: str, seen=None) -> dict[str, object]:
    """Flatten a playlist and everything it includes."""
    seen = seen if seen is not None else set()
    if stem in seen or stem not in pls:
        return {}
    seen.add(stem)
    pl = pls[stem]
    out = {s.name: s for s in pl.sounds}
    for inc in pl.includes:
        out.update(playlist_sounds(pls, include_stem(inc), seen))
    return out


# --------------------------------------------------------------------------
# sound references inside object properties
# --------------------------------------------------------------------------
SOUND_PROPS = ('soundList', 'introSound', 'collectSound', 'loopSound',
               'tripSound', 'shuffleSound', 'inactivitySounds', 'awareSound',
               'defaultSound', 'chaseSound', 'notThereSound', 'attackSound',
               'walkingPauseSound', 'restSound', 'alertSound', 'thanksSound',
               'abandonSound', 'onRangeSound', 'briefingSound', 'hailSounds',
               'shootSound', 'hitWallSound', 'proximitySound')


def referenced_sounds(obj) -> list[str]:
    names: list[str] = []
    for key in SOUND_PROPS:
        v = obj.properties.get(key)
        if not v:
            continue
        names.extend(n for n in str(v).split('&') if n)
    for t in obj.triggers:
        for k in ('soundName',):
            if k in t.parameters:
                names.extend(n for n in t.parameters[k].split('&') if n)
    return names


def run(emit=print) -> dict:
    msgs = known_messages()
    msg_params = message_params()
    hub = hub_list()
    audio = audio_index()
    pls = playlists()

    levels: dict[str, LevelData] = {}
    for fp in sorted(glob.glob(os.path.join(EXPORTS, '*.json'))):
        stem = os.path.splitext(os.path.basename(fp))[0]
        levels[stem] = load_level(fp, stem)

    problems: list[str] = []
    stats = collections.Counter()
    unknown_props = collections.Counter()
    unknown_msgs = collections.Counter()
    missing_sounds = collections.Counter()
    not_in_playlist = collections.Counter()
    missing_targets: list[str] = []
    malformed: list[str] = []
    footstep_prefixes = collections.Counter()

    for name, lv in sorted(levels.items()):
        pl_sounds = playlist_sounds(pls, name)
        all_names = {o.name for o in lv.objects if o.name}
        path_names = {o.name for o in lv.objects if o.type == 'Path'}

        for o in [lv.room] + lv.objects + ([lv.player] if lv.player else []):
            if o is None:
                continue
            stats[o.type] += 1
            for k in o.settable:
                if k not in SETTABLE and k not in KNOWN_DATA_TYPOS:
                    unknown_props[f'{o.type}.{k}'] += 1
            if 'footstepsPrefix' in o.properties:
                footstep_prefixes[o.properties['footstepsPrefix']] += 1

            for snd in referenced_sounds(o):
                if snd not in pl_sounds and snd not in audio:
                    missing_sounds[f'{name}:{snd}'] += 1
                elif snd not in pl_sounds:
                    # The file exists but the level's own playlist never
                    # declares it, so the engine's lookup returns nothing and
                    # the sound is silent in play.  FINAL_ITD_inactive_all in
                    # level 1 is one of these.
                    not_in_playlist[f'{name}:{snd}'] += 1

            for t in o.triggers:
                stats['trigger'] += 1
                if t.malformed:
                    malformed.append(f'{name}/{o.type}[{o.name}].{t.trigger_type}: {t.raw}')
                if t.notification_name not in msgs:
                    unknown_msgs[f'{name}: {t.notification_name}'] += 1
                    continue
                short = t.notification_name[len('PGE_MESSAGE_'):]
                # reference integrity
                tgt = t.parameters.get('name')
                if short in ('ActivateAgentWithName', 'DeactivateAgentWithName',
                             'ChangeSoundListOnAgentWithName',
                             'PlaySpatialSoundOnAgentWithName',
                             'AlertEnemyWithName', 'ActivateNPCWithName',
                             'ActivateSummonerWithName', 'MovePlayerToPositionWithName',
                             'MoveObjectToPositionWithName'):
                    ref = t.parameters.get('agentName', tgt)
                    if ref and ref not in all_names:
                        missing_targets.append(
                            f'{name}/{o.type}[{o.name}].{t.trigger_type} -> {short}: '
                            f'no agent named {ref!r}')
                if short in ('FollowPathWithName', 'StopFollowPathWithName') and tgt:
                    if tgt not in path_names:
                        missing_targets.append(
                            f'{name}/{o.type}[{o.name}] -> {short}: no path {tgt!r}')
                if short == 'LoadLevelWithName' and tgt and tgt not in levels:
                    missing_targets.append(
                        f'{name}/{o.type}[{o.name}] -> LoadLevelWithName: '
                        f'missing level {tgt!r}')
                # parameter names
                expected = msg_params.get(t.notification_name)
                if expected is not None:
                    for k in t.parameters:
                        if k not in expected and k not in ('senderName', 'position'):
                            unknown_props[f'msgparam {short}.{k}'] += 1

    # ---- playlist declarations must resolve to shipped files --------------
    unresolved_decls = []
    empty_decls = []
    for stem, pl in sorted(pls.items()):
        for s in pl.sounds:
            if not s.name:
                empty_decls.append(f'{stem}: empty name in {s.path}')
                continue
            if not s.path.startswith('ps1'):
                continue          # PS2 / Nightjar assets are not shipped
            if s.name not in audio:
                unresolved_decls.append(f'{stem}: {s.bundle_path}')

    # ---- footstep bank coverage, through the playlists --------------------
    # moveForwardOneStep: builds "<prefix>_<speed>_<foot>" and falls back to
    # "<prefix>_s"; every level that names a prefix must have those banks in
    # its own (flattened) playlist, or footsteps go silent.
    footstep_missing = []
    footstep_incomplete = []
    for lname, lv in sorted(levels.items()):
        pl_sounds = playlist_sounds(pls, lname)
        prefixes = {o.properties['footstepsPrefix']
                    for o in ([lv.room] + lv.objects)
                    if o is not None and o.properties.get('footstepsPrefix')}
        for prefix in prefixes:
            for speed in ('s1', 's3'):
                for foot in ('L', 'R'):
                    key = f'{prefix}_{speed}_{foot}'
                    direct = [n for n in pl_sounds if n.startswith(key)]
                    fallback = [n for n in pl_sounds if n.startswith(prefix + '_s')]
                    if not direct and not fallback:
                        footstep_missing.append(f'{lname}: {key}')
                    elif not direct:
                        footstep_incomplete.append(f'{lname}: {key} (fallback only)')

    # ---------------- report ----------------
    emit('=' * 72)
    emit('PAPA SANGRE CONTENT AUDIT')
    emit('=' * 72)
    emit(f'levels parsed            : {len(levels)}')
    emit(f'objects by type          : {dict(sorted(stats.items()))}')
    emit(f'distinct footstep prefixes: {len(footstep_prefixes)}')
    emit()
    emit(f'unknown object properties : {sum(unknown_props.values())}')
    for k, v in unknown_props.most_common(20):
        emit(f'    {v:4d}  {k}')
    emit(f'unknown message names     : {sum(unknown_msgs.values())}')
    for k, v in unknown_msgs.most_common(20):
        emit(f'    {v:4d}  {k}')
    emit(f'unresolved sound refs     : {sum(missing_sounds.values())}')
    for k, v in missing_sounds.most_common(20):
        emit(f'    {v:4d}  {k}')
    emit(f'referenced but not in the level playlist (silent in play): '
         f'{sum(not_in_playlist.values())}')
    for k, v in not_in_playlist.most_common(12):
        emit(f'    {v:4d}  {k}')
    emit(f'dangling name references  : {len(missing_targets)}')
    for k in missing_targets[:25]:
        emit(f'    {k}')
    emit(f'malformed trigger stmts   : {len(malformed)}')
    for k in malformed[:15]:
        emit(f'    {k}')
    emit(f'playlist declarations not shipped: {len(unresolved_decls)}')
    for k in unresolved_decls[:15]:
        emit(f'    {k}')
    emit(f'empty playlist declarations: {len(empty_decls)}   {empty_decls}')
    emit(f'footstep banks missing entirely : {len(footstep_missing)}')
    for k in footstep_missing[:20]:
        emit(f'    {k}')
    emit(f'footstep banks on fallback only : {len(footstep_incomplete)}')
    for k in footstep_incomplete[:20]:
        emit(f'    {k}')

    # ---------------- checklist ----------------
    os.makedirs(DOCS, exist_ok=True)
    out = [
        '# Papa Sangre — content inventory and porting checklist',
        '',
        'Generated by `tools/audit.py` from the untouched reference bundle.',
        'Every row is content that must exist in the Windows port.',
        'Status legend: `[ ]` not started · `[~]` in progress · `[x]` ported and verified.',
        '',
    ]
    for stem in LEVEL_ORDER + ['ps1_1b', 'reckoner']:
        if stem not in levels:
            continue
        lv = levels[stem]
        meta = next((v for v in hub.values() if v.get('fileName') == stem), None)
        title = meta['altName'] if meta else '(not in hub list)'
        counts = collections.Counter(o.type for o in lv.objects)
        out.append(f'## {stem} — {title}')
        out.append('')
        out.append(f'- world rect: `{lv.rect[2]:.0f} x {lv.rect[3]:.0f}` px, '
                   f'origin at room centre (Tiled offset '
                   f'{lv.mid_room_on_tiled[0]:.0f},{lv.mid_room_on_tiled[1]:.0f})')
        if lv.player:
            out.append(f'- player start: `({lv.player.x:.0f}, {lv.player.y:.0f})` '
                       f'startAngle `{lv.player.properties.get("startAngle","-")}` '
                       f'pixelsPerStep `{lv.player.properties.get("pixelsPerStep","-")}`')
        out.append(f'- objects: ' + ', '.join(f'{k} x{v}' for k, v in sorted(counts.items())))
        out.append('')
        out.append('| status | type | name | pos | triggers |')
        out.append('|---|---|---|---|---|')
        out.append(f'| [ ] | Room | (level) | {lv.rect[2]:.0f}x{lv.rect[3]:.0f} | '
                   f'{len(lv.room.triggers) if lv.room else 0} |')
        for o in lv.objects:
            trg = ', '.join(sorted({t.trigger_type for t in o.triggers})) or '-'
            out.append(f'| [ ] | {o.type} | `{o.name or "(unnamed)"}` | '
                       f'{o.x:.0f},{o.y:.0f} | {trg} |')
        out.append('')

    with open(os.path.join(DOCS, 'CONTENT_INVENTORY.md'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out))
    emit()
    emit(f'wrote {os.path.join(DOCS, "CONTENT_INVENTORY.md")}')
    return {
        'levels': len(levels),
        'objects': dict(stats),
        'unknown_props': sum(unknown_props.values()),
        'unknown_messages': sum(unknown_msgs.values()),
        'unresolved_sounds': sum(missing_sounds.values()),
        'not_in_playlist': sum(not_in_playlist.values()),
        'dangling_names': len(missing_targets),
        'malformed_triggers': len(malformed),
        'unresolved_declarations': len(unresolved_decls),
        'empty_declarations': len(empty_decls),
        'footstep_banks_missing': len(footstep_missing),
        'footstep_banks_fallback_only': len(footstep_incomplete),
        'inventory_path': os.path.join(DOCS, 'CONTENT_INVENTORY.md'),
    }
