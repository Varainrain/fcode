"""Deterministic tests for the dynamic multi-front allocator."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_dynamic_fronts"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("dynamic_fronts", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def test_pressure_gap_sizes_front_without_consuming_local_economy():
    assert BOT.required_defense_fronts(0, 0, 5) == 0
    assert BOT.required_defense_fronts(1, 0, 5) == 1
    assert BOT.required_defense_fronts(3, 0, 5) == 3
    assert BOT.required_defense_fronts(5, 0, 4) == 2
    assert BOT.required_defense_fronts(3, 2, 5) == 2


def test_fronts_are_distinct_and_siegers_are_last_resort():
    candidates = [
        (10, Position(1, 1)),
        (11, Position(8, 8)),
        (12, Position(2, 2)),
        (13, Position(7, 7)),
        (14, Position(4, 4)),
    ]
    threats = [
        (100, Position(0, 0)),
        (101, Position(9, 9)),
        (102, Position(5, 5)),
    ]
    result = BOT.choose_defense_fronts(
        candidates, {10, 11}, threats, {100: 0, 101: 0, 102: 0})
    assert len(result) == 3
    assert len({builder for builder, _, _ in result}) == 3
    assert len({threat for _, threat, _ in result}) == 3
    assert {builder for builder, _, _ in result}.isdisjoint({10, 11})


def test_existing_coverage_reduces_assignment_count_and_priority():
    candidates = [
        (1, Position(1, 1)), (2, Position(8, 8)),
        (3, Position(5, 5)), (4, Position(4, 4)),
    ]
    threats = [(20, Position(0, 0)), (21, Position(9, 9))]
    result = BOT.choose_defense_fronts(
        candidates, set(), threats, {20: 2, 21: 0})
    assert len(result) == 1
    assert result[0][1] == 21


def test_protocol_slots_do_not_overlap_enemy_core():
    assert set(BOT.DEFENDER_ID_SLOTS).isdisjoint(
        BOT.DEFENDER_TARGET_SLOTS)
    assert BOT.SLOT_ENEMY_CORE not in BOT.DEFENDER_ID_SLOTS
    assert BOT.SLOT_ENEMY_CORE not in BOT.DEFENDER_TARGET_SLOTS
    assert BOT.SLOT_DEFENSE_COUNT not in BOT.DEFENDER_ID_SLOTS


def test_no_fingerprints():
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_pressure_gap_sizes_front_without_consuming_local_economy()
    test_fronts_are_distinct_and_siegers_are_last_resort()
    test_existing_coverage_reduces_assignment_count_and_priority()
    test_protocol_slots_do_not_overlap_enemy_core()
    test_no_fingerprints()
