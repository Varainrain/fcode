"""What separates the games we WIN from the ones we lose, vs one opponent?

Aggregates every captured game of a matchup and prints the average profile of
our wins next to our losses. With ~50 matches per opponent this is a real
sample, not a single-replay anecdote.
"""
import sys, glob, os, csv
sys.path.insert(0, '.')
import replay_stats as rs
from collections import defaultdict

OPP = sys.argv[1]

rows = list(csv.DictReader(open('scrim_log.csv', encoding='utf-8')))
byid = {r['match_id']: r for r in rows if r['opponent'] == OPP}


def profile(path):
    data = open(path, 'rb').read()
    top = rs.walk(data)
    turns = top[(3, 'm')]
    cores, ent = {}, {}
    mp = rs.walk(top[(1, 'm')][0]) or {}
    for cm in mp.get((4, 'm'), []):
        c = rs.walk(cm) or {}
        t_ = c.get((2, 'v'), [0])[0]
        cores[t_] = rs.pos_of(c[(3, 'm')][0]) if (3, 'm') in c else None
        ent[c.get((1, 'v'), [None])[0]] = (t_, 'core')
    # our side: the replay does not name teams, so infer from the match record
    # via core survival is unreliable -> caller passes side
    return top, turns, cores, ent


def analyse(path, ere):
    top, turns, cores, ent = profile(path)
    cnt = defaultdict(lambda: defaultdict(int))
    dealtTo = defaultdict(int)
    heal = defaultdict(int)
    dmg = defaultdict(int)
    firstHit = {}
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
                for (fn, tk) in c:
                    if tk == 'm' and fn >= 10:
                        ty = rs.PAYLOAD_TYPE.get(fn, '?')
                ent[eid] = (team, ty)
                cnt[team][ty] += 1
            elif (5, 'm') in se:
                dm = rs.walk(se[(5, 'm')][0]) or {}
                eid = dm.get((1, 'v'), [None])[0]
                delta = rs.signed(dm.get((2, 'v'), [0])[0])
                if eid not in ent:
                    continue
                vt, vty = ent[eid]
                if delta < 0:
                    if vt != ere:
                        dealtTo[vty] += -delta
                    if vty == 'core':
                        dmg[1 - vt] += -delta
                        if (1 - vt) not in firstHit:
                            firstHit[1 - vt] = r
                elif vty == 'core':
                    heal[vt] += delta
    return dict(turns=len(turns), us=cnt[ere], them=cnt[1 - ere],
                dealtTo=dealtTo, ourDmg=dmg[ere], theirDmg=dmg[1 - ere],
                ourHeal=heal[ere], theirHeal=heal[1 - ere],
                firstHit=firstHit.get(ere))


agg = {'W': defaultdict(list), 'L': defaultdict(list)}
n = {'W': 0, 'L': 0}
for f in sorted(glob.glob('prod/*.replay26')):
    mid = os.path.basename(f).split('_game_')[0]
    rec = byid.get(mid)
    if not rec:
        continue
    # our side: try team 0, and check the core-damage story matches the result
    for ere in (0, 1):
        a = analyse(f, ere)
        # our core survived if they dealt less than ~500 total
        weWon = a['theirDmg'] < 500 <= a['ourDmg'] + 1
        if weWon == (rec['result'] == 'W'):
            break
    k = rec['result']
    n[k] += 1
    agg[k]['turns'].append(a['turns'])
    agg[k]['ourDmg'].append(a['ourDmg'])
    agg[k]['theirDmg'].append(a['theirDmg'])
    agg[k]['ourHeal'].append(a['ourHeal'])
    agg[k]['theirHeal'].append(a['theirHeal'])
    for key in ('harvester', 'conveyor', 'gunner', 'sentinel', 'barrier', 'builder'):
        agg[k]['our_' + key].append(a['us'].get(key, 0))
        agg[k]['their_' + key].append(a['them'].get(key, 0))
    agg[k]['dmg_core'].append(a['dealtTo'].get('core', 0))
    agg[k]['dmg_barrier'].append(a['dealtTo'].get('barrier', 0))
    agg[k]['dmg_eco'].append(a['dealtTo'].get('harvester', 0) + a['dealtTo'].get('conveyor', 0))
    agg[k]['firstHit'].append(a['firstHit'] if a['firstHit'] is not None else 999)


def avg(v):
    return sum(v) / len(v) if v else 0


print(f"=== vs {OPP}: {n['W']} games we WON, {n['L']} we lost ===")
keys = ['turns', 'ourDmg', 'theirDmg', 'ourHeal', 'theirHeal', 'firstHit',
        'dmg_core', 'dmg_barrier', 'dmg_eco',
        'our_harvester', 'their_harvester', 'our_conveyor', 'their_conveyor',
        'our_gunner', 'their_gunner', 'our_sentinel', 'their_sentinel',
        'our_barrier', 'their_barrier', 'our_builder']
print(f"{'metric':18} {'WIN avg':>9} {'LOSS avg':>9}   delta")
for k in keys:
    w, l = avg(agg['W'][k]), avg(agg['L'][k])
    flag = ''
    if l and abs(w - l) / max(abs(l), 1) > 0.4:
        flag = '  <<<'
    print(f"{k:18} {w:9.1f} {l:9.1f}   {w-l:+8.1f}{flag}")
