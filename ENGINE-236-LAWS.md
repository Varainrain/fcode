# ENGINE 2.3.6 — the measured rules everything in this repo was NOT designed for

Measured 2026-08-06 on `fcode 2.3.6`, WSL, with probe bots (`bots/probe_scale`,
`bots/probe_scale2`, `bots/probe_cost`) — not read off a changelog. Per
PITFALL #18 (*engine patches void all numbers*), every constant below differs
from the ones quoted in HANDOFF.md / CLAUDE-PITFALLS.md, so the arithmetic in
those docs — and any bot tuned to it — is stale.

## 1. The map pool rotated to 15 maps and 12 of them were not on disk

`fcode maps list` on 2.3.6: **antler, archipelago, atoll, drumlin, eider,
fjordgate, heart, hive, jackpot, lighthouse, meander, moonrise, nordkap, saga,
snowflake**. Only atoll/hive/jackpot survive from the old 21. Every local gate
run before `fcode maps sync` was scored on 18 maps the league no longer plays.
The retired maps are parked in `maps_stale_236/`; `maps/` is now the live pool.

## 2. The unit economy inverted

| | docs said | 2.3.6 |
|---|---|---|
| GUNNER_BASE_COST | 10 | **20** |
| GUNNER_DAMAGE | 10 | **7** |
| GUNNER_MAX_HP | 40 | **25** |
| GUNNER_AMMO_COST | — | **4** |
| SENTINEL | 30 Ti / 18 dmg | 30 Ti / 18 dmg / 40 hp / **10 ammo** / cooldown 2 |
| BUILDER_BOT_BASE_COST | — | **30** |
| HARVESTER / CONVEYOR / BARRIER | — | 20 / 3 / 3 |
| HEAL_AMOUNT | 4 | 4 |
| CORE_MAX_HP | 500 | 500 |

New entity type: **SPLITTER** (6 Ti, 20 hp) with `build_splitter()`. Nothing in
`bots/` builds one; nobody has looked at it.

**The heal arithmetic that follows is the important part.** A builder heals
4 hp/turn. A gunner deals 7. So **one enemy builder healing cancels 57% of a
gunner, and two healers cancel it entirely** — a lone seated gun can never
break a tended core. A sentinel averages 9 dmg/turn (18 on a 2-turn cooldown),
so two healers stop that too. Concentration is not a preference on 2.3.6, it is
the only thing that damages a defended core, which is the mechanism behind the
one invariant we never beat: *every team above us lands more guns on the enemy
core than we do — 8.8 / 7.0 / 6.2 against our 4.0.*

## 3. Costs SCALE with what you own (this is new and it is the big one)

`get_scale_percent()` plus per-entity cost getters (`get_gunner_cost()`, …).
Measured law, from a probe that pinned the unit count and built/destroyed
conveyors one at a time:

```
scale%  =  100  +  20 x (living units - 1)  +  1 x (living buildings)
cost    =  base cost x scale% / 100
```

- Verified linear: 1 unit → 100%, 2 → 120%, … 12 → 363%; each conveyor built
  moved it +1 and each conveyor **destroyed moved it back -1**, so the term is
  *alive*, not *ever built*.
- Observed in a real game: a gunner costs **20 Ti at t0 and 58-72 Ti by t40-240**
  (probe log: r5 → 40, r40 → 58, r240 → 72). Builders go 30 → 108.

Consequences the whole team is currently paying for blind:

1. **Our own economy taxes our offense.** Every conveyor makes the next gunner
   1% dearer, permanently, until it dies. A 100-building bot pays roughly double
   for the same siege that a 20-building bot buys.
2. **Every hardcoded titanium gate in every bot is now wrong**, in both
   directions: too strict at t0 (when guns are cheapest and the enemy has no
   defence), too loose late (when passing the gate still leaves you unable to
   pay, or drops the bank under the core's ammo-conversion floor). Ask
   `ct.get_gunner_cost()` instead of comparing to a number.
3. **Attrition subsidises the loser.** Killing an enemy builder cuts 20% off
   *their* next purchase; killing their conveyors cuts 1% each. Chip damage on
   the periphery makes the enemy's core defence cheaper. Going at the core does
   not.

## 4. Ammo is a hard team-wide firepower throttle

Turrets fire from one global pool; only the core refills it, at most once per
turn, 1:1 from titanium. The chassis converts
`min(16 - ammo, titanium - 28)` — a **16-ammo ceiling = 4 gunner shots per turn
for the entire team**, attack and defence combined, no matter how many turrets
are standing. Instrumented over 12 games (`bots/oa_trace`), **19.2% of all
attacker turns ran with the pool under a single shot's worth of ammo.**

Our measured guns-landed-on-their-core is 4.0. Our sustainable shots per turn
is 4. That may be a coincidence; it is at minimum a ceiling we are sitting on,
and v44 already ran this line at 60.

## 5. The gate instrument is noisier than the docs claim — recalibrate before believing anything

`bots/oa_null` is a byte-identical copy of `bots/OogwayAttack` (md5-verified,
both files). Three 120-game runs of identical code against itself:

| run | candidate slot | result |
|---|---|---|
| #1 | `oa_null` | **61%** — identical code clears the PROMOTE bar by six points |
| #2 | `oa_null` | 49% |
| #3 | `OogwayAttack` (reversed) | 50% |

Pooled: **192/360 = 53.3%, 95% CI 48.2-58.4** — the CI contains 50, so there is
**no systematic candidate-slot bias**; run #1 was variance. What the instrument
has is width: at n=120 identical code lands anywhere in 49-61%, so **nothing
below roughly a ten-point effect is resolvable** at sample sizes we can afford
(detecting a true +5 needs ~1500 games per arm). The branch
`claude/measurement-fixes` found the same thing from the other direction —
three repeats of a 168-game control reading 49/56/51, and warns that "a
168-game PROMOTE is a 1-in-10 coin flip".

The practical consequence is not "stop changing things", it is **demote the win
rate to a regression check and promote the mechanism receipt to primary
evidence**: a trace counter or replay metric proving the change does what it
claims. Twenty-five experiments have now read "neutral" on an instrument that
cannot see them.

**Rule: run the byte-identical null on the current engine and map pool in the
same session, and read every candidate against that null, not against 50%.**
`gate2.py` (lifted from `claude/measurement-fixes`) prints Wilson CIs, per-seat
splits and seat-lock flags; main's `gate.py` prints none of it.
