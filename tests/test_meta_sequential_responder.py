"""Deterministic scope tests for exact-v9 sequential home response."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import ast
import sys


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_meta_sequential_responder"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("meta_sequential_responder", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def threat(x, y, entity_id):
    pos = BOT.Position(x, y)
    return (0, x, y, entity_id, pos)


def test_first_uncovered_threat_is_selected():
    threats = [threat(2, 3, 10), threat(3, 3, 11), threat(4, 3, 12)]
    assert BOT.choose_home_threat(threats, set()) == threats[0][4]
    assert BOT.choose_home_threat(
        threats, {threats[0][4]}) == threats[1][4]
    assert BOT.choose_home_threat(
        threats, {threats[0][4], threats[1][4]}) == threats[2][4]


def test_all_covered_retains_stable_assignment():
    threats = [threat(2, 3, 10), threat(3, 3, 11)]
    assert BOT.choose_home_threat(
        threats, {item[4] for item in threats}) == threats[0][4]
    assert BOT.choose_home_threat([], set()) is None


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


def test_only_assignment_method_changes_from_exact_v9():
    parent = ROOT / "bots" / "meta-generalist-v1"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (parent / name).read_bytes()
    candidate_methods = class_methods(BOT_DIR / "main.py")
    parent_methods = class_methods(parent / "main.py")
    assert candidate_methods.keys() == parent_methods.keys()
    for name in candidate_methods:
        if name != "_assign_home_defender":
            assert candidate_methods[name] == parent_methods[name]


def test_no_fingerprints():
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_first_uncovered_threat_is_selected()
    test_all_covered_retains_stable_assignment()
    test_only_assignment_method_changes_from_exact_v9()
    test_no_fingerprints()
