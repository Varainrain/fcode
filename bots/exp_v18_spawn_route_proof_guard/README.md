# v18 spawn discipline + route proof + vision guard

Independent child of `bots/exp_v18_spawn_discipline`. Conveyor routing no
longer treats every visible non-loop conveyor as a completed trunk. It merges
only into a chain visibly reaching the core, or a chain that leaves vision
after every observed edge makes strict Manhattan progress toward the core.
Combat, roles, spawning, and the round-40 economy transition are unchanged.

The home-position planner also avoids querying core-ring occupants outside the
builder's current vision. This prevents the production `GameError` observed in
a paired Bridge replay without changing the selected home tile once visible.

Fresh production 2.3.3 gates (21 maps, four seeds, both sides):

| Gate | Result | Core kills | v18 baseline |
|---|---:|---:|---:|
| exact v18 head-to-head | 86/168 (51.2%) | 73-72 | 50% expectation |
| vs `spar_rush` | 151/168 (89.9%) | 150-11 | 154/168 |
| vs `oogbest-v6` | 146/168 (86.9%) | 143-15 | 145/168 |
| vs `meta-generalist-v1` | 146/168 (86.9%) | 144-17 | 144/168 |
| String/Bridge focus | 18/32 (56.2%) | 11-10 | head-to-head |

In the 12 round-1000 parent games it won eight, collected 434 more titanium
per game, retained 1,799 more titanium, and used 4.7 fewer units. In the focused
String/Bridge block it won four of five round-1000 games and collected 1,248
more titanium per game. Deterministic coverage is in
`tests/test_v18_spawn_discipline.py`. This candidate is local and inactive.
