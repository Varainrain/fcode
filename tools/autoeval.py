"""autoeval — A/B two SUBMISSIONS against the REAL top of the ladder.

MFF1's postmortem (Cambridge Battlecode, 7th/8th) describes the tool that made
their decisions, and the reason for it is our exact problem:

    "testing against our own bot had massive downsides - we frequently tried
     to counter strategies that we never implemented our self, which is hard
     to test locally"

Our whole campaign gated against archetypes WE wrote. None of them cage a core
the way Lorem Ipsum, O(1) and Bean counters do, none of them land four
sentinels by t35 the way not adgato does - so every change aimed at those
matchups measured as noise. This runs the other way round: it sets one of our
submissions active, spends the unrated budget against real teams, then swaps to
the other and does the same, so both are measured against the SAME opponents.

MFF1 also pinned the enemy version per round to keep it fair between candidates;
we cannot pin an opponent's submission through the CLI, but alternating every
cycle keeps drift shared between the two candidates instead of loaded onto one.

    python autoeval.py --versions 203 198 --top 5 --until "10:30"

SAFETY: the finals bot is whatever is ACTIVE at the lock, so this always
finishes by activating --final (default: the first version listed), and it
refuses to start within --margin minutes of --until.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
LOG = "autoeval_log.csv"


def run(cmd, timeout=180):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return ""


def jrun(cmd):
    """fcode writes an 'Update available' banner to stderr; raw_decode past it.
    (oni lost 37 hours of scrimbot to exactly this - commit aa6b1c5.)"""
    txt = run(cmd)
    for i, ch in enumerate(txt):
        if ch in "[{":
            try:
                return json.JSONDecoder().raw_decode(txt[i:])[0]
            except ValueError:
                continue
    return None


def activate(version):
    """Activate and VERIFY against status. Parsing the CLI's prose failed the
    first run: v203 was already active, fcode said so in different words, and
    the A/B aborted before a single match. Ask what is active instead."""
    if active_version() == str(version):
        return True
    run(["fcode", "submission", "activate", str(version)])
    for _ in range(6):
        if active_version() == str(version):
            return True
        time.sleep(5)
    return False


def active_version():
    m = re.search(r"Active bot:\s*v(\d+)", run(["fcode", "status"]))
    return m.group(1) if m else None


def named_teams(names, us="Erebus"):
    """Resolve EXACT opponents by name. The finals prize money is decided
    against a specific short list - not adgato, Pantheon, Leviathan, Clankers,
    Lorem Ipsum - and 'top N' drifts as the ladder moves, so a run aimed at
    those five has to name them."""
    data = jrun(["fcode", "ladder", "--limit", "40", "--json"])
    rows = data if isinstance(data, list) else (data or {}).get("teams", [])
    byname = {}
    for r in rows:
        nm = r.get("name") or r.get("teamName")
        tid = r.get("id") or r.get("teamId")
        if nm and tid:
            byname[nm.strip().lower()] = (nm, tid)
    out = []
    for want in names:
        hit = byname.get(want.strip().lower())
        if hit:
            out.append(hit)
        else:
            print(f"   ! could not resolve team '{want}'", flush=True)
    return out


def top_teams(n, us="Erebus"):
    data = jrun(["fcode", "ladder", "--limit", str(n + 3), "--json"])
    rows = data if isinstance(data, list) else (data or {}).get("teams", [])
    out = []
    for r in rows:
        name = r.get("name") or r.get("teamName")
        tid = r.get("id") or r.get("teamId")
        if name and tid and name != us:
            out.append((name, tid))
        if len(out) >= n:
            break
    return out


def request(tid):
    out = run(["fcode", "match", "unrated", tid])
    if "rate limit" in out.lower():
        return None, True
    ids = UUID.findall(out)
    return (ids[0] if ids else None), False


def result_of(mid, us="Erebus"):
    data = jrun(["fcode", "match", "info", mid, "--json"])
    if not data:
        return None
    # `match info --json` nests everything under "match" (top keys are
    # ["match", "games"]). Reading teamAName off the top level silently
    # returned None for every poll and the first run logged nothing at all.
    data = data.get("match", data)
    if data.get("status") != "complete":
        return None
    a, b = data.get("teamAName"), data.get("teamBName")
    sa, sb = data.get("scoreA"), data.get("scoreB")
    if sa is None or sb is None:
        return None
    if a == us:
        return sa, sb, b
    if b == us:
        return sb, sa, a
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", nargs="+", required=True)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--teams", nargs="+", default=None,
                    help="exact opponent names (overrides --top)")
    ap.add_argument("--until", default="10:30", help="local HH:MM to stop by")
    ap.add_argument("--margin", type=int, default=45,
                    help="minutes of headroom required before --until")
    ap.add_argument("--final", default=None,
                    help="version to leave ACTIVE at the end (default: first)")
    ap.add_argument("--cycle", type=int, default=20, help="minutes per window")
    ap.add_argument("--chunk", type=int, default=5,
                    help="requests per rate-limit window")
    ap.add_argument("--chunk-gap", type=int, default=10,
                    help="minutes between request chunks")
    a = ap.parse_args()

    final = a.final or a.versions[0]
    hh, mm = (int(x) for x in a.until.split(":"))
    now = dt.datetime.now()
    stop = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if stop <= now:
        stop += dt.timedelta(days=1)
    if (stop - now).total_seconds() < a.margin * 60:
        print(f"refusing to start: less than {a.margin} min before {a.until}")
        return

    teams = named_teams(a.teams) if a.teams else top_teams(a.top)
    if not teams:
        print("could not read the ladder")
        return
    print(f"A/B {a.versions} vs {[t[0] for t in teams]}")
    print(f"until {stop:%H:%M}, then activating v{final}\n", flush=True)

    tally = {v: [0, 0, 0, 0] for v in a.versions}   # W, L, gamesFor, gamesAgainst
    new = not os.path.exists(LOG)
    fh = open(LOG, "a", newline="", encoding="utf-8")
    w = csv.writer(fh)
    if new:
        w.writerow(["time", "version", "opponent", "us", "them", "match_id"])

    i = 0
    while dt.datetime.now() < stop - dt.timedelta(minutes=a.margin):
        ver = a.versions[i % len(a.versions)]
        if not activate(ver):
            print(f"could not activate v{ver}; stopping", flush=True)
            break
        print(f"[{dt.datetime.now():%H:%M}] v{ver} active", flush=True)
        # CHUNKED REQUESTS. The cap is 5 unrated per ACCOUNT per window, so a
        # 20-minute cycle against the top 10 fits as 5 now and 5 after the
        # window rolls. Requesting all ten back-to-back just burns five of
        # them on refusals.
        pending = []
        limited_first = False
        for chunk_i in range(0, len(teams), a.chunk):
            if chunk_i:
                time.sleep(a.chunk_gap * 60)
            for name, tid in teams[chunk_i:chunk_i + a.chunk]:
                mid, limited = request(tid)
                if limited:
                    limited_first = not pending
                    print("   ~ rate limited", flush=True)
                    break
                if mid:
                    pending.append((name, mid))
        # Do NOT burn this version's turn on a window where we got nothing:
        # a rate-limited cycle used to advance the rotation, handing the other
        # candidate an extra window and skewing the A/B.
        if not limited_first:
            i += 1
        time.sleep(150)
        for name, mid in pending:
            res = None
            for _ in range(12):
                res = result_of(mid)
                if res:
                    break
                time.sleep(20)
            if not res:
                continue
            us, them, opp = res
            t = tally[ver]
            t[0 if us > them else 1] += 1
            t[2] += us
            t[3] += them
            w.writerow([dt.datetime.now().isoformat(timespec="seconds"),
                        ver, opp, us, them, mid])
            fh.flush()
            print(f"   v{ver} {us}-{them} vs {opp}", flush=True)
        for v, t in tally.items():
            n = t[0] + t[1]
            if n:
                print(f"   TALLY v{v}: {t[0]}W-{t[1]}L  games {t[2]}-{t[3]}"
                      f"  ({100*t[0]/n:.0f}% matches,"
                      f" {100*t[2]/max(1,t[2]+t[3]):.0f}% games)", flush=True)
        left = (stop - dt.timedelta(minutes=a.margin) - dt.datetime.now())
        rest = a.chunk_gap * 60 if len(teams) > a.chunk else a.cycle * 60
        if left.total_seconds() > rest:
            time.sleep(rest)

    fh.close()
    print(f"\nactivating final v{final}", flush=True)
    print("OK" if activate(final) else "FAILED TO ACTIVATE - DO IT BY HAND",
          flush=True)
    for v, t in tally.items():
        n = t[0] + t[1]
        if n:
            print(f"v{v}: {t[0]}W-{t[1]}L over {n} matches, "
                  f"games {t[2]}-{t[3]}", flush=True)


main()
