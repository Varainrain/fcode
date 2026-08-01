# exp_heal_lock_retreat

Parent: `bots/generalist-v3` (the live bot). One hypothesis, one mechanism.

## Evidence that motivated it

200 live ladder games, 2026-08-01, bot v1 (team Oogway, rank #1/86, 62%
overall). Win rate against the top four teams by game length:

| turns | win rate |
|---|---|
| <150 | 27/40 (68%) |
| **150-299** | **10/34 (29%)** |
| 300-899 | 12/21 (57%) |
| 900+ cap | 26/45 (58%) |

Controlled for opponent it survives — OopsGotYourElo alone (n=95): 64% / **40%**
/ 60% / 64%. The 24 losses in that window span 4 opponents, 10 maps, and seats
12/12; 23 of 24 are `core_destroyed`. From 85 replays of those matches:

| group | dmg to our core | dmg to enemy core | our gunners | fully healed |
|---|---|---|---|---|
| WIN <150 | 93 | 633 | 13 | 0/17 |
| **LOSS 150-299** | **722** | **268** | **30** | **12/23** |
| WIN 150+ | 537 | 1446 | 122 | 8/20 |

In the failure window we field MORE gunners than the enemy and convert a third
of the damage, because half those games are fully healed — while our own core
takes 722. The only long games we win take 122 gunners: the sole answer the
parent has to a healed core is to overwhelm it.

## The mechanism

`_observe_enemy_core_heal` watches the visible enemy core's HP and publishes a
net-recovery count to store slot 12 (previously unused). A core that keeps
regaining HP counts up; a core that is losing HP counts back down, so a siege
that starts converting again releases the unit.

When the count reaches `HEAL_LOCK_TRIGGER` (2) **and** home is genuinely
threatened, the role-2 sieger — the one that already gives up its seat to
counter a defender — runs `_run_home_defense` instead of the siege. Role 1
never stops sieging, so pressure on the enemy core is never fully abandoned,
and an unthreatened home cannot pull anyone off the core.

No map name, dimension, side, opponent identity, or turn number is read. Both
conditions are observable state and both release the unit when they clear.

## Verification

- `tests/test_heal_lock_retreat.py` — 9 deterministic tests: store round-trip,
  first observation cannot trigger, one heal tick cannot trigger, sustained
  recovery does, a converting siege releases, evidence bounded both ways, slot
  12 collision-free, and a diff assertion that no parent line was deleted.
- Activation proven by replay, not assumed: the instrumented twin
  `bots/exp_heal_lock_retreat_trace` logged **1,696 real retreats over 168
  games** (median round 466, 404 of them inside the 150-300 target window), and
  3,682 lock events of which the home-threat gate filtered 54%.
- The FIRST trace run was discarded: the instrumentation had been inserted into
  the parent's pre-existing home-defender block, so its 23,203 "retreats" were
  ordinary parent behaviour. Check where a trace landed before believing it.

## Known weakness

Evidence pins at `HEAL_LOCK_MAX` (15) in ~1,900 observations, and the release
path needs the enemy core in vision — which the retreating unit no longer has.
Release therefore depends on role 1 still observing. A time-bounded retreat
would be the next iteration if the mechanism is worth keeping.

## Result

See the gate line recorded in `MEASUREMENT-FINDINGS.md`. Local gates cannot
show a gain for this class of change — no local opponent reproduces the
150-300 collapse — so the gate is a regression guard and the ladder is the
only place the hypothesis can actually be tested.
