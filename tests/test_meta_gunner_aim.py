from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fcode import Direction, EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "exp_meta_gunner_aim"


def load_main():
    sys.path.insert(0, str(BOT))
    try:
        spec = importlib.util.spec_from_file_location("meta_aim", BOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


META = load_main()


class Controller:
    def __init__(self, threat=True, resources=26):
        self.threat = threat
        self.resources = resources
        self.rotated = None

    def get_gunner_target(self): return None
    def get_direction(self): return Direction.NORTH
    def get_position(self): return Position(0, 0)
    def get_team(self, entity_id=None): return 0
    def read_store(self, slot):
        return (META.pack_position(Position(2, 0))
                if self.threat and slot == META.SLOT_HOME_THREAT else 0)
    def can_fire_from(self, pos, direction, kind, target):
        return (kind == EntityType.GUNNER and direction == Direction.EAST
                and target == Position(2, 0))
    def get_global_resources(self): return self.resources
    def can_rotate(self, direction): return direction == Direction.EAST
    def rotate(self, direction): self.rotated = direction


def test_exact_home_threat_rotates_gunner_at_defense_floor():
    ct = Controller()
    META.Player().runGunner(ct)
    assert ct.rotated == Direction.EAST


def test_absent_threat_does_not_use_defense_floor():
    ct = Controller(threat=False)
    META.Player().runGunner(ct)
    assert ct.rotated is None


def test_only_main_and_readme_change():
    parent = ROOT / "bots" / "exp_trans_40"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT / name).read_bytes() == (parent / name).read_bytes()


if __name__ == "__main__":
    test_exact_home_threat_rotates_gunner_at_defense_floor()
    test_absent_threat_does_not_use_defense_floor()
    test_only_main_and_readme_change()
    print("home gunner aiming tests passed")
