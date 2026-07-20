"""fast home-siege detection and builder counter-battery."""

from fcode import Direction, EntityType, Environment, Position

import turretplan


# big maps keep one gunner standing near the core before any rush shows up
STANDING_GUARD_MIN_AREA = 0  # every map: small maps get rushed the fastest
STANDING_GUARD_RESERVE = 40  # ti to keep above the gunner cost
STANDING_GUARD_MIN_ROUND = 8  # up before the earliest rush arrives
STANDING_GUARD_WALK_MANHATTAN = 8  # defense bots further than this dont bother

# home turrets this close trigger the interrupt.
HOME_TURRET_MANHATTAN = 5
# only builders already near home may respond.
HOME_RESPONDER_MANHATTAN = 10
# fresh sightings keep the interrupt alive this long locally.
HOME_SIGHTING_FRESH_ROUNDS = 8
# large home groups are thinned by a deterministic parity filter.
HOME_PARITY_SPAWN_THRESHOLD = 2
# reactive builds preserve one builder's titanium.
HOME_BUILDER_RESERVE = 15
# no more than this many live counter-turrets are wanted.
HOME_COUNTER_TURRET_CAP = 2
# emergency ammo supports twenty gunner shots.
HOME_AMMO_BUFFER = 40


# cardinal facings in store-compatible order.
FACINGS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)


def _manhattan(a, b):
    return abs(a.x - b.x) + abs(a.y - b.y)


def _core_tiles(corner, width, height):
    tiles = []
    for dx in (0, 1):
        for dy in (0, 1):
            x, y = corner.x + dx, corner.y + dy
            if 0 <= x < width and 0 <= y < height:
                tiles.append(Position(x, y))
    return tiles if tiles else [corner]


def _near_core(pos, core_tiles):
    return min(_manhattan(pos, tile) for tile in core_tiles)


def _direction_to(origin, target):
    if origin.x == target.x:
        if target.y > origin.y:
            return Direction.SOUTH
        if target.y < origin.y:
            return Direction.NORTH
    if origin.y == target.y:
        if target.x > origin.x:
            return Direction.EAST
        if target.x < origin.x:
            return Direction.WEST
    return None


class HomeDefense:
    def __init__(self):
        self.current_targets = []
        self.fresh_until = {}
        self.reactive_turrets = {}

    def observe_from_core(self, ct):
        """Publish one nearest visible turret and return the live emergency."""
        width = ct.get_map_width()
        height = ct.get_map_height()
        corner = ct.get_position()
        core_tiles = _core_tiles(corner, width, height)
        visible = []
        for building_id in ct.get_nearby_buildings():
            if ct.get_team(building_id) == ct.get_team():
                continue
            entity_type = ct.get_entity_type(building_id)
            type_code = turretplan.ENTITY_TO_INFRA.get(entity_type)
            if type_code not in turretplan.TURRET_TYPES:
                continue
            pos = ct.get_position(building_id)
            visible.append((pos, type_code))

        visible.sort(key=lambda item: (
            _near_core(item[0], core_tiles), item[0].x, item[0].y,
            item[1],
        ))
        wrote_slot = None
        if visible:
            pos, type_code = visible[0]
            wrote_slot = turretplan.publish_enemy_infra_sighting(
                ct, width, height, pos, type_code
            )

        # core vision owns liveness for every home-range record.
        if wrote_slot is None:
            live_positions = {(pos.x, pos.y) for pos, _ in visible}
            records = turretplan.read_enemy_infra_records(ct, width, height)
            for record in records:
                if record is None or record[2] not in turretplan.TURRET_TYPES:
                    continue
                pos = Position(record[0], record[1])
                if (_near_core(pos, core_tiles) > HOME_TURRET_MANHATTAN
                        or not ct.is_in_vision(pos)
                        or (pos.x, pos.y) in live_positions):
                    continue
                turretplan.clear_enemy_infra_sighting(
                    ct, width, height, pos
                )
                break

        return any(_near_core(pos, core_tiles) <= HOME_TURRET_MANHATTAN
                   for pos, _ in visible)

    def home_emergency(self, ct, planner, core_tiles):
        """Return whether shared sightings and local core vision demand action."""
        self.current_targets = []
        if planner is None or not core_tiles:
            return False
        now = ct.get_current_round()
        core_damaged = None
        shared = {(record[0], record[1], record[2])
                  for record in planner.shared_infra_records()}
        for (x, y), (type_code, freshness) in planner.infra_memory.items():
            if type_code not in turretplan.TURRET_TYPES:
                continue
            pos = Position(x, y)
            if _near_core(pos, core_tiles) > HOME_TURRET_MANHATTAN:
                continue
            if core_damaged is None:
                core_damaged = self._core_damaged(ct, core_tiles)
            age = turretplan.infra_sighting_age_rounds(now, freshness)
            present = ((x, y, type_code) in shared or ct.is_in_vision(pos))
            if age == 0 and present:
                self.fresh_until[(x, y)] = now + HOME_SIGHTING_FRESH_ROUNDS
            fresh = now <= self.fresh_until.get((x, y), -1)
            if (bool(core_damaged) and present) or fresh:
                self.current_targets.append((pos, type_code))

        known = {(pos.x, pos.y) for pos, _ in self.current_targets}
        for key in list(self.fresh_until):
            if key not in planner.infra_memory or (
                    key not in known and now > self.fresh_until[key]):
                del self.fresh_until[key]
        self.current_targets.sort(key=lambda item: (
            _near_core(item[0], core_tiles), item[0].x, item[0].y,
            item[1],
        ))
        return bool(self.current_targets)

    def should_respond(self, ct, my_num, core_tiles):
        if not self.current_targets or my_num < 1:
            return False
        if _near_core(ct.get_position(), core_tiles) > HOME_RESPONDER_MANHATTAN:
            return False
        spawn_count = ct.read_store(0)
        if spawn_count <= HOME_PARITY_SPAWN_THRESHOLD:
            return True
        target = self.current_targets[0][0]
        return (my_num & 1) == ((target.x + target.y) & 1)

    def respond(self, ct, planner, my_num, core_tiles, full_map, move_to):
        """Run one elected builder's emergency turn."""
        if not self.home_emergency(ct, planner, core_tiles):
            return False, None
        if not self.should_respond(ct, my_num, core_tiles):
            return False, None

        self._prune_reactive_memory(ct)
        counter_count = self._counter_turret_count(ct, planner)
        wanted = min(HOME_COUNTER_TURRET_CAP, len(self.current_targets))
        if counter_count < wanted:
            built = self._try_build(ct, planner, core_tiles, full_map)
            if built is not None:
                return True, built

        self._heal_core(ct, core_tiles)
        target = self._staging_tile(ct, core_tiles, full_map)
        if target is None:
            target = min(core_tiles, key=lambda tile: (
                _manhattan(ct.get_position(), tile), tile.x, tile.y
            ))
        move_to(ct, target)
        return True, None

    def _core_damaged(self, ct, core_tiles):
        checked = set()
        for tile in core_tiles:
            if not ct.is_in_vision(tile):
                continue
            building_id = ct.get_tile_building_id(tile)
            if building_id is None or building_id in checked:
                continue
            checked.add(building_id)
            if (ct.get_team(building_id) == ct.get_team()
                    and ct.get_entity_type(building_id) == EntityType.CORE
                    and ct.get_hp(building_id) < ct.get_max_hp(building_id)):
                return True
        return False

    def _try_build(self, ct, planner, core_tiles, full_map):
        # flat reserve: the counter turret IS the survival spend, dont
        # price it against a scaled builder replacement
        reserve = HOME_BUILDER_RESERVE
        resources = ct.get_global_resources()
        gunner_cost = ct.get_gunner_cost()
        if resources >= gunner_cost + reserve:
            candidates = self._gunner_candidates(
                ct, core_tiles, full_map, local_only=True
            )
            for _, pos, facing, target in candidates:
                if (not ct.can_build_gunner(pos, facing)
                        and not self._clear_allied_build_tile(ct, pos)):
                    continue
                if not ct.can_build_gunner(pos, facing):
                    continue
                ct.build_gunner(pos, facing)
                self._record_built(
                    ct, planner, pos, turretplan.INFRA_GUNNER, facing
                )
                return pos

        sentinel_cost = ct.get_sentinel_cost()
        if resources >= sentinel_cost + reserve:
            candidates = self._sentinel_candidates(
                ct, core_tiles, full_map, local_only=True
            )
            for _, pos, facing, target in candidates:
                if (not ct.can_build_sentinel(pos, facing)
                        and not self._clear_allied_build_tile(ct, pos)):
                    continue
                if not ct.can_build_sentinel(pos, facing):
                    continue
                ct.build_sentinel(pos, facing)
                self._record_built(
                    ct, planner, pos, turretplan.INFRA_SENTINEL, facing
                )
                return pos
        return None

    def _record_built(self, ct, planner, pos, type_code, facing):
        self.reactive_turrets[(pos.x, pos.y)] = (type_code, facing)
        proposal = turretplan.Proposal(
            pos.x, pos.y, type_code, facing, 0, False, False, False, 0
        )
        planner.record_built(ct, proposal)

    def _local_tiles(self, ct):
        return sorted(ct.get_nearby_tiles(2), key=lambda pos: (pos.x, pos.y))

    def _gunner_candidates(self, ct, core_tiles, full_map, local_only):
        if local_only:
            tiles = self._local_tiles(ct)
        else:
            tiles = self._global_candidate_tiles(ct, full_map)
        candidates = []
        for target_index, (target, target_type) in enumerate(self.current_targets):
            for pos in tiles:
                facing = _direction_to(pos, target)
                distance_squared = pos.distance_squared(target)
                if (facing is None or distance_squared > 13
                        or not self._ray_clear(ct, full_map, pos, target)):
                    continue
                exposed = self._in_inferred_home_ray(
                    pos, target, target_type, core_tiles
                )
                move_distance = _manhattan(ct.get_position(), pos)
                score = (int(exposed), target_index, move_distance,
                         -distance_squared, pos.x, pos.y)
                candidates.append((score, pos, facing, target))
        candidates.sort(key=lambda item: item[0])
        return candidates

    def _sentinel_candidates(self, ct, core_tiles, full_map, local_only):
        if local_only:
            tiles = self._local_tiles(ct)
        else:
            tiles = self._global_candidate_tiles(ct, full_map)
        candidates = []
        for target_index, (target, target_type) in enumerate(self.current_targets):
            for pos in tiles:
                for facing in FACINGS:
                    if not turretplan.in_turret_envelope(
                            (pos.x, pos.y), (target.x, target.y),
                            turretplan.INFRA_SENTINEL, facing):
                        continue
                    exposed = self._in_inferred_home_ray(
                        pos, target, target_type, core_tiles
                    )
                    move_distance = _manhattan(ct.get_position(), pos)
                    score = (int(exposed), target_index, move_distance,
                             -pos.distance_squared(target), pos.x, pos.y,
                             FACINGS.index(facing))
                    candidates.append((score, pos, facing, target))
        candidates.sort(key=lambda item: item[0])
        return candidates

    def _global_candidate_tiles(self, ct, full_map):
        width = ct.get_map_width()
        height = ct.get_map_height()
        tiles = set()
        for target, _ in self.current_targets:
            for dx in range(-5, 6):
                for dy in range(-5, 6):
                    x, y = target.x + dx, target.y + dy
                    if not (0 <= x < width and 0 <= y < height):
                        continue
                    if dx * dx + dy * dy > 32:
                        continue
                    if full_map is not None and full_map[x][y] in (2, 3):
                        continue
                    tiles.add((x, y))
        return [Position(x, y) for x, y in sorted(tiles)]

    def _staging_tile(self, ct, core_tiles, full_map):
        gunners = self._gunner_candidates(
            ct, core_tiles, full_map, local_only=False
        )
        if gunners:
            return gunners[0][1]
        sentinels = self._sentinel_candidates(
            ct, core_tiles, full_map, local_only=False
        )
        return sentinels[0][1] if sentinels else None

    def _ray_clear(self, ct, full_map, origin, target):
        facing = _direction_to(origin, target)
        if facing is None:
            return False
        dx = 0 if origin.x == target.x else (1 if target.x > origin.x else -1)
        dy = 0 if origin.y == target.y else (1 if target.y > origin.y else -1)
        x, y = origin.x + dx, origin.y + dy
        width = ct.get_map_width()
        height = ct.get_map_height()
        while (x, y) != (target.x, target.y):
            if not (0 <= x < width and 0 <= y < height):
                return False
            pos = Position(x, y)
            if ct.is_in_vision(pos):
                if (ct.get_tile_env(pos) == Environment.WALL
                        or ct.get_tile_building_id(pos) is not None):
                    return False
            elif full_map is None or full_map[x][y] in (-1, 2, 3):
                return False
            x += dx
            y += dy
        return True

    def _in_inferred_home_ray(self, pos, enemy, enemy_type, core_tiles):
        core = min(core_tiles, key=lambda tile: (
            _manhattan(enemy, tile), tile.x, tile.y
        ))
        facing = _direction_to(enemy, core)
        if facing is None:
            dx = core.x - enemy.x
            dy = core.y - enemy.y
            if abs(dx) >= abs(dy):
                facing = Direction.EAST if dx > 0 else Direction.WEST
            else:
                facing = Direction.SOUTH if dy > 0 else Direction.NORTH
        index = FACINGS.index(facing)
        forward_x, forward_y = turretplan.FACING_DELTAS[index]
        dx = pos.x - enemy.x
        dy = pos.y - enemy.y
        forward = dx * forward_x + dy * forward_y
        lateral = abs(dx * forward_y - dy * forward_x)
        range_squared = 13 if enemy_type == turretplan.INFRA_GUNNER else 32
        return (forward > 0 and lateral <= 1
                and dx * dx + dy * dy <= range_squared)

    def _counter_turret_count(self, ct, planner):
        turrets = {key: (type_code, None)
                   for key, type_code in planner.turret_memory.items()}
        turrets.update(self.reactive_turrets)
        for building_id in ct.get_nearby_buildings():
            if ct.get_team(building_id) != ct.get_team():
                continue
            type_code = turretplan.ENTITY_TO_INFRA.get(
                ct.get_entity_type(building_id)
            )
            if type_code in turretplan.TURRET_TYPES:
                pos = ct.get_position(building_id)
                turrets[(pos.x, pos.y)] = (
                    type_code, ct.get_direction(building_id)
                )

        count = 0
        for (x, y), (type_code, facing) in turrets.items():
            if facing is None:
                continue
            for target, _ in self.current_targets:
                if turretplan.in_turret_envelope(
                        (x, y), (target.x, target.y), type_code, facing):
                    count += 1
                    break
        return min(HOME_COUNTER_TURRET_CAP, count)

    def _prune_reactive_memory(self, ct):
        for key, (type_code, facing) in list(self.reactive_turrets.items()):
            pos = Position(*key)
            if not ct.is_in_vision(pos):
                continue
            building_id = ct.get_tile_building_id(pos)
            actual = None
            if building_id is not None and ct.get_team(building_id) == ct.get_team():
                actual = turretplan.ENTITY_TO_INFRA.get(
                    ct.get_entity_type(building_id)
                )
            if actual != type_code:
                del self.reactive_turrets[key]

    def _clear_allied_build_tile(self, ct, pos):
        if not ct.is_in_vision(pos):
            return False
        building_id = ct.get_tile_building_id(pos)
        if building_id is None or ct.get_team(building_id) != ct.get_team():
            return False
        protected = (
            EntityType.CORE,
            EntityType.HARVESTER,
            EntityType.GUNNER,
            EntityType.SENTINEL,
        )
        if ct.get_entity_type(building_id) in protected or not ct.can_destroy(pos):
            return False
        ct.destroy(pos)
        return True

    def _heal_core(self, ct, core_tiles):
        checked = set()
        for tile in core_tiles:
            if (ct.get_position().distance_squared(tile) > 2
                    or not ct.is_in_vision(tile)):
                continue
            building_id = ct.get_tile_building_id(tile)
            if building_id is None or building_id in checked:
                continue
            checked.add(building_id)
            if (ct.get_team(building_id) == ct.get_team()
                    and ct.get_entity_type(building_id) == EntityType.CORE
                    and ct.get_hp(building_id) < ct.get_max_hp(building_id)
                    and ct.can_heal(tile)):
                ct.heal(tile)
                return True
        return False


    def maintain_standing_guard(self, ct, planner, core_tiles, enemy_core,
                                full_map, move_to):
        """big maps only: one cheap pre-built gunner near the core so a rush
        meets fire before the reactive battery spins up. returns
        (engaged, built_tile)."""
        if planner is None or not core_tiles:
            return False, None
        w, h = ct.get_map_width(), ct.get_map_height()
        if w * h <= STANDING_GUARD_MIN_AREA:
            return False, None
        if ct.get_current_round() < STANDING_GUARD_MIN_ROUND:
            return False, None
        if ct.get_global_resources() < ct.get_gunner_cost() + STANDING_GUARD_RESERVE:
            return False, None
        # already guarded? shared records first, then own vision
        for x, y, _t in planner._friendly_turrets():
            if _near_core(Position(x, y), core_tiles) <= HOME_TURRET_MANHATTAN:
                return False, None
        team = ct.get_team()
        for b in ct.get_nearby_buildings():
            if (ct.get_team(b) == team
                    and ct.get_entity_type(b) in (EntityType.GUNNER,
                                                  EntityType.SENTINEL)
                    and _near_core(ct.get_position(b), core_tiles)
                    <= HOME_TURRET_MANHATTAN):
                return False, None

        # face the likely approach: sighted enemy core, else rotational guess
        base = core_tiles[0]
        if enemy_core is None:
            enemy_core = Position(w - 2 - base.x, h - 2 - base.y)
        dx = enemy_core.x - base.x
        dy = enemy_core.y - base.y
        if abs(dx) >= abs(dy):
            face = Direction.EAST if dx > 0 else Direction.WEST
        else:
            face = Direction.SOUTH if dy > 0 else Direction.NORTH
        fdx, fdy = face.delta()

        # spot: two out from the core footprint toward the approach, slight
        # side offsets as fallbacks
        cands = []
        for c in core_tiles:
            p2 = Position(c.x + 2 * fdx, c.y + 2 * fdy)
            for q in (p2, Position(p2.x + fdy, p2.y + fdx),
                      Position(p2.x - fdy, p2.y - fdx)):
                if 0 <= q.x < w and 0 <= q.y < h and q not in cands:
                    cands.append(q)
        my = ct.get_position()
        for q in cands:
            if full_map[q.x][q.y] != 0:
                continue  # only known-empty ground
            if my.distance_squared(q) <= 2:
                if ct.can_build_gunner(q, face):
                    ct.build_gunner(q, face)
                    planner.pending_turrets[(q.x, q.y)] = turretplan.INFRA_GUNNER
                    return True, q
                continue
            if _manhattan(my, q) <= STANDING_GUARD_WALK_MANHATTAN:
                move_to(ct, q)
                return True, None
        return False, None
