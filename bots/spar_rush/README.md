# spar_rush — SPARRING PARTNER, NEVER A SUBMISSION

Our own engine with `SIEGE_START = 5`. Do not submit it, do not stack it.

It exists because the ladder's top teams put a gun on the enemy core at t19-t24
and nothing in `bots/` did anything remotely like it, so no local gate could see
how a candidate handles a rush. It immediately found a hole that 500+ games
against our own lineage had completely hidden:

| vs spar_rush | win rate | core kills |
|---|---|---|
| generalist-v3 (live at the time) | **39%** (CI 32-46) | 58-91 |
| exp_early_siege | 49-52% | 70-78 |
| exp_siege_on_sight | 52% | 76-69 |

See the mandatory-gate section in `WORKFLOW.md`.
