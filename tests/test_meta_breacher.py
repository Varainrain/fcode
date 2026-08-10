from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fcode import EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "exp_meta_breacher"


def load_main():
    sys.path.insert(0, str(BOT))
    try:
        spec = importlib.util.spec_from_file_location("meta_breacher", BOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


META = load_main()


class BlockerController:
    def __init__(self, kind=EntityType.BARRIER, enemy=True, firing=True):
        self.kind = kind
        self.enemy = enemy
        self.firing = firing
        self.position = Position(7, 10)

    def get_team(self, entity_id=None):
        return 1 if entity_id is not None and self.enemy else 0

    def get_nearby_buildings(self):
        return [4]

    def get_entity_type(self, entity_id):
        return self.kind

    def get_position(self, entity_id):
        return self.position

    def can_fire_from(self, seat, facing, kind, target):
        return self.firing and seat == self.position and kind == EntityType.GUNNER


def blocker(kind=EntityType.BARRIER, enemy=True, firing=True):
    ct = BlockerController(kind, enemy, firing)
    player = META.Player()
    return player._visible_core_seat_blocker(ct, Position(10, 10))


def test_only_enemy_barrier_on_real_core_seat_is_selected():
    assert blocker() == Position(7, 10)
    assert blocker(enemy=False) is None
    assert blocker(kind=EntityType.CONVEYOR) is None
    assert blocker(firing=False) is None


def test_supporting_modules_match_parent():
    parent = ROOT / "bots" / "exp_trans_40"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT / name).read_bytes() == (parent / name).read_bytes()


if __name__ == "__main__":
    test_only_enemy_barrier_on_real_core_seat_is_selected()
    test_supporting_modules_match_parent()
    print("breacher tests passed")
