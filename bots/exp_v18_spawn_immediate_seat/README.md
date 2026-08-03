# v18 spawn discipline + immediate siege seat

Independent child of `bots/exp_v18_spawn_discipline`. Direct siege now prefers
a legal gunner placement it can build this turn before walking toward another
equivalent firing plan, and it rejects seats occupied by a builder. Targeting,
movement, routing, defense, and spawning are otherwise unchanged.

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
