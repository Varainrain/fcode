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

if len(sys.argv) < 3:
    sys.exit(__doc__)
SITE = sys.argv[1].rstrip("/")
KEY = sys.argv[2]
WORKER = socket.gethostname()[:20]

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


print(f"war room worker '{WORKER}' online -> {SITE}")
print(f"repo: {ROOT}  |  bots available: "
      f"{', '.join(sorted(p.name for p in (ROOT / 'bots').iterdir() if (p / 'main.py').is_file()))}")
while True:
    try:
        d = api("/api/claim", {"worker": WORKER})
        job = d.get("job")
        if not job:
            time.sleep(10)
            continue
        print(f"claimed {job['id']}: {job['a']} vs {job['b']} "
              f"({job['maps']}, {job['seeds']} seed(s), queued by {job['by']})")
        games = run_job(job)
        api("/api/report", {"id": job["id"], "a": job["a"], "b": job["b"],
                            "games": games, "worker": WORKER})
        wa = sum(1 for g in games if g["winner"] == job["a"])
        wb = sum(1 for g in games if g["winner"] == job["b"])
        print(f"  reported: {job['a']} {wa} - {wb} {job['b']}")
    except KeyboardInterrupt:
        print("\nworker offline")
        break
    except Exception as e:
        print(f"  error: {e} (retrying in 30s)")
        time.sleep(30)
