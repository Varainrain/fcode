# frozen-erebus-v1

**A frozen, verified snapshot of `oogerebus` — the strongest bot the team has.**
Not a new build. Frozen on 2026-07-26 so gates have a stable baseline that
does not drift while people keep editing `oogerebus`.

## Verified record (engine 2.3.0.dev26, --tle 10, 21-map pool, both sides)

| opponent   | result | source            |
|------------|--------|-------------------|
| OogwayWIP  | 61%    | 84-game gate      |
| krb        | 62%    | 84-game gate      |
| oogerebus3 | 67%    | arena, 16-8       |
| kfort      | 75%    | arena, 18-6       |

It is the only bot with a winning record against **every** other bot we have.

## What it is

Oogway's hand-written brawler (point-blank counter-gunnery, native 8-way
facing, self-aiming turrets, protected low-id econ crew) plus the team's
armor:

- **core-facing conveyor wall** — denial tiles that double as delivery
  infrastructure (barriers there strangled our own trunk lines; a
  *dead-end* wall conveyor swallows whole harvest chains)
- **passive walling** — a spare-action side effect, never a state (as a
  state it starved the economy: 32%/46% gates)
- **finisher march** — when rich, late and idle, march the mirrored enemy
  core instead of corner-exploring
- **dev26 crash armor** — an uncaught exception permanently destroys a
  unit, so `run()` catches everything
- heal/flee fix, per-turn `print()` removed, vision guards on tile queries

## Attempts to beat it that FAILED (do not redo these)

| attempt | result |
|---|---|
| home guard, builder home till t60 | 45% |
| home guard till t30 | 43% over 168 games (54% at 84 was noise) |
| ammo buffer 20 → 40/60 when rich | 54% mirror but 52% vs krb (62% baseline) |
| sentinel artillery vs static targets | 54% / 56% — Ti+ammo cost outweighs outranging |
| spawn-order role gates (id symmetry) | near-no-op; `get_id()>4` is symmetric by luck |

**Known hole:** wave/rush bots on maps that empty the home zone (skerry,
vault). `oogerebus3` counters those hard (85-100% vs krb) at the price of
44% in this mirror — field it when the opponent is a known rusher.

## v2 (fire-only reactive defense)
frozen-erebus-v1 + ONE change: builders within manhattan 10 of our core that
are orthogonally adjacent to an enemy turret now `fire()` it (2.3 capability
the pre-patch code never used — v1 loitered next to the gun killing our core).
Local A/B on 2.3 (10 maps x 3 seeds vs krb): v1 38-22, v2 39-21 = no
regression. Convergence/home-guard variant REJECTED (22-38, the documented
43-45% home-guard trap). Motivation: lastpopperian rush cores v1 ~r94 with a
doorstep gunner cluster while our builders stand adjacent doing nothing.
NEEDS an unrated series vs lastpopperian to confirm the real target — krb is
not a valid rush proxy (v1 already beats krb 63%).
