from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "exp_meta_armor_rebuild"


def load_main():
    sys.path.insert(0, str(BOT))
    try:
        spec = importlib.util.spec_from_file_location("meta_armor", BOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


META = load_main()


def action(threat, claimed, barrier, damaged, empty):
    return META.armor_maintenance_action(
        threat, claimed, barrier, damaged, empty)


def test_maintenance_is_strictly_threat_gated():
    assert action(False, True, True, True, False) is None
    assert action(False, True, False, False, True) is None


def test_damaged_claimed_barrier_is_healed():
    assert action(True, True, True, True, False) == "heal"
    assert action(True, True, True, False, False) is None


def test_destroyed_claimed_barrier_is_rebuilt_not_expanded():
    assert action(True, True, False, False, True) == "rebuild"
    assert action(True, False, False, False, True) is None
    assert action(True, True, False, False, False) is None


def test_supporting_modules_match_prearmor_parent():
    parent = ROOT / "bots" / "exp_prearmor"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT / name).read_bytes() == (parent / name).read_bytes()


if __name__ == "__main__":
    test_maintenance_is_strictly_threat_gated()
    test_damaged_claimed_barrier_is_healed()
    test_destroyed_claimed_barrier_is_rebuilt_not_expanded()
    test_supporting_modules_match_prearmor_parent()
    print("armor rebuild tests passed")
