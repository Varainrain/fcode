from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "exp_meta_reinforce"


def load_main():
    sys.path.insert(0, str(BOT))
    try:
        spec = importlib.util.spec_from_file_location(
            "exp_meta_reinforce_main", BOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


META = load_main()


def policy(round_no, spawned=5, waller=False, committed=False, contact=False):
    return META.should_commit_reinforcement(
        round_no, spawned, waller, committed, contact)


def test_opening_is_preserved_without_contact():
    assert not policy(17, contact=True)
    assert not policy(18, spawned=4, contact=True)
    assert not policy(39)


def test_mature_contact_can_trigger_early_conversion():
    assert policy(18, contact=True)
    assert policy(39, contact=True)


def test_normal_transition_converts_without_contact():
    assert not policy(39)
    assert policy(40)
    assert policy(100)


def test_commitment_latches_but_never_claims_the_waller():
    assert policy(25, committed=True)
    assert not policy(100, waller=True, committed=True, contact=True)


def test_experiment_changes_only_main_and_readme():
    parent = ROOT / "bots" / "exp_trans_40"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT / name).read_bytes() == (parent / name).read_bytes()


if __name__ == "__main__":
    test_opening_is_preserved_without_contact()
    test_mature_contact_can_trigger_early_conversion()
    test_normal_transition_converts_without_contact()
    test_commitment_latches_but_never_claims_the_waller()
    test_experiment_changes_only_main_and_readme()
    print("meta reinforcement tests passed")
