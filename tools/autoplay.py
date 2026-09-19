"""Play a level automatically and report whether it can be finished.

Not a substitute for the per-level tests: this is a smoke harness that answers
one question for every level at once - does it load, does the collectible chain
run, and does it hand on to the level it should?  It walks the chain in
``nextCollectible`` order and steers away from anything that hunts.
"""
from __future__ import annotations

import glob
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from papasangre.assets.sexp import include_stem, parse_playlist
from papasangre.core.messages import MessageBus
from papasangre.entities.collectible import Collectible
from papasangre.entities.monster import Monster
from papasangre.input.interpreter import LEFT, RIGHT, MoveInterpretor
from papasangre.save import GameProgress
from papasangre.world.level import Level
from test_level import FakeBank

BUNDLE = os.path.join(ROOT, 'reference', 'Payload', 'Papa Sangre.app')
EXPORTS = os.path.join(BUNDLE, 'Exports', 'Papa Sangre')
META = os.path.join(BUNDLE, 'meta', 'S3DPlayListModel')


def declared(stem, seen=None, out=None):
    seen = seen if seen is not None else set()
    out = out if out is not None else set()
    if stem in seen:
        return out
    seen.add(stem)
    m = glob.glob(os.path.join(META, f'{stem}.S3DPlayListModel*.sexp'))
    if not m:
        return out
    pl = parse_playlist(open(m[0], encoding='utf-8', errors='replace').read(), stem)
    out |= {s.name for s in pl.sounds}
    for inc in pl.includes:
        declared(include_stem(inc), seen, out)
    return out


def build(stem, progress=None):
    bus = MessageBus()
    mi = MoveInterpretor(bus)
    bank = FakeBank(sorted(declared(stem)), clock=lambda: bus.now)
    progress = progress or GameProgress(
        path=os.path.join(tempfile.mkdtemp(), 'p.json'))
    lv = Level(bus, bank, progress=progress).load(
        os.path.join(EXPORTS, f'{stem}.json'), stem)
    return bus, mi, bank, lv


def chain(lv):
    """Collectibles in nextCollectible order, starting from whatever leads."""
    cols = {a.name: a for a in lv.agents if isinstance(a, Collectible)}
    targets = {c.next_collectible for c in cols.values() if c.next_collectible}
    heads = [n for n in cols if n not in targets] or list(cols)
    order, seen = [], set()
    for head in heads:
        name = head
        while name and name in cols and name not in seen:
            seen.add(name)
            order.append(name)
            name = cols[name].next_collectible
    for n in cols:                      # anything the chain never reaches
        if n not in seen:
            order.append(n)
    return order


def play(stem, steps=2500, interval=0.45, keep=70.0, progress=None,
         quiet=True, peaceful=False):
    bus, mi, bank, lv = build(stem, progress)
    report = {'level': stem, 'agents': len(lv.agents), 'floors': len(lv.floors),
              'collected': [], 'next': None, 'complete': False, 'error': None}
    try:
        lv.start(0.0)
        for a in lv.agents:             # skip the opening narration
            if a.active and a.sound is not None:
                a.sound.stop()
        t = 1.0
        for s in (t, t + 0.1):
            bus.now = s
            lv.update(s)
        t += 0.1
        order = chain(lv)
        report['chain'] = order
        p = lv.player
        hunters = [a for a in lv.agents if isinstance(a, Monster)]
        x0, y0, w, h = lv.rect
        def trip_bpm_at(x, y):
            """The tripBPM of the ground at a point - the level's own depth
            search, so it matches what playerMovedToPosition: will assign."""
            best = lv
            for s in lv.floors:
                if s.contains(x, y) and s.z > best.z:
                    best = s
            return best.trip_bpm

        slowest = min([s.trip_bpm for s in lv.floors if s.trip_bpm > 0]
                      + [lv.trip_bpm or 0.0] or [0.0], default=0.0)
        report['slowest_trip_bpm'] = slowest
        if peaceful:
            # Verifying the level's *structure* - chain, doors, exit - not
            # whether a bot can out-manoeuvre a hog that runs at 30 px/s when
            # the player manages about 22.  The hunters get their own tests.
            for r in hunters:
                r.active = False
        foot = LEFT
        idle = 0
        for _ in range(steps):
            goal = None
            for name in order:
                a = lv.agent(name)
                if a is not None and a.active and not a.was_collected:
                    goal = a.position
                    break
            if goal is None:
                # The next link in the chain is activated by the last one's
                # OnCollide, which is enqueued - so there are always a few
                # frames with nothing to aim at.  Mark time rather than give up.
                idle += 1
                if idle > 20:
                    break
                t += interval
                bus.now = t
                lv.update(t)
                continue
            idle = 0
            gx, gy = goal[0] - p.position[0], goal[1] - p.position[1]
            n = math.hypot(gx, gy) or 1.0
            vx, vy = gx / n, gy / n
            for r in hunters:
                if not r.active:
                    continue
                rx, ry = p.position[0] - r.position[0], p.position[1] - r.position[1]
                d = math.hypot(rx, ry) or 1.0
                if d < keep:
                    flee = (keep - d) / keep * 2.5
                    vx += rx / d * flee
                    vy += ry / d * flee
            # Keep off the walls, but not when the thing we are walking to is
            # itself against one - ps1_16's door sits exactly on the left edge.
            if math.hypot(gx, gy) > 60.0:
                if p.position[0] < x0 + 30:
                    vx += 1.0
                if p.position[0] > x0 + w - 30:
                    vx -= 1.0
                if p.position[1] < y0 + 30:
                    vy += 1.0
                if p.position[1] > y0 + h - 30:
                    vy -= 1.0
            p.rotate_to_fixed_rotation(math.atan2(vy, vx))
            # Pace ourselves the way a player has to.  updateBPMCounter keeps
            # five stamps and divides by the count rather than the interval
            # count, so a steady tempo reads as 75/interval BPM; ps1_11 caps
            # you at 65, which is a genuine creep.  Trip and every enemy in the
            # level hears it.
            # Pace for the slowest ground anywhere in the level.  checkStepBPM
            # tests the tempo you *arrive* with against the new surface's
            # tripBPM, so speeding up on fast ground and then crossing onto
            # slow ground trips you - and a trip alerts every enemy there is.
            safe = 75.0 / (slowest * 0.85) if slowest > 0 else interval
            t += max(interval, safe)
            bus.now = t
            mi.foot_pressed(foot)
            mi.foot_released(foot, t)
            foot = RIGHT if foot == LEFT else LEFT
            lv.update(t)
            for a in lv.agents:
                if getattr(a, '_phase', None) == 'collect' and a.sound is not None:
                    a.sound.stop()
            for name in order:
                a = lv.agent(name)
                if a is not None and a.was_collected and name not in report['collected']:
                    report['collected'].append(name)
            if lv.shutting_down:
                break
        # Let the closing narration run out.  A door can chain more than one
        # sound - ps1_23 plays its win line and then the dilemma phone call -
        # so keep stopping and stepping until the level says it is finished.
        for _ in range(12):
            for a in lv.agents:
                if a.sound is not None:
                    a.sound.stop()
            t += 0.5
            bus.now = t
            lv.update(t)
            if lv.finished:
                break
        report['next'] = lv.next_level
        report['complete'] = bool(lv.finished)
        report['game_complete'] = bool(getattr(lv, 'game_complete', False))
        report['reverb'] = lv.reverb_profile
    except Exception as e:              # noqa: BLE001
        import traceback
        report['error'] = f'{type(e).__name__}: {e}'
        if not quiet:
            traceback.print_exc()
    return report


def main(argv):
    peaceful = '--peaceful' in argv
    stems = [a for a in argv[1:] if not a.startswith('--')]
    if not stems:
        stems = [f'ps1_{i}' for i in range(1, 26)]
        stems.insert(1, 'ps1_1b')
    bad = 0
    print(f'{"level":8} {"agents":>6} {"floors":>6} {"got":>4} {"next":<9} '
          f'{"reverb":<8} status')
    for stem in stems:
        r = play(stem, peaceful=peaceful)
        status = r['error'] or ('COMPLETE' if r['complete'] else 'did not finish')
        if r.get('game_complete'):
            status = 'GAME COMPLETE'
        if r['error'] or not r['complete']:
            bad += 1
        print(f'{stem:8} {r["agents"]:6} {r["floors"]:6} '
              f'{len(r["collected"]):4} {str(r["next"]):<9} '
              f'{str(r.get("reverb")):<8} {status}')
    print(f'\n{len(stems) - bad} of {len(stems)} levels completed')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
