# Meta Generalist v1 — local frozen candidate

Parent: production v8 source (`exp_trans_40`).

The only behavior change fixes gunner handling of the engine's separate builder
layer. Enemy builders on otherwise empty tiles are now valid current targets and
contribute the existing weight of 2 during rotation. Friendly builders remain
protected. No opening, economy, spawning, siege, recall, store, map, or opponent
logic changes.

Validation on local fcode 2.3.2.dev29:

- 200/336 (60%), core kills 181–127, versus v8.
- 88/168 (52%), core kills 81–64, versus `spar_rush`; v8 control was 92/168
  (55%), kills 85–64, so treat this matchup as neutral/slightly negative.
- 86/168 (51%), core kills 83–67, versus source-diverse `oogbest-v6`.

This folder and `meta-generalist-v1.zip` are local only. They are not root,
uploaded, queued, or active.
