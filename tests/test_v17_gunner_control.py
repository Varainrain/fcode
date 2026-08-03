"""Deterministic tests for the exact-v17 gun-control experiment."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v17_gunner_control"
PARENT = ROOT / "bots" / "live-v17-control"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v17_gunner_control", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class BuilderTargetController:
    def __init__(self, friendly=False):
        self.friendly = friendly
        self.target = Position(0, 2)
        self.fired = None

    def get_gunner_target(self): return self.target
    def get_direction(self, entity_id=None): return Direction.NORTH
    def get_position(self): return Position(0, 0)
    def get_team(self, entity_id=None):
        return 0 if entity_id is None or self.friendly else 1
    def get_tile_building_id(self, position): return None
    def get_tile_builder_bot_id(self, position): return 7
    def can_fire(self, position): return position == self.target
    def fire(self, position): self.fired = position


class AimController:
    def __init__(self, current, attacks, resources=100):
        self.current = current
        self.attacks = attacks
        self.resources = resources
        self.rotated = None
        self.entities = {}
        next_id = 10
        for positions in attacks.values():
            for position in positions:
                if position not in self.entities:
                    self.entities[position] = next_id
                    next_id += 1

    def get_gunner_target(self): return None
    def get_direction(self, entity_id=None):
        return self.current if entity_id is None else Direction.SOUTH
    def get_position(self): return Position(4, 4)
    def get_team(self, entity_id=None): return 0 if entity_id is None else 1
    def get_attackable_tiles_from(self, position, direction, entity_type):
        assert entity_type == EntityType.GUNNER
        return self.attacks.get(direction, [])
    def get_tile_building_id(self, position): return self.entities.get(position)
    def get_entity_type(self, entity_id): return EntityType.GUNNER
    def get_global_resources(self): return self.resources
    def can_rotate(self, direction): return True
    def rotate(self, direction): self.rotated = direction


def test_gunner_fires_lone_enemy_builder_but_not_friendly_builder():
    enemy = BuilderTargetController()
    BOT.Player().runGunner(enemy)
    assert enemy.fired == enemy.target
    friendly = BuilderTargetController(friendly=True)
    BOT.Player().runGunner(friendly)
    assert friendly.fired is None


def test_equal_score_keeps_current_facing():
    north = Position(4, 1)
    east = Position(7, 4)
    ct = AimController(
        Direction.EAST,
        {Direction.NORTH: [north], Direction.EAST: [east]})
    player = BOT.Player()
    player.coreThreatSpots = lambda _: set()
    player.runGunner(ct)
    assert ct.rotated is None


def test_core_threat_target_beats_multiple_unrelated_guns():
    threat = Position(4, 1)
    ct = AimController(
        Direction.EAST,
        {
            Direction.NORTH: [threat],
            Direction.EAST: [Position(7, 4), Position(6, 4)],
        },
        resources=30,
    )
    player = BOT.Player()
    player.coreThreatSpots = lambda _: {
        (threat.x, threat.y, Direction.SOUTH)
    }
    player.runGunner(ct)
    assert ct.rotated == Direction.NORTH


def test_scope_and_no_fingerprints():
    assert (BOT_DIR / "mapPathfinding.py").read_bytes() == (
        PARENT / "mapPathfinding.py").read_bytes()
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "pinch.map", "pantheon", "smartfridge"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_gunner_fires_lone_enemy_builder_but_not_friendly_builder()
    test_equal_score_keeps_current_facing()
    test_core_threat_target_beats_multiple_unrelated_guns()
    test_scope_and_no_fingerprints()
