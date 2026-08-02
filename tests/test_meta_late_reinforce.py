from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "exp_meta_late_reinforce"


def load_main():
    sys.path.insert(0, str(BOT))
    try:
        spec = importlib.util.spec_from_file_location(
            "exp_meta_late_reinforce_main", BOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


META = load_main()


def test_existing_economy_never_converts():
    assert not META.is_late_reinforcement(1, False, False)
    assert not META.is_late_reinforcement(META.ECON_CUTOFF - 1, False, False)


def test_post_transition_production_converts():
    assert META.is_late_reinforcement(META.ECON_CUTOFF, False, False)
    assert META.is_late_reinforcement(META.ECON_CUTOFF + 100, False, False)


def test_special_roles_are_not_reclassified():
    assert not META.is_late_reinforcement(META.ECON_CUTOFF, True, False)
    assert not META.is_late_reinforcement(META.ECON_CUTOFF, False, True)


def test_experiment_changes_only_main_and_readme():
    parent = ROOT / "bots" / "exp_trans_40"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT / name).read_bytes() == (parent / name).read_bytes()


if __name__ == "__main__":
    test_existing_economy_never_converts()
    test_post_transition_production_converts()
    test_special_roles_are_not_reclassified()
    test_experiment_changes_only_main_and_readme()
    print("late reinforcement tests passed")
