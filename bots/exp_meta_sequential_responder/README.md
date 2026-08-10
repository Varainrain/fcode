# Sequential Home Responder experiment

Parent: exact active-v9 source, `meta-generalist-v1`.

Across the latest 50 production games, 25 losses ended by core destruction and
23 of those were gunner-only attacks. The existing single responder remains
locked to the lexicographically first live threat after a friendly gun covers
it, leaving later core-firing turrets unanswered.

This experiment changes only core threat selection. It keeps exactly one local
responder, but selects the first threat not covered by a friendly gunner; when
all are covered, it retains the deterministic first threat and heals normally.
No recall, spawning, economy, siege, counter placement, store slot, map,
dimension, side, or opponent behavior changes.

Local experiment only. It is not packaged, uploaded, activated, or copied to
root.
