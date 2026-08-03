"""Deterministic checks for the v18 diagonal core-heal correction."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_heal_stand"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v18_heal_stand", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def test_only_orthogonal_ring_tiles_are_heal_stands():
    core = Position(1, 1)
    assert BOT.isCoreHealStand(Position(0, 1), core)
    assert BOT.isCoreHealStand(Position(2, 0), core)
    assert not BOT.isCoreHealStand(Position(0, 0), core)
    assert not BOT.isCoreHealStand(Position(3, 3), core)


if __name__ == "__main__":
    test_only_orthogonal_ring_tiles_are_heal_stands()
