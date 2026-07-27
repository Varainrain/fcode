# Findings — oni session 2026-07-27 (all numbers 168 games / 4 seeds, engine 2.3.0.dev26)

## 1. ⚠ WARROOM ELO IS MISLEADING FOR CHAMPION SELECTION — 133-point inversion
`/api/state` ranks **OogwayOld #1 at 1758 ELO**, above frozen-erebus-v1 (1625).
Measured head-to-head, which had **never been run**:

| matchup | result | verdict |
|---|---|---|
| OogwayOld vs frozen-erebus-v1 | **80/168 = 48%**, kills **61-76 against** | REJECT — fev1 holds |

Win% and kill-diff agree, so this is a trustworthy read (per the handoff's own
corroboration rule). **This is the SECOND confirmed ELO inversion** — the
handoff already caught it with OogwayWIP (#1 at 1790, actually beaten by
oogerebus pairwise). Two independent cases = structural, not a fluke:
**use the pairwise matrix / gate.py, never the ELO column, to pick a champion.**

## 2. shield-v1 — REJECTED (see bots/shield-v1/README.md)
Harvester guard-conveyors ("shield pieces"), the one idea BOTH Cambridge top-2
teams use that we had never tried (we only ever ringed the core). Built as a
passive spare-action side effect (zero restriction — the documented ~11pt tax
is the restriction, not the walling).
- vs frozen-erebus-v1: **51%** (kills 70-63) — inside the unproven band = tie
- vs krb: 62% — but the champion itself is 63% vs krb, so no gain
**Why it likely doesn't transfer:** in Cambridge the shield was cheap ROADS and
turret ammo was conveyor-FED, so denying feeder-adjacency mattered. fcode has
no roads and a GLOBAL ammo pool — an enemy gunner does not need to sit next to
our mine to work.

## 3. OogwayOld's recent commits (61e29d8 -> f5de80b): noise + one likely regression
Six changes, all constant-tuning inside a fixed strategy (rotate score +2->+4,
attack weight 10->11, falloff /40->/48, explore cycle /20->/16, heal guard,
destroy-list). Measured head-to-head **29-31 = indistinguishable**.
- ⚠ **One change is high-risk:** the attack gate `>120 and get_id()>4` -> `>100`.
  The handoff already establishes this gate is LOAD-BEARING (three loosening
  variants gated 26%/18%), and `fe-idfix` showed `get_id()>4` reserves exactly
  one defender per side (ids A:3,5,8,13 / B:4,6,9,14 — symmetric by luck).
  Deleting it removed the last defensive reservation while the bot's live
  failure mode is dying to blitzes. **Suggest reverting that one line.**
- OogwayOld and OogwayWIP are 382 lines each, **48 diff lines apart** — near
  identical siblings. oogerebus = that same chassis + 88 lines of proven armor
  (56% PROMOTE). Inheriting that beats hunting constants.
- Neither OogwayOld nor OogwayWIP has the dev26 crash wrapper (oogerebus does).
  Measured **0 exceptions in 3 games** — cheap insurance, not a live bug.

## 4. ⚠ GATE HYGIENE: `bots/champion` is STALE
It still contains `coreHelper.py` / `defend.py` from the old botv2-era bot, so
`python gate.py mybot` (default opponent = "champion") silently gates against
the WRONG bot. Always name the baseline explicitly: `gate.py mybot frozen-erebus-v1 4`.

## Standing
Twelve challengers have now failed against frozen-erebus-v1. The cheap-fix
space looks genuinely exhausted; remaining unmined ideas from the handoff are
state-commitment (anti-thrash), store slots 8-15 coordination + canonical-ally
anti-clumping, and ore-hopping.
