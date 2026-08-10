"""Deterministic mechanism tests for exp_connected_economy."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fcode import Direction, EntityType, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_connected_economy"


def load_bot():
    sys.path.insert(0, str(BOT_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "connected_economy_main", BOT_DIR / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


BOT = load_bot()


def footprint():
    return BOT.core_footprint_positions(Position(0, 0))


def test_only_actual_facing_chains_are_connected():
    conveyors = {
        Position(2, 0): Direction.WEST,
        Position(3, 0): Direction.WEST,
        # Spatially touches the valid trunk, but points away from it.
        Position(2, 1): Direction.SOUTH,
    }
    connected = BOT.proven_connected_conveyors(conveyors, footprint())
    assert connected == {Position(2, 0), Position(3, 0)}


def test_wrong_facing_harvester_neighbor_is_not_a_root():
    harvester = Position(5, 5)
    conveyors = {
        Position(4, 5): Direction.EAST,   # outputs into the harvester
        Position(5, 4): Direction.WEST,   # accepts from the harvester
    }
    assert BOT.harvester_chain_roots(harvester, conveyors) == [
        Position(5, 4)
    ]


def test_dead_end_is_extended_but_cycle_is_rejected():
    dead_end = {
        Position(5, 5): Direction.WEST,
        Position(4, 5): Direction.WEST,
    }
    assert BOT.trace_conveyor_chain(
        Position(5, 5), dead_end, footprint(), set()
    ) == ("dead_end", Position(3, 5))

    cycle = {
        Position(5, 5): Direction.EAST,
        Position(6, 5): Direction.WEST,
    }
    assert BOT.trace_conveyor_chain(
        Position(5, 5), cycle, footprint(), set()
    ) == ("cycle", None)


class ObservationController:
    def __init__(self):
        self.entities = {}

    def get_tile_building_id(self, position):
        record = self.entities.get(position)
        return None if record is None else record[0]

    def get_team(self, entity_id=None):
        if entity_id is None:
            return 1
        for record in self.entities.values():
            if record[0] == entity_id:
                return record[1]
        raise KeyError(entity_id)

    def get_entity_type(self, entity_id):
        for record in self.entities.values():
            if record[0] == entity_id:
                return record[2]
        raise KeyError(entity_id)

    def get_direction(self, entity_id):
        for record in self.entities.values():
            if record[0] == entity_id:
                return record[3]
        raise KeyError(entity_id)


def test_revisited_tiles_clear_stale_economy_memory():
    pathfinder = BOT.MapPathfinder()
    controller = ObservationController()
    conveyor = Position(3, 3)
    harvester = Position(4, 4)
    controller.entities[conveyor] = (
        10, 1, EntityType.CONVEYOR, Direction.WEST)
    controller.entities[harvester] = (
        11, 1, EntityType.HARVESTER, None)
    pathfinder.observeEconomyTile(controller, conveyor)
    pathfinder.observeEconomyTile(controller, harvester)
    assert pathfinder.knownTeamConveyors[conveyor] == Direction.WEST
    assert harvester in pathfinder.knownTeamHarvesters

    controller.entities.clear()
    pathfinder.observeEconomyTile(controller, conveyor)
    pathfinder.observeEconomyTile(controller, harvester)
    assert conveyor not in pathfinder.knownTeamConveyors
    assert harvester not in pathfinder.knownTeamHarvesters


class CandidateController(ObservationController):
    def __init__(self):
        super().__init__()
        self.builders = {}

    def is_in_vision(self, position):
        return True

    def is_tile_passable(self, position):
        return position not in self.builders

    def get_tile_builder_bot_id(self, position):
        return self.builders.get(position)

    def get_team(self, entity_id=None):
        if entity_id in self.builders.values():
            return 1
        return super().get_team(entity_id)


def test_served_harvester_produces_no_route_work():
    pathfinder = BOT.MapPathfinder()
    pathfinder.teamCore = Position(0, 0)
    pathfinder.mapW = pathfinder.mapH = 12
    harvester = Position(4, 0)
    pathfinder.knownTeamHarvesters = {harvester}
    pathfinder.knownTeamConveyors = {
        Position(3, 0): Direction.WEST,
        Position(2, 0): Direction.WEST,
    }
    controller = CandidateController()
    controller.entities = {
        harvester: (20, 1, EntityType.HARVESTER, None),
        Position(3, 0): (21, 1, EntityType.CONVEYOR, Direction.WEST),
        Position(2, 0): (22, 1, EntityType.CONVEYOR, Direction.WEST),
    }
    assert pathfinder.economyRouteCandidates(controller) == []


def test_wrong_facing_neighbor_does_not_hide_orphan_harvester():
    pathfinder = BOT.MapPathfinder()
    pathfinder.teamCore = Position(0, 0)
    pathfinder.mapW = pathfinder.mapH = 12
    harvester = Position(5, 5)
    wrong = Position(4, 5)
    pathfinder.knownTeamHarvesters = {harvester}
    pathfinder.knownTeamConveyors = {wrong: Direction.EAST}
    controller = CandidateController()
    controller.entities = {
        harvester: (30, 1, EntityType.HARVESTER, None),
        wrong: (31, 1, EntityType.CONVEYOR, Direction.EAST),
    }
    candidates = pathfinder.economyRouteCandidates(controller)
    ends = {candidate[1] for candidate in candidates}
    assert wrong not in ends
    assert ends == {
        Position(5, 4), Position(5, 6), Position(6, 5)
    }


def test_friendly_builder_on_missing_link_keeps_route_candidate_alive():
    pathfinder = BOT.MapPathfinder()
    pathfinder.teamCore = Position(0, 0)
    pathfinder.mapW = pathfinder.mapH = 12
    harvester = Position(5, 5)
    occupied_end = Position(5, 4)
    pathfinder.knownTeamHarvesters = {harvester}
    controller = CandidateController()
    controller.entities = {
        harvester: (40, 1, EntityType.HARVESTER, None),
    }
    controller.builders[occupied_end] = 41
    candidates = pathfinder.economyRouteCandidates(controller)
    assert occupied_end in {candidate[1] for candidate in candidates}


def test_late_repair_is_bounded_and_below_direct_threat_priority():
    allowed = BOT.late_route_repair_allowed
    assert not allowed(79, 500, 1)
    assert allowed(80, BOT.LATE_ROUTE_RESOURCE_FLOOR,
                   BOT.LATE_ROUTE_MAX_LINKS)
    assert not allowed(80, BOT.LATE_ROUTE_RESOURCE_FLOOR - 1, 1)
    assert not allowed(80, 500, BOT.LATE_ROUTE_MAX_LINKS + 1)
    assert BOT.LATE_ROUTE_SCORE_CAP < 10


def test_one_nearest_builder_claims_a_late_repair():
    target = Position(5, 5)
    candidates = [
        (9, Position(3, 5)),
        (7, Position(5, 3)),
        (4, Position(9, 9)),
    ]
    assert BOT.choose_route_repairer(candidates, target) == 7
    assert BOT.choose_route_repairer(candidates, target, {7, 9}) == 4
    assert BOT.choose_route_repairer([], target) is None


def test_experiment_preserves_protocol_and_has_no_fingerprints():
    parent = ROOT / "bots" / "meta-generalist-v1"
    for name in ("initialSpawning.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (parent / name).read_bytes()
    source = "\n".join(
        (BOT_DIR / name).read_text(encoding="utf-8").lower()
        for name in ("main.py", "mapPathfinding.py")
    )
    for fingerprint in ("string.map", "bridge.map", "duel.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_only_actual_facing_chains_are_connected()
    test_wrong_facing_harvester_neighbor_is_not_a_root()
    test_dead_end_is_extended_but_cycle_is_rejected()
    test_revisited_tiles_clear_stale_economy_memory()
    test_served_harvester_produces_no_route_work()
    test_wrong_facing_neighbor_does_not_hide_orphan_harvester()
    test_friendly_builder_on_missing_link_keeps_route_candidate_alive()
    test_late_repair_is_bounded_and_below_direct_threat_priority()
    test_one_nearest_builder_claims_a_late_repair()
    test_experiment_preserves_protocol_and_has_no_fingerprints()
    print("connected economy tests passed")
