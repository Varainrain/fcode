"""Deterministic tests for the replay-driven adaptive siege stage."""

from pathlib import Path
import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[1]


def load_bot():
    bot_dir = ROOT / "bots" / "exp_adaptive_siege"
    sys.path.insert(0, str(bot_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "exp_adaptive_siege_main", bot_dir / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


BOT = load_bot()


class DummyPathfinder:
    def __init__(self):
        self.moves = []

    def moveTo(self, ct, target):
        self.moves.append(target)


class FakeController:
    def __init__(self, position, nearby, fire_plans=None, unsafe=None):
        self.position = position
        self.nearby = list(nearby)
        self.fire_plans = set(fire_plans or ())
        self.unsafe = dict(unsafe or {})
        self.buildings = {}
        self.teams = {}
        self.types = {}
        self.hp = {}
        self.max_hp = {}
        self.built = []
        self.healed = []
        self.writes = []
        self.round = 100
        self.store = {
            BOT.SLOT_SIEGER_1_ID: 8,
            BOT.SLOT_SIEGER_2_ID: 10,
        }
        self.entity_id = 7

    def get_position(self, entity_id=None):
        return self.position

    def get_nearby_tiles(self):
        return self.nearby

    def get_tile_env(self, position):
        return BOT.Environment.EMPTY

    def get_tile_building_id(self, position):
        return self.buildings.get(position)

    def get_tile_builder_bot_id(self, position):
        return None

    def is_in_vision(self, position):
        return True

    def is_tile_passable(self, position):
        return True

    def can_fire_from(self, position, facing, turret_type, target):
        return (position, facing, turret_type, target) in self.fire_plans

    def get_attackable_tiles_from(self, position, facing, turret_type):
        return self.unsafe.get((position, facing, turret_type), [])

    def get_team(self, entity_id=None):
        if entity_id is None:
            return 1
        return self.teams[entity_id]

    def get_entity_type(self, entity_id=None):
        return self.types[entity_id]

    def get_hp(self, entity_id=None):
        return self.hp[entity_id]

    def get_max_hp(self, entity_id=None):
        return self.max_hp[entity_id]

    def can_heal(self, position):
        return True

    def heal(self, position):
        self.healed.append(position)

    def can_act(self):
        return True

    def get_global_resources(self):
        return 500

    def can_build_gunner(self, position, facing):
        return self.get_tile_building_id(position) is None

    def build_gunner(self, position, facing):
        self.built.append((position, facing))
        building_id = 99
        self.buildings[position] = building_id
        self.teams[building_id] = 1
        self.types[building_id] = BOT.EntityType.GUNNER
        self.hp[building_id] = 40
        self.max_hp[building_id] = 40
        return building_id

    def get_current_round(self):
        return self.round

    def get_id(self):
        return self.entity_id

    def read_store(self, slot):
        return self.store.get(slot, 0)

    def write_store(self, slot, value):
        self.writes.append((slot, value))
        self.store[slot] = value


def fresh_player():
    player = BOT.Player()
    player.mapW = 20
    player.mapH = 20
    player.mapPf = DummyPathfinder()
    return player


def test_undefended_core_selects_direct_firing_seat():
    target = BOT.Position(10, 10)
    seat = BOT.Position(8, 8)
    stand = seat.add(BOT.Direction.NORTH)
    facing = BOT.Direction.SOUTHEAST
    ct = FakeController(
        stand,
        [seat, stand],
        {(seat, facing, BOT.EntityType.GUNNER, target)},
    )
    player = fresh_player()
    player.enemyCorePos = target

    player._run_direct_core_siege(ct, stand, target)

    assert ct.built == [(seat, facing)]


def test_one_and_three_defenders_split_sieger_roles():
    assert not BOT.siege_role_counters(1, 0)
    assert not BOT.siege_role_counters(2, 0)
    assert not BOT.siege_role_counters(1, 1)
    assert BOT.siege_role_counters(2, 1)
    assert BOT.siege_role_counters(1, 3)
    assert BOT.siege_role_counters(2, 3)


def test_counter_plan_rejects_unsafe_seat_and_builder_stand():
    target = BOT.Position(10, 10)
    defender = BOT.Position(9, 10)
    defender_facing = BOT.Direction.WEST
    unsafe_seat = BOT.Position(7, 10)
    unsafe_stand = unsafe_seat.add(BOT.Direction.NORTH)
    safe_seat = BOT.Position(8, 8)
    safe_stand = safe_seat.add(BOT.Direction.NORTH)
    firing = BOT.Direction.SOUTHEAST
    ct = FakeController(
        safe_stand,
        [unsafe_seat, unsafe_stand, safe_seat, safe_stand],
        {
            (unsafe_seat, firing, BOT.EntityType.GUNNER, target),
            (safe_seat, firing, BOT.EntityType.GUNNER, target),
        },
        {
            (defender, defender_facing, BOT.EntityType.GUNNER):
                [unsafe_seat, unsafe_stand],
        },
    )
    defenders = [(
        defender.x,
        defender.y,
        40,
        defender,
        BOT.EntityType.GUNNER,
        defender_facing,
    )]
    player = fresh_player()

    plan = player._counter_plan(ct, safe_stand, target, defenders)

    assert plan == (safe_seat, safe_stand, firing)


def test_counter_gunner_is_maintained_and_healed_before_retargeting():
    target = BOT.Position(10, 10)
    seat = BOT.Position(8, 8)
    stand = seat.add(BOT.Direction.NORTH)
    facing = BOT.Direction.SOUTHEAST
    ct = FakeController(stand, [seat, stand])
    ct.buildings[seat] = 55
    ct.teams[55] = 1
    ct.types[55] = BOT.EntityType.GUNNER
    ct.hp[55] = 24
    ct.max_hp[55] = 40
    selected = (
        target.x,
        target.y,
        70,
        target,
        BOT.EntityType.GUNNER,
        BOT.Direction.WEST,
    )
    player = fresh_player()
    player._counterTarget = target
    player._counterSeat = seat
    player._counterStand = stand
    player._counterFacing = facing

    player._run_counter_battery(ct, stand, selected, [selected])

    assert ct.healed == [seat]
    assert ct.built == []
    assert player.mapPf.moves == []


def test_stall_pauses_for_32_rounds_then_allows_retry():
    objective = BOT.Position(10, 10)
    ct = FakeController(BOT.Position(5, 5), [])
    player = fresh_player()

    assert player._update_siege_progress(ct, objective, 3, 500)
    for _ in range(BOT.SIEGE_STALL_ROUNDS - 1):
        ct.round += 1
        assert player._update_siege_progress(ct, objective, 3, 500)
    ct.round += 1
    assert not player._update_siege_progress(ct, objective, 3, 500)
    pause_started = ct.round

    assert player._siegePauseUntil == pause_started + 32
    assert pause_started + 31 < player._siegePauseUntil
    assert pause_started + 32 >= player._siegePauseUntil
    assert (BOT.SLOT_SIEGER_1_TARGET, 0) in ct.writes


if __name__ == "__main__":
    test_undefended_core_selects_direct_firing_seat()
    test_one_and_three_defenders_split_sieger_roles()
    test_counter_plan_rejects_unsafe_seat_and_builder_stand()
    test_counter_gunner_is_maintained_and_healed_before_retargeting()
    test_stall_pauses_for_32_rounds_then_allows_retry()
    print("adaptive siege tests passed")
