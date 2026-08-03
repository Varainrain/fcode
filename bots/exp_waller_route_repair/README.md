# Waller Route Repair experiment

**Crash-screen reject.** 4/12 versus parent and 2/12 versus rush, with several
losses before the round-120 feature boundary. Cause: economy-graph observation
was still hooked into every builder's every-tile map scan from round 1. The
successor must remove that hot-path overhead and refresh only on the waller
after activation.

Parent: frozen `meta-generalist-v1`.

Prior variants established the tradeoff on production engine 2.3.3:

- Round-80 repair won 19/25 long games with a large titanium advantage, but
  lost core kills 64-79 over 168.
- Waller-preferred repair still let normal builders substitute and lost core
  kills 64-77.
- Round-300 repair restored core kills to 70-71 but was too late to improve the
  long-game economy.

This independent allocation variant permits repair from round 120, but only the
parent's existing wall-role builder may act. That role is already prohibited
from normal attacks. It also defers whenever any friendly entity needs healing,
so home support remains ahead of economy. There is no normal-builder fallback.

The actual repair is unchanged: facing-proven core connectivity, one local
claim, at most eight missing links, at least 100 titanium, no loaded or unproven
merge, and surgical rebuild of a wrong-facing/cyclic link rooted at an orphan
harvester. No map, dimensions, side, opponent, or new store state is used.
Root, frozen parent, and live package remain untouched.
