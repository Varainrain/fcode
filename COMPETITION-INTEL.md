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
