"""Method-by-method coverage of the port against the original's classes.

The mechanism that was missing when the walking rule turned out to be wrong: a
mechanical list of every method the original defines on the classes the port
claims to implement, and whether the port implements it.

Property accessors are excluded - they are storage, not behaviour.  Everything
else is either matched to a Python method (by snake_case name or an explicit
alias) or reported MISSING.

A match here means only that *something with that name exists*.  It is a list of
places to go and read, not a claim that the logic agrees; that judgement lives in
DIVERGENCES.md.

    python tools/coverage.py            # summary + gaps
    python tools/coverage.py -v         # list every method
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP = os.path.join(ROOT, 'tools', 'classdump.txt')

#: ObjC class -> the port module that stands in for it.
PORTED = {
    'PGEMoveInterpretor': 'papasangre/input/interpreter.py',
    'PGEPlayer':          'papasangre/entities/player.py',
    'PGEObjectWithTriggers': 'papasangre/core/triggers.py',
    'PGEGameAgent':       'papasangre/entities/agent.py',
    'PGEEnemy':           'papasangre/entities/monster.py',
    'PGEForgetfulMan':    'papasangre/entities/monster.py',
    'PGECollectible':     'papasangre/entities/collectible.py',
    'PGESound':           'papasangre/entities/sound_agent.py',
    'PGESurface':         'papasangre/world/surface.py',
    'PGEActionSurface':   'papasangre/world/surface.py',
    'PGELevel':           'papasangre/world/level.py',
    'PGEGameProgress':    'papasangre/save/progress.py',
}

#: Selectors whose port method is named differently.  Kept explicit so that a
#: rename cannot silently turn a real gap into a false match.
ALIASES = {
    'footButtonPressed:': 'foot_pressed',
    'footButtonReleased:': 'foot_released',
    'rotatePlayerFromAngle:': 'rotate_by',
    'rotatePlayerToFixedRotation:': 'rotate_to_fixed_rotation',
    'anySoundWihPrefix:': 'any_sound_with_prefix',
    'shutDownLevel:': '_on_shut_down',
    'alertEnemy:': 'alert',
    'playSound:looping:': 'play_sound',
    'S3DSound:': 'sound',
    'getStateDictionnary': 'get_state_dictionary',
    # verified equivalents - the port names its message handlers after the
    # message, not after the ObjC selector
    'playerMovedToPosition:': '_on_player_moved',
    'playerDidRotate:': '_on_player_rotated',
    'activateAgentWithName:': '_on_activate_named',
    'deactivateAgentWithName:': '_on_deactivate_named',
    'changeSoundListOnAgentWithName:': '_on_change_sound_list',
    'playSpatialSoundOnAgentWithName:': '_on_play_spatial_named',
    'moveAgentToPosition:': '_on_move_named',
    'levelInited:': '_on_level_inited',
    'levelInitedMessageReceived:': 'level',
    'deactivateWithNoCallback': 'deactivate_no_callback',
    'triggerOnCollide': 'collides_with_player',
    'applyProximityRadius:': '_on_proximity',
    'setPlaylistName:': 'playlist',
    'setSoundsFromString:': 'sound_list',
    'setAgentId:name:playlistName:delegate:': 'name',
    'popAtPosition:': 'position',
    'changeInactivityTime:': '_on_change_inactivity_time',
    'changeInactivitySoundList:': '_on_change_inactivity_list',
    'playerDidCollideAWall:': '_on_wall',
    'clearLevelData': 'shutdown',
    'loadDataFromJsonFile:previousLevel:': 'load',
    'actuallyLoadDataFromJsonFile': 'load',
    'loadLevelStructure:': 'apply_room',
    'loadLevelAgents:': 'load',
    'loadPlayer:': 'load',
    'createObjectFromDict:': 'load',
    'parseTriggersForNames:propertiesDict:receiver:': 'add_triggers',
    'createDictFromTriggerDescription:': 'add_triggers',
    'playerDidCompleteLevel:': 'player_did_complete_level',
    'isLevelCompleted:': 'is_level_completed',
    'playerDidUnlockLevel:': 'player_did_unlock_level',
    'isLevelUnlocked:': 'is_level_unlocked',
    'lastUnlockedLevel': 'last_unlocked_level',
    'saveDilemmaStatus:forId:': 'save_dilemma_status',
    'getDilemmaStatus:': 'get_dilemma_status',
    'saveLastPlaylist:': 'save_last_playlist',
    'getLastPlaylist': 'get_last_playlist',
    'saveSkippableSound:': 'save_skippable_sound',
    'canSkipSound:': 'can_skip_sound',
    'playerStateDidChange:': '_state_changed',
    'triggerWithType:': 'trigger',
    'solveDillemas': 'solve_dilemmas',
    'followPathWithName:': '_on_follow_path',
    'stopFollowingPath:': '_on_stop_following_path',
}

#: Selectors the port implements, but in a different module from the one this
#: class maps to - inherited behaviour, or shared machinery.  Each names the
#: module that actually has it, so "implemented" still has to be earned.
ELSEWHERE = {
    'messageNameFromString:': ('papasangre/assets/tiled.py', 'message_name'),
    'startTriggerAfterDelay:': ('papasangre/core/messages.py', 'post_after'),
    'parseTriggersForNames:propertiesDict:receiver:':
        ('papasangre/assets/tiled.py', 'parse_trigger_statement'),
    'createDictFromTriggerDescription:':
        ('papasangre/assets/tiled.py', 'parse_trigger_statement'),
    'setAgentId:name:playlistName:delegate:':
        ('papasangre/entities/agent.py', '__init__'),
    # PGEEnemy inherits these from PGEGameAgent, and so does the port's Monster
    'deactivate': ('papasangre/entities/agent.py', 'deactivate'),
    'findDirectionTo:': ('papasangre/entities/agent.py', 'find_direction_to'),
}

#: Methods that exist only to serve iOS plumbing the port has no equivalent for
#: (nibs, views, touch handling, Flurry, the on-screen debug map).  Listed one
#: by one rather than pattern-matched, so nothing hides behind a wildcard.
NOT_APPLICABLE = {
    '.cxx_destruct', 'dealloc', 'init', 'initWithNibName:bundle:',
    'viewDidLoad', 'viewDidUnload', 'shouldAutorotateToInterfaceOrientation:',
    'description', 'copyWithZone:', 'encodeWithCoder:', 'initWithCoder:',
    # resolved as N/A during the audit; the evidence is in DIVERGENCES.md §3
    'sendDidMoveMessage',            # PGE_MESSAGE_AgentDidMove: no observers
    'sendActivityChangedMessage',    # likewise
    'clearPlaylistPointer',          # ObjC memory bookkeeping
    'initSoundEngine', 'displayLevelImage', 'playlistIsLoaded',
    'deactivatePlaylist', 'didFinishAnnouncement:',
    'annoucementTimerNotIOS6', 'isThisTypeAnAgent:',
    'startAlarm:',                   # no level sends it
    'onDoubleTap', 'updateHandsView:', 'handButtonPressed:', 'handsClapped:',
    'playerDidShoot:', 'wasShot', 'wasMissed', 'triggerOnShoot',
    'triggerOnShootMissed',          # every OnShoot in the data is empty
    'startToJump', 'updateJump', 'landFromJump', 'swim:', 'startToSwim',
    'shoot:', 'beat:',               # no level enables jump, swim or hands
    'triggerOnExitJumping', 'triggerOnExitNotJumping',
    'initWithRectangle:surfaceId:z:', 'triggerOnButtonPressed',
    'updateWhiteNoise',              # PGEForgetfulMan is never used
    'activate',                      # PGEForgetfulMan's override; type unused
    'activateEnemy:',                # no level sends its message
}

_SEL = re.compile(r'^\s+([-+])\s(\S+)\s')
_PROP = re.compile(r'^\s+prop\s+(\S+)\s')
_IVAR = re.compile(r'^\s+ivar\s+(\S+)\s')

_LOWER_UPPER = re.compile(r'([a-z0-9])([A-Z])')
_ACRONYM = re.compile(r'([A-Z]+)([A-Z][a-z])')
_NON_ALNUM = re.compile(r'[^a-z0-9]')


def snake(sel: str) -> str:
    """camelCase -> snake_case, keeping acronym runs together (BPM, ID, S3D)."""
    base = sel.split(':')[0]
    base = _ACRONYM.sub(lambda m: m.group(1) + '_' + m.group(2), base)
    base = _LOWER_UPPER.sub(lambda m: m.group(1) + '_' + m.group(2), base)
    return base.lower().strip('_')


def flat(name: str) -> str:
    """Underscore- and case-insensitive form, for matching regardless of style."""
    return _NON_ALNUM.sub('', name.lower())


def parse_dump():
    classes = {}
    cur = None
    for line in open(DUMP, encoding='utf-8', errors='replace'):
        if line.startswith('@interface'):
            name = line.split()[1]
            cur = classes.setdefault(name, {'methods': [], 'props': set(),
                                            'ivars': set()})
            continue
        if line.startswith('@end'):
            cur = None
            continue
        if cur is None:
            continue
        m = _PROP.match(line)
        if m:
            cur['props'].add(m.group(1))
            continue
        m = _IVAR.match(line)
        if m:
            cur['ivars'].add(m.group(1).lstrip('_'))
            continue
        m = _SEL.match(line)
        if m and m.group(1) == '-':
            cur['methods'].append(m.group(2))
    return classes


def is_accessor(sel: str, props: set[str], ivars: set[str]) -> bool:
    """A getter or setter for a declared property or ivar carries no logic."""
    if sel.startswith('set') and sel.endswith(':') and sel.count(':') == 1:
        name = sel[3:-1]
        name = name[0].lower() + name[1:]
        return name in props or name in ivars
    return ':' not in sel and (sel in props or sel in ivars)


def port_names(path: str) -> set[str]:
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return set()
    text = open(full, encoding='utf-8').read()
    names = set(re.findall(r'^\s*def\s+(\w+)', text, re.M))
    # attributes count too: a one-line flag can stand in for a whole method
    names |= set(re.findall(r'^\s*self\.(\w+)\s*[:=]', text, re.M))
    return names


def main() -> int:
    verbose = '-v' in sys.argv
    classes = parse_dump()
    total = matched = 0
    gaps: list[tuple[str, str, str]] = []

    for cls, path in PORTED.items():
        info = classes.get(cls)
        if info is None:
            print(f'!! {cls}: not in the class dump')
            continue
        have = port_names(path)
        flat_have = {flat(h) for h in have}
        rows = []
        for sel in info['methods']:
            if sel in NOT_APPLICABLE or is_accessor(sel, info['props'],
                                                    info['ivars']):
                continue
            total += 1
            want = ALIASES.get(sel, snake(sel))
            ok = flat(want) in flat_have or flat(snake(sel)) in flat_have
            if not ok and sel in ELSEWHERE:
                mod, nm = ELSEWHERE[sel]
                ok = flat(nm) in {flat(h) for h in port_names(mod)}
                want = f'{nm} in {mod}'
            if ok:
                matched += 1
            else:
                gaps.append((cls, sel, want))
            rows.append(('ok  ' if ok else 'MISS', sel, want))
        if verbose and rows:
            print(f'\n--- {cls}  ({path})')
            for flag, sel, want in rows:
                print(f'  {flag}  {sel:<44} -> {want}')

    print(f'\n{matched}/{total} behaviour methods have a counterpart, '
          f'{len(gaps)} do not')
    if gaps:
        print('\nNo counterpart in the port:')
        for cls, sel, want in gaps:
            print(f'  {cls:<22} {sel:<44} (looked for {want})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
