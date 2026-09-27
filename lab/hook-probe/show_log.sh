#!/bin/bash
# Summarise the probe log: event, tool name, count.
L="$HOME/bob-hook-probe-log.tsv"
[ -f "$L" ] || { echo "no log yet: $L"; exit 1; }
python3 - "$L" <<'P'
import sys,json,collections
c=collections.Counter(); order=[]
for line in open(sys.argv[1]):
    p=line.rstrip('\n').split('\t')
    if len(p)>=4:
        try: j=json.loads(p[3]); tool=j.get('tool') or '-'; ev=j.get('event') or p[1]
        except Exception: tool='?'; ev=p[1]
        key=(p[1],ev,tool)
    else: key=tuple(p[1:3])
    c[key]+=1; order.append((p[0],)+key)
for k,v in c.items(): print(v,'x',k)
print('--- sequence ---')
for o in order: print(*o)
P
