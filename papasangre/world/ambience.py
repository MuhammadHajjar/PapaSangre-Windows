"""Which levels are outdoors - and why that is a question at all.

**Nothing in the original asks it.** Papa Sangre has exactly one reverb for the
whole game: no playlist declares a reverb field, no level property names one,
there is not a single string literal containing "reverb" in the binary, and the
three parameters have exactly two writers, both of them engine ``init``
(``-[S3DEngine init]``, then ``-[PGEngine init]`` which overrides it and wins).
The island in ps1_8 was reverberated exactly like the cellar in ps1_1.

This module exists because Muhammad asked for the open-air levels to stop
sounding like a small room, having first asked whether that was authentic - it
is - and then decided he wanted it changed anyway.  It is a **deliberate
divergence**, recorded in DIVERGENCES.md, and the only one in the port that
changes how the game sounds rather than what it does.

The classification is taken from the ground under your feet rather than a list
of level names, so a level answers the question itself.  ``footstepsPrefix`` is
the most concrete signal the data has: it is the surface the designers chose to
put you on, and it splits cleanly.  A level counts as outdoors when every named
ground it uses is an outdoor one - a single indoor floor is enough to make it a
building, which is what you want for a hut in a field.
"""

from __future__ import annotations

import json
import os

from ..util import paths

#: What the open-air levels get.  ``outdoor`` is the custom open reverb;
#: ``dry`` removes the tail altogether; ``indoor`` puts the original back on
#: every level and undoes this whole module.  Overridable without a rebuild in
#: ``config/audio.json`` next to the executable: ``{"outdoorReverb": "dry"}``.
DEFAULT_OUTDOOR_PROFILE = 'outdoor'
VALID_PROFILES = ('outdoor', 'dry', 'indoor')


#: Written out on first run, the way ``config/keys.json`` is, so the setting is
#: discoverable without anyone having to be told the file exists.
_DEFAULT_AUDIO_CONFIG = {
    '_comment': 'Reverb for the open-air levels: 8-12, 19, 20, 22, 23 and 25.',
    '_note': ('Papa Sangre itself has ONE reverb for the whole game and no '
              'notion of being outdoors; this is a deliberate addition. Set '
              "outdoorReverb to 'indoor' to put the original back everywhere."),
    '_choices': list(VALID_PROFILES),
    'outdoorReverb': DEFAULT_OUTDOOR_PROFILE,
}


def audio_config_path() -> str:
    d = os.path.join(paths.writable_root(), 'config')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return os.path.join(d, 'audio.json')


def configured_outdoor_profile(path: str | None = None) -> str:
    """Read the choice from ``config/audio.json``, falling back to the default.

    A missing file is written out with the defaults; a corrupt or read-only one
    is ignored, because no audio setting is worth refusing to start over.
    """
    path = path or audio_config_path()
    try:
        with open(path, encoding='utf-8') as fh:
            value = json.load(fh).get('outdoorReverb')
    except FileNotFoundError:
        try:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(_DEFAULT_AUDIO_CONFIG, fh, indent=2)
        except OSError:
            pass
        return DEFAULT_OUTDOOR_PROFILE
    except (OSError, ValueError, AttributeError):
        return DEFAULT_OUTDOOR_PROFILE
    if isinstance(value, str) and value in VALID_PROFILES:
        return value
    return DEFAULT_OUTDOOR_PROFILE


#: Grounds that only occur in the open.  Taken from every ``footstepsPrefix``
#: in all 27 maps; the survey is in PORTING_STATUS.md.
OUTDOOR_GROUNDS = frozenset({
    'foot_reeds', 'foot_reeds-water', 'foot_sand', 'foot_sand-water',
    'foot_waterswim', 'foot_stonepath', 'foot_cornfield', 'foot_quicksand',
    'foot_hillclimb', 'foot_snow', 'foot_icethin', 'foot_icefoot',
    'foot_field',
})

#: Grounds that mean a building, a cellar, a ship or a cathedral.
INDOOR_GROUNDS = frozenset({
    'foot_stone', 'foot_stone-kennel', 'foot_kennel', 'foot_bone', 'foot_guts',
    'foot_metalsolid', 'foot_metalhollow', 'foot_metalmelodic',
    'foot_melodicbum', 'foot_wood', 'foot_hotwater', 'foot_brokenglass',
    'foot_marble', 'foot_metalbridge', 'foot_metalspacewalk', 'foot_ladder',
    'foot_racetrack',
})


def ground_family(prefix: str) -> str:
    """Strip the per-patch suffix off a footsteps prefix.

    The maps use ``foot_reeds-waterA``..``D`` and ``foot_metalmelodicA``..``P``
    for variations of one material; only the stem decides indoors or out.
    """
    name = (prefix or '').strip()
    if not name:
        return ''
    for family in sorted(OUTDOOR_GROUNDS | INDOOR_GROUNDS,
                         key=len, reverse=True):
        if name == family or name.startswith(family):
            return family
    return name


def is_outdoor(prefixes) -> bool:
    """True when every ground named is an outdoor one, and there is one.

    A level that names no ground at all (ps1_1b, the cell you wake up in) is
    not outdoors.
    """
    families = {ground_family(p) for p in prefixes if p}
    families.discard('')
    if not families:
        return False
    return families <= OUTDOOR_GROUNDS


def reverb_profile_for(prefixes, outdoor_profile: str = 'outdoor') -> str:
    """The profile name to hand to ``AudioEngine.set_reverb_profile``."""
    return outdoor_profile if is_outdoor(prefixes) else 'indoor'
