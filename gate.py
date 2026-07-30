"""GATE - team promotion harness.

Runs a candidate bot against the frozen champion baseline across every map,
multiple seeds, both sides, in parallel. Prints per-map results, appends every
game and its current-engine JSON economy metrics to gate_results.csv, and gives a
verdict:

  PROMOTE  win rate >= 55%  (a clear edge; anything nearer 50% is noise)
  REJECT   otherwise

Usage:
  python gate.py <candidate> [opponent=champion] [seeds=4] [fast] [quiet]
                 [maps=name1,name2]

  python gate.py mybot              # full gate: all maps x 4 seeds x both sides
  python gate.py mybot champion 1 fast   # quick 6-map screen (12 games)
  python gate.py mybot oldbot 4     # any bot vs any bot, 4 seeds
  python gate.py mybot oldbot 16 maps=string,bridge quiet

Bots live in bots/<name>/ with a main.py entry point. See WORKFLOW.md.
Draws and crashed/unparseable games count AGAINST the candidate.
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
BASE = args[1] if len(args) > 1 else "champion"
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
    "first_player",
    "winner",
    "condition",
    "turns",
    "engine",
] + METRIC_COLUMNS


def game(first, second, m, seed):
    # Every concurrent game gets a private disposable replay path. The CLI's
    # default replay.replay26 path is shared and races under the gate's worker
    # pool, which used to dirty the tracked fixture and corrupt replay output.
    with tempfile.TemporaryDirectory(prefix="fcode-gate-") as temp_dir:
        replay_path = Path(temp_dir) / "game.replay26"
        out = run(
            [
                "fcode",
                "run",
                first,
                second,
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
        return m, first, second, seed, "draw", "unknown", 0, {
            column: 0 for column in METRIC_COLUMNS
        }

    winner_side = result.get("winner")
    winner = first if winner_side == "A" else second if winner_side == "B" else "draw"
    candidate_is_a = first == CAND
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
        first,
        second,
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
    for i, (m, first, second, seed, winner, cond, turn, metrics) in enumerate(
            ex.map(lambda j: game(*j), jobs), 1):
        rows.append([dt.datetime.now().isoformat(timespec="seconds"),
                     CAND, BASE, m, seed, first, winner, cond, turn, ENGINE]
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
            print(f"  [{i:>2}/{n}] {m:12s} seed {seed}  {first} first  ->  {winner} ({cond}, t{turn})")

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
            migrated.append([values.get(column, "") for column in CSV_COLUMNS])
        tmp_path = results_path.with_suffix(".csv.tmp")
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(migrated)
        os.replace(tmp_path, results_path)
with open(results_path, "a", newline="", encoding="utf-8") as f:
    cw = csv.writer(f)
    if new:
        cw.writerow(CSV_COLUMNS)
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
