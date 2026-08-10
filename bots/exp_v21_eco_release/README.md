# v21 opportunistic productive-edge repair

Independent child of inactive v20 `exp_v19_near_core_finish`. It preserves all
v20 combat, spawning, roles, direct siege, and normal conveyor routing.

Each economy builder remembers only conveyor edges it personally observed as
draining toward the core. If an exact remembered edge later disappears, it is
eligible for repair only when a live upstream conveyor/harvester still feeds
the tile and the remembered output joins a currently proven downstream suffix.
The builder rebuilds it only when `can_build_conveyor` succeeds immediately.
It never walks toward a repair, reserves a role, publishes a claim, or commits
to a distant route. This is the spare-opportunity form of Pantheon's persistent
map/route-repair idea.

Fresh production 2.3.3 gates (21 maps, four seeds, both sides):

| Gate | Result | Core kills | v20 baseline / requirement |
|---|---:|---:|---:|
| exact v20 parent | **88/168 (52.4%)** | **75-71** | >=50%, nonnegative kills |
| `spar_rush` | **156/168 (92.9%)** | **156-7** | 158/168 |
| `oogbest-v6` | **139/168 (82.7%)** | **136-22** | 142/168 |
| `meta-generalist-v1` | **153/168 (91.1%)** | **153-10** | 155/168 |

All family regressions are below five percentage points. After dead claim/travel
code was removed, compact screens were 6/12 parent, 11/12 rush, 10/12 Oogway,
and 10/12 generalist; direct tests and compilation pass.

Rejected siblings are evidence, not stack components. The walking/TTL repair
finished 249/504 with core kills 214-218 despite a long-game titanium gain;
the round-120 version finished 82/168 with kills 69-71. Gunner preemption
finished 75/168 with kills 61-82. Deterministic coverage is in
`tests/test_v20_opportunistic_trunk_repair.py`.
