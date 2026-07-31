# Claude operating brief

Read `HANDOFF.md` first, then `WORKFLOW.md`. Keep both current by rewriting
sections in place; never append diary-style logs.

## Current state

- Live submission: v89, source frozen at `bots/generalist-v2`.
- Next local candidate: `bots/generalist-v3`; package
  `generalist-v3.zip`; evidence `generalist_v3_results.json`.
- Root sources and `bot.zip` are historical v88. Do not replace them.
- Engine: staging `fcode 2.3.2.dev29`, 21 synced maps.
- Never upload, queue matches, activate, or replace root without fresh,
  explicit user approval.

## Required iteration method

1. Plan before code. Classify new losses across unrelated opponents/maps into
   general failure mechanisms.
2. Never fingerprint map name, dimensions, side order, opponent, or one replay.
   React only to observable state.
3. Copy the frozen parent into one independent experiment per hypothesis.
   Preserve openings and unrelated behavior.
4. Add deterministic mechanism tests. For rare behavior, instrument a
   disposable trace copy and require replay proof that it actually activated;
   reject win-rate changes from inactive code as noise.
5. Gate in order: compile/protocol tests; 12-game crash screen; 168-game
   both-side parent gate; 168 games each against champion, lastpop2, and
   OogwayOld. Require nonnegative core-kill differential and no opponent
   regression over five percentage points from a fresh control.
6. Stack only independently passing changes, one at a time, then rerun every
   gate. Record rejected mechanisms and why.
7. Freeze/package winners separately; verify ZIP contents byte-for-byte,
   `git diff --check`, and attempt the legacy evaluator while reporting its
   known multi-file import incompatibility honestly.

Use `live_replay_audit.py` for batch replay categories and `gate.py` for dev29
JSON metrics/private replay paths. Treat ladder results as confirmation, never
as the sole promotion signal. Preserve unrelated dirty-worktree changes and
stage explicit paths only.

## Commands

Run the real engine in WSL:

```bash
cd /mnt/c/Users/subodh/Downloads/fcode
source ~/.venvs/fcode/bin/activate
python gate.py generalist-v3 generalist-v2 4 quiet
python gate.py generalist-v3 champion 4 quiet
python gate.py generalist-v3 lastpop2 4 quiet
python gate.py generalist-v3 OogwayOld 4 quiet
```

The exact v3 results, hashes, caveat about second-family activation, and next
remote-validation decision are at the top of `HANDOFF.md`.
