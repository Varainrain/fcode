"""Attribute each building to the builder that was standing next to it.

The replay records a create event with the new entity's position but not who
made it, so we track every builder's position per turn and attribute a build to
an adjacent friendly builder. That yields a per-builder timeline: does one unit
farm AND deliver, or do they specialise?
"""
import sys, collections
sys.path.insert(0, "/mnt/c/Users/subodh/Downloads/fcode")
from replay_stats import walk, pos_of, PAYLOAD_TYPE

def trace(path, team_wanted):
    top = walk(open(path, "rb").read())
    turns = top[(3, 'm')]
    pos = {}                       # entity id -> current position
    team = {}                      # entity id -> team
    kind = {}
    timeline = collections.defaultdict(list)
    for r, tm in enumerate(turns):
        t = walk(tm) or {}
        builds = []
        for e in t.get((1, 'm'), []):
            se = walk(e) or {}
            if (1, 'm') in se:                       # create
                outer = walk(se[(1, 'm')][0]) or {}
                c = walk(outer[(1, 'm')][0]) if (1, 'm') in outer else outer
                c = c or {}
                cid = c.get((1, 'v'), [None])[0]
                tm_ = c.get((2, 'v'), [0])[0]
                p = pos_of(c[(3, 'm')][0]) if (3, 'm') in c else (0, 0)
                k = None
                for key in c:
                    if key[0] in PAYLOAD_TYPE:
                        k = PAYLOAD_TYPE[key[0]]
                if cid is not None:
                    pos[cid], team[cid], kind[cid] = p, tm_, k
                if k and k != "builder" and tm_ == team_wanted:
                    builds.append((p, k))
            elif (2, 'm') in se:                     # move
                m = walk(se[(2, 'm')][0]) or {}
                mid = m.get((1, 'v'), [None])[0]
                if mid is not None and (2, 'm') in m:
                    pos[mid] = pos_of(m[(2, 'm')][0])
        for p, k in builds:
            best = None
            for eid, ep in pos.items():
                if team.get(eid) != team_wanted or kind.get(eid) != "builder":
                    continue
                if abs(ep[0] - p[0]) + abs(ep[1] - p[1]) <= 1:
                    best = eid
                    break
            if best is not None:
                timeline[best].append((r, k))
    return timeline

tl = trace(sys.argv[1], int(sys.argv[2]))
rows = sorted(tl.items(), key=lambda kv: -len(kv[1]))[:6]
print(f"{'builder':>8s}  {'builds':>6s}  timeline (turn:what)")
for eid, evs in rows:
    kinds = collections.Counter(k for _, k in evs)
    s = " ".join(f"{r}:{k[:4]}" for r, k in evs[:16])
    print(f"{eid:8d}  {len(evs):6d}  {s}")
    print(f"{'':8s}  {'':6s}  mix: {dict(kinds)}")
