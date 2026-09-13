# Papa Sangre — Windows port

A faithful port of *Papa Sangre* (Somethin' Else, iOS, 2010) to Windows: the
audio-only horror game you play entirely by listening. All 25 levels, keyboard
and controller, screen-reader output, and the original's own HRTF.

The engine is not a re-imagining. It is the original's logic, recovered from
the arm64 binary and its data: the same maps, the same playlists, the same
walking arithmetic, the same monster state machine. `PORTING_STATUS.md` is the
journal of how each piece was recovered; `DIVERGENCES.md` lists everything that
had to differ and why; `GAME_STRUCTURE.md` is the recovered structure of the
game itself.

## Building

Everything the game runs on is in here: the audio, the Tiled map exports, the
S3D playlists, the message and object lists, and the HRTF table. Clone it and
build, there is nothing else to find.

    python tools/build_exes.py        the .exe files, into Run/

`build_exes.py` wants `vendor/makemhr/makemhr.exe` (from openal-soft's tools)
to turn the HRTF table into an `.mhr`; `vendor/openal/soft_oal.dll` is
committed.

The original's compiled binary is *not* here, and two scripts want it:
`tools/extract_hrtf.py`, which is how `tools/embedded_hrtf.dat` was pulled out
in the first place, and `tools/psdis.py`, which produces the arm64 disassembly
the port was reverse-engineered from. Neither is needed to build or play. Drop
the app at `reference/Payload/Papa Sangre.app/` if you want to run them.

## Running from source

Python 3.12, `pygame-ce`, and OpenAL Soft. Speech goes through the NVDA
controller client when NVDA is running, SAPI 5 otherwise.

    python apps/play.py               the game
    python apps/play.py ps1_17        straight into one level
    python tools/autoplay.py ps1_5    automated playthrough, for testing

## Controls

Keyboard, all rebindable in Options → Keys:

| | |
|---|---|
| A / D | left foot, right foot. Alternate them to walk |
| Left / Right arrow | turn |
| Enter | select, and skip narration |
| Up / Down arrow | move through a menu |
| Left / Right arrow | change a setting |
| Escape | pause menu, and back out of a menu |
| Page up / Page down | volume |

Controller, rebindable in Options → Controller buttons:

| | |
|---|---|
| D-pad left / right | left foot, right foot. Also left/right in a menu |
| D-pad up / down | move through a menu |
| Right stick | turn |
| A | select, and skip narration |
| B, or Back | back |
| Start | pause menu |
| Shoulders | volume |

Nothing on the keyboard or the pad quits the game: that is alt+F4, or Quit in
a menu.

## Layout

    apps/           the executables: the game, and the diagnostic tools
    papasangre/
        assets/     playlist (.sexp) and Tiled map parsing
        audio/      OpenAL binding, the S3D engine equivalent, the sound bank
        core/       message bus, run loop, timing, state machine
        input/      rebindable key map and controller map, foot interpreter
        world/      level, room, surface, path, ambience
        entities/   player, sound agent, collectible, monster, dilemma
        shell/      the menus
    tests/          297 tests, plain functions, no runner needed
    tools/          build, packaging, reverse-engineering and audit scripts

## Credits

*Papa Sangre* was created by **Somethin' Else**, published by Playground, with
the Papa Engine. This port is not affiliated with them.

Windows port by **Muhammad Hajjar**.

## Licence

The port's own code is MIT, see `LICENSE`. That covers this repository and
nothing else: the original game's audio, maps, script and trademarks are not
mine to license and are not included here.
