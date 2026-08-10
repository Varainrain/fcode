"""Replay-derived tests for surgical conveyor merge validation."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import ast

from fcode import Direction, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_route_integrity"
spec = spec_from_file_location("route_integrity_pathfinding", BOT_DIR / "mapPathfinding.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


CORE = {
    Position(0, 13), Position(1, 13),
    Position(0, 14), Position(1, 14),
}


def test_replay_cycle_is_rejected():
    # Exact shape observed in Oogway v9's Sweden titanium loss.
    cycle = {
        Position(4, 11): Direction.SOUTH,
        Position(4, 12): Direction.EAST,
        Position(5, 12): Direction.NORTH,
        Position(5, 11): Direction.WEST,
    }
    visible = set(cycle) | {position.add(facing) for position, facing in cycle.items()}
    for position in cycle:
        assert not BOT.visible_conveyor_merge_safe(position, cycle, CORE, visible)


def test_visible_chain_reaching_core_is_accepted():
    chain = {
        Position(4, 13): Direction.WEST,
        Position(3, 13): Direction.WEST,
        Position(2, 13): Direction.WEST,
    }
    assert BOT.visible_conveyor_merge_safe(
        Position(4, 13), chain, CORE, set(chain) | CORE)


def test_visible_dead_end_is_rejected():
    chain = {Position(4, 13): Direction.WEST}
    assert not BOT.visible_conveyor_merge_safe(
        Position(4, 13), chain, CORE,
        {Position(4, 13), Position(3, 13)},
    )


def test_monotone_chain_may_leave_vision_but_detour_may_not():
    monotone = {Position(4, 13): Direction.WEST}
    assert BOT.visible_conveyor_merge_safe(
        Position(4, 13), monotone, CORE, {Position(4, 13)})
    detour = {Position(4, 13): Direction.NORTH}
    assert not BOT.visible_conveyor_merge_safe(
        Position(4, 13), detour, CORE, {Position(4, 13)})


def method_ast(path, class_name, method_name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return ast.dump(child, include_attributes=False)
    raise AssertionError(method_name)


def test_parent_behavior_outside_merge_validation_is_preserved():
    parent = ROOT / "bots" / "exp_waller_route_light"
    for name in ("main.py", "initialSpawning.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (parent / name).read_bytes()
    for method in ("routeConveyor", "moveTo", "getNewTiles"):
        assert method_ast(BOT_DIR / "mapPathfinding.py", "MapPathfinder", method) == method_ast(
            parent / "mapPathfinding.py", "MapPathfinder", method)
    source = (BOT_DIR / "mapPathfinding.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_replay_cycle_is_rejected()
    test_visible_chain_reaching_core_is_accepted()
    test_visible_dead_end_is_rejected()
    test_monotone_chain_may_leave_vision_but_detour_may_not()
    test_parent_behavior_outside_merge_validation_is_preserved()
