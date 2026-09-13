"""Objectively verify the port's binaural chain end to end.

Rather than trusting that the HRTF, the coordinate mapping and OpenAL agree,
this renders real output through OpenAL Soft's loopback device and measures it:
a click is placed at known bearings around the listener and the resulting stereo
output is checked for the interaural level and time differences a real head
produces.

It exercises everything at once — the recovered IRCAM 1050 HRTF, the .mhr
conversion, ``normalize_to_head``, the CSL -> OpenAL axis mapping, and OpenAL's
own HRTF renderer.

Run:  python tools/verify_spatial.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from papasangre.audio.measure import (LoopbackRenderer, check,  # noqa: E402
                                      sweep)


def main() -> int:
    r = LoopbackRenderer()
    print(f'loopback device, HRTF: {r.hrtf_status}, offered: {r.available}')
    if r.hrtf_status != 'enabled':
        print('HRTF is not active — the measurement below would be meaningless')
        return 1
    if 'papa_ircam_1050' not in r.available:
        print('the recovered HRTF is not installed; run tools/extract_hrtf.py '
              'and makemhr first')
        return 1

    rows = sweep(r)
    print()
    print(f'{"bearing":>9}{"ITD samples":>14}{"ILD dB":>10}   expectation')
    print('-' * 62)
    for bearing, itd, ild in rows:
        exp = ('centred' if bearing in (0.0, 180.0)
               else 'left ear near' if bearing < 180 else 'right ear near')
        print(f'{bearing:>9.0f}{itd:>14.1f}{ild:>10.2f}   {exp}')
    print()

    failures = check(rows)
    if failures:
        print('FAILED:')
        for f in failures:
            print('  -', f)
        r.close()
        return 1

    lateral = max(abs(itd) for b, itd, _ in rows if b in (90.0, 270.0))
    print('PASS: rendered output shows correct interaural cues at every bearing.')
    print(f'      peak lateral ITD {lateral:.0f} samples '
          f'({lateral / r.rate * 1000:.2f} ms)')
    r.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
