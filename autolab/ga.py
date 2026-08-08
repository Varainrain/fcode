"""AUTOLAB GA — overnight population search over the attack knob space.

    python -m autolab.ga                 # defaults: 12 genomes x 6 generations
    python -m autolab.ga --pop 16 --gens 8 --games 80

Why a population search is worth running at all, given the hill-climber has
found nothing in ~11k games: the hill-climber moves ONE knob at a time from the
champion, so it can only find effects that are visible in isolation. Knobs that
only pay in combination (a looser seat gate AND a seat cap, say) are invisible
to it by construction.

Why it is affordable, which I initially got wrong: with a binary win/loss
fitness a genome needs ~400 games to rank, and 80 genomes is 22 hours. With the
continuous per-game margin (store.margin_of) a usable RANKING needs ~80, so
12 genomes x 6 generations is ~6k games, about 4 hours. This is the Halite III
pattern from the sources: continuous fitness for search, win/loss for the
verdict.

THE DISCIPLINE THAT MAKES THE OUTPUT MEAN ANYTHING:
  * A CONTROL GENOME - byte-identical to the champion - is re-created fresh in
    every generation and ranked alongside the mutants. It is the noise floor,
    measured inside the GA's own sampling budget. A generation whose "best"
    genome does not clearly beat the control learned nothing, and the log says
    so rather than crowning a winner anyway.
  * The GA NEVER PROMOTES. Its output is a shortlist. Winners are queued into
    the normal lab as candidates and must clear the null-referenced win-rate
    gate over 400 games like anything else. A multi-knob genome is
    unattributable (PITFALL #19), so it is gated as a whole, exactly as a
    foreign chassis would be.
"""
import argparse
import itertools
import json
import random
import shutil
import sys
import time
import concurrent.futures as cf

from . import engine, runner, store
from .build_template import KNOB_SPEC

SEQ = itertools.count(int(time.time()) % 100000)


def attack_knobs(lanes):
    return [k for k, v in KNOB_SPEC.items() if v[4] in lanes]


def random_genome(base, knobs, rng):
    g = dict(base)
    for k in knobs:
        if rng.random() < 0.5:                     # mutate about half the genes
            default, lo, hi, kind, _ = KNOB_SPEC[k]
            if kind == "bool":
                g[k] = rng.randint(0, 1)
            else:
                span = max(1, (hi - lo) // 6)
                g[k] = max(lo, min(hi, base[k] + rng.randint(-span, span)))
    return g


def crossover(a, b, knobs, rng, mutation=0.05):
    """Uniform crossover plus the ~5% mutation rate the sources describe."""
    child = dict(a)
    for k in knobs:
        child[k] = (a if rng.random() < 0.5 else b)[k]
        if rng.random() < mutation:
            default, lo, hi, kind, _ = KNOB_SPEC[k]
            if kind == "bool":
                child[k] = 1 - int(child[k])
            else:
                span = max(1, (hi - lo) // 6)
                child[k] = max(lo, min(hi, child[k] + rng.randint(-span, span)))
    return child


def describe(genome, base, knobs):
    diff = [f"{k} {base[k]}->{genome[k]}" for k in knobs if genome[k] != base[k]]
    return ", ".join(diff) if diff else "(identical to champion)"


def evaluate(con, names, champ, games_each, workers, rng):
    """Play games_each games for every genome, on the shared map/seat rotation."""
    jobs = []
    for name in names:
        start = store.tally(con, name, champ)[1]
        for i in range(games_each):
            map_, seat_a = runner.schedule(name, start + i)
            jobs.append((name, champ, map_, rng.randint(1, 10 ** 6), seat_a))
    rng.shuffle(jobs)                 # spread each genome across the whole run
    done = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(lambda j: runner.one_game(*j), jobs):
            variant, map_, seed, seat, won, cond, turns = res
            if cond == "no-result":
                store.log(con, "error", f"ga: no result {variant} on {map_}")
                continue
            store.record_game(con, variant, champ, map_, seed, seat, won, cond, turns)
            done += 1
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pop", type=int, default=12)
    ap.add_argument("--gens", type=int, default=6)
    ap.add_argument("--games", type=int, default=80, help="games per genome per generation")
    ap.add_argument("--elite", type=int, default=4)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    con = store.init()
    if engine.detect() == "missing":
        sys.exit("fcode engine not found - run `python -m autolab.doctor`")
    engine.prepare_scratch()

    champ_row = store.champion(con)
    if champ_row is None:
        sys.exit("no champion in the lab - start `python -m autolab.runner` once first")
    champ = champ_row["name"]
    base = runner.full_knobs(champ_row["knobs"])
    lanes = runner.lanes_enabled(con)
    knobs = attack_knobs(lanes)
    rng = random.Random()

    # The hill-climber and the GA would fight over the CPU and over the map/seat
    # rotation, so the GA takes the machine for the duration.
    was_paused = store.get_control(con, "paused", "0")
    store.set_control(con, "paused", "1")
    store.log(con, "ga", f"GA start: pop {args.pop} x {args.gens} gens x "
                         f"{args.games} games, knobs {sorted(knobs)} vs {champ}")
    print(f"GA vs {champ}: {args.pop} genomes x {args.gens} generations "
          f"x {args.games} games = ~{args.pop * args.gens * args.games} games")

    population = [dict(base)] + [random_genome(base, knobs, rng)
                                 for _ in range(args.pop - 1)]
    best_overall, best_fit = None, None
    try:
        for gen in range(1, args.gens + 1):
            names, meta = [], {}
            # index 0 of every generation is the CONTROL: byte-identical to the
            # champion, fresh name, so its spread is this generation's noise floor
            for i, genome in enumerate([dict(base)] + population[:args.pop - 1]):
                name = f"ga_g{gen}_{next(SEQ)}"
                runner.materialise(name, genome)
                note = ("CONTROL (= champion)" if i == 0
                        else describe(genome, base, knobs))
                store.add_variant(con, name, genome, "ga", parent=champ,
                                  note=f"gen{gen}: {note}")
                names.append(name)
                meta[name] = (genome, note)

            t0 = time.time()
            played = evaluate(con, names, champ, args.games, args.workers, rng)
            ranked = []
            for name in names:
                m, se, n = store.margin_stats(con, name, champ)
                w, gn = store.tally(con, name, champ)
                ranked.append((m, se, n, w, gn, name))
            ranked.sort(reverse=True)
            ctrl = next(r for r in ranked if meta[r[5]][1].startswith("CONTROL"))

            print(f"\n=== generation {gen}  ({played} games, {time.time()-t0:.0f}s) ===")
            for m, se, n, w, gn, name in ranked:
                flag = ""
                if not meta[name][1].startswith("CONTROL"):
                    sep = (m - ctrl[0]) / max(0.02, (se * se + ctrl[1] ** 2) ** 0.5)
                    flag = f"  {sep:+.1f} SE vs control"
                print(f"  margin {m:+.3f}  win {100*w/max(1,gn):5.1f}%  "
                      f"{name:16s} {meta[name][1][:52]}{flag}")

            top = [meta[r[5]][0] for r in ranked[:args.elite]]
            gain = ranked[0][0] - ctrl[0]
            sep = gain / max(0.02, (ranked[0][1] ** 2 + ctrl[1] ** 2) ** 0.5)
            store.log(con, "ga", f"gen{gen}: best {ranked[0][5]} margin "
                                 f"{ranked[0][0]:+.3f} vs control {ctrl[0]:+.3f} "
                                 f"({sep:+.1f} SE)")
            if sep < 2.0:
                print(f"  -> best genome is {sep:+.1f} SE from the control: "
                      f"this generation separated nothing.")
            if best_fit is None or ranked[0][0] > best_fit:
                best_fit, best_overall = ranked[0][0], meta[ranked[0][5]][0]

            for name in names:                       # keep the db, drop the folders
                store.close_variant(con, name, "retired")
                shutil.rmtree(runner.BOTS / name, ignore_errors=True)

            population = list(top)
            while len(population) < args.pop:
                a, b = rng.choice(top), rng.choice(top)
                population.append(crossover(a, b, knobs, rng))

        # Hand the winner to the real gate. The GA ranks; it does not promote.
        if best_overall and best_overall != base:
            name = f"lab_c{next(SEQ)}"
            runner.materialise(name, best_overall)
            note = "GA winner: " + describe(best_overall, base, knobs)
            store.add_variant(con, name, best_overall, "candidate",
                              parent=champ, note=note)
            store.log(con, "ga", f"queued {name} for null-referenced gating - {note}")
            print(f"\nqueued {name} as a normal candidate: {note}")
            print("It must still clear the null band over 400 games like anything else.")
        else:
            print("\nno genome beat the champion's own vector - nothing queued.")
    finally:
        store.set_control(con, "paused", was_paused)
        store.log(con, "ga", "GA finished; runner resumed")


if __name__ == "__main__":
    main()
