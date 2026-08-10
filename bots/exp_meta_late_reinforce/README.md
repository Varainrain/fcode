# Late reinforcement experiment

Parent: frozen `exp_trans_40` (production v8 lineage).

This tests the measured top-meta production order without changing the opening:
the first two siegers still pressure immediately, all existing economy builders
stay in their normal lifecycle, and only builders born at or after the t40
economy transition join direct siege. The original waller remains the home
anchor. Recall, home response, safe counter-battery, spawning, economy scoring,
and pathfinding are byte-for-byte inherited.

Unlike `exp_meta_reinforce`, this does not recall established economy builders
or convert the whole population at once.
