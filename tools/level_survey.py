import json, os, glob, collections, re, sys

BASE = r"C:\Users\Muhammad\Documents\My-claude-works\PapaSangre\reference\Payload\Papa Sangre.app"
EXP  = os.path.join(BASE, "Exports", "Papa Sangre")

types = collections.Counter()
props_by_type = collections.defaultdict(collections.Counter)
triggers = collections.Counter()
messages = collections.Counter()
msg_params = collections.defaultdict(collections.Counter)
layer_names = collections.Counter()
shape_kinds = collections.Counter()

TRIGGER_KEYS = set()

files = sorted(glob.glob(os.path.join(EXP,"*.json")))
for fp in files:
    d = json.load(open(fp, encoding='utf-8'))
    for layer in d['layers']:
        layer_names[layer['name']] += 1
        if layer['name'] == 'ToolBar':   # editor palette, not level content
            continue
        for o in layer.get('objects',[]):
            t = o.get('type','') or '(none)'
            types[t]+=1
            if 'polyline' in o: shape_kinds[t+':polyline']+=1
            elif 'polygon' in o: shape_kinds[t+':polygon']+=1
            elif o.get('width') or o.get('height'): shape_kinds[t+':rect']+=1
            else: shape_kinds[t+':point']+=1
            for k,v in (o.get('properties') or {}).items():
                props_by_type[t][k]+=1
                if k.startswith('On') or k in ('OnEnter','OnExit'):
                    TRIGGER_KEYS.add(k)
                    triggers[k]+=1
                    for stmt in str(v).split('|'):
                        stmt=stmt.strip()
                        if not stmt: continue
                        nm = stmt.split(':',1)[0]
                        messages[nm]+=1
                        if ':' in stmt:
                            for par in stmt.split(':',1)[1].split(';'):
                                if '=' in par:
                                    msg_params[nm][par.split('=',1)[0]]+=1

print("FILES:", len(files))
print("\n=== LAYER NAMES ===")
for k,v in layer_names.most_common(): print(f"  {v:4d}  {k}")
print("\n=== OBJECT TYPES (ToolBar excluded) ===")
for k,v in types.most_common(): print(f"  {v:5d}  {k}")
print("\n=== SHAPE KINDS ===")
for k,v in sorted(shape_kinds.items()): print(f"  {v:5d}  {k}")
print("\n=== PROPERTIES BY TYPE ===")
for t in sorted(props_by_type):
    print(f"  [{t}]")
    for k,v in props_by_type[t].most_common(): print(f"      {v:4d}  {k}")
print("\n=== TRIGGER KEYS ===")
for k,v in triggers.most_common(): print(f"  {v:4d}  {k}")
print("\n=== MESSAGES USED IN LEVEL DATA ===")
for k,v in messages.most_common():
    ps = ",".join(sorted(msg_params[k])) if msg_params[k] else ""
    print(f"  {v:4d}  {k:45s} params: {ps}")
