"""REPLAY STATS — decode a .replay26 protobuf and print a per-game battle report.

The real-game review tool: no mimics, no guessing — what ACTUALLY happened.

Usage:
  python replay_stats.py <file.replay26> [--events]
  fcode match replay <match-id>   # to download games first

Wire format (reverse-engineered):
  top: f1=map, f3=turn (xN), f6=result{f1=str}
  turn: f1=event (xN); event is a oneof by field number:
    f1 create {f1:id, f2:team(0=A,1=B), f3:{f1:x,f2:y}, f4:hp, f5:maxhp,
               payload-field = entity type (10=builder, 21=gunner, ...)}
    f2 move   {f1:id, f2:{x,y}}
    f3 death  {f1:id}
    f4 attack {f1:{f1:{x,y}from, f2:{x,y}to}}
    f5 damage {f1:id, f2:delta (zigzag-ish two's complement; negative=dmg)}
    f13 building destroyed {f1:id}
"""
import struct
import sys
from collections import Counter, defaultdict

# Verified 2026-07-13 against a replay with known builds (12 wall sentinels +
# 51 wired conveyors): 11=CONVEYOR and 22=SENTINEL — the earlier notes had
# them SWAPPED. 18=barrier and 24=launcher are consistent but less tested.
PAYLOAD_TYPE = {10: "builder", 11: "conveyor", 15: "harvester", 18: "barrier",
                21: "gunner", 22: "sentinel", 24: "launcher"}


def walk(buf):
    i, n = 0, len(buf)
    fields = {}
    while i < n:
        try:
            tag = 0
            shift = 0
            while True:
                b = buf[i]; i += 1
                tag |= (b & 0x7F) << shift
                if not b & 0x80:
                    break
                shift += 7
            fnum, wt = tag >> 3, tag & 7
            if wt == 0:
                v = 0; shift = 0
                while True:
                    b = buf[i]; i += 1
                    v |= (b & 0x7F) << shift
                    if not b & 0x80:
                        break
                    shift += 7
                fields.setdefault((fnum, 'v'), []).append(v)
            elif wt == 2:
                ln = 0; shift = 0
                while True:
                    b = buf[i]; i += 1
                    ln |= (b & 0x7F) << shift
                    if not b & 0x80:
                        break
                    shift += 7
                fields.setdefault((fnum, 'm'), []).append(buf[i:i + ln]); i += ln
            elif wt == 5:
                fields.setdefault((fnum, 'f'), []).append(struct.unpack('<f', buf[i:i + 4])[0]); i += 4
            elif wt == 1:
                fields.setdefault((fnum, 'd'), []).append(struct.unpack('<d', buf[i:i + 8])[0]); i += 8
            else:
                return None
        except Exception:
            return None
    return fields


def signed(v):
    return v - (1 << 64) if v > (1 << 63) else v


def pos_of(msg):
    p = walk(msg) or {}
    return (p.get((1, 'v'), [0])[0], p.get((2, 'v'), [0])[0])


def main(path, show_events=False):
    data = open(path, "rb").read()
    top = walk(data)
    turns = top[(3, 'm')]
    result = walk(top[(6, 'm')][0]) if (6, 'm') in top else None
    res_str = (result.get((1, 'm'), [b""])[0].decode(errors="replace")
               if result else "?")

    ent = {}                    # id -> dict(team, type, born, pos)
    # seed the two CORES from the map header — they never appear in create
    # events, so core damage/kills were invisible before this
    if (1, 'm') in top:
        mp = walk(top[(1, 'm')][0]) or {}
        for cm in mp.get((4, 'm'), []):
            c = walk(cm) or {}
            cid = c.get((1, 'v'), [None])[0]
            cteam = c.get((2, 'v'), [0])[0]
            cpos = pos_of(c[(3, 'm')][0]) if (3, 'm') in c else (-1, -1)
            if cid is not None:
                ent[cid] = {"team": cteam, "type": "core", "born": 0, "pos": cpos}
    dmg_taken = defaultdict(int)    # (team,type) -> total dmg
    dmg_by_turn_core = defaultdict(int)  # turn -> dmg on cores by team
    deaths = []
    creates_tl = defaultdict(list)  # team -> [(turn,type,pos)]
    unknown_payloads = Counter()

    for r, tm in enumerate(turns):
        t = walk(tm)
        if not t:
            continue
        for e in t.get((1, 'm'), []):
            se = walk(e)
            if not se:
                continue
            if (1, 'm') in se:      # create (payload wraps the entity msg)
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
                        if fn not in PAYLOAD_TYPE:
                            unknown_payloads[fn] += 1
                ent[eid] = {"team": team, "type": etype, "born": r, "pos": p}
                creates_tl[team].append((r, etype, p))
            elif (2, 'm') in se and (1, 'v') in se:   # move
                mv = walk(se[(2, 'm')][0])
                eid = se[(1, 'v')][0]
                if eid in ent and mv:
                    ent[eid]["pos"] = (mv.get((1, 'v'), [0])[0], mv.get((2, 'v'), [0])[0])
            elif (5, 'm') in se:    # damage
                d = walk(se[(5, 'm')][0]) or {}
                eid = d.get((1, 'v'), [None])[0]
                delta = signed(d.get((2, 'v'), [0])[0])
                if delta < 0 and eid in ent:
                    key = (ent[eid]["team"], ent[eid]["type"])
                    dmg_taken[key] += -delta
            elif (3, 'm') in se:    # death
                d = walk(se[(3, 'm')][0]) or {}
                eid = d.get((1, 'v'), [None])[0]
                if eid in ent:
                    deaths.append((r, ent[eid]["team"], ent[eid]["type"], ent[eid]["pos"]))
            elif (13, 'm') in se:   # building destroyed
                d = walk(se[(13, 'm')][0]) or {}
                eid = d.get((1, 'v'), [None])[0]
                if eid in ent:
                    deaths.append((r, ent[eid]["team"], ent[eid]["type"], ent[eid]["pos"]))

    print(f"=== {path} | {len(turns)} turns | result: {res_str} ===")
    for team in (0, 1):
        tl = creates_tl[team]
        by_type = Counter(t for _, t, _ in tl)
        print(f"\nTEAM {'A' if team == 0 else 'B'}: {len(tl)} entities built: {dict(by_type)}")
        # first 12 builds timeline
        for r, ty, p in tl[:12]:
            print(f"   t{r:<4} {ty:10s} at {p}")
    print("\nDAMAGE TAKEN (team,type -> total):")
    for k, v in sorted(dmg_taken.items(), key=lambda kv: -kv[1]):
        print(f"   {'A' if k[0] == 0 else 'B'} {k[1]:10s} {v}")
    print("\nDEATHS (first 20):")
    for r, team, ty, p in deaths[:20]:
        print(f"   t{r:<4} {'A' if team == 0 else 'B'} {ty:10s} at {p}")
    if unknown_payloads:
        print("\nUNKNOWN entity payload fields (add to PAYLOAD_TYPE):",
              dict(unknown_payloads))


if __name__ == "__main__":
    main(sys.argv[1], "--events" in sys.argv)
