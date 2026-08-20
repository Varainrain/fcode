"""Starter bot — economy-first strategy with light defense.

Each unit gets its own Player instance; the engine calls run() once per round.
Use ct.get_entity_type() to branch on what kind of unit you are.

Strategy:
  1. Core spawns builder bots and publishes its position via the store
  2. Builder bots explore, build harvesters on ore, and lay conveyors toward
     the core so titanium flows back automatically
  3. Once the economy is running (3+ harvesters), builder bots place gunners
     near the core for defense
  4. Gunners auto-fire at the closest visible enemy

Entity types used:  Core, Builder Bot, Harvester, Conveyor, Gunner

Communication store slots:
  0  SLOT_CORE_X          Core X position (written by core on round 1)
  1  SLOT_CORE_Y          Core Y position
  2  SLOT_HARVESTER_COUNT Total harvesters built by the team
  3  SLOT_ORE_LOCATION    Packed (x, y) of an uncovered ore tile
  Slots 4-15 are free — use them for your own coordination logic.

Ideas for improvement:
  - Build full conveyor chains from distant harvesters back to the core
  - Feed ammo to gunners via conveyors so they can actually fire
  - Add sentinels or launchers for stronger defense
  - Explore the map systematically instead of picking random targets
  - Use more store slots to coordinate roles between builder bots
"""

import random

from fcode import Controller, Direction, EntityType, Environment, GameConstants, Position

# All directions except CENTRE — useful for movement and spawning
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

# Cardinal directions only — conveyors and splitters can only face these
CARDINALS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

# --- Communication store slot assignments ---
# The store has 16 slots (indices 0-15), each holding a u32 value.
# Writes are buffered: a write_store() call becomes visible to all units
# at the start of the *next* round.
SLOT_CORE_X = 0
SLOT_CORE_Y = 1
SLOT_HARVESTER_COUNT = 2
SLOT_ORE_LOCATION = 3

# How many builder bots the core will spawn over the course of the game
MAX_BUILDERS = 7

# How many harvesters we want before switching builder bots to defense duty
TARGET_HARVESTERS = 5

# Defense doctrine: sentinels first (indirect fire ignores armor and their
# facing can cover approach lanes), then sniper gunners, then heal wardens.
TARGET_SENTINELS = 3
TARGET_GUNNERS = 2
SLOT_SENTINEL_COUNT = 4
SLOT_GUNNER_COUNT = 5


def pack_pos(pos: Position) -> int:
    """Encode a position into a single u32 for the communication store.

    We offset by +1 so that position (0, 0) doesn't encode as 0,
    which we reserve to mean "no data".
    """
    return ((pos.x + 1) << 16) | (pos.y + 1)


def unpack_pos(val: int) -> Position | None:
    """Decode a position from the communication store. Returns None if empty (0)."""
    if val == 0:
        return None
    return Position((val >> 16) - 1, (val & 0xFFFF) - 1)


def nearest_cardinal(d: Direction) -> Direction:
    """Snap any direction to the nearest cardinal direction.

    Conveyors and splitters can only face cardinal directions (N/E/S/W),
    so we use this to convert an arbitrary direction into a valid facing.
    """
    return {
        Direction.NORTH: Direction.NORTH,
        Direction.NORTHEAST: Direction.NORTH,
        Direction.EAST: Direction.EAST,
        Direction.SOUTHEAST: Direction.EAST,
        Direction.SOUTH: Direction.SOUTH,
        Direction.SOUTHWEST: Direction.SOUTH,
        Direction.WEST: Direction.WEST,
        Direction.NORTHWEST: Direction.WEST,
        Direction.CENTRE: Direction.NORTH,
    }[d]


class Player:
    def __init__(self):
        # Core tracks how many builder bots it has spawned
        self.num_spawned = 0

        # Builder bot navigation state
        self.target: Position | None = None   # where we're trying to walk to
        self.last_pos: Position | None = None  # position last round (for stuck detection)
        self.stuck = 0                         # consecutive rounds without moving

        # Cached core position (read from the store once, then reused)
        self.core_pos: Position | None = None

    def run(self, ct: Controller) -> None:
        """Entry point called by the engine every round for each unit.

        We check what type of entity we are and dispatch to the right handler.
        Each entity type (core, builder bot, gunner) has its own run logic.
        """
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self._run_core(ct)
        elif etype == EntityType.BUILDER_BOT:
            self._run_builder(ct)
        elif etype == EntityType.GUNNER:
            self._run_gunner(ct)
        elif entity_type == EntityType.SENTINEL:
            self._run_sentinel(ct)

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def _run_core(self, ct: Controller) -> None:
        """Core logic: publish our position so builder bots can orient toward us,
        then try to spawn a builder bot each round until we hit the cap.
        """
        # Write our position into the store every round so newly spawned bots
        # can read it. Store writes are buffered — they become visible next round.
        pos = ct.get_position()
        ct.write_store(SLOT_CORE_X, pos.x)
        ct.write_store(SLOT_CORE_Y, pos.y)

        # AMMO: turrets fire from the global pool - without conversion they
        # are decorative. Keep a modest pool topped up, reserve build money.
        ammo = ct.get_global_ammo()
        ti = ct.get_global_resources()
        want = min(24 - ammo, ti - 40)
        if want > 0 and ct.can_convert_ammo(want):
            ct.convert_ammo(want)

        # Don't spawn more than MAX_BUILDERS total
        if self.num_spawned >= MAX_BUILDERS:
            return

        # Check we can afford a builder bot before trying
        ti = ct.get_global_resources()
        cost = ct.get_builder_bot_cost()
        if ti < cost:
            return

        # Try to spawn on a random adjacent tile (shuffle to avoid bias)
        dirs = list(DIRECTIONS)
        random.shuffle(dirs)
        for d in dirs:
            spawn_pos = pos.add(d)
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.num_spawned += 1
                return

    # ------------------------------------------------------------------
    # Builder bot
    # ------------------------------------------------------------------

    def _run_builder(self, ct: Controller) -> None:
        """Builder bot logic, executed each round. Priority order:
        1. Build a harvester if adjacent to uncovered ore
        2. Build a gunner if we already have enough harvesters
        3. Heal any damaged friendly buildings nearby
        4. Move toward the next target (ore or exploration)
        5. Broadcast any visible ore to teammates via the store
        """
        pos = ct.get_position()

        # On our first turn, read the core's position from the store.
        # We cache it so we don't have to read every round.
        if self.core_pos is None:
            self._read_core_pos(ct)

        # Stuck detection: if we haven't moved in 3 rounds, we'll pick a new
        # target in _move_toward_target to avoid getting permanently stuck.
        if self.last_pos == pos:
            self.stuck += 1
        else:
            self.stuck = 0
        self.last_pos = pos

        # THREAT OVERRIDE (kick rushes arrive t8 - no eco-gated ladder can
        # answer that; and unlike a rush bot, citadel pays NO race tax for
        # home spending: the whole bot IS the garrison). Any enemy near our
        # core -> defense outranks economy unconditionally.
        threat = self._nearest_home_threat(ct)
        if threat is not None and ct.get_action_cooldown() == 0:
            if self._try_build_defense_facing(ct, threat):
                return
            if self._try_heal(ct):
                return

        # --- Build phase (requires action cooldown == 0) ---
        # Try to build a harvester first; if none available, consider a gunner
        if ct.get_action_cooldown() == 0:
            if not self._try_build_harvester(ct):
                # Only build gunners once our economy is up (enough harvesters)
                # STAGE LADDER (v0 died naked: waves kill t63, kicks t31 -
                # five harvesters before any defense is a 40-turn open door.
                # Lorem's law: the picket exists by t14, economy behind it).
                harvester_count = ct.read_store(SLOT_HARVESTER_COUNT)
                sentinels = ct.read_store(SLOT_SENTINEL_COUNT)
                gunners = ct.read_store(SLOT_GUNNER_COUNT)
                if harvester_count >= 2 and sentinels < 1:
                    self._try_build_sentinel(ct)
                elif harvester_count >= 3 and sentinels < 2:
                    self._try_build_sentinel(ct)
                elif harvester_count >= 3 and gunners < 1:
                    self._try_build_gunner(ct)
                elif harvester_count >= TARGET_HARVESTERS:
                    if sentinels < TARGET_SENTINELS:
                        self._try_build_sentinel(ct)
                    elif gunners < TARGET_GUNNERS:
                        self._try_build_gunner(ct)

        # If we still have an action left (didn't build anything), heal nearby
        if ct.get_action_cooldown() == 0:
            self._try_heal(ct)

        # --- Move phase (requires move cooldown == 0) ---
        self._move_toward_target(ct)

        # --- Communication phase (no cooldown needed) ---
        # Share any visible ore location with teammates
        self._share_ore(ct)

    def _read_core_pos(self, ct: Controller) -> None:
        """Read the core's position from the communication store.

        The core writes its position on round 1, so on round 1 these will
        still be 0. We skip storing (0, 0) unless the core really is there.
        """
        x = ct.read_store(SLOT_CORE_X)
        y = ct.read_store(SLOT_CORE_Y)
        if x > 0 or y > 0:
            self.core_pos = Position(x, y)

    def _try_build_harvester(self, ct: Controller) -> bool:
        """Try to build a harvester on an adjacent ore tile.

        Harvesters can only be placed on ore tiles (Environment.ORE_TITANIUM).
        can_build_harvester() checks for ore, empty tile, and sufficient resources.
        After building, we also try to place a conveyor next to it to start
        routing the titanium back toward the core.
        """
        ti = ct.get_global_resources()
        cost = ct.get_harvester_cost()
        if ti < cost:
            return False

        pos = ct.get_position()
        for d in Direction:
            build_pos = pos.add(d)
            if ct.can_build_harvester(build_pos):
                ct.build_harvester(build_pos)
                # Update the shared harvester counter so other bots know
                count = ct.read_store(SLOT_HARVESTER_COUNT)
                ct.write_store(SLOT_HARVESTER_COUNT, count + 1)
                # Try to add a conveyor next to the harvester to route resources
                self._try_build_conveyor_toward_core(ct, build_pos)
                # Clear our target so we move on instead of lingering near this
                # harvester.  Without this the bot would try to walk onto the
                # (non-passable) harvester tile for 3 rounds before stuck
                # detection finally kicks in.
                self.target = None
                return True
        return False

    def _try_build_conveyor_toward_core(self, ct: Controller, harvester_pos: Position) -> None:
        """Place a conveyor adjacent to a harvester, facing toward the core.

        Harvesters output titanium stacks to adjacent buildings. By placing a
        conveyor on the core-facing side, resources will start flowing in the
        right direction. For a complete supply chain you'd need more conveyors
        linking all the way back to the core.
        """
        if self.core_pos is None:
            return
        ti = ct.get_global_resources()
        cost = ct.get_conveyor_cost()
        if ti < cost:
            return

        # Figure out which cardinal direction points from the harvester toward the core
        toward_core = harvester_pos.direction_to(self.core_pos)
        if toward_core == Direction.CENTRE:
            return  # harvester is right on top of the core (unlikely)
        facing = nearest_cardinal(toward_core)

        # Place the conveyor one step toward the core from the harvester
        conv_pos = harvester_pos.add(facing)
        if ct.can_build_conveyor(conv_pos, facing):
            ct.build_conveyor(conv_pos, facing)

    def _nearest_home_threat(self, ct: Controller):
        """Nearest enemy unit or turret within ~7 tiles of our core."""
        if self.core_pos is None:
            return None
        best, bd = None, 50
        my_team = ct.get_team()
        for u in ct.get_nearby_units():
            if ct.get_team(u) != my_team:
                p = ct.get_position(u)
                d = p.distance_squared(self.core_pos)
                if d < bd:
                    bd, best = d, p
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != my_team:
                et = ct.get_entity_type(b)
                if et in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.LAUNCHER):
                    p = ct.get_position(b)
                    d = p.distance_squared(self.core_pos)
                    if d < bd:
                        bd, best = d, p
        return best

    def _try_build_defense_facing(self, ct: Controller, threat) -> bool:
        """Emergency turret facing the threat: gunner if affordable (cheap,
        fast), sentinel if the threat looks entrenched and we are rich."""
        pos = ct.get_position()
        if pos.distance_squared(threat) > 36:
            return False    # too far to matter - let the eco continue
        fdx = (threat.x > pos.x) - (threat.x < pos.x)
        fdy = (threat.y > pos.y) - (threat.y < pos.y)
        for fd in CARDINALS:
            if fd.delta() in ((fdx, 0), (0, fdy)):
                for d in CARDINALS:
                    spot = pos.add(d)
                    if ct.get_global_resources() >= ct.get_gunner_cost() + 10:
                        if ct.can_build_gunner(spot, fd):
                            ct.build_gunner(spot, fd)
                            ct.write_store(SLOT_GUNNER_COUNT,
                                           ct.read_store(SLOT_GUNNER_COUNT) + 1)
                            return True
                break
        return False

    def _try_build_sentinel(self, ct: Controller) -> bool:
        """Sentinel ring: indirect fire ignores walls/armor, and a lane-facing
        sentinel punishes anything walking our approach. Seats sit 2-4 tiles
        from the core, facing AWAY from it."""
        cost = ct.get_sentinel_cost()
        if ct.get_global_resources() < cost + 30:
            return False
        if self.core_pos is None:
            return False
        pos = ct.get_position()
        d_core = pos.distance_squared(self.core_pos)
        if d_core > 25:
            return False    # build defense near home only
        for d in CARDINALS:
            spot = pos.add(d)
            if spot.distance_squared(self.core_pos) < 2:
                continue    # not hugging the core - leave heal lanes open
            # face away from the core: the direction whose delta matches
            # core -> spot extended
            fdx = (spot.x > self.core_pos.x) - (spot.x < self.core_pos.x)
            fdy = (spot.y > self.core_pos.y) - (spot.y < self.core_pos.y)
            for fd in CARDINALS:
                if fd.delta() == (fdx, 0) or fd.delta() == (0, fdy):
                    if ct.can_build_sentinel(spot, fd):
                        ct.build_sentinel(spot, fd)
                        ct.write_store(SLOT_SENTINEL_COUNT,
                                       ct.read_store(SLOT_SENTINEL_COUNT) + 1)
                        return True
        return False

    def _try_build_gunner(self, ct: Controller) -> bool:
        """Build a gunner turret on an adjacent tile, facing away from the core.

        Gunners fire in a straight line in their facing direction, so pointing
        them outward from the core gives them the best chance of hitting
        approaching enemies. We only build if we're close to the core
        (within ~4 tiles) so gunners end up defending the base.

        Note: gunners need ammo delivered via conveyors to fire. This starter
        bot doesn't set up ammo supply — that's an exercise for the player!
        """
        ti = ct.get_global_resources()
        cost = ct.get_gunner_cost()
        if ti < cost:
            return False

        pos = ct.get_position()
        # Only build gunners when we're reasonably close to the core
        if self.core_pos is None or pos.distance_squared(self.core_pos) > 18:
            return False

        # Face the gunner away from the core (toward incoming enemies)
        facing = pos.direction_to(self.core_pos).opposite()
        if facing == Direction.CENTRE:
            facing = random.choice(DIRECTIONS)

        # Try each adjacent tile for a valid gunner placement
        for d in Direction:
            build_pos = pos.add(d)
            if ct.can_build_gunner(build_pos, facing):
                ct.build_gunner(build_pos, facing)
                ct.write_store(SLOT_GUNNER_COUNT, ct.read_store(SLOT_GUNNER_COUNT) + 1)
                return True
        return False

    def _try_heal(self, ct: Controller) -> None:
        """Heal a damaged friendly building or bot on an adjacent tile.

        Healing costs 1 titanium and restores 4 HP. can_heal() checks that
        there's actually a damaged friendly entity on the tile.
        """
        pos = ct.get_position()
        for d in Direction:
            check = pos.add(d)
            if ct.can_heal(check):
                ct.heal(check)
                return

    # ------------------------------------------------------------------
    # Builder bot — movement
    # ------------------------------------------------------------------

    def _move_toward_target(self, ct: Controller) -> None:
        """Navigate toward our current target, picking a new one if needed.

        Target priority: visible ore > ore shared via store > random position.
        If we've been stuck for 3+ rounds, we give up on the current target
        and pick a fresh one.
        """
        if ct.get_move_cooldown() != 0:
            return

        pos = ct.get_position()

        # Pick a new target if we don't have one, reached it, or are stuck
        if self.target is None or pos == self.target or self.stuck >= 3:
            self.target = self._pick_target(ct)
            self.stuck = 0
        if self.target is None:
            return

        # Get the direction toward our target
        desired = pos.direction_to(self.target)
        if desired == Direction.CENTRE:
            return

        # Try the ideal direction first, then slightly left/right of it.
        # If all three fail (e.g. boxed in by harvesters), try every remaining
        # direction so the bot can escape instead of sitting stuck for 3 rounds.
        primary = [desired, desired.rotate_left(), desired.rotate_right()]
        for d in primary:
            if self._try_move(ct, d):
                return
        remaining = [d for d in DIRECTIONS if d not in primary]
        random.shuffle(remaining)
        for d in remaining:
            if self._try_move(ct, d):
                return

    def _try_move(self, ct: Controller, d: Direction) -> bool:
        """Try to move one step in direction d, laying conveyor infra along the way.

        Builder bots can walk on any tile that isn't a wall or occupied by another
        builder bot. If the destination is empty and we know where our core is, we
        lay a conveyor pointing toward it so it doubles as part of the resource
        network -- this is optional now, not required for movement.
        """
        if d == Direction.CENTRE:
            return False
        pos = ct.get_position()
        next_pos = pos.add(d)

        if ct.is_tile_empty(next_pos) and self.core_pos is not None:
            toward_core = next_pos.direction_to(self.core_pos)
            cardinal = nearest_cardinal(toward_core)
            if ct.can_build_conveyor(next_pos, cardinal):
                ct.build_conveyor(next_pos, cardinal)

        if ct.can_move(d):
            ct.move(d)
            return True
        return False

    def _pick_target(self, ct: Controller) -> Position:
        """Choose the next position to navigate toward.

        Priority:
        1. Closest visible ore tile without a harvester on it — go build one
        2. If economy is established (enough harvesters), head back toward
           the core so we can build gunners for defense
        3. Ore location shared by a teammate via the store — head that way
        4. Random map position — pure exploration
        """
        pos = ct.get_position()

        # 1. Scan visible tiles for the nearest uncovered ore
        best_ore = None
        best_dist = float("inf")
        for tile in ct.get_nearby_tiles():
            if ct.get_tile_env(tile) != Environment.ORE_TITANIUM:
                continue
            # Skip ore that already has a building (harvester or otherwise) on it
            if ct.get_tile_building_id(tile) is not None:
                continue
            d = pos.distance_squared(tile)
            if d < best_dist:
                best_dist = d
                best_ore = tile
        if best_ore is not None:
            return best_ore

        # 2. Once we have enough harvesters, head back to the core so we can
        #    build gunners nearby.  _try_build_gunner requires being within
        #    distance² 18 of the core, so we navigate there.
        harvester_count = ct.read_store(SLOT_HARVESTER_COUNT)
        if harvester_count >= TARGET_HARVESTERS and self.core_pos is not None:
            if pos.distance_squared(self.core_pos) > 8:
                return self.core_pos

        # 3. Check the store for an ore location shared by a teammate
        shared = unpack_pos(ct.read_store(SLOT_ORE_LOCATION))
        if shared is not None and pos.distance_squared(shared) > 4:
            return shared

        # 4. No known ore — pick a random position to explore
        w, h = ct.get_map_width(), ct.get_map_height()
        return Position(random.randrange(w), random.randrange(h))

    def _share_ore(self, ct: Controller) -> None:
        """Broadcast a visible uncovered ore tile to teammates via the store.

        Any builder bot that sees ore without a building on it writes the
        location to SLOT_ORE_LOCATION. Other bots can read this to navigate
        toward ore they haven't seen yet.
        """
        pos = ct.get_position()
        for tile in ct.get_nearby_tiles():
            if ct.get_tile_env(tile) == Environment.ORE_TITANIUM:
                if ct.get_tile_building_id(tile) is None:
                    ct.write_store(SLOT_ORE_LOCATION, pack_pos(tile))
                    return

    # ------------------------------------------------------------------
    # Gunner
    # ------------------------------------------------------------------

    def _run_sentinel(self, ct: Controller) -> None:
        """Medic-priority targeting: the enemy builder TENDING a position is
        worth more than the position (kill the healer, the camp collapses).
        Then turrets, then anything else. Indirect fire - walls irrelevant."""
        best, score = None, 0
        my_team = ct.get_team()
        for tile in ct.get_attackable_tiles():
            if not ct.is_in_vision(tile):
                continue
            b_id = ct.get_tile_building_id(tile)
            bb_id = ct.get_tile_builder_bot_id(tile)
            if bb_id is not None and ct.get_team(bb_id) == my_team:
                continue
            if b_id is not None and ct.get_team(b_id) == my_team:
                continue
            s = 0
            if bb_id is not None:
                s = 4   # enemy builder in our zone = planter/medic/chewer
            elif b_id is not None:
                bt = ct.get_entity_type(b_id)
                if bt in (EntityType.GUNNER, EntityType.SENTINEL):
                    s = 3
                elif bt == EntityType.LAUNCHER:
                    s = 3   # logistics keystone
                elif bt == EntityType.CORE:
                    s = 1
            if s > score:
                score, best = s, tile
        if best is not None and ct.can_fire(best):
            ct.fire(best)

    def _run_gunner(self, ct: Controller) -> None:
        """Gunner logic: fire at the first enemy in our line of sight.

        get_gunner_target() returns the closest entity along the gunner's
        facing direction, or None if the line is clear. We only fire if
        can_fire() confirms we have ammo and cooldown is ready.
        """
        target = ct.get_gunner_target()
        if target is not None and ct.can_fire(target):
            ct.fire(target)
