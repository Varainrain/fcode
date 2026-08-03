"""Tests for damage-gated sequential home countering."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import ast
import sys

from fcode import Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_meta_damage_sequential"
PARENT = ROOT / "bots" / "meta-generalist-v1"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("meta_damage_sequential", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def threat(x, y, entity_id):
    pos = Position(x, y)
    return (0, x, y, entity_id, pos)


def test_healthy_core_keeps_first_target():
    threats = [threat(2, 3, 10), threat(4, 3, 11)]
    assert BOT.choose_home_threat(
        threats, {Position(2, 3)}, False) == Position(2, 3)


def test_damaged_core_advances_to_uncovered_target():
    threats = [threat(2, 3, 10), threat(4, 3, 11), threat(6, 3, 12)]
    assert BOT.choose_home_threat(
        threats, {Position(2, 3)}, True) == Position(4, 3)
    assert BOT.choose_home_threat(
        threats, {Position(2, 3), Position(4, 3)}, True) == Position(6, 3)
    assert BOT.choose_home_threat(
        threats, {item[4] for item in threats}, True) == Position(2, 3)


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
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (PARENT / name).read_bytes()
    candidate = class_methods(BOT_DIR / "main.py")
    control = class_methods(PARENT / "main.py")
    assert candidate.keys() == control.keys()
    for name in candidate:
        if name != "_assign_home_defender":
            assert candidate[name] == control[name]
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8")
    assert (
        "sequential = ct.get_hp() < DAMAGE_SEQUENTIAL_HP and len(threats) >= 2"
        in source
    )


def test_no_fingerprints():
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_healthy_core_keeps_first_target()
    test_damaged_core_advances_to_uncovered_target()
    test_exact_v9_scope()
    test_no_fingerprints()
