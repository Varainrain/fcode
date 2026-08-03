"""Deterministic scope tests for the bounded role-2 early recall."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import ast
import sys


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_meta_role2_recall"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("meta_role2_recall", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def test_damaged_core_keeps_full_recall():
    assert BOT.choose_recall_mode(
        BOT.RECALL_CORE_HP - 1, 1) == BOT.RECALL_ALL_SIEGERS
    assert BOT.choose_recall_mode(
        BOT.RECALL_CORE_HP - 1, 3) == BOT.RECALL_ALL_SIEGERS


def test_undamaged_multi_threat_recalls_only_role_two():
    assert BOT.choose_recall_mode(500, 1) == BOT.RECALL_NONE
    assert BOT.choose_recall_mode(500, 2) == BOT.RECALL_SIEGER_2
    assert BOT.choose_recall_mode(500, 5) == BOT.RECALL_SIEGER_2
    assert BOT.choose_recall_mode(399, 0) == BOT.RECALL_NONE


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


def test_exact_v9_scope():
    parent = ROOT / "bots" / "meta-generalist-v1"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (parent / name).read_bytes()
    candidate = class_methods(BOT_DIR / "main.py")
    control = class_methods(parent / "main.py")
    assert candidate.keys() == control.keys()
    for name in candidate:
        if name not in {"runCore", "_recall_is_up"}:
            assert candidate[name] == control[name]


def test_no_fingerprints():
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_damaged_core_keeps_full_recall()
    test_undamaged_multi_threat_recalls_only_role_two()
    test_exact_v9_scope()
    test_no_fingerprints()
