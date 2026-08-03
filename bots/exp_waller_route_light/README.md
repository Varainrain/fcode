# Lightweight Waller Route Repair experiment

**Mechanism pass, promotion hold.** Three complete parent gates on engine
2.3.3 combine to 256/504 (50.8%), core kills 210-211. The 81 round-1000 games
went 45-36 (55.6%) with mean collected titanium 3,328 versus 3,245. The change
improves the reported failure and is aggregate-neutral, but misses the declared
nonnegative core-kill gate by one. Do not stack, package, upload, or promote
without new production replay evidence.

Parent: frozen `meta-generalist-v1`.

The facing-aware repair mechanism improved long-game titanium in two full
gates, but early versions scanned economy buildings inside every builder's hot
map loop. The waller-only version then lost 2/12 to the rush, including several
pre-activation games, identifying observation overhead as an independent bug.

This variant preserves the waller-only, heal-gated round-120 repair while
moving graph observation completely out of `MapPathfinder.getNewTiles`.
Ordinary builders never scan the economic graph. The waller starts refreshing
visible harvester positions and conveyor facings only at the activation round.
Before round 120, the parent hot path and actions are unchanged except for one
short-circuited round-number comparison.

Repair remains bounded to eight links and 100 titanium, merges only into an
empty facing-proven trunk, and may rebuild one wrong-facing or cyclic link
rooted at an orphan harvester. No map, dimensions, side, opponent, or new store
state is used. Root, frozen parent, and live package are untouched.
