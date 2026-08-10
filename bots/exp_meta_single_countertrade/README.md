# Single-Threat Countertrade experiment

Parent: exact active-v9 source, `meta-generalist-v1`.

The production audit found two core losses where one enemy gunner fired 44 and
83 times without being removed. V9 searches for a fully safe counter seat, but
its bounded exposed-seat fallback is disabled unless two core-firing turrets
already exist.

This experiment permits that existing bounded countertrade for one or more
visible core-firing turrets. The builder stand must remain outside every attack
pattern and the gunner seat may be exposed to at most one turret. All placement,
budget, responder, recall, economy, siege, spawning, and protocol behavior is
otherwise byte-identical to v9.

Local experiment only. It is not packaged, uploaded, activated, or copied to
root.
