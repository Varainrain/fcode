# Idle Late Route Repair experiment

**Promotion reject.** Parent gate on engine 2.3.3: 81/168 (48%), core kills
64-77. Round-1000 subset: 17/27 wins and mean titanium 4,017 versus 3,496.
Prioritizing the waller reduced but did not remove the midgame conversion cost.
The successor must not activate until a game is already a true stalemate.

Parent: frozen `meta-generalist-v1`. Immediate predecessor
`exp_late_route_repair` proved the mechanism but failed promotion: 83/168
(49.4%), core kills 64-79. It won 19/25 round-1000 games and collected 4,838
versus 2,785 mean titanium there, but score-six repair claims diverted brawlers.

This variant keeps the same facing-proven, bounded round-80 repair but changes
only ownership/priority:

- Prefer the existing wall-role builder, which the parent already forbids from
  normal attacks, whenever it is locally visible.
- Exclude both siegers and the active home responder.
- The waller retains the parent's route priority of six.
- A normal builder is only a fallback and receives score 1.5, below meaningful
  combat but above idle exploration.

Everything through round 79 remains parent behavior. No map, dimension, side,
opponent, or new store signal is used. Root, frozen parent, and live package are
untouched.
