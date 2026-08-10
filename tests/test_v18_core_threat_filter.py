"""Deterministic checks for v18 defender threat filtering."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_core_threat_filter"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v18_core_threat_filter", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class ThreatController:
    def __init__(self, attackable):
        self.attackable = attackable

    def get_entity_type(self, entity_id): return EntityType.GUNNER
    def get_position(self, entity_id): return Position(4, 1)
    def get_direction(self, entity_id): return Direction.WEST
    def get_attackable_tiles_from(self, position, direction, entity_type):
        return self.attackable


def test_only_current_attack_pattern_counts():
    player = BOT.Player()
    player.mapPf.teamCore = Position(1, 1)
    assert player.turretThreatensCore(
        ThreatController([Position(3, 1), Position(2, 1)]), 10)
    assert not player.turretThreatensCore(
        ThreatController([Position(4, 2), Position(3, 3)]), 10)


if __name__ == "__main__":
    test_only_current_attack_pattern_counts()
