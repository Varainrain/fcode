# Team workflow — bots, champion, gate

How we develop without merge hell and without shipping regressions. One branch,
folder-per-bot, a frozen champion baseline, and a gate script that decides
promotions by data instead of vibes.

## Layout

```
main.py, ...              <- historical root package; may differ from live
bots/
  champion/               <- frozen, hash-verified reference opponent
  exp_trans_40/           <- shipped-v8 source lineage / current frozen parent
  meta-generalist-v1/     <- current local frozen candidate
  <yourbot>/              <- your experiment: a folder with main.py (+ any modules)
maps/                     <- the current 21-map league pool (.map26)
gate.py                   <- the promotion gate
gate_results.csv          <- every gate game ever run, appended automatically
fcode.toml                <- points the fcode CLI at bots/ and maps/
```

Every strategy/experiment is its own folder under `bots/`. Don't edit someone
else's bot folder — copy it, rename it, hack on your copy. Multiple strategies
coexist; nothing gets clobbered by a merge.

## Required generalist iteration cycle

Every non-trivial iteration or rebuild starts with a written plan before code
changes. The plan must identify the observed failure categories, the proposed
general mechanism behind each one, the independent experiments, and the
evidence required to accept or reject each experiment.

1. Freeze the current proven bot and record its source/archive hashes.
2. Review losses across maps, sides, seeds, and unrelated opponent families.
   Treat a losing replay as diagnostic evidence for a possible bot weakness,
   not as a target to encode.
3. Reject hypotheses that depend on map names, map dimensions, opponent
   identity, side order, or one favorable matchup. Prefer observable game state
   such as threats, congestion, resource flow, reachable firing plans, damage,
   and positional progress.
4. Build each hypothesis independently from the same frozen baseline. Do not
   combine unproven features, because a winning component can hide a regression
   from another component.
5. Add deterministic tests for the mechanism itself, including activation,
   non-activation, state cleanup, death/reassignment, and boundary timing where
   relevant.
6. Use graduated gates:
   - compile/protocol/deterministic tests and a fast crash screen;
   - full both-side head-to-head against the frozen parent;
   - full both-side gates against multiple unrelated opponent families;
   - focused replay/metric checks proving the intended mechanism actually
     caused the improvement.
7. Accept a feature only when it passes its aggregate regression thresholds and
   improves the relevant failure category across at least two unrelated
   opponent families. A single-map or single-opponent gain is investigation
   material, never promotion evidence.
8. Stack accepted features one at a time in a declared order. After every
   addition, rerun all parent and opponent gates; remove any feature that fails
   when combined.
9. Freeze and package the final passing stack separately. Keep root sources,
   the active submission, and the previous frozen baseline unchanged until the
   complete stack passes and the user explicitly approves the next external
   action.
10. After an engine or server-map update, mark older totals historical and
    rerun the relevant gates before promotion.

Record rejected hypotheses and why they failed, so future work learns from
them without reviving them under a new name.

## Making a change

1. Copy the exact frozen candidate named in `HANDOFF.md`:
   `cp -r bots/meta-generalist-v1 bots/mybot`.
2. Hack on `bots/mybot/`.
3. Sanity-run one game: `fcode run mybot champion maps/duel.map26 --seed 1 --tle 10`
4. Run the gate: `python gate.py mybot`

## The gate rule

```
python gate.py <candidate>
```

runs the candidate vs the frozen `bots/champion` on all maps x 4 seeds x
both sides, in parallel, and prints per-map results plus a
verdict:

- **PROMOTE** — win rate >= 55%
- **REJECT** — anything less

**Why 55% and not 50%:** single games are extremely noisy (map/side/seed
variance). Over 60 games, ~50% is indistinguishable from "changed nothing".
55%+ is a real edge. If your change "should" help but gates at 48-54%, it's
not proven — iterate or drop it, don't ship it.

Quick screen while iterating (12 games, 6 maps): `python gate.py mybot champion 1 fast`
Head-to-head between any two bots: `python gate.py botA botB`

**Measurement standard — results only compare if we all run the same setup:**
- same engine (`pip show fcode` before trusting any number; update command is
  pinned in the Discord staging announcements)
- current server maps (`fcode maps list`, then `fcode maps sync` when anything
  is missing or outdated)
- `--tle 10` (the server's real per-turn budget — gate.py does this; ad-hoc
  `fcode run` tests must pass it explicitly, the default is tighter and
  punishes compute-heavy bots unrealistically)
- the full `maps/` pool, both sides, 4+ seeds (168+ games)
Two of us measured the same matchup 26 points apart once (kfort vs krb,
72% vs 46%) — environment drift, not variance. Check setup first, argue
strategy second.

### MANDATORY: gate against `bots/spar_rush` as well as the live bot

`spar_rush` is our own engine with `SIEGE_START = 5` — a sparring partner, never
a submission. It exists because the ladder's top two (Powered by SmartFridge,
Pantheon) put a gun on the enemy core at t19-t24 and NOTHING in `bots/` did
anything remotely like it, so no local gate could see how a candidate handles a
rush. It found a hole 500+ games against our own lineage had completely hidden:

| vs `spar_rush` | win rate | core kills |
|---|---|---|
| historical `generalist-v3` | **39%** (CI 32-46) | 58-91 |
| shipped-v8 source `exp_trans_40` | 55% (168) | 85-64 |
| `meta-generalist-v1` | 52% (168) | 81-64 |

A candidate that only ever fights our own lineage is being measured against an
archetype that no longer exists at the top of the ladder. Run both:

```
python gate.py <candidate> meta-generalist-v1 8 quiet # 336 games, local parent
python gate.py <candidate> spar_rush 4 quiet       # does it survive a rush?
```

Keep a fresh parent control next to each - the numbers only mean something as a
difference.

### Measured noise floor (identical-code control, 2026-08-01, engine 2.3.3)

`bots/exp_emergency_countertrade` is byte-identical to `bots/generalist-v3`
(md5 `bf31fa04b650`). Gating it against itself measures the harness, since every
result is pure noise. Rerun this control after any engine bump — it is the only
way to know what a number means.

- **Aggregate is well calibrated: 50% at n=168, 52% at n=336.** Trust the
  headline verdict to about +/-2-3%. The 55% bar is sound.
- **Per-map lines are NOISE. Do not read them.** Identical code produced
  `sweden` 1/8 and `longship` 6/8 in the same run. Any claim of the form
  "we're weak on <map>" taken from a gate needs its own dedicated experiment;
  a per-map line at n=8 or n=16 supports nothing.
- **Seat bias is large and pool-wide.** With identical code the second player
  won 197/336 = 59% overall. This aggregate is solid.
- **Seat-locked maps (verified by direct `fcode run`, BOTH argument orders,
  20 games each, identical code):** `duel`, `showdown`, `skerry`, `strait` all
  went **20/20 to the second-listed bot**. `sprint` is balanced (9/20). These
  four cannot distinguish closely matched bots at all.
- **DO NOT DERIVE PER-MAP SEAT NUMBERS FROM gate.py OUTPUT — its per-game
  "<bot> first" label does not reflect actual play order.** It reported
  `strait` as balanced 8/16 when direct runs show 20/20, and its 4-seed and
  8-seed logs contradicted each other. The AGGREGATE verdict is still sound
  (identical code lands at 50-52%, which requires genuine side-alternation),
  so the bug is in logging, not in what it plays. Measure seat effects with
  scripts/seat_check.sh, never by parsing the gate log.
- Seat bias is **bounded by skill**: across a large gap (generalist-v3 vs
  OogwayOld, 86-14) skill won 29/32 on the seat-locked maps. The seat only
  decides between *closely matched* bots.

**Consequence for iteration — this is the important part.** The changes we
actually test are small deltas, which IS the closely-matched regime. On roughly
half the pool those games are decided by seat, and because the gate plays both
sides they average to a forced ~50%. So the gate dilutes exactly the improvement
it is meant to detect: a real +3% edge can land in the 45-60% "unproven" band
and be discarded. When a change gates at 52-54%, that is NOT evidence it did
nothing — rerun it on the balanced maps before dropping it.

Do not describe this as "RNG" or fix it with more seeds. On `duel` the seed is
inert; extra seeds just produce more identical games.

### Choosing a reference opponent

**`bots/champion` is stale (= `oogerebus3`) and must not be used as a default
reference.** Screened against it, ten bots scored 91-100% and then lost to the
live bot; `OogwayNEW` screened 83% and lost 21-79 over 168 games. The reference
inverted the ranking. Gate against the CURRENT LIVE BOT unless you have a
specific reason not to, and state which reference a number came from — a win
rate is meaningless without it.

A cheap screen can only ELIMINATE (a bot at 0-25% is genuinely broken). It
cannot promote: identical code reads up to 67% at n=12. Never advance a bot on
screen numbers alone.

## Promotion procedure

1. Pass the frozen-parent and all broad gates in the required cycle.
2. Freeze source, results, and a byte-verified ZIP under a new version.
3. With fresh user approval, upload it **inactive** and run the declared
   unranked replay sample.
4. If the live threshold passes, request separate approval before activation
   or root replacement. Otherwise leave the current submission/root unchanged.

`bots/champion/` is a stable reference opponent, not automatically the active
submission. Nobody edits it casually. `live_baseline.json` records its exact
hashes, and `gate.py` refuses to use a drifted default champion.

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
