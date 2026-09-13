import struct, sys
f=open(sys.argv[1],'rb'); data=f.read()
magic=struct.unpack('<I',data[:4])[0]
print('magic %08x'%magic)
assert magic==0xfeedfacf
cputype,cpusub,filetype,ncmds,sizeofcmds,flags,res = struct.unpack('<iiIIIII', data[4:32])
print('cputype',cputype,'ncmds',ncmds)
off=32
segs=[]
for i in range(ncmds):
    cmd,cmdsize=struct.unpack('<II',data[off:off+8])
    if cmd==0x19: # LC_SEGMENT_64
        name=data[off+8:off+24].rstrip(b'\0').decode()
        vmaddr,vmsize,fileoff,filesize=struct.unpack('<QQQQ',data[off+24:off+56])
        nsects=struct.unpack('<I',data[off+64:off+68])[0]
        print('SEG %-12s vm=%016x size=%08x off=%08x nsects=%d'%(name,vmaddr,vmsize,fileoff,nsects))
        so=off+72
        for s in range(nsects):
            sname=data[so:so+16].rstrip(b'\0').decode()
            sgname=data[so+16:so+32].rstrip(b'\0').decode()
            addr,size=struct.unpack('<QQ',data[so+32:so+48])
            soff=struct.unpack('<I',data[so+48:so+52])[0]
            print('   %-20s addr=%016x size=%08x off=%08x'%(sname,addr,size,soff))
            segs.append((sgname,sname,addr,size,soff))
            so+=80
    elif cmd==0x0c or cmd==0x18: # LOAD_DYLIB
        pass
    elif cmd==0x2c: # LC_ENCRYPTION_INFO_64
        cryptoff,cryptsize,cryptid=struct.unpack('<III',data[off+8:off+20])
        print('ENCRYPTION_INFO cryptid=%d off=%d size=%d'%(cryptid,cryptoff,cryptsize))
    off+=cmdsize
print("=== dylibs ===")
off=32
for i in range(ncmds):
    cmd,cmdsize=struct.unpack('<II',data[off:off+8])
    if cmd in (0x0c,0x18,0x8000001f,0x22,0x23):
        o=struct.unpack('<I',data[off+8:off+12])[0]
        s=data[off+o:off+cmdsize].split(b'\0')[0].decode()
        print('  ',s)
    off+=cmdsize
