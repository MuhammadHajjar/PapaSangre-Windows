"""Papa Sangre - the Windows port, playing from level 1 onward.

Runs the recovered engine on the original's own maps, sounds and scripts, and
chains from one level to the next the way the game does: the exit's win
narration ends, which fires ``LoadLevelWithName``.

Opens on a spoken menu: Continue, Choose level, Options, Credits, Quit.  Up
and down move, Enter chooses, Escape goes back, and on an options row the
**left and right arrows** change the setting.  P opens the same menu
mid-level.

Controls (all rebindable in the Options menu, or in ``config\\keys.json``):

  LEFT HAND    A left foot, D right foot - alternate them to walk
  RIGHT HAND   Left/Right arrow turn; Enter skips narration;
               Page up/down volume; Escape opens the pause menu
  CONTROLLER   d-pad left/right are the feet - and left and right in a
               menu; right stick turns; A selects, B goes back,
               Start pauses

Papa Sangre 1 uses only the feet and turning; the engine's hands, clapping,
jumping and swimming are never switched on by this game.

Built as ``Play Papa Sangre.exe``.  Headphones on.
"""

from __future__ import annotations

import math
import os
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame                                                    # noqa: E402

from papasangre.audio.engine import AudioEngine                  # noqa: E402
from papasangre.core.game import Game                            # noqa: E402
from papasangre.input.interpreter import LEFT, RIGHT             # noqa: E402
from papasangre.input.keymap import Action, KeyMap               # noqa: E402
from papasangre.input.padmap import PadMap, button_label          # noqa: E402
from papasangre.input.pygame_source import PygameInput           # noqa: E402
from papasangre.save import GameProgress                          # noqa: E402
from papasangre.shell import (CREDITS, keys_menu,                 # noqa: E402
                              level_complete_menu, level_failed_menu,
                              level_menu, main_menu, options_menu,
                              pad_menu, pause_menu)
from papasangre.shell.menu import PAD_REBINDABLE, REBINDABLE      # noqa: E402
from papasangre.util import console, paths, sysaudio             # noqa: E402
from papasangre.util.settings import Settings                     # noqa: E402

#: Turning rates live in ``papasangre.util.settings`` now, because the options
#: menu changes them and they are remembered between sittings.  [N] - the
#: original turned by swiping, so there is no rate to recover from it.

#: Names taken from each level's own FINAL_<name>_Intro asset, so they are the
#: game's own titles rather than anything invented here.
TITLES = {
    'ps1_1': 'level one: In the Dark',
    'ps1_1b': 'level one, part two: Swipe With Your Ears',
    'ps1_2': 'level two: Soul Music',
    'ps1_3': 'level three: The Kennel',
    'ps1_4': 'level four: Bed of Bones',
    'ps1_5': 'level five: Hog Patrol',
    'ps1_6': 'level six: Bedtime',
    'ps1_7': 'level seven: The Charnel House',
    'ps1_8': 'level eight: The Island',
    'ps1_9': 'level nine: The Grin Reaper',
    'ps1_10': 'level ten: Home Run',
    'ps1_11': 'level eleven: Quicksand',
    'ps1_12': 'level twelve: The River',
    'ps1_13': 'level thirteen: Pathway of Pain',
    'ps1_14': 'level fourteen: The Chessboard',
    'ps1_15': 'level fifteen: Feeding Time',
    'ps1_16': 'level sixteen: Xylophone Road',
    'ps1_17': 'level seventeen: Papa Sangre Says',
    'ps1_18': 'level eighteen: The Little Girl',
    'ps1_19': 'level nineteen: Frozen Rivers',
    'ps1_20': 'level twenty: The Zoo',
    'ps1_21': 'level twenty one: The Glass Cathedral',
    'ps1_22': 'level twenty two: The Blizzard',
    'ps1_23': 'level twenty three: Ice Lake',
    'ps1_24': 'level twenty four: The Fate Bell',
    'ps1_25': 'level twenty five: Elysium',
}


def bundle_dir() -> str:
    for c in (paths.resource('gamedata'),
              paths.resource('reference', 'Payload', 'Papa Sangre.app')):
        if os.path.isdir(os.path.join(c, 'Exports')):
            return c
    return paths.resource('reference', 'Payload', 'Papa Sangre.app')


def announce_level(game: Game, rep, keymap) -> None:
    stem = game.level_name
    title = TITLES.get(stem, stem)
    lv = game.level
    rep.show()
    rep.show(f'--- {stem}: {lv} ---')
    rep.show(f'    room {lv.rect[2]:.0f} x {lv.rect[3]:.0f}, '
             f'footsteps {lv.footsteps_prefix or "(default)"}')
    missing = game.missing_content(stem)
    if missing:
        rep.show(f'    NOT YET IMPLEMENTED in this level: '
                 + ', '.join(f'{v} {k}' for k, v in sorted(missing.items())))
    rep.say(f'Papa Sangre, {title}.')
    time.sleep(1.2)
    if missing:
        rep.say('Note: this level contains '
                + ', '.join(f'{v} {k.lower()}{"s" if v > 1 else ""}'
                            for k, v in sorted(missing.items()))
                + ', which the port does not build yet. '
                'You can walk through it, but that content is missing.')
        time.sleep(2.0)


#: The game's own startup sting, played by -[PGEViewController
#: crossFadeSplashScreen].  It is not in any playlist - it is loaded by path -
#: so it has to be named here too.
SPLASH = ('ps1', 'splash', 'papa_engine_splash.wav')


def play_intro(engine, src, rep, clock) -> None:
    """The splash, skippable.

    Four seconds, and the first thing the original plays.  Enter or A cuts it
    short, the same keys that skip a level's narration, because being made to
    sit through a sting every launch gets old fast.
    """
    from papasangre.audio.engine import SoundSpec                # noqa: PLC0415
    path = paths.game_audio(*SPLASH)
    if not os.path.exists(path):
        return
    try:
        sound = engine.load(SoundSpec('splash', path, spatialized=False))
    except Exception:                                            # noqa: BLE001
        return                       # a missing splash is not worth a crash
    sound.play()
    while sound.playing:
        if src.quit_requested:
            break
        skipped = False
        for action, phase, _stamp in src.poll():
            if phase == 'down' and action in (Action.CONFIRM.value,
                                              Action.SKIP.value,
                                              Action.CANCEL.value,
                                              Action.PAUSE.value):
                skipped = True
        if skipped:
            break
        clock.tick(60)
    sound.stop()


def keep_ambience(game) -> None:
    """Bring the level's atmosphere back for the menu that follows it.

    ``ShutDownLevel`` deactivates every agent, and ``deactivate`` does not just
    stop the sound - it drops it (``self.sound = None``).  So by the time the
    level-complete menu opens there is nothing left to restart, and the sound
    has to be fetched from the bank again by name.

    Only the looping atmospheres come back: narration and one-shots would be
    wrong to replay, and the door is still finishing its own line.
    """
    level = getattr(game, 'level', None)
    bank = getattr(game, 'bank', None)
    if level is None or bank is None:
        return []
    revived = []
    for agent in level.agents:
        if not agent.name.startswith('atmos'):
            continue
        if not getattr(agent, 'looping', False):
            continue
        try:
            sound = bank.from_sound_list(getattr(agent, 'sound_list', ''))
            if sound is None:
                continue
            sound.spatialized = False
            sound.looping = True
            sound.gain = getattr(agent, 'gain', 1.0)
            if not sound.playing:
                sound.play()
            revived.append(sound)
        except Exception:                                        # noqa: BLE001
            continue
    return revived


def stop_ambience(sounds) -> None:
    for sound in sounds or ():
        try:
            sound.stop()
        except Exception:                                        # noqa: BLE001
            pass


def rebind(keymap, action, label, src, rep, clock) -> None:
    """Bind one action to whatever key is pressed next.

    Listening for the *raw* key matters: if it went through the bindings, a
    key that is currently unbound would produce nothing and the screen would
    look broken.  Escape backs out, so escape is the one key this cannot bind
    - it has to stay the way out of a screen that swallows everything.
    """
    rep.say(f'Press the key you want for {label}. '
            'Press escape to leave it as it is.')
    key = src.capture_key(10.0)
    if not key:
        rep.say(f'{label} is still {keymap.describe(action)}.')
        return
    taken = [a for a in keymap.actions_for(key) if a != action]
    keymap.bind(action, [key])
    try:
        keymap.save()
    except OSError:
        pass
    said = f'{label} is now {key}.'
    if taken:
        # Said out loud rather than refused: the player may well want the key
        # moved, and silently ignoring the press would be worse than telling
        # them what else it does.
        nice = ', '.join(dict(REBINDABLE).get(a, a) for a in taken)
        said += f' That key is also {nice}.'
    rep.say(said)


def rebind_button(padmap, action, label, src, rep, clock) -> None:
    """The same, for a controller button.

    Escape on the keyboard cancels, because no controller button is safe to
    reserve for cancelling - it could be the one being bound.
    """
    if not src.pad.connected:
        rep.say('No controller is connected, so there is nothing to press. '
                'Plug one in and start the game again.')
        return
    rep.say(f'Press the controller button you want for {label}. '
            'Press escape on the keyboard to leave it as it is.')
    button = src.capture_button(10.0)
    if not button:
        rep.say(f'{label} is still {padmap.describe(action)}.')
        return
    taken = [a for a in padmap.actions_for(button) if a != action]
    padmap.bind(action, [button])
    try:
        padmap.save()
    except OSError:
        pass
    said = f'{label} is now {button_label(button)}.'
    if taken:
        nice = ', '.join(dict(PAD_REBINDABLE).get(a, a) for a in taken)
        said += f' That button is also {nice}.'
    rep.say(said)


def run_menu(menu, src, rep, clock, engine=None, settings=None,
             keymap=None, padmap=None):
    """Speak a menu and walk through it.  Returns ``(action, value)``.

    Up and down move, Enter or A chooses, Escape or B backs out.  On a row that
    can be adjusted - the options - **the left and right arrow keys** change
    it, or the d-pad on a controller.  Not A and D: those are feet, and only
    feet.  Nothing is drawn: the spoken row *is* the interface.
    """
    rep.show(f'  [{menu.title}]')
    rep.say(menu.announce())
    while True:
        if src.quit_requested:
            return ('quit', None)
        # One press of Enter arrives as *two* actions - confirm and skip are
        # both on it, exactly as A and its pad twin are - so a batch is only
        # allowed to choose once.  Without this, choosing a key row asked for
        # a new key twice in a row.
        chose_already = False
        for action, phase, _stamp in src.poll():
            if phase != 'down':
                continue
            if action == Action.MENU_UP.value:
                rep.say(menu.move(-1))
            elif action == Action.MENU_DOWN.value:
                rep.say(menu.move(+1))
            elif action == Action.MENU_LEFT.value:
                said = menu.adjust_current(-1)
                if said:
                    rep.say(said)
            elif action == Action.MENU_RIGHT.value:
                said = menu.adjust_current(+1)
                if said:
                    rep.say(said)
            elif action in (Action.CONFIRM.value, Action.SKIP.value):
                if chose_already:
                    continue
                chose_already = True
                chosen = menu.choose()
                if chosen is None:
                    continue
                if chosen[0] == 'blocked':
                    rep.say('That level is locked.')
                    continue
                if chosen[0] == 'adjust':
                    continue          # a slider row: left and right, not Enter
                if chosen[0] == 'rebind' and keymap is not None:
                    label = dict(REBINDABLE).get(chosen[1], chosen[1])
                    rebind(keymap, chosen[1], label, src, rep, clock)
                    menu.items = keys_menu(keymap).items
                    rep.say(menu.speak_current())
                    continue
                if chosen[0] == 'reset_keys' and keymap is not None:
                    keymap.reset()
                    keymap.save()
                    menu.items = keys_menu(keymap).items
                    rep.say('Every key is back to its default.')
                    continue
                if chosen[0] == 'rebind_button' and padmap is not None:
                    label = dict(PAD_REBINDABLE).get(chosen[1], chosen[1])
                    rebind_button(padmap, chosen[1], label, src, rep, clock)
                    menu.items = pad_menu(padmap).items
                    rep.say(menu.speak_current())
                    continue
                if chosen[0] == 'reset_buttons' and padmap is not None:
                    padmap.reset()
                    try:
                        padmap.save()
                    except OSError:
                        pass
                    menu.items = pad_menu(padmap).items
                    rep.say('Every controller button is back to its default.')
                    continue
                rep.show(f'  -> {chosen[0]}')
                return chosen
            elif action == Action.CANCEL.value:
                return ('back', None)
        clock.tick(60)


def after_game_complete(game, src, rep, clock, engine, settings, progress,
                        base, keymap=None, padmap=None):
    """The end of the game.  Returns a level to play, or None to stop.

    ps1_25 sends ``PresentAdiosVC`` from both of its doors, the good ending and
    the bad one, and the original answered it by presenting
    ``PGEAdiosViewController`` over ``playMenuAtmos``: a screen you are left
    sitting on, with the game still running behind it.

    This used to end the process instead, which from the player's side is the
    game vanishing the moment they beat it - reported as a crash, and fairly.
    You come back to the main menu now, with the last level's atmosphere still
    going underneath, and every level you have unlocked is there to replay.
    """
    finished_name = game.level_name
    progress.player_did_complete_level(finished_name)
    rep.show(f'  {finished_name} complete - the game is over')
    ambience = keep_ambience(game)
    rep.say('You have finished Papa Sangre.')
    time.sleep(2.5)
    chosen = shell(game, src, rep, clock, engine, settings, progress, base,
                   keymap, padmap)
    stop_ambience(ambience)
    return chosen


def options_loop(src, rep, clock, engine, settings, keymap, padmap) -> str:
    """Options, and the two rebinding screens underneath it.

    One function because the options are reachable from two places - the main
    menu and the pause menu - and they must behave identically in both.
    Returns how it was left, so 'quit' can be passed on.
    """
    while True:
        act, _ = run_menu(options_menu(settings, engine), src, rep, clock,
                          engine, settings, keymap, padmap)
        if act == 'keys' and keymap is not None:
            run_menu(keys_menu(keymap), src, rep, clock, engine, settings,
                     keymap, padmap)
        elif act == 'buttons' and padmap is not None:
            run_menu(pad_menu(padmap), src, rep, clock, engine, settings,
                     keymap, padmap)
        else:
            return act


def shell(game, src, rep, clock, engine, settings, progress, base,
          keymap=None, padmap=None):
    """The menus around the game.  Returns a level name to play, or None."""
    while True:
        has_progress = bool(progress.values.get('lastLevelUnlocked'))
        action, value = run_menu(main_menu(progress, has_progress),
                                 src, rep, clock, engine, settings)
        if action in ('quit', 'back'):
            return None
        if action == 'continue':
            name = progress.last_unlocked_level if has_progress else 'ps1_1'
            if not game.has_level(name):
                name = 'ps1_1'
            return name
        if action == 'levels':
            act, val = run_menu(level_menu(base, progress), src, rep, clock)
            if act == 'quit':
                return None
            if act == 'play' and val:
                return val
        elif action == 'options':
            if options_loop(src, rep, clock, engine, settings,
                            keymap, padmap) == 'quit':
                return None
        elif action == 'credits':
            rep.say(CREDITS)
            time.sleep(2.5)


def main(rep) -> int:
    #: A level name on the command line (the "Start at level N" launchers) goes
    #: straight in.  With no argument you get the menu, the way the game does.
    start = sys.argv[1] if len(sys.argv) > 1 else None
    base = bundle_dir()

    rep.show('Papa Sangre - Windows port')
    rep.show('=' * 46)
    engine = AudioEngine()
    engine.open()
    rep.show(f'output device : {console.ascii_safe(engine.device_name)}')
    rep.show(f'HRTF          : {engine.hrtf_status} {engine.available_hrtfs}')
    rep.show(f'volume        : {engine.master_volume_db:+.1f} dB')
    for w in sysaudio.warnings_for(engine.device_name):
        rep.say('Warning. ' + w)
        time.sleep(2.0)

    keymap = KeyMap.load()
    if getattr(keymap, 'was_reset', False):
        rep.show('  key bindings were reset for this version')
        rep.say('Your key bindings were reset, because the default keys '
                'changed in this version.')
    clash = keymap.conflicts()
    if clash:
        rep.say('Warning: keys bound twice: '
                + '; '.join(f'{k} is {" and ".join(v)}' for k, v in clash.items()))

    padmap = PadMap.load()
    settings = Settings()
    progress = GameProgress()
    rep.show(f'turn speed    : {settings.turn_rate:.0f} deg/s')

    game = Game(engine, base)
    if start is not None and not game.has_level(start):
        rep.say(f'There is no level called {start}.')
        return 1

    src = PygameInput(keymap, title='Papa Sangre', padmap=padmap)
    rep.show()
    rep.show('Controls  (edit config\\keys.json to change any of them):')
    for action, label in ((Action.FOOT_LEFT, 'left foot   (left hand)'),
                          (Action.FOOT_RIGHT, 'right foot  (left hand)'),
                          (Action.TURN_LEFT, 'turn left   (right hand)'),
                          (Action.TURN_RIGHT, 'turn right  (right hand)'),
                          (Action.SKIP, 'skip narration'),
                          (Action.VOLUME_UP, 'volume up'),
                          (Action.VOLUME_DOWN, 'volume down'),
                          (Action.PAUSE, 'pause and resume'),
                          (Action.CANCEL, 'quit')):
        rep.show(f'  {keymap.describe(action):<22} {label}')
    rep.show()
    rep.say('Papa Sangre. Put your headphones on. Your left hand walks: '
            f'{keymap.describe(Action.FOOT_LEFT)} is your left foot, '
            f'{keymap.describe(Action.FOOT_RIGHT)} is your right. You must '
            'alternate them. A foot you have just used will not step again, so '
            'if nothing happens, it is the turn of the other foot. Stop for '
            'two seconds and you will hear yourself shuffle, and then either foot '
            'may start. Your right hand turns with the arrow keys. Press '
            f'{keymap.describe(Action.SKIP)} to skip narration.')
    time.sleep(1.0)

    clock = pygame.time.Clock()
    if src.pad.connected:
        rep.show(f'controller    : {console.ascii_safe(src.pad.name)}')
        rep.say(src.pad.describe())
        time.sleep(1.0)

    if start is None:
        play_intro(engine, src, rep, clock)
        start = shell(game, src, rep, clock, engine, settings, progress,
                      base, keymap, padmap)
        if start is None:
            rep.say('Goodbye.')
            src.close()
            engine.close()
            pygame.quit()
            return 0

    t0 = time.perf_counter()
    game.load(start, 0.0)
    progress.player_did_unlock_level(start)
    announce_level(game, rep, keymap)

    last_report = 0.0
    running = True

    while running:
        now = time.perf_counter() - t0
        mi = game.interpreter

        for action, phase, stamp in src.poll():
            ts = stamp - t0
            foot = (LEFT if action == Action.FOOT_LEFT.value else
                    RIGHT if action == Action.FOOT_RIGHT.value else None)
            if foot is not None:
                if phase == 'down':
                    mi.foot_pressed(foot)
                else:
                    mi.foot_released(foot, ts)
            elif phase == 'down':
                if action == Action.SKIP.value:
                    for a in game.level.agents:
                        if getattr(a, 'skip', None) and a.skip():
                            rep.show('  (narration skipped)')
                            break
                elif action == Action.VOLUME_UP.value:
                    engine.adjust_master_volume(+2.0)
                    rep.say(f'Volume {engine.master_volume_db:+.0f} decibels.')
                elif action == Action.VOLUME_DOWN.value:
                    engine.adjust_master_volume(-2.0)
                    rep.say(f'Volume {engine.master_volume_db:+.0f} decibels.')
                elif action == Action.PAUSE.value:
                    lv = game.level
                    lv.pause()
                    choice, _ = run_menu(pause_menu(), src, rep, clock,
                                         engine, settings)
                    if choice in ('resume', 'back'):
                        lv.resume(time.perf_counter() - t0)
                        rep.say('Resumed.')
                    elif choice == 'options':
                        options_loop(src, rep, clock, engine, settings,
                                     keymap, padmap)
                        lv.resume(time.perf_counter() - t0)
                        rep.say('Resumed.')
                    elif choice == 'restart':
                        t0 = time.perf_counter()
                        game.load(game.level_name, 0.0)
                        announce_level(game, rep, keymap)
                    elif choice == 'main':
                        nxt = shell(game, src, rep, clock, engine, settings,
                                    progress, base, keymap, padmap)
                        if nxt is None:
                            running = False
                        else:
                            t0 = time.perf_counter()
                            game.load(nxt, 0.0)
                            progress.player_did_unlock_level(nxt)
                            announce_level(game, rep, keymap)
                    else:
                        running = False
                # CANCEL is deliberately *not* a quit.  Escape pauses, and
                # the only ways out are Quit in the menu or alt+F4.
        if src.quit_requested:
            running = False

        dt = clock.get_time() / 1000.0
        if dt > 0:
            turn = 0.0
            rate = settings.turn_rate
            if src.is_held(Action.TURN_LEFT):
                turn += rate * dt
            if src.is_held(Action.TURN_RIGHT):
                turn -= rate * dt
            # The right stick is analogue, so it turns as a rate: pushed half
            # way you turn at half speed, which is what makes it feel like the
            # swipe it stands in for.
            stick = src.turn_rate()
            if stick:
                turn -= stick * rate * dt
            if turn:
                mi.rotate_by(math.radians(turn))

        game.update(now)

        if now - last_report > 10.0:
            last_report = now
            p = game.level.player
            rep.show(f'  t={now:6.1f}s  {game.level_name}  '
                     f'({p.position[0]:7.1f},{p.position[1]:7.1f})  '
                     f'facing {p.bearing_degrees:5.1f}  bpm {p.walk_bpm:6.1f}')

        if game.finished and game.game_complete:
            nxt3 = after_game_complete(game, src, rep, clock, engine, settings,
                                       progress, base, keymap, padmap)
            if nxt3 is None:
                running = False
            else:
                t0 = time.perf_counter()
                game.load(nxt3, 0.0)
                progress.player_did_unlock_level(nxt3)
                last_report = 0.0
                announce_level(game, rep, keymap)
        elif game.finished or (game.level is not None
                               and game.level.shutting_down
                               and game.next_level == game.level_name):
            # The level is over, one way or the other.  The original chained
            # straight on; this stops and asks, with the level's own ambience
            # still running underneath so it stays part of the game.
            failed = game.next_level == game.level_name
            finished_name = game.level_name
            nxt = None if failed else game.next_level
            if not failed:
                progress.player_did_complete_level(finished_name)
                if nxt:
                    progress.player_did_unlock_level(nxt)
            ambience = keep_ambience(game)
            title = TITLES.get(finished_name, finished_name)
            menu = (level_failed_menu(title) if failed
                    else level_complete_menu(nxt, title))
            choice, value = run_menu(menu, src, rep, clock, engine,
                                     settings, keymap)
            stop_ambience(ambience)

            if choice in ('quit',) or (choice == 'back' and failed is None):
                running = False
            elif choice == 'next' and value:
                t0 = time.perf_counter()
                game.load(value, 0.0)
                progress.player_did_unlock_level(value)
                last_report = 0.0
                announce_level(game, rep, keymap)
            elif choice in ('replay', 'back'):
                t0 = time.perf_counter()
                game.load(finished_name, 0.0)
                last_report = 0.0
                announce_level(game, rep, keymap)
            elif choice in ('levels', 'main', 'options'):
                nxt2 = shell(game, src, rep, clock, engine, settings,
                             progress, base, keymap, padmap)
                if nxt2 is None:
                    running = False
                else:
                    t0 = time.perf_counter()
                    game.load(nxt2, 0.0)
                    progress.player_did_unlock_level(nxt2)
                    last_report = 0.0
                    announce_level(game, rep, keymap)
            else:
                running = False

        clock.tick(120)

    rep.show()
    rep.show(f'levels played: {" -> ".join(game.history)}')
    rep.say('Stopped.')
    game.unload()
    src.close()
    engine.close()
    pygame.quit()
    return 0


if __name__ == '__main__':
    raise SystemExit(console.run(main))
