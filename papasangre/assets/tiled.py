"""Importer for the original engine's Tiled level exports.

Every Papa Sangre level ships as a Tiled JSON map under
``Exports/Papa Sangre/<name>.json``.  This module reproduces
``-[PGELevel loadDataFromJsonFile:previousLevel:]`` and its helpers
(``loadLevelStructure:``, ``loadLevelAgents:``, ``loadPlayer:``,
``createObjectFromDict:``, ``parseTriggersForNames:propertiesDict:receiver:``
and ``createDictFromTriggerDescription:``) as recovered from the arm64 binary.

Recovered facts this module encodes
-----------------------------------
* Layers named ``ToolBar`` are the level editor's stencil palette and are
  skipped entirely (``loadLevelStructure``/``loadLevelAgents`` both test for it).
* Loading happens in three passes, in this order:
    1. ``Room`` objects only  -> defines the level rectangle and the origin.
    2. every agent/surface/path except ``Room`` and ``Player``.
    3. the ``Player``.
* The ``Room`` sets ``level.rectangle = CGRect(-w/2, -h/2, w, h)`` and
  ``midRoomOnTiled = (x + w/2, y + h/2)``.
* Every object position is ``tiled - midRoomOnTiled`` **with Y negated**.  The
  negation is easy to miss - it is a lone ``fneg`` after the subtraction at each
  of the five position sites - and without it the whole game is mirrored
  front-to-back: in level 1 the player would start facing the far wall and walk
  away from all three notes.
* Objects are placed at the centre of their Tiled box:
  ``(x + w/2, -(y + h/2 - mid.y))``.  Point objects have zero width and height,
  so this reduces to ``(x - mid.x, -(y - mid.y))``.
* A ``Surface`` also keeps a rectangle, built as
  ``origin = (x - mid.x, -(y - mid.y) - height)``, ``size = (width, height)`` -
  the flip moves the Tiled top edge to the world bottom edge.
* Property keys beginning with ``On`` are triggers.  Everything else is applied
  generically by building the selector ``set<Capitalised key>:`` and calling it
  if the object responds — reproduced here as a name-mapped attribute set.
* A trigger's value is a ``|``-separated list of statements.  Each statement is
  ``MessageName`` or ``MessageName:key=value;key=value``.  The keys ``count``,
  ``afterCount`` and ``afterDelay`` are consumed by the trigger itself; all
  other keys become message parameters.
* Message names are normalised by ``messageNameFromString:``: keep as-is when
  already prefixed ``PGE_MESSAGE_``, otherwise prepend it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

MESSAGE_PREFIX = 'PGE_MESSAGE_'

#: Object types that ``-[PGELevel isThisTypeAnAgent:]`` accepts.
AGENT_TYPES = {
    'Collectible', 'Monster', 'Summoner', 'Position', 'NPC', 'Sound',
    'Beatable', 'TagPlayer', 'Dilemma', 'ForgetfulMan',
}

#: Trigger property names accepted per object type, from ``createObjectFromDict:``.
_AGENT_TRIGGERS = ['OnActivate', 'OnDeactivate', 'OnEnteringShootRange',
                   'OnPathEnd', 'OnLoad']
TRIGGER_NAMES: dict[str, list[str]] = {
    'Collectible':    _AGENT_TRIGGERS + ['OnCollide', 'OnSoundEnd'],
    'Sound':          _AGENT_TRIGGERS + ['OnCollide', 'OnSoundEnd'],
    'Monster':        _AGENT_TRIGGERS + ['OnCollide', 'OnShoot', 'OnShootMissed'],
    'ForgetfulMan':   _AGENT_TRIGGERS + ['OnCollide', 'OnShoot', 'OnShootMissed'],
    'Dilemma':        _AGENT_TRIGGERS + ['OnCollide'],
    'NPC':            _AGENT_TRIGGERS + ['OnCollide'],
    'Summoner':       _AGENT_TRIGGERS + ['OnCollide'],
    'Beatable':       _AGENT_TRIGGERS + ['OnShoot'],
    'Position':       _AGENT_TRIGGERS,
    'TagPlayer':      _AGENT_TRIGGERS,
    'Player':         ['OnTrip', 'OnShootMissed'],
    'PlayerListener': ['OnStart', 'OnDeath', 'OnWallCollision', 'OnTrip',
                       'OnRun', 'OnStartToRun'],
    'Room':           ['OnEnter', 'OnStep', 'OnExit', 'OnExitNotJumping',
                       'OnExitJumping', 'OnButtonPressed'],
    'Surface':        ['OnEnter', 'OnStep', 'OnExit', 'OnExitNotJumping',
                       'OnExitJumping', 'OnButtonPressed'],
    'ActionSurface':  ['OnEnter', 'OnStep', 'OnExit', 'OnExitNotJumping',
                       'OnExitJumping', 'OnButtonPressed'],
    'Path':           [],
}


def message_name(raw: str) -> str:
    """``-[PGEObjectWithTriggers messageNameFromString:]``"""
    return raw if raw.startswith(MESSAGE_PREFIX) else MESSAGE_PREFIX + raw


@dataclass
class Trigger:
    """One parsed statement of a trigger property."""
    trigger_type: str                 # e.g. "OnCollide"
    notification_name: str            # normalised, e.g. "PGE_MESSAGE_PlaySound"
    parameters: dict[str, str] = field(default_factory=dict)
    count: int | None = None          # remaining allowed firings
    after_count: int | None = None    # fire only once this many hits have passed
    after_delay: float = 0.0
    raw: str = ''
    malformed: bool = False           # original data errors, kept for fidelity

    def clone(self) -> 'Trigger':
        return Trigger(self.trigger_type, self.notification_name,
                       dict(self.parameters), self.count, self.after_count,
                       self.after_delay, self.raw, self.malformed)


def parse_trigger_statement(trigger_type: str, statement: str) -> Trigger:
    """``-[PGELevel createDictFromTriggerDescription:]`` for one statement."""
    parts = statement.split(':')
    t = Trigger(trigger_type=trigger_type, notification_name='', raw=statement)
    if len(parts) == 2:
        t.notification_name = message_name(parts[0])
        for pair in parts[1].split(';'):
            kv = pair.split('=')
            if len(kv) != 2:
                # Original logs "Trigger definition error : '=' is missing in %@"
                # and drops the pair; we mirror that but record it.
                t.malformed = True
                continue
            key, value = kv[0], kv[1]
            if key == 'count':
                t.count = _int(value)
            elif key == 'afterCount':
                t.after_count = _int(value)
            elif key == 'afterDelay':
                t.after_delay = _float(value)
            else:
                t.parameters[key] = value
    else:
        # No colon (or more than one): the whole string becomes the name.
        # Statements such as "ChangeInactivitySoundList_soundList=..." land here
        # and resolve to an unknown message, which the original silently drops.
        t.notification_name = message_name(parts[0])
        if len(parts) != 1:
            t.malformed = True
            t.notification_name = message_name(statement)
    return t


def _int(v: str) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_triggers(obj_type: str, properties: dict[str, Any]) -> list[Trigger]:
    """``parseTriggersForNames:propertiesDict:receiver:`` for one object."""
    out: list[Trigger] = []
    for name in TRIGGER_NAMES.get(obj_type, _AGENT_TRIGGERS):
        value = properties.get(name)
        if value in (None, ''):
            continue
        for statement in str(value).split('|'):
            statement = statement.strip()
            if not statement:
                continue
            out.append(parse_trigger_statement(name, statement))
    return out


@dataclass
class LevelObject:
    """One object placed in the level's ``Level Layer``."""
    type: str
    name: str
    x: float                       # world space (room-centred)
    y: float
    width: float = 0.0
    height: float = 0.0
    properties: dict[str, str] = field(default_factory=dict)
    triggers: list[Trigger] = field(default_factory=list)
    polyline: list[tuple[float, float]] = field(default_factory=list)
    #: World-space rectangle (x, y, w, h) for Surface / ActionSurface.
    rect: tuple[float, float, float, float] | None = None
    gid: int | None = None
    tiled_x: float = 0.0           # original, pre-transform, for diagnostics
    tiled_y: float = 0.0

    def contains(self, x: float, y: float) -> bool:
        """CGRectContainsPoint against this object's rectangle."""
        if self.rect is None:
            return False
        rx, ry, rw, rh = self.rect
        return rx <= x < rx + rw and ry <= y < ry + rh

    @property
    def settable(self) -> dict[str, str]:
        """Properties the generic ``set<Key>:`` applicator would consume."""
        return {k: v for k, v in self.properties.items() if not k.startswith('On')}


@dataclass
class LevelData:
    name: str
    rect: tuple[float, float, float, float]      # x, y, w, h  (centred on origin)
    mid_room_on_tiled: tuple[float, float]
    room: LevelObject | None = None
    player: LevelObject | None = None
    objects: list[LevelObject] = field(default_factory=list)   # load order
    skipped_layers: list[str] = field(default_factory=list)

    def of_type(self, *types: str) -> list[LevelObject]:
        s = set(types)
        return [o for o in self.objects if o.type in s]

    def by_name(self, name: str) -> LevelObject | None:
        for o in self.objects:
            if o.name == name:
                return o
        return None

    def contains(self, x: float, y: float) -> bool:
        """``CGRectContainsPoint(level.rectangle, p)`` — the wall test."""
        rx, ry, rw, rh = self.rect
        return rx <= x < rx + rw and ry <= y < ry + rh


def _num(d: dict, key: str, default: float = 0.0) -> float:
    v = d.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_level(path: str, name: str | None = None) -> LevelData:
    with open(path, encoding='utf-8') as fh:
        doc = json.load(fh)
    if name is None:
        name = os.path.splitext(os.path.basename(path))[0]

    layers = [l for l in doc.get('layers', []) if l.get('type') == 'objectgroup']
    skipped = [l['name'] for l in layers if l.get('name') == 'ToolBar']
    live = [l for l in layers if l.get('name') != 'ToolBar']

    # --- pass 1: Room defines the coordinate frame -------------------------
    room_dict = None
    for layer in live:
        for o in layer.get('objects', []):
            if o.get('type') == 'Room':
                room_dict = o
                break
        if room_dict:
            break
    if room_dict is None:
        raise ValueError(f'{name}: no Room object; cannot establish level frame')

    rw, rh = _num(room_dict, 'width'), _num(room_dict, 'height')
    rx, ry = _num(room_dict, 'x'), _num(room_dict, 'y')
    rect = (-rw / 2.0, -rh / 2.0, rw, rh)
    mid = (rx + rw / 2.0, ry + rh / 2.0)

    data = LevelData(name=name, rect=rect, mid_room_on_tiled=mid,
                     skipped_layers=skipped)

    def make(o: dict) -> LevelObject:
        t = o.get('type', '') or ''
        w, h = _num(o, 'width'), _num(o, 'height')
        tx, ty = _num(o, 'x'), _num(o, 'y')
        # Every object is placed at the centre of its Tiled box, with Y negated.
        # Point objects have w = h = 0, so this is just (x, -y) about the room
        # centre.  The 'Position' marker type is the one exception in the engine
        # (it skips the half-extents); Papa Sangre 1 never uses it.
        wx = tx + w / 2.0 - mid[0]
        wy = -(ty + h / 2.0 - mid[1])
        props = {k: v for k, v in (o.get('properties') or {}).items()}
        obj = LevelObject(
            type=t, name=o.get('name', '') or '', x=wx, y=wy,
            width=w, height=h, properties=props,
            triggers=parse_triggers(t, props),
            gid=o.get('gid'), tiled_x=tx, tiled_y=ty,
        )
        if t in ('Surface', 'ActionSurface'):
            obj.rect = (tx - mid[0], -(ty - mid[1]) - h, w, h)
        if 'polyline' in o:
            # Path points are relative to the object's own origin.
            obj.polyline = [(tx + _num(p, 'x') - mid[0],
                             -(ty + _num(p, 'y') - mid[1]))
                            for p in o['polyline']]
        return obj

    data.room = make(room_dict)

    # --- pass 2: every agent, surface and path except Room and Player ------
    for layer in live:
        for o in layer.get('objects', []):
            t = o.get('type', '')
            if t in ('Room', 'Player'):
                continue
            if not t:
                continue          # untyped editor annotations
            if t == 'Comment':
                continue
            data.objects.append(make(o))

    # --- pass 3: the player ------------------------------------------------
    for layer in live:
        for o in layer.get('objects', []):
            if o.get('type') == 'Player':
                data.player = make(o)
                break
        if data.player:
            break

    return data
