"""Deterministic checks for immediate-buildable siege-seat preference."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, Environment, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_spawn_immediate_seat"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v18_spawn_immediate_seat", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class SeatController:
    def __init__(self, blocked_builder=None, buildable=None):
        self.blocked_builder = blocked_builder
        self.buildable = buildable

    def get_position(self): return Position(2, 2)
    def is_in_vision(self, tile): return True
    def get_tile_building_id(self, tile): return None
    def get_tile_builder_bot_id(self, tile):
        return 9 if tile == self.blocked_builder else None
    def get_tile_env(self, tile): return Environment.EMPTY
    def can_build_gunner(self, tile, direction): return tile == self.buildable


def make_player(candidates, coverage=None):
    player = BOT.Player()
    player.mapW = player.mapH = 10
    player.mapPf.enemyCorePos = Position(7, 7)
    player.getAttackableTiles = lambda _: candidates
    player.enemyTurretCoverage = lambda _: coverage or {}
    return player


def test_immediate_legal_seat_beats_remote_uncovered_plan():
    immediate = (Position(2, 1), Direction.SOUTH)
    remote = (Position(5, 5), Direction.SOUTHEAST)
    player = make_player([remote, immediate], {(2, 1): 1})
    assert player.findGunnerSpot(SeatController(buildable=immediate[0])) == immediate


def test_builder_occupied_seat_is_rejected():
    blocked = (Position(2, 1), Direction.SOUTH)
    open_seat = (Position(3, 2), Direction.EAST)
    player = make_player([blocked, open_seat])
    assert player.findGunnerSpot(
        SeatController(blocked_builder=blocked[0], buildable=open_seat[0])) == open_seat


if __name__ == "__main__":
    test_immediate_legal_seat_beats_remote_uncovered_plan()
    test_builder_occupied_seat_is_rejected()
