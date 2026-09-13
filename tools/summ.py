"""Condense a disassembly dump into just the semantically meaningful lines."""
import sys, re

KEEP = re.compile(
    r'; SEL "|; IVAR |; @"|; -> (?!_objc_(retain|release|autorelease|storeStrong|loadWeak|destroyWeak|initWeak|copyWeak|msgSend\b))|'
    r'\bfloat |\bdouble |#\d|'
    r'^\S+\s+(cmp|cmn|fcmp|b\.|cbz|cbnz|tbz|tbnz|fadd|fsub|fmul|fdiv|fneg|fabs|fsqrt|scvtf|fcvtzs|'
    r'add|sub|mul|sdiv|udiv|and|orr|eor|lsl|lsr|asr|mov|movk|movz|fmov|fcsel|csel|cset|fmadd|fmsub|ret|b\b)')

DROP = re.compile(r'; -> _objc_(retain|release|autorelease|storeStrong|loadWeak|destroyWeak|initWeak|copyWeak)')

path = sys.argv[1]
pat = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None
out = []
printing = False
for line in open(path, encoding='utf-8'):
    line = line.rstrip('\n')
    if line.startswith('====='):
        printing = (pat.search(line) is not None) if pat else True
        if printing:
            out.append('\n' + line)
        continue
    if not printing:
        continue
    if DROP.search(line):
        continue
    # keep only interesting instructions
    m = re.match(r'^(0x[0-9a-f]+)  (\S+)\s+(.*?)(\s*; .*)?$', line)
    if not m:
        continue
    addr, mn, ops, cmt = m.group(1), m.group(2), (m.group(3) or '').strip(), (m.group(4) or '').strip()
    if mn in ('stp', 'ldp', 'nop', 'stur', 'ldur') and not cmt:
        continue
    if mn in ('str', 'ldr', 'ldrb', 'strb', 'ldrsw', 'ldrsb') and not cmt:
        # keep ivar stores/loads only if commented; otherwise keep register-relative ones briefly
        if not re.search(r'\[x(19|20|21|0)\b', ops):
            continue
    if mn == 'mov' and not cmt and not re.search(r'#', ops):
        continue
    out.append('%s %-7s %-40s %s' % (addr[-6:], mn, ops, cmt))
print('\n'.join(out))
