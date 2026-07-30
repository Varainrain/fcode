"""BOT BATTLE - head-to-head comparison between any two bots.

Runs botA vs botB across every map, multiple seeds, both sides.
Prints per-map results and overall win rates.

Usage:
  python botBattle.py <botA> <botB> [seeds=4]
  python botBattle.py <botA> <botB> <start_seed> <end_seed>

  python botBattle.py OogwayWIP khaos
  python botBattle.py OogwayWIP khaos 2
  python botBattle.py OogwayWIP khaos 10 12
"""
import concurrent.futures as cf
import os
import re
import shutil
import sys
from pathlib import Path
from subprocess import run

ROOT = Path(__file__).parent

args = sys.argv[1:]
if len(args) < 2:
    sys.exit(__doc__)
BOT_A = args[0]
BOT_B = args[1]
if len(args) >= 4:
    START_SEED, END_SEED = int(args[2]), int(args[3])
elif len(args) == 3:
    START_SEED, END_SEED = 1, int(args[2])
else:
    START_SEED, END_SEED = 1, 4

if BOT_A == BOT_B:
    sys.exit("both bots are the same name")
if shutil.which("fcode") is None:
    sys.exit("fcode CLI not found on PATH")
for bot in (BOT_A, BOT_B):
    if not (ROOT / "bots" / bot / "main.py").is_file():
        sys.exit(f"no bot at bots/{bot}/main.py")

ALL = sorted(p.stem for p in (ROOT / "maps").glob("*.map26"))
if not ALL:
    sys.exit("no maps in maps/")
WIN = re.compile(r"Winner:\s+(\S+)\s+\((.*?),\s*turn\s*(\d+)\)")


def game(first, second, m, seed):
    out = run(["fcode", "run", first, second, f"maps/{m}.map26",
               "--seed", str(seed), "--tle", "10"],
              capture_output=True, encoding="utf-8", errors="replace",
              cwd=ROOT).stdout or ""
    mo = WIN.search(out)
    if not mo:
        return m, first, second, seed, "draw", "unknown", 0
    return m, first, second, seed, mo.group(1), mo.group(2), int(mo.group(3))


jobs = [(a, b, m, s) for m in ALL for s in range(START_SEED, END_SEED + 1)
        for a, b in ((BOT_A, BOT_B), (BOT_B, BOT_A))]
n = len(jobs)
print(f"BATTLE  {BOT_A} vs {BOT_B}  |  {len(ALL)} maps x seeds {START_SEED}-{END_SEED} x both sides = {n} games\n")

rows, wins_a, wins_b = [], 0, 0
with cf.ThreadPoolExecutor(max_workers=min(21, os.cpu_count() or 4)) as ex:
    for i, (m, first, second, seed, winner, cond, turn) in enumerate(
            ex.map(lambda j: game(*j), jobs), 1):
        rows.append([BOT_A, BOT_B, m, seed, first, winner, cond, turn])
        if winner == BOT_A:
            wins_a += 1
        elif winner == BOT_B:
            wins_b += 1
        print(f"  [{i:>2}/{n}] {m:12s} seed {seed}  {first} first  ->  {winner} ({cond}, t{turn})")

print(f"\n{'='*50}")
print(f"  {BOT_A}: {wins_a}/{n} ({100*wins_a/n:.1f}%)")
print(f"  {BOT_B}: {wins_b}/{n} ({100*wins_b/n:.1f}%)")
print(f"  draws/errors: {n - wins_a - wins_b}")

per = {}
for r in rows:
    per.setdefault(r[2], [0, 0, 0])
    per[r[2]][2] += 1
    if r[5] == BOT_A:
        per[r[2]][0] += 1
    elif r[5] == BOT_B:
        per[r[2]][1] += 1

print(f"\n{'='*50}")
print(f"  {'MAP':14s} {BOT_A:>8s} {BOT_B:>8s}  {'games':>5s}")
print(f"  {'-'*40}")
for m in ALL:
    a, b, t = per.get(m, [0, 0, 0])
    print(f"  {m:14s} {a:>5d}/{t:<3d} {b:>5d}/{t:<3d}  {t:>5d}")
print()
