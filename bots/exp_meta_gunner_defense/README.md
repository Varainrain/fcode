# Reactive home-gunner experiment

Parent: frozen `exp_trans_40` (production v8 lineage).

This isolates the two defensive mechanics present in the old v6 live success
but omitted when recall was ported: nearby friendly gunners rotate directly onto
the exact core-hitting threat published in slot 15, and the core may refill ammo
during a real low-HP attack while preserving 28 titanium. Generic gunner logic,
recall, the responder, siege, economy, spawning, and pathfinding are unchanged.

The behavior is memoryless and fully reactive. It activates only from the real
attack pattern used by the existing home-threat detector.
