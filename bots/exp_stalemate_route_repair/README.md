# Stalemate Route Repair experiment

**Promotion reject.** Parent gate: 82/168 (49%), core kills 70-71. Combat was
preserved, but round 300 was too late: the 26 round-1000 games went 12-14 and
mean titanium was 3,528 versus 3,565. Preserve as boundary evidence.

Parent: frozen `meta-generalist-v1`.

Two earlier independent gates proved that facing-aware orphan repair improves
round-1000 titanium but that round-80 activation costs core conversions:

- Broad rewrite: rejected at 3/12, core kills 3-9.
- Bounded round-80 repair: 83/168, core kills 64-79; won 19/25 round-1000
  games with 4,838 versus 2,785 mean titanium.
- Waller-first round-80 repair: 81/168, core kills 64-77; won 17/27 round-1000
  games with 4,017 versus 3,496 mean titanium.

This experiment changes one boundary: repair cannot activate before round 300.
The opening, economy, pressure transition, and full normal combat window remain
the parent behavior. In a surviving stalemate, the waller is preferred; a
normal builder repairs only while idle at score 1.5. Routes are bounded to eight
links, start with at least 100 titanium, follow real conveyor facings, avoid
loaded/unproven trunks, and can surgically rebuild one wrong-facing or cyclic
link rooted at an orphan harvester.

No map, dimensions, side, opponent, or new store state is used. Root, frozen
parent, and live package remain untouched.
