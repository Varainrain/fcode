# 🏁 SPRINT-DAY TOURNAMENT: p57 "barrier routing fix" IS THE BOT — ACTIVE (2026-08-08)
Full bracket, every live candidate vs the then-active p58, league pool:

| candidate | vs p58 (n=60) | verdict |
|---|---|---|
| **p57 barrier-routing-fix (Oogway)** | 53% → **53% at n=300 (158/300, kills 132-124)** | **CHAMPION, ACTIVE** |
| p55 covered-tiles (Oogway) | 43% | out |
| v55 ore-fix line (ours) | 42% | out — Oogway's overnight line lapped ours |
| v51 | 35% | out |
| v42-stack | 12% | museum piece |
(p56 skipped — Oogway self-marked WORSE. That self-audit is the culture working.)

Field validation: **p57/p58 beat Pivot 3-2** (they 0-5'd us 48h ago) and both lose 1-4
to sporks — identical, so p57's mirror edge is free. **Board: sporks #1 2114 pulled
away, Pantheon #2 2031 resurging, Lorem Ipsum #3 from nowhere. We are #7 of 111.**
SPORKS IS THE FRONTIER: t154-278 kills, they beat everything we field. Their scrim
replays: prod/5fbb384e* + 7f6e12c5*. Next real work after the sprint = sporks autopsy
+ the two structural moves already specced (crew-size sweep, sentinel-weighted attack,
Coreflood-style cost-law optimization).# ✅ 300-GAME AUDIT VERDICTS (2026-08-07 evening)
| disputed fix | my n=60 claim | Oogway's n=300 | MY n=300 (league pool, both sides, 10 seeds) |
|---|---|---|---|
| v54 bootstrap-first heals | 53% | 44% | **52% (155/300, kills 140-136) — FREE** |
| v55 ore tie-breaking | 52% | — | **50% (149/300, kills 135-135) — FREE** |
Neither reproduces Oogway's 44% on the league pool; possibly a harness/pool/port
difference — worth 10 min on the VC comparing setups (if he ported the fix into HIS
chassis for testing, that's the 27th transplant datapoint, not a gate of my ship).
Bottom line at proper power: **both fixes are mirror-FREE, neither is a mirror GAIN.**
They ship on their specific-class receipts (t1000 tiebreak wins vs Jython #2, heart
starvation map 3/4, jackpot t458 grind) — which mirrors structurally under-weight.
His sentinel-fix 35.7%/300 stands unchallenged (I never re-gated it; if it's my
rotation floor ported into his line, same transplant caveat applies — the fix's home
gate was 49% in ITS chassis). Standing rule reaffirmed either way: **nothing ships on
n=60 again — screens screen, 300 decides.**
# 🧾 OOGWAY'S AUDIT — RESPONSE (2026-08-07 afternoon). He's right on the code, maybe right on the gates.
1. **Scorer critique: CORRECT.** `bestScore = -1`, so far ore scoring 0 still passed
   `0 > -1` — "mathematically invisible" was WRONG, retracted. The real defects the fix
   touches: (a) all far tiles TIE at 0, so the winner was the first tile in scan order —
   an arbitrary far-left bias, often unreachable-in-time targets; (b) the
   `resources > dist/7` gate inside the same branch couples poverty to range (poor ->
   no far ore -> poor). v55's `max(1,...)` works by breaking ties toward the BUILDER'S
   proximity, not by "restoring visibility". Doc corrected. Whether it's worth points
   is his 300-game question -> re-gating now.
2. **His 300-game audits: sentinel fix 35.7%, v54 heals 44%.** My recent ships were
   gated at n=60 (CI ±13) under time pressure — underpowered by MY OWN 168-game rule.
   **300-game re-gates of v54-vs-v51 and v55-vs-v54 are RUNNING.** Anything that fails
   at n=300 gets pulled from the line, no attachment. This is the pipeline working:
   module owner ships, orchestrator audits, loser is the noise not the person.
3. **Tooling alert #2 RETRACTED** — damage events are fine; my ad-hoc script forgot to
   seed cores from the map header. replay_stats.py main was always correct.

# 🏭 COREFLOOD SPEC (0-5 x2 explained): THE FIRST COST-LAW-OPTIMIZED TEAM
Corrected autopsy, all 5 games: **b8-12 crews (ours: capped at 5), cv54-78 conveyor
econ (income is UNTAXED by the cost law), sentinel-weighted offense s1-3 with FEW
gunners (dodging the +20%/gunner scaling we pay on every gun), zero launcher tricks.**
Our signature in every loss: healed >> dealt (g1: healed 1009, dealt 147) = permanent
triage funded by a starved econ against their grind. The structural gaps, by lane:
- ECO (Oogway): the b5 builder cap — they run 8-12 working bodies. Cost law taxes
  gunners by unit count (+20% each), so extra BUILDERS cost gun-price too — but their
  math clearly nets positive. Needs a gated crew-size sweep (6/8/10).
- ATTACK (oni): gunner-weighted offense pays the scaling tax Coreflood dodges;
  sentinel-weighted is the cost-law answer (they prove it works at 1764->beating us).
- The heal-war is downstream of both: they win it on income, not on heal logic.
# 📅 2026-08-07 midday: JYTHON 4-1, ORE BLINDNESS FIXED, COREFLOOD IS THE OPEN PROBLEM
## Jython scrim (c2da0e10): WE WIN 4-1 — and they are Pareto-ion renamed (Cambridge silver)
Their current archetype: **BARRIER FORTRESS** — bar8-36/game (g4: 36!), g22-28 gunners,
near-zero econ (h0-5). In 3 of our 4 wins they dealt ZERO core damage; we won two
t1000 tiebreaks on economy (the poverty-trap fix earning its keep at #2 level).
## ORE BLINDNESS FIXED (v55, ACTIVE): the harvest scorer zeroed all ore beyond dist^2
160 from our core (`max(0,160-dist)`) — far ore mathematically invisible forever
(heart: 3 harvesters in 409t vs Coreflood's 10+). Now a penalty, never a cutoff.
Mirror 52% kills 28-26; heart flips 3/4. ic3d's "doesn't pathfind titanium" = exact.
## COREFLOOD (0-5 TWICE, incl. post-fix): the open problem
Their profile: **big-econ machine** — b8-12, cv54-78, h3-14, s1-3, L1-2 (launchers!).
Against them specifically our eco still collapses (h0-4, g1: LITERALLY ZERO eco builds
on fjordgate). Something they DO suppresses our economy — likely early harass on eco
builders (needs autopsy with fixed parser). Fresh replays: prod/d8375ef2*.
## ⚠ TOOLING ALERT #2: damage events ALSO unreadable in fresh replays (both sides read
0 dealt/healed in games that ended Core Destroyed) — same nesting-change family as the
move events. replay_stats damage branch needs the same both-formats fix. DO NOT trust
any dealt/healed numbers from replays downloaded after ~14:00 today until fixed.
# 🌅 MORNING SPEC: THE team-lazy GAP IS THROUGHPUT, NOT TEMPO (2026-08-07, fixed-parser numbers)
Five-game spec table vs the team that beats everyone (their L/W vs us):

| game | side | h@t30 | first gun | first hit | total builds | CORE DMG DEALT | healed |
|---|---|---|---|---|---|---|---|
| atoll | LAZY / us | 4 / 4 | t15 / t23 | t27 / t28 | 34 / 26 | **1960 / 420** | 48 / 1456 |
| jackpot (our W) | LAZY / us | 2 / 3 | t21 / t21 | t27 / t26 | 22 / 24 | 3024 / 2156 | 1656 / 3017 |
| hive | LAZY / us | 3 / 2 | t33 / t29 | t35 / t30 | 38 / 30 | 784 / 651 | 188 / 280 |
| heart | LAZY / us | 2 / 1 | t11 / t9 | t12 / t10 | 24 / 15 | 798 / 714 | 552 / 296 |
| antler | LAZY / us | 3 / 2 | t8 / t3 | t6 / t4 | **33 / 13** | **1477 / 609** | 516 / 975 |

**MYTH KILLED: we MATCH their opening tempo** (first guns/hits nearly simultaneous, econ
identical at t30). The gap: (1) **damage throughput — they out-deal us 2-5x** (atoll
1960 v 420!) with similar or equal build counts: their turret-seats LAND on our core,
ours mostly do not (oni's guns-on-core metric, now quantified per-game); (2) **mid-game
build flow — they keep producing t30+** (antler 33 builds to our 13) while we stall and
convert titanium into heals instead (atoll: we healed 1456 while dealing 420 — healing
is the losing side's activity when damage isn't landing).
LANES: attack (oni) = seats that actually reach the core + sustained production past
t30; eco (Oogway) = fund the flow. Defense is NOT the gap anymore in any game measured.
Board note: sporks ran away (#1, 2023); **Jython = Cambridge silver authors ('something
else': osteo/Jython/Coderz75) surfaced at #2** — their postmortem is the one whose
Turret Takedown / VisionTracker ideas we mined. Coreflood 0-5'd us twice = scout-worthy.
# 💊 POVERTY TRAP FIXED OURSELVES — v54 ACTIVE (2026-08-07 09:40)
Three gated shapes to find the notch (each one dial-turn, never bundled):
| shape | gate vs v51 |
|---|---|
| flat Ti floor (no heals < 30 Ti unless critical) | 35% — always-healers win mirror races |
| income gate (no heals until 2 harvesters ever) | 43% — right idea, covers too much race window |
| **bounded: round<=30 AND harvesters<2 AND core>150** | **53%, kills 27-27 — FREE. Shipped.** |
The lesson generalizes: emergency-response policies need BOTH a resource condition and
a TIME BOUND — unbounded versions of correct ideas lose races (same family as the
attackBan latch and the all-heal lock).
Scrim vs team lazy: 1-4 (was 0-5). Our one win = jackpot t458 grind, exactly the game
the fix targets. Their other kills t102-132: **team lazy is now the apex — lean-fast
(oni called it: 'lazy runs everything lean'), winning races before bootstrap matters.
That is attack-tempo + lean-footprint turf (oni + Oogway lanes).** Their 5 fresh
replays: prod/0604725d*. v54 active (strongest family + free fix).
# 🔬 THE team-lazy 5-0, CORRECTLY DIAGNOSED + A TOOLING ALERT (2026-08-07 08:30)
## ⚠ TOOLING FIRST: 2.3.6 changed the REPLAY WIRE FORMAT for move events
Moves are now fully nested ({id,{x,y}} inside field 2; the id left the top level).
Every move-count from our parsers since the 2.3.6 update was silently ZERO —
my "all builders frozen, 0 moves" reads were artifacts. replay_stats.py is fixed
(handles both formats) and pushed. @oni check builder_trace.py for the same break.
HUMAN EYES REMAIN THE GROUND TRUTH — ic3d's "they froze" was still right in
substance: three of five builders went stationary from t18/t39/t60.

## What ACTUALLY happened in 72d9266b (v51 vs team lazy)
Not a movement bug, not a crash: **a POVERTY TRAP.** Both sides rushed (we hit
t10, them t12; we dealt 700, them 840). From t15 to t103 we built NOTHING:
with h1 income (~2.5 Ti/turn), continuous 1-Ti core heals consumed every coin
on arrival — we could never save 20 for a harvester, so income never grew, so
we heal-dripped while they out-threw us on double economy (h2 cv14, healed 536).
ic3d's "we can never reach more than 2 titanium" was the exact mechanism.

## The fix attempt and why it needs the eco lane
v52 = heal-economy-floor (no heals below 30 Ti unless core <200hp): **35% in
mirror** — in mirror RACES the always-healer wins; the trap only kills in long
games vs better economies. The tension is real: heal priority must be a
function of INCOME (harvester count), not just titanium-on-hand. That is an
eco-lane call (Oogway) with oni's burst thesis attached: the alternative frame
is that the fix is not less healing, it is MORE INCOME EARLIER so the floor
never binds. v42 stack stays active meanwhile (stable field record).
# 🔁 v47 SCRIM VERDICT: NEGATIVE — REVERTED TO THE STACK (2026-08-07 00:40)
ic3d's call to test before more rated bleed was right. v47 scrims: O(1) 2-3 AGAIN,
Pivot 1-4. The defense steps are not the cause — the OogwayAttack chassis family is
weaker ON THE FIELD than the old stack despite its 77% mirror (mirror-lies confirmation
#3). Rated evidence: stack held #8 @ ~1800; oogatk family bled to #10 with losses to
1706-tier. **Active reverted to platform v42 (the stack).**

## What the O(1) replays show (fresh, in prod/61684b68*): THE META IS NOW GIGA-HEAL WARS
| game | us dealt/healed | them dealt/healed | result |
|---|---|---|---|
| g3 hive (1000t) | 3010 / 2726 | 3006 / **3010** | they win tiebreak |
| g1 lighthouse | 490 / 826 | **1327** / 490 | they kill through |
| g2 atoll (W) | **1708** / 7 | 7 / 1206 | we kill through |
Cores now absorb 3-6x their HP per game via healing. Games are decided by
(damage throughput) vs (heal economy) — pure econ war, exactly oni's titanium-bound
thesis and Oogway's eco lane. The winner is whoever funds more heals AND lands
overwhelming burst. Note our heal numbers finally work (claim pattern: 826/2726
healed) — the defense lane's job is done; the game is now won upstream in econ.
NEXT (eco lane): O(1) runs b6/h4-8 lean-and-heal; our g5 dealt 14 damage all game —
attack throughput on THIS chassis line needs oni's burst thesis + Oogway's lean econ.
# 🧩 THE MODULES BOT v1 IS LIVE (2026-08-06 23:50) — defense integrated INTO OogwayAttack, one advisor at a time
Answer to "cant we integrate it?": yes — done, with the one-at-a-time discipline the 26
failures demanded. ACTIVE as v47 = OogwayAttack + defense steps 1-2:
| step | advisor | gate (15-map pool, read vs oni's mirror-null band) | verdict |
|---|---|---|---|
| 1 | would_entomb placement veto | 45% (rare-event veto; Besvik 4-1 receipt) | KEEP |
| 2 | claim_heal_duty (slot 14) | 48%, kills 22-22 (Oops 4-1 receipt) | KEEP |
| 3 | 12-tile sentinel seal | **42% REJECT** | retired |
| 3b | 4-tile diagonal seal | **40% REJECT** | retired |
| 4 | rotation floor | not attempted — one line, left for Oogway (documented in advisor) |
Scrims: naked chassis 3-2 Pantheon, od2 2-3 Pantheon — inside 5-game noise; the mirror
says both steps are free and the receipts say they kill catastrophic loss modes.

**THE BIG 2.3.6 FINDING: SHIELDS ARE DEAD, and oni's cost law says why.** Every building
adds +1% to every gunner purchase — the 12-barrier seal that gated FREE on 2.3.4 now
taxes our own guns +12% and gated 42%. Even 4 barriers gated 40% on this lean chassis.
**A fix that was measured-free last week is measured-harmful this week. Also note what
this implies for ONI's lane: conveyor count taxes guns the same way — his "leaner
footprint buys guns" hypothesis is now double-supported. And Oogway's chassis being
building-lean is WHY it wins generations.**
Chassis note for the ordering bug family: OogwayAttack's fight-block-returns-before-heal
was the 3rd recurrence of heal-unreachable-during-siege. The claim pattern is the cure;
it is now in the live bot.
# 🚂 OOGWAYATTACK SHIPPED VIA THE PIPELINE — ACTIVE as v46 (2026-08-06 22:30)
First full run of the MODULES.md pipeline on a submission:
1. **Gate vs active stack**: 77% (kills 92-22); on league-pool maps only ~83%. Another
   Oogway generation jump — even WITHOUT the defense module.
2. **Scrim**: Pantheon 3-2 (won antler t233, heart t95, atoll t70; lost fjordgate t485,
   lighthouse t163).
3. Activated. Old active (v42 stack) retired after 2.3.6 + the map rotation voided its
   local numbers anyway.
HYGIENE (oni's find, now applied here too): the league pool is 15 maps — antler,
archipelago, atoll, drumlin, eider, fjordgate, heart, hive, jackpot, lighthouse,
meander, moonrise, nordkap, saga, snowflake. 18 stale maps parked in maps_stale_236/.
ANY number gated before 2026-08-06 on the old pool is void.
**THE MODULES BOT IS STILL NOT DONE**: OogwayAttack contains zero defense-advisor calls
(modules/defense_advisor.py waits with its 4 receipts + integration doc), and oni's
attack_advisor/ATTACK-INTEGRATION.md are not on main yet. Integration targets from the
scrim: fjordgate + lighthouse (both losses = home-defense shaped). Also noting gently:
attack is oni's lane per the role split three hours before OogwayAttack landed —
orchestrator and lane owner should sync so work doesn't collide.
# ⚖️ THE pv43 PARADOX + REVERT (2026-08-06 07:40) — @Oogway read this one
Oogway's new OogwayPlus (platform v43) is a GENUINELY STRONGER CHASSIS: it beats our
full fix-stack line 76%/73% head-to-head (kills 58-19!). And it went **3W-7L rated**
(SmartFridge 0-5/1-4/2-3, Pivot 1-4, Coreflood, Flotte — though it beat Pantheon AND
Besvikomat 3-2). It shipped with NONE of the five gated defense fixes. Field > mirror
(proven twice this week), so ladder record decides: **reverted active to platform v42
(anti-entombment stack, #8 at ~1797)** until the stack lives inside the new chassis.
**I TRIED THE MERGE TWICE AND FAILED TWICE (both 10%, kills ~5-68)** — hooks that worked
on four straight chassis generations break somewhere in the new role structure I can't
see from outside. 26th transplant failure. @Oogway: the winning move is YOU integrating
the five fixes natively into OogwayPlus — each is ~30-60 lines, self-contained, in
bots/v44 with its gate history: (1) cornerShields+triage [Pantheon 4-1], (2) split-duty
healer slot 14 [Oops 4-1], (3) _wouldEntomb placement filter [Besvikomat 4-1],
(4) home-sentinel rotation floor, (5) sentinel-line seal geometry. OogwayPlus + these
five = plausibly the strongest bot in the league; the chassis alone already trades 3-2
with Pantheon.
# ⚰️ THE ENTOMBMENT BUG — found by ic3d's eyes, fixed, Besvikomat 4-1 (2026-08-06 00:10)
ic3d watched 0788a40d g1 and said "all builder bots parked near our core doing nothing."
Movement analysis confirmed 100%: ALL 14 of our builders ended at d2-4 from the core,
moving once or never for 450 turns. Mechanism: our own conveyors (impassable to us) +
defensive gunners at (2,2),(1,3),(3,1),(0,2) sealed every exit from the core pocket —
each new spawn joined the tomb. 2 harvesters all game; Besvikomat won the tiebreak
WITHOUT EVER DAMAGING OUR CORE. oni's landmine 3 at fatal scale.
**Fix (ACTIVE, platform v42 "v44 anti-entombment"): _wouldEntomb() — near the core, never
place an impassable building that leaves <3 open exit tiles (own barriers count as open —
passable). Mirror 52%. Scrim: BESVIKOMAT 4-1** (won vault t74, showdown, aurora, pinch).
**STILL UNSHIPPED — ic3d's #1 request, now 4 attempts deep: sentinel-preferred attack.**
v43 (repeat-seat + gunner cost cap) gated 19% — the re-seat loop stalls attackers, same
family as v31s. The chassis authors need to own this one: the attack state must prefer
sentinels natively, not via my bolt-on seat loop. Data: 25 gunners/2 sentinels in the
Besvik game, 10th gunner costs ~100 Ti under +20% scaling, the wave died by t37.
# 🩹 v42 SPLIT-DUTY HEAL DEFENSE — ACTIVE (2026-08-05 23:30)
ic3d watched 9d28da39 g2 (OopsGotYourElo, rated): one defensive gunner facing west, two
lanes empty, and STILL heal-zero — we dealt 693 to their 504 and lost because they healed
686 off passive income and we healed 0. Root cause was the SECOND heal-blocking gate:
runDefend only reaches healCore when NO uncovered enemy turret is visible — i.e. never
during a siege. (First gate was cornerShields preempting, fixed in v40.)
- v41 all-heal lock: 42% — both defenders nurse a scratch forever while the turret fires.
- **v42 split-duty (ACTIVE): ONE defender claims healer per round via store slot 14, the
  rest keep counter-turret play.** Mirror 46% (jackpot/longship 0/4 — watch those).
- **Scrims: OopsGotYourElo 4-1** — with TWO t1000 tiebreak survivals, the heal wall
  demonstrably functioning on our side — **sporks 2-3** (map variance from v40's 4-1;
  atoll lost at t715).
STILL OPEN (ic3d's other observation): the attack keeps building GUNNERS as fallback
after the first sentinel — sentinel-preferred attack is untested in isolation (the
earlier attempt was tangled in a 17% bundle). One clean gate: replace gunner fallback
with repeat shieldedSentinel while Ti>=80. Also open: more-defensive-gunners knob,
sporks' t1-sentinel showdown book.
# 💉 v40 TRIAGE BEATS SPORKS 4-1 (2026-08-05 21:40, match 020ad085) — ACTIVE
The sporks autopsy (10 games, heal-flow measured) found their edge AND our defect in one pass:
- **Their formula**: 3-4x our harvester economy (h9-14 vs our h0-7) funding a CORE HEAL WALL
  of 400-900hp/game — in cb25c373 g1 we dealt 1197 core damage (2.4 cores) and they healed
  900 of it — plus burst pushes of 5-6 gunners in ~10 turns that out-dps rotation defense.
- **Our defect: core healing was ZERO in 4 of 10 games.** cornerShields preempts the heal
  logic in runDefend; under sustained fire the shields always need work, so the defender
  shields forever while the core dies. Armor on a corpse.
- **The fix (v40): triage — shields yield when core hp < 350.** 11 lines. Mirror 55%.
  **Scrim: SPORKS 4-1** (won jackpot t65, sweden t89, twins t100, runestone t254) after
  two 1-4s. The #2 team's entire edge over us was that they healed and we didn't.
Session arc: watch -> autopsy -> one scoped fix -> scrim the target team. Third time this
loop has flipped a top-4 matchup in a day (Pantheon seal, sentinel switch, now triage).
Still open vs sporks: showdown (their t1-sentinel@d5 opening book on that map).
# 🔧 v39 ACTIVE (rotation fix) + THE SPORKS PROBLEM IS ITS OWN THING (2026-08-05 20:30)
ic3d watched the sporks loss (cb25c373) and called three defects. Measured results:
1. **SHIPPED (v39, active): home-sentinel rotation fix.** A defensive gunner sat one tile
   off the ray of the sentinel killing our core and never rotated - sentinels were not
   counted as core threats, so the rotate floor stayed at 80 Ti. Fix is SCOPED: sentinels
   within 7 of OUR core count as core threats (rotate floor 20). Mirror-free 49%.
   ⚠ The UNSCOPED version was a disaster (every siege gunner map-wide rotating at 20 Ti
   floor = bank bleed): v39b 17%. Scope matters more than the idea.
2. **REJECTED for now: sentinel-instead-of-gunner at their core** - part of the 17% bundle,
   needs clean isolation before retry.
3. **REJECTED as implemented: conveyor chipping** (sporks does it to us) - opportunistic
   adjacent-fire hooks cost 29%: eco builders got stuck plinking 20hp conveyors. If
   retried: TARGETED trunk cuts (one dedicated cutter, chosen tile severing max flow),
   not opportunistic plinks.
4. **UNTESTED: ic3d's "more defensive gunners" knob** - the defend clamp count is a chassis
   parameter, one gate each for 3/4/5 defenders.
**SPORKS (now #2 with only 108 matches): 1-4 again with v39. Their wins are LONG GRINDS
(t149-471) - the absorb archetype played at top level, not a blitz.** Next session: autopsy
their wins from cb25c373 + 88d6aab5 replays (downloaded, in prod/) before touching code.
# ⚔️ v38 THE SENTINEL SWITCH IS LIVE — AND THE MIRROR LIED (2026-08-05 19:30)
ic3d's call: "we're top 8 because we still use gunners." Correct. v38 = v37 + shielded
diagonal sentinel siege (deterministic k=4/3 seats outside gunner reach, then the SAME
builder flanks its sentinel with two barriers — naked sentinels died in v32p; seat-search
stalled in v31s) + ammo buffer 16->60.

**THE METHODOLOGY FINDING, maybe the most important one yet: v38 loses our own mirror 36%
— and beats the actual field.** Scrims as active bot: **PANTHEON 4-1** (won crossfire t63,
the exact map v37 could not take) vs their 0-5 rated sweep of v37 hours earlier;
Pareto-ion 2-3 vs 1-4/1-4. **A mirror gate measures a meta switch against yesterday's
meta.** For meta changes, the referee is scrims against the teams actually above us,
not the parent bot. v38 ACTIVE. Remaining holes: Pareto's fast maps (skerry t77,
longship t87 - the blitz window, still the t25-shields lever).# 🏆 v37 BEATS PANTHEON 4-1 (2026-08-05 07:10, match f07f75b5) — ACTIVE
**v37 = Oogway's v36 (healing, 62% over v34) + the sentinel-line seal (ic3d's observation,
mirror-free 50%).** Scrim progression vs Pantheon: 0-5 -> 1-4 -> 2-3 -> 2-3 -> **4-1**
(won longship t100, fjord t69, showdown t193, sweden t491; lost only crossfire t67).
The formula that did it: **Oogway's chassis + ic3d's observed counter + gates on every step.**
Neither half alone got past 2-3. v36 shipped WITHOUT the seal — always check that a new
chassis carries the measured wins of the old one before it goes active.
Remaining: crossfire t67 (fast-map blitz where the seal isn't up yet — the t25-shields
lever is still unclaimed for whoever wants the 5-0).
# 👁️ EYES BEAT AUTOPSIES: ic3d's observation -> corner shields -> 2-3 vs PANTHEON, TWICE (2026-08-05)

ic3d watched the Pantheon loss manually and saw it: they win with TWO sentinels placed
DIAGONALLY at standoff (range^2 exactly 32) where our five gunners (range^2 13) can never
answer. The observation contained its own counter, and it shipped the same evening:

- **v33 corner shields**: every diagonal sentinel line into a core corner passes through the
  ONE tile diagonally adjacent to that corner. 4 barriers, 12 Ti, all diagonal lines dead.
  Mirror: 51% vs v30 over 168g (kills 75-75) = FREE. First Pantheon scrim: **2-3** (twins WON
  t171, bridge WON t720 absorb war) vs the 0-5 / 1-4 baseline. Their kills rerouted to
  CARDINAL columns (atoll: sentinel at (14,7), our core (14,2), straight down the lane).
- **v34 full seal** (ACTIVE): + 8 cardinal-lane barriers at distance 2 (d1 ring stays free
  for spawns/heals — barriers are passable to own units, so no 29% full-seal trap). 12
  barriers, 36 Ti, every sentinel line into the core blocked. Mirror: 49% = free. Second
  Pantheon scrim: **2-3** again (won crossfire t114, sprint t113).

**Remaining gap: the sub-t50 blitz** (twins t41) — the seal isn't up before their opening
lands. Next lever for the chassis authors: shields up by ~t25 (one defender prioritizes
them over econ in the opening), and the diagonal-corner shield that was missing on fjord.
For the record: copying their START failed twice as the graft law predicts (v31s 10%,
v32p 36%) — the COUNTER transferred, the strategy did not. Eyes on replays found in one
evening what 23 code-first integrations missed. This is the pipeline: ic3d watches, the
lab measures, the chassis authors land it.
# 🚨 WHY WE ARE LOSING + THE 2.3.4 META SHIFT (2026-08-05, 20 fresh loss games parsed)

## The new archetype: SENTINEL SIEGE — Pantheon and Pareto-ion both switched within a DAY of the patch
| team | profile in wins vs us | kills us at |
|---|---|---|
| Pantheon | b3, **s2, L1, bar1-6, g0 (ZERO gunners)** | t46-72 |
| Pareto-ion (1887, climbing) | **s1-5, L1, bar4-18, g0-1** | t65-209 |

Sentinel post-patch: **9 dmg/round (vs nerfed gunner 7), range^2 32 vs 13 (seats ~5.6 tiles out,
OUTSIDE gunner reach), 40hp vs 25, flat 30 Ti with NO +20% scaling.** The gunner is now the
fallback weapon; the sentinel is the siege weapon. **v30 builds zero sentinels.**

## The loss anatomy (Pivot x3, SmartFridge, all 2-3s)
**We hit first in nearly every loss (t8-36), deal 200-784 core damage, and STALL** — their
barriers (Pivot: 5-18/game) + heals absorb nerfed gunner dps (7/round through 30hp barriers),
then their counter kills us t126-449. The absorb-counter pattern we documented in staging is
now the mid-ladder standard, and our finisher can't finish through it.

## Ranked improvements for v30 (for the chassis authors — my integration attempt failed)
1. **Adopt sentinel siege in runAttack** — seats via can_fire_from(spot, f, SENTINEL, coreTile),
   standoff outside gunner range. My first cut (bots/v31s) gated 10% — attackers stalled
   hunting seats (kills 3-68); the SHAPE is: seat search must not preempt fighting, and ammo
   buffer must rise (sentinel drinks 10/shot vs 4). The concept is Pantheon-proven; the
   integration needs the author's hand. This is attempt #23 of outsider-grafts-fail.
2. **Finish through absorb**: our 385-784 damage stalls vs barriers+heals. Sentinel dps (9/rnd,
   and 18 per hit punches 25hp gunners in 2 and 30hp barriers in 2) is also the answer HERE.
3. **Build barriers around our own siege seats** — every team that beats us builds 2-18;
   we build 0. Shield pieces for besiegers, not just harvesters.
# 🎯 2.3.4 STATE OF PLAY: v30 SWEEPS + LAUNCHER TECH RESOLVED (2026-08-05)

## v30 "defend bot change" vs everything, on 2.3.4 (84g each)
| v30 vs | result | kills |
|---|---|---|
| v13 _OogwayRush (was best) | **89%** | 72-9 |
| v9 pls codex | 80% | 64-16 |
| prime-a | 86% | 72-12 |
| oogerebus3 | 86% | 71-11 |

The turret patch (gunner 10->7 dmg, 10->20 Ti, +20%/gunner scaling, 25hp) killed the
t25 rush meta overnight — v13 went from best-ever to 11% in one balance pass.
**v30 is the undisputed best and correctly active. All old numbers are void; regate
everything after every engine patch.**

## Launcher tech: both concepts now measured on the v30 chassis (attempts 14-15)
- **ballista (Pantheon tempo opening, bolt state SOLVED): 29% — REJECT.** The
  mechanism oni's 13 attempts couldn't land now fully works: pad t2 perpendicular
  (landmine 3), self-contained launcher with slot-published target (landmine 1),
  own-stepper march (landmine 2), throws at t4/t7 = Pantheon's cadence, and the
  bolt LATCHED ON LANDING (position jump >2, not on claim — v6's bug). It loses
  anyway: a 6-tile throw is a small slice of a 35-tile journey, the opening
  diverts 20 Ti + two attackers' turns, and 2.3.4 devalued first-gun tempo (the
  thing the throw buys) by nerfing the gun itself.
- **ballista-d (khaos defensive throw — eject enemy builders from our seat zone):
  46%, kills 34-38 — NEUTRAL.** Free but unpaid in the mirror; the pad rarely
  catches a sieger in pickup range. Not shippable by the only-what-gates rule.
**The launcher question is now CLOSED with data on both concepts (15 total
attempts). The working modules live in bots/ballista{,-d} — pad placement, throw
selection, bolt march are all functional and reusable if a future patch or a
Pantheon-style big-map logistics design makes them pay.**
# 👑 OUR BEST BOT IS v9 "pls codex" — AND IT IS NOT CLOSE (2026-08-03)
Downloaded oni's deployed v9 from prod (`fcode submission download 9`) and gated it
against our entire local line, 84 games each on dev29 + synced pool:

| v9 vs | result | kills |
|---|---|---|
| prime-a (our best-ever local: OogwayNEW+armor) | **93%** | **78-2** |
| lastpop2 (siege clone) | **98%** | 82-1 |
| oogerebus3 (anti-siege specialist) | **82%** | 67-6 |

**Every bot in the repo is obsolete as a baseline.** The week of local work
(OogwayNEW line, oogerebus line, all 21 experiments) played in a different league
than what oni's codex pipeline produced. New rule: ALL future gates run against v9.
(v9's own weak maps, from the per-map splits: string 1/4 vs prime-a, sweden 0/4 and
vase 1/4 vs oogerebus3 — narrow-map wall metas. Worth telling oni's pipeline.)

## But v9 has one measured hole against the TOP-4 (from 15 prod games)
0-5 Pantheon, 1-4 CtrlAltDefeat, 0-5 Orizon: **in 13 of 15 games v9 dealt ZERO
core damage.** Two distinct failure modes:
1. **Race losses on fast maps** — Orizon/CAD hit t14-42 with 4-15 lean guns and kill
   t51-116 before v9's siege lands. (Orizon = pure rush: b4, kills t51-83.)
2. **Long-game non-conversion** — CAD g2 (267t), Pantheon bridge (270t) and
   runestone (306t): hundreds of turns, v9 never touches their core. On runestone
   v9 built 169 guns for zero core damage.
The one prod win pattern: atoll t949 grind (unit-cap econ absorb). erebus shelf
now holds v10=prime-a, v11=oogerebus3 as inactive options; **v9 stays active.**
⚠ `fcode submission upload` AUTO-ACTIVATES — always `submission activate 9` after
shelving anything (this bit me for ~2 minutes of ladder time today).

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
