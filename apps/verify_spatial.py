"""Objectively verify the port's binaural chain, end to end.

Renders clicks at known bearings through OpenAL Soft's loopback device and
measures the resulting stereo output for the interaural time and level
differences a real head produces.  Nothing here relies on listening.

Exercised in one go: the HRTF recovered from the iOS binary, the makemhr
conversion, the recovered listener transform, the CSL to OpenAL axis mapping,
and OpenAL's own HRTF renderer.

Built as ``Verify spatial audio.exe``.
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papasangre.audio.measure import (LoopbackRenderer, check,   # noqa: E402
                                      sweep)
from papasangre.util import console, paths                       # noqa: E402


def main(rep) -> int:
    rep.show('Papa Sangre - spatial audio verification')
    rep.show('=' * 46)
    rep.show(f'HRTF directory : {paths.hrtf_dir()}')
    rep.show(f'OpenAL DLL     : {paths.openal_dll()}')
    rep.show()

    r = LoopbackRenderer()
    try:
        rep.show(f'HRTF status    : {r.hrtf_status}')
        rep.show(f'HRTF offered   : {r.available}')
        rep.show()
        if r.hrtf_status != 'enabled':
            rep.say('H R T F is not active, so this measurement would mean '
                    'nothing. Verification failed.')
            return 1
        if 'papa_ircam_1050' not in r.available:
            rep.say('The recovered H R T F is not installed. Verification failed.')
            return 1

        rep.say('Measuring. This takes a few seconds.')
        rows = sweep(r)

        rep.show(f'{"bearing":>9}{"ITD samples":>14}{"ILD dB":>10}   expectation')
        rep.show('-' * 62)
        for bearing, itd, ild in rows:
            exp = ('centred' if bearing in (0.0, 180.0)
                   else 'left ear near' if bearing < 180 else 'right ear near')
            rep.show(f'{bearing:>9.0f}{itd:>14.1f}{ild:>10.2f}   {exp}')
        rep.show()

        failures = check(rows)
        lateral = max(abs(itd) for b, itd, _ in rows if b in (90.0, 270.0))
        if failures:
            for f in failures:
                rep.show(f'  FAILED: {f}')
            rep.say(f'Verification failed with {len(failures)} problems. '
                    f'See the list above.')
            return 1

        rep.show(f'peak lateral delay: {lateral:.0f} samples '
                 f'({lateral / r.rate * 1000:.2f} milliseconds)')
        rep.show()
        rep.say('Verification passed. The rendered output shows correct '
                'interaural cues at every bearing, with a peak lateral delay '
                f'of {lateral / r.rate * 1000:.2f} milliseconds, which is what '
                'a real head produces.')
        return 0
    finally:
        r.close()


if __name__ == '__main__':
    raise SystemExit(console.run(main))
