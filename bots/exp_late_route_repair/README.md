# Late Route Repair experiment

Parent: frozen `meta-generalist-v1` (reported live on ladder).

This is the narrowed successor to rejected `exp_connected_economy`, whose
broad opening-router rewrite failed its 2.3.3 crash screen at 3/12 with core
kills 3-9.

The parent opening, route scoring, conveyor pathfinder, round-40 transition,
siege, defense, spawning, and store protocol remain unchanged through round 79.
Each builder only observes friendly harvester positions and conveyor facings in
its existing local cache.

From round 80 onward, if a built harvester's real facing chain does not reach
the core, one locally nearest non-sieger/non-responder may finish at most an
eight-link route while the bank has at least 100 titanium. The repair uses at
most the parent's original route score of six, so nearby direct threats retain
their score-ten priority. It may merge only into a facing-proven, empty trunk;
wrong-facing links, cycles, dead ends, loaded trunks, and defensive conveyors
that do not reach the core are rejected as merge targets. A cycle rooted at an
orphan harvester is repaired by removing one disconnected loop link and
rebuilding it toward a proven trunk. A friendly builder standing on the missing
link owns it and can build the walkable conveyor under itself.

No map name, dimensions, side, opponent identity, or new store slot is used.
Root sources, the frozen parent, and the live package are untouched.
