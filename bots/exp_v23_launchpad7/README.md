# v22 productive-edge repair + damaged-core economy ownership

Child of inactive submission v21 `exp_v20_opportunistic_trunk_repair`.
It preserves v21's exact spare-opportunity repair of previously productive
conveyor edges.

The additional change fixes an inherited role-ownership bug. Economy builders
still counter every visible uncovered enemy gun. Once all visible guns are
covered, however, they join healing only when they can see that the friendly
core is actually damaged. A full or out-of-sight core releases them back to
routing and harvesting. Fixed defender roles continue countering and healing
unchanged. This prevents `healCore` from recalling all economy builders after a
failed heal while retaining emergency healing during real damage.

Fresh production 2.3.3 gates (21 maps, four seeds, both sides):

| Gate | Result | Core kills | v21 baseline |
|---|---:|---:|---:|
| exact v21 parent | **90/168 (53.6%)** | **73-73** | parity requirement |
| `spar_rush` | **160/168 (95.2%)** | **157-5** | 156/168 |
| `oogbest-v6` | **147/168 (87.5%)** | **140-16** | 139/168 |
| `meta-generalist-v1` | **153/168 (91.1%)** | **152-9** | 153/168 |

The broader release of all covered-threat economy builders was rejected at
83/168 with core kills 73-79. The visible-damaged-core condition is therefore
part of the mechanism, not a tuning detail. Deterministic coverage is in
`tests/test_v21_eco_release_only_damaged.py`.

Submission v22 (`5861c003-13a8-48c4-bc42-fe01445c6245`) completed ten unrated
series at **30-20**, estimated core kills **30-19**. Against unchanged opponent
versions it scored 29-11: CtrlAltDefeat 10-0, Orizon 7-3, team lazy 6-4, and
SmartFridge 6-4. Updated Pantheon v14 scored 9-1 against v22 and remains a new
pressure-meta problem rather than an optimization target. Across all 50 games
v22 averaged 10.36 connected and 1.32 disconnected conveyors. The replay-
confirmed team-lazy String failure changed from no economy and a round-1000
loss in v21 to five harvesters and a turn-829 core win in v22. Replays are in
`C:/Users/subodh/Downloads/fcode-gate-artifacts/ladder-v22-20260803/`.

A pinned v18 control then scored 0-5 against Pantheon v14 on String, Pinch,
Bridge, Atoll, and Sprint, all by core destruction. V22 was 1-4 on its matching
five-map series, so the Pantheon result is a new opponent-version weakness, not
a demonstrated v22 regression.
