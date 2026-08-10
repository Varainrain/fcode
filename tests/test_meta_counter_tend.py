"""Tests for adjacent maintenance of a live home countergun."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import ast
import sys

from fcode import Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_meta_counter_tend"
PARENT = ROOT / "bots" / "meta-generalist-v1"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("meta_counter_tend", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class TendController:
    def __init__(self, damaged=True):
        self.damaged = damaged
        self.healed = None

    def is_in_vision(self, pos):
        return False

    def get_position(self, entity_id=None):
        return Position(3, 3)

    def get_hp(self, entity_id=None):
        return 30 if self.damaged else 40

    def get_max_hp(self, entity_id=None):
        return 40

    def can_heal(self, pos):
        return True

    def heal(self, pos):
        self.healed = pos


def test_damaged_covering_gunner_is_healed_before_core():
    player = BOT.Player()
    player._friendly_covering_gunner = lambda ct, threat: 7
    player._heal_or_approach_core = lambda ct, pos: (_ for _ in ()).throw(
        AssertionError("core heal should not preempt countergun maintenance")
    )
    ct = TendController(damaged=True)
    player._run_home_defense(ct, Position(3, 4), Position(3, 1))
    assert ct.healed == Position(3, 3)


def test_healthy_covering_gunner_keeps_existing_core_behavior():
    player = BOT.Player()
    player._friendly_covering_gunner = lambda ct, threat: 7
    called = []
    player._heal_or_approach_core = lambda ct, pos: called.append(pos)
    ct = TendController(damaged=False)
    player._run_home_defense(ct, Position(3, 4), Position(3, 1))
    assert ct.healed is None
    assert called == [Position(3, 4)]


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
    assert set(candidate) == set(control) | {"_friendly_covering_gunner"}
    for name in control:
        if name not in {"_friendly_gunner_covers", "_run_home_defense"}:
            assert candidate[name] == control[name]


def test_no_fingerprints():
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_damaged_covering_gunner_is_healed_before_core()
    test_healthy_covering_gunner_keeps_existing_core_behavior()
    test_exact_v9_scope()
    test_no_fingerprints()
