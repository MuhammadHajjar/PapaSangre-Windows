import struct, sys, re

path=sys.argv[1]
data=open(path,'rb').read()

# --- parse segments/sections ---
ncmds=struct.unpack('<I',data[16:20])[0]
sections=[]
off=32
for i in range(ncmds):
    cmd,cmdsize=struct.unpack('<II',data[off:off+8])
    if cmd==0x19:
        nsects=struct.unpack('<I',data[off+64:off+68])[0]
        so=off+72
        for s in range(nsects):
            sname=data[so:so+16].rstrip(b'\0').decode()
            sgname=data[so+16:so+32].rstrip(b'\0').decode()
            addr,size=struct.unpack('<QQ',data[so+32:so+48])
            soff=struct.unpack('<I',data[so+48:so+52])[0]
            sections.append((sgname,sname,addr,size,soff))
            so+=80
    off+=cmdsize

def v2f(vmaddr):
    for sg,sn,addr,size,soff in sections:
        if addr<=vmaddr<addr+size:
            if sn=='__bss' or sn=='__common': return None
            return soff+(vmaddr-addr)
    return None

def rd(vm,n):
    o=v2f(vm)
    if o is None: return None
    return data[o:o+n]

def u64(vm):
    b=rd(vm,8)
    if b is None or len(b)<8: return 0
    return struct.unpack('<Q',b)[0]
def u32(vm):
    b=rd(vm,4)
    if b is None or len(b)<4: return 0
    return struct.unpack('<I',b)[0]

def cstr(vm):
    if not vm: return None
    o=v2f(vm)
    if o is None: return None
    e=data.index(b'\0',o)
    return data[o:e].decode('utf-8','replace')

def sect(name):
    for sg,sn,addr,size,soff in sections:
        if sn==name: return addr,size,soff
    return None

# ---- struct layouts (arm64 64-bit) ----
# class_t: isa, superclass, cache, vtable, data(class_ro_t*)
# class_ro_t: flags(u32), instanceStart(u32), instanceSize(u32), reserved(u32),
#             ivarLayout(ptr), name(ptr), baseMethods(ptr), baseProtocols(ptr),
#             ivars(ptr), weakIvarLayout(ptr), baseProperties(ptr)

def parse_methods(vm, small_ok=True):
    if not vm: return []
    entsize=u32(vm); count=u32(vm+4)
    res=[]
    flags=entsize & 0xffff0000
    esz=entsize & 0xffff
    p=vm+8
    for i in range(count):
        if entsize & 0x80000000:  # small method list, relative offsets
            nameoff=struct.unpack('<i',rd(p,4))[0]
            typesoff=struct.unpack('<i',rd(p+4,4))[0]
            impoff=struct.unpack('<i',rd(p+8,4))[0]
            selptr=u64(p+nameoff)   # points to selref -> sel string
            name=cstr(selptr)
            types=cstr(p+4+typesoff)
            imp=p+8+impoff
        else:
            name=cstr(u64(p)); types=cstr(u64(p+8)); imp=u64(p+16)
        res.append((name,types,imp))
        p+=esz
    return res

def parse_ivars(vm):
    if not vm: return []
    entsize=u32(vm); count=u32(vm+4)
    res=[];p=vm+8
    for i in range(count):
        offp=u64(p); name=cstr(u64(p+8)); types=cstr(u64(p+16))
        al=u32(p+24); sz=u32(p+28)
        offv=u32(offp) if offp else 0
        res.append((name,types,offv,sz))
        p+=entsize
    return res

def parse_props(vm):
    if not vm: return []
    entsize=u32(vm); count=u32(vm+4)
    res=[];p=vm+8
    for i in range(count):
        res.append((cstr(u64(p)),cstr(u64(p+8))))
        p+=entsize
    return res

def parse_class(clsvm, meta=False):
    isa=u64(clsvm); sup=u64(clsvm+8); ro=u64(clsvm+32)
    ro &= ~0x3   # swift flags
    flags=u32(ro); instStart=u32(ro+4); instSize=u32(ro+8)
    name=cstr(u64(ro+24))
    methods=parse_methods(u64(ro+32))
    ivars=parse_ivars(u64(ro+48))
    props=parse_props(u64(ro+64))
    return dict(name=name,isa=isa,sup=sup,instSize=instSize,methods=methods,ivars=ivars,props=props,vm=clsvm)

addr,size,soff=sect('__objc_classlist')
classes=[]
for i in range(size//8):
    cv=u64(addr+i*8)
    try:
        c=parse_class(cv)
        classes.append(c)
    except Exception as e:
        pass

# superclass name resolution
byvm={c['vm']:c for c in classes}
out=[]
filt = sys.argv[2] if len(sys.argv)>2 else None
for c in sorted(classes,key=lambda x:x['name'] or ''):
    if filt and not re.search(filt,c['name'] or '',re.I): continue
    supn = byvm[c['sup']]['name'] if c['sup'] in byvm else ('?%x'%c['sup'] if c['sup'] else 'NSObject')
    out.append('@interface %s : %s   // size=%d'%(c['name'],supn,c['instSize']))
    for n,t,o,s in c['ivars']:
        out.append('  ivar %-40s %-30s @%d (%d)'%(n,t,o,s))
    for n,t in c['props']:
        out.append('  prop %-40s %s'%(n,t))
    # class methods
    try:
        mc=parse_class(c['isa'])
        for n,t,imp in mc['methods']:
            out.append('  + %-60s %-20s imp=0x%x'%(n,t,imp))
    except Exception: pass
    for n,t,imp in c['methods']:
        out.append('  - %-60s %-20s imp=0x%x'%(n,t,imp))
    out.append('@end\n')
print('\n'.join(out))
