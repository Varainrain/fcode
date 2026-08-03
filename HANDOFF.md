# FCode production handoff

Updated 2026-08-03. Read this before changing a bot. `AGENTS.md` contains the
iteration rules; `WORKFLOW.md` contains the gate protocol.

## Current decision

- Frozen ladder control: `bots/live-v17-control`, downloaded byte-for-byte from
  active production submission `v17 (dumb bot v6)`. Original archive:
  `C:/Users/subodh/Downloads/fcode-gate-artifacts/ladder-v17-20260803/v17-live.zip`.
- Latest observed production status on 2026-08-03: Erebus rank #1/92, rating
  1907 after 322 matches, active v22, latest ten 9W-1L. Submission v22 was
  activated with explicit user approval; keep it active after future uploads.
- Current production bot: `bots/exp_v21_eco_release_only_damaged`
  (submission v22, ID `5861c003-13a8-48c4-bc42-fe01445c6245`). It combines
  v20 route completion, v21 spare-opportunity productive-edge repair, and a
  bounded economy/defense ownership fix. All local gates and the 50-game
  remote threshold pass. Updated Pantheon v14 remains a severe 1-9 weakness,
  but pinned v18 also scored 0-5 on the same five maps. v22 is active; root
  remains unchanged.
- `meta-generalist-v1` remains the exact archived v9 control, but is no longer
  the parent for new work.
- Root `main.py` / `bot.zip` remain the historical v88 package and are dirty in
  git from prior user work. Do not replace them without explicit approval.
- Local WSL is production `fcode 2.3.3` with all 21 maps and an authenticated
  production session. The ten completed v9 ladder series (50 games) are in
  `C:/Users/subodh/Downloads/fcode-gate-artifacts/ladder-v9-20260802-1830/`.
  Gates below distinguish old dev29 evidence from new 2.3.3 evidence.

## Candidate evidence

All gates use 21 maps, both sides, `--tle 10`; fresh blocks only.

| Opponent | Result | Core kills | Interpretation |
|---|---:|---:|---|
| `exp_trans_40` | **200/336 (60%)** | **181-127** | decisive parent win |
| `spar_rush` | 88/168 (52%) | 81-64 | neutral/slightly negative |
| v8 control vs `spar_rush` | 92/168 (55%) | 85-64 | comparison control |
| `oogbest-v6` | 86/168 (51%) | 83-67 | source-diverse parity |

Parent-gate mean titanium collected was 819.1 vs 718.0; buildings 19.2 vs
18.4. The source change cannot alter economy directly. Deterministic tests prove
enemy builders fire and friendly builders do not.

Validation completed:

- all `tests/test_*.py` files pass when run directly in the WSL venv;
- `pytest` is not installed, so `python -m pytest` was unavailable;
- frozen sources compile and a Duel smoke game completed by core destruction;
- `git diff --check` passes (line-ending warnings only);
- ZIP contains exactly four Python files at root and is byte-identical to the
  frozen folder;
- mandated `python scripts/eval_chain.py` attempt fails because this repository
  has no `scripts/eval_chain.py`. Record this as missing legacy tooling, not a
  pass.

SHA-256:

| File | SHA-256 |
|---|---|
| `main.py` | `A9EC959ECAE2E0B11EDB3DAA89AD3A3CD480196C903FEB543F8059B76C2D965C` |
| `initialSpawning.py` | `E6D48213A505729ED98BBBC1B55623484BC83B202B2E78D4FA9E929686D40BB6` |
| `mapPathfinding.py` | `971A102A26E8792E6B0FED6FE8F7710641FD1D03D299322F97423A43342AE4A6` |
| `symmetry.py` | `8C4AB5843AB90F8C0907E261E2049B75588BC88BFB8CEEA2CC236E3CD10CD9A1` |
| ZIP | `4F94E7301B99EC34283C82F6FAFDE7C61F03135C9702F4792AE3D3BC6642EE07` |

## Production-era lineage

| Line | Evidence / status |
|---|---|
| root v88 | historical package, preserve |
| `generalist-v2` | v89 source; early live sample 26-14 |
| `generalist-v3` | bounded countertrade; later live v3 was rank #1/86 at 62%, but top-four window only 29% |
| `exp_siege_on_sight` | shipped live v2; 67%/336 vs v3, 52% vs rush |
| `exp_recall2` | soft v6 recall; hard recall rejected |
| `exp_trans_40` | shipped v8 lineage; economy stops at t40; 60%/504 vs recall parent, but live top-five trade rather than clear gain |
| `meta-generalist-v1` | archived v9 control; gunner builder-layer bug fix |
| `live-v17-control` | active v17; four-builder rush/defense/economy chassis; rank #3 at freeze |
| `exp_v17_gunner_control` | validated v17 successor candidate; local only |
| `exp_v18_spawn_route_proof` | submission v19; facing-proven merges; inactive; remote 33-17 |
| `exp_v19_near_core_finish` | submission v20; bounded route completion; inactive; remote 14-11 |
| `exp_v20_opportunistic_trunk_repair` | submission v21; no-travel exact edge repair; remote 14-11; superseded by v22 |
| `exp_v21_eco_release_only_damaged` | submission v22; current active production bot; remote 30-20 |

## Live v17 replay audit and candidate

Thirty ladder games from the six series actually played by v17 were downloaded
to `C:/Users/subodh/Downloads/fcode-gate-artifacts/ladder-v17-20260803/`.
The sample was 23-7 against Pantheon, Askar City, team lazy, CtrlAltDefeat,
the one piece, and Powered by SmartFridge.

All seven losses were core destruction under multiple enemy gunners. Five were
early races ending on turns 28-68; one Sprint game lost on turn 301 after 580
enemy-core damage was partly healed; one Sweden game lost on turn 575 after
building 52 gunners but never damaging the enemy core. Only one or two home
turrets existed before the first incoming shot in every loss. This indicates
three remaining categories: early gun-line control, healed/stalled conversion,
and rare enemy-core discovery/pathing failure.

Source audit found three general gunner bugs: v17 ignored lone enemy builders;
equal target scores could rotate away from the current line and waste 10 Ti;
and a gun countering a real core-threatening gun received only a lower spend
floor, not targeting priority. `exp_v17_gunner_control` fixes exactly these.

| Production 2.3.3 gate | Candidate | Exact v17 control | Candidate core kills |
|---|---:|---:|---:|
| head-to-head | **200/336 (59.5%)** | 136/336 | **187-128** |
| vs `oogbest-v6` | **145/168 (86%)** | 140/168 (83%) | **143-18** vs 139-25 |
| vs `meta-generalist-v1` | **144/168 (86%)** | 142/168 (85%) | **142-19** vs 140-25 |

The candidate passes deterministic targeting/tie/priority tests, compiles, and
completed a smoke game. It was packaged byte-identically as submission v18
`v17 gun-control candidate` (ZIP SHA-256
`416FAB58A9EBA8F22735EAC0A5E1339617F125E5AD9B7CD26174CEDDB5B77359`).
The CLI automatically activated v18 on upload; v17 was immediately restored as
active. Treat upload as activation-capable in future workflows.

Eight v18 unranked series pinned to opponent versions from the loss sample
scored **34/40**. Batch one: Pantheon 5-0, Askar City 5-0, team lazy 3-2,
CtrlAltDefeat 4-1, and the one piece 5-0. Batch two: SmartFridge 3-2,
team lazy 4-1, and CtrlAltDefeat 5-0. Replays are in
`C:/Users/subodh/Downloads/fcode-gate-artifacts/ladder-v17-20260803/v18-unranked/`.
and its `v18-unranked-repeat/` sibling. All six losses were multi-gunner core
destructions. Five were early races on Showdown, Runestone, Sprint, or Atoll;
one was a turn-990 Sweden loss where 200 damage was fully healed. This confirms
early gun races and healed/stalled Sweden remain the live failure categories.

## v18 follow-up audit and spawn candidate

The 40 v18 unrated replays contain no evidence of our units dying from uncaught
exceptions. The remaining failures exposed home-gun races and one long-game
resource leak: the Sweden loss spawned 56 builders versus 24 while converting
only 200 enemy-core damage. Production 2.3.3 also documents builder build/heal
range as orthogonal only; older repository rules saying diagonal/own-tile are
stale.

Independent audits tested exact core-threat filtering, legal heal stands,
obstruction-aware gun lines, legal siege/harvest stands, and congestion-aware
spawning. Only `exp_v18_spawn_discipline` passed its mechanism and broad gates.
It preserves the first four builders, then pauses extra spawning while six
friendly builders are inside core vision and resumes after dispersal/death.

| Production 2.3.3 gate | Candidate | Core kills | v18 baseline |
|---|---:|---:|---:|
| exact v18 | 86/168 (51%) | 73-72 | 50% expectation |
| `spar_rush` | 151/168 (90%) | 150-11 | 154/168 |
| `oogbest-v6` | 146/168 (87%) | 143-15 | 145/168 |
| `meta-generalist-v1` | 146/168 (87%) | 144-17 | 144/168 |
| String/Bridge focus | 18/32 (56%) | 11-10 | head-to-head |

Across 12 round-1000 parent games it won 8, collected +434 Ti/game, retained
+1,799 Ti, and used 4.7 fewer units. The focused block won four of five
round-1000 games with +1,248 collected Ti/game. Core-threat filtering reached
90/168 and kills 78-63 but lost 94 collected Ti/game; harvest-stand reached
89/168 and kills 78-69 but lost 740 collected Ti/game in round-1000 games.
All other audit variants failed their screens. Nothing was uploaded or activated.

## Pantheon postmortem cycle

The Cambridge/Pantheon postmortem validates mechanisms, not a directly portable
bot: its game included foundries, axionite, bridges, roads, breaches, markers,
50x50 maps, and 2000 rounds. Current v18 already overlaps with its memoryless
map layer, symmetry inference, weighted bucket pathfinding, conveyor-cycle
classification, deterministic roles, threat-aware gun plans, and ID-jittered
stuck timeout. Missing architecture-level ideas are per-turn state scoring,
claim/Voronoi ownership, TTL target-failure caches, and incremental map deltas.

Three isolated ports started from `exp_v18_spawn_discipline`:

| Experiment | Parent result | Decision |
|---|---:|---|
| passive spare-action heal | fast 3/12, kills 3-9 | reject |
| immediate-buildable siege seat | 80/168, kills 73-82 | reject |
| facing-proven route merge | **86/168, kills 69-68** | pass |

`exp_v18_spawn_route_proof` treats a visible conveyor as a completed merge sink
only when its facing chain reaches the core, or leaves vision after every
observed edge strictly reduces Manhattan distance to the core. Full 2.3.3 gates:

| Opponent | Result | Core kills | Spawn-parent baseline |
|---|---:|---:|---:|
| `exp_v18_spawn_discipline` | **86/168** | **69-68** | parity gate |
| `spar_rush` | **152/168** | **151-13** | 151/168 |
| `oogbest-v6` | **148/168** | **141-18** | 146/168 |
| `meta-generalist-v1` | **142/168** | **142-21** | 146/168 |
| String/Bridge parent focus | **21/32** | **15-7** | 18/32 prior block |

Parent JSON: +10 Ti collected/game, +36 retained Ti/game, 1.2 fewer buildings;
round-1000 games were 10-9. Sixteen paired Bridge replays in
`artifacts/pantheon-route-proof-bridge/` preserved connected conveyors and
served harvesters while reducing total conveyors 18.94 -> 14.69, disconnected
16.81 -> 12.56, and post-round-40 builds 10.00 -> 5.94. It removes waste but
does not fix Bridge team A, which still had zero connected conveyors in both
variants.

The replay batch exposed an inherited `getDefendHome()` out-of-vision occupant
query that can kill a defender with `GameError`. Two isolated fixes were not
stacked: assumed-empty ring caching gated 83/168 with kills 67-70; a visible-
only/core-return version failed its fast screen 5/12. Keep the bug open rather
than claiming either unproven fallback passed.

### Remote route-proof and near-core-finisher cycle

`exp_v18_spawn_route_proof` was packaged as inactive submission v19
(`a3a732e6-5916-4c40-9088-69a119a3f4d8`, ZIP SHA-256
`EAAE6E...D7170B3`). Its 50-game unrated sample was **33-17**, estimated core
kills **27-15**: Pantheon 8-2, Orizon 8-2, team lazy 5-5, CtrlAltDefeat 8-2,
SmartFridge 4-6. Replays are in
`C:/Users/subodh/Downloads/fcode-gate-artifacts/ladder-v19-20260803/`.
The losses showed that facing-proof prevents false merges but does not finish
short routes: an Orizon Bridge loss built 27 conveyors, connected none, and
kept starting branches after combat.

`exp_v19_near_core_finish` remembers an unfinished route only while its head is
within four Manhattan links of the core footprint, resets on progress, and
abandons after 24 stalled rounds. A post-move vision recheck is mandatory:
without it, querying the old target after movement raises `GameError`.

| Production 2.3.3 gate | Result | Core kills | Notes |
|---|---:|---:|---|
| exact v19 parent | **88/168** | **72-69** | +193 Ti collected/game |
| `spar_rush` | **158/168** | 158-3 | pass |
| `oogbest-v6` | **142/168** | 138-19 | 3.6 pp below v19, within gate |
| `meta-generalist-v1` | **155/168** | 152-12 | pass |

In 16 paired Bridge games it cut total conveyors **24.81 -> 6.06**,
disconnected conveyors **23.25 -> 4.00**, and post-round-40 builds
**16.00 -> 1.62**, while increasing connected conveyors **1.56 -> 2.06**.
The fixed source produced no tracebacks. Submission v20 ZIP SHA-256 is
`BE321AA7...EC8D3`; the archive contains only byte-identical `main.py` and
`mapPathfinding.py`.

The v20 remote sample was **14-11**, estimated core kills **13-11**: Pantheon
4-1, Orizon 3-2, team lazy 1-4, CtrlAltDefeat 4-1, SmartFridge 2-3. Replays are
in `C:/Users/subodh/Downloads/fcode-gate-artifacts/ladder-v20-20260803/`.
Across all 25 games it averaged 9.00 conveyors: 6.76 connected and 2.24
disconnected. The surviving failure is narrower than initial routing. In the
turn-640 Pantheon Sweden loss, the network was fully healthy at round 80
(24/24 conveyors connected, 5/5 harvesters served), then enemy damage severed
the trunk; by round 400 it had 36 disconnected conveyors and only 5/9
harvesters served. New builders created branches instead of reclaiming the
previously served graph.

Do not revive the broad sticky-route variant: it scored 83/168 and lost 32.6
collected Ti/game because builders chased long unfinished paths. Do not use the
rejected opportunistic-pressure override either; it scored 5/12 against v20.
Early remote losses were gun races in which defensive guns spent 13-41 shots
on enemy gunners while the opponent delivered 50-77 core shots. The next
combat change needs deterministic target/front ownership, not more attackers
or a role override. The next route change needs incremental memory of a
formerly connected trunk plus a bounded repair claim; it must never become a
general long-route commitment.

### v21/v22 productive-edge and ownership cycle

The first persistent repair followed remembered edges across the map. Despite
large titanium gains it finished **249/504**, core kills **214-218**; a
round-120 sibling finished 82/168, kills 69-71. Gunner preemption was also
rejected at 75/168, kills 61-82: paying 10 Ti and losing the current shot to
rotate away from a turret was worse than finishing it.

Submission v21 `exp_v20_opportunistic_trunk_repair` keeps only the safe part:
an economy builder remembers an edge it personally observed draining and
rebuilds that exact edge only when a live upstream producer and proven
downstream suffix remain **and** `can_build_conveyor` succeeds immediately. It
never walks, claims, or changes roles for repair.

| v21 local gate | Result | Core kills | v20 baseline |
|---|---:|---:|---:|
| exact v20 parent | **88/168** | **75-71** | parity |
| `spar_rush` | **156/168** | 156-7 | 158/168 |
| `oogbest-v6` | **139/168** | 136-22 | 142/168 |
| `meta-generalist-v1` | **153/168** | 153-10 | 155/168 |

Its remote sample was 14-11. Replay review then found the broader ownership
bug: when all visible enemy guns were already covered, every economy builder
called `healCore` and returned. If the core was full or out of sight, the heal
failed and the helper recalled the builder anyway. One team-lazy String loss
therefore reached turn 1000 with zero harvesters and zero conveyors.

The broad fix (always release covered-threat economy) lost 83/168 with kills
73-79 because healing during actual damage matters. Submission v22
`exp_v21_eco_release_only_damaged` releases economy only while the friendly
core is full or not locally visible; uncovered threats and visible damaged
cores retain their old priority.

| v22 local gate | Result | Core kills | v21 baseline |
|---|---:|---:|---:|
| exact v21 parent | **90/168** | **73-73** | parity |
| `spar_rush` | **160/168** | 157-5 | 156/168 |
| `oogbest-v6` | **147/168** | 140-16 | 139/168 |
| `meta-generalist-v1` | **153/168** | 152-9 | 153/168 |

Ten v22 unrated series scored **30-20**, estimated core kills **30-19**.
Unchanged versions: CtrlAltDefeat 10-0, Orizon 7-3, team lazy 6-4, SmartFridge
6-4. Updated Pantheon v14 was 9-1 against v22 and is new meta evidence, not an
apples-to-apples regression from the earlier v13 control. Across all 50 games
v22 averaged 10.36 connected and 1.32 disconnected conveyors. The new
team-lazy String replay built five harvesters and won by core destruction on
turn 829, directly confirming the ownership fix. Replays:
`C:/Users/subodh/Downloads/fcode-gate-artifacts/ladder-v22-20260803/`.

A pinned v18 control against Pantheon v14 on String, Pinch, Bridge, Atoll, and
Sprint scored **0-5**, all core losses. V22 scored 1-4 on its corresponding
five-map series. Pantheon v14 is therefore a chassis-wide new-meta weakness,
not evidence that v22 regressed v18. Control replays:
`C:/Users/subodh/Downloads/fcode-gate-artifacts/ladder-v18-pantheon-v14-control-20260803/`.

## Conveyor iteration on production engine 2.3.3

Live observation and local replay audits confirmed the parent can build many
conveyors while leaving harvesters unserved. Causes in the inherited router:
any adjacent conveyor counts as connected, arbitrary visible conveyors are
merge sinks, and the round-40 cutoff abandons incomplete paths. Defensive
conveyors can also form wrong-facing loops.

`conveyor_audit.py` now reports facing-proven connections, dead ends, cycles,
backfeeding roots, served harvesters, and post-round-40 construction from
`.replay26` files.

| Experiment | Parent result | Long-game result | Decision |
|---|---:|---:|---|
| `exp_connected_economy` | 3/12, kills 3-9 | broad rewrite | reject: opening changed |
| `exp_late_route_repair` | 83/168, kills 64-79 | 19/25; Ti 4838-2785 | mechanism pass, combat fail |
| `exp_late_route_idle` | 81/168, kills 64-77 | 17/27; Ti 4017-3496 | reject |
| `exp_stalemate_route_repair` | 82/168, kills 70-71 | 12/26; Ti 3528-3565 | round 300 too late |
| `exp_waller_route_repair` | rush screen 2/12 | hot scan from round 1 | reject: CPU/hot-path pollution |
| `exp_waller_route_light` | **256/504 (50.8%)**, kills **210-211** | **45/81**, Ti **3328-3245** | hold: misses kill gate by one |
| `exp_route_integrity` | 85/168, kills 71-74 | Sweden 7/8 | reject: topology guard became a specialist trade |
| `exp_waller_route_reserve` | fast 5/12, kills 5-7 | not gated | reject before full gate |

The final lightweight mechanism observes the graph only on the non-attacking
waller after round 120, defers to healing, repairs at most eight links, merges
only into a facing-proven empty trunk, and can rebuild one orphan-rooted cycle
link. It is the only branch worth revisiting, but it is **not promoted**: the
declared parent gate required nonnegative core kills. No unrelated-family gate,
ZIP, upload, activation, or root replacement was performed.

The downloaded production v9 archive is byte-identical to
`bots/meta-generalist-v1` across all four Python sources. The audited 95 ladder
games produced 43 wins and 52 losses; 49 losses were core destruction and 46
of those had multi-turret home pressure. In the newest 45 games, 23 of 24 core
losses had multiple attackers and 23 were gunner-only. No enemy builder was
adjacent to the core when the first core shot landed in any of the 49 losses,
so builder-chasing and broad recall are misdiagnoses. At
round 40, mean served-harvester fraction was 79% in wins and 73% in losses.
Both titanium losses had incomplete networks; one contained a four-conveyor
cycle trapping a seven-link disconnected branch. Routing is real but secondary,
so neither rejected route variant should
be promoted over the exact active source.

## Current meta evidence

Production replay measurements across unrelated top teams:

| Team archetype | First gun | Guns near enemy core | Economy / defense |
|---|---:|---:|---|
| Oogway v7 | t24 | 2.2 | 13.4 conveyors, 3.0 harvesters |
| Orizon | t18 | 16.0 | 8.0 conveyors, 1.9 harvesters |
| Prompt Engineers | t26 | 14.0 | 3.2 conveyors, 1.0 harvester |
| Flotte | t22 | 6.5 | no economy; ~5.7 home barriers |
| Pantheon | t22 | 18.7 | 17.7 conveyors, 4.1 harvesters, ~39.8 barriers |

General conclusions:

- The field builds economy, then converts actions into core pressure. Fixed
  early all-in allocation starves income; v8's t40 transition was the first
  local experiment to beat its parent.
- Delivery builders matter. The new candidate fixes a real engine-layer bug
  that let them survive in gun lines.
- Direct siege succeeds against undefended cores. Fortified cores need safe,
  reactive handling, but local barrier/breacher proxies have not produced a
  proven generalist gain.
- Long stalemates are congestion/economy problems. Reassigning all freed or late
  builders to siege reduced collected titanium and lost.
- A single local responder, surgical turret counter-battery, soft recall, early
  two-sieger pressure, and t40 economy transition are already in v8.

## Rejected experiments from the 2026-08-02 cycle

Keep these folders as evidence; do not stack or rename-and-repeat them.

| Experiment | Key result | Why rejected |
|---|---|---|
| `exp_meta_reinforce` | 43%/168 vs v8, kills 65-80 | whole population converted; ~220 less Ti collected/game |
| `exp_meta_late_reinforce` | 45%/42, kills 16-20 | late production still lost ~140 Ti/game in screen |
| `exp_meta_gunner_defense` | 57%/168 vs rush, then 43%/336 vs v8 | combined steering+ammo was a specialist trade |
| `exp_meta_emergency_ammo` | 38%/42 vs v8 | low-HP conversion drains the race |
| `exp_meta_gunner_aim` | 50% screens vs v8 and rush | mechanically valid, no gain |
| `exp_prearmor` | 51%/336 vs v8; combined 56%/336 vs rush | neutral/noisy; six sites best, larger rings regress |
| `exp_meta_armor_rebuild` | 51%/168 vs prearmor, 47%/168 vs rush | healing opportunity cost cancels absorb benefit |
| `exp_meta_breacher` | 45% screen vs v8; +3 vs historical barrier fort | control already won 90%; no attributable gain |
| `exp_flank` | 44%/336 vs v8 | spread heuristic regressed conversion |
| `exp_trans_def` | 46%/336 vs v8, 45% vs rush | defense overriding transition pulls pressure away |
| larger prearmor (10/14) | 39-51% | extra denial actions are too expensive |

Earlier measured negatives still stand: permanent guards, global hard recalls,
full-ring sealing, attack-gate removal, launcher highways, from-scratch bastion,
all-sieger allocation, and broad `attackBan` rewrites.

### Architecture-ceiling experiments

The follow-up home-defense cycle is closed. These were deliberately small
mechanism probes; none is a promotion candidate.

| Experiment | Key result | Decision |
|---|---|---|
| `exp_meta_multi_recall` | 47%/168, kills 64-78 | reject |
| `exp_meta_recall450` | 43%/168, kills 57-83 | reject |
| `exp_meta_safe_counter60` | 52% parent, 52% rush, 45% Oogbest | reject: opponent regression >5 pp |
| `exp_meta_damage_sequential` | 49%/168, kills 71-72 | reject |
| `exp_meta_damage_sequential400` | 49%/168, kills 70-69 | reject: misses parity |
| `exp_meta_counter_tend` | 51%/168 | reject: -739 mean Ti in round-1000 subset |
| `exp_meta_counter_tend6` | 47%/168, kills 63-78 | reject |
| `exp_meta_counter_tend8` | 52% parent; 51% rush | incomplete Oogbest gate; not promoted |
| `exp_dynamic_fronts` | 92/168 parent; 93/168 rush; 89/168 Oogbest | first consistent architectural gain, but only +1.8 to +3.6 pp; hold, do not promote |

The repeated tradeoffs establish a chassis ceiling. `exp_dynamic_fronts`
replaces the single responder with up to three distinct pressure/coverage-sized
front assignments, preserves two local economy builders, latches both siegers
on offense, and bounds countergun maintenance to eight heals. It improved all
three tested families and core-kill margins, but the effect is still modest:
parent 92-76 (kills 74-62), rush 93-75 (82-64), Oogbest 89-79 (84-63).
Therefore fixed ownership was one real problem, not the whole problem. Stop
tuning recall HP, reserve thresholds, or heal counts; the next experiment must
also replace unbounded extra spawning and the universal round-40 gun churn.

## Architecture and store protocol

`exp_trans_40` / `meta-generalist-v1` are mostly memoryless state scorers with
small per-unit caches and explicit roles. Each unit has its own `Player` object;
there is no persistent state across matches.

| Slot | Use |
|---:|---|
| 0 | spawned builder count |
| 1-6 | map sharing |
| 7 | opening/exploration target |
| 8 | waller ID + 1 |
| 9-10 | two sieger IDs + 1 |
| 11 | enemy core position |
| 12 | soft recall flag |
| 13 | Sieger 2 temporary counter target |
| 14 | home defender ID + 1 |
| 15 | verified home-threat position |

Writes are buffered until the next round. Entity IDs interleave across teams;
never infer roles from global ID thresholds. Use IDs returned by spawn and store
them explicitly.

Core behavior: five opening builders/roles, resource-gated additional spawning,
ammo buffer, verified threat/recall, one nearby responder. Builder priority:
assigned home response; bounded wall duty; designated siege; state scorer;
passive wall. Sieger 2 counters a turret only when every direct core plan is
unsafe. Gunners preserve core-capable aim and now correctly target enemy
builders.

## Engine and measurement gotchas

- Local WSL venv: `~/.venvs/fcode`; activate it before tests/gates.
- Current local CLI: production `fcode 2.3.3`; all 21 maps are present and the
  remote session is authenticated.
- Production 2.3.3 builder construction, attack, and healing are orthogonally
  adjacent only. Do not trust older same-tile/diagonal comments in `AGENTS.md`.
- Production 2.3.3 still uses gunner damage/cost/HP/ammo 10/10/40/2. The
  discussed 5/20/30/4 turret patch is only a proposal; if deployed, invalidate
  current numeric gates and retune ammo/resource floors.
- Bot `random` is not seeded by engine `--seed`; identical serial games can
  flip. Use 168 for clear deltas and 336 for close ones.
- Per-map gate rows are noisy and gate side labels are unreliable. Use aggregate
  results and direct seat checks only.
- Known seat-locked maps can force outcomes between close bots. More seeds do
  not repair deterministic seat locks.
- An uncaught exception permanently destroys the unit on dev26+; preserve the
  top-level `try/except` armor.
- Turrets/buildings and builder bots occupy separate tile layers. Query both
  `get_tile_building_id` and `get_tile_builder_bot_id`.
- Root and many experiment READMEs may be stale copies. Trust source hashes,
  commit messages, replay traces, and gate CSV blocks.
- `bots/champion` is stale and can invert rankings. Gate against the current
  frozen parent plus unrelated archetypes.

## Commands

From WSL:

```bash
cd /mnt/c/Users/subodh/Downloads/fcode
source ~/.venvs/fcode/bin/activate
python tests/test_v18_spawn_route_proof.py
python tests/test_v19_near_core_finish.py
python tests/test_v20_opportunistic_trunk_repair.py
python tests/test_v21_eco_release_only_damaged.py
python gate.py exp_v21_eco_release_only_damaged exp_v20_opportunistic_trunk_repair 4 quiet
python gate.py exp_v21_eco_release_only_damaged spar_rush 4 quiet
fcode run exp_v21_eco_release_only_damaged exp_v20_opportunistic_trunk_repair maps/bridge.map26 --seed 1 --tle 10 --json
```

Before any new remote action: install/authenticate the production CLI, run
`fcode maps sync`, verify engine/map pool, and rerun the relevant controls.

## Next steps

1. Keep active v22 and root unchanged. Monitor fresh ladder replays for
   cross-opponent failure categories before making another behavioral change.
2. Treat `exp_v21_eco_release_only_damaged` as the current production source.
   Its local gates and 30-20 remote threshold pass; archive and server members
   are byte-identical.
3. Updated Pantheon v14 is the remaining live weakness: ten v22 games scored
   1-9, mostly early multi-gunner core pressure; pinned v18 scored 0-5. Treat it
   as a new cross-chassis threat and seek mechanisms that generalize.
4. Do not tune by Pantheon identity or maps. Any response must also improve
   unrelated high-pressure families and preserve v22's economy conversion.
5. Do not revive walking/TTL repair, round-gated repair, gunner preemption, or
   broad covered-threat release. Their full gates failed.
6. Any upload may auto-activate; restore v22 immediately. Root replacement and
   future ladder activation changes require explicit approval.

No external action is authorized by this handoff.
