"""Deterministic tests for the isolated generalist experiments."""

from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def load_bot(bot_name):
    bot_dir = ROOT / "bots" / bot_name
    sys.path.insert(0, str(bot_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            f"{bot_name}_main", bot_dir / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


SPAWN = load_bot("exp_spawn_discipline")
RESPONDER = load_bot("exp_local_responder")
SURGICAL = load_bot("exp_surgical_counter")
STACK = load_bot("exp_generalist_stack")


class FakeNearbyUnits:
    def __init__(self, units):
        self.units = units

    def get_team(self, unit_id=None):
        if unit_id is None:
            return 1
        return self.units[unit_id][0]

    def get_entity_type(self, unit_id):
        return self.units[unit_id][1]

    def get_nearby_units(self):
        return list(self.units)


def test_extra_spawning_stops_at_six_and_resumes_after_dispersal():
    assert SPAWN.extra_spawn_allowed(5)
    assert not SPAWN.extra_spawn_allowed(6)
    assert not SPAWN.extra_spawn_allowed(9)
    assert SPAWN.extra_spawn_allowed(4)


def test_spawn_congestion_counts_only_nearby_friendly_builders():
    units = {
        1: (1, SPAWN.EntityType.CORE),
        2: (1, SPAWN.EntityType.BUILDER_BOT),
        3: (1, SPAWN.EntityType.BUILDER_BOT),
        4: (2, SPAWN.EntityType.BUILDER_BOT),
        5: (1, SPAWN.EntityType.GUNNER),
    }
    assert SPAWN.count_nearby_friendly_builders(
        FakeNearbyUnits(units)) == 2


def test_first_five_opening_block_precedes_congestion_rule():
    source = (
        ROOT / "bots" / "exp_spawn_discipline" / "main.py"
    ).read_text(encoding="utf-8")
    opening = source.index("if self.fiveDirections and len(self.fiveDirections) > 0")
    congestion = source.index(
        "nearby_friendly_builders = count_nearby_friendly_builders(ct)")
    assert opening < congestion
    assert "SLOT_WALLER_ID, spawned_id + 1" in source
    assert "SLOT_SIEGER_1_ID, spawned_id + 1" in source
    assert "SLOT_SIEGER_2_ID, spawned_id + 1" in source


class FakeThreatController:
    def __init__(self):
        self.core = RESPONDER.Position(5, 5)
        self.entities = {
            10: (
                2,
                RESPONDER.EntityType.GUNNER,
                RESPONDER.Position(8, 5),
                RESPONDER.Direction.WEST,
            ),
            11: (
                2,
                RESPONDER.EntityType.SENTINEL,
                RESPONDER.Position(9, 9),
                RESPONDER.Direction.NORTH,
            ),
            12: (
                2,
                RESPONDER.EntityType.BUILDER_BOT,
                RESPONDER.Position(4, 5),
                None,
            ),
        }

    def get_position(self, entity_id=None):
        return self.core if entity_id is None else self.entities[entity_id][2]

    def get_team(self, entity_id=None):
        return 1 if entity_id is None else self.entities[entity_id][0]

    def get_entity_type(self, entity_id):
        return self.entities[entity_id][1]

    def get_direction(self, entity_id):
        return self.entities[entity_id][3]

    def get_nearby_buildings(self):
        return [10, 11]

    def get_nearby_units(self):
        return [10, 11, 12]

    def get_attackable_tiles_from(self, position, facing, entity_type):
        if position == self.entities[10][2]:
            return [RESPONDER.Position(6, 5)]
        return [RESPONDER.Position(9, 8)]


def test_home_threat_detection_is_exact():
    player = RESPONDER.Player()
    threats = player._home_threats(FakeThreatController())
    assert [threat[3] for threat in threats] == [10, 12]


def test_home_defender_selection_prefers_one_non_sieger_then_distance_and_id():
    threat = RESPONDER.Position(5, 5)
    candidates = [
        (20, RESPONDER.Position(5, 4)),
        (21, RESPONDER.Position(6, 5)),
        (22, RESPONDER.Position(8, 8)),
    ]
    assert RESPONDER.choose_home_defender(
        candidates, {20}, threat) == 21
    assert RESPONDER.choose_home_defender(
        candidates, {20, 21}, threat) == 22
    tied = [
        (31, RESPONDER.Position(5, 4)),
        (30, RESPONDER.Position(4, 5)),
    ]
    assert RESPONDER.choose_home_defender(tied, set(), threat) == 30


class FakeAssignmentController:
    def __init__(self):
        self.round = 20
        self.units = {
            20: RESPONDER.Position(4, 5),
            21: RESPONDER.Position(7, 5),
            22: RESPONDER.Position(8, 5),
        }
        self.store = {
            RESPONDER.SLOT_SIEGER_1_ID: 21,
            RESPONDER.SLOT_SIEGER_2_ID: 0,
        }

    def get_current_round(self):
        return self.round

    def get_team(self, entity_id=None):
        return 1

    def get_nearby_units(self):
        return list(self.units)

    def get_entity_type(self, entity_id):
        return RESPONDER.EntityType.BUILDER_BOT

    def get_position(self, entity_id):
        return self.units[entity_id]

    def read_store(self, slot):
        return self.store.get(slot, 0)

    def write_store(self, slot, value):
        self.store[slot] = value


def test_home_assignment_holds_cleans_up_and_reassigns_dead_builder():
    threat = RESPONDER.Position(6, 5)
    threat_record = (0, threat.x, threat.y, 99, threat)
    player = RESPONDER.Player()
    ct = FakeAssignmentController()
    player._home_threats = lambda controller: [threat_record]

    player._assign_home_defender(ct)
    assert ct.store[RESPONDER.SLOT_HOME_DEFENDER_ID] == 22

    del ct.units[21]
    ct.round += 1
    player._assign_home_defender(ct)
    assert ct.store[RESPONDER.SLOT_HOME_DEFENDER_ID] == 23

    player._home_threats = lambda controller: []
    ct.round += RESPONDER.HOME_DEFENDER_HOLD_ROUNDS
    player._assign_home_defender(ct)
    assert ct.store[RESPONDER.SLOT_HOME_DEFENDER_ID] == 23

    ct.round += 1
    player._assign_home_defender(ct)
    assert ct.store[RESPONDER.SLOT_HOME_DEFENDER_ID] == 0
    assert ct.store[RESPONDER.SLOT_HOME_THREAT] == 0


class FakeSurgicalController:
    def __init__(self, position):
        self.position = position
        self.store = {
            SURGICAL.SLOT_SIEGER_1_ID: 8,
            SURGICAL.SLOT_SIEGER_2_ID: 10,
        }
        self.writes = []
        self.built = []

    def get_id(self):
        return 9

    def read_store(self, slot):
        return self.store.get(slot, 0)

    def write_store(self, slot, value):
        self.store[slot] = value
        self.writes.append((slot, value))

    def get_attackable_tiles_from(self, position, facing, entity_type):
        return [SURGICAL.Position(7, 7), SURGICAL.Position(7, 6)]

    def can_act(self):
        return True

    def get_global_resources(self):
        return 500

    def can_build_gunner(self, position, facing):
        return True

    def build_gunner(self, position, facing):
        self.built.append((position, facing))


def test_surgical_counter_uses_safe_direct_plan_and_cleans_target_slot():
    target = SURGICAL.Position(10, 10)
    seat = SURGICAL.Position(8, 8)
    stand = SURGICAL.Position(8, 7)
    facing = SURGICAL.Direction.SOUTHEAST
    plan = ((0, 0, 0, 0, 0), seat, stand, facing)
    player = SURGICAL.Player()
    player._enemy_core_target = lambda: target
    player._direct_siege_plans = lambda ct, loc, tgt: [plan]
    player._visible_defenders = lambda ct: []
    ct = FakeSurgicalController(stand)

    player._run_core_siege(ct, stand)

    assert ct.built == [(seat, facing)]
    assert (
        SURGICAL.SLOT_SIEGER_2_COUNTER_TARGET, 0
    ) in ct.writes


def test_surgical_counter_fallback_only_when_every_direct_plan_is_covered():
    target = SURGICAL.Position(10, 10)
    direct_seat = SURGICAL.Position(7, 7)
    direct_stand = SURGICAL.Position(7, 6)
    direct_facing = SURGICAL.Direction.SOUTHEAST
    direct_plan = (
        (0, 0, 0, 0, 0),
        direct_seat,
        direct_stand,
        direct_facing,
    )
    defender_pos = SURGICAL.Position(9, 9)
    defender = (
        defender_pos.x,
        defender_pos.y,
        70,
        defender_pos,
        SURGICAL.EntityType.GUNNER,
        SURGICAL.Direction.NORTHWEST,
    )
    counter_seat = SURGICAL.Position(8, 6)
    counter_stand = SURGICAL.Position(8, 5)
    counter_facing = SURGICAL.Direction.SOUTHEAST
    player = SURGICAL.Player()
    player._enemy_core_target = lambda: target
    player._direct_siege_plans = lambda ct, loc, tgt: [direct_plan]
    player._visible_defenders = lambda ct: [defender]
    player._friendly_gunner_covers = lambda ct, tgt: False
    player._safe_counter_plan = (
        lambda ct, loc, tgt, unsafe:
        (counter_seat, counter_stand, counter_facing)
    )
    ct = FakeSurgicalController(counter_stand)

    player._run_core_siege(ct, counter_stand)

    assert SURGICAL.direct_plans_all_covered(
        [direct_plan], {direct_seat})
    assert ct.built == [(counter_seat, counter_facing)]
    assert ct.store[SURGICAL.SLOT_SIEGER_2_COUNTER_TARGET] == (
        SURGICAL.pack_position(defender_pos)
    )


def test_generalist_stack_contains_only_the_two_passing_components():
    source = (
        ROOT / "bots" / "exp_generalist_stack" / "main.py"
    ).read_text(encoding="utf-8")
    assert "SLOT_SIEGER_2_COUNTER_TARGET = 13" in source
    assert "SLOT_HOME_DEFENDER_ID = 14" in source
    assert "SLOT_HOME_THREAT = 15" in source
    assert "CORE_BUILDER_CONGESTION_LIMIT" not in source
    assert "SIEGE_STALL_ROUNDS" not in source
    assert "def _assign_home_defender" in source
    assert "def _safe_counter_plan" in source


def test_frozen_generalist_and_separate_archive_identity():
    required = {
        "main.py",
        "initialSpawning.py",
        "mapPathfinding.py",
        "symmetry.py",
    }
    stack = ROOT / "bots" / "exp_generalist_stack"
    frozen = ROOT / "bots" / "generalist-v2"
    for name in required:
        assert (stack / name).read_bytes() == (frozen / name).read_bytes()
    with zipfile.ZipFile(ROOT / "generalist-v2.zip") as archive:
        assert set(archive.namelist()) == required
        for name in required:
            assert archive.read(name) == (frozen / name).read_bytes()
    manifest = json.loads(
        (ROOT / "generalist_v2_results.json").read_text(encoding="utf-8"))
    for name in required:
        assert hashlib.sha256((frozen / name).read_bytes()).hexdigest().upper() == (
            manifest["sha256"][name]
        )
    assert hashlib.sha256(
        (ROOT / "generalist-v2.zip").read_bytes()
    ).hexdigest().upper() == manifest["sha256"]["generalist-v2.zip"]


if __name__ == "__main__":
    test_extra_spawning_stops_at_six_and_resumes_after_dispersal()
    test_spawn_congestion_counts_only_nearby_friendly_builders()
    test_first_five_opening_block_precedes_congestion_rule()
    test_home_threat_detection_is_exact()
    test_home_defender_selection_prefers_one_non_sieger_then_distance_and_id()
    test_home_assignment_holds_cleans_up_and_reassigns_dead_builder()
    test_surgical_counter_uses_safe_direct_plan_and_cleans_target_slot()
    test_surgical_counter_fallback_only_when_every_direct_plan_is_covered()
    test_generalist_stack_contains_only_the_two_passing_components()
    test_frozen_generalist_and_separate_archive_identity()
    print("generalist cycle tests passed")
