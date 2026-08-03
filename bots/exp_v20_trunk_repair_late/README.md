# v20 route proof + near-core route finish

Independent child of `bots/exp_v18_spawn_route_proof` (remote submission v19).
Conveyor routing no
longer treats every visible non-loop conveyor as a completed trunk. It merges
only into a chain visibly reaching the core, or a chain that leaves vision
after every observed edge makes strict Manhattan progress toward the core.
Combat, roles, spawning, and the round-40 economy transition are unchanged.

An economy builder remembers an interrupted conveyor head only when at most
four Manhattan links remain to the core footprint. It advances the commitment
whenever a segment is built or distance falls, and clears after 24 rounds with
no progress. Longer routes retain the parent's memoryless behavior. This ports
Pantheon's economic route-cost and TTL ideas without map/opponent fingerprints.

Fresh production 2.3.3 gates (21 maps, four seeds, both sides):

| Gate | Result | Core kills | v19 baseline |
|---|---:|---:|---:|
| exact v19 route parent | 88/168 (52.4%) | 72-69 | parity gate |
| vs `spar_rush` | 158/168 (94.0%) | 158-3 | 152/168 |
| vs `oogbest-v6` | 142/168 (84.5%) | 138-19 | 148/168 |
| vs `meta-generalist-v1` | 155/168 (92.3%) | 152-12 | 142/168 |

Across the fixed-source parent gate it collected 193 more titanium per game and
won 15/24 round-1000 games, with +839 collected titanium in those long games.
Sixteen side-swapped Bridge replays increased connected conveyors 1.56 to 2.06
while reducing disconnected conveyors 23.25 to 4.00, dead ends 2.38 to 0.81,
and post-round-40 conveyors 16.00 to 1.62. Team-A connected routes improved
from 0.00 to 2.12. Deterministic coverage is in
`tests/test_v19_near_core_finish.py`. This candidate is local and inactive.
