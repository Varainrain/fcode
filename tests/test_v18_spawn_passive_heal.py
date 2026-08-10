"""Deterministic checks for Pantheon-style spare-action healing."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, EntityType, Position, Team


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_spawn_passive_heal"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v18_spawn_passive_heal", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class HealController:
    def __init__(self, resources=100, cooldown=0):
        self.resources = resources
        self.cooldown = cooldown
        self.healed = None
        origin = Position(5, 5)
        self.buildings = {
            origin.add(Direction.NORTH): 10,
            origin.add(Direction.EAST): 11,
        }
        self.types = {10: EntityType.CORE, 11: EntityType.GUNNER}
        self.hp = {10: 499, 11: 20}
        self.max_hp = {10: 500, 11: 40}

    def get_action_cooldown(self): return self.cooldown
    def get_global_resources(self): return self.resources
    def get_position(self): return Position(5, 5)
    def get_team(self, entity_id=None): return Team.A
    def get_tile_building_id(self, tile): return self.buildings.get(tile)
    def get_hp(self, entity_id): return self.hp[entity_id]
    def get_max_hp(self, entity_id): return self.max_hp[entity_id]
    def get_entity_type(self, entity_id): return self.types[entity_id]
    def can_heal(self, tile): return tile in self.buildings
    def heal(self, tile): self.healed = tile


def test_core_priority_beats_more_damaged_gunner():
    ct = HealController()
    assert BOT.Player().tryPassiveHeal(ct)
    assert ct.healed == Position(5, 4)


def test_passive_heal_never_spends_reserve_or_overrides_action():
    reserve = HealController(resources=BOT.PASSIVE_HEAL_TITANIUM_FLOOR)
    assert not BOT.Player().tryPassiveHeal(reserve)
    assert reserve.healed is None
    acted = HealController(cooldown=1)
    assert not BOT.Player().tryPassiveHeal(acted)
    assert acted.healed is None


if __name__ == "__main__":
    test_core_priority_beats_more_damaged_gunner()
    test_passive_heal_never_spends_reserve_or_overrides_action()
