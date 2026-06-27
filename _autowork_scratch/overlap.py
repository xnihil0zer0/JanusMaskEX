import json, datetime, time
def to_epoch(ts):
    if isinstance(ts,(int,float)): return float(ts)
    try: return datetime.datetime.fromisoformat(str(ts).replace('Z','+00:00')).timestamp()
    except Exception: return None
events=[]
with open('state/impl_progress.jsonl') as f:
    for i,line in enumerate(f):
        if i < 107399: continue
        try: r=json.loads(line)
        except Exception: continue
        ev=r.get('event'); tid=r.get('task_id'); t=to_epoch(r.get('ts'))
        if ev in ('worker_start','worker_exit','task_terminal','auto_commit') and tid and t:
            events.append((t,ev,tid))
events.sort()
intervals=[]; open_start={}
for t,ev,tid in events:
    if ev=='worker_start': open_start.setdefault(tid,[]).append(t)
    elif ev in ('worker_exit','task_terminal'):
        if open_start.get(tid): intervals.append((open_start[tid].pop(0), t, tid))
now=time.time()
for tid,starts in open_start.items():
    for s in starts: intervals.append((s, now, tid+'(OPEN)'))
intervals.sort()
base=min(i[0] for i in intervals) if intervals else 0
print('worker intervals (sec since first worker_start):')
for s,e,tid in intervals:
    print('  [%7.1f .. %7.1f]  %s' % (s-base, e-base, tid))
ov=[]
for a in range(len(intervals)):
    for b in range(a+1,len(intervals)):
        s1,e1,t1=intervals[a]; s2,e2,t2=intervals[b]
        if t1.replace('(OPEN)','')==t2.replace('(OPEN)',''): continue
        lo=max(s1,s2); hi=min(e1,e2)
        if hi>lo: ov.append((t1,t2,round(hi-lo,1)))
print()
if ov:
    print('PARALLEL OPERATION CONFIRMED — distinct tasks overlapped in time:')
    for t1,t2,d in ov: print('  %s  ||  %s   overlap=%ss' % (t1,t2,d))
else:
    print('NO distinct-task overlap yet (sequential so far).')
