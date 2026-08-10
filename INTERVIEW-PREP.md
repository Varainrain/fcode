# INTERVIEW PREP — Erebus / HEIMDALL

## THE MATCH TO SHOW

**Rated ladder, Erebus 4-1 Pantheon (~#5 team, 1959 elo at the time)**
https://game.code.florent.vc/visualiser?matchId=f23a8ca7-60b6-46a5-a6e1-a9976eafdd44

Why this one: it's rated (not a scrim), we won 4 of 5 by core destruction —
three of them in under 200 turns — and the one loss was a t1000 tiebreak, so
every game is watchable. And there's a story: we beat Pantheon **with a
strategy we learned by watching Pantheon** (see "the siege sentinel" below).

### Game 3 — fjordgate, win in 101 turns, 504-0 core damage (the flex)
Scrub to these turns:
- **t1-t6**: our siege sentinels land at d5-7 of their core — the opening IS
  the siege on this map
- **t9**: first core damage. From turn 9 to 101 they never touch our core (0
  damage taken all game)
- **t91, t99**: "entomb" barriers placed on the tiles next to their core —
  denying the squares their builders need to stand on to heal it. The kill
  follows immediately.

### Game 1 — snowflake, win in 130 turns (every mechanic in one game)
- **t39-54**: our gunner ring closes on their core (d3 → d1)
- **t41-72**: five entomb caps around their core + three cut-and-cap barriers
  on tiles where their conveyors died (once capped, the line can never be
  rebuilt in place)
- **t50-70**: their counter-attack — sentinel at d3 + gunner at d5 of OUR
  core. We take 288, stabilize, and win the race 504-288.

---

## "EXPLAIN YOUR BOT" (the 60-second version)

The bot is called **HEIMDALL** — the Norse watchman who sees everything and
sounds the horn. That's literally the architecture: the core has the biggest
vision radius in the game (36, which covers every tile a sentinel can legally
fire from), so we use it as a **sensor** that broadcasts threats through the
shared store, and every defensive mechanism keys off that signal. Offense is
one idea: sentinels outrange everything, so get one parked at the enemy core
with support before they can do it to us.

We built it empirically: watch replays of losses, name the exact failure,
ship ONE scoped fix, gate it over hundreds of lab games before it goes live.
Every mechanic in the bot exists because a specific opponent beat us with
something and we measured our way to the counter.

## THE NAMED MECHANICS (what he'll see on screen)

- **Siege sentinel** — attackers park ONE ray-aligned sentinel in firing
  range of the enemy core before spamming gunners. Learned from watching
  Pantheon beat sporks (#1) with it: a sentinel deals a sustained 9 dmg/turn
  and most heal responses max out around 5-6/turn, so the math is a slow
  guaranteed kill. We measured their formula, implemented it, and our gate
  read 77% with a 105-31 kill ratio — biggest margin we ever recorded.
- **Entomb** — barriers are passable only to their owner. So we cap the
  tiles adjacent to THEIR core: their healers lose the squares they need to
  stand on. Heal-denial for 3 titanium a tile.
- **Cut-and-cap** — when an enemy conveyor dies, cap the tile with a barrier
  within a few rounds: the line can never be rebuilt in place, the reroute
  tax is permanent. We spotted Pantheon doing this, then confirmed Jython
  used it to beat sporks, then shipped it ourselves.
- **The seal** — reactive barrier geometry around our own core that blocks
  turret firing lines. Triggers on sentinels and on gunner PACKS (2+), never
  on lone harassers (that scoping cost us a 0/10 map until we measured it).
- **Sentinel radar + counter-battery** — the core broadcasts parked enemy
  sentinels it can see (builders' vision is only 20, so d5-9 "artillery
  parks" are invisible to them); one builder answers with OUR sentinel next
  to our healers — our defender out-heals the duel, theirs dies in 3 shots.
- **The early horn** — if the core sees 2+ turrets in firing range before
  t120 and has taken a hit, it sounds recall immediately instead of waiting
  to bleed to 400hp. Turned a 30% matchup vs a hyper-rush team into 65%.
- **Spawn rate limit** — the chassis used to respawn builders forever into
  kill zones (we measured 76-109 builder deaths in single games vs one
  turtle team). 8-round respawn cooldown fixed our worst matchup.

## ENGINE NUMBERS THAT ANCHOR ANSWERS (memorize-ish)

- Gunner: 20 Ti base, 7 dmg, 25 hp, range² 13, fires every round, ammo 4/shot
- Sentinel: 30 Ti, 18 dmg, 40 hp, range² 32, fires every 2 rounds, ammo 10/shot
- → **a gunner can NEVER duel a sentinel** (range 13 vs 32) — this one fact
  reshaped our whole attack and defense
- Barrier: 3 Ti, 30 hp → eats 2 sentinel shots = 20 Ti of their ammo. Our
  cheapest weapon is economic.
- Builder: 30 Ti, 40 hp, vision² 20, heals 4 hp for 1 Ti — 3 healers beat a
  sentinel's DPS for 3 Ti/turn
- Core: 500 hp, vision² 36 (covers all sentinel firing tiles — why it's our radar)
- Cost scaling: +20% per unit, +1% per building owned — over-expansion taxes
  every future turret
- Harvester output round-robins to ADJACENT buildings with no ownership
  check — enemy conveyors plugged into your harvesters literally steal your
  income (top teams do this; we detect it)

## "HOW DO YOU TEST?" (the methodology story — devs love this)

- Every change is gated vs the frozen champion: 150-game screen, 300 for
  close calls. Byte-identical bots measure 53% in our harness, so anything
  inside ~48-58 is noise — we say "free" not "better" unless it clears that.
- **Field > mirror**: lab results get overridden by real matches. We shipped
  a mechanically-perfect seal once that went 0-5 vs sporks because their
  stolen economy funded the ammo war forever — rolled it back same hour.
- We wrote our own replay parser and autopsy scripts — every loss gets
  quantified (core damage timelines, turret distances, builder deaths)
  before any code is written. Rule: watch replays first, code second.
- We built **opponent replicas** (a sporks-style rusher) and a **map
  compiler** — we reverse-engineered the .map26 format (roundtrip
  byte-identical) and generated a 6-map stress suite so we can reproduce
  rare failure modes on demand instead of waiting for the ladder to
  serve us the right map.

## WAR STORIES (best honest answers to "what was hard?")

1. **The seal that strangled us.** Our first core-defense build was a
   12-tile barrier ring with great receipts on another chassis. On this
   chassis it starved us: conveyors connect cardinally and the ring closed
   every approach — 340 titanium mined in 735 turns vs thousands normally.
   One smoke game caught it. Lesson: a mechanism gated on one chassis can be
   poison on another.
2. **The spawn faucet.** Our worst matchup ("not adgato") confused us for a
   week. Autopsy showed our core fed 76-109 builders per game into their
   gunner nets — the respawn rule had no memory of what happened to the last
   builder. An 8-round cooldown fixed it; their whole playstyle was
   accidentally a counter to one line of our spawn logic.
3. **The out-of-vision trap.** Tile queries RAISE outside vision in this
   engine. A muzzle-jamming feature we built silently no-opped in its main
   use case because one probe lacked a vision guard and the exception path
   returned early. An adversarial code review caught it before it shipped.
4. **Winning the damage war and losing anyway.** One opponent out-healed
   2989 core damage and beat us on tiebreak with 21 harvesters to our 4.
   Defense and damage were solved; economy decides the long games. That's
   our current frontier.

## TEAM (credit where due)

- **Oogway (Varainrain)** — chassis owner: dispatch, roles, shared-map
  bit-packed store protocol, Dijkstra pathfinding. Integrates all merges.
- **oni** — attack/siege lane, runs his own measurement pipeline (his cost
  law: scale% = 100 + 20*(units-1) + buildings; his mirror-null calibration).
- **me (ic3d)** — defense module + intel/measurement: replay autopsies,
  gates, scrims, the stress-map suite, and the watching-replays-and-naming-
  failures loop that feeds everyone.
- **Module rule that makes it work**: a module never takes a turn, it
  proposes; the chassis arbiter decides. Every regression we ever shipped
  came from breaking that rule.

## LIKELY QUESTIONS, SHORT ANSWERS

- "Why did your bot build a sentinel at turn 1 here?" → On small maps the
  opening titanium (500) covers it, and a core-aligned sentinel is the
  fastest race-winner. On big maps it lands eco-backed around t50 — same
  code, distance decides the timing.
- "Why barriers next to the ENEMY core?" → Heal denial (entomb). Barriers
  are owner-passable only; their healers lose standing squares.
- "Your bot ignores a lone gunner harassing — intentional?" → Yes, measured:
  chasing lone harassers cost us 4 of 5 builders on drumlin. Packs of 2+
  trigger defense; singles are the chassis turret-response's job.
- "What would you do with two more weeks?" → The economy war: harvester
  count decides tiebreaks (we've seen 21-vs-4), plus a bounced-siege
  detector so we stop reinforcing sieges that walls have already blanked.
- "Biggest surprise?" → SENTINEL_AMMO_COST=10: shooting our 3-Ti barrier
  costs the shooter 20 Ti. Half our defense is really economic warfare.
