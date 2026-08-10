# Reserve-gated Waller Route Repair

Parent: `exp_waller_route_light`, an exact-v9 branch.

The 50-game production audit confirmed that incomplete conveyor networks are a
general secondary weakness, but 25 of 27 losses were still core destructions.
This variant therefore changes only the late-repair reserve: the designated
non-attacking waller may repair an observed orphan route from round 120 only
when at least 200 titanium remains, rather than 100. Healing and home response
still override it, the repair stays bounded to eight links, and the opening,
siege, spawning, and combat logic are unchanged.

No map, dimension, side, opponent, or submission identity is inspected. This
is a local experiment only; it is not packaged, uploaded, activated, or copied
to root.
