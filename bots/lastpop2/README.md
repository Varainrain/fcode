# lastpop2 — WIP clone of lastpopperian_ (NOT faithful yet: 33% vs champion, real is ~60%)

Do NOT gate defensive fixes against this yet — it is much weaker than the
real opponent and would give false confidence.

## What the replays actually show (this part IS solid)
Parsed from five of their wins (67fecf4c g1-4, 1d28bf18 g2) with
replay_stats.py, separating their HOME turrets from their ATTACK turrets
by distance to OUR core:

| map    | their builders | home sentinel | 1st doorstep gun | attack guns    | we die |
|--------|----------------|---------------|------------------|----------------|--------|
| aurora | 4              | t7            | t59              | 4 @ d3-5 diag  | t90    |
| strait | 4              | t13           | t59              | 3 @ d3-4       | t86    |
| bridge | 3              | t4            | t82              | 4 @ d1-3       | t107   |
| twins  | 4              | t13           | t84              | 4 @ d3-5 diag  | t109   |
| hive   | 3              | t7            | t74              | 3 @ d2-4       | t100   |

* THEY ARE NOT A RUSHER. krb (t29 waves) was the wrong proxy for every
  anti-rush number we produced this week, including oogerebus3's tuning.
* One home sentinel t4-13, ~4-5 tiles out, enemy-facing. Covers the
  APPROACH LANE, not the doorstep.
* At t45-70 one or two builders permanently leave the economy, walk over,
  and seat gunners at manhattan 2-5 from our core, DIAGONALS PREFERRED
  (our ring wall only denies orthogonals; a gunner two diagonal steps out
  still reaches). They rebuild every seat we kill - on bridge, the same
  tile 12 times. Core dies ~25 turns after the first seat lands.
* THEY DO NOT OUT-ECONOMY US: aurora 58 entities to our 92. We out-build
  them and lose anyway. Chasing "lean economy" cost me two iterations -
  the siege is the weapon, the small crew is just their handicap.

## What was tried
* bots/lastpop  (mech-v1 econ + siege)              -> 8%  econ never funds it
* bots/lastpop2 (champion econ + lean crew + siege) -> 33%
* bots/siege-v1 (champion, FULL econ + their siege) -> 29%  the siege does
  not transplant: two builders leave and never convert.

## Open question for whoever picks this up
How do 3-4 builders sustain a rebuilt siege AND an economy? That is the
part we have not reproduced, and it is the whole matchup.
