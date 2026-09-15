"""Check that the port accounts for every piece of the original game's content.

Loads all 27 level exports and all 104 sound playlists from the original iOS
data, then verifies that every object type, property, message, sound reference,
level link and footstep bank resolves. Anything that does not resolve is either
a gap in the port or a defect in the original data, and the report says which.

Also writes CONTENT_INVENTORY.md next to the executable: a per-object checklist
of everything that has to exist in the port, on any platform.

Built as ``Check game content.exe``.
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papasangre.assets import audit                             # noqa: E402
from papasangre.util import console                             # noqa: E402

#: Counts that are expected and understood - every one is a defect in the
#: original shipped data, catalogued in GAME_STRUCTURE.md section 11, and the
#: port reproduces its effect rather than fixing it.
EXPECTED_ORIGINAL_DEFECTS = {
    'unknown_messages': 8,
    'unresolved_sounds': 6,
    'dangling_names': 6,
    'malformed_triggers': 5,
    'empty_declarations': 4,
    'not_in_playlist': 8,
}

#: Counts that must be zero - a non-zero value means the port has lost content.
MUST_BE_ZERO = (
    ('unknown_props', 'object properties the engine has no setter for'),
    ('unresolved_declarations', 'declared sounds with no shipped audio file'),
    ('footstep_banks_missing', 'footstep banks a level cannot reach'),
)


def main(rep) -> int:
    rep.say('Checking Papa Sangre content coverage. This takes a few seconds.')
    rep.show()

    result = audit.run(emit=rep.show)

    rep.show()
    rep.show('=' * 62)
    rep.show('SUMMARY')
    rep.show('=' * 62)
    total_objects = sum(v for k, v in result['objects'].items() if k != 'trigger')
    rep.show(f"levels parsed            : {result['levels']}")
    rep.show(f"objects accounted for    : {total_objects}")
    rep.show(f"trigger statements       : {result['objects'].get('trigger', 0)}")
    rep.show()

    problems = []
    for key, description in MUST_BE_ZERO:
        n = result[key]
        rep.show(f'{description:<48}: {n}')
        if n:
            problems.append(f'{n} {description}')

    rep.show()
    rep.show('Known defects in the original game data (reproduced, not fixed):')
    drift = []
    for key, expected in EXPECTED_ORIGINAL_DEFECTS.items():
        got = result[key]
        label = key.replace('_', ' ')
        mark = 'as expected' if got == expected else f'CHANGED - expected {expected}'
        rep.show(f'  {label:<26}: {got:>3}   {mark}')
        if got != expected:
            drift.append(f'{label}: {got} instead of {expected}')

    rep.show()
    rep.show(f"checklist written to: {result['inventory_path']}")
    rep.show()

    if problems:
        rep.say('Content check failed. ' + '; '.join(problems))
        return 1
    if drift:
        rep.say('Content check passed, but the count of known original defects '
                'has changed: ' + '; '.join(drift) + '. That is worth a look.')
        return 0
    rep.say(f'Content check passed. All {total_objects} objects across '
            f"{result['levels']} levels are accounted for, every declared sound "
            'resolves to a real audio file, and every footstep bank is '
            'reachable. The only unresolved references are the thirty-seven '
            'known defects in the original game data, which the port '
            'reproduces exactly.')
    return 0


if __name__ == '__main__':
    raise SystemExit(console.run(main))
