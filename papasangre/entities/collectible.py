"""``PGECollectible`` - the things you walk into: notes, doors, exits.

Lifecycle, from the disassembly:

``activate``
    fetch the playlist, then ``playIntroSound``.
``playIntroSound``
    with no intro sound (or no loop sound) go straight to ``startLoop``;
    otherwise play the intro spatialised, and start the loop when it ends.
``startLoop``
    play ``loopSound`` spatialised and looping - this is the beacon you home in
    on.
``collidesWithPlayer``
    only while active and not yet collected: fire ``OnCollide``, then
    ``playCollectSound``.
``playCollectSound``
    stop the beacon and play ``collectSound`` **unspatialised**; when that ends,
    go inactive, activate ``nextCollectible`` if one is named, and fire
    ``OnSoundEnd``.  A ``collectSound`` of ``dilemmaOutcome`` is resolved by the
    level into one of the fourteen recorded endings first.

The reverb send values are the original's: min distance 1, max distance 100,
wet send from 0.05 at the near distance to 0.3 at the far one.
"""

from __future__ import annotations

from ..core.messages import MessageBus
from .agent import GameAgent

MIN_REVERB_DISTANCE = 1.0        # -[PGECollectible startLoop]
MAX_REVERB_DISTANCE = 100.0
MIN_WET_SEND = 0.05
MAX_WET_SEND = 0.3

#: [N] Port-side trim on the homing beacon only.  The original sets no gain at
#: all here, so this is a mix decision, not a recovered value - kept as one
#: named number so it is easy to find and easy to undo.
#:
#: Why it is needed: measured across the ps1_1-4 playlists, this game masters
#: almost everything close to full scale - doors -0.8 dBFS, monsters -1.6,
#: narration -3.9 - while footsteps sit at -15.8 and are then played at gain
#: 0.5.  Everything else at that level is *intermittent*; the beacon is a
#: continuous loop, so it is the one sound that sits on top of the mix the
#: whole time you are looking for it.  -4 dB pulls it back under the narration
#: without hurting how findable it is: it is still well clear of the ambience
#: at the far wall.
COLLECTIBLE_LOOP_GAIN = 0.63


class Collectible(GameAgent):
    def __init__(self, bus: MessageBus, name: str = '',
                 position=(0.0, 0.0), bank=None, level=None) -> None:
        super().__init__(bus, name=name, position=position, bank=bank, level=level)
        self.intro_sound = ''
        self.loop_sound = ''
        self.collect_sound = ''
        self.next_collectible = ''
        #: ``PGECollectible.collected``.  **Transient, not a record**: it
        #: guards against re-collecting while the collect sound is still
        #: playing, and ``deactivate`` clears it again (0x10001bb04).  For
        #: "has this ever been picked up", use ``was_collected``.
        self.collected = False
        #: Port-side: a durable record, because ``collected`` is not one.
        self.was_collected = False
        self._phase = 'idle'         # idle | intro | loop | collect

    # ------------------------------------------------------------------
    def activate(self) -> None:
        self.active = True
        self.trigger('OnActivate')
        self.play_intro_sound()

    def deactivate(self) -> None:
        """``-[PGECollectible deactivate]`` - and it **clears ``collected``**.

        ``strb wzr`` at 0x10001bb04, before the call to super.  That one store
        is the whole re-arming mechanism: a collectible that is deactivated and
        activated again is collectable again.

        ps1_23's chicken cage is built out of it.  Walking into
        ``chicken_launcher_1`` activates ``chicken_1``, whose ``OnActivate``
        alerts the hog and schedules its own deactivation 20 seconds later; its
        ``OnDeactivate`` re-activates the launcher.  Without this clear the
        launcher comes back but stays ``collected``, so the cage can be sprung
        exactly once and never again.
        """
        self.collected = False
        self._phase = 'idle'
        super().deactivate()

    # ------------------------------------------------------------------
    def _spatial(self, sound) -> None:
        sound.spatialized = True
        sound.send_to_reverb = True
        sound.wet_gain = MIN_WET_SEND
        sound.planar = (self.position[0], self.position[1], 0.0)

    def play_intro_sound(self) -> None:
        """``-[PGECollectible playIntroSound]``"""
        if self.bank is None:
            return
        if len(self.intro_sound) < 2 or not self.loop_sound:
            self.start_loop()
            return
        if self.sound is not None:
            self.sound.stop()
        sound = self.bank.sound(self.intro_sound)
        if sound is None:
            self.start_loop()
            return
        self.sound = sound
        self._spatial(sound)
        sound.looping = False
        sound.play()
        self._phase = 'intro'

    def start_loop(self) -> None:
        """``-[PGECollectible startLoop]``"""
        if self.bank is None:
            return
        if self.sound is not None:
            self.sound.stop()
        sound = self.bank.sound(self.loop_sound)
        if sound is None:
            self._phase = 'idle'
            return
        self.sound = sound
        self._spatial(sound)
        sound.gain = COLLECTIBLE_LOOP_GAIN
        sound.looping = True
        self.update_spatialized_sound()
        sound.play()
        self._phase = 'loop'

    # ------------------------------------------------------------------
    def collides_with_player(self) -> None:
        """``-[PGECollectible collidesWithPlayer]``"""
        if not self.active or self.collected:
            return
        self.trigger('OnCollide')
        self.play_collect_sound()
        # the flag is set last, at 0x10001b9a0, after both of those.  It makes
        # no difference while OnCollide is enqueued rather than posted, but the
        # order is the order.  (The original then tells PGEGameTracker to
        # incrementCollectibles - Flurry telemetry, nothing audible.)
        self.collected = True
        self.was_collected = True

    def play_collect_sound(self) -> None:
        """``-[PGECollectible playCollectSound]``"""
        if self.sound is not None:
            self.sound.stop()
            self.sound = None
        name = self.collect_sound
        if name == 'dilemmaOutcome' and self.level is not None:
            name = self.level.solve_dilemmas()
            self.collect_sound = name
        sound = self.bank.sound(name) if self.bank else None
        if sound is None:
            self._finish_collect()
            return
        self.sound = sound
        sound.spatialized = False
        sound.looping = False
        sound.play()
        self._phase = 'collect'

    def _finish_collect(self) -> None:
        # The original ends the collect sound with ``[self setActive:NO]``
        # (0x10001c030), and ``-[PGEGameAgent setActive:]`` calls ``deactivate``
        # on a true->false transition (0x10001fe30).  So this has to go through
        # deactivate rather than just clearing the flag: the override there is
        # what resets ``collected``, and without it a collectible can never be
        # collected a second time.  ps1_23's chicken cage is built on exactly
        # that, and sprang once and then never again.
        self.deactivate()
        self._phase = 'idle'
        if self.next_collectible:
            self.bus.enqueue('PGE_MESSAGE_ActivateAgentWithName',
                             {'name': self.next_collectible})
        self.trigger('OnSoundEnd')

    # ------------------------------------------------------------------
    def update(self, now: float, dt: float = 1.0 / 60.0) -> None:
        """Drive the intro -> loop and collect -> finished transitions.

        PGECollectible does not override ``update:`` - it inherits the base
        one, and gets end-of-sound from the S3D engine's own callback.  The
        port has no such callback so it polls here, but the base class's
        per-frame work still has to run, and first.
        """
        super().update(now, dt)
        if self.sound is None:
            return
        if self._phase == 'intro' and not self.sound.playing:
            self.start_loop()
        elif self._phase == 'collect' and not self.sound.playing:
            self._phase = 'idle'
            self._finish_collect()
