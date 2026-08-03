"""Deterministic checks for facing-proven conveyor merge targets."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fcode import Direction, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_spawn_route_proof"
spec = spec_from_file_location(
    "v18_spawn_route_proof_map", BOT_DIR / "mapPathfinding.py")
MAP = module_from_spec(spec)
spec.loader.exec_module(MAP)


CORE = Position(0, 0)
CORE_TILES = MAP.coreFootprint(CORE)


def test_chain_reaching_core_is_safe_merge():
    directions = {
        Position(3, 0): Direction.WEST,
        Position(2, 0): Direction.WEST,
    }
    visible = {Position(x, 0) for x in range(5)}
    assert MAP.visibleConveyorMergeSafe(
        Position(3, 0), directions, CORE_TILES, visible)


def test_visible_dead_end_and_cycle_are_rejected():
    dead_end = {Position(3, 0): Direction.WEST}
    visible = {Position(x, 0) for x in range(5)}
    assert not MAP.visibleConveyorMergeSafe(
        Position(3, 0), dead_end, CORE_TILES, visible)
    cycle = {
        Position(3, 0): Direction.WEST,
        Position(2, 0): Direction.EAST,
    }
    assert not MAP.visibleConveyorMergeSafe(
        Position(3, 0), cycle, CORE_TILES, visible)


def test_unseen_continuation_requires_strict_core_progress():
    visible = {Position(3, 0)}
    assert MAP.visibleConveyorMergeSafe(
        Position(3, 0), {Position(3, 0): Direction.WEST},
        CORE_TILES, visible)
    assert not MAP.visibleConveyorMergeSafe(
        Position(3, 0), {Position(3, 0): Direction.EAST},
        CORE_TILES, visible)


if __name__ == "__main__":
    test_chain_reaching_core_is_safe_merge()
    test_visible_dead_end_and_cycle_are_rejected()
    test_unseen_continuation_requires_strict_core_progress()
