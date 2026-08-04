# Team workflow — bots, champion, gate

How we develop without merge hell and without shipping regressions. One branch,
folder-per-bot, a frozen champion baseline, and a gate script that decides
promotions by data instead of vibes.

## Layout

```
main.py, ...              <- historical root package; may differ from live
bots/
  champion/               <- frozen, hash-verified reference opponent
  generalist-v2/          <- exact live-v89 source
  generalist-v3/          <- next locally passing candidate
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

1. Copy the exact frozen parent named in `HANDOFF.md`:
   `cp -r bots/generalist-v2 bots/mybot`.
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

## ENGINE 2.3.4 REBALANCE — every pre-patch number is stale (2026-08-04)

`fcode 2.3.3 -> 2.3.4` changed six constants. Gunners were nerfed on FOUR axes at
once and sentinels buffed on two:

| constant | 2.3.3 | 2.3.4 |
|---|---:|---:|
| GUNNER_BASE_COST | 10 | **20** |
| GUNNER_DAMAGE | 10 | **7** |
| GUNNER_AMMO_COST | 2 | **4** |
| GUNNER_MAX_HP | 40 | **25** |
| SENTINEL_FIRE_COOLDOWN | 3 | **2** |
| SENTINEL_MAX_HP | 30 | **40** |

That inverts the unit economy:

| | dmg/turn | dmg/ammo | dmg/Ti | HP | reach |
|---|---:|---:|---:|---:|---|
| gunner | 7.0 | 1.75 | 0.35 | 25 | cardinal 3, diagonal 2 |
| **sentinel** | **9.0** | 1.80 | **0.60** | **40** | **cardinal 5, diagonal 4** |

Sentinels are now better on every axis except cooldown. Reach was MEASURED with a
probe bot, not assumed: `gunnerLines` in `mapPathfinding.py` is hardcoded 3/2 and
a gunner seat is NOT a sentinel seat, so sentinel work needs its own seat list
(`sentinelSpots` in `bots/exp_v31_sentinel`).

A 500 HP core now costs ~280 ammo to kill, up from 100. Ammo policies tuned
before the patch are probably the binding constraint now, and attack gates sized
for 10-Ti gunners (`resources >= 80`) are not sized for 30-Ti sentinels.

## NOISE FLOOR ON 2.3.4 — rerun after the patch, and it is WIDE

`bots/live-v30-twin` is byte-identical to `bots/live-v30-control`. Gated against
itself on 2.3.4, 336 games:

**54% (CI 49-60), core kills 162-142.**

- **Treat anything under ~57-58% at n=336 as unproven.** Identical code reached
  54%, one point under the promote bar.
- **KILL DIFFERENTIALS ARE NOT INDEPENDENT CORROBORATION.** Identical code
  produced +20 (162-142). A candidate showing a positive differential alongside a
  ~52% win rate has shown nothing; the two numbers move together.
- Rerun this control after every engine bump. It is the only way to know what a
  number means.

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
