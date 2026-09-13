"""The game shell: loads a level, runs it, and moves on to the next.

``PGE_MESSAGE_LoadLevelWithName`` is how the original chains levels - the exit
collectible fires it when its win narration finishes.  Everything belonging to
the old level is torn down and rebuilt, which is also what the original does
(``clearLevelData`` invalidates the update timer and removes every observer).
"""

from __future__ import annotations

import os
import random

from ..audio.bank import SoundBank
from ..audio.engine import AudioEngine
from ..input.interpreter import MoveInterpretor
from ..save import GameProgress
from ..world.level import Level
from .messages import MessageBus

#: Object types the port can build so far.  A level containing anything else
#: still loads and plays, but that content is absent - reported, never silent.
IMPLEMENTED_TYPES = {'Player', 'Room', 'Sound', 'Collectible', 'Surface',
                     'ActionSurface', 'Monster', 'ForgetfulMan', 'Path', 'Dilemma',
                     # inert in the shipped data: the NPCs carry no properties
                     # at all, Comment holds only the designer's Goal note, and
                     # the untyped objects are editor leftovers.
                     'NPC', 'Comment', ''}


class Game:
    """One audio engine, one level at a time."""

    def __init__(self, engine: AudioEngine, bundle_dir: str,
                 progress=None, rng: random.Random | None = None) -> None:
        self.engine = engine
        self.bundle_dir = bundle_dir
        self.exports = os.path.join(bundle_dir, 'Exports', 'Papa Sangre')
        if progress is None:
            progress = GameProgress()
        self.progress = progress
        self.rng = rng or random.Random()

        self.bus: MessageBus | None = None
        self.interpreter: MoveInterpretor | None = None
        self.bank: SoundBank | None = None
        self.level: Level | None = None
        self.level_name = ''
        self.history: list[str] = []

    # ------------------------------------------------------------------
    def level_path(self, stem: str) -> str:
        return os.path.join(self.exports, f'{stem}.json')

    def has_level(self, stem: str) -> bool:
        return os.path.exists(self.level_path(stem))

    def missing_content(self, stem: str) -> dict[str, int]:
        """Object types in this level that the port does not build yet."""
        from ..assets.tiled import load_level          # noqa: PLC0415
        data = load_level(self.level_path(stem), stem)
        out: dict[str, int] = {}
        for o in data.objects:
            if o.type and o.type not in IMPLEMENTED_TYPES:
                out[o.type] = out.get(o.type, 0) + 1
        return out

    # ------------------------------------------------------------------
    def load(self, stem: str, now: float = 0.0) -> Level:
        """Tear down whatever is running and start ``stem``."""
        self.unload()
        self.bus = MessageBus()
        self.interpreter = MoveInterpretor(self.bus)
        self.bank = SoundBank(self.engine, self.bundle_dir, rng=self.rng)
        self.bank.load_playlist(stem)
        self.level = Level(self.bus, self.bank, progress=self.progress,
                           rng=self.rng).load(self.level_path(stem), stem)
        self.level_name = stem
        self.history.append(stem)
        # -[PGELevel actuallyLoadDataFromJsonFile] remembers the playlist here
        self.progress.save_last_playlist(stem)
        self.level.start(now)
        self.sync_listener()
        return self.level

    def unload(self) -> None:
        if self.level is not None:
            self.level.shutdown()
        if self.bank is not None:
            self.bank.stop_all()
        self.level = None
        self.bank = None
        self.bus = None
        self.interpreter = None

    # ------------------------------------------------------------------
    def update(self, now: float) -> None:
        if self.level is None:
            return
        self.bus.now = now
        self.level.update(now)
        self.sync_listener()

    def sync_listener(self) -> None:
        if self.level is None or self.level.player is None:
            return
        self.engine.set_listener(self.level.player.position,
                                 self.level.player.bearing_degrees)
        self.engine.update_positions(self.bank.live_sounds())

    # ------------------------------------------------------------------
    @property
    def finished(self) -> bool:
        return self.level is not None and self.level.finished

    @property
    def next_level(self) -> str | None:
        return self.level.next_level if self.level else None

    @property
    def game_complete(self) -> bool:
        """ps1_25 sent ``PresentAdiosVC`` - there is nothing after this."""
        return bool(self.level is not None and
                    getattr(self.level, 'game_complete', False))

    def advance(self, now: float) -> str | None:
        """Move to whatever the finished level asked for.  Returns its name."""
        nxt = self.next_level
        if not nxt:
            return None
        if not self.has_level(nxt):
            return None
        self.load(nxt, now)
        return nxt

    # ------------------------------------------------------------------
    def describe_controls(self) -> str:
        """What the current level actually lets you do."""
        mi = self.interpreter
        if mi is None:
            return ''
        can = []
        if mi.player_can_walk:
            can.append('walk')
        if mi.player_can_rotate:
            can.append('turn')
        if mi.player_can_use_hands:
            can.append('use your hands')
        if mi.player_can_jump:
            can.append('jump')
        if not can:
            return 'You cannot move yet.'
        if len(can) == 1:
            return f'In this level you can {can[0]}.'
        return f'In this level you can {", ".join(can[:-1])} and {can[-1]}.'
