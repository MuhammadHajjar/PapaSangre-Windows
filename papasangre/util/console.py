"""Console helpers for the standalone tools.

These tools are launched by double-clicking, so they must never vanish without
saying what happened, and everything important is spoken as well as printed.
"""

from __future__ import annotations

import datetime
import os
import sys
import traceback

from ..accessibility import speech as speech_mod


def ascii_safe(text: str) -> str:
    """Strip anything the console code page would turn into mojibake.

    Device names in particular can carry non-Latin characters, which render as
    a run of question marks and read as noise to a screen reader.
    """
    return (text or '').encode('ascii', 'replace').decode('ascii')


class Reporter:
    """Prints and speaks."""

    def __init__(self, speak_all: bool = True):
        self.sp = speech_mod.create()
        self.speak_all = speak_all

    @property
    def backend(self) -> str:
        return self.sp.name

    @staticmethod
    def _write(text: str) -> None:
        """Print, unless there is nowhere to print to.

        The game is built windowed - no console at all - and in that case
        PyInstaller leaves ``sys.stdout`` as None, where a bare ``print`` would
        raise.  Speech is the real output anyway; the console is a convenience
        for the diagnostic tools, which are still built with one.
        """
        if sys.stdout is None:
            return
        try:
            print(text, flush=True)
        except (OSError, ValueError, AttributeError):
            pass

    def say(self, text: str, interrupt: bool = True) -> None:
        self._write(text)
        if self.speak_all:
            self.sp.speak(text, interrupt=interrupt)

    def show(self, text: str = '') -> None:
        """Print only - for tables and detail that would be tedious to hear."""
        self._write(text)

    def hold(self, message: str = 'Finished. Press Enter to close this window.') -> None:
        if sys.stdin is None or sys.stdout is None:
            return          # windowed build: there is no window to hold open
        self.say(message)
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass


def run(main, speak_all: bool = True) -> int:
    """Run a tool's ``main(reporter)`` and keep the window open afterwards.

    Any crash is printed *and spoken*, then held, so a failure is never a
    window that flashes and disappears.
    """
    rep = Reporter(speak_all=speak_all)
    try:
        code = main(rep) or 0
    except Exception as exc:                                   # noqa: BLE001
        code = 1
        detail = traceback.format_exc()
        rep.show('')
        rep.show(detail)
        where = _write_crash_log(detail)
        # The game is built windowed, so there is no console left to read a
        # traceback off.  Say what happened, and say where it was written down.
        rep.say(f'This stopped with an error: {exc}')
        if where and sys.stdout is None:
            rep.say(f'The details were written to {where}')
    rep.hold()
    return code


def _write_crash_log(detail: str) -> str:
    """Drop a traceback next to the executable so a crash is diagnosable."""
    try:
        from . import paths                                    # noqa: PLC0415
        path = os.path.join(paths.writable_root(), 'crash.log')
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(f'--- {stamp}\n')
            fh.write(detail)
            fh.write('\n')
        return path
    except Exception:                                          # noqa: BLE001
        return ''
