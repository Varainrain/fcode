"""LEAGUE - the private war room. Round-robin arena for OUR bots, fully
local: nothing touches the server, nothing becomes a public replay.

(Every server match - rated OR unrated - is visible in the global feed and
its replay is downloadable by anyone. That is exactly how we scouted
lastpopperian_ and Besvikomat. Gatekept bots fight HERE only.)

Usage:
  python league.py <bot> <bot> [<bot> ...] [seeds=N] [fast]

  python league.py oogerebus OogwayWIP krb            # 3-way, 1 seed
  python league.py oogerebus OogwayWIP krb kfort seeds=2
  python league.py oogerebus krb fast                 # quick 6-map screen

Runs every pairing on the full map pool, both sides, at the team measurement
standard (--tle 10). Prints a standings table and the pairwise matrix, and
appends the summary to league_results.md (commit it so everyone sees the
current table).
"""
import concurrent.futures as cf
import datetime as dt
import itertools
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

args = [a for a in sys.argv[1:] if a != "fast" and not a.startswith("seeds=")]
FAST = "fast" in sys.argv[1:]
SEEDS = 1
for a in sys.argv[1:]:
    if a.startswith("seeds="):
        SEEDS = int(a.split("=")[1])
if len(args) < 2:
    sys.exit(__doc__)
BOTS = args

if shutil.which("fcode") is None:
    sys.exit("fcode CLI not found on PATH")
for b in BOTS:
    if not (ROOT / "bots" / b / "main.py").is_file():
        sys.exit(f"no bot at bots/{b}/main.py")

ALL = sorted(p.stem for p in (ROOT / "maps").glob("*.map26"))
MAPS = ([m for m in ["duel", "quarry", "aurora", "twins", "longship", "sprint"]
         if m in ALL] if FAST else ALL)
WIN = re.compile(r"Winner:\s+(\S+)\s+\((.*?),\s*turn\s*(\d+)\)")

ver = subprocess.run(["pip", "show", "fcode"], capture_output=True,
                     encoding="utf-8", errors="replace").stdout
ver = (re.search(r"Version:\s*(\S+)", ver) or [None, "?"])[1]


def game(first, second, m, seed):
    out = subprocess.run(
        ["fcode", "run", first, second, f"maps/{m}.map26",
         "--seed", str(seed), "--tle", "10"],
        capture_output=True, encoding="utf-8", errors="replace",
        cwd=ROOT).stdout or ""
    mo = WIN.search(out)
    return first, second, (mo.group(1) if mo else None)


jobs = []
for a, b in itertools.combinations(BOTS, 2):
    for m in MAPS:
        for s in range(1, SEEDS + 1):
            jobs.append((a, b, m, s))
            jobs.append((b, a, m, s))
n = len(jobs)
print(f"LEAGUE  {' vs '.join(BOTS)}  |  engine {ver}  |  {n} games\n")

wins = {b: 0 for b in BOTS}
games_played = {b: 0 for b in BOTS}
pair = {}   # (a, b) -> a's wins against b
for a, b in itertools.permutations(BOTS, 2):
    pair[(a, b)] = 0
done = 0
# 6 workers: the team standard (12 parallel engines OOM windows w/ heavy bots)
with cf.ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 4)) as ex:
    for first, second, winner in ex.map(lambda j: game(*j), jobs):
        done += 1
        games_played[first] += 1
        games_played[second] += 1
        if winner in (first, second):
            wins[winner] += 1
            loser = second if winner == first else first
            pair[(winner, loser)] += 1
        if done % 20 == 0:
            print(f"  ... {done}/{n}")

stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
lines = [f"\n## League {stamp}  |  engine {ver}  |  "
         f"{len(MAPS)} maps x {SEEDS} seed(s) x both sides\n"]
standings = sorted(BOTS, key=lambda b: -wins[b] / max(1, games_played[b]))
lines.append("| bot | win% | wins/games |")
lines.append("|---|---|---|")
for b in standings:
    pct = 100 * wins[b] / max(1, games_played[b])
    lines.append(f"| {b} | {pct:.0f}% | {wins[b]}/{games_played[b]} |")
lines.append("")
lines.append("| vs | " + " | ".join(standings) + " |")
lines.append("|---|" + "---|" * len(standings))
for a in standings:
    row = [a]
    for b in standings:
        if a == b:
            row.append("-")
        else:
            total = pair[(a, b)] + pair[(b, a)]
            row.append(f"{100 * pair[(a, b)] / total:.0f}%" if total else "?")
    lines.append("| " + " | ".join(row) + " |")
report = "\n".join(lines)
print(report)
with open(ROOT / "league_results.md", "a", encoding="utf-8") as f:
    f.write(report + "\n")
print("\nappended to league_results.md - commit it so the team sees the table")
