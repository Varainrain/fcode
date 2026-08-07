"""Deterministic test of the decision logic — no games, no engine.

The expensive part of this pipeline (playing games) is not the part that can be
silently wrong. The adjudicator is: a sign error in the promote rule would ship
the WORST knob vector it finds, and it would take hours of games to notice. So
the rules are tested against synthetic tallies with known answers.

    python -m autolab.selftest
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from . import runner, store


def seed_games(con, variant, wins, games):
    now = time.time()
    rows = [(variant, "champ", "map", i, "A", 1 if i < wins else 0, "x", 100, now)
            for i in range(games)]
    con.executemany(
        "INSERT INTO games(variant,opponent,map,seed,seat,won,cond,turns,ts)"
        " VALUES(?,?,?,?,?,?,?,?,?)", rows)
    con.commit()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="autolab_selftest_"))
    old_db, old_bots = store.DB, runner.BOTS
    store.DB = tmp / "t.db"
    runner.BOTS = tmp / "bots"
    runner.BOTS.mkdir()
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  {'ok  ' if got == want else 'FAIL'} {label}: {got}")

    try:
        con = store.init()
        knobs = runner.defaults()
        store.add_variant(con, "champ", knobs, "champion")
        store.add_variant(con, "null", knobs, "null", parent="champ")
        store.set_control(con, "min_prune", "60")
        store.set_control(con, "min_promote", "400")
        store.set_control(con, "max_games", "800")

        # A null band of 50% +/- a bit, from 500 games.
        seed_games(con, "null", 250, 500)
        _, nlo, nhi = store.wilson(250, 500)
        print(f"null band {nlo:.1f}-{nhi:.1f}")

        # clearly worse, past the prune gate -> rejected
        store.add_variant(con, "bad", knobs, "candidate", note="bad")
        seed_games(con, "bad", 20, 100)
        # clearly better, past the promote gate -> promoted
        store.add_variant(con, "good", knobs, "candidate", note="good")
        seed_games(con, "good", 260, 400)
        # a sibling that is still mid-flight when the promotion lands
        store.add_variant(con, "sibling", knobs, "candidate", note="sibling")
        seed_games(con, "sibling", 2, 30)

        champ = store.champion(con)
        null = store.active(con, "null")[0]
        changed = runner.adjudicate(con, champ, null)

        def status(name):
            return con.execute("SELECT status FROM variants WHERE name=?",
                               (name,)).fetchone()["status"]

        check("clearly-worse candidate is rejected", status("bad"), "rejected")
        check("clearly-better candidate is promoted", status("good"), "promoted")
        # Deliberate: siblings were measured against the OLD champion, so their
        # tallies are void the moment it changes (PITFALL #17, carry-forward).
        check("promotion voids in-flight siblings", status("sibling"), "retired")
        check("champion changed", changed, True)
        check("old champion retired", status("champ"), "retired")
        check("old null retired", status("null"), "retired")
        newchamp = store.champion(con)
        check("new champion exists", newchamp is not None and newchamp["name"] != "champ", True)
        check("new champion inherits the candidate's knobs",
              json.loads(newchamp["knobs"]) == knobs, True)

        # A null with too few games must referee nothing at all.
        store.DB = tmp / "t2.db"
        con2 = store.init()
        store.add_variant(con2, "champ", knobs, "champion")
        store.add_variant(con2, "null", knobs, "null")
        seed_games(con2, "null", 5, 10)                 # nowhere near min_prune
        store.add_variant(con2, "bad", knobs, "candidate")
        seed_games(con2, "bad", 5, 200)                 # 2.5%, obviously awful
        runner.adjudicate(con2, store.champion(con2), store.active(con2, "null")[0])
        check("no adjudication while the null is under-sampled",
              con2.execute("SELECT status FROM variants WHERE name='bad'")
              .fetchone()["status"], "active")

        # No promotion in flight: under-sampled is left alone, level-at-the-
        # ceiling is retired rather than promoted.
        store.DB = tmp / "t3.db"
        con3 = store.init()
        store.add_variant(con3, "champ", knobs, "champion")
        store.add_variant(con3, "null", knobs, "null")
        seed_games(con3, "null", 250, 500)
        store.add_variant(con3, "early", knobs, "candidate")
        seed_games(con3, "early", 2, 30)                # awful but only n=30
        store.add_variant(con3, "flat", knobs, "candidate")
        seed_games(con3, "flat", 400, 800)              # 50%, at max_games
        changed3 = runner.adjudicate(con3, store.champion(con3),
                                     store.active(con3, "null")[0])

        def status3(name):
            return con3.execute("SELECT status FROM variants WHERE name=?",
                                (name,)).fetchone()["status"]

        check("under-sampled candidate is left alone", status3("early"), "active")
        check("undecided candidate retires at max_games", status3("flat"), "retired")
        check("no promotion from a level candidate", changed3, False)

        # The promote rule must be strictly one-sided.
        pct, lo, hi = store.wilson(260, 400)
        check("promote rule is one-sided (better beats the null's upper bound)",
              lo > nhi, True)
        pct2, lo2, hi2 = store.wilson(20, 100)
        check("prune rule is one-sided (worse falls under the null's lower bound)",
              hi2 < nlo, True)
    finally:
        store.DB, runner.BOTS = old_db, old_bots
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\nFAILURES:\n  " + "\n  ".join(failures))
        return 1
    print("\nall adjudicator rules hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
