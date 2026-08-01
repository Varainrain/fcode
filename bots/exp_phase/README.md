# exp_siege_on_sight  (Variant B — SHIPPED as live v2, 2026-08-01 17:20)

Parent: `bots/generalist-v3`. The siege dispatch gate stops being a round
number and becomes state: enemy core located AND titanium above the floor.
Both are true from roughly t5 via the symmetry tracker. The titanium floor is
unchanged, so the siege is earlier, not cheaper.

Variant A (`exp_early_siege`) moved the same gate 45 -> 25 and bought 26 turns.
The rest of the gap is TRAVEL — siegers start at home and walk 25-30 tiles.

| gate | result | core kills |
|---|---|---|
| vs generalist-v3 (336) | **67%** (CI 61-71) | 211-91 |
| vs exp_early_siege (168) | 63% (CI 56-70) | 96-53 |
| vs spar_rush (168) | 52% (CI 45-60) | 76-69 |

For scale, the parent scores 39% against `spar_rush` (kills 58-91).
First gun on the enemy core: t52 median, reaching t18-t22 on some maps.
Packaged byte-for-byte as `siege-on-sight.zip`.
