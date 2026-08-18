"""Per-version performance ratings from the platform's own match records.

Every match row carries teamA/BVersion and ratingA/BBefore, so attribution
is exact - no activation-window guessing. Performance rating = classic
avgOpp + 400*(W-L)/n over GAMES (not series) is what Oogway's table used;
we compute both series-level and game-level, with a 90% CI from the
binomial SE (800 * 1.645 * sqrt(p(1-p)/n)).

Usage: python _perf.py [minVersion]
"""
import json
import math
import os
import subprocess
import sys

API = "https://game.code.florent.vc"
MY_TEAM = "Erebus"


def fetch_all():
    env = dict(os.environ, FCODE_API_URL=API)
    out, cursor, rows = None, None, []
    while True:
        cmd = ["fcode", "match", "list", "--mine", "--type", "ladder", "--json"]
        if cursor:
            cmd += ["--cursor", cursor]
        p = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                           errors="replace", env=env, timeout=120)
        try:
            d = json.loads(p.stdout)
        except Exception:
            break
        rows += d.get("matches", [])
        cursor = d.get("next_cursor")
        if not cursor:
            break
    return rows


def main():
    minv = int(sys.argv[1]) if len(sys.argv) > 1 else 130
    stats = {}   # version -> [seriesW, seriesN, gameW, gameN, sumOppBefore, nOpp]
    for m in fetch_all():
        if m.get("status") != "complete" or not m.get("rated"):
            continue
        if m.get("teamAName") == MY_TEAM:
            ver, opp = m.get("teamAVersion"), m.get("ratingBBefore")
            gw, gl = m.get("scoreA", 0), m.get("scoreB", 0)
            won = m.get("winnerId") == m.get("teamAId")
        elif m.get("teamBName") == MY_TEAM:
            ver, opp = m.get("teamBVersion"), m.get("ratingABefore")
            gw, gl = m.get("scoreB", 0), m.get("scoreA", 0)
            won = m.get("winnerId") == m.get("teamBId")
        else:
            continue
        if ver is None or int(ver) < minv:
            continue
        s = stats.setdefault(int(ver), [0, 0, 0, 0, 0.0, 0])
        s[0] += 1 if won else 0
        s[1] += 1
        s[2] += gw
        s[3] += gw + gl
        if opp:
            s[4] += float(opp)
            s[5] += 1

    print(f"{'ver':>4} {'series':>9} {'games':>11} {'win%':>6} {'avgOpp':>7} "
          f"{'perf':>7} {'90% CI':>16}")
    for ver in sorted(stats):
        sw, sn, gw, gn, so, no = stats[ver]
        if gn == 0 or no == 0:
            continue
        p = gw / gn
        avg = so / no
        perf = avg + 400 * (2 * p - 1)
        ci = 800 * 1.645 * math.sqrt(max(p * (1 - p), 1e-9) / gn)
        print(f"{ver:>4} {f'{sw}-{sn-sw}':>9} {f'{gw}/{gn}':>11} {100*p:>5.1f}% "
              f"{avg:>7.0f} {perf:>7.1f} [{perf-ci:>5.0f}, {perf+ci:>5.0f}]")


if __name__ == "__main__":
    main()
