"""Covered threats recall economy only for a visible damaged friendly core."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v21_eco_release_only_damaged"
PARENT = ROOT / "bots" / "exp_v20_opportunistic_trunk_repair"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v21_eco_release_only_damaged", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class MapStub:
    teamCore = Position(2, 2)


class ControllerStub:
    enemy = Position(5, 5)

    def __init__(self, core_hp=500): self.core_hp = core_hp
    def get_position(self, entity_id=None):
        return Position(3, 3) if entity_id is None else self.enemy
    def get_team(self, entity_id=None):
        return 0 if entity_id is None or entity_id == 1 else 1
    def get_nearby_buildings(self): return [1, 9]
    def get_entity_type(self, entity_id):
        return EntityType.CORE if entity_id == 1 else EntityType.GUNNER
    def get_hp(self, entity_id): return self.core_hp
    def get_max_hp(self, entity_id): return 500


def configured_player(ct):
    player = BOT.Player()
    player.mapPf = MapStub()
    player.coveredTiles = lambda _: {(ct.enemy.x, ct.enemy.y)}
    player.buildGunnerFor = lambda *args: (_ for _ in ()).throw(
        AssertionError("covered gun built another counter"))
    player.resumeCommittedRoute = lambda *args: False
    player.routeConveyorTask = lambda *args: False
    player.routeHarvesterTask = lambda *args: False
    player.harvestTask = lambda *args: False
    return player


def test_full_core_releases_economy():
    ct = ControllerStub(core_hp=500)
    player = configured_player(ct)
    player.healCore = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("full core recalled economy builder"))
    repaired = []
    player.repairFormerlyConnectedTrunk = lambda *args: repaired.append(True) or True
    player.runEco(ct)
    assert repaired == [True]


def test_damaged_visible_core_keeps_healing_priority():
    ct = ControllerStub(core_hp=480)
    player = configured_player(ct)
    healed = []
    player.healCore = lambda *args, **kwargs: healed.append(True)
    player.repairFormerlyConnectedTrunk = lambda *args: (_ for _ in ()).throw(
        AssertionError("economy ran before damaged-core healing"))
    player.runEco(ct)
    assert healed == [True]


def test_scope_and_no_fingerprints():
    assert (BOT_DIR / "mapPathfinding.py").read_bytes() == (
        PARENT / "mapPathfinding.py").read_bytes()
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("string.map", "pantheon", "team lazy", "sweden.map"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_full_core_releases_economy()
    test_damaged_visible_core_keeps_healing_priority()
    test_scope_and_no_fingerprints()
