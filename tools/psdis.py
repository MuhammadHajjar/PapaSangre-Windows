"""ARM64 Mach-O disassembler with Objective-C selector / cstring / float resolution.

Used to recover the Papa Sangre engine's algorithms and numeric constants from the
decrypted arm64 binary.
"""
import struct, sys, re, os
from capstone import *
from capstone.arm64 import *

PATH = os.environ.get("PS_BIN",
    r"C:\Users\Muhammad\Documents\My-claude-works\PapaSangre\reference\Payload\Papa Sangre.app\Papa Sangre")
data = open(PATH, 'rb').read()

# ---------------- load commands ----------------
ncmds = struct.unpack('<I', data[16:20])[0]
sections = []
symtab = None
dysymtab = None
off = 32
for _ in range(ncmds):
    cmd, cmdsize = struct.unpack('<II', data[off:off + 8])
    if cmd == 0x19:  # LC_SEGMENT_64
        nsects = struct.unpack('<I', data[off + 64:off + 68])[0]
        so = off + 72
        for _s in range(nsects):
            sname = data[so:so + 16].rstrip(b'\0').decode()
            sgname = data[so + 16:so + 32].rstrip(b'\0').decode()
            addr, size = struct.unpack('<QQ', data[so + 32:so + 48])
            soff = struct.unpack('<I', data[so + 48:so + 52])[0]
            flags = struct.unpack('<I', data[so + 56:so + 60])[0]
            r1 = struct.unpack('<I', data[so + 60:so + 64])[0]
            sections.append(dict(seg=sgname, name=sname, addr=addr, size=size,
                                 off=soff, flags=flags, r1=r1))
            so += 80
    elif cmd == 0x02:
        symtab = struct.unpack('<IIII', data[off + 8:off + 24])
    elif cmd == 0x0b:
        dysymtab = struct.unpack('<' + 'I' * 18, data[off + 8:off + 80])
    off += cmdsize


def sec(n):
    for s in sections:
        if s['name'] == n:
            return s
    return None


def v2f(vm):
    for s in sections:
        if s['addr'] <= vm < s['addr'] + s['size']:
            if s['name'] in ('__bss', '__common'):
                return None
            return s['off'] + (vm - s['addr'])
    return None


def rd(vm, n):
    o = v2f(vm)
    return None if o is None else data[o:o + n]


def u64(vm):
    b = rd(vm, 8)
    return struct.unpack('<Q', b)[0] if b and len(b) == 8 else None


def u32(vm):
    b = rd(vm, 4)
    return struct.unpack('<I', b)[0] if b and len(b) == 4 else None


def cstr(vm):
    if not vm:
        return None
    o = v2f(vm)
    if o is None:
        return None
    try:
        e = data.index(b'\0', o)
    except ValueError:
        return None
    s = data[o:e]
    if len(s) > 400:
        return None
    try:
        return s.decode('utf-8')
    except Exception:
        return None


# ---------------- symbols ----------------
symoff, nsyms, stroff, strsize = symtab
symnames = {}
symaddr = {}
for i in range(nsyms):
    p = symoff + i * 16
    n_strx, n_type, n_sect, n_desc = struct.unpack('<IBBH', data[p:p + 8])
    n_value = struct.unpack('<Q', data[p + 8:p + 16])[0]
    e = data.index(b'\0', stroff + n_strx)
    nm = data[stroff + n_strx:e].decode('utf-8', 'replace')
    symnames[i] = nm
    if n_value and (n_type & 0x0e) == 0x0e:
        symaddr.setdefault(n_value, nm)

indirectoff, nindirect = dysymtab[12], dysymtab[13]


def indirect(i):
    idx = struct.unpack('<I', data[indirectoff + i * 4:indirectoff + i * 4 + 4])[0]
    return symnames.get(idx, '?')


stubmap = {}
for s in sections:
    if s['name'] in ('__stubs', '__la_symbol_ptr', '__got', '__nl_symbol_ptr'):
        esz = 12 if s['name'] == '__stubs' else 8
        for i in range(s['size'] // esz):
            stubmap[s['addr'] + i * esz] = indirect(s['r1'] + i)

# ---------------- CFStrings ----------------
cfmap = {}
_cfs = sec('__cfstring')
if _cfs:
    for i in range(_cfs['size'] // 32):
        a = _cfs['addr'] + i * 32
        cfmap[a] = cstr(u64(a + 16))


# ---------------- objc imp map ----------------
def build_imp_map():
    m = {}
    cl = sec('__objc_classlist')

    def pm(vm, cname, kind):
        if not vm:
            return
        entsize = u32(vm)
        count = u32(vm + 4)
        esz = entsize & 0xffff
        p = vm + 8
        for _ in range(count):
            if entsize & 0x80000000:
                no = struct.unpack('<i', rd(p, 4))[0]
                io = struct.unpack('<i', rd(p + 8, 4))[0]
                selp = u64(p + no)
                sel = cstr(selp)
                imp = p + 8 + io
            else:
                sel = cstr(u64(p))
                imp = u64(p + 16)
            m[imp] = "%s[%s %s]" % (kind, cname, sel)
            p += esz

    for i in range(cl['size'] // 8):
        cv = u64(cl['addr'] + i * 8)
        ro = u64(cv + 32) & ~3
        name = cstr(u64(ro + 24))
        pm(u64(ro + 32), name, '-')
        isa = u64(cv)
        mro = u64(isa + 32) & ~3
        pm(u64(mro + 32), name, '+')
    return m


IMPMAP = build_imp_map()


def build_ivar_map():
    """address-of-ivar-offset-global -> 'Class.ivar (=offset)'"""
    m = {}
    cl = sec('__objc_classlist')
    for i in range(cl['size'] // 8):
        cv = u64(cl['addr'] + i * 8)
        ro = u64(cv + 32) & ~3
        cname = cstr(u64(ro + 24))
        iv = u64(ro + 48)
        if not iv:
            continue
        entsize = u32(iv)
        count = u32(iv + 4)
        p = iv + 8
        for _ in range(count):
            offp = u64(p)
            nm = cstr(u64(p + 8))
            if offp:
                m[offp] = '%s.%s=%d' % (cname, nm, u32(offp))
            p += entsize
    return m


IVARMAP = build_ivar_map()

md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md.detail = True

SELREFS = sec('__objc_selrefs')
CLSREFS = sec('__objc_classrefs')


def find_imp(pattern):
    return sorted([(a, n) for a, n in IMPMAP.items() if re.search(pattern, n)],
                  key=lambda x: x[1])


def disas(vm, maxins=6000):
    o = v2f(vm)
    cands = [a for a in IMPMAP if a > vm]
    end = min(cands) if cands else vm + 0x2000
    size = min(end - vm, maxins * 4)
    code = data[o:o + size]
    regs = {}
    lines = []
    for ins in md.disasm(code, vm):
        cmt = ''
        mn = ins.mnemonic
        try:
            ops = ins.operands
            if mn == 'adrp':
                regs[ins.reg_name(ops[0].reg)] = ('page', ops[1].imm)
            elif mn == 'add' and len(ops) == 3 and ops[2].type == ARM64_OP_IMM:
                src = ins.reg_name(ops[1].reg)
                dst = ins.reg_name(ops[0].reg)
                if src in regs and regs[src][0] == 'page':
                    a = regs[src][1] + ops[2].imm
                    regs[dst] = ('addr', a)
                    if a in cfmap:
                        cmt = ' ; @"%s"' % cfmap[a]
                    else:
                        s = cstr(a)
                        cmt = ' ; "%s"' % s if s else ' ; 0x%x' % a
                else:
                    regs.pop(dst, None)
            elif mn in ('ldr', 'ldrsw') and ops[1].type == ARM64_OP_MEM:
                base = ins.reg_name(ops[1].mem.base)
                dst = ins.reg_name(ops[0].reg)
                disp = ops[1].mem.disp
                if base in regs and regs[base][0] == 'page':
                    a = regs[base][1] + disp
                    v = u64(a)
                    regs[dst] = ('addr', v)
                    if a in IVARMAP:
                        cmt = ' ; IVAR %s' % IVARMAP[a]
                    elif SELREFS and SELREFS['addr'] <= a < SELREFS['addr'] + SELREFS['size']:
                        cmt = ' ; SEL "%s"' % cstr(v)
                    elif CLSREFS and CLSREFS['addr'] <= a < CLSREFS['addr'] + CLSREFS['size']:
                        ro = (u64(v + 32) & ~3) if v else 0
                        cmt = ' ; CLASS %s' % (cstr(u64(ro + 24)) if ro else '?')
                    elif a in stubmap:
                        cmt = ' ; %s' % stubmap[a]
                    elif v in cfmap:
                        cmt = ' ; @"%s"' % cfmap[v]
                    else:
                        s = cstr(v) if v else None
                        cmt = ' ; [0x%x]=0x%x%s' % (a, v or 0, (' "%s"' % s) if s else '')
                else:
                    regs.pop(dst, None)
            elif mn == 'ldr' and ops[1].type == ARM64_OP_IMM:
                a = ops[1].imm
                dst = ins.reg_name(ops[0].reg)
                if dst.startswith('s'):
                    b = rd(a, 4)
                    cmt = ' ; float %g' % struct.unpack('<f', b)[0] if b else ''
                elif dst.startswith('d'):
                    b = rd(a, 8)
                    cmt = ' ; double %g' % struct.unpack('<d', b)[0] if b else ''
                else:
                    cmt = ' ; 0x%x' % (u64(a) or 0)
            elif mn == 'fmov' and len(ops) > 1 and ops[1].type == ARM64_OP_FP:
                cmt = ' ; #%g' % ops[1].fp
            elif mn in ('bl', 'b') and ops[0].type == ARM64_OP_IMM:
                t = ops[0].imm
                if t in stubmap:
                    cmt = ' ; -> %s' % stubmap[t]
                elif t in IMPMAP:
                    cmt = ' ; -> %s' % IMPMAP[t]
                elif t in symaddr:
                    cmt = ' ; -> %s' % symaddr[t]
        except Exception:
            pass
        lines.append('0x%08x  %-8s %-46s%s' % (ins.address, mn, ins.op_str, cmt))
    return '\n'.join(lines)


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == 'list':
        for a, n in find_imp(sys.argv[2]):
            print('0x%x %s' % (a, n))
    elif len(sys.argv) > 2 and sys.argv[1] == 'at':
        print(disas(int(sys.argv[2], 16)))
    else:
        for a, n in find_imp(sys.argv[1]):
            print('\n===== %s  (0x%x) =====' % (n, a))
            print(disas(a))
