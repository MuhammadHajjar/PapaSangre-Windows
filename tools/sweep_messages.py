import glob, json, os, re
EX = os.path.join('reference', 'Payload', 'Papa Sangre.app', 'Exports', 'Papa Sangre')
msgs, keys = {}, {}
for p in sorted(glob.glob(os.path.join(EX, '*.json'))):
    stem = os.path.basename(p)[:-5]
    raw = open(p, encoding='utf-8', errors='replace').read()
    for m in set(re.findall(r'PGE_[A-Za-z_0-9]+', raw)):
        msgs.setdefault(m, set()).add(stem)
    data = json.load(open(p, encoding='utf-8', errors='replace'))
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                keys.setdefault(k, set()).add(stem)
                walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(data)

port = ''
for root, _d, fs in os.walk('papasangre'):
    if '__pycache__' in root: continue
    for f in fs:
        if f.endswith('.py'):
            port += open(os.path.join(root, f), encoding='utf-8').read()

gaps = [(m, s) for m, s in msgs.items() if m not in port]
print(f'=== MESSAGES: {len(msgs)} distinct, {len(gaps)} not mentioned in the port ===')
for m, s in sorted(gaps, key=lambda kv: -len(kv[1])):
    print(f'  GAP  {m:<48} {len(s):>2} levels  e.g. {sorted(s)[0]}')

print(f'\n=== PROPERTY KEYS: {len(keys)} distinct ===')
kgaps = [(k, s) for k, s in keys.items()
         if not re.search(r"['\"]" + re.escape(k) + r"['\"]", port)]
for k, s in sorted(kgaps, key=lambda kv: -len(kv[1])):
    print(f'  GAP  {k:<34} {len(s):>2} levels  e.g. {sorted(s)[0]}')
