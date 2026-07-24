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
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent

# args or env (env lets a systemd service keep the secret in a root-only file)
SITE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WARROOM_URL", "")).rstrip("/")
KEY = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("WARROOM_KEY", "")
if not SITE or not KEY:
    sys.exit(__doc__)
WORKER = os.environ.get("WARROOM_NAME", socket.gethostname())[:20]

FAST_MAPS = ["duel", "quarry", "aurora", "twins", "longship", "sprint"]
WIN = re.compile(r"Winner:\s+(\S+)\s+\((.*?),\s*turn\s*(\d+)\)")


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
    out = subprocess.run(
        ["fcode", "run", first, second, f"maps/{m}.map26",
         "--seed", str(seed), "--tle", "10"],
        capture_output=True, encoding="utf-8", errors="replace",
        cwd=ROOT).stdout or ""
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
    maps = [m for m in FAST_MAPS if m in all_maps] if job["maps"] == "fast" else all_maps
    jobs = [(x, y, m, s) for m in maps for s in range(1, job["seeds"] + 1)
            for x, y in ((a, b), (b, a))]
    print(f"  {a} vs {b}: {len(jobs)} games...")
    results = []
    with cf.ThreadPoolExecutor(max_workers=min(6, os.cpu_count() or 4)) as ex:
        for g in ex.map(lambda j: game(*j), jobs):
            results.append(g)
            done = len(results)
            if done % 10 == 0:
                print(f"    {done}/{len(jobs)}")
    return results


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


print(f"war room worker '{WORKER}' online -> {SITE}")
bots = sync_roster()
print(f"repo: {ROOT}  |  {len(bots)} bots registered: {', '.join(bots)}")
last_sync = time.time()

while True:
    try:
        # re-pull + re-register every ~2 min so new bots on main auto-join
        if time.time() - last_sync > 120:
            sync_roster()
            last_sync = time.time()
        # manual queue first, then the auto league
        job = api("/api/claim", {"worker": WORKER}).get("job")
        source = "queued"
        if not job:
            job = api("/api/matchmake", {"worker": WORKER}).get("job")
            source = "auto"
        if not job:
            time.sleep(10)
            continue
        print(f"[{source}] {job['a']} vs {job['b']} "
              f"({job['maps']}, {job['seeds']} seed(s), by {job['by']})")
        games = run_job(job)
        api("/api/report", {"id": job["id"], "a": job["a"], "b": job["b"],
                            "games": games, "worker": WORKER})
        wa = sum(1 for g in games if g["winner"] == job["a"])
        wb = sum(1 for g in games if g["winner"] == job["b"])
        print(f"  -> {job['a']} {wa} - {wb} {job['b']}")
    except KeyboardInterrupt:
        print("\nworker offline")
        break
    except Exception as e:
        print(f"  error: {e} (retrying in 30s)")
        time.sleep(30)
