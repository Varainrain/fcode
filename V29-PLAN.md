# v29 diagnosis and iteration plan — 2026-08-04

Status: **Erebus #2 of 92, rating 1966, v29 "routing + threat avoidance"
419-81 (84%) over 500 rounds.** Pantheon #1 at 2016 — a 50-point gap.

Evidence base: 70 replays downloaded from v29's own losing matches (Pantheon,
Pareto-ion, team lazy, Coreflood, the one piece) plus the full per-version
ladder record. Nothing below is inferred from a single game.

## 1. Where we actually lose

Only one matchup is below 50%:

| opponent | record | rate |
|---|---|---|
| **Pantheon (#1)** | 24-26 | **48%** |
| the one piece | 5-5 | 50% (n=10) |
| Coreflood (#5) | 17-8 | 68% |
| team lazy (#4) | 18-7 | 72% |
| Pareto-ion (#3) | 27-8 | 77% |
| everyone else | — | 80-100% |

**23 of 26 losses are `core_destroyed`, median t62, and 12 of them end before
t60.** We are not being out-grinded; we are being killed early.

## 2. The measured gap, side by side (same games)

| side | 1st gun | on core | built | conv | harv | barriers | launchers |
|---|---|---|---|---|---|---|---|
| **US (v29)** | **t22** | **5.3** | **17.7** | 10.0 | 2.1 | **0.0** | **0.0** |
| Pantheon | **t7** | 12.1 | 22.2 | 7.0 | 2.3 | 3.0 | 1.0 |
| Pareto-ion | t16 | 7.7 | 16.1 | 8.3 | 2.3 | 4.1 | 1.5 |
| team lazy | t14 | 10.8 | 13.1 | 7.3 | 1.8 | 0.0 | 0.0 |
| Coreflood | t28 | 9.8 | 17.6 | 7.5 | 1.8 | 0.0 | 0.1 |
| the one piece | t30 | 6.6 | 8.8 | 4.6 | 1.4 | 0.0 | 0.4 |

Three facts fall out:

1. **Our gun-to-core conversion is the worst on the board: 30% (5.3 of 17.7).**
   team lazy converts 82%, the one piece 75%, Pantheon 55%. We build the most
   guns of anyone and land the fewest proportionally. This is the single largest
   number in the table.
2. **We are the slowest to first gun except two: t22.** Pantheon t7 — fifteen
   turns. team lazy t14, Pareto-ion t16.
3. **We build zero barriers.** The two teams above/near us build 3.0 and 4.1.

We also lay the most conveyor (10.0) of anyone.

## 3. Plan

### Phase 0 — diagnostics only, no code (about 20 minutes)

These are cheap and they decide which Phase 1 experiments are worth running.
Running experiments before these is how the last two days produced ~20
rejections.

- **D1. Where do the 12.4 non-converting guns go?** Distance-to-enemy-core
  histogram for every gun we build, split by game phase. If they cluster
  mid-map, it is target selection; if they cluster at home, it is defensive
  spend; if they cluster at 7-12, it is arriving-and-dying.
- **D2. What kills us before t60?** For the 12 sub-t60 losses: when does the
  first enemy gun appear near our core, how many, and what were our builders
  doing that turn.
- **D3. Do our guns die or just miss?** Gun lifetime and total core damage dealt
  per game, us vs each opponent. Distinguishes "placed badly" from "placed fine
  and killed".

### Phase 1 — experiments, in priority order

Each is a single mechanism, forked from a frozen `bots/live-v29-control`
extracted byte-for-byte from the active submission. One at a time, no stacking
until each passes alone.

- **E1 — conversion (highest expected value).** Target the 30%. Exact change
  depends on D1: if guns are going mid-map, restrict discretionary placement to
  seats that pass `can_fire_from` against a core tile; if they are dying on
  arrival, that is E3 instead.
  *Prior art: `exp_core_pressure` tried this on the v8 lineage and gated 46%,
  losing 9 points against rushers because it stripped home defence. Any version
  must keep the home counter-gun path intact.*
- **E2 — first-gun tempo t22 -> ~t14.** Not the launcher: thirteen launcher
  variants were rejected and `LAUNCHER-HANDOFF.md` documents why. The cheaper
  question is why our first attacker takes 22 turns when team lazy manages 14
  with no launcher either.
- **E3 — barriers at the seats we hold.** We build zero; Pantheon 3.0,
  Pareto-ion 4.1. Only worth building if D3 says our guns are dying rather than
  missing.
  *Prior art: `aegis-v1` (reactive armour at home) and `bastion` both rejected;
  `exp_v23_fwd_armor` on the v22 lineage gated 47%. Different lineage now, and
  D3 decides whether the premise holds at all.*
- **E4 — economy right-sizing.** We lay 10.0 conveyors to Pantheon's 7.0 and
  team lazy's 7.3. Lowest priority: it is the smallest gap and the most likely
  to be load-bearing.

### Phase 2 — gates and promotion criteria

Per `WORKFLOW.md`, plus what the noise-floor work established:

- frozen parent `bots/live-v29-control`, 336 rounds, both sides, `--tle 10`
- **promote only if the 95% CI excludes 50%** — at n=336 that is roughly 55%+.
  A 168-round result can eliminate but never promote.
- fresh parent control beside every opponent gate; a number means nothing alone
- mechanism must be shown active in replay before its win rate is believed
- anything that passes goes to an unrated scrim vs Pantheon and Pareto-ion
  before it is considered for the ladder

### What we will NOT do again

Documented rejections, with reasons, so they are not rebuilt under new names:
launcher-as-transport (13 variants, best 45%), launcher-as-sensor (43%, effect
real but 2-3 turns only), flanking (44%), placement radius (46%), heal-lock
retreat (52%), pre-armour seat denial (51%), phase-ordered economy on the old
lineage (34%), zero-economy delivery (27%).

## 4. Success criterion

The only number that matters: **Pantheon 48% -> 55%+.** Everything else is
already 68-100%, and beating the field harder does not close a 50-point rating
gap to the one team we cannot beat.
