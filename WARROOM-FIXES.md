# Warroom fixes (oni, 2026-07-27) — evidence-backed, priority order

## P0 — the rating column is not usable for champion selection
**Evidence 1 (duplicate pollution):** `frozen-erebus-v1` and `oogerebus` are
BYTE-IDENTICAL (md5 `6313a2fa66d1361af5424ca314d085f0` on main.py, verified
today) yet sit at **1625 vs 1573 = 52 ELO apart** as two separate pool entries.
Identical bots, 52 points. That gap IS the noise floor, measured.
**Evidence 2 (rank inversion):** `OogwayOld` ranks **#1 at 1758**, above
`frozen-erebus-v1` at 1625 — but head-to-head over 168 games it loses
**48% (kills 61-76)**. A 133-point inversion. This is the SECOND such case;
the handoff already caught it with OogwayWIP (#1 at 1790, beaten pairwise).

Fixes:
1. **De-duplicate by content hash.** Hash each bot dir on registration; merge
   or refuse duplicates. Identical bots currently split their sample AND
   generate meaningless self-matches that move both ratings.
2. **Rank by pairwise, not ELO.** Make the pairwise matrix the primary view;
   demote ELO to a rough sort key with a visible "advisory only" note.
3. **Exclude weak bots from rating updates.** Pool contains `public` (5.4%),
   `v85` (17.3%), `khaos` (29.2%), `kfort` (38.2%). Whoever farms them rises.
   Either park them or compute ratings only over peers (e.g. within 300 ELO).

## P1 — scheduling leaves the decisive matchups unplayed
`OogwayOld` vs `frozen-erebus-v1` — the #1 and #3 bots — had **ZERO games ever**
until I ran it manually. The auto-league happily ran dozens of other pairings.
Fixes:
4. **Coverage matrix in the UI**: games-per-pair, so gaps are obvious at a glance.
5. **Prioritised scheduling**: never-played pairs first, then top-of-table pairs,
   then highest-variance pairs. Random pairing wastes most of the compute.

## P2 — sample sizes below the noise floor are displayed as facts
Auto-league default is **6-game minis** (`maps:mini, seeds:1`). Team's own
calibration: byte-identical bots read **67-33**. A 6-game result is ~zero
information, but it renders identically to a 168-game result.
Fixes:
6. **Show `n` and a confidence interval on every number.**
7. **Grey out / label "unproven" anything under ~100 games or in the 45-60% band**
   (the team's own stated threshold).
8. **Show kill-differential next to win%** — the handoff already says to use it
   as the corroborator; it should be first-class, not manual.

## P3 — large jobs silently vanish
I queued two jobs via `/api/queue` (`c15vi7y1`, `6wd3vd25`: full maps, seeds=4,
= 168 games each). Within minutes: `queue: 0`, `running: 0`, and no results ever
appeared. Workers had been running 6-game minis and went idle ~25 min earlier.
Fixes:
9. **Job timeout + auto-requeue** if a claim isn't reported within N minutes.
10. **Surface claimed-but-unreported jobs** in the UI (currently invisible).
11. **Chunk large jobs** into per-map units so partial progress survives a worker
    dying, and so a 168-game job can't monopolise/strand a slot.

## P4 — gate hygiene trap outside the warroom itself
12. **`bots/champion` is STALE** — it still contains `coreHelper.py`/`defend.py`
    from the old botv2-era bot. `gate.py mybot` (default opponent = "champion")
    therefore gates against the WRONG baseline silently. Make `champion` a
    pointer resolved at runtime (or hash-verify it against the current champion
    and refuse to run if it drifts).

## Nice-to-have
13. Read-only standings view without the key, so teammates can glance at the
    table without holding a write-capable credential.
