"""Core damage vs core healing per side, straight from a local .replay26.

The ladder loss signature (2026-08-01) is siege damage that gets fully healed:
  python heal_audit.py replays/*.replay26
prints, per side, total core damage taken and how much of it was healed back.
A heal fraction near 1.0 means our siege converted to nothing. Works offline -
unlike live_replay_audit.py it needs no API metadata."""
import sys
sys.path.insert(0,"/mnt/c/Users/subodh/Downloads/fcode")
from replay_stats import walk, pos_of, signed

def analyse(path):
    top = walk(open(path,"rb").read())
    ent = {}
    mp = walk(top[(1,'m')][0]) or {}
    for cm in mp.get((4,'m'), []):
        c = walk(cm) or {}
        cid = c.get((1,'v'),[None])[0]
        if cid is not None:
            ent[cid] = {"team": c.get((2,'v'),[0])[0], "type":"core"}
    dmg = {0:0, 1:0}; heal = {0:0, 1:0}; guns = {0:0, 1:0}
    turns = top[(3,'m')]
    for tm in turns:
        t = walk(tm) or {}
        for e in t.get((1,'m'), []):
            se = walk(e) or {}
            if (1,'m') in se:
                outer = walk(se[(1,'m')][0]) or {}
                c = walk(outer[(1,'m')][0]) if (1,'m') in outer else outer
                c = c or {}
                cid = c.get((1,'v'),[None])[0]
                team = c.get((2,'v'),[0])[0]
                if cid is not None and cid not in ent:
                    ent[cid] = {"team": team, "type":"unit"}
                    if any(k[0]==21 for k in c):   # gunner payload field
                        guns[team] = guns.get(team,0)+1
            elif (5,'m') in se:
                d = walk(se[(5,'m')][0]) or {}
                tid = d.get((1,'v'),[None])[0]
                delta = signed(d.get((2,'v'),[0])[0])
                info = ent.get(tid)
                if info and info["type"]=="core":
                    if delta < 0: dmg[info["team"]] += -delta
                    else:         heal[info["team"]] += delta
    return dmg, heal, guns, len(turns)

for p in sys.argv[1:]:
    dmg, heal, guns, n = analyse(p)
    print(f"{p.split('/')[-1][:28]:30s} t{n:<5d}", end="")
    for team in (0,1):
        d,h = dmg[team], heal[team]
        frac = h/d if d else 0
        print(f" | core{('A','B')[team]} took {d:5d} healed {h:5d} ({frac*100:3.0f}%)", end="")
    print()
