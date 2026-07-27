# lastpop2 — sparring clone of lastpopperian_ (45% vs frozen-erebus-v1; real ~60%)

USABLE for sparring, but read the caveat: it is ~15 points weaker than the
real opponent, so treat a win against it as necessary, not sufficient.

Progress this session: 8% -> 25% -> 33% -> 45%.

## Their pattern (parsed from 5 of their wins, replay_stats.py)

| map    | builders | home sentinel | 1st doorstep gun | attack guns   | we die |
|--------|----------|---------------|------------------|---------------|--------|
| aurora | 4        | t7            | t59              | 4 @ d3-5 diag | t90    |
| strait | 4        | t13           | t59              | 3 @ d3-4      | t86    |
| bridge | 3        | t4            | t82              | 4 @ d1-3      | t107   |
| twins  | 4        | t13           | t84              | 4 @ d3-5 diag | t109   |
| hive   | 3        | t7            | t74              | 3 @ d2-4      | t100   |

NOT a rusher. krb (t29 waves) was the wrong proxy for every anti-rush
number we produced this week, INCLUDING oogerebus3's tuning.

## The trait that mattered most: DISCIPLINE
On hive the real bot won at t90 with FOUR gunners. An earlier version of
this clone inherited our champion's opportunistic brawler reflex, built
EIGHTEEN, and lost at t186 — the extra guns drain titanium and the SHARED
ammo pool (2/shot) that the deliberate siege needs. Clone mined 950 vs the
champion's 2040. With skirmishing switched off it won at t147 with ONE
gunner and 29 total buildings against the champion's 110.
(Note: applying the same damping to OUR champion — bots/disc-v1, infra
attack score 8 -> 3 — gated 49% over 168 games. A wash. Their discipline
works inside their design; it is not a free win bolted onto ours.)

## Still missing (the remaining ~15 points)
How 3-4 builders sustain a rebuilt siege AND an economy. Their guns get
REBUILT indefinitely — bridge: the same seat 12 times — while ours are
placed once. That persistence is probably the gap.
