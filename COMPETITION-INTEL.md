# ⚔️ v38 THE SENTINEL SWITCH IS LIVE — AND THE MIRROR LIED (2026-08-05 19:30)
ic3d's call: "we're top 8 because we still use gunners." Correct. v38 = v37 + shielded
diagonal sentinel siege (deterministic k=4/3 seats outside gunner reach, then the SAME
builder flanks its sentinel with two barriers — naked sentinels died in v32p; seat-search
stalled in v31s) + ammo buffer 16->60.

**THE METHODOLOGY FINDING, maybe the most important one yet: v38 loses our own mirror 36%
— and beats the actual field.** Scrims as active bot: **PANTHEON 4-1** (won crossfire t63,
the exact map v37 could not take) vs their 0-5 rated sweep of v37 hours earlier;
Pareto-ion 2-3 vs 1-4/1-4. **A mirror gate measures a meta switch against yesterday's
meta.** For meta changes, the referee is scrims against the teams actually above us,
not the parent bot. v38 ACTIVE. Remaining holes: Pareto's fast maps (skerry t77,
longship t87 - the blitz window, still the t25-shields lever).# 🏆 v37 BEATS PANTHEON 4-1 (2026-08-05 07:10, match f07f75b5) — ACTIVE
**v37 = Oogway's v36 (healing, 62% over v34) + the sentinel-line seal (ic3d's observation,
mirror-free 50%).** Scrim progression vs Pantheon: 0-5 -> 1-4 -> 2-3 -> 2-3 -> **4-1**
(won longship t100, fjord t69, showdown t193, sweden t491; lost only crossfire t67).
The formula that did it: **Oogway's chassis + ic3d's observed counter + gates on every step.**
Neither half alone got past 2-3. v36 shipped WITHOUT the seal — always check that a new
chassis carries the measured wins of the old one before it goes active.
Remaining: crossfire t67 (fast-map blitz where the seal isn't up yet — the t25-shields
lever is still unclaimed for whoever wants the 5-0).
# 👁️ EYES BEAT AUTOPSIES: ic3d's observation -> corner shields -> 2-3 vs PANTHEON, TWICE (2026-08-05)

ic3d watched the Pantheon loss manually and saw it: they win with TWO sentinels placed
DIAGONALLY at standoff (range^2 exactly 32) where our five gunners (range^2 13) can never
answer. The observation contained its own counter, and it shipped the same evening:

- **v33 corner shields**: every diagonal sentinel line into a core corner passes through the
  ONE tile diagonally adjacent to that corner. 4 barriers, 12 Ti, all diagonal lines dead.
  Mirror: 51% vs v30 over 168g (kills 75-75) = FREE. First Pantheon scrim: **2-3** (twins WON
  t171, bridge WON t720 absorb war) vs the 0-5 / 1-4 baseline. Their kills rerouted to
  CARDINAL columns (atoll: sentinel at (14,7), our core (14,2), straight down the lane).
- **v34 full seal** (ACTIVE): + 8 cardinal-lane barriers at distance 2 (d1 ring stays free
  for spawns/heals — barriers are passable to own units, so no 29% full-seal trap). 12
  barriers, 36 Ti, every sentinel line into the core blocked. Mirror: 49% = free. Second
  Pantheon scrim: **2-3** again (won crossfire t114, sprint t113).

**Remaining gap: the sub-t50 blitz** (twins t41) — the seal isn't up before their opening
lands. Next lever for the chassis authors: shields up by ~t25 (one defender prioritizes
them over econ in the opening), and the diagonal-corner shield that was missing on fjord.
For the record: copying their START failed twice as the graft law predicts (v31s 10%,
v32p 36%) — the COUNTER transferred, the strategy did not. Eyes on replays found in one
evening what 23 code-first integrations missed. This is the pipeline: ic3d watches, the
lab measures, the chassis authors land it.
# 🚨 WHY WE ARE LOSING + THE 2.3.4 META SHIFT (2026-08-05, 20 fresh loss games parsed)

## The new archetype: SENTINEL SIEGE — Pantheon and Pareto-ion both switched within a DAY of the patch
| team | profile in wins vs us | kills us at |
|---|---|---|
| Pantheon | b3, **s2, L1, bar1-6, g0 (ZERO gunners)** | t46-72 |
| Pareto-ion (1887, climbing) | **s1-5, L1, bar4-18, g0-1** | t65-209 |

Sentinel post-patch: **9 dmg/round (vs nerfed gunner 7), range^2 32 vs 13 (seats ~5.6 tiles out,
OUTSIDE gunner reach), 40hp vs 25, flat 30 Ti with NO +20% scaling.** The gunner is now the
fallback weapon; the sentinel is the siege weapon. **v30 builds zero sentinels.**

## The loss anatomy (Pivot x3, SmartFridge, all 2-3s)
**We hit first in nearly every loss (t8-36), deal 200-784 core damage, and STALL** — their
barriers (Pivot: 5-18/game) + heals absorb nerfed gunner dps (7/round through 30hp barriers),
then their counter kills us t126-449. The absorb-counter pattern we documented in staging is
now the mid-ladder standard, and our finisher can't finish through it.

## Ranked improvements for v30 (for the chassis authors — my integration attempt failed)
1. **Adopt sentinel siege in runAttack** — seats via can_fire_from(spot, f, SENTINEL, coreTile),
   standoff outside gunner range. My first cut (bots/v31s) gated 10% — attackers stalled
   hunting seats (kills 3-68); the SHAPE is: seat search must not preempt fighting, and ammo
   buffer must rise (sentinel drinks 10/shot vs 4). The concept is Pantheon-proven; the
   integration needs the author's hand. This is attempt #23 of outsider-grafts-fail.
2. **Finish through absorb**: our 385-784 damage stalls vs barriers+heals. Sentinel dps (9/rnd,
   and 18 per hit punches 25hp gunners in 2 and 30hp barriers in 2) is also the answer HERE.
3. **Build barriers around our own siege seats** — every team that beats us builds 2-18;
   we build 0. Shield pieces for besiegers, not just harvesters.
# 🎯 2.3.4 STATE OF PLAY: v30 SWEEPS + LAUNCHER TECH RESOLVED (2026-08-05)

## v30 "defend bot change" vs everything, on 2.3.4 (84g each)
| v30 vs | result | kills |
|---|---|---|
| v13 _OogwayRush (was best) | **89%** | 72-9 |
| v9 pls codex | 80% | 64-16 |
| prime-a | 86% | 72-12 |
| oogerebus3 | 86% | 71-11 |

The turret patch (gunner 10->7 dmg, 10->20 Ti, +20%/gunner scaling, 25hp) killed the
t25 rush meta overnight — v13 went from best-ever to 11% in one balance pass.
**v30 is the undisputed best and correctly active. All old numbers are void; regate
everything after every engine patch.**

## Launcher tech: both concepts now measured on the v30 chassis (attempts 14-15)
- **ballista (Pantheon tempo opening, bolt state SOLVED): 29% — REJECT.** The
  mechanism oni's 13 attempts couldn't land now fully works: pad t2 perpendicular
  (landmine 3), self-contained launcher with slot-published target (landmine 1),
  own-stepper march (landmine 2), throws at t4/t7 = Pantheon's cadence, and the
  bolt LATCHED ON LANDING (position jump >2, not on claim — v6's bug). It loses
  anyway: a 6-tile throw is a small slice of a 35-tile journey, the opening
  diverts 20 Ti + two attackers' turns, and 2.3.4 devalued first-gun tempo (the
  thing the throw buys) by nerfing the gun itself.
- **ballista-d (khaos defensive throw — eject enemy builders from our seat zone):
  46%, kills 34-38 — NEUTRAL.** Free but unpaid in the mirror; the pad rarely
  catches a sieger in pickup range. Not shippable by the only-what-gates rule.
**The launcher question is now CLOSED with data on both concepts (15 total
attempts). The working modules live in bots/ballista{,-d} — pad placement, throw
selection, bolt march are all functional and reusable if a future patch or a
Pantheon-style big-map logistics design makes them pay.**
# 👑 OUR BEST BOT IS v9 "pls codex" — AND IT IS NOT CLOSE (2026-08-03)
Downloaded oni's deployed v9 from prod (`fcode submission download 9`) and gated it
against our entire local line, 84 games each on dev29 + synced pool:

| v9 vs | result | kills |
|---|---|---|
| prime-a (our best-ever local: OogwayNEW+armor) | **93%** | **78-2** |
| lastpop2 (siege clone) | **98%** | 82-1 |
| oogerebus3 (anti-siege specialist) | **82%** | 67-6 |

**Every bot in the repo is obsolete as a baseline.** The week of local work
(OogwayNEW line, oogerebus line, all 21 experiments) played in a different league
than what oni's codex pipeline produced. New rule: ALL future gates run against v9.
(v9's own weak maps, from the per-map splits: string 1/4 vs prime-a, sweden 0/4 and
vase 1/4 vs oogerebus3 — narrow-map wall metas. Worth telling oni's pipeline.)

## But v9 has one measured hole against the TOP-4 (from 15 prod games)
0-5 Pantheon, 1-4 CtrlAltDefeat, 0-5 Orizon: **in 13 of 15 games v9 dealt ZERO
core damage.** Two distinct failure modes:
1. **Race losses on fast maps** — Orizon/CAD hit t14-42 with 4-15 lean guns and kill
   t51-116 before v9's siege lands. (Orizon = pure rush: b4, kills t51-83.)
2. **Long-game non-conversion** — CAD g2 (267t), Pantheon bridge (270t) and
   runestone (306t): hundreds of turns, v9 never touches their core. On runestone
   v9 built 169 guns for zero core damage.
The one prod win pattern: atoll t949 grind (unit-cap econ absorb). erebus shelf
now holds v10=prime-a, v11=oogerebus3 as inactive options; **v9 stays active.**
⚠ `fcode submission upload` AUTO-ACTIVATES — always `submission activate 9` after
shelving anything (this bit me for ~2 minutes of ladder time today).

# ⚔️ PANTHEON AUTOPSY — fresh 0-5, challenged them directly (2026-08-03)

## HOW TO SCOUT ON PROD (method matters — replays EXPIRE in hours)
The dev CLI hardcodes staging; override with `FCODE_API_URL=https://game.code.florent.vc`
(then `fcode login` once). **Replays can only be downloaded for OUR matches and only
while fresh** — yesterday's are already gone. So the pipeline is:
`fcode match unrated <team-uuid>` → poll `match info` → `match replay` IMMEDIATELY.
One unrated challenge = 5 games of any team's CURRENT bot. They already see our bot
in every public match, so it costs nothing. Pantheon uuid: 3a7b78b8-5d79-4e55-94a3-7732fcaa4105.

## What their bot is (f876f538, 0-5, all cores destroyed)
| map | turns | their profile | 1st gun | 1st core hit (them vs us) |
|---|---|---|---|---|
| sprint | 41 | b5 g8, nothing else | **t5** | **t6** vs t13 |
| showdown | 107 | b5 g16 bar6 | t7 | t8 vs t14 |
| twins | 139 | b7 g10 **L3** bar3 | t95 | t125 vs NEVER |
| bridge | 270 | b11 g24 **L3** bar6 | t53 | t190 vs NEVER |
| runestone | 306 | b6 g32 **L6** bar2 | t43 | t280 vs NEVER |

1. **FULL-SPECTRUM TEMPO.** Hyper-rush on small maps (first gun t5, core hit t6 —
   faster than khaos's fabled t29), patient t190-280 grinds on big ones. They pick
   the tempo per map; nobody else does both.
2. **LAUNCHERS — 3-6 per game on every big map. No other team builds ANY.** This is
   Pantheon's Cambridge launcher tech alive in fcode: mobility/tempo through the
   unit our own engine-facts memo called "completely untapped" (friendly launch
   works, ~2.5x walking speed; enemy-throw removes attackers from sieges).
3. **Barriers (2-6/game)** — the absorb element, same as the other top teams.
4. **In 3 of 5 games we dealt ZERO core damage.** On runestone our deployed bot
   built **169 gunners and never hit their core once** — the exact placement
   pathology oni diagnosed (atoll: 14 useless guns) is still in the live bot, at
   10x scale. The core-seeking fix is not optional.

## Read on the field (real ladder, 92 teams)
Pantheon 1962 #1 (beat #2 CtrlAltDefeat 4-1 unrated); CtrlAltDefeat 1812; Orizon
1736 (4-1'd us rated). We are #14 ~1590. Staging teams (Besvikomat, Ouroboros,
lastpopperian_) are mid-table HERE — the staging meta was a small pond. The teams
above us that we have never scouted: CtrlAltDefeat, Orizon, team lazy, Flotte,
SmartFridge, Askar City, OopsGotYourElo — the challenge pipeline above works on
every one of them.

# Competition intel — day 2 autopsy (2026-08-03, 10 games parsed)
Matches: Besvikomat 4-1 Ouroboros (65b7e76c), lastpopperian_ 4-1 Ouroboros (766e5c46).
Metric: turn of first core damage vs who actually won.

## THE HEADLINE: THE RACE META IS DEAD AT THE TOP
In 5 of the 8 decided games, **the team that landed the FIRST core hit LOST**:
| game | first hit | by | winner | final |
|---|---|---|---|---|
| Besvi g1 | t37 | Ouroboros | Besvikomat | t118 |
| Besvi g2 | t50 | Ouroboros | Besvikomat | t209 |
| Besvi g4 | t28 | Ouroboros | Besvikomat | t90 |
| lastpop g2 | t69 | Ouroboros | lastpopperian_ | t167 |
| lastpop g5 | t41 | Ouroboros | lastpopperian_ | t136 |

**Both top teams now ABSORB the first hit and counter-kill.** oni's race diagnosis
("loser deals zero core damage") described the July staging meta. The August
competition meta at #1/#2 is absorb-counter — the strategy we decoded from Ijti,
now run harder by better teams.

## The three top profiles
- **Besvikomat (#1, 2295): absorb + overwhelming counter-battery.** Lean crew
  (b4-6), 27-85 gunners per game, 3 sentinels, tiny infra. Takes your best punch,
  then out-guns you 5:1. Also wins tiebreaks vs bigger infra (denial?).
- **lastpopperian_ (#2, 2261): EVOLVED since July.** Still 1 sentinel, but now
  cv75/h6 economies and — new — survives first core damage (t69 hit -> t167 win).
  Our July model of them (pure sniper race) is stale.
- **Ouroboros = Pantheon (#4, 2092): a RACE bot.** First core hit t28-54 in
  nearly every game, barriers (bar1-9, khaos DNA). Crushes the midfield 5-0,
  **loses 1-4, 1-4 to both absorb teams.** The ceiling of the race strategy is
  #3-4 in this field.

## What it means for us
1. **Our v90/prime-a family has Ouroboros's exact profile** (race machine, first
   hit t51-84, no absorb). Expect the same ceiling: beats midfield, loses to
   Besvikomat and lastpopperian_.
2. **The sandbag window (oni's plan) is the time to build absorb-counter INTO a
   real engine.** The full spec is in HANDOFF (Ijti barrier spec, 935bf5b):
   garrison bodies at home, pre-armor seat zone, rebuild loop, heal posture —
   PLUS Besvikomat's lesson: the counter-battery must be massive (27-85 guns),
   not polite. Both absorb teams pair survival with overwhelming response.
3. **Bastion already proved the absorb half works when games reach it** (atoll
   t243 win where prime-a dies t72) — it failed on engine quality, not thesis.
   Inside oni's or Oogway's engine, this is the meta-correct design.
4. Erebus is #12 at 1177 on the deliberate sandbag (v1). Fine per plan — but
   every day the top teams also see only our sandbag, which is the point.
