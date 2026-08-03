"""Deterministic tests for the exact-v9 single-threat countertrade."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import ast
import sys


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_meta_single_countertrade"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("meta_single_countertrade", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class FakeController:
    def __init__(self, seat, facing, target):
        self.seat = seat
        self.facing = facing
        self.target = target

    def get_nearby_tiles(self):
        return [self.seat]

    def get_tile_env(self, position):
        return BOT.Environment.EMPTY

    def get_tile_building_id(self, position):
        return None

    def can_fire_from(self, seat, facing, entity_type, target):
        return (
            seat == self.seat and facing == self.facing
            and entity_type == BOT.EntityType.GUNNER and target == self.target
        )

    def is_in_vision(self, position):
        return True

    def get_tile_builder_bot_id(self, position):
        return None

    def is_tile_passable(self, position):
        return True


def fixture():
    seat = BOT.Position(8, 8)
    stand = seat.add(BOT.Direction.NORTH)
    target = BOT.Position(10, 10)
    facing = BOT.Direction.SOUTHEAST
    controller = FakeController(seat, facing, target)
    player = BOT.Player()
    player.mapW = player.mapH = 20
    return player, controller, seat, stand, target, facing


def test_one_turret_allows_bounded_countertrade():
    player, controller, seat, stand, target, facing = fixture()
    one_turret = [(1, 1, 10, {seat})]
    assert player._bounded_home_counter_plan(
        controller, stand, target, one_turret
    ) == (seat, stand, facing)


def test_builder_stand_remains_strictly_safe():
    player, controller, seat, stand, target, _ = fixture()
    unsafe_stands = {seat.add(direction) for direction in BOT.CARDINALS}
    one_turret = [(1, 1, 10, {seat} | unsafe_stands)]
    assert player._bounded_home_counter_plan(
        controller, stand, target, one_turret
    ) is None


def test_zero_threats_produces_no_plan():
    player, controller, _, stand, target, _ = fixture()
    assert player._bounded_home_counter_plan(
        controller, stand, target, []
    ) is None


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


def test_only_bounded_plan_changes_from_exact_v9():
    parent = ROOT / "bots" / "meta-generalist-v1"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (parent / name).read_bytes()
    candidate_methods = class_methods(BOT_DIR / "main.py")
    parent_methods = class_methods(parent / "main.py")
    assert candidate_methods.keys() == parent_methods.keys()
    for name in candidate_methods:
        if name != "_bounded_home_counter_plan":
            assert candidate_methods[name] == parent_methods[name]


def test_no_fingerprints():
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_one_turret_allows_bounded_countertrade()
    test_builder_stand_remains_strictly_safe()
    test_zero_threats_produces_no_plan()
    test_only_bounded_plan_changes_from_exact_v9()
    test_no_fingerprints()
