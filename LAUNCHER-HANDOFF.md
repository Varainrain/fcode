# Launcher tech — what works, what doesn't, and what's left (2026-08-03)

Thirteen attempts, all rejected. Best 45% vs live v22. This is everything you
need to finish it without repeating any of it. Branch: `claude/measurement-fixes`.

## What Pantheon actually does (traced from replays, not guessed)

```
t1   launcher built 2 tiles from THEIR core (18 from ours), OFF the core->core axis
t2   builder 3  (3,4) -> (4,10)   jumped 7
t3   builder 5  (2,4) -> (4,10)   jumped 8   <- same landing tile, a rally point
t4   builder 8  (4,4) -> (1,6)    jumped 5
t5   builder 11 (4,15)-> (1,17)   jumped 5
then the thrown builder BOLTS: 14,13,12,11,10,9,8,7,6,5 — one tile per turn,
no detour, no economy work — and the first gunner lands t13 at distance 4.
```

Three to four throws per game, all in the first five turns. The throw buys ~6
tiles; the bolt does the rest. Without it that is a t21 gun.

Engine facts, measured directly:
- pickup range 1-2 tiles, throw up to 7, 1-turn cooldown, 20 Ti (cost scales)
- `LAUNCHER_VISION_RADIUS_SQ` 26 vs a builder's 20
- ammo converts 1:1, same turn, once per team per turn

## THREE LANDMINES IN OUR CODEBASE — hit these and the mechanism silently dies

1. **Non-builder entities have no map.** Every entity gets its own `Player` and
   only `builderBot()` calls `setupMap()`, so in a launcher/gunner/sentinel
   `mapPf.enemyCorePos` and `teamCore` are permanently `None`. A throw routine
   written against `mapPf.enemyCorePos` compiles, runs, and never fires — no
   error. Cost me a whole day. Fix is in `exp_v23_fix_storemap`: builders publish
   the enemy core to **slot 9**, non-builders read it. Slots 0-8 are taken
   (0 numSpawned, 1-6 map share, 7 team core, 8 symmetry mask).
2. **`mapPf.moveTo` dead-ends against our own conveyor ring** — our conveyors are
   impassable to us. It then waits `2 + (id % 8)` turns (3-10!) before trying a
   **random** direction. HANDOFF records this costing aegis-v1 seven turns "2
   tiles short". Sidestep fix in `exp_v23_fix_stuck` (neutral, safe).
3. **Our own buildings block our own exit.** Placing the pad on the tile nearest
   the enemy — the obvious choice — parks it in the doorway every builder walks
   through. Traced: a builder bouncing 22<->21 for eight turns where the pad-less
   parent marched straight out. Put the pad **one tile perpendicular** to the
   core->enemy axis. 41% of our conveyors also land in that corridor.

## What each attempt proved (don't redo these)

| variant | result | what it proved |
|---|---|---|
| v1 pad gated on resources+role | 52% | pad went up too late to matter |
| v2 + routing, 6 pads by accident | — | **pad COUNT is not the issue**: six beat one by nothing |
| v3 pad t1, 1/game, right placement | — | **0 launches** — landmine 1 |
| v4 target via store slot 9 | — | 8.5 launches from t2, but first gun t24->t26: it was throwing the ECONOMY crew |
| v5 attackers claim rides (slot 10) | 40% | 17.1 launches, first gun t20. Riders kept coming back for more |
| v6 one-ride-per-builder flag | — | 0.8 launches: flag set on CLAIM, and one claim survives per turn, so losers disqualify themselves |
| v7 geometry (throw must clear the radius) | 38% | 8.8 launches, first gun t20 |
| v8 rider given the store fallback | — | **deadlock**: riders waited at the pad t6->t89 |
| v9 wait timeout | — | oscillation 21<->22 all game |
| v11 no detour, claim only if already beside it | 45% | **3.8 launches/game = Pantheon's exact rate** |
| v12 pad off the exit lane | 45% | bolt restored (22,21,20,18,17,...) — landmine 3 |
| combo v7 + forward armour | 40% | armour does not rescue it |
| eye (sensor only, no throwing) | 43% | **symmetry DOES resolve 2-3 turns earlier** (measured: 1,2,3,3,3 vs 4,5,5,5,5) — real, but does not pay |

## What is still unsolved — the actual remaining problem

**Our thrown builders do not bolt.** Pantheon's marches one tile per turn
straight in. Ours lands and re-enters `runAttack`, whose `findGunnerSpot` pulls
it sideways, and if it drifts back near the pad the ride logic grabs it again.
Every version that fixed the ride broke the march and vice versa.

If you want to finish this, that is the piece: **a thrown builder should be in a
committed "bolt" state — straight-line march to the enemy core, no gunner-spot
search, no re-riding — until it is inside the firing band.** Detect the landing
(position jumped >1 tile in a turn) and latch the state.

## Also worth knowing

- v24 beat Pantheon 3-2 and CtrlAltDefeat 3-2 in fresh unrated scrims; v22 went
  0-5 vs Pantheon the same day. v24 is NOT a regression — the raw 80%-vs-60%
  ladder gap is schedule (v24 played 40 rounds vs Pantheon). Like-for-like it is
  -5 points at 1.2 sigma.
- Our first gun vs Pantheon is now **t21 to their t14** with zero launchers,
  where this morning it was t31 to t13. v23/v24 already bought most of the tempo
  the launcher was supposed to buy — which is why the launcher's remaining upside
  may be small.
- **The one asymmetry left: they build 3.2 barriers/game, we build none.**

## Tools added

- `builder_trace.py` — attributes each building to the builder standing next to
  it, giving a per-builder timeline. This is what cracked Orizon, Prompt
  Engineers and Pantheon. Use it before theorising.
- `heal_audit.py` — per-side core damage vs healing, offline, no API needed.
- oarena (github.com/frkns/oarena) for 2D replay viewing. Its venv needs a `.pth`
  pointing at the fcode site-packages, because a venv created from another venv
  does not inherit it. `oarena serve` on :7878.
