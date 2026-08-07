"""AUTOLAB RUNNER — the self-iterating search loop. No model in the loop.

    python -m autolab.runner

What it does, forever, until you pause it from the dashboard:

  1. Holds a CHAMPION (a knob vector) and a NULL - a byte-identical copy of the
     champion under a different name. The null plays too. That is the whole
     trick: the null's Wilson band IS the noise floor, measured live on the
     current engine and map pool, and candidates are judged against it rather
     than against 50%. Today's session measured identical code at 61/49/50 over
     three 120-game runs, so a pipeline that judged against 50% would promote
     noise roughly one time in ten.
  2. Keeps N candidates alive, each a champion knob vector with one knob moved
     (coordinate descent), materialised into bots/<name>/ from bots/_template.
  3. Plays games on random (map, seed, seat) - seeds are extra samples, not a
     control variable, because the bots' own RNG is unseeded.
  4. PRUNES a candidate whose Wilson upper bound falls below the null's lower
     bound (it is losing), RETIRES one that is still undecided at max_games,
     and PROMOTES one whose Wilson lower bound clears the null's upper bound.
  5. On promotion: the candidate becomes champion, a fresh null is minted, all
     candidates are killed, and the search restarts from the new vector.

It cannot invent a mechanism. It searches the knob space declared in
autolab/build_template.py, which by default is the ATTACK lane only - the other
lanes belong to other owners (MODULES.md). Widen it from the dashboard if the
lane owners agree.
"""
import concurrent.futures as cf
import itertools
import json
import random
import re
import shutil
import sys
import time
from pathlib import Path

from . import engine, store
from .build_template import KNOB_SPEC, TEMPLATE

ROOT = Path(__file__).resolve().parent.parent
BOTS = ROOT / "bots"
MAPS = sorted(p.stem for p in (ROOT / "maps").glob("*.map26"))
WIN = re.compile(r"Winner:\s+(\S+)\s+\((.*?),\s*turn\s*(\d+)\)")
SEQ = itertools.count(int(time.time()) % 100000)


# ---------------------------------------------------------------- materialise

def materialise(name, knobs):
    """Write bots/<name>/ from the template with this knob vector baked in."""
    dest = BOTS / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(TEMPLATE, dest, ignore=shutil.ignore_patterns("__pycache__"))
    p = dest / "main.py"
    b = p.read_bytes()
    line_re = re.compile(rb"KNOBS = \{[^\n]*\}  # autolab")
    new = ("KNOBS = {" + ", ".join('"%s": %d' % (k, int(knobs[k]))
                                   for k in KNOB_SPEC) + "}  # autolab").encode()
    b, n = line_re.subn(new, b, count=1)
    if n != 1:
        raise RuntimeError(f"{name}: KNOBS line not found in template")
    p.write_bytes(b)
    return dest


def defaults():
    return {k: v[0] for k, v in KNOB_SPEC.items()}


def lanes_enabled(con):
    return {s.strip() for s in
            (store.get_control(con, "lanes", "attack") or "").split(",") if s.strip()}


def propose(con, champ_knobs, tried, lanes, rng):
    """One knob moved off the champion. Coordinate descent, not a random restart:
    a vector far from the champion is untestable - too many things changed to
    attribute the result, and the repo has receipts on bundles dying
    unattributable (PITFALL #19)."""
    pool = [k for k, v in KNOB_SPEC.items() if v[4] in lanes]
    rng.shuffle(pool)
    for knob in pool:
        default, lo, hi, kind, _ = KNOB_SPEC[knob]
        cur = champ_knobs[knob]
        if kind == "bool":
            options = [1 - int(cur)]
        else:
            span = max(1, (hi - lo) // 8)
            options = [cur + span, cur - span, cur + 2 * span, cur - 2 * span,
                       rng.randint(lo, hi)]
        rng.shuffle(options)
        for val in options:
            val = max(lo, min(hi, int(val)))
            if val == cur:
                continue
            cand = dict(champ_knobs, **{knob: val})
            key = json.dumps(cand, sort_keys=True)
            if key in tried:
                continue
            return cand, f"{knob} {cur}->{val}"
    return None, None


# ---------------------------------------------------------------------- games

def play(a, b, map_, seed):
    out = engine.run(["run", a, b, f"maps/{map_}.map26", "--seed", str(seed),
                      "--tle", "10"])
    mo = WIN.search(out)
    if not mo:
        return None, "no-result", 0
    return mo.group(1), mo.group(2), int(mo.group(3))


def one_game(variant, champ, map_, seed, seat_a):
    a, b = (variant, champ) if seat_a else (champ, variant)
    winner, cond, turns = play(a, b, map_, seed)
    return variant, map_, seed, ("A" if seat_a else "B"), int(winner == variant), cond, turns


def schedule(arm, k):
    """Map and seat for this arm's k-th game — a fixed rotation, not a draw.

    Every arm walks the SAME map cycle and flips seat every full pass, so two
    arms with the same game count have played the same maps in both seats. Drawing
    maps at random instead lets one arm collect more of a seat-locked map than
    another and shows up as a phantom several points wide - which is exactly the
    kind of artefact this pipeline exists to not fall for.
    """
    map_ = MAPS[k % len(MAPS)]
    seat_a = (k // len(MAPS)) % 2 == 0
    return map_, seat_a


# ----------------------------------------------------------------------- loop

def ensure_arena(con, rng):
    """Champion + null must exist and be materialised before anything runs."""
    champ = store.champion(con)
    if champ is None:
        knobs = defaults()
        name = f"lab_champ_{next(SEQ)}"
        materialise(name, knobs)
        store.add_variant(con, name, knobs, "champion", note="chassis defaults")
        store.log(con, "champion", f"{name} seeded from chassis defaults")
        champ = store.champion(con)
    nulls = store.active(con, "null")
    if not nulls:
        knobs = json.loads(champ["knobs"])
        name = f"lab_null_{next(SEQ)}"
        materialise(name, knobs)
        store.add_variant(con, name, knobs, "null", parent=champ["name"],
                          note="byte-identical control")
        store.log(con, "null", f"{name} minted against {champ['name']}")
    if not (BOTS / champ["name"]).exists():
        materialise(champ["name"], json.loads(champ["knobs"]))
    for n in store.active(con, "null"):
        if not (BOTS / n["name"]).exists():
            materialise(n["name"], json.loads(n["knobs"]))
    return store.champion(con), store.active(con, "null")[0]


def refill(con, champ, rng):
    want = int(store.get_control(con, "candidates", "3"))
    live = store.active(con, "candidate")
    if len(live) >= want:
        return
    tried = {r["knobs"] for r in
             con.execute("SELECT knobs FROM variants").fetchall()}
    lanes = lanes_enabled(con)
    champ_knobs = json.loads(champ["knobs"])
    for _ in range(want - len(live)):
        cand, desc = propose(con, champ_knobs, tried, lanes, rng)
        if cand is None:
            store.log(con, "search", "knob space exhausted for the enabled lanes")
            return
        name = f"lab_c{next(SEQ)}"
        materialise(name, cand)
        store.add_variant(con, name, cand, "candidate", parent=champ["name"],
                          note=desc)
        tried.add(json.dumps(cand, sort_keys=True))
        store.log(con, "spawn", f"{name}: {desc}")


def adjudicate(con, champ, null):
    """Prune / retire / promote. Returns True if the champion changed."""
    nw, nn = store.tally(con, null["name"])
    _, nlo, nhi = store.wilson(nw, nn)
    min_prune = int(store.get_control(con, "min_prune", "60"))
    min_promote = int(store.get_control(con, "min_promote", "400"))
    max_games = int(store.get_control(con, "max_games", "800"))
    # The null needs its own sample before it can referee anything.
    null_ready = nn >= min_prune
    for c in store.active(con, "candidate"):
        w, n = store.tally(con, c["name"])
        pct, lo, hi = store.wilson(w, n)
        if null_ready and n >= min_promote and lo > nhi:
            store.close_variant(con, c["name"], "promoted")
            store.close_variant(con, champ["name"], "retired")
            store.close_variant(con, null["name"], "retired")
            knobs = json.loads(c["knobs"])
            newname = f"lab_champ_{next(SEQ)}"
            materialise(newname, knobs)
            store.add_variant(con, newname, knobs, "champion", parent=c["name"],
                              note=c["note"])
            for other in store.active(con, "candidate"):
                store.close_variant(con, other["name"], "retired")
            store.log(con, "PROMOTE",
                      f"{c['name']} ({c['note']}) {pct:.1f}% CI {lo:.1f}-{hi:.1f} "
                      f"over null {nlo:.1f}-{nhi:.1f} at n={n} -> {newname}")
            return True
        if null_ready and n >= min_prune and hi < nlo:
            store.close_variant(con, c["name"], "rejected")
            store.log(con, "reject",
                      f"{c['name']} ({c['note']}) {pct:.1f}% CI {lo:.1f}-{hi:.1f} "
                      f"below null {nlo:.1f}-{nhi:.1f} at n={n}")
        elif n >= max_games:
            store.close_variant(con, c["name"], "retired")
            store.log(con, "retire",
                      f"{c['name']} ({c['note']}) undecided at n={n}: "
                      f"{pct:.1f}% CI {lo:.1f}-{hi:.1f} vs null {nlo:.1f}-{nhi:.1f}")
    return False


def handle_request(con, champ, rng):
    req = store.get_control(con, "request", "") or ""
    if not req:
        return False
    store.set_control(con, "request", "")
    try:
        cmd, _, arg = req.partition(" ")
        if cmd == "kill":
            store.close_variant(con, arg.strip(), "retired")
            store.log(con, "manual", f"killed {arg.strip()}")
        elif cmd == "try":
            knobs = dict(json.loads(champ["knobs"]), **json.loads(arg))
            name = f"lab_c{next(SEQ)}"
            materialise(name, knobs)
            store.add_variant(con, name, knobs, "candidate", parent=champ["name"],
                              note="manual: " + arg.strip())
            store.log(con, "manual", f"queued {name}: {arg.strip()}")
        elif cmd == "rebase":
            # chassis changed under us: rebuild the template and re-seed
            from .build_template import build
            build(arg.strip() or "OogwayAttack")
            store.log(con, "manual", f"template rebuilt from {arg.strip()}")
        else:
            store.log(con, "manual", f"unknown request {req!r}")
    except Exception as exc:                       # noqa: BLE001 - surface it
        store.log(con, "error", f"request {req!r} failed: {exc}")
    return True


def main():
    con = store.init()
    rng = random.Random()
    if not MAPS:
        sys.exit("no maps in maps/ - run `fcode maps sync` first")
    if not TEMPLATE.exists():
        sys.exit("no bots/_template - run `python -m autolab.build_template`")
    mode = engine.detect()
    if mode == "missing":
        sys.exit("fcode engine not found - run `python -m autolab.doctor`")
    store.log(con, "start",
              f"runner up, {len(MAPS)} maps in the pool, engine: {engine.describe()}")
    print(f"autolab runner: engine={engine.describe()}")
    while True:
        if store.get_control(con, "paused", "0") == "1":
            time.sleep(3)
            continue
        champ, null = ensure_arena(con, rng)
        handle_request(con, champ, rng)
        refill(con, champ, rng)
        arena = [null] + list(store.active(con, "candidate"))
        if len(arena) < 2:
            time.sleep(5)
            continue
        workers = max(1, int(store.get_control(con, "workers", "6")))
        # Fewest games first: the null keeps pace with the candidates, so its
        # band is always current rather than a stale number from an hour ago.
        jobs = []
        counts = {v["name"]: store.tally(con, v["name"])[1] for v in arena}
        for _ in range(workers * 2):
            pick = min(arena, key=lambda v: counts[v["name"]])
            k = counts[pick["name"]]
            counts[pick["name"]] += 1
            map_, seat_a = schedule(pick["name"], k)
            jobs.append((pick["name"], champ["name"], map_,
                         rng.randint(1, 10 ** 6), seat_a))
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(lambda j: one_game(*j), jobs):
                variant, map_, seed, seat, won, cond, turns = res
                if cond == "no-result":
                    # A crashed or unparseable game is missing data, not a loss.
                    # Counting it against the variant (gate.py's convention) is a
                    # silent one-sided bias, since the champion never sits in the
                    # variant slot. Discard and log it instead.
                    store.log(con, "error",
                              f"no result: {variant} on {map_} seed {seed} - discarded")
                    continue
                store.record_game(con, variant, champ["name"], map_, seed, seat,
                                  won, cond, turns)
        if adjudicate(con, champ, null):
            continue


if __name__ == "__main__":
    main()
