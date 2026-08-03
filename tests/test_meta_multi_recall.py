"""Deterministic scope tests for exact-v9 multi-threat soft recall."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import ast
import sys


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_meta_multi_recall"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("meta_multi_recall", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def test_original_damage_trigger_is_preserved():
    assert BOT.should_raise_recall(BOT.RECALL_CORE_HP - 1, 1)
    assert not BOT.should_raise_recall(BOT.RECALL_CORE_HP, 1)
    assert not BOT.should_raise_recall(BOT.RECALL_CORE_HP - 1, 0)


def test_multiple_verified_threats_trigger_before_damage():
    assert BOT.should_raise_recall(500, 2)
    assert BOT.should_raise_recall(500, 5)
    assert not BOT.should_raise_recall(500, 0)


def class_methods(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    player = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Player"
    )
    return {
        node.name: ast.dump(node, include_attributes=False)
        for node in player.body if isinstance(node, ast.FunctionDef)
    }


def test_only_core_trigger_changes_from_exact_v9():
    parent = ROOT / "bots" / "meta-generalist-v1"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (parent / name).read_bytes()
    candidate_methods = class_methods(BOT_DIR / "main.py")
    parent_methods = class_methods(parent / "main.py")
    assert candidate_methods.keys() == parent_methods.keys()
    for name in candidate_methods:
        if name != "runCore":
            assert candidate_methods[name] == parent_methods[name]


def test_no_fingerprints():
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_original_damage_trigger_is_preserved()
    test_multiple_verified_threats_trigger_before_damage()
    test_only_core_trigger_changes_from_exact_v9()
    test_no_fingerprints()
