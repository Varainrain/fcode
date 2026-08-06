# ATTACK-INTEGRATION.md — for Oogway, hooking attack_advisor into OogwayAttack

Engine 2.3.6, synced 15-map pool, parent `bots/OogwayAttack` (commit 2b662d9).
Everything below was measured this session. Read `ENGINE-236-LAWS.md` first —
the constants the chassis was tuned against no longer exist.

## Read this before the call sites: what the gate can and cannot tell you

A byte-identical copy of your bot (`bots/oa_null`, md5-verified on both files)
gated against its own original reads:

| null run | candidate slot | n | win% |
|---|---|---|---|
| #1 | `oa_null` | 120 | **61%** |
| #2 | `oa_null` | 120 | 49% |
| #3 | `OogwayAttack` (reversed) | 120 | 50% |
| **pooled** | | **360** | **53.3%, CI 48.2-58.4** |

The pooled CI contains 50, so the candidate slot is not favoured — run #1 was
variance. What the instrument has is *width*: identical code lands anywhere in
49-61% at n=120. **It cannot resolve anything smaller than roughly ten points at
sample sizes we can afford** (a true +5 needs ~1500 games per arm). That is not
a reason to stop changing things; it is a reason to require a *mechanism*
receipt — a trace or replay metric proving the change does what it claims — and
to use the win rate only as a regression check ("did this fall out of the null
band?").

Every candidate below is reported with both.

## The four call sites

### 1. Seat gate -> ask the engine for the price
In `runAttack`, replace the flat `96` / `30`:
```python
floor = attack_advisor.gunner_seat_floor(ct)      # gunner cost + the core's 28 Ti ammo reserve
if ct.get_global_resources() < floor:
    ...march / harass...
```
A gunner costs 20 Ti at t0 and 58-72 Ti by t40+ (`scale% = 100 + 20*(units-1) +
1*buildings`). The flat gate refuses the cheap early seats and, late, lets the
bank drop under the core's own conversion floor.
⚠ Measured: the gate only mis-fires on ~1% of attacker turns, so this is a
correctness fix, not a points fix.

### 2. Ammo awareness — as information, NOT as a veto (measured negative)
```python
attack_advisor.pool_has_a_shot(ct)   # ammo >= 4, i.e. one gunner shot
```
19.2% of attacker turns run with the global pool under one shot's worth. It is
tempting to refuse the seat when that is true. **Do not** — that exact veto is
`oa_a7` and it gated **47.1% (CI 40.9-53.4), below the null**: the pool refills
the same turn the core converts, so a briefly-dry gun beats a turn spent not
seating one. Use the signal to *rank* seats or to size the ammo ceiling, never
to block a build.

### 3. Rotation scoring -> score the target you would actually hit ⭐ THE ONE TO TAKE
In `runGunner`'s facing loop:
```python
tiles = ct.get_attackable_tiles_from(myPos, d, EntityType.GUNNER)
kind, tid = attack_advisor.first_entity_on_ray(ct, tiles)   # the shot stops there
```
The scorer sums hits down the whole ray, but a shot stops at the first entity,
so a facing that clips an enemy conveyor at range 1 and their core at range 2
scores a core hit it can never land. This is `oa_a9`: **55.0% (CI 48.7-61.2)**,
the highest reading of the session, statistically level with the 53.3% null —
no measured gain, no measured cost, strictly more correct. Take it on
correctness.

⚠ The sibling defect is real and the fix for it measured WORSE. The scorer only
reads `get_tile_building_id`, so **enemy builders are worth zero**: a facing
covering two enemy builders scores `(0,0,0,0)` while one covering a single enemy
conveyor scores `(0,0,0,1)` and wins the rotation. That looks indefensible —
enemy builders seat their guns and heal their core, and a builder healing 4
hp/turn cancels 57% of a 7-damage gunner. But counting them (`oa_a8`,
`attack_advisor.enemy_builders_on`) gated **45.8% (CI 39.6-52.2)**, the lowest
of the ten. Best guess: a rotation that chases mobile builders gives up standing
core pressure. If you want it, rank builders strictly BELOW the core and turret
terms and re-gate — do not adopt it as written.

### 4. The ammo ceiling — your call site, not mine, and it is a wash
`runCore` converts `min(16 - ammo, Ti - 28)`. A 16 ceiling is **four gunner
shots per turn for the entire team**, attack and defence combined, however many
turrets stand. `bots/v44` already ran this line at 60 and OogwayAttack shipped
without it (PITFALL #17, carry-forward). Instrumented A/B on the same six maps
and seed: ammo-dry attacker turns **8.4% -> 0.0%**, at the cost of seating ~40%
fewer guns because the titanium goes to ammo instead. `attack_advisor.
recommended_ammo_ceiling(ct)` sizes it from turret count instead of a constant.

**Gate: `oa_a4`, 360 games, 50.6% (CI 45.4-55.7) — dead level with the null.**
So take it for burst capacity if you like the shape, but it is not points, and
together with `oa_a7` it says something more useful than either alone (see the
conclusion under the results table).

## Results table

| candidate | change | n | win% vs parent | vs null | mechanism receipt |
|---|---|---|---|---|---|
| `oa_null` | byte-identical control | 360 | 53.3% (CI 48.2-58.4) | — | — |
| `oa_a1` | one action per turn in the seat branch | 120 | 52% | inside band | double `moveTo` on 7.3% of attacker turns |
| `oa_a2` | cost-aware seat gate | 120 | 52% | inside band | flat gate mis-fires on 1.0% of turns |
| `oa_a3` | skip seats a body is standing on | 120 | 52% | inside band | fires on 0.2% of turns — dead path |
| `oa_a4` | ammo ceiling 16 -> 60 | **360** | 50.6% (45.4-55.7) | inside band | ammo-dry 8.4% -> 0.0%, guns seated 8 -> 5 |
| `oa_a7` | do not seat while the pool is dry | **240** | 47.1% (40.9-53.4) | below null | ammo-dry fires on 19.2% of attacker turns |
| `oa_a8` | enemy builders count in rotation | **240** | 45.8% (39.6-52.2) | lowest reading; do not adopt | — |
| `oa_a9` | score only the first entity on the ray | **240** | **55.0% (48.7-61.2)** | highest reading; level with null | — |
| `oa_a10` | attacker share 1/3 -> 1/2 | **180** | 48.3% (41.1-55.6) | inside band | — |
| `oa_a11` | attacker share 1/3 -> 1/4 | **180** | 54.4% (47.2-61.6) | inside band | — |

**Nothing promoted.** Eight independent mechanisms, 1800 games, every one inside
a null band 48.2-58.4. Two things follow, and the second is the more important:

1. The attacker share is on a flat plateau around 1/3. Halving it and
   one-and-a-half-ing it both land inside the band, with the *fewer*-attackers
   direction reading slightly better — which is the direction the cost law
   predicts (fewer living units = cheaper guns = more econ), but not at any
   strength worth acting on.
2. **The ammo pair resolves where the real constraint is.** `oa_a4` relieves the
   throttle (ammo-dry 8.4% -> 0.0%) and reads dead level; `oa_a7` respects it and
   reads *below* the null, because the pool refills the same turn the core
   converts, so a briefly-dry gun beats a turn spent not seating one. Ammo is a
   measurable throttle that costs nothing to relieve and nothing to respect —
   i.e. it is not what is limiting us. At the margin the offense is TITANIUM
   bound, and under `scale% = 100 + 20*(units-1) + 1*(buildings)` titanium is a
   function of our own living entity count. That is the first mechanical account
   of the guns-on-core invariant (8.8 / 7.0 / 6.2 against our 4.0) that is not
   tempo and not aim, both of which this repo has already falsified.

The next experiment I would run in this lane is not another attack tweak: it is
whether a leaner *own* footprint buys guns. Same siege code, fewer live
conveyors — the cost law says every one of them is a 1% tax on every gun we will
ever build.

## What I would NOT bother with (measured negatives, so nobody repeats them)

- The seat-occupied collision and the "adjacent but unbuildable" no-op loop that
  a full code review ranked as the top two attack bugs: instrumented at 0.2% and
  0.1% of attacker turns. Real code defects, no game impact on this chassis.
- The `moveTo` launcher-halo freeze (`mapPathfinding.py:571-592`): an attacker
  whose next step is within d²<4 of an enemy launcher returns without moving or
  acting, and the random-unstick below is unreachable. Genuine permanent freeze
  — but nothing on the current ladder builds launchers, so it never triggered in
  any traced game. Worth the three-line fix on principle, not on evidence.
