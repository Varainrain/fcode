"""LAB_FINALS — the same runner, pointed at maps_finals/.

The Stockholm finals use maps we have never seen, and every gate in
our history is measured on the 15-map league pool - a bot can be tuned
to that pool's quirks without anyone noticing. These 15 maps span core
distances 24-52, sizes 18x18 to 34x16, and 0-172 walls, so a champion
that only wins at one distance or only with ore at the door shows it
HERE instead of in the finals. Results go to lab_finals.csv; maps stay
out of maps/ so the ship gate stays league-pure.

Original header follows.

"""
"""LAB — automated experiment runner (our answer to Cookie's dashboard).

Champion-vs-challenger batches across maps x seeds x both sides, in parallel,
tracking WIN RATE and CORE-KILL RATE, appending every game to lab_finals.csv,
and printing a PROMOTION verdict.

Usage:
  python lab.py <challenger> <champion> [seeds=2] [fast]
  python lab.py ic3d champion 2
  python lab.py mut_x champion 1 fast     # quick 6-map screen

Promotion rule: challenger promotes if win rate >= 55% (clear edge, not noise).
"""
import concurrent.futures as cf
import csv
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

CH = sys.argv[1] if len(sys.argv) > 1 else "ic3d"
BASE = sys.argv[2] if len(sys.argv) > 2 else "champion"
SEEDS = int(sys.argv[3]) if len(sys.argv) > 3 else 2
FAST = "fast" in sys.argv[4:]

ALL = sorted(p.stem for p in Path("maps_finals").glob("*.map26"))
MAPS = ["open_close", "open_far", "onegate", "corridors", "barrenfin", "richfield"] if FAST else ALL
WIN = re.compile(r"Winner:\s+(\S+)\s+\((.*?),\s*turn\s*(\d+)\)")


def game(first, second, m, seed):
    out = subprocess.run(
        ["fcode", "run", first, second, f"maps_finals/{m}.map26", "--seed", str(seed), "--tle", "10"],
        capture_output=True, encoding="utf-8", errors="replace").stdout or ""
    mo = WIN.search(out)
    if not mo:
        return m, first, second, "draw", "unknown", 0
    return m, first, second, mo.group(1), mo.group(2), int(mo.group(3))


jobs = [(a, b, m, s) for m in MAPS for s in range(1, SEEDS + 1)
        for a, b in ((CH, BASE), (BASE, CH))]
rows, w, kills, kills_against = [], 0, 0, 0
# 6, not 12: heavy bots (khaos) at 12 parallel engines exhaust Windows commit
# memory (WinError 1455 + phantom draws) — same cap as the team gate.py
with cf.ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 4)) as ex:
    for m, first, second, winner, cond, turn in ex.map(lambda j: game(*j), jobs):
        rows.append([dt.datetime.now().isoformat(timespec="seconds"),
                     CH, BASE, m, first, winner, cond, turn])
        if winner == CH:
            w += 1
            if "destroyed" in cond.lower():
                kills += 1
        elif winner == BASE and "destroyed" in cond.lower():
            kills_against += 1

new = not Path("lab_finals.csv").exists()
with open("lab_finals.csv", "a", newline="", encoding="utf-8") as f:
    cw = csv.writer(f)
    if new:
        cw.writerow(["time", "challenger", "champion", "map", "first_player",
                     "winner", "condition", "turns"])
    cw.writerows(rows)

n = len(jobs)
pct = 100 * w / n
print(f"\nLAB  {CH} vs {BASE}  |  {n} games  |  {CH} wins {w} ({pct:.0f}%)  "
      f"|  kills by {CH}: {kills}  |  kills against: {kills_against}")
per = {}
for r in rows:
    per.setdefault(r[3], [0, 0])
    per[r[3]][1] += 1
    if r[5] == CH:
        per[r[3]][0] += 1
for m in MAPS:
    a, t = per.get(m, [0, 0])
    print(f"  {m:12s} {a}/{t}")
print("\nVERDICT:", "PROMOTE" if pct >= 55 else ("NEUTRAL" if pct >= 45 else "REJECT"))
