"""Render a scripted run of the game to a WAV file, without a sound card.

The point is to be able to answer "is that sound actually in the output?" by
listening to the port's own rendering rather than by reading logs.  The engine
opens OpenAL Soft's loopback device, the game runs on a fixed clock, and every
frame of audio is captured.

    python tools/record_gameplay.py                    # default: walk, stop, listen
    python tools/record_gameplay.py ps1_3 out.wav
    python tools/record_gameplay.py ps1_1 trip.wav --trip

The default scenario walks six steps, stops for four seconds (which is what
makes the shuffle fire), walks two more, then stops again.

``--trip`` first sends ``ApplyBpmConstraint:value=50``, exactly as ps1_12 and
ps1_23 do, then steps fast enough to cross it.  That is the only way to hear
the fall: with no constraint the engine default is ``tripBPM = 10000``, which
no human can reach, and no level before ps1_11 lowers it.
"""
from __future__ import annotations

import os
import struct
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.audio.engine import AudioEngine          # noqa: E402
from papasangre.core.game import Game                    # noqa: E402
from papasangre.input.interpreter import LEFT, RIGHT     # noqa: E402

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
RATE = 44100
FRAME = 1.0 / 60.0


class Recorder:
    def __init__(self, stem: str, out: str) -> None:
        self.engine = AudioEngine()
        self.engine.open(loopback=True)
        self.game = Game(self.engine, BUNDLE)
        self.game.load(stem, 0.0)
        self.out = out
        self.frames = bytearray()
        self.t = 0.0
        self.marks: list[tuple[float, str]] = []
        bus = self.game.level.bus
        bus.subscribe('PGE_ACTION_Shuffle',
                      lambda n, p: self.marks.append((self.t, 'shuffle')))
        bus.subscribe('PGE_ACTION_OneStep',
                      lambda n, p: self.marks.append((self.t, 'step')))

    def advance(self, seconds: float) -> None:
        target = self.t + seconds
        while self.t < target:
            self.t += FRAME
            self.game.update(self.t)
            buf = self.engine.render(int(RATE * FRAME))
            for v in buf:
                v = -1.0 if v < -1.0 else (1.0 if v > 1.0 else v)
                self.frames += struct.pack('<h', int(v * 32767))

    #: The real loop reads the key-up stamp from the input event, which sits a
    #: few ms ahead of the frame clock.  Recording with that lag is the point:
    #: it is what used to stop the shuffle firing.
    KEY_LAG = 0.004

    def step(self, foot: str) -> None:
        mi = self.game.interpreter
        mi.foot_pressed(foot)
        mi.foot_released(foot, self.t + self.KEY_LAG)

    def save(self) -> str:
        with wave.open(self.out, 'wb') as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(bytes(self.frames))
        return self.out


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    trip = '--trip' in sys.argv
    stem = args[0] if args else 'ps1_1'
    out = args[1] if len(args) > 1 else os.path.join(ROOT, 'Run',
                                                     f'{stem}_walk.wav')
    r = Recorder(stem, out)
    lv = r.game.level
    lv.bus.subscribe('PGE_ACTION_Trip',
                     lambda n, p: r.marks.append((r.t, 'TRIP')))
    lv.bus.subscribe('PGE_MESSAGE_PlayerDidTrip',
                     lambda n, p: r.marks.append((r.t, 'player fell')))
    lv.bus.subscribe('PGE_MESSAGE_PlayerStartsToRun',
                     lambda n, p: r.marks.append((r.t, 'starts to run')))

    print(f'recording {stem} -> {out}')
    # let the intro narration run for a moment, then cut it short the way the
    # skip button does, so the walk starts promptly
    r.advance(2.0)
    for a in lv.agents:
        if getattr(a, 'skip', None):
            a.skip()
    r.advance(1.0)

    if trip:
        # No constraint needed any more: a Surface's own default tripBPM of 280
        # reaches the player as soon as they stand on one.  ps1_3's kennel rings
        # do that, so just run.
        print(f'  player tripBPM at start: {lv.player.trip_bpm}')
        foot = LEFT
        for _ in range(26):
            r.step(foot)
            foot = RIGHT if foot == LEFT else LEFT
            r.advance(0.16)          # far quicker than 280 BPM
        r.advance(5.0)
        path = r.save()
        print(f'{len(r.frames) / 4 / RATE:.1f} s written')
        for tm, what in r.marks:
            print(f'  {tm:6.2f}s  {what}')
        r.game.unload(); r.engine.close()
        return 0

    foot = LEFT
    for _ in range(6):
        r.step(foot)
        foot = RIGHT if foot == LEFT else LEFT
        r.advance(0.45)

    r.advance(4.0)              # stand still - the shuffle lands 2 s in

    for _ in range(2):
        r.step(foot)
        foot = RIGHT if foot == LEFT else LEFT
        r.advance(0.45)

    r.advance(4.0)

    path = r.save()
    print(f'{len(r.frames) / 4 / RATE:.1f} s written')
    print('events:')
    for t, what in r.marks:
        print(f'  {t:6.2f}s  {what}')
    r.game.unload()
    r.engine.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
