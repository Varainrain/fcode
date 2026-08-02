# FCode production handoff

Updated 2026-08-02. Read this before changing a bot. `AGENTS.md` contains the
iteration rules; `WORKFLOW.md` contains the gate protocol.

## Current decision

- Strongest local candidate: `bots/meta-generalist-v1`.
- Parent: `bots/exp_trans_40`, the shipped-v8 source lineage.
- Only change: gunners now recognize enemy builders on the engine's separate
  builder layer. The parent fired/rotated only when an enemy building occupied
  the tile; a lone delivery builder was invisible.
- Frozen package: `meta-generalist-v1.zip`; manifest:
  `meta_generalist_v1_results.json`.
- Local only. It has not been uploaded, queued, activated, or copied to root.
- Root `main.py` / `bot.zip` remain the historical v88 package and are dirty in
  git from prior user work. Do not replace them without explicit approval.
- Production status cannot be queried with the current CLI session: the local
  WSL environment is staging `fcode 2.3.2.dev29` and its session is expired.
  The user says the real competition has started. Re-authenticate/update before
  any remote verification and never describe local dev29 gates as production.

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
| `meta-generalist-v1` | current local candidate; gunner builder-layer bug fix |

The exact active production version must be verified after re-authentication.
Commit messages say transition40 was shipped as v8; do not infer activation from
the local root files.

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
- Current local CLI: `fcode 2.3.2.dev29` staging. Production has started; update
  and sync production maps before trusting new gates.
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
python tests/test_meta_builder_targeting.py
python gate.py meta-generalist-v1 exp_trans_40 8 quiet
python gate.py meta-generalist-v1 spar_rush 4 quiet
fcode run meta-generalist-v1 exp_trans_40 maps/duel.map26 --seed 1 --tle 10 --json
```

Before any new remote action: install/authenticate the production CLI, run
`fcode maps sync`, verify engine/map pool, and rerun the relevant controls.

## Next steps

1. Do not mutate `meta-generalist-v1`; branch experiments from it.
2. With explicit user approval only, authenticate production and upload the ZIP
   as inactive. Do not activate.
3. Run multiple unranked series against diverse live opponents, not only Ijti.
   Download every replay. Require nonnegative kills and evidence that enemy
   delivery builders are actually being shot in more than one opponent family.
4. If production confirms the candidate, ask separately before root replacement
   or activation.
5. Next local hypotheses should come from fresh production losses. Prefer source
   correctness bugs or narrowly reactive observable-state fixes. Do not revisit
   the rejected allocation, ammo, armor-rebuild, or breacher branches without
   new multi-opponent evidence.

No external action is authorized by this handoff.
