"""Resolve resource paths the same way whether running from source or frozen.

PyInstaller unpacks a one-file build into a temporary directory and points
``sys._MEIPASS`` at it.  Everything the game loads at runtime — the OpenAL DLL,
the recovered HRTF, the audio tree — goes through here so the two cases behave
identically.
"""

from __future__ import annotations

import os
import sys
import tempfile

FROZEN = getattr(sys, 'frozen', False)


def resource_root() -> str:
    """Directory holding bundled data files."""
    if FROZEN:
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def writable_root() -> str:
    """Directory we may write to (config, saves, logs).

    A one-file build's resource root is a temporary directory that disappears on
    exit, so anything that must persist goes next to the executable instead.
    """
    if FROZEN:
        return os.path.dirname(sys.executable)
    return resource_root()


def resource(*parts: str) -> str:
    return os.path.join(resource_root(), *parts)


def openal_dll() -> str:
    for candidate in (resource('soft_oal.dll'),
                      resource('vendor', 'openal', 'soft_oal.dll')):
        if os.path.exists(candidate):
            return candidate
    return resource('vendor', 'openal', 'soft_oal.dll')


def hrtf_dir() -> str:
    for candidate in (resource('hrtf'), resource('build', 'hrtf')):
        if os.path.isdir(candidate):
            return candidate
    return resource('build', 'hrtf')


def config_dir() -> str:
    """Where the player's own settings live, next to the executable.

    Keys, options, the outdoor reverb choice and the save file.  Things a
    person is meant to be able to open and change.
    """
    d = os.path.join(writable_root(), 'config')
    os.makedirs(d, exist_ok=True)
    return d


def config_path() -> str:
    """Where OpenAL Soft's own ``alsoft.ini`` goes - **not** next to the game.

    This file is not a setting, it is plumbing: it is rewritten from scratch on
    every start, and its ``hrtf-paths`` is an absolute path to wherever this
    run unpacked itself, so it is meaningless on any other machine and stale
    within seconds on this one.  Worse, it offers ``hrtf = true`` as something
    editable, and this game is the HRTF - switching it off leaves you with a
    flat mix and no way to tell why.

    So it is written into the system temp directory, where it does the job
    OpenAL needs and is not presented to anyone as a knob to turn.
    """
    d = os.path.join(tempfile.gettempdir(), 'papasangre')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = tempfile.gettempdir()
    return os.path.join(d, 'alsoft.ini')


def game_audio(*parts: str) -> str:
    """A file inside the original ``Papa Sangre.app`` audio tree."""
    for base in (resource('gamedata'),
                 resource('reference', 'Payload', 'Papa Sangre.app')):
        p = os.path.join(base, *parts)
        if os.path.exists(p):
            return p
    return os.path.join(resource('reference', 'Payload', 'Papa Sangre.app'), *parts)
