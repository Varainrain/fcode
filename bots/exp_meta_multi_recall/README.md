# Multi-Threat Early Soft Recall experiment

Parent: exact active-v9 source, `meta-generalist-v1`.

Fifteen of the latest 25 core-destruction losses began by round 60, and 24
involved multiple core-firing turrets. V9 raises its recall flag only after core
HP falls below 400, even when several verified shooters are already visible.

This experiment raises the existing soft recall when either the original
damaged-core condition holds or at least two real core-firing turrets are
visible. Recall semantics are unchanged: established siege seats keep firing;
only traveling or otherwise idle siegers return. One shooter without confirmed
damage does not trigger it. No defender count, economy, spawning, placement,
store slot, map, dimension, side, or opponent behavior changes.

Local experiment only. It is not packaged, uploaded, activated, or copied to
root.
