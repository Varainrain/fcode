"""Gunners must choose the best facing before firing the current line."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v20_gunner_preempt"
PARENT = ROOT / "bots" / "exp_v19_near_core_finish"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v20_gunner_preempt", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class AimController:
    def __init__(self, current_type, alternate_type, resources=100):
        self.current = Position(7, 4)
        self.alternate = Position(4, 1)
        self.types = {10: current_type, 11: alternate_type}
        self.positions = {self.current: 10, self.alternate: 11}
        self.resources = resources
        self.rotated = None
        self.fired = None

    def get_gunner_target(self): return self.current
    def get_direction(self, entity_id=None):
        return Direction.EAST if entity_id is None else Direction.SOUTH
    def get_position(self): return Position(4, 4)
    def get_team(self, entity_id=None): return 0 if entity_id is None else 1
    def get_tile_building_id(self, position): return self.positions.get(position)
    def get_tile_builder_bot_id(self, position): return None
    def get_entity_type(self, entity_id): return self.types[entity_id]
    def get_attackable_tiles_from(self, position, direction, entity_type):
        if direction == Direction.EAST: return [self.current]
        if direction == Direction.NORTH: return [self.alternate]
        return []
    def get_global_resources(self): return self.resources
    def can_rotate(self, direction): return True
    def rotate(self, direction): self.rotated = direction
    def can_fire(self, target): return target == self.current
    def fire(self, target): self.fired = target


def run(controller):
    player = BOT.Player()
    player.coreThreatSpots = lambda _: set()
    player.runGunner(controller)


def test_enemy_core_facing_preempts_current_turret_shot():
    ct = AimController(EntityType.GUNNER, EntityType.CORE)
    run(ct)
    assert ct.rotated == Direction.NORTH
    assert ct.fired is None


def test_current_core_target_still_fires_immediately():
    ct = AimController(EntityType.CORE, EntityType.GUNNER)
    run(ct)
    assert ct.rotated is None
    assert ct.fired == ct.current


def test_unaffordable_rotation_keeps_useful_current_shot():
    ct = AimController(EntityType.GUNNER, EntityType.CORE, resources=50)
    run(ct)
    assert ct.rotated is None
    assert ct.fired == ct.current


def test_scope_is_main_only_and_has_no_fingerprints():
    assert (BOT_DIR / "mapPathfinding.py").read_bytes() == (
        PARENT / "mapPathfinding.py").read_bytes()
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "runestone.map", "team lazy", "smartfridge"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_enemy_core_facing_preempts_current_turret_shot()
    test_current_core_target_still_fires_immediately()
    test_unaffordable_rotation_keeps_useful_current_shot()
    test_scope_is_main_only_and_has_no_fingerprints()
