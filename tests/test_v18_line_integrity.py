"""Deterministic checks for obstruction-aware v18 gun lines."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_line_integrity"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v18_line_integrity", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class CoverageController:
    def __init__(self, reaches):
        self.reaches = reaches

    def get_team(self, entity_id=None): return 0
    def get_nearby_buildings(self): return [10]
    def get_entity_type(self, entity_id): return EntityType.GUNNER
    def get_position(self, entity_id): return Position(1, 1)
    def get_direction(self, entity_id): return Direction.EAST
    def can_fire_from(self, position, direction, entity_type, target):
        return self.reaches


class BlockedAimController:
    def __init__(self):
        self.rotated = None
        self.friendly_builder = Position(5, 4)
        self.enemy_core = Position(4, 1)

    def get_gunner_target(self): return self.friendly_builder
    def get_direction(self, entity_id=None): return Direction.EAST
    def get_position(self): return Position(4, 4)
    def get_team(self, entity_id=None):
        if entity_id in (7, None): return 0
        return 1
    def get_tile_building_id(self, position):
        return 20 if position == self.enemy_core else None
    def get_tile_builder_bot_id(self, position):
        return 7 if position == self.friendly_builder else None
    def get_entity_type(self, entity_id): return EntityType.CORE
    def get_attackable_tiles_from(self, position, direction, entity_type):
        if direction == Direction.EAST:
            return [self.friendly_builder, Position(6, 4)]
        if direction == Direction.NORTH:
            return [self.enemy_core]
        return []
    def get_global_resources(self): return 100
    def can_rotate(self, direction): return True
    def rotate(self, direction): self.rotated = direction


class GunnerPathController:
    def __init__(self):
        self.position = Position(1, 1)
        self.blocker = Position(2, 1)
        self.destroyed = False
        self.moved = None

    def get_position(self): return self.position
    def get_nearby_buildings(self): return []
    def get_team(self, entity_id=None): return 0
    def get_tile_building_id(self, position):
        return 10 if position == self.blocker and not self.destroyed else None
    def get_entity_type(self, entity_id): return EntityType.GUNNER
    def can_destroy(self, position): return position == self.blocker
    def destroy(self, position): self.destroyed = True
    def can_move(self, direction):
        return direction == Direction.EAST and self.destroyed
    def move(self, direction): self.moved = direction


def test_geometric_coverage_is_not_enough():
    player = BOT.Player()
    target = Position(3, 1)
    assert not player.friendlyTurretCanHit(CoverageController(False), target)
    assert player.friendlyTurretCanHit(CoverageController(True), target)


def test_friendly_builder_does_not_freeze_gunner():
    ct = BlockedAimController()
    player = BOT.Player()
    player.coreThreatSpots = lambda _: set()
    player.runGunner(ct)
    assert ct.rotated == Direction.NORTH


def test_pathfinder_clears_selected_friendly_gunner_blocker():
    pathfinder = BOT.MapPathfinder()
    pathfinder.mapW = pathfinder.mapH = 3
    pathfinder.fullMap = [[0] * 3 for _ in range(3)]
    pathfinder.distMap = [[99] * 3 for _ in range(3)]
    pathfinder.distMap[2][1] = 0
    target = Position(2, 2)
    pathfinder.prevTarget = target
    pathfinder.mapChanged = False
    ct = GunnerPathController()
    pathfinder.moveTo(ct, target)
    assert ct.destroyed
    assert ct.moved == Direction.EAST


if __name__ == "__main__":
    test_geometric_coverage_is_not_enough()
    test_friendly_builder_does_not_freeze_gunner()
    test_pathfinder_clears_selected_friendly_gunner_blocker()
