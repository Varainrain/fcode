"""Scope tests for the lower safe home-counter reserve."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import ast
import sys


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_meta_safe_counter60"
PARENT = ROOT / "bots" / "meta-generalist-v1"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("meta_safe_counter60", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def test_safe_counter_uses_bounded_reserve():
    assert not BOT.home_counter_budget_allows(60, False)
    assert BOT.home_counter_budget_allows(61, False)
    assert BOT.home_counter_budget_allows(0, True)


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


def test_exact_v9_class_and_module_scope():
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (PARENT / name).read_bytes()
    assert class_methods(BOT_DIR / "main.py") == class_methods(
        PARENT / "main.py")
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8")
    assert "SAFE_HOME_COUNTER_FLOOR = 60" in source


def test_no_fingerprints():
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_safe_counter_uses_bounded_reserve()
    test_exact_v9_class_and_module_scope()
    test_no_fingerprints()
