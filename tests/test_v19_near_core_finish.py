"""Checks that only cheap near-core route completions become persistent."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v19_near_core_finish"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v19_near_core_finish", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class MapStub:
    teamCore = Position(7, 2)
    def __init__(self): self.routed = None
    def routeConveyor(self, ct, target): self.routed = target


class MovingMapStub(MapStub):
    def routeConveyor(self, ct, target):
        self.routed = target
        ct.visible = False


class RoundController:
    def get_current_round(self): return 10


class MovingController(RoundController):
    def __init__(self): self.visible = True
    def get_team(self, entity_id=None): return 0
    def get_position(self): return Position(4, 2)
    def is_in_vision(self, target): return self.visible
    def get_tile_building_id(self, target):
        if not self.visible:
            raise AssertionError("post-move out-of-vision query")
        return None


def test_core_footprint_distance_handles_two_by_two_core():
    assert BOT.coreFootprintManhattan(Position(5, 2), Position(7, 2)) == 2
    assert BOT.coreFootprintManhattan(Position(8, 3), Position(7, 2)) == 0


def test_far_route_is_not_committed():
    player = BOT.Player()
    player.mapPf = MapStub()
    target = Position(0, 0)
    assert player.commitRoute(RoundController(), target)
    assert player.mapPf.routed == target
    assert player.routeTarget is None


def test_post_route_move_rechecks_vision_before_tile_query():
    player = BOT.Player()
    player.mapW = player.mapH = 10
    player.mapPf = MovingMapStub()
    player.routeTarget = Position(5, 2)
    player.routeLastProgressRound = 10
    assert player.resumeCommittedRoute(MovingController())
    assert player.routeTarget == Position(5, 2)


if __name__ == "__main__":
    test_core_footprint_distance_handles_two_by_two_core()
    test_far_route_is_not_committed()
    test_post_route_move_rechecks_vision_before_tile_query()
