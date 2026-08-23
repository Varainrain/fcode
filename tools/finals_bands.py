"""finals_bands — report lab_finals results BY CORE-DISTANCE BAND.

A single pooled win rate over maps_finals/ is misleading: the pool spans
core distance 8 to 52, and bots in this family behave completely differently
across that range (the spear and the hybrid's spear mode want a long march;
the economy line wants a short one). Reporting one number is how the first
draft of the harness manufactured a 57% "finals promote" for hybrid7 that
turned out to be map-pool bias. Bands, always.

    python finals_bands.py [challenger ...]
"""
import collections
import csv
import glob
import os
import sys

sys.path.insert(0, '.')
from replay_stats import walk, pos_of

BANDS = ('short d8-16', 'mid d24-36', 'long d40-52')


def band_of(d):
    if d <= 16:
        return BANDS[0]
    return BANDS[1] if d <= 36 else BANDS[2]


def map_distances():
    out = {}
    for p in glob.glob(os.path.join('maps_finals', '*.map26')):
        top = walk(open(p, 'rb').read())
        pts = []
        for cm in (top.get((4, 'm')) or []):
            c = walk(cm) or {}
            if (3, 'm') in c:
                pts.append(pos_of(c[(3, 'm')][0]))
        if len(pts) == 2:
            name = os.path.splitext(os.path.basename(p))[0]
            out[name] = abs(pts[0][0] - pts[1][0]) + abs(pts[0][1] - pts[1][1])
    return out


def main():
    want = set(sys.argv[1:])
    dist = map_distances()
    rows = list(csv.DictReader(open('lab_finals.csv', encoding='utf-8',
                                    errors='replace')))
    per = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for r in rows:
        d = dist.get(r['map'])
        if d is None:
            continue
        key = (r['challenger'], r['champion'])
        if want and r['challenger'] not in want:
            continue
        cell = per[key][band_of(d)]
        cell[1] += 1
        if r['winner'] == r['challenger']:
            cell[0] += 1
    print('VERSATILITY BY CORE-DISTANCE BAND (challenger win% vs champion)')
    print(f"{'matchup':<22}" + ''.join(f'{b:>15}' for b in BANDS) + f"{'pooled':>10}")
    for (ch, champ), bands in sorted(per.items()):
        line = f"{ch + ' vs ' + champ:<22}"
        tw = tn = 0
        for b in BANDS:
            w, n = bands[b]
            tw += w
            tn += n
            line += f"{(str(round(100 * w / n)) + '% (' + str(n) + ')') if n else '-':>15}"
        line += f"{(str(round(100 * tw / tn)) + '%') if tn else '-':>10}"
        print(line)


main()
