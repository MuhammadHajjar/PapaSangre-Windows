"""``PGESound`` - a sound placed in the world.

Does double duty in the shipped levels: the atmosphere loops, the narration, and
the invisible proximity triggers (a Sound with a ``collideRadius`` and an
``OnCollide`` but no sound list) are all this one class.

``activate`` schedules ``createSpatializedSound``, which picks a sound out of the
``soundList``, applies the spatialised flag and gain, plays it, and registers an
end-of-sound monitor that fires ``OnSoundEnd``.  A skippable sound that has been
heard before also asks the shell to show its skip button.
"""

from __future__ import annotations

from ..core.messages import MessageBus, Params
from .agent import GameAgent


class SoundAgent(GameAgent):
    def __init__(self, bus: MessageBus, name: str = '',
                 position=(0.0, 0.0), bank=None, level=None) -> None:
        super().__init__(bus, name=name, position=position, bank=bank, level=level)
        self.looping = False
        self.skippable = False
        self.on_x_rail = False
        self.on_y_rail = False
        self._monitoring = False

    # ------------------------------------------------------------------
    def activate(self) -> None:
        """``-[PGESound activate]`` - set active, fire OnActivate, then sound."""
        self.active = True
        self.trigger('OnActivate')
        self.create_spatialized_sound()

    def deactivate(self) -> None:
        self._monitoring = False
        super().deactivate()

    # ------------------------------------------------------------------
    def create_spatialized_sound(self) -> None:
        """``-[PGESound createSpatializedSound]``"""
        if self.bank is None:
            return
        sound = self.bank.from_sound_list(self.sound_list)
        if sound is None:
            # A Sound object with no sound list is a pure proximity trigger.
            return
        self.sound = sound
        sound.spatialized = self.spatialized
        if self.spatialized:
            self.update_spatialized_sound()
        sound.gain = self.gain
        sound.looping = self.looping
        sound.play()
        self._monitoring = not self.looping

        if self.skippable and self.level is not None:
            if self.level.can_skip_sound(sound.name):
                self.bus.post('PGE_MESSAGE_ShowSkipButton', {'soundName': sound.name})

    def update(self, now: float, dt: float = 1.0 / 60.0) -> None:
        """Watch for the end of a non-looping sound (the 3D sound monitor).

        PGESound inherits ``update:`` rather than overriding it; the polling
        below stands in for the engine's end-of-sound callback, so the base
        class's per-frame work has to run too.
        """
        super().update(now, dt)
        if not self._monitoring or self.sound is None:
            return
        if not self.sound.playing:
            self._monitoring = False
            self.trigger_on_sound_end()

    def skip(self) -> bool:
        """End a skippable sound early, as the shell's skip button does."""
        if not (self.skippable and self._monitoring and self.sound is not None):
            return False
        self.sound.stop()
        self._monitoring = False
        self.trigger_on_sound_end()
        return True

    def trigger_on_sound_end(self) -> None:
        """``-[PGESound triggerOnSoundEnd]``"""
        self.bus.post('PGE_MESSAGE_RemoveFullScreenImage', {})
        if self.skippable and self.sound is not None and self.level is not None:
            self.level.save_skippable_sound(self.sound.name)
        self.trigger('OnSoundEnd')

    # ------------------------------------------------------------------
    def _on_player_moved(self, name: str, params: Params) -> None:
        """A railed sound tracks the player on one axis before colliding."""
        pos = params.get('position')
        if isinstance(pos, (tuple, list)) and len(pos) >= 2:
            px, py = float(pos[0]), float(pos[1])
            if self.on_x_rail:
                self.position = (px, self.position[1])
            if self.on_y_rail:
                self.position = (self.position[0], py)
            if self.on_x_rail or self.on_y_rail:
                self.update_spatialized_sound()
        super()._on_player_moved(name, params)
