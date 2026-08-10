"""Deterministic tests for the heal-lock retreat.

The trigger has to be a real "the siege stopped converting" signal, not a
one-off heal tick, and it has to release the unit again once the core starts
losing HP. These tests pin both directions plus the store round-trip.
"""

from pathlib import Path
import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[1]


def load_bot():
    bot_dir = ROOT / "bots" / "exp_heal_lock_retreat"
    sys.path.insert(0, str(bot_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "exp_heal_lock_retreat_main", bot_dir / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


BOT = load_bot()


def test_store_round_trip():
    for hp in (0, 1, 500, 1000, 0xFFFF):
        for evidence in range(BOT.HEAL_LOCK_MAX + 1):
            packed = BOT.pack_heal_lock(hp, evidence)
            assert packed >= 0
            if packed == 0:
                # only the genuinely empty observation encodes as "unset"
                assert hp == 0 and evidence == 0
                continue
            assert BOT.unpack_heal_lock(packed) == (hp, evidence)


def test_unset_store_reads_as_no_observation():
    assert BOT.unpack_heal_lock(0) == (None, 0)


def test_first_observation_cannot_trigger():
    # No previous HP means no evidence, however low the core is.
    assert BOT.next_heal_evidence(None, 120, 0) == 0


def test_recovering_core_accumulates_evidence():
    evidence = 0
    evidence = BOT.next_heal_evidence(100, 120, evidence)
    assert evidence == 1
    assert evidence < BOT.HEAL_LOCK_TRIGGER, "one heal tick must not trigger"
    evidence = BOT.next_heal_evidence(120, 140, evidence)
    assert evidence >= BOT.HEAL_LOCK_TRIGGER, "sustained recovery must trigger"


def test_converting_siege_releases_the_unit():
    evidence = BOT.HEAL_LOCK_TRIGGER
    evidence = BOT.next_heal_evidence(140, 120, evidence)
    assert evidence < BOT.HEAL_LOCK_TRIGGER, "damage getting through must release"


def test_evidence_is_bounded_both_ways():
    steps = BOT.HEAL_LOCK_MAX + 5      # more ticks than the cap, both ways
    evidence = 0
    for i in range(steps):
        evidence = BOT.next_heal_evidence(100 + 10 * i, 110 + 10 * i, evidence)
    assert evidence == BOT.HEAL_LOCK_MAX
    for i in range(steps):
        evidence = BOT.next_heal_evidence(110 + 10 * i, 100 + 10 * i, evidence)
    assert evidence == 0


def test_stalemate_holds_evidence_steady():
    assert BOT.next_heal_evidence(120, 120, 1) == 1


def test_heal_lock_slot_does_not_collide():
    used = {
        BOT.SLOT_WALLER_ID, BOT.SLOT_SIEGER_1_ID, BOT.SLOT_SIEGER_2_ID,
        BOT.SLOT_ENEMY_CORE, BOT.SLOT_SIEGER_2_COUNTER_TARGET,
        BOT.SLOT_HOME_DEFENDER_ID, BOT.SLOT_HOME_THREAT,
    }
    # 0 is numSpawned, 1-6 the map share, 7 the initial target.
    used.update({0, 1, 2, 3, 4, 5, 6, 7})
    assert BOT.SLOT_HEAL_LOCK not in used
    assert 0 <= BOT.SLOT_HEAL_LOCK < 16


def test_parent_behaviour_is_otherwise_untouched():
    """Everything the parent does outside the new branch must be identical."""
    import difflib
    parent = (ROOT / "bots" / "generalist-v3" / "main.py").read_text(
        encoding="utf-8").splitlines()
    child = (ROOT / "bots" / "exp_heal_lock_retreat" / "main.py").read_text(
        encoding="utf-8").splitlines()
    removed = [
        line for line in difflib.unified_diff(parent, child, lineterm="", n=0)
        if line.startswith("-") and not line.startswith("---")
    ]
    assert removed == [], f"the experiment deleted parent behaviour: {removed}"
