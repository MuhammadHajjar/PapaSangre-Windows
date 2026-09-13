"""``PGEDilemma`` - someone in the dark asking you to carry them.

Four of them across the game: the baby in ps1_7, the old man in ps1_12, the
girl in ps1_18 and the siren in ps1_23.  Each lies there calling out, and you
choose whether to pick them up.  Picking one up costs you something - the baby
wakes every enemy in the room, the old man and the siren cap how fast you may
step, the girl gives you a proximity radius that announces you - and the ending
you are told at the exit depends on which ones you carried.

It is a ``PGEGameAgent`` like everything else, and it drives the **same**
``state`` ivar the enemies use, on the four values their jump table leaves
unused:

===  ==========  ================================================
10   REST        lying there, looping ``restSound``
 9   ALERT       you came within ``alertDistance`` - ``alertSound``
 8   ABANDONED   you were near and then left again - ``abandonSound``
11   THANKED     you picked them up - ``thanksSound``, and that is final
===  ==========  ================================================

``bpmMalus`` is in the level data (the baby carries 50) and in the class, but
**nothing in the binary ever reads it** - only its own getter and setter exist.
It is dead data from an earlier design; the real price of the baby is its
``OnCollide``.
"""

from __future__ import annotations

from ..core.messages import MessageBus
from .agent import GameAgent

ABANDONED = 8
ALERT = 9
REST = 10
THANKED = 11

STATE_NAMES = {ABANDONED: 'abandoned', ALERT: 'calling out',
               REST: 'resting', THANKED: 'carried'}

#: -[PGEDilemma init]: setAlertDistance: 100.0 (0x100141be0), collected = NO.
DEFAULT_ALERT_DISTANCE = 100.0


class Dilemma(GameAgent):
    """A person you can choose to save."""

    def __init__(self, bus: MessageBus, name: str = '',
                 position=(0.0, 0.0), bank=None, level=None) -> None:
        super().__init__(bus, name=name, position=position, bank=bank, level=level)
        self.rest_sound = ''
        self.alert_sound = ''
        self.thanks_sound = ''
        self.abandon_sound = ''
        self.dilemma_id = ''
        self.collected = False
        self.bpm_malus = 0.0             # never read; see the module docstring
        self.alert_distance = DEFAULT_ALERT_DISTANCE
        self.state_at_previous_frame = 0
        self._current_sound_name = ''

    # ------------------------------------------------------------ activity
    def activate(self) -> None:
        """``-[PGEDilemma activate]`` - they start out resting."""
        self.state = REST
        super().activate()

    # --------------------------------------------------------------- sound
    def play_sound(self, name: str) -> None:
        """``-[PGEDilemma playSound:]``

        Guarded on the name alone, like the enemy's, and it leaves
        ``spatialized`` to the playlist - which marks the living, aware and
        abandon sounds positioned and the collect sound flat, so the thank-you
        is spoken in your head rather than from the floor.

        The call is ``[[self sound] play:YES]`` (``mov w2, #1`` at 0x1000457c8),
        so **every** dilemma sound loops - the baby goes on crying until its
        state changes.  ``PGECollectible startLoop`` passes the same flag; the
        one-shot ``hitwall`` passes ``play:NO``.
        """
        if self.bank is None or not name:
            return
        if name == self._current_sound_name:
            return
        if self.sound is not None:
            self.sound.stop()
        sound = self.bank.sound(name)
        if sound is None:
            return
        self.sound = sound
        self._current_sound_name = name
        if sound.spatialized:
            self.update_spatialized_sound()
        sound.looping = True
        sound.play()

    # ---------------------------------------------------------- collisions
    def check_collisions_with_player(self) -> bool:
        """``-[PGEDilemma checkCollisionsWithPlayer]``

        Once carried, nothing more happens - not even the ordinary collide
        test.  Otherwise coming inside ``alertDistance`` sets them calling, and
        leaving again after that sets them abandoned.  Note the asymmetry:
        abandoned is only reachable *from* alert, so someone you never went
        near never cries after you.
        """
        if self.state == THANKED:
            return False
        if self.active:
            dx = self.player_position[0] - self.position[0]
            dy = self.player_position[1] - self.position[1]
            if (dx * dx + dy * dy) < (self.alert_distance * self.alert_distance):
                self.state = ALERT
            elif self.state == ALERT:
                self.state = ABANDONED
        return super().check_collisions_with_player()

    def collides_with_player(self) -> None:
        """``-[PGEDilemma collidesWithPlayer]`` - you picked them up."""
        super().collides_with_player()
        self.collected = True
        self.state = THANKED

    # -------------------------------------------------------------- update
    def update(self, now: float, dt: float = 1.0 / 60.0) -> None:
        """``-[PGEDilemma update:]``"""
        if not self.active:
            return
        self.check_collisions_with_player()
        state = self.state
        if state != self.state_at_previous_frame:
            self.play_sound({ABANDONED: self.abandon_sound,
                             ALERT: self.alert_sound,
                             REST: self.rest_sound,
                             THANKED: self.thanks_sound}.get(state, ''))
        self.state_at_previous_frame = state
        super().update(now, dt)

    # ---------------------------------------------------------------- info
    @property
    def state_name(self) -> str:
        return STATE_NAMES.get(self.state, str(self.state))

    def __repr__(self) -> str:
        return (f'<Dilemma {self.name!r} {self.state_name}'
                f'{" collected" if self.collected else ""}>')
