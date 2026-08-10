# FLORENT CODE LEAGUE — COMPLETE RULES & COSTS
*(every number pulled from the engine's own source, engine 2.3.6 — nothing from memory)*

## THE GAME IN ONE PARAGRAPH
Two teams, each with a 2×2 **core** (500 hp). Kill the enemy core or have the
better economy at turn 1000. Your core spawns **builder bots**; builders mine
via **harvesters**, move titanium with **conveyors**, and construct turrets
(**gunners/sentinels**), **barriers**, **splitters** and **launchers**. Everything is
paid from ONE shared team titanium pool. Turrets need **ammo**, which the core
converts from titanium. Each unit runs your Python code once per round.

## WIN CONDITIONS (in order)
1. **Core Destroyed** — enemy core hp to 0. The normal win.
2. At turn 1000, the tiebreak cascade (from the engine's own labels, in
   order): **resources → titanium collected → harvesters → titanium stored →
   coinflip**. In practice: total collected titanium decides most t1000 games
   — eco wins long games by default.
3. A bot can also `resign()` (destroys own core).

## THE MONEY SYSTEM
- Start with **500 titanium** (shared team pool — every unit spends from it).
- **Passive income: +10 titanium every 4 turns** (tiny — you MUST mine).
- **Harvesters** (20 Ti) mine ore tiles. A harvester hands its output to
  **adjacent buildings, round-robin, least-recently-used cardinal side — and
  it does NOT check ownership**. That last part matters: an enemy conveyor
  plugged next to your harvester silently steals a share of your income.
  (Top teams do this deliberately; we detect it.)
- **Conveyors** (3 Ti, have a facing) pass resources along toward the core.
  **Splitters** (6 Ti) split a line into multiple outputs (redundancy).
  Resources on a tile stack up to **10** (STACK_SIZE).
- **Ammo**: the core converts titanium → ammo 1:1 (`convert_ammo`, once per
  turn, free action). Shots cost ammo from the GLOBAL pool:
  gunner **4/shot**, sentinel **10/shot**, launcher 0.

## COST SCALING (why you can't spam)
Every build costs its base price times a scale factor:
**scale% = 100 + 20 per unit you own (beyond the first) + 1 per building you own.**
So at 5 units + 30 buildings a "20 Ti" gunner really costs 20 × 2.1 = 42.
Over-expansion taxes every future purchase — 70 conveyors = +70% on everything.

## FULL PRICE / STATS TABLE (base costs, before scaling)

| thing | cost | hp | damage | fire rate | ammo/shot | range² (=vision) | notes |
|---|---|---|---|---|---|---|---|
| Core | — | 500 | — | — | — | 36 | spawns builders adjacent (d²≤2); acts within d²≤8 |
| Builder bot | 30 | 40 | 2 (adjacent only) | 1/turn | costs 2 Ti/shot | 20 | the only thing that moves; builds/heals/fires |
| Gunner | 20 | 25 | 7 | **every turn** | 4 | **13** | fires a straight line in its facing; first non-empty tile is hit |
| Sentinel | 30 | 40 | 18 | every **2** turns | 10 | **32** | the artillery: outranges everything |
| Launcher | 20 | 30 | — | 1/turn | 0 | 26 | picks up a builder bot and THROWS it to a target tile |
| Barrier | 3 | 30 | — | — | — | — | passable ONLY to its owner's units; blocks firing lines |
| Conveyor | 3 | 20 | — | — | — | — | has a facing; impassable to everyone |
| Splitter | 6 | 20 | — | — | — | — | splits resource flow |
| Harvester | 20 | 30 | — | — | — | — | only on ore tiles; round-robins output, no ownership check |
| Heal | 1 Ti | — | **+4 hp** | 1/turn | — | — | builder heals ALL friendlies on one adjacent tile |
| Gunner rotate | 10 Ti | — | — | cooldown 1 | — | — | turning a gunner isn't free |

- Team-wide cap: **50 units**. Game lasts max **1000 turns**.
- Map tiles: empty / wall / titanium ore. Walls block movement AND firing
  lines but can't be shot.

## HOW COMBAT ACTUALLY WORKS
- **Gunners** fire a straight line in their facing direction, every turn.
  The FIRST non-empty tile in the line gets hit — walls, builder bots, and
  buildings all block the line (walls can't be damaged). So a 3-Ti barrier
  in the line eats the shot.
- **Sentinels** same idea but range² 32 (≈5.6 tiles) vs gunner's 13 (≈3.6),
  18 damage, every 2 turns.
- **THE LAW**: range 13 vs range 32 means **a gunner can never duel a
  sentinel** — the sentinel kills it before it's ever in range. Counters to
  a sentinel: barriers in its line, your own sentinel, or out-healing it
  (9 dmg/turn sustained vs heal 4/turn per builder → 3 healers beat it).
- **Ammo economics** (our favorite fact): a sentinel pays 10 Ti ammo per
  shot; a 30-hp barrier takes 2 shots. Every 3-Ti barrier it chews through
  costs the shooter **20 Ti**.
- **Builder bots** can fire too: 2 damage, 2 Ti, orthogonally adjacent tile
  only, and only damages the BUILDING on that tile.
- **Launchers** don't shoot — they pick up a builder bot (either team's, per
  the July patch notes) and throw it across the map. Rare but scary.

## MOVEMENT & ACTION RULES (2.2/2.3 engine changes — trip everyone up)
- Builders move **4-way only** (cardinals; diagonal move raises an error).
- **Act XOR move**: if a unit acts on round N, it can't move until N+1.
  Cooldowns: `get_action_cooldown()` / `get_move_cooldown()`.
- ALL builder actions (build, heal, fire) target **orthogonally adjacent
  tiles only** — never diagonal, never the tile you stand on. Standing on
  your own build site = the build silently can't happen (classic bug).
- Spawning: the core spawns builders onto tiles around its 2×2 footprint;
  spawn respects the 50-unit cap.
- An uncaught exception in your bot code **permanently kills that unit**
  (CPU timeout only skips the turn) — everyone wraps run() in try/except.

## VISION (why "radar" matters)
Every entity sees a radius around itself; the team shares what any unit sees
THIS turn (no fog memory — out-of-vision tile queries throw errors).
- Builder sees d²20 (~4.5) — SHORT. A sentinel parked at d6 is invisible to it.
- **Core sees d²36 — which covers every tile a sentinel can legally shoot it
  from (32)**. That's why our bot uses the core as an early-warning radar.

## COMMUNICATION
Teams share a **16-slot store of u32 values** (`read_store`/`write_store`).
Writes land at the START of the next turn (one-round lag — team counters can
race). This is the only messaging between units. Our bot's slot map: 0 spawn
count, 1-6 shared map, 7 core pos + threats, 8 symmetry, 9 recall, 10 jam
claim, 11 counter-battery claim, 12 sentinel radar, 13 seal claim, 15
defensive barrier budget.

## MISC THAT COMES UP
- Builders can `destroy()` ALLIED buildings for free (repurpose a tile).
- `self_destruct()` exists; deals no damage (nerfed).
- Debug: bots draw colored dots/lines saved into the replay — that's the
  colored overlay you see in the visualiser (our colors: blue=hunting core,
  orange=marching, red=fighting turret, green=healing core, yellow=harvest).
- Maps are 180°-rotation symmetric; sizes ~10×10 (fjordgate) to 30×20.
  Cores can be 8 tiles apart (pure race maps) or 28+ (eco maps).

## THE FIVE NUMBERS TO REMEMBER IF YOU REMEMBER NOTHING ELSE
1. **13 vs 32** — gunner range vs sentinel range: gunners never duel sentinels.
2. **3 Ti barrier eats 20 Ti of sentinel ammo** — defense is economic warfare.
3. **+20%/unit +1%/building** — every purchase raises all future prices.
4. **4 hp/turn heal for 1 Ti** — 3-4 healers out-heal any single turret; heal
   walls are why sieges stall.
5. **Harvester output has no ownership check** — income can be stolen by
   adjacency. Watch for enemy conveyors near your harvesters.
