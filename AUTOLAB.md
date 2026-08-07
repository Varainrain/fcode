# AUTOLAB — the self-iterating knob search

A search loop with no model in it. Start it, watch it from a dashboard, come
back later. It proposes knob changes to the chassis, plays them against a
champion, and promotes only what clears a *live-measured* noise floor.

**All of these must run from the repo root** — `python -m autolab.*` does not
resolve from anywhere else. Start here:

```
cd C:\Users\subodh\Downloads\fcode
python -m autolab.doctor
```

The doctor checks the directory, the map pool, the template, the engine, the
database and the port, plays one real game to prove the whole chain works, and
prints the fix for anything broken. Then:

```
python -m autolab.build_template
python -m autolab.verify_template
python -m autolab.runner
python -m autolab.dash
```

Run the runner and the dashboard in two windows. They are separate processes on
purpose: closing the dashboard does not stop the search, and the search does not
need the dashboard to run. (In `cmd.exe` do not paste a trailing `# comment` —
cmd has no comment syntax and passes it as an argument.)

**On this machine the engine lives in a WSL venv and is not on the Windows
PATH**, while the repo sits on the Windows filesystem. `autolab/engine.py`
resolves that automatically: it uses `fcode` directly if it is on PATH, and
otherwise shims each game through WSL. So you can stay in `cmd.exe`. Two
environment variables override it if the setup moves:

- `AUTOLAB_ACTIVATE` — the snippet that puts `fcode` on PATH inside WSL
  (default `source ~/.venvs/fcode/bin/activate`)
- `AUTOLAB_ENGINE` — force `native` or `wsl`

Running the dashboard *inside* WSL and browsing it from Windows is the one
combination that does not reliably work; run the dashboard on the Windows side.

## What it can and cannot do — read this before trusting it

**It can:** search the declared knob space, hold statistical discipline that no
human running `gate.py` by hand will hold, run unattended for hours, and refuse
to promote noise.

**It cannot invent a mechanism.** Every candidate is the champion with one knob
moved. It will never write `first_entity_on_ray` for you, notice that enemy
builders are worth zero in a scorer, or discover that costs scale with entity
count. New *mechanisms* still need someone to read a replay and write code —
that is the part a search cannot replace, and it is where all four of this
repo's real wins came from. What this removes is the part that was burning your
time and credits anyway: babysitting gates, pooling runs, computing intervals,
and re-deciding what counts as evidence.

**Widening the knob space is how you feed it.** When someone lands a new
mechanism, add its knob to `KNOB_SPEC` in `autolab/build_template.py` with an
anchored replacement, re-run the builder and the verifier, and the search picks
it up. `RAY_FIRST` is in there as a worked example — it is candidate `oa_a9`
from the 2026-08-06 attack session, expressed as a 0/1 knob.

## The one idea that makes it trustworthy

A **null** — a byte-identical copy of the champion under a different name —
plays in the arena alongside every candidate, on the same maps, at the same
rate. Its Wilson interval *is* the noise floor, measured live on the current
engine and map pool. Candidates are judged against that band, never against 50%.

This is not theoretical. Measured 2026-08-06 on engine 2.3.6: identical code
gated **61% / 49% / 50%** across three 120-game runs (pooled 53.3%, CI
48.2-58.4). A pipeline judging against a flat 55% bar would have "promoted" a
byte-identical bot roughly one run in three. The null costs about a third of the
compute and buys the only thing that makes the rest of it mean anything.

Decisions, all from the same two intervals:

| outcome | rule | default |
|---|---|---|
| **prune** | candidate's CI upper < null's CI lower | after 60 games |
| **promote** | candidate's CI lower > null's CI upper | after 400 games |
| **retire** | still overlapping the null | at 800 games |

On promotion the candidate becomes champion, a **fresh null is minted against
it**, all candidates are killed and the search restarts from the new vector — so
the noise floor is always measured against the bot currently being defended, not
an ancestor.

Two smaller guarantees hold the comparison together:

- **Maps and seats are a fixed rotation, not a random draw.** Every arm walks the
  same map cycle and flips seat each full pass, so two arms with equal game
  counts have played the same maps in both seats. Drawing maps at random lets one
  arm collect more of a seat-locked map than another, which shows up as a phantom
  several points wide.
- **A crashed or unparseable game is discarded, not scored.** `gate.py` counts
  those against the candidate; here the champion never sits in the candidate
  slot, so that convention would be a silent one-sided bias. Discards are logged.

Sample-size reality: at these settings a promotion needs a true effect around
ten points. That is the instrument's resolution, not a policy choice — a true
+5 needs roughly 1500 games per arm. Lower `min_promote` from the dashboard if
you want more promotions, and understand you are buying them with false ones.

## Ownership

Knobs are lane-tagged (`attack` / `core` / `econ`) and **the search runs the
attack lane only by default** — the others belong to ic3d and Oogway per
MODULES.md. The dashboard can widen it; get the lane owner's agreement first,
because a promoted `econ` knob is a change to someone else's module.

## When the chassis changes

Oogway pushes a new bot, so:

```bash
git pull
python -m autolab.build_template OogwayNEWNAME
python -m autolab.verify_template OogwayNEWNAME
```

Every anchor is asserted. If a line moved, the builder **fails loudly** rather
than quietly producing a bot that ignores half its knobs. Old games stay in the
database but the new champion starts a fresh null, because per PITFALL #18 an
engine or chassis change voids the previous numbers. `rebase <chassis>` in the
dashboard's command box does the same thing without stopping the runner.

## Files

| file | what it is |
|---|---|
| `autolab/build_template.py` | knob registry + anchored lift of the chassis into `bots/_template` |
| `autolab/verify_template.py` | proves the template at default knobs is byte-identical to the chassis |
| `autolab/runner.py` | the search loop: propose, play, prune, promote |
| `autolab/store.py` | SQLite: every variant, every game, the event log, the control table |
| `autolab/dash.py` | the dashboard on :8643 |
| `autolab/engine.py` | finds `fcode` — native, or shimmed through WSL |
| `autolab/doctor.py` | environment check; run this first when anything fails |
| `autolab/selftest.py` | deterministic test of the prune/promote/retire rules |
| `autolab/lab.db` | the database (gitignored — it is machine-local evidence) |

## Dashboard controls

- **pause / resume**, **workers ±2** — the runner polls these between batches.
- **lane toggles** — widen or narrow the search space.
- **command box**:
  - `try {"SEAT_TI": 60}` — queue a hand-chosen candidate (champion + that knob)
  - `kill lab_c1234` — retire a candidate now
  - `rebase OogwayAttack` — rebuild the template from a chassis

## Promoting out of the lab and into the team

The pipeline never touches `bots/OogwayAttack`, never uploads, never activates.
A promotion is a row in the database and a `lab_champ_*` folder. To ship one:
diff its `KNOBS` against the chassis defaults, write the knob change up with its
CI and game count, and hand it to Oogway like any other module change
(MODULES.md pipeline). A knob vector is a proposal, not a merge.
