"""MATCH AUTOPSY — pull our ladder games and say where each one went wrong.

The half of the loop autolab cannot do. autolab searches the knob space; this
reads real ladder replays and finds MECHANISMS. Output is deliberately dense:
one line per game plus a short phase timeline, so a whole match costs a few
lines of reading rather than a replay dump.

  python match_autopsy.py fetch [--limit 8]     download our recent ladder games
  python match_autopsy.py report [--losses]     autopsy what has been downloaded

Timeline markers per side (US = the team whose submission we are running):
  h1     first harvester            (economy started)
  g1     first gunner built
  seat1  first gunner within 4 of the ENEMY core   (the siege landed)
  hit1   first damage dealt to the enemy core
  bled1  first damage taken on our core
  dead   core destroyed
"""
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from offense_audit import audit, man
from replay_stats import PAYLOAD_TYPE, pos_of, signed, walk

ROOT = Path(__file__).parent
DIR = ROOT / "ladder_replays"
OURS = "Erebus"


def fcode(args):
    # via autolab.engine: on this machine fcode lives in a WSL venv and is not
    # on the Windows PATH, and that shim already resolves it either way.
    from autolab import engine
    return engine.run(args, timeout=300)


def fetch(limit=8):
    DIR.mkdir(exist_ok=True)
    raw = fcode(["match", "list", "--mine", "--type", "ladder",
                 "--limit", str(limit), "--json"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(f"could not parse match list. Is `fcode login` current?\n{raw[:400]}")
    matches = data.get("matches", data if isinstance(data, list) else [])
    index = []
    for m in matches:
        mid = m.get("id") or m.get("matchId")
        an, bn = m.get("teamAName") or "?", m.get("teamBName") or "?"
        sa, sb = m.get("scoreA") or 0, m.get("scoreB") or 0
        ver = m.get("teamAVersion") if an == OURS else m.get("teamBVersion")
        we_are_a = (an == OURS)
        us, them = (an, bn) if we_are_a else (bn, an)
        ourscore, theirscore = (sa, sb) if we_are_a else (sb, sa)
        if not mid:
            continue
        out = fcode(["match", "replay", mid])
        got = sorted(DIR.glob(f"{mid}_game_*.replay26"))
        if not got:
            for f in sorted(ROOT.glob(f"{mid}_game_*.replay26")):
                f.rename(DIR / f.name)
            got = sorted(DIR.glob(f"{mid}_game_*.replay26"))
        index.append({"id": mid, "us": us, "them": them, "we_are_a": we_are_a,
                      "version": ver, "score": f"{ourscore}-{theirscore}",
                      "won": (ourscore or 0) > (theirscore or 0),
                      "games": [g.name for g in got]})
        print(f"  {mid[:8]} v{ver} vs {them[:22]:22s} {ourscore}-{theirscore} "
              f"{'W' if (ourscore or 0) > (theirscore or 0) else 'L'} "
              f"({len(got)} replays)")
    (DIR / "index.json").write_text(json.dumps(index, indent=1))
    print(f"\n{len(index)} matches -> {DIR}")


def timeline(path, we_are_a):
    """Compact phase markers for both sides of one replay."""
    data = open(path, "rb").read()
    top = walk(data)
    turns = top[(3, 'm')]
    ent, cores = {}, {}
    if (1, 'm') in top:
        mp = walk(top[(1, 'm')][0]) or {}
        for cm in mp.get((4, 'm'), []):
            c = walk(cm) or {}
            cid = c.get((1, 'v'), [None])[0]
            team = c.get((2, 'v'), [0])[0]
            p = pos_of(c[(3, 'm')][0]) if (3, 'm') in c else (-1, -1)
            if cid is not None:
                ent[cid] = {"team": team, "type": "core", "pos": p}
                cores[team] = p
    mark = defaultdict(dict)
    for r, tm in enumerate(turns):
        t = walk(tm)
        if not t:
            continue
        for e in t.get((1, 'm'), []):
            se = walk(e)
            if not se:
                continue
            if (1, 'm') in se:
                outer = walk(se[(1, 'm')][0]) or {}
                c = walk(outer[(1, 'm')][0]) if (1, 'm') in outer else outer
                c = c or {}
                eid = c.get((1, 'v'), [None])[0]
                team = c.get((2, 'v'), [0])[0]
                p = pos_of(c[(3, 'm')][0]) if (3, 'm') in c else (-1, -1)
                ty = "?"
                for (fn, k) in c:
                    if k == 'm' and fn >= 10:
                        ty = PAYLOAD_TYPE.get(fn, f"t{fn}")
                ent[eid] = {"team": team, "type": ty, "pos": p}
                if ty == "harvester":
                    mark[team].setdefault("h1", r)
                if ty == "gunner":
                    mark[team].setdefault("g1", r)
                    foe = 1 - team
                    if foe in cores and man(p, cores[foe]) <= 4:
                        mark[team].setdefault("seat1", r)
            elif (5, 'm') in se:
                d = walk(se[(5, 'm')][0]) or {}
                eid = d.get((1, 'v'), [None])[0]
                if signed(d.get((2, 'v'), [0])[0]) < 0 and eid in ent \
                        and ent[eid]["type"] == "core":
                    mark[1 - ent[eid]["team"]].setdefault("hit1", r)
            elif (3, 'm') in se or (13, 'm') in se:
                key = (3, 'm') if (3, 'm') in se else (13, 'm')
                d = walk(se[key][0]) or {}
                eid = d.get((1, 'v'), [None])[0]
                if eid in ent and ent[eid]["type"] == "core":
                    mark[ent[eid]["team"]].setdefault("dead", r)
    us, them = (0, 1) if we_are_a else (1, 0)
    return len(turns), mark[us], mark[them]


def report(losses_only=False):
    idx = json.loads((DIR / "index.json").read_text())
    print(f"{'match':9s} {'opp':20s} {'g':2s} {'res':4s} {'turns':>5s} | "
          f"{'US h1':>5s} {'g1':>4s} {'seat':>4s} {'hit':>4s} {'dead':>4s} | "
          f"{'THEM h1':>7s} {'g1':>4s} {'seat':>4s} {'hit':>4s} {'dead':>4s} | guns/seats")
    print("-" * 128)
    agg = defaultdict(list)
    for m in idx:
        if losses_only and m["won"]:
            continue
        for gname in m["games"]:
            p = DIR / gname
            if not p.exists():
                continue
            try:
                turns, us, them = timeline(p, m["we_are_a"])
                a = audit(str(p))
                side = "A" if m["we_are_a"] else "B"
                d = a["teams"][side]
                o = a["teams"]["B" if side == "A" else "A"]
            except Exception as exc:                       # noqa: BLE001
                print(f"  {gname}: unreadable ({exc})")
                continue
            res = "W" if us.get("dead") is None and them.get("dead") is not None \
                else ("L" if us.get("dead") is not None else "t1k")
            g = gname.split("game_")[-1].split(".")[0]
            print(f"{m['id'][:8]:9s} {m['them'][:20]:20s} {g:2s} {res:4s} {turns:5d} | "
                  f"{str(us.get('h1','-')):>5s} {str(us.get('g1','-')):>4s} "
                  f"{str(us.get('seat1','-')):>4s} {str(us.get('hit1','-')):>4s} "
                  f"{str(us.get('dead','-')):>4s} | "
                  f"{str(them.get('h1','-')):>7s} {str(them.get('g1','-')):>4s} "
                  f"{str(them.get('seat1','-')):>4s} {str(them.get('hit1','-')):>4s} "
                  f"{str(them.get('dead','-')):>4s} | "
                  f"{d['guns']}/{d['seats_le4']} vs {o['guns']}/{o['seats_le4']}")
            for k in ("h1", "g1", "seat1", "hit1"):
                if us.get(k) is not None:
                    agg["us_" + k].append(us[k])
                if them.get(k) is not None:
                    agg["them_" + k].append(them[k])
            agg["us_seats"].append(d["seats_le4"])
            agg["them_seats"].append(o["seats_le4"])
            agg["us_dmg"].append(d["core_dmg_dealt"])
            agg["them_dmg"].append(o["core_dmg_dealt"])
            agg["res"].append(res)

    if not agg:
        print("\nnothing to report - run `fetch` first")
        return
    print("\nMEDIANS (the whole point: where we are systematically later or thinner)")

    def med(k):
        v = sorted(agg[k])
        return v[len(v) // 2] if v else None
    for label, a, b in (("first harvester", "us_h1", "them_h1"),
                        ("first gunner", "us_g1", "them_g1"),
                        ("first SEAT on their core", "us_seat1", "them_seat1"),
                        ("first damage to their core", "us_hit1", "them_hit1"),
                        ("seats landed (count)", "us_seats", "them_seats"),
                        ("core damage dealt", "us_dmg", "them_dmg")):
        ours, theirs = med(a), med(b)
        flag = ""
        if ours is not None and theirs is not None:
            if "seats" in a or "dmg" in a:
                flag = "  <-- WE ARE THINNER" if ours < theirs else ""
            else:
                flag = "  <-- WE ARE LATER" if ours > theirs else ""
        print(f"  {label:28s} us {str(ours):>6s}   them {str(theirs):>6s}{flag}")
    n = len(agg["res"])
    print(f"\n  {agg['res'].count('W')}W {agg['res'].count('L')}L "
          f"{agg['res'].count('t1k')} tiebreak  ({n} games)")


def narrate(path, we_are_a, limit_turns=None):
    """A compact round-by-round account of ONE game, as plain text.

    Built to be fed to a research assistant that knows FCL strategy but has
    never seen our replays: it needs what happened and when, not a byte dump.
    Every line is an event, positions are given relative to BOTH cores so
    "where" is interpretable without the map.
    """
    data = open(path, "rb").read()
    top = walk(data)
    turns = top[(3, 'm')]
    ent, cores = {}, {}
    if (1, 'm') in top:
        mp = walk(top[(1, 'm')][0]) or {}
        for cm in mp.get((4, 'm'), []):
            c = walk(cm) or {}
            cid = c.get((1, 'v'), [None])[0]
            team = c.get((2, 'v'), [0])[0]
            p = pos_of(c[(3, 'm')][0]) if (3, 'm') in c else (-1, -1)
            if cid is not None:
                ent[cid] = {"team": team, "type": "core", "pos": p}
                cores[team] = p
    us, them = (0, 1) if we_are_a else (1, 0)

    def coredist(p, team):
        """Manhattan to the NEAREST tile of a 2x2 core, not to its top-left.

        Measuring to the top-left alone overstates distance by up to 2 and made
        a seat that is exactly in gunner range look hopelessly out of it.
        """
        c = cores.get(team)
        if c is None:
            return -1
        return min(man(p, (c[0] + dx, c[1] + dy)) for dx in (0, 1) for dy in (0, 1))

    def where(p):
        return "d%d/d%d" % (coredist(p, us), coredist(p, them))

    out = ["GAME: %d turns. Positions are given as dOUR/dTHEIR = manhattan "
           "distance to our core / to their core." % len(turns), ""]
    dmg = {us: 0, them: 0}
    last_report = -50
    for r, tm in enumerate(turns):
        if limit_turns and r > limit_turns:
            break
        t = walk(tm)
        if not t:
            continue
        for e in t.get((1, 'm'), []):
            se = walk(e)
            if not se:
                continue
            if (1, 'm') in se:
                outer = walk(se[(1, 'm')][0]) or {}
                c = walk(outer[(1, 'm')][0]) if (1, 'm') in outer else outer
                c = c or {}
                eid = c.get((1, 'v'), [None])[0]
                team = c.get((2, 'v'), [0])[0]
                p = pos_of(c[(3, 'm')][0]) if (3, 'm') in c else (-1, -1)
                ty = "?"
                for (fn, k) in c:
                    if k == 'm' and fn >= 10:
                        ty = PAYLOAD_TYPE.get(fn, "t%d" % fn)
                ent[eid] = {"team": team, "type": ty, "pos": p}
                if ty in ("gunner", "sentinel", "harvester", "launcher", "barrier"):
                    out.append("t%-4d %-4s built %-9s at %s"
                               % (r, "US" if team == us else "THEM", ty, where(p)))
            elif (5, 'm') in se:
                d = walk(se[(5, 'm')][0]) or {}
                eid = d.get((1, 'v'), [None])[0]
                delta = signed(d.get((2, 'v'), [0])[0])
                if eid in ent and ent[eid]["type"] == "core" and delta < 0:
                    # CUMULATIVE DAMAGE, not hp: heals are positive deltas and
                    # are deliberately not netted off, so "damage dealt far above
                    # 500 on a 500 hp core" is visible as the heal wall it is.
                    dmg[ent[eid]["team"]] -= delta
                    if r - last_report >= 25:
                        out.append("t%-4d cumulative core damage TAKEN: us %d, them %d "
                                   "(core max hp is 500; anything above that was healed back)"
                                   % (r, dmg.get(us, 0), dmg.get(them, 0)))
                        last_report = r
            elif (3, 'm') in se or (13, 'm') in se:
                key = (3, 'm') if (3, 'm') in se else (13, 'm')
                d = walk(se[key][0]) or {}
                eid = d.get((1, 'v'), [None])[0]
                if eid in ent and ent[eid]["type"] in ("gunner", "sentinel", "core", "harvester"):
                    out.append("t%-4d %-4s LOST %-9s at %s"
                               % (r, "US" if ent[eid]["team"] == us else "THEM",
                                  ent[eid]["type"], where(ent[eid]["pos"])))
    return "\n".join(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "narrate":
        idx = json.loads((DIR / "index.json").read_text())
        losses = [(m, g) for m in idx if not m["won"] for g in m["games"]]
        m, g = losses[int(sys.argv[2]) if len(sys.argv) > 2 else 0]
        print("# LADDER LOSS vs %s (match %s, %s)" % (m["them"], m["id"][:8], g))
        print(narrate(str(DIR / g), m["we_are_a"]))
    elif cmd == "fetch":
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 8
        fetch(lim)
    else:
        report("--losses" in sys.argv)
