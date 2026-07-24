# Team workflow — bots, champion, gate

How we develop without merge hell and without shipping regressions. One branch,
folder-per-bot, a frozen champion baseline, and a gate script that decides
promotions by data instead of vibes.

## Layout

```
main.py, defend.py, ...   <- the CURRENT LADDER BOT (what fcode submit ships)
bots/
  champion/               <- FROZEN copy of the ladder bot. Never edit directly.
  <yourbot>/              <- your experiment: a folder with main.py (+ any modules)
maps/                     <- the 15 league maps (.map26)
gate.py                   <- the promotion gate
gate_results.csv          <- every gate game ever run, appended automatically
fcode.toml                <- points the fcode CLI at bots/ and maps/
```

Every strategy/experiment is its own folder under `bots/`. Don't edit someone
else's bot folder — copy it, rename it, hack on your copy. Multiple strategies
coexist; nothing gets clobbered by a merge.

## Making a change

1. Copy the current best as your starting point:
   `cp -r bots/champion bots/mybot` (or copy the root bot files into `bots/mybot/`).
2. Hack on `bots/mybot/`.
3. Sanity-run one game: `fcode run mybot champion maps/duel.map26 --seed 1`
4. Run the gate: `python gate.py mybot`

## The gate rule

```
python gate.py <candidate>
```

runs the candidate vs the frozen `bots/champion` on all 15 maps x 2 seeds x
both sides = **60 games**, in parallel, and prints per-map results plus a
verdict:

- **PROMOTE** — win rate >= 55%
- **REJECT** — anything less

**Why 55% and not 50%:** single games are extremely noisy (map/side/seed
variance). Over 60 games, ~50% is indistinguishable from "changed nothing".
55%+ is a real edge. If your change "should" help but gates at 48-54%, it's
not proven — iterate or drop it, don't ship it.

Quick screen while iterating (24 games, 6 maps): `python gate.py mybot champion 1 fast`
Head-to-head between any two bots: `python gate.py botA botB`

## Promotion procedure

1. `python gate.py mybot` says PROMOTE.
2. Copy `bots/mybot/*` over the root bot files, submit to the ladder.
3. Watch real matches. **Live results override the gate** — a lab PROMOTE that
   loses rating on the ladder gets reverted, no argument.
4. Once it holds up live, freeze it: copy the new bot over `bots/champion/`
   (same commit, so champion always == what's proven on the ladder).

The champion only ever moves forward through steps 1-4. Nobody edits
`bots/champion/` directly.

## War Room dashboard

`python dashboard.py` then open http://localhost:8642 — live team rating,
rank, rating sparkline, match feed with per-match ELO, a rival-scouting
panel (edit `NEW_TEAM` at the top to pick who), the repo's recent commits,
and a Battle button that queues unrated matches (max 5 per 10 min,
rate-limit is shared team-wide). Needs the fcode CLI logged in (`fcode
login`) — same data for every team member. First load after a cold start
shows last-known numbers instantly and refreshes live within ~10s.

## Practical notes

- Engine moves fast (2.2.0.devNN via test.pypi, breaking changes land without
  warning). Check `pip show fcode` before trusting any numbers, and re-gate
  after every engine bump — old results don't carry over.
- fcode suppresses bot stdout in local runs. Debug with file logging or
  `draw_indicator_line/dot`, not prints.
- `get_cpu_time_elapsed()` returns 0 locally (server-only). Profile with
  `time.perf_counter_ns`.
- Store writes are buffered one round — team counters lag, N same-round
  builders can overshoot a global cap.
- Fixed seeds make runs reproducible; that's why the gate reports per-map,
  per-seed lines and logs everything to `gate_results.csv`.
