# Route Integrity experiment

Parent: `exp_waller_route_light`, itself an exact-v9 branch.

Production v9 replays exposed a four-link conveyor cycle trapping a
seven-conveyor disconnected branch in a round-1000 titanium loss. The inherited
router seeds every visible friendly conveyor as a
completed trunk without following its facing. This branch keeps the bounded
waller-only late repair and makes one opening-router change: a visible merge
target is accepted only if its facing chain reaches the core, or if the chain
leaves vision after making strict progress toward the core on every observed
edge. Visible cycles and dead ends are rejected.

The rule uses only sensed topology and facing. It contains no map, side,
dimension, opponent, or remote-match fingerprint. It is a local experiment,
not packaged, uploaded, activated, or copied to root.
