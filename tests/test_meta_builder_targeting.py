from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fcode import Direction, Position


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "exp_meta_builder_targeting"


def load_main():
    sys.path.insert(0, str(BOT))
    try:
        spec = importlib.util.spec_from_file_location("meta_builder_target", BOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


META = load_main()


class CurrentBuilderTarget:
    def __init__(self, friendly=False):
        self.friendly = friendly
        self.fired = None
        self.target = Position(0, 2)

    def get_gunner_target(self): return self.target
    def get_direction(self): return Direction.NORTH
    def get_position(self): return Position(0, 0)
    def get_team(self, entity_id=None):
        if entity_id == 7:
            return 0 if self.friendly else 1
        return 0
    def get_tile_building_id(self, position): return None
    def get_tile_builder_bot_id(self, position): return 7
    def can_fire(self, position): return position == self.target
    def fire(self, position): self.fired = position
    def get_global_resources(self): return 0


def test_gunner_fires_enemy_builder_on_empty_tile():
    ct = CurrentBuilderTarget()
    META.Player().runGunner(ct)
    assert ct.fired == ct.target


def test_gunner_never_fires_friendly_builder():
    ct = CurrentBuilderTarget(friendly=True)
    META.Player().runGunner(ct)
    assert ct.fired is None


def test_supporting_modules_match_parent():
    parent = ROOT / "bots" / "exp_trans_40"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT / name).read_bytes() == (parent / name).read_bytes()


if __name__ == "__main__":
    test_gunner_fires_enemy_builder_on_empty_tile()
    test_gunner_never_fires_friendly_builder()
    test_supporting_modules_match_parent()
    print("builder targeting tests passed")
