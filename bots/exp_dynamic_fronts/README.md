# exp_dynamic_fronts

Architectural probe from exact production v9 (`meta-generalist-v1`). It keeps
the proven opening, pathfinding, direct siege, and gunner targeting, but
replaces the single home responder and team-wide recall with up to three
distinct local defense fronts.

The core sizes fronts from verified core-reaching threats versus surviving
friendly gun coverage. It prefers non-siegers, leaves two local builders free
for economy, keeps both siegers on offense, targets weakly covered threats
deterministically, and limits each defender to eight countergun repair actions.
Slots 8-10 publish defender IDs, slot 12 their count, and slots 13-15 their
targets after the opening roles have latched locally.

Fresh production-engine gates:

- v9 parent: 92/168 (54.8%), core kills 74-62.
- `spar_rush`: 93/168 (55.4%), core kills 82-64.
- `oogbest-v6`: 89/168 (53.0%), core kills 84-63.

This is consistent evidence that fixed ownership was a vulnerability, but the
gain is only 1.8-3.6 percentage points over v9 controls. Hold as a chassis
probe; do not package, upload, or promote it.
