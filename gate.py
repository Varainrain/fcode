"""GATE - team promotion harness.

Runs a candidate bot against the frozen champion baseline across every map,
multiple seeds, both sides, in parallel. Prints per-map results, appends every
game to gate_results.csv, and gives a verdict:

  PROMOTE  win rate >= 55%  (a clear edge; anything nearer 50% is noise)
  REJECT   otherwise

Usage:
  python gate.py <candidate> [opponent=champion] [seeds=2] [fast]

  python gate.py mybot              # full gate: 15 maps x 2 seeds x both sides = 60 games
  python gate.py mybot champion 1 fast   # quick 6-map screen (24 games)
  python gate.py mybot oldbot 3     # any bot vs any bot, 3 seeds (90 games)

Bots live in bots/<name>/ with a main.py entry point. See WORKFLOW.md.
Draws and crashed/unparseable games count AGAINST the candidate.
"""
import concurrent.futures as cf
import csv
import datetime as dt
import os
import re
import shutil
import sys
from pathlib import Path
from subprocess import run

ROOT = Path(__file__).parent

args = [a for a in sys.argv[1:] if a != "fast"]
FAST = "fast" in sys.argv[1:]
if not args:
    sys.exit(__doc__)
CAND = args[0]
BASE = args[1] if len(args) > 1 else "champion"
SEEDS = int(args[2]) if len(args) > 2 else 2

if CAND == BASE:
    sys.exit("candidate and opponent are the same bot name - the winner line can't be "
             "attributed. Mirror-testing? Copy the folder under a second name first.")
if shutil.which("fcode") is None:
    sys.exit("fcode CLI not found on PATH (pip install fcode from test.pypi, then fcode login)")
for bot in (CAND, BASE):
    if not (ROOT / "bots" / bot / "main.py").is_file():
        sys.exit(f"no bot at bots/{bot}/main.py - see WORKFLOW.md for the layout")

ALL = sorted(p.stem for p in (ROOT / "maps").glob("*.map26"))
if not ALL:
    sys.exit("no maps in maps/")
MAPS = [m for m in ["duel", "quarry", "aurora", "twins", "longship", "sprint"] if m in ALL] if FAST else ALL
WIN = re.compile(r"Winner:\s+(\S+)\s+\((.*?),\s*turn\s*(\d+)\)")


def game(first, second, m, seed):
    # utf-8 + replace, not text=True: on Windows the default cp1252 decode
    # dies on any non-ascii byte in the output and returns stdout=None
    out = run(["fcode", "run", first, second, f"maps/{m}.map26",
               "--seed", str(seed), "--tle", "10"],
              capture_output=True, encoding="utf-8", errors="replace",
              cwd=ROOT).stdout or ""
    mo = WIN.search(out)
    if not mo:
        return m, first, second, seed, "draw", "unknown", 0
    return m, first, second, seed, mo.group(1), mo.group(2), int(mo.group(3))


jobs = [(a, b, m, s) for m in MAPS for s in range(1, SEEDS + 1)
        for a, b in ((CAND, BASE), (BASE, CAND))]
n = len(jobs)
print(f"GATE  {CAND} vs {BASE}  |  {len(MAPS)} maps x {SEEDS} seeds x both sides = {n} games\n")

rows, w, kills, kills_against, oddballs = [], 0, 0, 0, 0
# 6, not 12: heavy bots (khaos's map analysis) at 12 parallel engines exhaust
# the Windows commit limit -> WinError 1455 + phantom "draw (unknown)" games
with cf.ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 4)) as ex:
    for i, (m, first, second, seed, winner, cond, turn) in enumerate(
            ex.map(lambda j: game(*j), jobs), 1):
        rows.append([dt.datetime.now().isoformat(timespec="seconds"),
                     CAND, BASE, m, seed, first, winner, cond, turn])
        if winner == CAND:
            w += 1
            if "destroyed" in cond.lower():
                kills += 1
        else:
            if winner == BASE and "destroyed" in cond.lower():
                kills_against += 1
            if winner not in (CAND, BASE):
                oddballs += 1
        print(f"  [{i:>2}/{n}] {m:12s} seed {seed}  {first} first  ->  {winner} ({cond}, t{turn})")

new = not (ROOT / "gate_results.csv").exists()
with open(ROOT / "gate_results.csv", "a", newline="", encoding="utf-8") as f:
    cw = csv.writer(f)
    if new:
        cw.writerow(["time", "candidate", "opponent", "map", "seed",
                     "first_player", "winner", "condition", "turns"])
    cw.writerows(rows)

pct = 100 * w / n
print(f"\nGATE  {CAND} vs {BASE}  |  {n} games  |  {CAND} wins {w} ({pct:.0f}%)  "
      f"|  core kills by {CAND}: {kills}  |  against: {kills_against}")
if oddballs:
    print(f"  note: {oddballs} draw/error games counted against {CAND}")
per = {}
for r in rows:
    per.setdefault(r[3], [0, 0])
    per[r[3]][1] += 1
    if r[6] == CAND:
        per[r[3]][0] += 1
for m in MAPS:
    a, t = per.get(m, [0, 0])
    print(f"  {m:12s} {a}/{t}")
print("\nVERDICT:", "PROMOTE" if pct >= 55 else "REJECT",
      f"({pct:.0f}% vs the 55% bar)")
