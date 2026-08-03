# v17 gun-control experiment

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
candidate only; it has not been packaged, uploaded, or activated.
