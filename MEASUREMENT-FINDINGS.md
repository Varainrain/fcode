# Measurement findings — 2026-08-01, prod engine 2.3.3

Everything here is measured, not inferred. Method notes matter more than the
numbers: several confident claims made during this session were wrong, and the
errors all came from trusting a derived log instead of a direct run.

## Champion

**`bots/generalist-v3` = the live bot (v90) = champion.** Nothing beats it.
All figures are full gates vs generalist-v3, 168 games (21 maps x 4 seeds x
both sides, `--tle 10`):

| challenger | result |
|---|---|
| OogwayNEW | 21% |
| OogwayOld | 14% |
| aegis-v1 | 14% |
| generalist-v2 | 49% (tied — same lineage) |
| exp_bounded_home_counter | 48% |
| exp_healer_suppression | 48% |
| exp_local_responder | 53% |
| **byte-identical control** | **50-52%** |

No swap was made. Nothing was submitted or activated.

## The gate is calibrated — but the band is +/-8, not +/-3

`bots/exp_emergency_countertrade` is byte-identical to `bots/generalist-v3`
(md5 `bf31fa04b650`). Gating it against itself measures pure noise:

- Single draws: n=168 -> 50%; n=336 -> 52%; n=288 (18 maps) -> 51%.
- **CORRECTED 2026-08-01: one draw per n cannot estimate a spread.** Three
  repeats of the same 168-game control gave **49%, 56%, 51%** — the middle one
  clears the bar and PROMOTES a bot over itself.
- Binomial SD at n=168 is 3.9 points, so the 95% band is +/-7.6 and identical
  code clears 55% about **10% of the time**. At n=336 that drops to 3%.
- **A 168-game PROMOTE is a 1-in-10 coin flip. Use seeds=8 (336) to decide.**
  gate.py now prints the 95% CI and warns when it spans 50%.

Games are not reproducible at all: 46 of the 48 bots/ call `random.*` unseeded,
and `--seed` seeds the ENGINE, not the bot's Python RNG. Two identical SERIAL
runs flipped 8/20 winners on `sprint` (10/20 with `--tle 0`); seeding the bot
RNG gave 0/16. So this is not the worker pool and not the TLE - never diff two
runs game by game, and never treat a seed as a control variable.

A hypothesis was tested and REJECTED: that seat-locked maps were compressing
real gains toward 50% and burying good bots. Dropping the locked maps moved the
control 52% -> 51% and the best candidate 53% -> 53%. **No meaningful gain — do
not redesign the gate for this.** The three exp_* bots above were correctly
rejected; they are not better.

Rerun the control after any engine bump. It is the only way to know what a
number means.

## Per-map gate output — RESOLVED 2026-08-01

The old `"<bot> first"` label was a wrong WORD, not wrong data. It always named
the bot passed as `bot_a` (verified against `fcode run` and the replay: bot_a is
team 0). Since execution interleaves ABABAB, nobody is "first", so the label now
reads `as A` and the CSV column is `side_a`.

**`gate_results.csv` was never wrong, and past per-map analyses are not invalid
on these grounds.** Whole-history A-seat win rates are strongly structured
(`bridge` 84%, `jackpot` 67% ... `skerry` 22%, `duel` 29%) - a scrambled column
would sit at 50% everywhere.

The 8/16-vs-20/20 "contradiction" was never one: 8/16 is exactly what a
seat-locked map produces when the candidate holds each seat half the time. The
old summary collapsed both seats into one number and hid it. gate.py now prints
the per-seat split and flags the lock:
`strait 4/8  as A 0/4  as B 4/4  SEAT-LOCKED (side B won every game)`.
Lock detection off the gate is now trustworthy; per-map WIN RATES still are not
(n=8, SD 17.7 points).

Per-map lines are noise regardless: identical code produced `sweden` 1/8 and
`longship` 6/8 in one run. Measure seat effects with `scripts/seat_check.sh`
(both orders, explicit), never by parsing gate output.

## Turn order

- Execution order is by **global entity id**, interleaved `ABABAB`
  (A-core, B-core, A-builder, B-builder...). It is NOT "all of team A, then
  all of team B". Measured with an instrumented probe bot, not inferred.
- With identical code the second player wins **59%** pool-wide.
- Verified seat-locked (direct runs, both orders, 20 games, identical code):
  `duel`, `showdown`, `skerry`, `strait` — all **20/20** to the second-listed
  bot. `sprint` is balanced (9/20). **The other 16 maps were never measured
  directly** — any figure for them came from the unreliable gate log.
- Seat bias is bounded by skill: across a large gap (generalist-v3 vs
  OogwayOld, 86-14) skill won 29/32 on locked maps. The seat only decides
  between closely matched bots — which is the top-of-ladder regime.
- All 21 maps are **exactly symmetric** (terrain, ore, and core placement
  under rot180/mirrorX/mirrorY), so spawn quality is ruled out. Turn order is
  the only remaining asymmetry.
- Do not call this "RNG" or try to fix it with more seeds: on `duel` the seed
  is inert.

## Reference opponent

**`bots/champion` is stale — it is `oogerebus3`, two generations behind live.**
Screened against it, ten bots scored 91-100% and then lost to the live bot;
OogwayNEW screened 83% and lost 21-79. It inverts rankings. Gate against the
CURRENT LIVE BOT and always state which reference a number came from.

A 12-game screen can only ELIMINATE (0-25% = broken). It can never promote —
identical code reads up to 67% at n=12.

## Repo hygiene

- `main` is a superset of every remote branch; `origin/betterOogway` is behind
  it (deletions only). Nothing left to merge.
- Byte-identical duplicates: `champion`==`oogerebus3`,
  `exp_emergency_countertrade`==`generalist-v3`,
  `exp_generalist_stack`==`generalist-v2`,
  `core-sniper-v1`==`exp_core_sniper`, `frozen-erebus-v1`==`oogerebus`.
  `*_trace` bots are instrumented twins, not independent results — counting
  them separately overstates evidence.

## Ladder diagnosis, 200 live games (2026-08-01, bot v1, 11:25-14:08)

Team Oogway, **rank #1 of 86**, rating 1675, **62% overall**. Rivals:
OopsGotYourElo 54/95, Besvikomat 12/25, Ouroboros 5/10, Pantheon 4/10.
Everyone else 75-100%.

**Seat order does not matter live: 63% as A, 62% as B.** The seat effect that
dominates local mirror gates is absent when skill differs, so the spawn-timing
lead below is aimed at something the ladder cannot see. Deprioritised.

**The loss is a game-length window.** Against the top four rivals:

| turns | win rate |
|---|---|
| <150 | 27/40 (68%) |
| **150-299** | **10/34 (29%)** |
| 300-899 | 12/21 (57%) |
| 900+ cap | 26/45 (58%) |

Controlled for opponent it holds - OopsGotYourElo alone (n=95): 64% / **40%** /
60% / 64%. The 24 losses in the window span 4 opponents, 10 maps, and seats
12/12, and 23 of 24 are `core_destroyed`. It is a general mechanism, not a map.

**Mechanism: our siege damage gets healed to nothing.** From 85 downloaded
replays (`fcode-gate-artifacts/v90-midgame-replays`):

| group | dmg to our core | dmg to enemy core | our gunners | fully healed |
|---|---|---|---|---|
| WIN <150 | 93 | 633 | 13 | 0/17 |
| **LOSS 150-299** | **722** | **268** | **30** | **12/23** |
| LOSS 300+ | 416 | 260 | 46 | 11/18 |
| WIN 150+ | 537 | 1446 | **122** | 8/20 |

In the failure window we have MORE gunners than the enemy (30 vs 23) and still
deal a third of the damage, because half those games are fully healed. Winning
a long game took 122 gunners - 4x - i.e. the only answer the bot currently has
to healing is overwhelming it. Four separate `quarry` losses ended at exactly
t184 with heal fraction 1.0, so the failure is deterministic and repeatable.

**This does NOT reproduce locally.** Same buckets from `gate_results.csv`
(1844 games): vs OogwayOld 98/75/52/41, vs lastpop2 90/100/100/86, vs
generalist-v2 flat 48/55/53/55. Local opponents either die before t150 or are
same-lineage mirrors. **A local gate cannot show a gain on this class of change
— it can only prove nothing broke.** The gain is only observable on the ladder.

The MECHANISM is locally reproducible even though the win rate is not: mirror
games hit the same heal-lock (`sprint` t350, core B took 490 and healed 490 =
100%). Measure it with `heal_audit.py` (new, offline, no API needed).

## Open lead for generalist-v3

Action order follows entity id, and id is assigned at spawn — so **spawn timing
is a controllable lever**. A unit spawned later acts after more enemy units and
sees a more current board. Falsifiable cheaply: one variant that delays its
first spawn a round vs one that does not, gated normally against v3.

Already banked in v3, do not redo: `_direct_siege_plans` (main.py ~638) only
accepts gunner seats where `can_fire_from(...)` succeeds against an enemy core
tile, so it cannot plant out-of-range gunners. That was the atoll/lastpopperian
failure mode and it is fixed.
