# lastpopperian_ diagnosis — it's a winner-take-all RACE, not a defence problem
oni, 2026-07-28. Evidence: 3 consecutive rated series (all 3-2 losses) + 3 replays read frame-by-frame.

## TL;DR
**In every game examined, the LOSER dealt exactly ZERO core damage.** Whoever lands
a gunner within range of the enemy core first wins outright. That is why every
series is 3-2 — it's a coin-flip race resolved per-map, not a blitz we're failing
to survive.

**When we lose, it is because our gunners are built in the wrong place — not
because we build too few.** On atoll we out-built them 14 gunners to 10 and still
dealt zero damage.

## The evidence
| game | map | first core hit | winner | loser's core damage |
|---|---|---|---|---|
| fjord (WIN) | 20x20 | **r47** our gunner (2,12) -> their core (2,15) | us | **0** |
| atoll (LOSS) | 18x18 | r45 their gunner (12,4) -> our core (14,2) | them | **0** |
| bridge (LOSS) | 21x8 | r93 their gunner (19,4) -> our core (19,6) | them | **0** |

Gunner/damage counts (50 damage events = 500hp = a dead core):
| game | our gunners | our core dmg | their gunners | their core dmg |
|---|---|---|---|---|
| atoll (LOSS) | **14** | **0** | 10 | 50 |
| bridge (LOSS) | 1 | **0** | 9 | 50 |
| fjord (WIN) | — | 50 | — | **0** |

## Why we lose the race: we brawl, they snipe
**atoll is the smoking gun.** Our 14 gunners went to (10,8), (8,12), (7,5), (5,8),
(10,13) — every one of them **6-8 tiles from their core at (2,14)**, when gunner
range is r^2=13 (~3.6 tiles). Not one could ever threaten the core. Meanwhile they
placed **one gunner at (12,4) on r44** and a second at (13,5), both at range 2-3 of
our core at (14,2), and killed us by r63.

This is architectural, and it matches the known description of the chassis: the
attack state "plants a gunner adjacent to self facing any enemy within ~6 tiles" —
a **brawler**. It fights whatever infrastructure it bumps into mid-map. Theirs is a
**core-sniper**. Over a 60-100 round game, sniping the core wins; chipping
conveyors does not.

The `finisher` march at the mirrored enemy core already exists but only fires when
rich **AND idle** — the brawler reflex preempts it, so it rarely runs.

## Second-order cost: the aggression starves the passive wall
`passiveWall` only builds when a builder happens to stand ortho-adjacent to a ring
tile **with a spare action**. With the crew out brawling mid-map, the home zone
empties and the ring never forms — the same mechanism as the documented skerry
autopsy ("the passive wall needs foot traffic").
Concretely on atoll: the ray from their gunner at (12,4) to our core corner (14,2)
passes through **(13,3)** — a distance-1 ring tile that would have absorbed it with
a 20hp conveyor. We never built it.

## This kills two hypotheses
1. **Builder adjacent-fire (frozen-erebus-v2) was aimed at a threat that does not
   exist.** Their gunners sit at **range 2-3, never orthogonally adjacent**, and
   `fire()` requires ortho-adjacency. It could never have worked — that, not just
   the 2dmg-vs-40hp arithmetic, is why it measured 2-13 on the ladder.
2. **"We need more defence" is not clearly right either.** We lose games in which we
   out-build them militarily. The waste is in **placement**, not quantity.

## Ranked suggestions
1. **Make the attack state core-seeking, not nearest-enemy-seeking** (highest
   leverage). Weight enemy-core proximity far above generic enemy entities, or let
   the finisher march fire when rich regardless of idle. On atoll this redirects 14
   already-paid-for gunners from useless tiles onto the only target that ends games.
2. **Only count a gunner placement as "attack" if it can actually reach the target**
   — require the planned tile to be within r^2<=13 of something that matters.
   Placing at 6-8 tiles is pure waste.
3. **Map ledger — spend effort here first:** repeat losses are **jackpot 0-3**
   (t232/t269/t595) and **atoll 0-2** (t83/t63). Repeat wins: fjord, skerry,
   showdown, sprint, twins, string. bridge/longship/crossfire lost once each.
4. If defence is revisited, the ring must cover the **distance 2-3 diagonal approach
   tiles**, since that is exactly where their gunners sit.

## Caveats
3 series / 3 replays is a small sample. "Loser deals zero core damage" is 3/3 but
n=3. The map ledger is 1-3 games per map. Worth re-checking against more replays
before treating the per-map splits as settled.

## Reproduce
```
fcode match info <match-id>                      # per-game map/turn/winner
fcode match replay <match-id> --game N           # download
python scripts/replay_timeline.py <file>.replay26   # builds + core damage timeline
```
