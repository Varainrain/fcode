"""OFFENSE GATE REPORT — pool every gate run of a candidate and print Wilson CIs.

gate.py appends every game to gate_results.csv, so repeated runs of the same
matchup are extra samples, not separate experiments (seeds are not a control
variable: the bots' own RNG is unseeded). This pools them and prints each
candidate against the byte-identical NULL rather than against 50%.

Usage:
  python offense_gate_report.py <opponent> <null_candidate> <cand> [cand ...]
  python offense_gate_report.py OogwayAttack oa_null oa_a4 oa_a8 oa_a9
"""
import csv
import sys
from collections import defaultdict
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).parent
SINCE = "2026-08-06"          # engine 2.3.6 + synced 15-map pool


def wilson(w, n, z=1.96):
    if not n:
        return 0.0, 0.0, 0.0
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * p, 100 * max(0.0, c - half), 100 * min(1.0, c + half)


def collect(opponent, names):
    tally = defaultdict(lambda: [0, 0])       # cand -> [wins, games]
    with open(ROOT / "gate_results.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["time"] < SINCE:
                continue
            cand, opp, winner = row["candidate"], row["opponent"], row["winner"]
            # count both orientations: X vs OPP, and OPP vs X (inverted)
            if opp == opponent and cand in names:
                tally[cand][1] += 1
                tally[cand][0] += (winner == cand)
            elif cand == opponent and opp in names:
                tally[opp][1] += 1
                tally[opp][0] += (winner == opp)
    return tally


def main(opponent, null_name, cands):
    tally = collect(opponent, set(cands) | {null_name})
    nw, nn = tally[null_name]
    npct, nlo, nhi = wilson(nw, nn)
    print(f"opponent: {opponent}   (games since {SINCE}, engine 2.3.6 / 15-map pool)\n")
    print(f"{'candidate':14s} {'games':>6} {'win%':>6}  {'95% CI':>13}   verdict")
    print("-" * 62)
    print(f"{null_name + ' (NULL)':14s} {nn:6d} {npct:6.1f}  "
          f"[{nlo:5.1f}-{nhi:5.1f}]   byte-identical control")
    for c in cands:
        w, n = tally[c]
        if not n:
            print(f"{c:14s} {0:6d}      -              -   no games")
            continue
        pct, lo, hi = wilson(w, n)
        if nn:
            # separated from the null only if the CIs do not overlap
            sep = "ABOVE NULL" if lo > nhi else ("BELOW NULL" if hi < nlo else
                                                "inside null band")
        else:
            sep = "no null"
        print(f"{c:14s} {n:6d} {pct:6.1f}  [{lo:5.1f}-{hi:5.1f}]   {sep}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
