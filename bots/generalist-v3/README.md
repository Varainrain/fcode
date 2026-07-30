# generalist-v3

Live-v89 source plus one bounded emergency countertrade:

- activates only with at least two visible turrets whose real attack patterns
  hit the core;
- keeps the responder's builder stand outside every visible attack pattern;
- permits a countergun seat covered by at most one turret;
- waives the 120-Ti reserve only for that one trade.

No opening, economy, spawning, siege, role, store, map, or opponent-specific
logic changed.

Dev29 gates (168 games each):

| opponent | wins | core kills |
|---|---:|---:|
| generalist-v2 | 90 (54%) | 79-69 |
| champion | 135 (80%) | 120-21 |
| lastpop2 | 153 (91%) | 147-14 |
| OogwayOld | 146 (87%) | 143-15 |

Mechanism trace: 4 completed countergun builds from 20 plans against champion.
Second-family builds were not reproduced locally, so inactive live validation
is still required. See `generalist_v3_results.json` and `HANDOFF.md`.
