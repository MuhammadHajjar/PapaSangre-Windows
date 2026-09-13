import glob, json, os, re, collections
EX = os.path.join('reference','Payload','Papa Sangre.app','Exports','Papa Sangre')
keys = collections.defaultdict(set)
for p in sorted(glob.glob(os.path.join(EX,'*.json'))):
    stem = os.path.basename(p)[:-5]
    d = json.load(open(p, encoding='utf-8', errors='replace'))
    for layer in d.get('layers', []):
        for o in layer.get('objects', []) or []:
            for k in (o.get('properties') or {}):
                keys[k].add(stem)
    for k in (d.get('properties') or {}):
        keys[k].add(stem)

port = ''
for root, _d, fs in os.walk('papasangre'):
    if '__pycache__' in root: continue
    for f in fs:
        if f.endswith('.py'):
            port += open(os.path.join(root, f), encoding='utf-8').read()

known, gaps = [], []
for k, s in keys.items():
    (known if re.search(r"['\"]" + re.escape(k) + r"['\"]", port) else gaps).append((k, s))
print(f'{len(keys)} distinct object property keys; port knows {len(known)}, ignores {len(gaps)}\n')
print('IGNORED BY THE PORT:')
for k, s in sorted(gaps, key=lambda kv: -len(kv[1])):
    print(f'  {k:<30} {len(s):>2} levels   e.g. {sorted(s)[0]}')
