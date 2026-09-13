"""Asset reachability: sounds a level DECLARES that no port code path can name."""
import glob, json, os, re, sys
sys.path.insert(0, '.')
from papasangre.assets.sexp import parse_playlist, include_stem

BASE = os.path.join('reference','Payload','Papa Sangre.app')
EX   = os.path.join(BASE,'Exports','Papa Sangre')
META = os.path.join(BASE,'meta','S3DPlayListModel')

def declared(stem, seen=None, out=None):
    seen = seen if seen is not None else set()
    out  = out  if out  is not None else set()
    if stem in seen: return out
    seen.add(stem)
    m = glob.glob(os.path.join(META, f'{stem}.S3DPlayListModel*.sexp'))
    if not m: return out
    pl = parse_playlist(open(m[0], encoding='utf-8', errors='replace').read(), stem)
    out |= {s.name for s in pl.sounds}
    for inc in pl.includes:
        declared(include_stem(inc), seen, out)
    return out

total_gaps = {}
for p in sorted(glob.glob(os.path.join(EX,'*.json'))):
    stem = os.path.basename(p)[:-5]
    names = declared(stem)
    if not names: continue
    raw = open(p, encoding='utf-8', errors='replace').read()
    d = json.load(open(p, encoding='utf-8', errors='replace'))

    prefixes = set(re.findall(r'"footstepsPrefix"\s*:\s*"([^"]+)"', raw))
    reach = set()
    for n in names:
        if n in raw:                                   # named outright
            reach.add(n); continue
        if any(n.startswith(pre + '_') for pre in prefixes):   # footstep bank
            reach.add(n); continue
    gaps = sorted(names - reach)
    if gaps:
        total_gaps[stem] = gaps

print('Declared but not nameable by any port code path:\n')
for stem, gaps in total_gaps.items():
    print(f'  {stem:<9} {len(gaps):>2}  {", ".join(gaps[:6])}'
          + (' ...' if len(gaps) > 6 else ''))
allg = sorted({g for gs in total_gaps.values() for g in gs})
print(f'\n{len(allg)} distinct sounds across {len(total_gaps)} levels')
