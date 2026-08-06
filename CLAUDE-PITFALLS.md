# CLAUDE-PITFALLS.md — every AI-code failure class we have MEASURED, with receipts
(oni's ask 2026-08-05: "consolidate the common errors... i can incorporate it into a claude.md".
Every entry below cost us a real gate or a real match. Paste into any bot-writing session.)

## A. Silent-failure API traps (no crash, no log — the unit just does nothing)
1. **`store[0]` off-by-one**: the core increments BEFORE the new builder runs; the "first"
   builder reads 1, not 0. mech-v1's idx-0 role NEVER RAN all season.
2. **Spawn-index race**: a builder born t0 first reads at t1, after the core may have bumped
   the counter again. Roles from `read_store(0)` land on the wrong bot. Claim via a FREE
   store slot instead (8-15 are free in most of our bots).
3. **Building on your own tile silently fails** (2.3+). Require manhattan == 1 exactly;
   a bot standing ON its target loops forever.
4. **`can_fire_from(spot, f, SENTINEL, far_target)` is always False past range** — gating a
   BUILD on "can I hit their core from here" means the building is never placed. Check
   range before asking, or face the target without asking.
5. **Non-builder entities have no map** (launcher/gunner/sentinel Player instances never run
   setupMap): `mapPf.enemyCorePos` is permanently None there. Publish positions via store.
6. **Uncaught exception = PERMANENT unit death** (dev26+). One bad tile query kills the unit
   forever. Crash-armor `run()` — OogwayNEW shipped without it.

## B. Latch/one-shot logic bugs (decide-at-the-wrong-time)
7. **Deciding before the trigger round**: `if x is None: x=False` on first turn + `if round>=N:
   claim` = every unit born before N latches False forever; only units born later can claim.
   Cost the lastpop clone every attack gunner. DECIDE AT THE TRIGGER, never before.
8. **Ban/cooldown decrement in an else-branch** that an emergency path skips → the ban
   latches on forever and the unit never acts again (fe-def attackBan, 26% gate).
9. **One-shot flags set on CLAIM instead of COMPLETION**: v6-launcher set rode=True on
   claiming a ride; claim races meant losers self-disqualified. Set flags on the OUTCOME
   (landing detected), not the attempt.

## C. Scope errors (right idea, wrong radius — the #1 regression source)
10. **Every-unit-responds**: emergency defense that let all builders react = economy collapse
    (26%/18%). Sporks-style: ONE claimant per job per round via store slot.
11. **Unscoped cheap actions**: letting every gunner rotate at the 20-Ti floor toward any
    sentinel = map-wide bank bleed (17%). Scoped to sentinels within 7 of OUR core = free
    and correct. Same idea, wrong radius, catastrophe.
12. **All-or-nothing modes**: all-heal lock (42%) vs split-duty heal (one healer/round, rest
    fight) — balance beats override.
13. **Self-entombment**: impassable buildings (conveyors! gunners!) sealing our own core
    pocket — all 14 builders parked 450 turns, lost without the enemy touching our core.
    Placement filters must preserve >=3 open exits (own barriers are passable = open).

## D. Process laws (verified repeatedly — treat as physics)
14. **Outsider transplants fail: 26/26.** A mechanism gated on one chassis breaks on another;
    only the chassis author can integrate. Diagnose from outside, integrate from inside.
15. **Small samples lie**: 84-game gates swing ±10; byte-identical bots read 67-33 in an
    arena. 168 games (4 seeds) minimum for close calls; kill-diff as cross-check.
16. **The mirror lies about meta switches**: v38 lost its own mirror 36% and beat the field
    (Pantheon 4-1). For meta changes the referee is scrims vs the teams above us.
17. **Carry-forward on chassis swaps**: v36 shipped without the seal; OogwayPlus shipped
    without all five defense fixes and went 3W-7L. A new chassis must carry (or re-gate the
    absence of) every currently-shipped fix: cornerShields+triage, split-duty healer,
    _wouldEntomb, sentinel rotation floor. They live in bots/v44 with gate receipts.
18. **Engine patches void all numbers**: after every update, `fcode maps sync` + re-gate.
    2.3.4 turned the best bot in the repo (t25 rush) into an 11% bot overnight.
19. **One change per gate.** Every bundle we shipped (3-fix bundle 17%, my 2 merge attempts
    10%) died unattributable. Isolate, gate, then stack.
20. **Watch replays before writing code.** Every top-4 matchup we flipped started with a
    human eyeballing a loss (diagonal sentinels, parked builders, the 1-tile-off gunner) —
    autopsy scripts quantified it, ONE scoped fix shipped it. Code-first guessing went
    0-for-23 before this pipeline existed.
