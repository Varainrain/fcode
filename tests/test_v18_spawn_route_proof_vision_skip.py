"""Regression check for vision-safe defender return planning."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_spawn_route_proof_vision_skip"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location(
    "v18_spawn_route_proof_vision_skip", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class MapStub:
    myNum = 4
    teamCore = Position(2, 2)

    @staticmethod
    def getTileEnv(tile): return 0


class OutOfVisionController:
    def is_in_vision(self, tile): return False
    def get_tile_building_id(self, tile):
        raise AssertionError("out-of-vision occupant query")
    def get_nearby_buildings(self): return []
    def get_team(self, entity_id=None): return 0


def test_distant_defender_approaches_core_without_caching_ring():
    player = BOT.Player()
    player.mapPf = MapStub()
    player.mapW = player.mapH = 10
    assert player.getDefendHome(OutOfVisionController()) == Position(2, 2)
    assert player.defendHome is None


if __name__ == "__main__":
    test_distant_defender_approaches_core_without_caching_ring()
