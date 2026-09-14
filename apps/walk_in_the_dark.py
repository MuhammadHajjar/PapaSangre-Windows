"""Papa Sangre, level 1: "In the Dark" - the first playable cell of the port.

Everything here runs on the recovered engine: the level is the original's Tiled
export, the sounds are the original's own files, the spatialisation uses the
HRTF lifted out of the iOS binary, and the walking, tempo and trigger logic are
the arithmetic read out of its ARM64 code.

Controls (rebindable in ``config/keys.json``):

    A / D            left foot, right foot - alternate them to walk
    Left / Right     turn, while held
    Enter            skip the narration
    Page up / down   volume

Built as ``Walk in the dark.exe``.  Headphones on.
"""

from __future__ import annotations

import math
import os
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame                                                    # noqa: E402

from papasangre.audio.bank import SoundBank                      # noqa: E402
from papasangre.audio.engine import AudioEngine                  # noqa: E402
from papasangre.core.messages import MessageBus                  # noqa: E402
from papasangre.input.interpreter import (LEFT, RIGHT,           # noqa: E402
                                          MoveInterpretor)
from papasangre.input.keymap import Action, KeyMap               # noqa: E402
from papasangre.input.pygame_source import PygameInput           # noqa: E402
from papasangre.util import console, host, paths, sysaudio       # noqa: E402
from papasangre.world.level import Level                         # noqa: E402

#: Degrees per second while a turn key is held.  The original turned by swiping,
#: so there is no rate to recover - this is a keyboard-side choice, and it is in
#: the key map's config file so it can be changed.
TURN_RATE_DEG = 120.0
#: Degrees per press of the discrete turn keys.
TURN_STEP_DEG = 15.0

LEVEL = 'ps1_1'
LEVEL_TITLE = 'Papa Sangre, level one: In the Dark'


def bundle_dir() -> str:
    for c in (paths.resource('gamedata'),
              paths.resource('reference', 'Payload', 'Papa Sangre.app')):
        if os.path.isdir(os.path.join(c, 'Exports')):
            return c
    return paths.resource('reference', 'Payload', 'Papa Sangre.app')


def main(rep) -> int:
    base = bundle_dir()
    exports = os.path.join(base, 'Exports', 'Papa Sangre')

    rep.show('Papa Sangre - ' + host.PORT_NAME + ' port')
    rep.show('=' * 46)
    engine = AudioEngine()
    engine.open()
    rep.show(f'output device : {console.ascii_safe(engine.device_name)}')
    rep.show(f'HRTF          : {engine.hrtf_status} {engine.available_hrtfs}')
    rep.show(f'reverb        : {"on" if engine.reverb_slot else "off"}')
    for w in sysaudio.warnings_for(engine.device_name):
        rep.say('Warning. ' + w)
        time.sleep(2.0)

    bus = MessageBus()
    interpreter = MoveInterpretor(bus)
    bank = SoundBank(engine, base)
    loaded = bank.load_playlist(LEVEL)
    rep.show(f'sound bank    : {loaded} sounds')

    level = Level(bus, bank).load(os.path.join(exports, f'{LEVEL}.json'), LEVEL)
    rep.show(f'level         : {level}')
    rep.show(f'room          : {level.rect[2]:.0f} by {level.rect[3]:.0f} pixels, '
             f'footsteps {level.footsteps_prefix!r}')

    keymap = KeyMap.load()
    src = PygameInput(keymap, title='Papa Sangre - In the Dark')
    rep.show()
    rep.show('Controls  (edit config/keys.json to change any of them):')
    for action, label in ((Action.FOOT_LEFT, 'left foot   (left hand)'),
                          (Action.FOOT_RIGHT, 'right foot  (left hand)'),
                          (Action.TURN_LEFT, 'turn left   (right hand)'),
                          (Action.TURN_RIGHT, 'turn right  (right hand)'),
                          (Action.SKIP, 'skip narration'),
                          (Action.VOLUME_UP, 'volume up'),
                          (Action.VOLUME_DOWN, 'volume down'),
                          (Action.CANCEL, 'leave')):
        rep.show(f'  {keymap.describe(action):<22} {label}')
    rep.show()
    rep.show('Papa Sangre 1 uses only the feet and turning. The engine also has')
    rep.show('hands, clapping, jumping and swimming, but this game never enables')
    rep.show('them - Papa Sangre II is the one with hands and clapping.')
    rep.show(f'volume        : {engine.master_volume_db:+.1f} dB')
    rep.show()
    clash = keymap.conflicts()
    if clash:
        rep.say('Warning: some keys are bound to two actions at once: '
                + '; '.join(f'{k} is {" and ".join(v)}' for k, v in clash.items()))
        time.sleep(2.0)

    rep.say(LEVEL_TITLE + '. Put your headphones on. '
            f'Your left hand walks: {keymap.describe(Action.FOOT_LEFT)} is your '
            f'left foot, {keymap.describe(Action.FOOT_RIGHT)} is your right. '
            'Alternate them. Do not use the same foot twice in a row or you '
            'will stumble. '
            f'Your right hand steers with the arrow keys, though this level '
            'has no turning. '
            'Page up and page down change the volume. '
            f'Press {keymap.describe(Action.SKIP)} to skip the narration.')

    clock = pygame.time.Clock()
    t0 = time.perf_counter()
    level.start(0.0)
    engine.set_listener(level.player.position, level.player.bearing_degrees)
    intro = level.agent('FINAL_ITD_Intro')
    if intro is not None and intro.sound is not None:
        rep.show(f'narration     : {intro.sound.name} '
                 f'({intro.sound.duration:.0f} s, press '
                 f'{keymap.describe(Action.SKIP)} to skip)')

    announced_walk = False
    warned_no_turn = False
    last_report = 0.0
    running = True
    result = ''

    while running:
        now = time.perf_counter() - t0
        bus.now = now

        for action, phase, stamp in src.poll():
            ts = stamp - t0
            foot = (LEFT if action == Action.FOOT_LEFT.value else
                    RIGHT if action == Action.FOOT_RIGHT.value else None)
            if foot is not None:
                # A step fires on release, timestamped when the key came up.
                if phase == 'down':
                    interpreter.foot_pressed(foot)
                else:
                    interpreter.foot_released(foot, ts)
            elif phase == 'down':
                if (action in (Action.TURN_LEFT.value, Action.TURN_RIGHT.value)
                        and not interpreter.player_can_rotate
                        and not warned_no_turn):
                    # Level 1's Room disables rotation and nothing re-enables it:
                    # "In the Dark" is a straight corridor. On iOS a swipe simply
                    # did nothing; with no screen to look at, say so once.
                    warned_no_turn = True
                    rep.say('Turning is disabled in this level. It is a straight '
                            'corridor - just keep walking forward.')
                if action == Action.SKIP.value:
                    for a in level.agents:
                        if getattr(a, 'skip', None) and a.skip():
                            rep.show('  (narration skipped)')
                            break
                elif action == Action.VOLUME_UP.value:
                    engine.adjust_master_volume(+2.0)
                    rep.say(f'Volume {engine.master_volume_db:+.0f} decibels.')
                elif action == Action.VOLUME_DOWN.value:
                    engine.adjust_master_volume(-2.0)
                    rep.say(f'Volume {engine.master_volume_db:+.0f} decibels.')
                elif action == Action.CANCEL.value:
                    running = False
        if src.quit_requested:
            running = False

        # continuous turning
        dt = clock.get_time() / 1000.0
        if dt > 0:
            turn = 0.0
            if src.is_held(Action.TURN_LEFT):
                turn += TURN_RATE_DEG * dt
            if src.is_held(Action.TURN_RIGHT):
                turn -= TURN_RATE_DEG * dt
            if turn:
                interpreter.rotate_by(math.radians(turn))

        level.update(now)
        engine.set_listener(level.player.position, level.player.bearing_degrees)
        engine.update_positions(bank.live_sounds())

        if not announced_walk and interpreter.player_can_walk:
            announced_walk = True
            rep.say('You can walk now.')

        if now - last_report > 5.0:
            last_report = now
            x, y = level.player.position
            rep.show(f'  t={now:6.1f}s  pos ({x:7.1f},{y:7.1f})  '
                     f'facing {level.player.bearing_degrees:5.1f}  '
                     f'bpm {level.player.walk_bpm:6.1f}  '
                     f'state {level.player.state}')

        if level.finished:
            result = f'Level complete. Next level would be {level.next_level}.'
            running = False
        elif level.shutting_down and not level.finished:
            pass                # the exit sound is still playing

        clock.tick(120)

    if result:
        rep.show()
        rep.say(result)
        time.sleep(2.0)
    else:
        rep.say('Stopped.')

    level.shutdown()
    src.close()
    engine.close()
    pygame.quit()
    return 0


if __name__ == '__main__':
    raise SystemExit(console.run(main))
