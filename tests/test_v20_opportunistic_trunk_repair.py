"""Deterministic checks for bounded repair of formerly productive edges."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v20_opportunistic_trunk_repair"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v20_opportunistic_trunk_repair", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def key(pos):
    return pos.x * 32 + pos.y


class MapStub:
    teamCore = Position(5, 5)

    def __init__(self, conv_dirs=None, conv_safe=None):
        self.conv_dirs = conv_dirs or {}
        self.conv_safe = conv_safe or {}
        self.moved = None

    def classifyConveyors(self, ct, team):
        return self.conv_dirs, {}, self.conv_safe

    def moveTo(self, ct, target):
        self.moved = target


class ControllerStub:
    def __init__(self):
        self.store = [0] * 16
        self.built = None
        self.round = 100
        self.entities = {}

    def get_current_round(self): return self.round
    def get_id(self): return 17
    def get_team(self, entity_id=None): return 0
    def is_in_vision(self, pos): return 0 <= pos.x < 10 and 0 <= pos.y < 10
    def get_tile_building_id(self, pos): return self.entities.get(pos)
    def get_entity_type(self, entity_id): return EntityType.CONVEYOR
    def get_direction(self, entity_id): return Direction.EAST
    def read_store(self, slot): return self.store[slot]
    def write_store(self, slot, value): self.store[slot] = value
    def can_build_conveyor(self, pos, direction): return pos == Position(4, 5)
    def build_conveyor(self, pos, direction): self.built = (pos, direction)


def live_upstream():
    upstream = Position(3, 5)
    return {key(upstream): [upstream, Direction.EAST, True]}


def test_missing_edge_requires_live_upstream_and_proven_downstream():
    player = BOT.Player()
    player.mapW = player.mapH = 10
    player.mapPf = MapStub()
    player.knownConnectedConveyors[key(Position(4, 5))] = (
        Position(4, 5), Direction.EAST)
    ct = ControllerStub()
    assert player.repairCandidate(ct, Position(2, 5), 0, live_upstream(), {}) == (
        Position(4, 5), Direction.EAST)
    assert player.repairCandidate(ct, Position(2, 5), 0, {}, {}) is None

    # A remembered branch whose output is not currently proven never becomes
    # a repair target merely because it used to exist.
    player.knownConnectedConveyors[key(Position(4, 3))] = (
        Position(4, 3), Direction.EAST)
    branch_upstream = Position(3, 3)
    branch_dirs = {key(branch_upstream): [branch_upstream, Direction.EAST, False]}
    candidate = player.repairCandidate(ct, Position(4, 2), 0, branch_dirs, {})
    assert candidate is None


def test_repairs_exact_remembered_facing():
    conv_dirs = live_upstream()
    player = BOT.Player()
    player.mapW = player.mapH = 10
    player.mapPf = MapStub(conv_dirs, {})
    player.knownConnectedConveyors[key(Position(4, 5))] = (
        Position(4, 5), Direction.EAST)
    ct = ControllerStub()
    assert player.repairFormerlyConnectedTrunk(ct, Position(3, 4), 0)
    assert ct.built == (Position(4, 5), Direction.EAST)


def test_never_walks_or_claims_when_edge_is_not_immediately_buildable():
    conv_dirs = live_upstream()
    player = BOT.Player()
    player.mapW = player.mapH = 10
    player.mapPf = MapStub(conv_dirs, {})
    player.knownConnectedConveyors[key(Position(4, 5))] = (
        Position(4, 5), Direction.EAST)
    ct = ControllerStub()
    ct.can_build_conveyor = lambda pos, direction: False
    assert not player.repairFormerlyConnectedTrunk(ct, Position(1, 1), 0)
    assert player.mapPf.moved is None


if __name__ == "__main__":
    test_missing_edge_requires_live_upstream_and_proven_downstream()
    test_repairs_exact_remembered_facing()
    test_never_walks_or_claims_when_edge_is_not_immediately_buildable()
