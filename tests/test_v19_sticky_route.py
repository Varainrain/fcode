"""Deterministic checks for interrupted-route commitment and expiry."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, EntityType, Position, Team


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v19_sticky_route"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v19_sticky_route", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class MapStub:
    teamCore = Position(7, 2)

    def __init__(self): self.routed = None
    def routeConveyor(self, ct, target): self.routed = target
    def moveTo(self, ct, target): self.routed = target


class RouteController:
    def __init__(self, round_number=10):
        self.round_number = round_number
        self.buildings = {Position(2, 2): 20, Position(3, 2): 21}

    def get_team(self, entity_id=None): return Team.A
    def get_current_round(self): return self.round_number
    def is_in_vision(self, target): return True
    def get_tile_building_id(self, target): return self.buildings.get(target)
    def get_entity_type(self, entity_id): return EntityType.CONVEYOR
    def get_direction(self, entity_id): return Direction.EAST
    def get_position(self): return Position(1, 2)


def make_player():
    player = BOT.Player()
    player.mapW = player.mapH = 10
    player.mapPf = MapStub()
    return player


def test_commitment_skips_built_suffix_and_targets_first_gap():
    player = make_player()
    player.routeTarget = Position(2, 2)
    ct = RouteController()
    assert player.resumeCommittedRoute(ct)
    assert player.mapPf.routed == Position(4, 2)
    assert player.routeTarget == Position(4, 2)


def test_commitment_expires_after_bounded_no_progress():
    player = make_player()
    player.routeTarget = Position(5, 5)
    player.routeBestDistance = 1
    player.routeLastProgressRound = 1
    ct = RouteController(round_number=1 + BOT.ROUTE_STALL_ROUNDS)
    assert not player.resumeCommittedRoute(ct)
    assert player.routeTarget is None
    assert player.mapPf.routed is None


if __name__ == "__main__":
    test_commitment_skips_built_suffix_and_targets_first_gap()
    test_commitment_expires_after_bounded_no_progress()
