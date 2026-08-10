# Gunner builder-target correctness fix

Parent: frozen `exp_trans_40`.

This changes only gunner target handling. The parent fired a current target only
when the tile contained an enemy building, and its enemy-builder rotation score
was accidentally nested inside the same building condition. Enemy builders on
otherwise empty tiles were therefore ignored. This variant fires a visible
enemy builder and scores that separate unit layer at the existing weight of 2.

No strategy thresholds, economy, siege, spawning, stores, or map logic change.
