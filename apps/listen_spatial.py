"""Listening check for the recovered Papa Sangre HRTF.

Plays real game audio through the port's audio engine and moves it around your
head, announcing each position, so the spatialisation can be judged by ear.

Built as ``Listen to spatial audio.exe`` - double-click it, headphones on.
Press Escape (or Ctrl+C) at any time to skip to the end.
"""

from __future__ import annotations

import math
import os
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papasangre.audio.engine import AudioEngine, SoundSpec      # noqa: E402
from papasangre.util import console, paths, sysaudio            # noqa: E402

RADIUS = 250.0          # Tiled pixels; about two metres at the game's scale

SOURCES = [
    ('the level one exit door', ('ps1', 'spatialized', 'door_castle_living.m4a')),
    ('a hog, from the monster set', ('ps1', 'monsters',
                                     'monster_hog1_01_dry_chase.m4a')),
]


def place(sound, bearing_deg: float, radius: float = RADIUS) -> None:
    r = math.radians(bearing_deg)
    sound.planar = (radius * math.cos(r), radius * math.sin(r), 0.0)


def hard_left_right(sound, rep) -> None:
    """The bluntest possible check: is there any left/right at all?

    If this does not swap sides clearly, nothing further is worth listening to
    and the problem is in the output path, not in the spatialisation.
    """
    rep.say('First, the blunt check. The sound will jump hard left, hard '
            'right, four times. If these do not swap sides clearly, stop and '
            'tell me, because nothing after this will make sense.')
    time.sleep(3.0)
    for _ in range(4):
        place(sound, 90.0, 150.0)
        rep.show('    LEFT')
        time.sleep(1.3)
        place(sound, 270.0, 150.0)
        rep.show('    RIGHT')
        time.sleep(1.3)


def cardinals(sound, rep) -> None:
    rep.say('Cardinal directions. Each one is held for three seconds.')
    time.sleep(1.5)
    for bearing, label in ((0, 'In front of you'),
                           (90, 'To your left'),
                           (180, 'Behind you'),
                           (270, 'To your right'),
                           (0, 'In front of you again')):
        place(sound, bearing)
        rep.say(label)
        time.sleep(3.0)


def orbit(sound, rep, turns: int = 2, seconds_per_turn: float = 8.0) -> None:
    rep.say(f'Orbit. {turns} slow turns, anticlockwise, starting in front.')
    time.sleep(2.0)
    steps = int(seconds_per_turn * 60)
    last = -1
    for t in range(turns * steps):
        bearing = 360.0 * (t % steps) / steps
        place(sound, bearing)
        q = int(bearing // 90)
        if q != last:
            last = q
            rep.show(f'    passing {["front", "left", "behind", "right"][q]}')
        time.sleep(1.0 / 60.0)


def approach(sound, rep) -> None:
    rep.say('Approach. The sound comes in from your left, from far away to '
            'right beside you, and back out again.')
    time.sleep(2.5)
    for r in list(range(600, 20, -6)) + list(range(20, 600, 6)):
        place(sound, 90.0, float(r))
        time.sleep(1.0 / 60.0)


def height(sound, rep) -> None:
    rep.say('Front to back, at walking distance. Front, then behind, '
            'four times, so you can judge whether they are distinct.')
    time.sleep(2.5)
    for _ in range(4):
        place(sound, 0.0, 150.0)
        rep.show('    front')
        time.sleep(1.6)
        place(sound, 180.0, 150.0)
        rep.show('    behind')
        time.sleep(1.6)


def main(rep) -> int:
    which = sys.argv[1].lower() if len(sys.argv) > 1 else 'all'

    rep.show('Papa Sangre - spatial audio listening check')
    rep.show('=' * 46)
    rep.show(f'speech backend : {rep.backend}')
    rep.show(f'HRTF directory : {paths.hrtf_dir()}')
    rep.show(f'OpenAL DLL     : {paths.openal_dll()}')
    rep.show()

    engine = AudioEngine()
    engine.open()
    rep.show(f'output device  : {console.ascii_safe(engine.device_name)}')
    rep.show(f'HRTF status    : {engine.hrtf_status}')
    rep.show(f'HRTF in use    : {engine.available_hrtfs}')
    rep.show(f'reverb         : {"on" if engine.reverb_slot else "off"}')
    mono = sysaudio.mono_mix_enabled()
    rep.show(f'Windows mono   : {"ON - this defeats all spatial audio" if mono else "off"}')
    rep.show()

    for w in sysaudio.warnings_for(engine.device_name):
        rep.say('Warning. ' + w)
        time.sleep(2.5)

    rep.say('Put your headphones on. This is the Papa Sangre spatial audio '
            'check, using the game\'s own H R T F recovered from the iOS build.')
    time.sleep(3.0)

    try:
        for label, rel in SOURCES:
            path = paths.game_audio(*rel)
            if not os.path.exists(path):
                rep.say(f'Missing audio file for {label}.')
                continue
            from papasangre.audio.loader import decode as _decode
            src_channels = _decode(path).channels
            sound = engine.load(SoundSpec(os.path.basename(path), path,
                                          spatialized=True))
            rep.show(f'  {os.path.basename(path)}: {src_channels} channel(s) on '
                     f'disk, played as {sound._channels} for spatialisation')
            rep.say(f'Now using {label}.')
            time.sleep(2.0)
            sound.looping = True
            sound.gain = 1.0
            place(sound, 0.0)
            sound.play()
            if which in ('all', 'leftright'):
                hard_left_right(sound, rep)
            if which in ('all', 'cardinals'):
                cardinals(sound, rep)
            if which in ('all', 'frontback'):
                height(sound, rep)
            if which in ('all', 'orbit'):
                orbit(sound, rep)
            if which in ('all', 'approach'):
                approach(sound, rep)
            sound.stop()
            time.sleep(0.6)
            if which != 'all':
                break
        rep.say('Listening check complete.')
        time.sleep(1.5)
    except KeyboardInterrupt:
        rep.say('Stopped.')
    finally:
        engine.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(console.run(main))
