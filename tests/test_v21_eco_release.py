"""Covered home threats must not permanently recall economy builders."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v21_eco_release"
PARENT = ROOT / "bots" / "exp_v20_opportunistic_trunk_repair"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v21_eco_release", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class MapStub:
    teamCore = Position(2, 2)


class ControllerStub:
    enemy = Position(5, 5)

    def get_team(self, entity_id=None): return 0 if entity_id is None else 1
    def get_nearby_buildings(self): return [9]
    def get_entity_type(self, entity_id): return EntityType.GUNNER
    def get_position(self, entity_id=None):
        return Position(3, 3) if entity_id is None else self.enemy


def player_with_stubs(covered):
    player = BOT.Player()
    player.mapPf = MapStub()
    player.coveredTiles = lambda _: covered
    player.healCore = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("covered gun recalled economy builder"))
    player.buildGunnerFor = lambda *args: (_ for _ in ()).throw(
        AssertionError("covered gun built another counter"))
    player.repairFormerlyConnectedTrunk = lambda *args: True
    player.resumeCommittedRoute = lambda *args: False
    player.routeConveyorTask = lambda *args: False
    player.routeHarvesterTask = lambda *args: False
    player.harvestTask = lambda *args: False
    return player


def test_covered_enemy_releases_economy_instead_of_healing():
    ct = ControllerStub()
    player = player_with_stubs({(ct.enemy.x, ct.enemy.y)})
    player.runEco(ct)


def test_uncovered_enemy_still_has_counter_priority():
    ct = ControllerStub()
    player = player_with_stubs(set())
    built = []
    player.buildGunnerFor = lambda controller, target: built.append(target) or True
    player.repairFormerlyConnectedTrunk = lambda *args: (_ for _ in ()).throw(
        AssertionError("economy ran before uncovered threat was handled"))
    player.runEco(ct)
    assert built == [ct.enemy]


def test_scope_is_one_role_ownership_change():
    assert (BOT_DIR / "mapPathfinding.py").read_bytes() == (
        PARENT / "mapPathfinding.py").read_bytes()
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("string.map", "pantheon", "team lazy", "sweden.map"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_covered_enemy_releases_economy_instead_of_healing()
    test_uncovered_enemy_still_has_counter_priority()
    test_scope_is_one_role_ownership_change()
