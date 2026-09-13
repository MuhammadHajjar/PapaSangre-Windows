"""Listening check for the recovered Papa Sangre HRTF.

Plays real game audio through the port's audio engine and moves it around your
head, announcing each position, so the spatialisation can be judged by ear
before any gameplay is built on top of it.

Put headphones on.  Then:

    python tools/listen.py            # the full sequence
    python tools/listen.py cardinals  # front / left / behind / right only
    python tools/listen.py orbit      # continuous circle
    python tools/listen.py approach   # far to near and back
"""

from __future__ import annotations

import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.accessibility import speech as speech_mod      # noqa: E402
from papasangre.audio.engine import AudioEngine, SoundSpec     # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')

# The level 1 exit: a looping, positioned sound the original places in the world.
DOOR = os.path.join(BUNDLE, 'ps1', 'spatialized', 'door_castle_living.m4a')
# A monster loop — mono, and what the game actually spatialises around you.
HOG = os.path.join(BUNDLE, 'ps1', 'monsters', 'monster_hog1_01_dry_chase.m4a')

RADIUS = 250.0          # Tiled pixels; about 2 metres at the game's scale


class Announcer:
    def __init__(self) -> None:
        self.sp = speech_mod.create()

    def say(self, text: str) -> None:
        print(f'  {text}', flush=True)
        self.sp.speak(text, interrupt=True)


def place(sound, bearing_deg: float, radius: float = RADIUS) -> None:
    r = math.radians(bearing_deg)
    sound.planar = (radius * math.cos(r), radius * math.sin(r), 0.0)


def cardinals(engine: AudioEngine, sound, ann: Announcer) -> None:
    ann.say('Cardinal directions. Each held for three seconds.')
    time.sleep(1.2)
    for bearing, label in ((0, 'in front of you'),
                           (90, 'to your left'),
                           (180, 'behind you'),
                           (270, 'to your right'),
                           (0, 'in front again')):
        place(sound, bearing)
        ann.say(label)
        time.sleep(3.0)


def orbit(engine: AudioEngine, sound, ann: Announcer, turns: int = 2,
          seconds_per_turn: float = 8.0) -> None:
    ann.say(f'Orbit. {turns} turns, anticlockwise, starting in front.')
    time.sleep(1.5)
    steps = int(seconds_per_turn * 60)
    last = -1
    for t in range(turns * steps):
        bearing = 360.0 * (t % steps) / steps
        place(sound, bearing)
        quadrant = int(bearing // 90)
        if quadrant != last:
            last = quadrant
            print(f'    passing {["front", "left", "behind", "right"][quadrant]}',
                  flush=True)
        time.sleep(1.0 / 60.0)


def approach(engine: AudioEngine, sound, ann: Announcer) -> None:
    ann.say('Approach. The sound comes from your left, from far away to right '
            'beside you, and back.')
    time.sleep(2.0)
    for r in list(range(600, 20, -8)) + list(range(20, 600, 8)):
        place(sound, 90.0, float(r))
        time.sleep(1.0 / 60.0)


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    ann = Announcer()
    print(f'speech backend: {ann.sp.name}')

    engine = AudioEngine()
    engine.open()
    print(f'HRTF: {engine.hrtf_status}  available: {engine.available_hrtfs}')
    if engine.hrtf_status != 'enabled':
        print('WARNING: HRTF is not active; this will not demonstrate anything.')
    print(f'reverb: {"on" if engine.reverb_slot else "off"}')
    print()

    door = engine.load(SoundSpec('door_castle_living', DOOR, spatialized=True))
    hog = engine.load(SoundSpec('monster_hog1_01_dry_chase', HOG, spatialized=True))

    try:
        for sound, label in ((door, 'the level one exit door'),
                             (hog, 'a hog, from the monster set')):
            ann.say(f'Now using {label}.')
            time.sleep(1.5)
            sound.looping = True
            sound.gain = 1.0
            place(sound, 0.0)
            sound.play()
            if which in ('all', 'cardinals'):
                cardinals(engine, sound, ann)
            if which in ('all', 'orbit'):
                orbit(engine, sound, ann)
            if which in ('all', 'approach'):
                approach(engine, sound, ann)
            sound.stop()
            time.sleep(0.5)
            if which != 'all':
                break
        ann.say('Done.')
        time.sleep(1.5)
    finally:
        engine.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
