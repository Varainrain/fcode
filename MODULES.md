# MODULES.md — one bot, four owners, explicit seams
(ic3d's reorg, 2026-08-06. This is how we divide the bot WITHOUT hitting the
26/26 transplant failure law. The law's root cause was never modularity — it was
implicit interfaces: two pieces of code silently fighting over the same builder's
turn, the same store slots, the same movement assumptions. Both Cambridge top-2
teams ran module architectures with named subsystems. So can we.)

## The one hard rule that makes it work
**A module never takes a turn. It PROPOSES.** Every module returns
`(score, action_fn)` proposals; the chassis's arbiter (Oogway's state scorer —
it already works this way internally) picks exactly one per unit per turn.
Every regression I shipped came from a module seizing turns: shields starving
heals (0-heal games), seat-hunts starving fights (10-19% gates), chip-hooks
starving eco (29%). Proposal + arbiter makes that class of bug structurally
impossible.

## Ownership
| module | owner | contents | status |
|---|---|---|---|
| CHASSIS: dispatch, roles, arbiter, pathfinding | **Oogway** | run(), builderBot(), state scorer, mapPf | his OogwayPlus — the measured spine (beats everything local 73-76%) |
| DEFENSE | **ic3d + Claude** | cornerShields+triage, split-duty healer, _wouldEntomb, rotation floor | gated on 4 chassis: Pantheon 4-1, Oops 4-1, Besvik 4-1; in bots/v44 |
| ATTACK/SIEGE | **oni** | sentinel siege, burst-building (his turrets-landed metric), gunner support | his pipeline + the 4 documented failed shapes to skip |
| INTEL | **ic3d + Claude** | replay autopsies, gates, scrims, meta reads | the pipeline that flipped every top-4 matchup |
| (sagarftw picks a lane with an owner as mentor) | | | |

## The blackboard — store slot allocation (16 slots, COLLISIONS = silent death)
| slot | owner | meaning |
|---|---|---|
| 0 | chassis | numSpawned (⚠ off-by-one + race documented, PITFALLS #1-2) |
| 1-6 | chassis | map sharing |
| 7 | chassis | team core pos (core republishes every turn) |
| 8 | chassis | symmetry mask |
| 9 | free | (was pad flag in launcher experiments — retired) |
| 10 | free | (was enemy-core publish — retire or re-adopt deliberately) |
| 11-13 | free | |
| 14 | DEFENSE | healer claim round (split-duty) |
| 15 | free | |
Any new slot use = a line in this table FIRST, then code.

## The merge pipeline (30 min, replaces all coordination overhead)
1. Module change → PR named `module/owner/what`.
2. Gate vs current ACTIVE bot (84g screen; 168g if 45-60%). One change per gate.
3. One scrim vs the team the change targets (unrated, replays downloaded same hour).
4. Carry-forward check: active bot must contain every shipped fix or a gate
   justifying its absence (PITFALLS #17 — this is what killed v36 and OogwayPlus's
   ladder run).
5. Only the CHASSIS OWNER merges into the bot. Module owners deliver specs +
   reference code + gate receipts; Oogway integrates natively (26/26 law).

## Why not from-scratch (the 75% question)
Measured: bastion had the right thesis and lost 1% — engine quality dominates
strategy, and engines take weeks we don't have (freeze in ~19 days). OogwayPlus
+ the defense stack + oni's siege work, integrated by the chassis owner through
this pipeline, IS the new bot.
