"""scrimbot — overnight unrated scrims against the top of the ladder.

Every CYCLE_MIN minutes it launches one unrated match against each of the
top N teams (skipping ourselves), waits for them, logs the results, and
downloads the replays before they expire.

Usage (from the repo root, so replays land in prod/):
    python scrimbot.py                 # top 5, every 20 min, forever
    python scrimbot.py --top 5 --every 20
    python scrimbot.py --cycles 12     # stop after 12 cycles
    python scrimbot.py --no-replays    # skip replay downloads

Notes
  - Unrated matches use whatever submission is currently ACTIVE, so make sure
    the bot you want tested is the active one before starting.
  - THE PLATFORM CAPS UNRATED MATCHES AT 5 PER 20 MINUTES, PER PERSON. That is
    exactly one cycle of --top 5 --every 20, which is why those are the
    defaults. The cap is per account, so teammates running this simultaneously
    DO stack: two people = 10 matches per window against the same active bot.
    Rate-limit refusals therefore mean your own account already spent slots in
    this window (e.g. from manual scrims) — not that a teammate took them.
  - Results append to scrim_log.csv and are printed as a running tally.
  - Replays expire within hours; they are downloaded into prod/ by default,
    which is what makes an overnight run worth analysing in the morning.
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import datetime as dt

API = "https://game.code.florent.vc"
LOG = "scrim_log.csv"
POLL_SECONDS = 20
MATCH_TIMEOUT = 15 * 60          # give up on a match after 15 minutes


def run(args, timeout=180):
    env = dict(os.environ, FCODE_API_URL=API)
    try:
        p = subprocess.run(args, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
        return (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return ""
    except Exception as e:                       # never let one call kill the loop
        return f"ERROR {e}"


def my_team_id():
    out = run(["fcode", "status", "--json"]) or ""
    try:
        d = json.loads(out)
        for key in ("teamId", "id"):
            if isinstance(d, dict) and d.get(key):
                return d[key]
            if isinstance(d, dict) and isinstance(d.get("team"), dict):
                return d["team"].get(key)
    except Exception:
        pass
    return None


def top_teams(n, skip_id):
    """Live top-N from the ladder, so the target list follows the meta."""
    out = run(["fcode", "ladder", "--limit", str(n + 3), "--json"])
    try:
        data = json.loads(out)
        rows = data if isinstance(data, list) else list(data.values())[0]
    except Exception:
        return []
    teams = []
    for r in rows:
        tid, name = r.get("teamId"), r.get("teamName")
        if not tid or tid == skip_id:
            continue
        teams.append((tid, name, round(r.get("rating", 0))))
        if len(teams) >= n:
            break
    return teams


def match_id_from(out):
    import re
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", out or "")
    return m.group(0) if m else None


def launch(team_id):
    """Returns (match_id, note). note is 'rate' when the platform refused
    because of the 5-per-20-minutes unrated cap."""
    out = run(["fcode", "match", "unrated", team_id])
    if "Rate limit" in (out or ""):
        return None, "rate"
    return match_id_from(out), None


def result_of(mid):
    """Return (our_score, their_score, winner_name, complete) for a match."""
    out = run(["fcode", "match", "info", mid, "--json"])
    try:
        d = json.loads(out)
    except Exception:
        return None
    m = d.get("match", d)
    if m.get("status") != "complete":
        return None
    a, b = m.get("teamAName"), m.get("teamBName")
    us = "A" if a == "Erebus" else "B"
    ours = m.get("scoreA") if us == "A" else m.get("scoreB")
    theirs = m.get("scoreB") if us == "A" else m.get("scoreA")
    opp = b if us == "A" else a
    return ours, theirs, opp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--every", type=int, default=20, help="minutes per cycle")
    ap.add_argument("--cycles", type=int, default=0, help="0 = run forever")
    ap.add_argument("--no-replays", action="store_true")
    a = ap.parse_args()

    me = my_team_id()
    new_log = not os.path.exists(LOG)
    tally = {}
    cycle = 0
    print(f"scrimbot: top {a.top}, every {a.every} min, replays="
          f"{'off' if a.no_replays else 'on'}. Ctrl-C to stop.\n", flush=True)

    while True:
        cycle += 1
        started = time.time()
        stamp = dt.datetime.now().strftime("%H:%M")
        targets = top_teams(a.top, me)
        if not targets:
            print(f"[{stamp}] could not read the ladder; retrying next cycle", flush=True)
        else:
            print(f"[{stamp}] cycle {cycle}: "
                  + ", ".join(f"{n}({r})" for _, n, r in targets), flush=True)

        live = []
        rate_limited = 0
        for tid, name, rating in targets:
            mid, note = launch(tid)
            if mid:
                live.append((mid, name))
            elif note == "rate":
                rate_limited += 1
                print(f"   ~ rate limited vs {name} "
                      f"(cap: 5 unrated / 20 min per ACCOUNT)", flush=True)
            else:
                print(f"   ! could not start vs {name}", flush=True)
            time.sleep(2)                         # be gentle with the API
        if rate_limited:
            print(f"   note: {rate_limited} slot(s) of YOUR 5 were already spent "
                  f"this window (manual scrims count). Teammates have their own.",
                  flush=True)

        deadline = time.time() + MATCH_TIMEOUT
        pending = dict(live)
        rows = []
        while pending and time.time() < deadline:
            time.sleep(POLL_SECONDS)
            for mid in list(pending):
                res = result_of(mid)
                if not res:
                    continue
                ours, theirs, opp = res
                name = pending.pop(mid)
                won = ours > theirs
                w, l = tally.get(name, (0, 0))
                tally[name] = (w + (1 if won else 0), l + (0 if won else 1))
                print(f"   {'W' if won else 'L'} {ours}-{theirs} vs {name}", flush=True)
                rows.append([dt.datetime.now().isoformat(timespec="seconds"),
                             cycle, name, ours, theirs, "W" if won else "L", mid])
                if not a.no_replays:
                    run(["fcode", "match", "replay", mid], timeout=300)
        for mid, name in live:
            if mid in pending:
                print(f"   ? timed out vs {name} ({mid[:8]})", flush=True)

        if rows:
            with open(LOG, "a", newline="", encoding="utf-8") as f:
                wtr = csv.writer(f)
                if new_log:
                    wtr.writerow(["time", "cycle", "opponent", "our_score",
                                  "their_score", "result", "match_id"])
                    new_log = False
                wtr.writerows(rows)

        if tally:
            total_w = sum(w for w, _ in tally.values())
            total_l = sum(l for _, l in tally.values())
            detail = "  ".join(f"{n} {w}-{l}" for n, (w, l) in sorted(tally.items()))
            print(f"   running total: {total_w}W-{total_l}L   |  {detail}\n", flush=True)

        if a.cycles and cycle >= a.cycles:
            print("done.", flush=True)
            return
        rest = a.every * 60 - (time.time() - started)
        if rest > 0:
            time.sleep(rest)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped.")
