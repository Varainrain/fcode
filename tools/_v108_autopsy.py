"""Structure of v108's field losses on the new pool (the 849-vs-174 question).

Method: win/loss profile over every v108 scrim with a replay on disk.
Key attribution trick: core-damage ticks identify the SHOOTER by delta -
18 = sentinel (indirect), 7 = gunner, 2 = builder melee. That splits the
damage imbalance by weapon without needing shooter ids.
"""
import sys, glob, os, csv
sys.path.insert(0, '.')
import replay_stats as rs
from collections import defaultdict

# v108-pure scrim windows (local time)
WINDOWS = [("2026-08-15T14:50", "2026-08-15T18:12"),
           ("2026-08-16T13:50", "2026-08-16T14:36"),
           ("2026-08-16T16:48", "2026-08-17T23:59")]

rows = list(csv.DictReader(open('scrim_log.csv', encoding='utf-8')))
sel = {}
for r in rows:
    if any(a <= r['time'] < b for a, b in WINDOWS):
        sel[r['match_id']] = r

files = [f for f in glob.glob('prod/*.replay26')
         if os.path.basename(f).split('_game_')[0] in sel]
print(f"v108 scrim games with replays: {len(files)}")

agg = {'W': defaultdict(list), 'L': defaultdict(list)}
mapsz = {'W': defaultdict(int), 'L': defaultdict(int)}

for f in files:
    mid = os.path.basename(f).split('_game_')[0]
    rec = sel[mid]
    try:
        data = open(f, 'rb').read()
        top = rs.walk(data)
        turns = top[(3, 'm')]
    except Exception:
        continue
    mp = rs.walk(top[(1, 'm')][0]) or {}
    W, H = mp[(1, 'v')][0], mp[(2, 'v')][0]
    ent = {}
    cores = {}
    for cm in mp.get((4, 'm'), []):
        c = rs.walk(cm) or {}
        t_ = c.get((2, 'v'), [0])[0]
        cores[t_] = rs.pos_of(c[(3, 'm')][0])
        ent[c.get((1, 'v'), [None])[0]] = (t_, 'core')
    counts = defaultdict(lambda: defaultdict(int))
    dmg_by = defaultdict(lambda: defaultdict(int))   # victimteam -> weapon -> dmg
    firstHit = {}
    throws = defaultdict(int)
    pos = {}
    snap = {}
    for r, tm in enumerate(turns):
        t = rs.walk(tm)
        if not t:
            continue
        for e in t.get((1, 'm'), []):
            se = rs.walk(e)
            if not se:
                continue
            if (1, 'm') in se:
                outer = rs.walk(se[(1, 'm')][0]) or {}
                c = rs.walk(outer[(1, 'm')][0]) if (1, 'm') in outer else outer
                c = c or {}
                eid = c.get((1, 'v'), [None])[0]
                team = c.get((2, 'v'), [0])[0]
                ty = '?'
                p = None
                for (fn, tk) in c:
                    if tk == 'm' and fn >= 10:
                        ty = rs.PAYLOAD_TYPE.get(fn, '?')
                        sub = rs.walk(c[(fn, 'm')][0]) or {}
                        if (1, 'm') in sub:
                            p = rs.pos_of(sub[(1, 'm')][0])
                ent[eid] = (team, ty)
                counts[team][ty] += 1
                if p:
                    pos[eid] = p
            elif (2, 'm') in se:
                mv = rs.walk(se[(2, 'm')][0]) or {}
                eid = mv.get((1, 'v'), [None])[0]
                pm = rs.walk(mv[(2, 'm')][0]) or {}
                np_ = (pm.get((1, 'v'), [0])[0], pm.get((2, 'v'), [0])[0])
                if eid in pos and eid in ent:
                    if max(abs(np_[0] - pos[eid][0]), abs(np_[1] - pos[eid][1])) > 1:
                        throws[ent[eid][0]] += 1
                pos[eid] = np_
            elif (5, 'm') in se:
                dm = rs.walk(se[(5, 'm')][0]) or {}
                eid = dm.get((1, 'v'), [None])[0]
                d = rs.signed(dm.get((2, 'v'), [0])[0])
                if eid in ent and ent[eid][1] == 'core' and d < 0:
                    v = ent[eid][0]
                    w = {18: 'sentinel', 7: 'gunner', 2: 'melee'}.get(-d, f'x{-d}')
                    dmg_by[v][w] += -d
                    if v not in firstHit:
                        firstHit[v] = r
        if r in (100, 200):
            snap[r] = {tm2: (counts[tm2].get('gunner', 0) + counts[tm2].get('sentinel', 0))
                       for tm2 in (0, 1)}
    tot = {v: sum(dmg_by[v].values()) for v in (0, 1)}
    us = max(tot, key=tot.get) if rec['result'] == 'L' else min(tot, key=tot.get)
    them = 1 - us
    k = rec['result']
    mapsz[k][f"{W}x{H}"] += 1
    a = agg[k]
    a['turns'].append(len(turns))
    a['dmg_taken'].append(tot[us])
    a['dmg_dealt'].append(tot[them])
    for w in ('sentinel', 'gunner', 'melee'):
        a['taken_' + w].append(dmg_by[us].get(w, 0))
        a['dealt_' + w].append(dmg_by[them].get(w, 0))
    a['firstHit_on_us'].append(firstHit.get(us, 999))
    a['firstHit_on_them'].append(firstHit.get(them, 999))
    a['their_throws'].append(throws[them])
    a['our_throws'].append(throws[us])
    for ty in ('sentinel', 'gunner', 'launcher', 'harvester', 'conveyor', 'barrier'):
        a['our_' + ty].append(counts[us].get(ty, 0))
        a['their_' + ty].append(counts[them].get(ty, 0))
    if 100 in snap:
        a['our_turrets_t100'].append(snap[100][us])
        a['their_turrets_t100'].append(snap[100][them])
    if 200 in snap:
        a['our_turrets_t200'].append(snap[200][us])
        a['their_turrets_t200'].append(snap[200][them])


def avg(v):
    return sum(v) / len(v) if v else 0


nW, nL = len(agg['W']['turns']), len(agg['L']['turns'])
print(f"\n=== v108 vs top-5: {nW} wins, {nL} losses ===")
keys = ['turns', 'dmg_taken', 'dmg_dealt',
        'taken_sentinel', 'taken_gunner', 'taken_melee',
        'dealt_sentinel', 'dealt_gunner', 'dealt_melee',
        'firstHit_on_us', 'firstHit_on_them',
        'their_throws', 'our_throws',
        'our_turrets_t100', 'their_turrets_t100',
        'our_turrets_t200', 'their_turrets_t200',
        'our_sentinel', 'their_sentinel', 'our_gunner', 'their_gunner',
        'our_launcher', 'their_launcher',
        'our_harvester', 'their_harvester', 'our_conveyor', 'their_conveyor',
        'our_barrier', 'their_barrier']
print(f"{'metric':20} {'WIN avg':>9} {'LOSS avg':>9}")
for k in keys:
    print(f"{k:20} {avg(agg['W'][k]):9.1f} {avg(agg['L'][k]):9.1f}")
print("\nmap sizes: wins", dict(mapsz['W']), " losses", dict(mapsz['L']))
