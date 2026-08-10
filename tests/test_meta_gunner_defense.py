from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fcode import Direction, EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "exp_meta_gunner_defense"


def load_main():
    sys.path.insert(0, str(BOT))
    try:
        spec = importlib.util.spec_from_file_location(
            "exp_meta_gunner_defense_main", BOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


META = load_main()


class GunnerController:
    def __init__(self, threat=True, resources=26):
        self.threat = threat
        self.resources = resources
        self.rotated = None

    def get_gunner_target(self):
        return None

    def get_direction(self):
        return Direction.NORTH

    def get_position(self):
        return Position(0, 0)

    def get_team(self, entity_id=None):
        return 0

    def read_store(self, slot):
        if slot == META.SLOT_HOME_THREAT and self.threat:
            return META.pack_position(Position(2, 0))
        return 0

    def can_fire_from(self, position, direction, entity_type, target):
        return (
            entity_type == EntityType.GUNNER
            and target == Position(2, 0)
            and direction == Direction.EAST
        )

    def get_global_resources(self):
        return self.resources

    def can_rotate(self, direction):
        return direction == Direction.EAST

    def rotate(self, direction):
        self.rotated = direction


def test_emergency_ammo_preserves_titanium_reserve():
    assert META.emergency_ammo_conversion(0, 40, True) == 12
    assert META.emergency_ammo_conversion(7, 100, True) == 13
    assert META.emergency_ammo_conversion(20, 100, True) == 0
    assert META.emergency_ammo_conversion(0, 100, False) == 0


def test_home_gunner_rotates_at_emergency_floor():
    controller = GunnerController()
    META.Player().runGunner(controller)
    assert controller.rotated == Direction.EAST


def test_no_threat_does_not_use_emergency_rotation():
    controller = GunnerController(threat=False, resources=26)
    META.Player().runGunner(controller)
    assert controller.rotated is None


def test_experiment_changes_only_main_and_readme():
    parent = ROOT / "bots" / "exp_trans_40"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT / name).read_bytes() == (parent / name).read_bytes()


if __name__ == "__main__":
    test_emergency_ammo_preserves_titanium_reserve()
    test_home_gunner_rotates_at_emergency_floor()
    test_no_threat_does_not_use_emergency_rotation()
    test_experiment_changes_only_main_and_readme()
    print("home gunner tests passed")
