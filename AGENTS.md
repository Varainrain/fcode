
## Team memory

This repo has a shared team memory MCP server. Other engineers' hard-won
knowledge lives there.

- Call `recall` before any non-trivial task and before assuming how something
  works.
- Call `remember` whenever I correct you on a convention, a pitfall, or a
  non-obvious reason for how something is built. Record the WHY, not just the
  rule.
- Do not record one-off task instructions or anything specific to the current
  ticket.

## Bot iteration policy

For every non-trivial bot iteration or rebuild, start with an explicit
evidence-driven plan. Diagnose losses as possible general weaknesses, never as
instructions to target a map name, map dimensions, opponent identity, or one
matchup. Implement each reactive hypothesis independently from the current
frozen baseline, require deterministic mechanism tests and graduated gates,
and stack only independently winning features. Re-gate the complete stack
after every addition. Preserve the baseline and do not upload, queue, replace
root, or activate without explicit user approval.

Gate against the CURRENT LIVE BOT, not `bots/champion` (stale = `oogerebus3`;
it inverted the ranking of ten bots). Always say which reference a win rate
came from. Never read per-map gate lines — identical code swings 1/8 to 6/8
on them. A 12-game screen eliminates, never promotes. Because ~half the map
pool is seat-decided between closely matched bots, the gate compresses small
real gains toward 50%: treat 52-54% as unresolved, not as refuted. Rerun the
identical-code control (WORKFLOW.md) after any engine bump.
