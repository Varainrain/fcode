# v19 route proof + sticky route repair

Independent child of `bots/exp_v18_spawn_discipline`. Conveyor routing no
longer treats every visible non-loop conveyor as a completed trunk. It merges
only into a chain visibly reaching the core, or a chain that leaves vision
after every observed edge makes strict Manhattan progress toward the core.
Combat, roles, spawning, and the round-40 economy transition are unchanged.

An economy builder now remembers the first missing conveyor link after combat
interrupts it. It returns to that head, advances the commitment whenever a
segment is built or distance falls, and clears the target after 24 rounds with
no progress. This ports Pantheon's bounded route-repair/TTL idea without shared
state, opponent fingerprints, or map fingerprints.

Fresh production 2.3.3 gates (21 maps, four seeds, both sides):

| Gate | Result | Core kills | spawn-parent baseline |
|---|---:|---:|---:|
| exact spawn parent | 86/168 (51.2%) | 69-68 | 50% expectation |
| vs `spar_rush` | 152/168 (90.5%) | 151-13 | 151/168 |
| vs `oogbest-v6` | 148/168 (88.1%) | 141-18 | 146/168 |
| vs `meta-generalist-v1` | 142/168 (84.5%) | 142-21 | 146/168 |
| String/Bridge focus | 21/32 (65.6%) | 15-7 | 18/32 prior block |

Across the 168 parent games it collected 10 more titanium per game, retained 36
more, and used 1.2 fewer buildings. It won 10/19 round-1000 games. Sixteen
paired Bridge replays preserved connected routes and served harvesters while
reducing total conveyors 18.94 to 14.69, disconnected conveyors 16.81 to 12.56,
and post-round-40 construction 10.00 to 5.94. Deterministic coverage is in
`tests/test_v18_spawn_route_proof.py`. This candidate is local and inactive.
