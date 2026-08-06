"""OFFENSE AUDIT — per-game attack metrics from .replay26 files.

The instrument for the ATTACK module: it answers "did the siege actually land,
and did it trade" instead of only "who won". Reuses replay_stats' wire walker.

Usage:
  python offense_audit.py <file.replay26> [more.replay26 ...] [--json]

Per team it reports:
  guns        gunners built
  seat<=4     gunners built within manhattan 4 of the ENEMY core (siege seats)
  seatLife    median turns a siege seat survived (None = still alive at end)
  firstDmg    turn of the first damage dealt to the enemy core
  coreDmg     total damage dealt to the enemy core (core has 500 hp)
  harv/conv   harvesters / conveyors built (economy sanity check)
  lost        own gunners that died
"""
import json
import statistics
import sys
from collections import Counter, defaultdict

from replay_stats import PAYLOAD_TYPE, pos_of, signed, walk


def man(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def audit(path):
    data = open(path, "rb").read()
    top = walk(data)
    turns = top[(3, 'm')]
    result = walk(top[(6, 'm')][0]) if (6, 'm') in top else None
    res_str = (result.get((1, 'm'), [b""])[0].decode(errors="replace")
               if result else "?")

    ent = {}
    cores = {}          # team -> core top-left pos
    if (1, 'm') in top:
        mp = walk(top[(1, 'm')][0]) or {}
        for cm in mp.get((4, 'm'), []):
            c = walk(cm) or {}
            cid = c.get((1, 'v'), [None])[0]
            cteam = c.get((2, 'v'), [0])[0]
            cpos = pos_of(c[(3, 'm')][0]) if (3, 'm') in c else (-1, -1)
            if cid is not None:
                ent[cid] = {"team": cteam, "type": "core", "born": 0, "pos": cpos}
                cores[cteam] = cpos

    built = defaultdict(Counter)        # team -> type counter
    seats = defaultdict(list)           # team -> [(id, born, pos)]
    core_dmg = defaultdict(int)         # attacking team -> dmg dealt to enemy core
    first_dmg = {}                      # attacking team -> turn
    gun_lost = Counter()
    died_at = {}

    for r, tm in enumerate(turns):
        t = walk(tm)
        if not t:
            continue
        for e in t.get((1, 'm'), []):
            se = walk(e)
            if not se:
                continue
            if (1, 'm') in se:                      # create
                outer = walk(se[(1, 'm')][0]) or {}
                c = walk(outer[(1, 'm')][0]) if (1, 'm') in outer else outer
                c = c or {}
                eid = c.get((1, 'v'), [None])[0]
                team = c.get((2, 'v'), [0])[0]
                p = pos_of(c[(3, 'm')][0]) if (3, 'm') in c else (-1, -1)
                etype = "?"
                for (fn, ty) in c:
                    if ty == 'm' and fn >= 10:
                        etype = PAYLOAD_TYPE.get(fn, f"type{fn}")
                ent[eid] = {"team": team, "type": etype, "born": r, "pos": p}
                built[team][etype] += 1
                foe = 1 - team
                if etype == "gunner" and foe in cores and man(p, cores[foe]) <= 4:
                    seats[team].append((eid, r, p))
            elif (2, 'm') in se and (1, 'v') in se:  # move
                mv = walk(se[(2, 'm')][0])
                eid = se[(1, 'v')][0]
                if eid in ent and mv:
                    ent[eid]["pos"] = (mv.get((1, 'v'), [0])[0], mv.get((2, 'v'), [0])[0])
            elif (5, 'm') in se:                     # damage
                d = walk(se[(5, 'm')][0]) or {}
                eid = d.get((1, 'v'), [None])[0]
                delta = signed(d.get((2, 'v'), [0])[0])
                if delta < 0 and eid in ent and ent[eid]["type"] == "core":
                    atk = 1 - ent[eid]["team"]
                    core_dmg[atk] += -delta
                    first_dmg.setdefault(atk, r)
            elif (3, 'm') in se or (13, 'm') in se:  # death / destroyed
                key = (3, 'm') if (3, 'm') in se else (13, 'm')
                d = walk(se[key][0]) or {}
                eid = d.get((1, 'v'), [None])[0]
                if eid in ent:
                    died_at[eid] = r
                    if ent[eid]["type"] == "gunner":
                        gun_lost[ent[eid]["team"]] += 1

    out = {"file": path, "turns": len(turns), "result": res_str, "teams": {}}
    for team in (0, 1):
        lives = [died_at.get(eid, len(turns)) - born for eid, born, _ in seats[team]]
        out["teams"]["A" if team == 0 else "B"] = {
            "guns": built[team]["gunner"],
            "sentinels": built[team]["sentinel"],
            "seats_le4": len(seats[team]),
            "seat_life_median": (statistics.median(lives) if lives else None),
            "first_core_dmg_turn": first_dmg.get(team),
            "core_dmg_dealt": core_dmg[team],
            "harv": built[team]["harvester"],
            "conv": built[team]["conveyor"],
            "builders": built[team]["builder"],
            "guns_lost": gun_lost[team],
        }
    return out


def main(paths, as_json):
    rows = [audit(p) for p in paths]
    if as_json:
        print(json.dumps(rows, indent=1))
        return
    hdr = (f"{'file':28s} {'res':22s} {'t':>5} | "
           f"{'side':4s} {'gun':>4} {'seat':>4} {'life':>5} {'1st':>5} "
           f"{'dmg':>5} {'harv':>4} {'conv':>4} {'lost':>4}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        for side, d in r["teams"].items():
            print(f"{r['file'][-28:]:28s} {r['result'][:22]:22s} {r['turns']:5d} | "
                  f"{side:4s} {d['guns']:4d} {d['seats_le4']:4d} "
                  f"{str(d['seat_life_median']):>5} {str(d['first_core_dmg_turn']):>5} "
                  f"{d['core_dmg_dealt']:5d} {d['harv']:4d} {d['conv']:4d} "
                  f"{d['guns_lost']:4d}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args, "--json" in sys.argv)
