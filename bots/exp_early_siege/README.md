# exp_early_siege  (Variant A — superseded by exp_siege_on_sight)

Parent: `bots/generalist-v3`. One constant: `SIEGE_START = 45 -> 25`.

Ladder measurement 2026-08-01: the top two teams put a gun within 6 tiles of the
enemy core at t19 (Powered by SmartFridge) and t24 (Pantheon); we managed t60.
An econ probe showed titanium is NEVER the constraint — the core holds >120 Ti
from round 0 and peaks at 470 by t45 — so this constant alone was making us
arrive last while sitting on unspent resources.

| gate (336 / 168 games) | result | core kills |
|---|---|---|
| vs generalist-v3 | 61% (CI 55-66) | 183-111 |
| vs OogwayOld | 90% (control 86%) | 150-9 |
| vs lastpop2 | 93% (control 90%) | 151-13 |
| vs spar_rush | 49-52% (two runs) | 70-78 / 79-71 |

First gun on the enemy core moved t84 -> t58. Superseded by
`exp_siege_on_sight`, which beat this bot 63% head to head.
Tests: `tests/test_early_siege.py`.
