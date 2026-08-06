# DEFENSE-INTEGRATION.md — for Oogway, hooking defense_advisor into OogwayPlus

Four call sites. Each advisor answers a question; your code keeps ALL control
flow. Total integration is ~25 lines of your own style.

## 1. Shield gap -> a scored state, NOT a preemptive return
In the defend/eco scorer, add a "shield" state:
```python
gap = defense_advisor.next_shield_gap(ct, coreTL, self.mapW, self.mapH)
# score it BELOW attack-under-fire and BELOW heal, ABOVE idle/explore.
# Building: barrier at gap when adjacent (3 Ti); walk toward it otherwise.
```
⚠ MEASURED TRAP #1: my merge ran this as `if shield(): return` at the top of
runEco for ALL eco builders -> economy died shielding (10%, kills 7-67).
It must be a state your arbiter can outvote, on your 2-builder defend crew only.

## 2. Heal claim -> highest defensive priority when it fires
```python
if defense_advisor.claim_heal_duty(ct, coreTL):
    # this unit heals the core this turn (your healCore(ct, home))
```
One unit per round claims; everyone else falls through to normal play.
Slot 14 is the claim (allocation table in MODULES.md).

## 3. Entombment veto -> inside every home-area build
In buildGunnerFor (and any conveyor/harvester placement within 3 of core):
```python
if defense_advisor.would_entomb(ct, coreTL, spot, myTeam, self.mapW, self.mapH):
    continue
```
⚠ MEASURED TRAP #2: do NOT apply to attack builds far from home — it no-ops
there anyway (dmin>3 early-out), so hooking it everywhere is safe but hooking
it INSTEAD of your spot loop is not.

## 4. Rotation scorer -> one line in runGunner
Where you count what a facing can hit:
```python
if tType == EntityType.SENTINEL and defense_advisor.sentinel_is_core_threat(coreTL, tile):
    coreThreatHits += 1   # rotate floor 20, not 80
```

## Gate plan after integration (the pipeline, MODULES.md step 2-4)
1. mirror vs plain OogwayPlus (expect ~50-55: the stack was mirror-free on
   every chassis it was gated on)
2. scrims: SmartFridge (beat pv43 3x), Pivot, one of Pantheon/sporks
3. then activate. Expected from history: the naked chassis went 3W-7L rated;
   v4x-with-stack held #8. Chassis+stack should clear both.

## Why you, not me (so this doc doesn't read as passing the buck)
Two auto-merges by me into OogwayPlus both gated 10%. 26/26 outsider
transplants have failed; every fix that shipped, shipped when integrated by
the chassis's own structure. The advisors are turn-neutral precisely so your
arbiter stays the only decision-maker.
