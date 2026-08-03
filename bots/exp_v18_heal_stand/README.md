# v18 legal heal-stand experiment

Independent from the active v18 source. Production 2.3.3 permits builder
healing only on orthogonally adjacent tiles. The home selector now excludes the
four diagonal core corners where a defender could previously park but not heal.

Exact production v17 with only gunner targeting/rotation corrected:

- fire at lone enemy builders on the separate builder layer;
- prioritize enemy gunners whose real position/facing can hit our core;
- preserve the current facing on equal scores instead of spending 10 Ti on a
  lateral rotation.

Fresh production-engine gates (21 maps, four seeds, both sides):

| Gate | Candidate | Control | Core kills |
|---|---:|---:|---:|
| exact v17 head-to-head | 200/336 (59.5%) | 136/336 | 187-128 |
| vs `oogbest-v6` | 145/168 | 140/168 | candidate 143-18; control 139-25 |
| vs `meta-generalist-v1` | 144/168 | 142/168 | candidate 142-19; control 140-25 |

Deterministic tests are in `tests/test_v17_gunner_control.py`. This is a local
candidate packaged as submission v18 (`v17 gun-control candidate`). Eight
unranked series against replay-loss opponents scored 34/40. The first batch was
Pantheon 5-0, Askar City 5-0, team lazy 3-2, CtrlAltDefeat 4-1, and the one
piece 5-0; repeats were SmartFridge 3-2, team lazy 4-1, and CtrlAltDefeat 5-0.
v18 was explicitly promoted to the active ladder submission on 2026-08-03.
