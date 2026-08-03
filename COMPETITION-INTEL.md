# ⚔️ PANTHEON AUTOPSY — fresh 0-5, challenged them directly (2026-08-03)

## HOW TO SCOUT ON PROD (method matters — replays EXPIRE in hours)
The dev CLI hardcodes staging; override with `FCODE_API_URL=https://game.code.florent.vc`
(then `fcode login` once). **Replays can only be downloaded for OUR matches and only
while fresh** — yesterday's are already gone. So the pipeline is:
`fcode match unrated <team-uuid>` → poll `match info` → `match replay` IMMEDIATELY.
One unrated challenge = 5 games of any team's CURRENT bot. They already see our bot
in every public match, so it costs nothing. Pantheon uuid: 3a7b78b8-5d79-4e55-94a3-7732fcaa4105.

## What their bot is (f876f538, 0-5, all cores destroyed)
| map | turns | their profile | 1st gun | 1st core hit (them vs us) |
|---|---|---|---|---|
| sprint | 41 | b5 g8, nothing else | **t5** | **t6** vs t13 |
| showdown | 107 | b5 g16 bar6 | t7 | t8 vs t14 |
| twins | 139 | b7 g10 **L3** bar3 | t95 | t125 vs NEVER |
| bridge | 270 | b11 g24 **L3** bar6 | t53 | t190 vs NEVER |
| runestone | 306 | b6 g32 **L6** bar2 | t43 | t280 vs NEVER |

1. **FULL-SPECTRUM TEMPO.** Hyper-rush on small maps (first gun t5, core hit t6 —
   faster than khaos's fabled t29), patient t190-280 grinds on big ones. They pick
   the tempo per map; nobody else does both.
2. **LAUNCHERS — 3-6 per game on every big map. No other team builds ANY.** This is
   Pantheon's Cambridge launcher tech alive in fcode: mobility/tempo through the
   unit our own engine-facts memo called "completely untapped" (friendly launch
   works, ~2.5x walking speed; enemy-throw removes attackers from sieges).
3. **Barriers (2-6/game)** — the absorb element, same as the other top teams.
4. **In 3 of 5 games we dealt ZERO core damage.** On runestone our deployed bot
   built **169 gunners and never hit their core once** — the exact placement
   pathology oni diagnosed (atoll: 14 useless guns) is still in the live bot, at
   10x scale. The core-seeking fix is not optional.

## Read on the field (real ladder, 92 teams)
Pantheon 1962 #1 (beat #2 CtrlAltDefeat 4-1 unrated); CtrlAltDefeat 1812; Orizon
1736 (4-1'd us rated). We are #14 ~1590. Staging teams (Besvikomat, Ouroboros,
lastpopperian_) are mid-table HERE — the staging meta was a small pond. The teams
above us that we have never scouted: CtrlAltDefeat, Orizon, team lazy, Flotte,
SmartFridge, Askar City, OopsGotYourElo — the challenge pipeline above works on
every one of them.

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
