"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; the engine calls run() once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""

import random

from fcode import Controller, Direction, EntityType, Environment, Position
from symmetry import SymmetryTracker

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]

from mapPathfinding import *
from initialSpawning import *
anglePerDir = [
    135, 108, 162, 90,
    45, 72, 18, 0,
    315, 288, 342, 270,
    225, 252, 198, 180
]
spawnPoints = [
    Position(-1, -1), Position(0, -1), Position(-1, 0), Position(0, -1), # tL
    Position(1, -1), Position(0, -1), Position(1, 0), Position(1, 0), # tR
    Position(1, 1), Position(0, 1), Position(1, 0), Position(0, 1), # bR
    Position(-1, 1), Position(0, 1), Position(-1, 0), Position(-1, 0) # bL
]
directionMoves = [
    Position(-6, -6), Position(-2, -6), Position(-6, -2), Position(0, -6), # tL
    Position(6, -6), Position(2, -6), Position(6, -2), Position(6, 0), # tR
    Position(6, 6), Position(2, 6), Position(6, 2), Position(0, 6), # bR
    Position(-6, 6), Position(-2, 6), Position(-6, 2), Position(-6, 0) # bL
]
gunnerAttacks = [
    Position(0, 1), Position(0, 2), Position(0, 3),
    Position(0, -1), Position(0, -2), Position(0, -3),
    Position(-1, 0), Position(-2, 0), Position(-3, 0),
    Position(1, 0), Position(2, 0), Position(3, 0),
    Position(-1, 1), Position(-2, 2),
    Position(-1, -1), Position(-2, -2),
    Position(1, 1), Position(2, 2),
    Position(1, -1), Position(2, -2)
]
# slot 0 numSpawned, slot 1-6 map sharing, slot 7 initial target
SLOT_WALLER_ID = 8
SLOT_SIEGER_1_ID = 9
SLOT_SIEGER_2_ID = 10
SLOT_ENEMY_CORE = 11
SLOT_RECALL = 12
SLOT_SIEGER_2_COUNTER_TARGET = 13
SLOT_HOME_DEFENDER_ID = 14
SLOT_HOME_THREAT = 15
SIEGE_START = 45
SIEGE_TITANIUM_FLOOR = 120
# PORTED FROM THE TEAM'S v6 (_OogwayBest), which is the only bot any of us has
# fielded that beats Pantheon: 10-5 (67%) live, where our v2 went 1-14 (7%) and
# v3 went 1-19 (5%). Pantheon wins 86% of its games by core destruction at a
# median of t50, rushing ~18 guns at the core; a single designated home defender
# plus a bounded countertrade - all this lineage has - does not answer that.
# v6's answer is a TEAM-WIDE RECALL: the core raises a flag when it is genuinely
# hurt and a real shooter is in vision, and everybody comes home. It also
# matches my own measurement that stripping home guns out (exp_core_pressure)
# cost 9 points against a rusher.
# Both conditions matter. HP alone would recall on chip damage; a threat alone
# would recall on every scout that wanders past.
RECALL_CORE_HP = 400
# Traced builder-by-builder from the 0-5 unrated sweep by Orizon (#3):
#   ORIZON b10: t6 harv, t8 conv, t12 harv, t14 conv, t16 conv -> STOPS FOREVER
#   ORIZON b4:  t30,31,37,43 gunner      b6: t33,34,35 gunner
#   US     b3:  t3 harv ... t25 conv, t42 harv, t44 conv, t46 conv, t49 conv
#   US     b9:  t7 harv, t9 conv, t11 conv, t25 GUNNER, t50 harv, t52 conv
# Their economy stops at t16 and everything after is guns: 14 built, 10.4 landed
# on our core. Ours never stops - 18.4 conveyors a game, 5 guns, 1.0 on target -
# and builder 9 literally builds a gun and then goes back to harvesting.
# This is a TRANSITION, not an allocation, which is why exp_phase (role cadre)
# and spar_pantheon (economy damped from t0) both missed it: the economy has to
# be built FULLY and then abandoned.
ECON_CUTOFF = 40
# PRE-ARMOUR, measured from The Flotte Experience (#5), who beat us 22-3:
# 100% of their 28 barriers across 5 games sat within 4 tiles of their OWN core,
# laid from t4 by a dedicated builder, before any threat existed. In the game I
# traced we built ELEVEN gunners starting t13 to their eight from t18 and still
# lost 5-0 - our guns need seats at range 4-6 from their core and those tiles
# were occupied.
# Our waller already walls manhattan 1 with conveyors, which blocks adjacency but
# not the FIRING SEATS. This adds the seat zone. 3 Ti for 30 HP is the cheapest
# denial in the game, and per the team's own note our barriers are passable to
# our own units, so it costs us no movement.
# This is NOT aegis-v1 or bastion: both were REACTIVE armour built after a
# threat appeared. This is pre-placed, which is the whole point.
ARMOR_MAX = 14
ARMOR_MIN_D = 2
ARMOR_MAX_D = 5
HOME_DEFENDER_HOLD_ROUNDS = 5


def pack_position(pos: Position) -> int:
    return ((pos.x + 1) << 6) | (pos.y + 1)


def unpack_position(value: int):
    if value == 0:
        return None
    return Position((value >> 6) - 1, (value & 0x3F) - 1)


def direct_plans_all_covered(plans, unsafe_tiles) -> bool:
    return bool(plans) and all(
        seat in unsafe_tiles or stand in unsafe_tiles
        for _, seat, stand, _ in plans
    )


def home_counter_budget_allows(resources: int, bounded_trade: bool) -> bool:
    return bounded_trade or resources > SIEGE_TITANIUM_FLOOR


def core_footprint(core: Position):
    return [
        Position(core.x + dx, core.y + dy)
        for dx in (0, 1) for dy in (0, 1)
    ]


def adjacent_to_core_footprint(position: Position, core: Position) -> bool:
    if position in core_footprint(core):
        return False
    return (
        core.x - 1 <= position.x <= core.x + 2
        and core.y - 1 <= position.y <= core.y + 2
    )


def choose_home_defender(candidates, sieger_ids, threat: Position):
    """Pick one nearby builder: non-sieger, distance, then entity ID."""
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            1 if item[0] in sieger_ids else 0,
            item[1].distance_squared(threat),
            item[0],
        ),
    )[0]


class Player:
    def __init__(self):
        self.mapPf = MapPathfinder()
        self.initSpawn = initialSpawn()
        self.numSpawned = 0
        self.fiveDirections = None
        self.initTarget = None
        self.turnsAlive = 0
        self.attackBan = 0
        self.mapW = None
        self.mapH = None
        self._wallSet = None  # deny tiles around our core, computed once
        self.symmetry = None
        self.symmetryVersion = 0
        self.enemyCorePos = None
        self.siegeCommitted = False
        self._homeDefenderId = None
        self._homeThreatPos = None
        self._homeThreatLastSeen = None

    def runCore(self, ct: Controller) -> None:
        if self.numSpawned == 0:
           self.fiveDirections =  self.initSpawn.setBestFive(ct)
           ct.draw_indicator_dot(Position(0, 0), 204, 23, 123)
        if self.fiveDirections and len(self.fiveDirections) > 0: # only the first 5 bots spawned should be there
            spawnAngle = self.fiveDirections[0]
            index = anglePerDir.index(spawnAngle)
            myLoc = ct.get_position()
            tL = myLoc
            tR = myLoc.add(Direction.EAST)
            bL = myLoc.add(Direction.SOUTH)
            bR = myLoc.add(Direction.SOUTH).add(Direction.EAST)
            coreCorners = [tL, tR, bR, bL]

            spawnPos = Position(
                coreCorners[index // 4].x + spawnPoints[index].x,
                coreCorners[index // 4].y + spawnPoints[index].y
            )
            target = Position(spawnPos.x + directionMoves[index].x, spawnPos.y + directionMoves[index].y)
            target = Position(
                max(0, min(target.x, self.mapW - 1)),
                max(0, min(target.y, self.mapH - 1))
            )
            if ct.can_spawn(spawnPos):
                spawned_id = ct.spawn_builder(spawnPos)
                if self.numSpawned == 0:
                    ct.write_store(SLOT_WALLER_ID, spawned_id + 1)
                elif self.numSpawned == 1:
                    ct.write_store(SLOT_SIEGER_1_ID, spawned_id + 1)
                elif self.numSpawned == 2:
                    ct.write_store(SLOT_SIEGER_2_ID, spawned_id + 1)
                self.numSpawned += 1
                ct.write_store(0, self.numSpawned )
                ct.write_store(7, target.x * 32 + target.y) #
                self.fiveDirections.remove(spawnAngle) # so it doesnt spawn in the same spot twice.
        globalAmmo = ct.get_global_ammo()
        globalTitanium = ct.get_global_resources()

        if globalTitanium > 80 + 60 * self.numSpawned:
            for i in ct.get_nearby_tiles():
                if ct.can_spawn(i):
                    ct.spawn_builder(i)
                    corners = [Position(0, 0), Position(self.mapW - 1, 0), Position(0, self.mapH - 1), Position(self.mapW - 1, self.mapH - 1)]
                    corners.sort(key=lambda corner: corner.distance_squared(ct.get_position()))
                    ct.write_store(7, corners[0].x * 32 + corners[0].y)
                    break
        if globalAmmo < 20 and globalTitanium > 100:
            if ct.can_convert_ammo(20 - globalAmmo):
                ct.convert_ammo(20 - globalAmmo)
        # RECALL: hurt core AND a real shooter in vision, not either alone.
        under_attack = (ct.get_hp() < RECALL_CORE_HP
                        and bool(self._home_threats(ct)))
        ct.write_store(SLOT_RECALL, 1 if under_attack else 0)
        self._assign_home_defender(ct)

    def run(self, ct: Controller) -> None:
        # dev26: an uncaught exception PERMANENTLY destroys this unit (a
        # CPU timeout only skips the turn) — one bad tile query must never
        # cost a unit
        try:
            if self.mapW is None:
                self.mapH = ct.get_map_height()
                self.mapW = ct.get_map_width()
                self.symmetry = SymmetryTracker(self.mapW, self.mapH)
            etype = ct.get_entity_type()
            if etype == EntityType.CORE:
                self.runCore(ct)
            elif etype == EntityType.BUILDER_BOT:
                self.builderBot(ct)
            elif etype == EntityType.GUNNER:
                self.runGunner(ct)
        except Exception:
            pass
    def builderBot(self, ct: Controller):
        myLoc = ct.get_position()
        self.numSpawned = ct.read_store(0)
        self.mapPf.setupMap(ct)
        self._update_enemy_core(ct)
        if self.initTarget is None: # set initial target for the first explore
            compact = ct.read_store(7)
            self.initTarget = Position(compact // 32, compact % 32)
        self.turnsAlive += 1
        if self._is_home_defender(ct):
            threat = unpack_position(ct.read_store(SLOT_HOME_THREAT))
            if threat is not None:
                self._run_home_defense(ct, myLoc, threat)
                return
        # WALL DUTY: the core publishes the first builder's exact entity ID.
        # during rounds 6-45, then rejoins normal life. Skerry t55 autopsy:
        # the passive wall needs foot traffic near the core, and on econ-
        # spread maps every builder leaves instantly — zero wall, doorstep
        # gunners at t29. One dedicated builder for ~40 rounds is bounded
        # (the all-crew wall STATE starved the econ, 32% gate). Duty is
        # Store counters and global entity-id thresholds are not stable role
        # assignments; the core writes the ID returned by spawn_builder().
        if (self._is_waller(ct)
                and 5 < ct.get_current_round() <= 60
                and self.mapPf.teamCore is not None):
            # FULL WALL DUTY — the measured design space: full duty = 85%
            # vs the wave meta / 44% mirror; watchman = too late always;
            # micro-duty = wave sidesteps (t62 kills). This bot is the
            # ANTI-RUSH SPECIALIST; its sibling oogerebus is the
            # mirror-strong generalist. Field per expected opponent.
            if self._pre_armor(ct, myLoc):
                return
            if self.wallDuty(ct, myLoc):
                return
        # VARIANT B: dispatch on state, not on a round number. exp_early_siege
        # moved SIEGE_START 45 -> 25 and bought 26 turns (first gun t84 -> t58),
        # but the ladder's top two land theirs at t19-t24 and the rest of our
        # gap is TRAVEL: the siegers still start at home and walk 25-30 tiles.
        # The only honest trigger is "we know where their core is and we can
        # afford a gun" - both true from roughly t5 via the symmetry tracker.
        # The titanium floor is unchanged, so this is earlier, not cheaper.
        if (self._is_sieger(ct)
                and (self.siegeCommitted
                     or (self._enemy_core_target() is not None
                         and ct.get_global_resources()
                         > SIEGE_TITANIUM_FLOOR))):
            self.siegeCommitted = True
            self._run_core_siege(ct, myLoc)
            return
        self.runBestState(ct, myLoc)
        # PASSIVE WALL (the kfort lesson, integrated the right way this
        # time): walling is a SIDE EFFECT of a spare action next to a deny
        # tile, never a destination. oogwip3/4 made it a state and starved
        # the economy (32%/46% gates) — this version costs zero movement
        # and zero state priority by construction.
        self.passiveWall(ct, ct.get_position())

    def _update_enemy_core(self, ct: Controller) -> None:
        if self.mapPf.mapChanged:
            self.symmetryVersion += 1
        if self.mapPf.teamCore is not None:
            self.symmetry.update(
                self.mapPf.fullMap, self.symmetryVersion, self.mapPf.teamCore)

        for building_id in ct.get_nearby_buildings():
            if (ct.get_team(building_id) != ct.get_team()
                    and ct.get_entity_type(building_id) == EntityType.CORE):
                self.enemyCorePos = ct.get_position(building_id)
                ct.write_store(SLOT_ENEMY_CORE, pack_position(self.enemyCorePos))
                return

        shared = unpack_position(ct.read_store(SLOT_ENEMY_CORE))
        if shared is not None:
            self.enemyCorePos = shared

    def _enemy_core_target(self):
        if self.enemyCorePos is not None:
            return self.enemyCorePos
        if self.mapPf.teamCore is None:
            return None
        x, y = self.symmetry.enemy_core(self.mapPf.teamCore)
        return Position(x, y)

    def _is_waller(self, ct: Controller) -> bool:
        assigned = ct.read_store(SLOT_WALLER_ID)
        return assigned != 0 and assigned == ct.get_id() + 1

    def _is_sieger(self, ct: Controller) -> bool:
        encoded_id = ct.get_id() + 1
        return encoded_id in (
            ct.read_store(SLOT_SIEGER_1_ID),
            ct.read_store(SLOT_SIEGER_2_ID),
        )

    def _sieger_role(self, ct: Controller) -> int:
        encoded_id = ct.get_id() + 1
        if encoded_id == ct.read_store(SLOT_SIEGER_1_ID):
            return 1
        if encoded_id == ct.read_store(SLOT_SIEGER_2_ID):
            return 2
        return 0

    def _is_home_defender(self, ct: Controller) -> bool:
        assigned = ct.read_store(SLOT_HOME_DEFENDER_ID)
        return assigned != 0 and assigned == ct.get_id() + 1

    def _home_threats(self, ct: Controller):
        core = ct.get_position()
        core_tiles = set(core_footprint(core))
        my_team = ct.get_team()
        threats = []
        for building_id in ct.get_nearby_buildings():
            if ct.get_team(building_id) == my_team:
                continue
            building_type = ct.get_entity_type(building_id)
            if building_type not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            position = ct.get_position(building_id)
            facing = ct.get_direction(building_id)
            attack_tiles = ct.get_attackable_tiles_from(
                position, facing, building_type)
            if core_tiles.intersection(attack_tiles):
                threats.append((0, position.x, position.y, building_id, position))
        for unit_id in ct.get_nearby_units():
            if (ct.get_team(unit_id) == my_team
                    or ct.get_entity_type(unit_id) != EntityType.BUILDER_BOT):
                continue
            position = ct.get_position(unit_id)
            if adjacent_to_core_footprint(position, core):
                threats.append((1, position.x, position.y, unit_id, position))
        threats.sort()
        return threats

    def _assign_home_defender(self, ct: Controller) -> None:
        threats = self._home_threats(ct)
        current_round = ct.get_current_round()
        if threats:
            self._homeThreatPos = threats[0][4]
            self._homeThreatLastSeen = current_round
        elif (self._homeThreatLastSeen is None
              or current_round - self._homeThreatLastSeen
              > HOME_DEFENDER_HOLD_ROUNDS):
            self._homeDefenderId = None
            self._homeThreatPos = None
            ct.write_store(SLOT_HOME_DEFENDER_ID, 0)
            ct.write_store(SLOT_HOME_THREAT, 0)
            return

        my_team = ct.get_team()
        candidates = []
        for unit_id in ct.get_nearby_units():
            if (ct.get_team(unit_id) == my_team
                    and ct.get_entity_type(unit_id)
                    == EntityType.BUILDER_BOT):
                candidates.append((unit_id, ct.get_position(unit_id)))
        candidate_ids = {item[0] for item in candidates}
        if self._homeDefenderId not in candidate_ids:
            sieger_ids = {
                encoded - 1
                for encoded in (
                    ct.read_store(SLOT_SIEGER_1_ID),
                    ct.read_store(SLOT_SIEGER_2_ID),
                )
                if encoded
            }
            self._homeDefenderId = choose_home_defender(
                candidates, sieger_ids, self._homeThreatPos)
        if self._homeDefenderId is None:
            ct.write_store(SLOT_HOME_DEFENDER_ID, 0)
            ct.write_store(SLOT_HOME_THREAT, 0)
            return
        ct.write_store(SLOT_HOME_DEFENDER_ID, self._homeDefenderId + 1)
        ct.write_store(SLOT_HOME_THREAT, pack_position(self._homeThreatPos))

    def _visible_enemy_attack_tiles(self, ct: Controller):
        unsafe = set()
        my_team = ct.get_team()
        for building_id in ct.get_nearby_buildings():
            if ct.get_team(building_id) == my_team:
                continue
            building_type = ct.get_entity_type(building_id)
            if building_type not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            unsafe.update(ct.get_attackable_tiles_from(
                ct.get_position(building_id),
                ct.get_direction(building_id),
                building_type,
            ))
        return unsafe

    def _safe_home_counter_plan(
            self, ct: Controller, myLoc: Position, threat: Position):
        unsafe = self._visible_enemy_attack_tiles(ct)
        best = None
        for seat in ct.get_nearby_tiles():
            if (seat in unsafe
                    or ct.get_tile_env(seat) != Environment.EMPTY
                    or ct.get_tile_building_id(seat) is not None):
                continue
            for facing_index, facing in enumerate(DIRECTIONS):
                if not ct.can_fire_from(
                        seat, facing, EntityType.GUNNER, threat):
                    continue
                for approach_index, approach in enumerate(CARDINALS):
                    stand = seat.add(approach)
                    if stand in unsafe:
                        continue
                    if not (0 <= stand.x < self.mapW
                            and 0 <= stand.y < self.mapH
                            and ct.is_in_vision(stand)):
                        continue
                    if stand != myLoc:
                        if ct.get_tile_builder_bot_id(stand) is not None:
                            continue
                        if not ct.is_tile_passable(stand):
                            continue
                    key = (
                        abs(myLoc.x - stand.x) + abs(myLoc.y - stand.y),
                        seat.distance_squared(threat),
                        seat.x,
                        seat.y,
                        facing_index,
                        approach_index,
                    )
                    if best is None or key < best[0]:
                        best = (key, seat, stand, facing)
        if best is None:
            return None
        return best[1:]

    def _visible_home_turret_attacks(self, ct: Controller):
        core = self.mapPf.teamCore
        if core is None:
            return []
        core_tiles = set(core_footprint(core))
        my_team = ct.get_team()
        threats = []
        for building_id in ct.get_nearby_buildings():
            if ct.get_team(building_id) == my_team:
                continue
            building_type = ct.get_entity_type(building_id)
            if building_type not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            position = ct.get_position(building_id)
            attack_tiles = set(ct.get_attackable_tiles_from(
                position, ct.get_direction(building_id), building_type))
            if core_tiles.intersection(attack_tiles):
                threats.append((
                    position.x, position.y, building_id, attack_tiles))
        threats.sort(key=lambda item: item[:3])
        return threats

    def _bounded_home_counter_plan(
            self, ct: Controller, myLoc: Position,
            threat: Position, turret_attacks):
        if len(turret_attacks) < 2:
            return None
        unsafe = set().union(
            *(attack_tiles for _, _, _, attack_tiles in turret_attacks))
        best = None
        for seat in ct.get_nearby_tiles():
            if (ct.get_tile_env(seat) != Environment.EMPTY
                    or ct.get_tile_building_id(seat) is not None):
                continue
            seat_exposure = sum(
                seat in attack_tiles
                for _, _, _, attack_tiles in turret_attacks)
            if seat_exposure > 1:
                continue
            for facing_index, facing in enumerate(DIRECTIONS):
                if not ct.can_fire_from(
                        seat, facing, EntityType.GUNNER, threat):
                    continue
                for approach_index, approach in enumerate(CARDINALS):
                    stand = seat.add(approach)
                    if stand in unsafe:
                        continue
                    if not (0 <= stand.x < self.mapW
                            and 0 <= stand.y < self.mapH
                            and ct.is_in_vision(stand)):
                        continue
                    if stand != myLoc:
                        if ct.get_tile_builder_bot_id(stand) is not None:
                            continue
                        if not ct.is_tile_passable(stand):
                            continue
                    key = (
                        seat_exposure,
                        abs(myLoc.x - stand.x) + abs(myLoc.y - stand.y),
                        seat.distance_squared(threat),
                        seat.x,
                        seat.y,
                        facing_index,
                        approach_index,
                    )
                    if best is None or key < best[0]:
                        best = (key, seat, stand, facing)
        if best is None:
            return None
        return best[1:]

    def _friendly_gunner_covers(
            self, ct: Controller, threat: Position) -> bool:
        my_team = ct.get_team()
        for building_id in ct.get_nearby_buildings():
            if (ct.get_team(building_id) != my_team
                    or ct.get_entity_type(building_id)
                    != EntityType.GUNNER):
                continue
            if threat in ct.get_attackable_tiles_from(
                    ct.get_position(building_id),
                    ct.get_direction(building_id),
                    EntityType.GUNNER):
                return True
        return False

    def _heal_or_approach_core(
            self, ct: Controller, myLoc: Position) -> None:
        core = self.mapPf.teamCore
        if core is None:
            return
        for core_tile in core_footprint(core):
            if ct.can_heal(core_tile):
                ct.heal(core_tile)
                return
        ring = []
        for x in range(core.x - 1, core.x + 3):
            for y in range(core.y - 1, core.y + 3):
                position = Position(x, y)
                if not adjacent_to_core_footprint(position, core):
                    continue
                if not (0 <= x < self.mapW and 0 <= y < self.mapH):
                    continue
                if not ct.is_in_vision(position):
                    continue
                if position != myLoc:
                    if ct.get_tile_builder_bot_id(position) is not None:
                        continue
                    if not ct.is_tile_passable(position):
                        continue
                ring.append(position)
        if ring:
            ring.sort(key=lambda p: (
                myLoc.distance_squared(p), p.x, p.y))
            self.mapPf.moveTo(ct, ring[0])

    def _run_home_defense(
            self, ct: Controller, myLoc: Position, threat: Position) -> None:
        if ct.is_in_vision(threat):
            threat_ids = [
                ct.get_tile_building_id(threat),
                ct.get_tile_builder_bot_id(threat),
            ]
            if not any(
                    entity_id is not None
                    and ct.get_team(entity_id) != ct.get_team()
                    for entity_id in threat_ids):
                self._heal_or_approach_core(ct, myLoc)
                return
        if self._friendly_gunner_covers(ct, threat):
            self._heal_or_approach_core(ct, myLoc)
            return
        plan = self._safe_home_counter_plan(ct, myLoc, threat)
        bounded_trade = False
        if plan is None:
            turret_attacks = self._visible_home_turret_attacks(ct)
            plan = self._bounded_home_counter_plan(
                ct, myLoc, threat, turret_attacks)
            bounded_trade = plan is not None
        if (plan is None or not home_counter_budget_allows(
                ct.get_global_resources(), bounded_trade)):
            self._heal_or_approach_core(ct, myLoc)
            return
        seat, stand, facing = plan
        if myLoc != stand:
            self.mapPf.moveTo(ct, stand)
            return
        if ct.can_act() and ct.can_build_gunner(seat, facing):
            ct.build_gunner(seat, facing)

    def _may_attack(self, ct: Controller) -> bool:
        # Preserve one home-side builder without relying on globally
        # interleaved entity IDs.
        return not self._is_waller(ct)

    def _recall_is_up(self, ct: Controller) -> bool:
        return ct.read_store(SLOT_RECALL) == 1

    def _answer_recall(self, ct: Controller, myLoc: Position) -> bool:
        """Go home - but only when there is nothing better to do here.

        exp_recall made this a hard override and lost 6 points to the parent
        (44%, CI 39-49, kills 120-169): it pulled siegers off live seats. v6
        scores retreat at 7-9, deliberately BELOW attack's core-defence ceiling
        of 12, so a unit that can build a killing gunner still builds it. This
        is that priority, expressed in our branch structure instead of a score.
        """
        threat = unpack_position(ct.read_store(SLOT_HOME_THREAT))
        if threat is not None:
            self._run_home_defense(ct, myLoc, threat)
            return True
        if self.mapPf.teamCore is not None:
            self._heal_or_approach_core(ct, myLoc)
            return True
        return False

    def _run_core_siege(self, ct: Controller, myLoc: Position) -> None:
        """Preserve direct siege; role 2 counters only if every plan is covered."""
        target = self._enemy_core_target()
        if target is None:
            return
        plans = self._direct_siege_plans(ct, myLoc, target)
        if self._sieger_role(ct) != 2:
            self._execute_direct_siege_plan(ct, myLoc, target, plans)
            return

        defenders = self._visible_defenders(ct)
        unsafe = set()
        defender_attacks = []
        for defender in defenders:
            attack_tiles = set(ct.get_attackable_tiles_from(
                defender[3], defender[5], defender[4]))
            unsafe.update(attack_tiles)
            defender_attacks.append((defender, attack_tiles))
        safe_plans = [
            plan for plan in plans
            if plan[1] not in unsafe and plan[2] not in unsafe
        ]
        if safe_plans:
            ct.write_store(SLOT_SIEGER_2_COUNTER_TARGET, 0)
            self._execute_direct_siege_plan(
                ct, myLoc, target, safe_plans)
            return
        if not direct_plans_all_covered(plans, unsafe):
            ct.write_store(SLOT_SIEGER_2_COUNTER_TARGET, 0)
            self._execute_direct_siege_plan(ct, myLoc, target, plans)
            return

        covered = []
        for defender, attack_tiles in defender_attacks:
            coverage = sum(
                1 for _, seat, stand, _ in plans
                if seat in attack_tiles or stand in attack_tiles
            )
            if coverage:
                covered.append((
                    -coverage,
                    defender[0],
                    defender[1],
                    defender[2],
                    defender,
                ))
        if not covered:
            ct.write_store(SLOT_SIEGER_2_COUNTER_TARGET, 0)
            self._execute_direct_siege_plan(ct, myLoc, target, plans)
            return
        covered.sort()
        defender_pos = covered[0][4][3]
        if self._friendly_gunner_covers(ct, defender_pos):
            ct.write_store(SLOT_SIEGER_2_COUNTER_TARGET, 0)
            self._execute_direct_siege_plan(ct, myLoc, target, plans)
            return
        counter_plan = self._safe_counter_plan(
            ct, myLoc, defender_pos, unsafe)
        if counter_plan is None:
            ct.write_store(SLOT_SIEGER_2_COUNTER_TARGET, 0)
            self._execute_direct_siege_plan(ct, myLoc, target, plans)
            return
        ct.write_store(
            SLOT_SIEGER_2_COUNTER_TARGET, pack_position(defender_pos))
        self._execute_siege_plan(ct, myLoc, counter_plan)

    def _direct_siege_plans(
            self, ct: Controller, myLoc: Position, target: Position):
        core_tiles = [
            Position(target.x + dx, target.y + dy)
            for dx in (0, 1) for dy in (0, 1)
        ]
        plans = []
        for seat in ct.get_nearby_tiles():
            if ct.get_tile_env(seat) != Environment.EMPTY:
                continue
            if ct.get_tile_building_id(seat) is not None:
                continue
            firing = None
            for facing in DIRECTIONS:
                for core_tile in core_tiles:
                    if ct.can_fire_from(
                            seat, facing, EntityType.GUNNER, core_tile):
                        firing = (facing, core_tile)
                        break
                if firing is not None:
                    break
            if firing is None:
                continue
            facing, core_tile = firing
            diagonal = seat.x != core_tile.x and seat.y != core_tile.y
            for approach in CARDINALS:
                stand = seat.add(approach)
                if not (0 <= stand.x < self.mapW and 0 <= stand.y < self.mapH):
                    continue
                if not ct.is_in_vision(stand):
                    continue
                if stand != myLoc:
                    if ct.get_tile_builder_bot_id(stand) is not None:
                        continue
                    if not ct.is_tile_passable(stand):
                        continue
                key = (
                    0 if diagonal else 1,
                    abs(myLoc.x - stand.x) + abs(myLoc.y - stand.y),
                    seat.distance_squared(target),
                    seat.x,
                    seat.y,
                )
                plans.append((key, seat, stand, facing))
        plans.sort()
        return plans

    def _execute_direct_siege_plan(
            self, ct: Controller, myLoc: Position,
            target: Position, plans) -> None:
        if not plans:
            if self._recall_is_up(ct) and self._answer_recall(ct, myLoc):
                return
            self.mapPf.moveTo(ct, target)
            return
        seat, stand, facing = plans[0][1:]
        if (myLoc != stand and self._recall_is_up(ct)
                and self._answer_recall(ct, myLoc)):
            return               # travelling, not shooting - go home instead
        self._execute_siege_plan(ct, myLoc, plans[0][1:])

    def _execute_siege_plan(self, ct: Controller, myLoc: Position, plan) -> None:
        seat, stand, facing = plan
        if myLoc != stand:
            self.mapPf.moveTo(ct, stand)
            return
        if (ct.can_act()
                and ct.get_global_resources() > SIEGE_TITANIUM_FLOOR
                and ct.can_build_gunner(seat, facing)):
            ct.build_gunner(seat, facing)

    def _visible_defenders(self, ct: Controller):
        my_team = ct.get_team()
        defenders = []
        for building_id in ct.get_nearby_buildings():
            if ct.get_team(building_id) == my_team:
                continue
            building_type = ct.get_entity_type(building_id)
            if building_type not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            position = ct.get_position(building_id)
            defenders.append((
                position.x,
                position.y,
                building_id,
                position,
                building_type,
                ct.get_direction(building_id),
            ))
        defenders.sort()
        return defenders

    def _safe_counter_plan(
            self, ct: Controller, myLoc: Position,
            target: Position, unsafe):
        best = None
        for seat in ct.get_nearby_tiles():
            if (seat in unsafe
                    or ct.get_tile_env(seat) != Environment.EMPTY
                    or ct.get_tile_building_id(seat) is not None):
                continue
            for facing_index, facing in enumerate(DIRECTIONS):
                if not ct.can_fire_from(
                        seat, facing, EntityType.GUNNER, target):
                    continue
                for approach_index, approach in enumerate(CARDINALS):
                    stand = seat.add(approach)
                    if stand in unsafe:
                        continue
                    if not (0 <= stand.x < self.mapW
                            and 0 <= stand.y < self.mapH
                            and ct.is_in_vision(stand)):
                        continue
                    if stand != myLoc:
                        if ct.get_tile_builder_bot_id(stand) is not None:
                            continue
                        if not ct.is_tile_passable(stand):
                            continue
                    key = (
                        abs(myLoc.x - stand.x) + abs(myLoc.y - stand.y),
                        seat.distance_squared(target),
                        seat.x,
                        seat.y,
                        facing_index,
                        approach_index,
                    )
                    if best is None or key < best[0]:
                        best = (key, seat, stand, facing)
        if best is None:
            return None
        return best[1:]

    def _pre_armor(self, ct: Controller, myLoc: Position) -> bool:
        """Deny the enemy their firing seats before they arrive."""
        tc = self.mapPf.teamCore
        eg = self._enemy_core_target()
        if tc is None or eg is None:
            return False
        if getattr(self, "_armorBuilt", 0) >= ARMOR_MAX:
            return False
        core_tiles = [Position(tc.x + dx, tc.y + dy)
                      for dx in (0, 1) for dy in (0, 1)]
        best = None
        for x in range(tc.x - ARMOR_MAX_D, tc.x + ARMOR_MAX_D + 2):
            for y in range(tc.y - ARMOR_MAX_D, tc.y + ARMOR_MAX_D + 2):
                if not (0 <= x < self.mapW and 0 <= y < self.mapH):
                    continue
                seat = Position(x, y)
                d = abs(x - tc.x) + abs(y - tc.y)
                if not (ARMOR_MIN_D <= d <= ARMOR_MAX_D):
                    continue
                # enemy side only - the home ring is the core's heal access
                if abs(x - eg.x) + abs(y - eg.y) > abs(tc.x - eg.x) + abs(tc.y - eg.y):
                    continue
                if not ct.is_in_vision(seat):
                    continue
                if ct.get_tile_building_id(seat) is not None:
                    continue
                # only tiles a gunner could actually shoot our core from
                shoots = False
                for facing in DIRECTIONS:
                    for ct_tile in core_tiles:
                        if ct.can_fire_from(seat, facing, EntityType.GUNNER, ct_tile):
                            shoots = True
                            break
                    if shoots:
                        break
                if not shoots:
                    continue
                key = abs(myLoc.x - x) + abs(myLoc.y - y)
                if best is None or key < best[0]:
                    best = (key, seat)
        if best is None:
            return False
        seat = best[1]
        if ct.can_act() and ct.can_build_barrier(seat):
            ct.build_barrier(seat)
            self._armorBuilt = getattr(self, "_armorBuilt", 0) + 1
            return True
        if best[0] > 1:
            self.mapPf.moveTo(ct, seat)
            return True
        return False

    def wallDuty(self, ct: Controller, myLoc: Position) -> bool:
        """One early builder's bounded job: wall the enemy-side ring with
        core-facing conveyors, then hand back to normal life (returns False
        when done). Home-side ring stays open — those are the core's only
        heal positions (full seal gated 29%)."""
        if getattr(self, "_dutyDone", False):
            return False
        tc = self.mapPf.teamCore
        cx, cy = tc.x, tc.y
        foot = {(cx + a, cy + b) for a in (0, 1) for b in (0, 1)}
        eg = self._enemy_core_target()
        if eg is None:
            return False
        cd = abs(cx + 0.5 - eg.x) + abs(cy + 0.5 - eg.y)
        todo = []
        for x in range(cx - 1, cx + 3):
            for y in range(cy - 1, cy + 3):
                if (x, y) in foot:
                    continue
                if not (0 <= x < self.mapW and 0 <= y < self.mapH):
                    continue
                if abs(x - eg.x) + abs(y - eg.y) > cd:
                    continue  # home side stays open
                p = Position(x, y)
                if not ct.is_in_vision(p):
                    todo.append(p)
                    continue
                if ct.get_tile_building_id(p) is not None:
                    continue
                if self.mapPf.getTileEnv(p) in (1, 2, 3):
                    continue
                todo.append(p)
        # FULL enemy-side ring — measured truth: 3-tile micro-duty just
        # displaced the wave one tile over (8 identical t62 kills); only
        # denying the whole half breaks it (skerry 69%, krb overall 85%)
        todo.sort(key=lambda q: abs(q.x - eg.x) + abs(q.y - eg.y))
        if not todo:
            self._dutyDone = True
            return False
        if ct.get_global_resources() < 15:
            return True   # hold near home while poor rather than wandering
        if ct.can_act():
            for p in todo:
                if abs(myLoc.x - p.x) + abs(myLoc.y - p.y) != 1:
                    continue
                tgt = None
                for d in CARDINALS:
                    n = p.add(d)
                    if (n.x, n.y) in foot:
                        tgt = n
                        break
                if tgt is None:
                    # ring corner: chain into an edge-ring conveyor that
                    # already exists (never create a dead end — trunk trap)
                    for d in CARDINALS:
                        n = p.add(d)
                        if not (0 <= n.x < self.mapW and 0 <= n.y < self.mapH):
                            continue
                        nId = ct.get_tile_building_id(n) if ct.is_in_vision(n) else None
                        if (nId is not None and ct.get_team(nId) == ct.get_team()
                                and ct.get_entity_type(nId) == EntityType.CONVEYOR):
                            tgt = n
                            break
                if tgt is None:
                    continue
                f = p.direction_to(tgt)
                if f in CARDINALS and ct.can_build_conveyor(p, f):
                    ct.build_conveyor(p, f)
                    return True
        todo.sort(key=lambda q: myLoc.distance_squared(q))
        self.mapPf.moveTo(ct, todo[0])
        return True

    def passiveWall(self, ct: Controller, myLoc: Position):
        if not ct.can_act():
            return  # this turn's action went to the real job
        tc = self.mapPf.teamCore
        if tc is None or ct.get_global_resources() < 60:
            return
        if self._wallSet is None:
            cx, cy = tc.x, tc.y
            foot = {(cx + a, cy + b) for a in (0, 1) for b in (0, 1)}
            eg = self._enemy_core_target()
            if eg is None:
                return
            cd = abs(cx + 0.5 - eg.x) + abs(cy + 0.5 - eg.y)
            s = set()
            for x in range(cx - 1, cx + 3):        # enemy-side ring + ties
                for y in range(cy - 1, cy + 3):    # (home side stays open:
                    if (x, y) in foot:             # spawn exit + the only
                        continue                   # core-heal positions)
                    if abs(x - eg.x) + abs(y - eg.y) <= cd:
                        s.add((x, y))
            for o in (0, 1):                       # cardinal rays d2-3
                for d in (2, 3):
                    s.update([(cx - d, cy + o), (cx + 1 + d, cy + o),
                              (cx + o, cy - d), (cx + o, cy + 1 + d)])
            for a in (0, 1):                       # 2-step diagonals (8-way
                for b in (0, 1):                   # facing since 2.3)
                    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                        s.add((cx + a + 2 * dx, cy + b + 2 * dy))
            self._wallSet = {(x, y) for (x, y) in s
                             if 0 <= x < self.mapW and 0 <= y < self.mapH}
        foot = {(tc.x + a, tc.y + b) for a in (0, 1) for b in (0, 1)}
        for d in CARDINALS:
            wp = myLoc.add(d)
            if (wp.x, wp.y) not in self._wallSet:
                continue
            if not ct.is_in_vision(wp) or ct.get_tile_building_id(wp) is not None:
                continue
            if self.mapPf.getTileEnv(wp) in (1, 2, 3):  # ore/wall/blocked
                continue
            # face coreward, and NEVER build a dead end: output must be the
            # core or an existing own conveyor (a dead-end wall conveyor
            # swallows every harvest chain routed into it)
            target = None
            for d2 in CARDINALS:
                nxt = wp.add(d2)
                if (nxt.x, nxt.y) in foot:
                    target = nxt
                    break
            if target is None:
                best = None
                for d2 in CARDINALS:
                    nxt = wp.add(d2)
                    if not (0 <= nxt.x < self.mapW and 0 <= nxt.y < self.mapH):
                        continue
                    if not ct.is_in_vision(nxt):
                        continue
                    nId = ct.get_tile_building_id(nxt)
                    if nId is None or ct.get_team(nId) != ct.get_team():
                        continue
                    if ct.get_entity_type(nId) != EntityType.CONVEYOR:
                        continue
                    dd = abs(nxt.x - tc.x) + abs(nxt.y - tc.y)
                    if best is None or dd < best[0]:
                        best = (dd, nxt)
                if best is not None:
                    target = best[1]
            if target is None:
                continue
            facing = wp.direction_to(target)
            if facing in CARDINALS and ct.can_build_conveyor(wp, facing):
                ct.build_conveyor(wp, facing)
                return
    def runGunner (self, ct: Controller):
        curTarget = ct.get_gunner_target()
        myDir = ct.get_direction()
        myPos = ct.get_position()
        myTeam = ct.get_team()
        if curTarget is not None:
            targetId = ct.get_tile_building_id(curTarget)
            bbId = ct.get_tile_builder_bot_id(curTarget)
            if bbId is not None and ct.get_team(bbId) == myTeam:
                return # dont kill your own bot
            if targetId is not None and ct.get_team(targetId) != ct.get_team():
                if ct.can_fire(curTarget):
                    ct.fire(curTarget)
                    return
        if ct.get_global_resources() > 60:
            bestScore = 0
            bestDir = myDir # so you only rotate when you need to
            for d in DIRECTIONS:
                curScore = 0
                for tile in ct.get_attackable_tiles_from(myPos, d, EntityType.GUNNER):
                    tileId = ct.get_tile_building_id(tile)
                    bbId = ct.get_tile_builder_bot_id(tile)
                    if tileId is not None and ct.get_team(tileId) != myTeam:
                        tType = ct.get_entity_type(tileId)
                        if tType in [EntityType.GUNNER, EntityType.SENTINEL]:
                            curScore += 10
                        elif tType == EntityType.CORE:
                            # A core-capable gun must never rotate back into
                            # mid-map brawling.
                            curScore += 1000
                        elif tType in [EntityType.LAUNCHER, EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER]:
                            curScore += 4
                        else:
                            curScore += 1
                        if bbId is not None and ct.get_team(bbId) != myTeam:
                            curScore += 2
                if curScore > bestScore:
                    bestScore = curScore
                    bestDir = d
            if bestDir != myDir:
                if ct.can_rotate(bestDir):
                    ct.rotate(bestDir)


    def runBestState(self, ct: Controller, myLoc: Position):
        nearbyUnits = ct.get_nearby_entities() # both builder bots and buildings
        myTeam = ct.get_team()

        # attack, max score of 10
        attackScore = 0
        attackPos = None
        if self.attackBan == 0:
            if ct.get_global_resources() > 120 and self._may_attack(ct):
                for b in nearbyUnits: # looks at nearby enemies, and scored on entity type and distance
                    bTeam = ct.get_team(b)
                    buildingScore = 0
                    if bTeam != myTeam:
                        bPos = ct.get_position(b)
                        bType = ct.get_entity_type(b)
                        if bType in [EntityType.GUNNER, EntityType.SENTINEL, EntityType.CORE]:
                            buildingScore = 10
                        elif bType in [EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER]:
                            buildingScore = 8
                        elif bType == EntityType.BUILDER_BOT:
                            buildingScore = 2
                        else:
                            buildingScore = 1
                    else:
                        continue
                    dist = myLoc.distance_squared(bPos)
                    buildingScore = buildingScore * (1 - dist/40)
                    if buildingScore > attackScore:
                        attackScore = buildingScore
                        attackPos = bPos # no need to worry about this not being initialized, as it needs buildingScore > attackScore, so there must be a position
                for b in ct.get_nearby_buildings(5):
                    if ct.get_entity_type(b) == EntityType.GUNNER and ct.get_team(b) == myTeam:
                        attackScore = 0
                        self.attackBan = 4 + (ct.get_id() % 8)
                        break
        else:
            self.attackBan -= 1

        # heal, max score of 8
        healScore = 0
        healPos = None
        for b in nearbyUnits: # scored on how low the unit is, distance, and entity type
            bTeam = ct.get_team(b)
            buildingScore = 0
            if bTeam == myTeam:
                bPos = ct.get_position(b)
                bType = ct.get_entity_type(b)
                if bType in [EntityType.CORE, EntityType.BUILDER_BOT]: # dont waste an entire state on just healing yourself
                    buildingScore = 8
                elif bType in [EntityType.GUNNER, EntityType.SENTINEL]:
                    buildingScore = 6
                elif bType in [EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER]:
                    buildingScore = 4
                else:
                    buildingScore = 2
            else:
                continue
            dist = myLoc.distance_squared(bPos)
            cHP = ct.get_hp(b)
            maxHP = ct.get_max_hp(b)
            mHP = maxHP - cHP
            buildingScore = buildingScore * (1 - dist/120) * (mHP/maxHP)
            if buildingScore > healScore:
                healScore = buildingScore
                healPos = bPos

        # route, max score of 6
        routeScore = 0 # orphan harvesters + unfinished conveyor chains
        routePos = None
        routeDir = None
        mapW = self.mapW
        mapH = self.mapH
        teamCore = self.mapPf.teamCore
        if teamCore is not None:
            for b in nearbyUnits:
                bScore = 0
                bPos = ct.get_position(b)
                bType = ct.get_entity_type(b)
                bDir = None
                endTile = None
                if bType == EntityType.HARVESTER and myLoc.distance_squared(bPos) < 16: # max score of 5 to prioritize cotninueing paths
                    noTeamConv = True
                    workingSpots = []
                    for possibleDir in CARDINALS: # would have named it dir, but thats not allowed
                        endTile = bPos.add(possibleDir)
                        if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and ct.is_tile_passable(endTile):
                            eId = ct.get_tile_building_id(endTile)
                            if eId is None:
                                workingSpots.append(endTile)
                            elif ct.get_team(eId) == myTeam and ct.get_entity_type(eId) == EntityType.CONVEYOR:
                                noTeamConv = False
                    if noTeamConv and len(workingSpots) > 0:
                        workingSpots.sort(key=lambda pos: pos.distance_squared(teamCore))
                        bScore = max(1.6, 5 * max(0, (1 - (workingSpots[0].distance_squared(teamCore) / 100))) * max(0, (1 - myLoc.distance_squared(bPos)/60)))
                        bDir = Direction.CENTRE
                        endTile = workingSpots[0]
                elif bType == EntityType.CONVEYOR:
                    if ct.get_team(b) == myTeam:
                        bDir = ct.get_direction(b)
                        endTile = bPos.add(bDir)
                        if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and ct.is_tile_passable(endTile):
                            eId = ct.get_tile_building_id(endTile)
                            if eId is None:
                                bScore = max(2, 6 * max(0, (1 - (endTile.distance_squared(teamCore) / 120))) * max(0, (1 - myLoc.distance_squared(bPos)/40)))
                if bScore > routeScore:
                    routeScore = bScore
                    routePos = endTile
                    routeDir = bDir

        # harvest, max score of 3
        harvestScore = 0
        harvestPos = None
        if teamCore is not None:
            for tile in ct.get_nearby_tiles():
                if self.mapPf.getTileEnv(tile) == 1: # since it checks all nearby tiles before choosing state, this is fine
                    if ct.get_tile_building_id(tile) is None:
                        dist = teamCore.distance_squared(tile)
                        tileScore = max(1.2, 3 * (1 - dist/160) * (1 - myLoc.distance_squared(tile)/120))
                        if tileScore > harvestScore:
                            harvestPos = tile
                            harvestScore = tileScore


        # explore, max score of 1
        exploreScore = 0
        if ct.get_current_round() < 12:
            explorePos = self.initTarget
            exploreScore = 1
        else:
            explorePos = self.mapPf.returnUnvisited(ct, myLoc)
            if explorePos is not None:
                exploreScore = 1
            else:
                exploreScore = 0.4 # exploring isnt as important then
        # After the cutoff the economy is what it is; every action goes to guns.
        if ct.get_current_round() >= ECON_CUTOFF:
            harvestScore = 0
            routeScore = 0
        stateScores = [attackScore, healScore, harvestScore, routeScore, exploreScore]
        stateScores.sort(key=lambda score: score, reverse=True)
        bestScore = stateScores[0]
        if bestScore == attackScore:
            self.attack(ct, attackPos)
        elif bestScore == healScore:
            self.heal(ct, healPos)
        elif bestScore == routeScore:
            self.route(ct, routePos, routeDir)
        elif bestScore == harvestScore:
            self.harvest(ct, harvestPos)
        else:
            self.explore(ct, explorePos)
    def attack(self, ct: Controller, attackPos: Position):
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        mapW = self.mapW
        mapH = self.mapH
        for d in CARDINALS:
            gunnerSpot = myLoc.add(d)
            dist = attackPos.distance_squared(gunnerSpot)
            if dist < 10 and dist != 5 and 0 <= gunnerSpot.x < mapW and 0 <= gunnerSpot.y < mapH:
                spotId = ct.get_tile_building_id(gunnerSpot)
                if spotId is None:
                    gunnerDir = gunnerSpot.direction_to(attackPos)
                    if ct.can_build_gunner(gunnerSpot, gunnerDir):
                        ct.build_gunner(gunnerSpot, gunnerDir)
                    return # you might be able to build next turn tho, so leave as is
        for d in CARDINALS: # try destorying after you exhaust all possible build opportunities
            gunnerSpot = myLoc.add(d)
            dist = attackPos.distance_squared(gunnerSpot)
            if dist < 10 and dist != 5:
                spotId = ct.get_tile_building_id(gunnerSpot)
                if spotId is not None:
                    spotTeam = ct.get_team(spotId)
                    spotType = ct.get_entity_type(spotId)
                    if spotTeam == myTeam and spotType in [EntityType.BARRIER, EntityType.CONVEYOR]:
                        if ct.can_destroy(gunnerSpot):
                            ct.destroy(gunnerSpot)
                            return
        self.mapPf.moveTo(ct, attackPos)

    def heal(self, ct: Controller, healPos: Position):
        myLoc = ct.get_position()
        if myLoc == healPos and ct.get_hp() < 40: # this means you are low, so run
            self.mapPf.moveTo(ct, self.mapPf.teamCore)
            return # act-xor-move: fleeing IS this turn, healing would no-op
        if ct.can_heal(healPos):
            ct.heal(healPos)
        else:
            self.mapPf.moveTo(ct, healPos)

    def route(self, ct: Controller, routePos: Position, routeDir: Direction):
        self.mapPf.routeConveyor(ct, routePos)
    def harvest(self, ct: Controller, harvestPos: Position):
        myLoc = ct.get_position()
        dist = harvestPos.distance_squared(myLoc)
        if dist > 2:
            self.mapPf.moveTo(ct, harvestPos)
            return
        elif dist == 2:
            for d in CARDINALS:
                nextPos = myLoc.add(d)
                if nextPos.distance_squared(harvestPos) == 1 and ct.can_move(d):
                    ct.move(d)
                    break
            return
        elif dist == 0:
            for d in CARDINALS:
                if ct.can_move(d):
                    ct.move(d)
                    break
            return
        if ct.can_build_harvester(harvestPos):
            ct.build_harvester(harvestPos)
    def explore(self, ct: Controller, explorePos: Position):
        myLoc = ct.get_position()
        # FINISHER: nothing in vision, bank full, game aging -> march at the
        # mirrored enemy core instead of sightseeing. The brawler reflex
        # (attack state) takes over the moment their stuff enters vision, so
        # this converts slow suffocation wins into core kills and rescues
        # would-be tiebreak games.
        if (ct.get_current_round() > 50 and ct.get_global_resources() > 150
                and self.mapPf.teamCore is not None and self._may_attack(ct)):
            explorePos = self._enemy_core_target()
        elif explorePos is None:
            corners = [Position(0, 0), Position(self.mapW - 1, 0), Position(0, self.mapH - 1), Position(self.mapW - 1, self.mapH - 1)]
            explorePos = corners[ct.get_current_round() // 20 % 4]
        self.mapPf.moveTo(ct, explorePos)
