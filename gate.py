"""GATE - team promotion harness.

Runs a candidate bot against the frozen champion baseline across every map,
multiple seeds, both sides, in parallel. Prints per-map results, appends every
game and its current-engine JSON economy metrics to gate_results.csv, and gives a
verdict:

  PROMOTE  win rate >= 55%  (a clear edge; anything nearer 50% is noise)
  REJECT   otherwise

Usage:
  python gate.py <candidate> [opponent=generalist-v3] [seeds=4] [fast] [quiet]
                 [maps=name1,name2]

  python gate.py mybot              # full gate: all maps x 4 seeds x both sides
  python gate.py mybot generalist-v3 1 fast   # quick 6-map screen (12 games)
  python gate.py mybot oldbot 4     # any bot vs any bot, 4 seeds
  python gate.py mybot oldbot 16 maps=string,bridge quiet

Bots live in bots/<name>/ with a main.py entry point. See WORKFLOW.md.
Draws and crashed/unparseable games count AGAINST the candidate.

Reproducibility: there is none at the game level. Almost every bot in bots/
calls random.* unseeded, and --seed seeds the engine, not the bot, so the same
(map, seed, seats) replays differently every run - about 40-50% of close games
flip winner. Seeds are extra samples, not a control variable. Read the win rate
with its CI; never diff two runs game by game.

Seats: `fcode run <bot_a> <bot_b>` seats bot_a as team 0 and bot_b as team 1,
and the seat fixes the spawn corner. Both sides act every round - neither seat
"goes first" - so results are reported per seat (`as A` / `as B`), never as a
turn order. Some maps are decided by the seat alone; those are flagged
SEAT-LOCKED and their collapsed win rate carries no information about the bots.
"""
import concurrent.futures as cf
import csv
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
from math import sqrt
from pathlib import Path
from subprocess import run

ROOT = Path(__file__).parent

MAP_ARG = next(
    (a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("maps=")),
    None,
)
args = [
    a for a in sys.argv[1:]
    if a not in ("fast", "quiet") and not a.startswith("maps=")
]
FAST = "fast" in sys.argv[1:]
QUIET = "quiet" in sys.argv[1:]
if not args:
    sys.exit(__doc__)
CAND = args[0]
# Default to the CURRENT LIVE BOT, not bots/champion. champion is stale
# (== oogerebus3, two generations behind): ten bots screened 91-100% against it
# and then lost to the live bot, and OogwayNEW screened 83% before losing 21-79.
# It inverts rankings, so it must never be the opponent you get by not choosing.
BASE = args[1] if len(args) > 1 else "generalist-v3"
SEEDS = int(args[2]) if len(args) > 2 else 4

if CAND == BASE:
    sys.exit("candidate and opponent are the same bot name - the winner line can't be "
             "attributed. Mirror-testing? Copy the folder under a second name first.")
if shutil.which("fcode") is None:
    sys.exit("fcode CLI not found on PATH (pip install fcode from test.pypi, then fcode login)")
for bot in (CAND, BASE):
    if not (ROOT / "bots" / bot / "main.py").is_file():
        sys.exit(f"no bot at bots/{bot}/main.py - see WORKFLOW.md for the layout")


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


if BASE == "champion":
    manifest_path = ROOT / "live_baseline.json"
    if not manifest_path.is_file():
        sys.exit("missing live_baseline.json; refusing to gate against an unverified champion")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files = manifest.get("files", {})
    champion_dir = ROOT / "bots" / "champion"
    actual_files = {
        p.name for p in champion_dir.iterdir()
        if p.is_file() and p.suffix == ".py"
    }
    mismatches = []
    if actual_files != set(expected_files):
        mismatches.append(
            f"file set is {sorted(actual_files)}, expected {sorted(expected_files)}")
    for name, expected in expected_files.items():
        path = champion_dir / name
        if path.is_file():
            actual = file_sha256(path)
            if actual != expected.upper():
                mismatches.append(f"{name}: {actual} != {expected.upper()}")
    if mismatches:
        sys.exit("champion does not match the recorded live baseline:\n  "
                 + "\n  ".join(mismatches))


version_result = run(
    ["fcode", "--version"], capture_output=True,
    encoding="utf-8", errors="replace", cwd=ROOT)
ENGINE = (version_result.stdout or version_result.stderr or "unknown").strip()

ALL = sorted(p.stem for p in (ROOT / "maps").glob("*.map26"))
if not ALL:
    sys.exit("no maps in maps/")
if MAP_ARG:
    requested_maps = [m.strip() for m in MAP_ARG.split(",") if m.strip()]
    missing_maps = [m for m in requested_maps if m not in ALL]
    if missing_maps:
        sys.exit(f"unknown maps in maps=: {', '.join(missing_maps)}")
    MAPS = requested_maps
elif FAST:
    MAPS = [
        m for m in
        ["duel", "quarry", "aurora", "twins", "longship", "sprint"]
        if m in ALL
    ]
else:
    MAPS = ALL

METRIC_COLUMNS = [
    "candidate_titanium",
    "opponent_titanium",
    "candidate_titanium_collected",
    "opponent_titanium_collected",
    "candidate_units",
    "opponent_units",
    "candidate_buildings",
    "opponent_buildings",
]
CSV_COLUMNS = [
    "time",
    "candidate",
    "opponent",
    "map",
    "seed",
    "side_a",
    "winner",
    "condition",
    "turns",
    "engine",
] + METRIC_COLUMNS
# side_a was called first_player until 2026-08-01. The name was wrong, the data
# was not: it has always held the bot passed as `fcode run <bot_a> <bot_b>`,
# i.e. the one the engine seats as team 0. There is no turn-order advantage to
# record - both sides act every round; what the seat decides is the spawn
# corner, and on some maps that alone settles the game (see SEAT-LOCKED below).
LEGACY_COLUMN_ALIASES = {"side_a": "first_player"}


def game(side_a, side_b, m, seed):
    # Every concurrent game gets a private disposable replay path. The CLI's
    # default replay.replay26 path is shared and races under the gate's worker
    # pool, which used to dirty the tracked fixture and corrupt replay output.
    with tempfile.TemporaryDirectory(prefix="fcode-gate-") as temp_dir:
        replay_path = Path(temp_dir) / "game.replay26"
        out = run(
            [
                "fcode",
                "run",
                side_a,
                side_b,
                f"maps/{m}.map26",
                "--seed",
                str(seed),
                "--tle",
                "10",
                "--json",
                "--replay",
                str(replay_path),
            ],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
        ).stdout or ""
    result = None
    for line in reversed(out.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            result = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if result is None:
        return m, side_a, side_b, seed, "draw", "unknown", 0, {
            column: 0 for column in METRIC_COLUMNS
        }

    winner_side = result.get("winner")
    winner = side_a if winner_side == "A" else side_b if winner_side == "B" else "draw"
    candidate_is_a = side_a == CAND
    candidate_prefix = "a" if candidate_is_a else "b"
    opponent_prefix = "b" if candidate_is_a else "a"
    metrics = {
        "candidate_titanium": result.get(f"{candidate_prefix}_titanium", 0),
        "opponent_titanium": result.get(f"{opponent_prefix}_titanium", 0),
        "candidate_titanium_collected": result.get(
            f"{candidate_prefix}_titanium_collected", 0),
        "opponent_titanium_collected": result.get(
            f"{opponent_prefix}_titanium_collected", 0),
        "candidate_units": result.get(f"{candidate_prefix}_units", 0),
        "opponent_units": result.get(f"{opponent_prefix}_units", 0),
        "candidate_buildings": result.get(f"{candidate_prefix}_buildings", 0),
        "opponent_buildings": result.get(f"{opponent_prefix}_buildings", 0),
    }
    return (
        m,
        side_a,
        side_b,
        seed,
        winner,
        result.get("win_condition", "unknown"),
        int(result.get("turns", 0)),
        metrics,
    )


jobs = [(a, b, m, s) for m in MAPS for s in range(1, SEEDS + 1)
        for a, b in ((CAND, BASE), (BASE, CAND))]
n = len(jobs)
print(f"GATE  {CAND} vs {BASE}  |  {len(MAPS)} maps x {SEEDS} seeds x both sides = {n} games")
print(f"ENGINE  {ENGINE}\n")

rows, w, kills, kills_against, oddballs = [], 0, 0, 0, 0
# 6, not 12: heavy bots (khaos's map analysis) at 12 parallel engines exhaust
# the Windows commit limit -> WinError 1455 + phantom "draw (unknown)" games
with cf.ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 4)) as ex:
    for i, (m, side_a, side_b, seed, winner, cond, turn, metrics) in enumerate(
            ex.map(lambda j: game(*j), jobs), 1):
        rows.append([dt.datetime.now().isoformat(timespec="seconds"),
                     CAND, BASE, m, seed, side_a, winner, cond, turn, ENGINE]
                    + [metrics[column] for column in METRIC_COLUMNS])
        if winner == CAND:
            w += 1
            if "destroyed" in cond.lower():
                kills += 1
        else:
            if winner == BASE and "destroyed" in cond.lower():
                kills_against += 1
            if winner not in (CAND, BASE):
                oddballs += 1
        if not QUIET:
            print(f"  [{i:>2}/{n}] {m:12s} seed {seed}  {side_a} as A  ->  {winner} ({cond}, t{turn})")

results_path = ROOT / "gate_results.csv"
new = not results_path.exists()
if not new:
    with open(results_path, newline="", encoding="utf-8") as f:
        existing = list(csv.reader(f))
    if existing and existing[0] != CSV_COLUMNS:
        old_header = existing[0]
        migrated = [CSV_COLUMNS]
        for old_row in existing[1:]:
            values = dict(zip(old_header, old_row))
            migrated.append([
                values.get(column, values.get(LEGACY_COLUMN_ALIASES.get(column, ""), ""))
                for column in CSV_COLUMNS
            ])
        tmp_path = results_path.with_suffix(".csv.tmp")
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(migrated)
        os.replace(tmp_path, results_path)
with open(results_path, "a", newline="", encoding="utf-8") as f:
    cw = csv.writer(f)
    if new:
        cw.writerow(CSV_COLUMNS)
    cw.writerows(rows)

def wilson(wins, games, z=1.96):
    """95% confidence interval for a win rate, as percentages."""
    if not games:
        return 0.0, 100.0
    p = wins / games
    d = 1 + z * z / games
    centre = (p + z * z / (2 * games)) / d
    half = z * sqrt(p * (1 - p) / games + z * z / (4 * games * games)) / d
    return 100 * (centre - half), 100 * (centre + half)


pct = 100 * w / n
lo, hi = wilson(w, n)
print(f"\nGATE  {CAND} vs {BASE}  |  {n} games  |  {CAND} wins {w} ({pct:.0f}%)  "
      f"[95% CI {lo:.0f}-{hi:.0f}%]  "
      f"|  core kills by {CAND}: {kills}  |  against: {kills_against}")
if oddballs:
    print(f"  note: {oddballs} draw/error games counted against {CAND}")
MAP_COL = CSV_COLUMNS.index("map")
SIDE_A_COL = CSV_COLUMNS.index("side_a")
WINNER_COL = CSV_COLUMNS.index("winner")

# Split by seat, always. A map where the side-A seat (or the side-B seat) wins
# every game looks exactly like a balanced 50/50 map in the collapsed
# candidate-wins/total number, because the candidate holds each seat half the
# time. Reading such a map as "even" is how a seat artefact gets mistaken for
# real parity - print the split so the two cases can never be confused.
per = {}
per_map_noise = False
for r in rows:
    stats = per.setdefault(r[MAP_COL], [0, 0, 0, 0, 0, 0])
    cand_is_a = r[SIDE_A_COL] == CAND
    stats[1 if cand_is_a else 3] += 1
    if r[WINNER_COL] == CAND:
        stats[0 if cand_is_a else 2] += 1
    # Decided games only. A crashed bot draws every game, which would otherwise
    # read as "side B won every game" and dress a broken build up as a seat lock.
    if r[WINNER_COL] in (CAND, BASE):
        stats[5] += 1
        if r[WINNER_COL] == r[SIDE_A_COL]:
            stats[4] += 1
for m in MAPS:
    wa, ga, wb, gb, a_seat_wins, decided = per.get(m, [0, 0, 0, 0, 0, 0])
    total = ga + gb
    note = ""
    if decided == total and total:
        if a_seat_wins == total:
            note = "  SEAT-LOCKED (side A won every game)"
        elif a_seat_wins == 0:
            note = "  SEAT-LOCKED (side B won every game)"
    print(f"  {m:12s} {wa + wb}/{total}   as A {wa}/{ga}   as B {wb}/{gb}{note}")
    if total < 30:
        per_map_noise = True

print("\nVERDICT:", "PROMOTE" if pct >= 55 else "REJECT",
      f"({pct:.0f}% vs the 55% bar)")

# Measured 2026-08-01: three 168-game gates of a bot against a BYTE-IDENTICAL
# copy of itself scored 49%, 56%, 51% - the middle one clears the bar and
# PROMOTEs a bot over itself. The games are not reproducible because 46 of the
# 48 bots/ call random.* without ever seeding it; `fcode run --seed` seeds the
# engine, not the bot's Python RNG. (Proven: seeding it made 16/16 games
# byte-repeat, winner and turn count. Not the worker pool - serial reruns flip
# just as often - and not --tle, which flips at 50% even when disabled.)
# So a gate score is a sample, and the bar has to be read against its width.
if lo < 50 < hi:
    print(f"  WARNING: the 95% CI ({lo:.0f}-{hi:.0f}%) spans 50% - this result does not "
          f"separate {CAND} from {BASE}.")
    print(f"  At n={n}, two identical bots land this far apart routinely. "
          f"Raise seeds before reading anything into it.")
if per_map_noise:
    print("  note: per-map rows are 8-16 games each (SD ~13-18 points). Treat them "
          "as direction only, never as evidence for a map-specific change.")
