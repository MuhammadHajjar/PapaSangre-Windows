# Papa Sangre — Windows, macOS, and Linux port

A faithful port of *Papa Sangre* (Somethin' Else, iOS, 2010) to Windows,
macOS, and Linux: the audio-only horror game you play entirely by listening. All 25
levels, keyboard and controller, screen-reader output, and the original's own
HRTF.

The engine is not a re-imagining. It is the original's logic, recovered from
the arm64 binary and its data: the same maps, the same playlists, the same
walking arithmetic, the same monster state machine. `PORTING_STATUS.md` is the
journal of how each piece was recovered; `DIVERGENCES.md` lists everything that
had to differ and why; `GAME_STRUCTURE.md` is the recovered structure of the
game itself.

## Building

The game's audio, Tiled map exports, S3D playlists, message and object lists,
and HRTF source table are in the repository. Linux also needs the system's
OpenAL Soft, Speech Dispatcher service and Python binding, and `makemhr`.

    python tools/build_exes.py        all apps, for the platform you are on

Windows and macOS each get their own game object: `Play Papa Sangre.exe` on
Windows, `Play Papa Sangre.app` on the Mac. Both carry their own OpenAL Soft
(``vendor/openal/soft_oal.dll`` vs ``vendor/openal-mac/libopenal.dylib``),
the recovered `.mhr` HRTF, and - Windows only - the NVDA controller client.
Speech on the Mac is VoiceOver, part of the operating system.
The Linux build uses the system Speech Dispatcher service.

How a bundle is frozen matters for how fast the game appears: a one-file
PyInstaller build unpacks its whole payload to a temp dir on every launch,
which costs the game tens of seconds of startup.  The Windows game is one-file
(its cost is tolerable there); the Mac game is a one-dir app instead, whose
files are read in place and whose bundle doubles as the double-clickable
`.app` — it is on screen in about a second and a half.  The diagnostic tools
are one-file builds on both platforms.

The HRTF is not committed in its built form: `build/` is generated.  The
committed `tools/embedded_hrtf.dat` is the original IRCAM 1050 set, and
`build_exes.py` rebuilds `build/hrtf/papa_ircam_1050.mhr` from it on a fresh
clone, needing `vendor/makemhr/makemhr.exe` (Windows, from openal-soft's
binary zip), `vendor/makemhr-mac/makemhr` (Mac, built and committed), or
`makemhr` from the system on Linux. The
Mac OpenAL dylib and makemhr are built once per machine with
`tools/build_openal_mac.sh` and committed.

The original's arm64 binary is here too, at
`reference/Payload/Papa Sangre.app/Papa Sangre`. Nothing needs it to build or
play, but it is the source of truth for the reverse engineering, and two
scripts read it:

    python tools/psdis.py .           the whole-binary disassembly, into tools/dis/
    python tools/extract_hrtf.py      the IRCAM HRTF table (already committed)

`psdis.py` is worth running before you touch the engine. The port was written
against that disassembly, and `PORTING_STATUS.md` cites it by address
throughout, so being able to look one up is the difference between reading the
journal and checking it.

## Running from source

Python 3.13+, `pygame-ce`, `pyobjc-framework-cocoa` on the Mac, and OpenAL
Soft. Speech goes through the NVDA controller client when NVDA is running,
SAPI 5 otherwise; on the Mac it goes through VoiceOver, and on Linux through
Speech Dispatcher. Install the distribution's service and Python 3 client
package, such as `speech-dispatcher` on Arch or `speech-dispatcher` plus
`python3-speechd` on Debian.

On Linux, use the system Python that can import `speechd`. The binding is
provided by the distribution, not by `uv`. The system Python must be 3.13 or
newer. Create a project environment that can see its system site-packages:

    python3 -c "import speechd"
    uv venv --system-site-packages --python "$(command -v python3)"
    uv sync --locked

On a fresh clone, generate the HRTF before playing. Install your
distribution's `makemhr` tool (usually provided by OpenAL Soft), then run:

    .venv/bin/python tools/extract_hrtf.py
    makemhr -i build/hrtf/papa_ircam_1050.def -o build/hrtf/papa_ircam_1050.mhr

Run the game with the project's Python:

    .venv/bin/python apps/play.py
    .venv/bin/python apps/play.py ps1_17
    .venv/bin/python tools/autoplay.py ps1_5

The second command starts directly at level 17; the third runs an automated
playthrough for testing.

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

Nothing on the keyboard or the pad quits the game: use Alt+F4 on Windows or
Linux, Cmd+Q on the Mac, or Quit in a menu.

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

Windows port by **Muhammad Hajjar**; the macOS build of the same port runs the
same engine, with VoiceOver for speech.

## Licence

The port's own code is MIT, see `LICENSE`. That covers this repository and
nothing else: the original game's audio, maps, script and trademarks are not
mine to license and are not included here.
