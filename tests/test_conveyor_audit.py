"""Topology classification tests for the offline conveyor audit."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conveyor_audit import topology


def record(team, kind, position, facing=None):
    return {
        "alive": True,
        "team": team,
        "type": kind,
        "position": position,
        "facing": facing,
        "born": 1,
    }


def test_cycle_and_backfeed_are_reported_separately():
    entities = {
        1: record(0, "harvester", (4, 4)),
        2: record(0, "conveyor", (3, 4), 3),  # east, into harvester
        3: record(0, "conveyor", (5, 5), 3),
        4: record(0, "conveyor", (6, 5), 5),
        5: record(0, "conveyor", (6, 6), 7),
        6: record(0, "conveyor", (5, 6), 1),
    }
    result = topology((0, 0), entities, 0)
    assert result["cycles"] == 1
    assert result["cycle_conveyors"] == 4
    assert result["backfeed_roots"] == 1
    assert result["served"] == 0


def test_connected_chain_has_no_false_cycle():
    entities = {
        1: record(0, "harvester", (4, 0)),
        2: record(0, "conveyor", (3, 0), 7),
        3: record(0, "conveyor", (2, 0), 7),
    }
    result = topology((0, 0), entities, 0)
    assert result["connected"] == 2
    assert result["served"] == 1
    assert result["cycles"] == 0
    assert result["backfeed_roots"] == 0


if __name__ == "__main__":
    test_cycle_and_backfeed_are_reported_separately()
    test_connected_chain_has_no_false_cycle()
