"""WAR ROOM WORKER - turns this PC into an arena engine.

Polls the private arena site for queued battles, runs them LOCALLY with the
fcode engine against this repo checkout's bots/, and posts results back.
Bots never leave this machine; the site only ever sees results.

Usage:
  python warroom_worker.py https://your-arena.vercel.app YOUR_WARROOM_KEY

Leave it running in a terminal. Multiple teammates can run workers at once -
job claiming is atomic, no double-runs. Ctrl+C to stop.
"""
import concurrent.futures as cf
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent

# Resolve fcode by FULL PATH, not via PATH lookup — a scheduled task running
# as SYSTEM has a different PATH and can't find the console script, so every
# game failed instantly under the task while manual runs worked. Fall back to
# the Scripts dir next to this Python, then to the bare name.
FCODE = (shutil.which("fcode")
         or (str(Path(sys.executable).parent / "Scripts" / "fcode.exe")
             if (Path(sys.executable).parent / "Scripts" / "fcode.exe").exists()
             else "fcode"))

# args or env (env lets a systemd service keep the secret in a root-only file)
SITE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WARROOM_URL", "")).rstrip("/")
KEY = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("WARROOM_KEY", "")
if not SITE or not KEY:
    sys.exit(__doc__)
WORKER = os.environ.get("WARROOM_NAME", socket.gethostname())[:20]

MINI_MAPS = ["duel", "aurora", "quarry"]   # 3 maps x both sides = 6 games
FAST_MAPS = ["duel", "quarry", "aurora", "twins", "longship", "sprint"]
STD_MAPS = ["duel", "quarry", "aurora", "twins", "longship", "sprint",
            "hive", "strait", "crossfire", "vault"]
MAP_MODES = {"mini": MINI_MAPS, "fast": FAST_MAPS, "std": STD_MAPS}  # "full"->all
WIN = re.compile(r"Winner:\s+(\S+)\s+\((.*?),\s*turn\s*(\d+)\)")

# concurrent MATCHES (each is its own RUNNING row) and total GAMES in flight.
# PAR oversubscribes the cores a bit (games have IO/startup slack), so on a
# 2-core box ~4 games run at once. Override with WARROOM_SLOTS / WARROOM_PAR.
SLOTS = int(os.environ.get("WARROOM_SLOTS", "0")) or 2
PAR = int(os.environ.get("WARROOM_PAR", "0")) or max(2, 2 * (os.cpu_count() or 2))
_GAME_POOL = cf.ThreadPoolExecutor(max_workers=PAR)


def api(path, body=None):
    req = urllib.request.Request(
        SITE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "x-warroom-key": KEY},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def game(first, second, m, seed):
    # HARD TIMEOUT: without it, one hung fcode game freezes the whole slot
    # forever (observed: a match stuck 10+ min, queue never draining). Kill
    # a game that runs past 90s and count it a draw so the slot moves on.
    try:
        out = subprocess.run(
            [FCODE, "run", first, second, f"maps/{m}.map26",
             "--seed", str(seed), "--tle", "10"],
            capture_output=True, encoding="utf-8", errors="replace",
            cwd=ROOT, timeout=90).stdout or ""
    except subprocess.TimeoutExpired:
        return {"map": m, "seed": seed, "winner": None, "cond": "timeout", "turn": 0}
    except Exception:
        return {"map": m, "seed": seed, "winner": None, "cond": "error", "turn": 0}
    mo = WIN.search(out)
    if not mo:
        return {"map": m, "seed": seed, "winner": None, "cond": "draw/error", "turn": 0}
    return {"map": m, "seed": seed, "winner": mo.group(1),
            "cond": mo.group(2), "turn": int(mo.group(3))}


def run_job(job):
    a, b = job["a"], job["b"]
    for bot in (a, b):
        if not (ROOT / "bots" / bot / "main.py").is_file():
            print(f"  !! bots/{bot} missing on this machine - reporting empty")
            return []
    all_maps = sorted(p.stem for p in (ROOT / "maps").glob("*.map26"))
    mode = job.get("maps", "mini")
    pool = all_maps if mode == "full" else MAP_MODES.get(mode, MINI_MAPS)
    maps = [m for m in pool if m in all_maps]
    combos = [(x, y, m, s) for m in maps for s in range(1, job["seeds"] + 1)
              for x, y in ((a, b), (b, a))]
    # submit all this match's games to the SHARED pool — total games in
    # flight across every slot is capped at PAR, so slots overlap cleanly
    futs = [_GAME_POOL.submit(game, *c) for c in combos]
    return [f.result() for f in futs]


def discover():
    return sorted(p.name for p in (ROOT / "bots").iterdir()
                  if (p / "main.py").is_file())


def sync_roster():
    # pull main so everyone runs the latest bots, then register the roster
    try:
        subprocess.run(["git", "-C", str(ROOT), "pull", "--ff-only", "--quiet"],
                       capture_output=True, timeout=60)
    except Exception as e:
        print(f"  git pull skipped: {e}")
    bots = discover()
    try:
        api("/api/roster", {"bots": bots})
    except Exception as e:
        print(f"  roster report failed: {e}")
    return bots


import threading

_stop = threading.Event()


def match_slot(n):
    """One concurrent match runner. Claims a job (manual queue first, then
    the auto league), plays it, reports. Many of these run at once."""
    wid = f"{WORKER}#{n}"   # unique per slot so slots don't clear each other's
    while not _stop.is_set():                                  # running rows
        try:
            job = api("/api/claim", {"worker": wid}).get("job")
            src = "queued"
            if not job:
                job = api("/api/matchmake", {"worker": wid}).get("job")
                src = "auto"
            if not job:
                _stop.wait(8)
                continue
            print(f"[slot {n}] [{src}] {job['a']} vs {job['b']} "
                  f"({job.get('maps', 'std')})")
            games = run_job(job)
            api("/api/report", {"id": job["id"], "a": job["a"], "b": job["b"],
                                "games": games, "worker": wid})
            wa = sum(1 for g in games if g["winner"] == job["a"])
            wb = sum(1 for g in games if g["winner"] == job["b"])
            print(f"  -> {job['a']} {wa} - {wb} {job['b']}")
        except Exception as e:
            print(f"  slot {n} error: {e} (retry 20s)")
            _stop.wait(20)


print(f"war room worker '{WORKER}' online -> {SITE}  |  {SLOTS} concurrent slots")
bots = sync_roster()
print(f"repo: {ROOT}  |  {len(bots)} bots registered: {', '.join(bots)}")

slots = [threading.Thread(target=match_slot, args=(i + 1,), daemon=True)
         for i in range(SLOTS)]
for t in slots:
    t.start()

try:
    while True:
        time.sleep(120)  # main thread: keep the roster fresh
        sync_roster()
except KeyboardInterrupt:
    print("\nworker offline")
    _stop.set()
