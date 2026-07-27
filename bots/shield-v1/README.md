# shield-v1 — REJECTED (2026-07-27)

frozen-erebus-v1 + **shield pieces**: guard conveyors on tiles orthogonally
adjacent to our OWN harvesters, so an enemy cannot plant a turret point-blank
on a mine. Motivation: the handoff notes BOTH Cambridge top-2 teams do the
guard-conveyor thing and we had only ever ringed the CORE, never harvesters.

Implemented as a **passive spare-action side effect** inside `passiveWall()`
(zero movement, zero state priority, Ti>=60 gate), reusing the existing
never-a-dead-end chaining rule unchanged — chosen because the measured lesson
is that the ~11pt cost is the RESTRICTION, not the walling.

## Gates (gate.py, 4 seeds / 168 games, engine 2.3.0.dev26)
| matchup | result | verdict |
|---|---|---|
| vs frozen-erebus-v1 | **86/168 = 51%** (kills 70-63) | REJECT (<55% bar) |
| vs krb | 104/168 = 62% | no gain — champion itself is 63% vs krb |

51% is inside the documented "45-60% = unproven" band = a tie. Kill diff was
mildly positive while win% was flat — the exact pattern the handoff says to
distrust.

Map splits (vs champion) were whack-a-mole, not a uniform lift: pinch 8/8,
jackpot 6/8, string 6/8 — but bridge 1/8, aurora 2/8, showdown 2/8, strait 2/8.

**Conclusion: harvester shielding is not a cheap win in fcode.** Plausible
reason it transfers poorly: in Cambridge the shield was cheap ROADS and turret
ammo was conveyor-FED (so denying feeder-adjacency mattered); fcode has no
roads and a global ammo pool, so an enemy gunner does not need to sit next to
our mine to function. Eleventh straight challenger to fail vs frozen-erebus-v1.
