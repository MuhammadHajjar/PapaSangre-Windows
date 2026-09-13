import sys, re
data = open(sys.argv[1],'rb').read()
minlen = int(sys.argv[2]) if len(sys.argv)>2 else 4
out=[]
for m in re.finditer(rb'[\x20-\x7e]{%d,}'%minlen, data):
    out.append(m.group().decode('ascii'))
sys.stdout.write('\n'.join(out))
