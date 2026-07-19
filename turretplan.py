"""picks spots for defensive turrets, coordinated through the store.

store layout (0..7 belong to the map sharing layer):

* 8..11: two 16 bit enemy infra sightings per u32, xxxxx yyyyy ttt fff
  (x, y, type, round//16 mod 8). zero = empty.
* 12..13: two 13 bit friendly turret records per u32: x, y, type. zero = empty.
* 14: current proposal (x, y, type, facing, frontier, urgent, valid, score
  band, generation).
* 15: claim slot for the urgent builder (number, manhattan distance, age,
  proposal fingerprint). one elected builder updates it per round so it
  settles on the nearest idle bot.

the store is a lossy cache, not the source of truth: writers retry until a
sighting shows up in the next-round snapshot, readers merge it with their
own memory.

engine test scenario: two rooms joined by a 1 wide choke at (7, 5), our core
(2, 5), enemy core (12, 5), enemy harvesters at (10, 4..6), (5, 5) passable
on our side and outside known enemy turret range. top proposal should be a
SENTINEL at (5, 5) facing EAST, its band crosses the choke and covers the
cluster where a gunner straight ray cant.
"""

from collections import namedtuple

from fcode import Direction, EntityType, Position

import mapanalysis


# scoring tunables
W_COVER = 3
W_CHOKE = 4
W_MUTUAL = 2
W_SAFE = 1
W_EXPOSED = 4
W_FRONTIER_PENALTY = 6
URGENT_THRESHOLD = 25

# operational tunables
CPU_BUDGET_US = 6000
TITANIUM_RESERVE = 20
FRESHNESS_ROUNDS = 16
MAX_FRESH_AGE = 3
CLAIM_MAX_AGE = 10
CORE_SPAWN_RING_MANHATTAN = 2  # 12 surrounding tiles: d=1 plus d=2.

INFRA_SLOT_FIRST = 8
INFRA_SLOT_COUNT = 4
TURRET_SLOT_FIRST = 12
TURRET_SLOT_COUNT = 2
PROPOSAL_SLOT = 14
PROPOSAL_CHECK_SLOT = 15

INFRA_NONE = 0
INFRA_HARVESTER = 1
INFRA_CONVEYOR = 2
INFRA_SPLITTER = 3
INFRA_GUNNER = 4
INFRA_SENTINEL = 5
INFRA_CORE = 6

ENTITY_TO_INFRA = {
    EntityType.HARVESTER: INFRA_HARVESTER,
    EntityType.CONVEYOR: INFRA_CONVEYOR,
    EntityType.SPLITTER: INFRA_SPLITTER,
    EntityType.GUNNER: INFRA_GUNNER,
    EntityType.SENTINEL: INFRA_SENTINEL,
    EntityType.CORE: INFRA_CORE,
}
TARGET_VALUE = {
    INFRA_HARVESTER: 5,
    INFRA_CONVEYOR: 2,
    INFRA_SPLITTER: 2,
    INFRA_GUNNER: 3,
    INFRA_SENTINEL: 3,
    INFRA_CORE: 10,
}
TURRET_TYPES = (INFRA_GUNNER, INFRA_SENTINEL)

FACINGS = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)
FACING_DELTAS = ((0, -1), (1, 0), (0, 1), (-1, 0))

Proposal = namedtuple(
    "Proposal",
    "x y turret_type facing score frontier urgent frontier_choke generation",
)


def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _epoch(round_number):
    return (round_number // FRESHNESS_ROUNDS) & 0x7


def _age(now_epoch, then_epoch):
    return (now_epoch - then_epoch) & 0x7


def _pack_infra(x, y, type_code, freshness):
    if type_code == INFRA_NONE:
        return 0
    return ((x & 0x1F) | ((y & 0x1F) << 5)
            | ((type_code & 0x7) << 10) | ((freshness & 0x7) << 13))


def _unpack_infra(value, width, height):
    if value == 0:
        return None
    x = value & 0x1F
    y = (value >> 5) & 0x1F
    type_code = (value >> 10) & 0x7
    freshness = (value >> 13) & 0x7
    if x >= width or y >= height or type_code not in TARGET_VALUE:
        return None
    return (x, y, type_code, freshness)


def _pack_turret(x, y, type_code):
    if type_code not in TURRET_TYPES:
        return 0
    return (x & 0x1F) | ((y & 0x1F) << 5) | ((type_code & 0x7) << 10)


def _unpack_turret(value, width, height):
    if value == 0:
        return None
    x = value & 0x1F
    y = (value >> 5) & 0x1F
    type_code = (value >> 10) & 0x7
    if x >= width or y >= height or type_code not in TURRET_TYPES:
        return None
    return (x, y, type_code)


def _record_at(word, record_bits, index):
    return (word >> (record_bits * index)) & ((1 << record_bits) - 1)


def _replace_record(word, record_bits, index, value):
    mask = ((1 << record_bits) - 1) << (record_bits * index)
    return (word & ~mask) | ((value << (record_bits * index)) & mask)


def _pack_proposal(proposal):
    if proposal is None:
        return 0
    # derive the generation from the proposal itself so independently running
    # builder planners publish an identical word for an identical top choice.
    generation = ((proposal.x * 3 + proposal.y * 5
                   + proposal.turret_type * 7
                   + FACINGS.index(proposal.facing) * 11
                   + int(proposal.score)) & 0xF)
    type_code = proposal.turret_type
    facing_code = FACINGS.index(proposal.facing)
    score_band = max(-512, min(511, int(proposal.score))) + 512
    value = ((proposal.x & 0x1F)
             | ((proposal.y & 0x1F) << 5)
             | ((type_code & 0x7) << 10)
             | ((facing_code & 0x3) << 13)
             | (int(bool(proposal.frontier)) << 15)
             | (int(bool(proposal.urgent)) << 16)
             | (1 << 17)
             | ((score_band & 0x3FF) << 18)
             | ((generation & 0xF) << 28))
    return value & 0xFFFFFFFF


def _unpack_proposal(value, width, height):
    if not ((value >> 17) & 1):
        return None
    x = value & 0x1F
    y = (value >> 5) & 0x1F
    type_code = (value >> 10) & 0x7
    facing_code = (value >> 13) & 0x3
    if x >= width or y >= height or type_code not in TURRET_TYPES:
        return None
    score = ((value >> 18) & 0x3FF) - 512
    frontier = bool((value >> 15) & 1)
    urgent = bool((value >> 16) & 1)
    generation = (value >> 28) & 0xF
    return Proposal(x, y, type_code, FACINGS[facing_code], score,
                    frontier, urgent, frontier, generation)


def _proposal_fingerprint(value):
    return (value ^ (value >> 14)) & 0x3FFF


def _pack_claim(builder_num, distance, generation, round_number, proposal_word):
    return (((builder_num - 1) & 0x7)
            | ((min(distance, 63) & 0x3F) << 3)
            | ((generation & 0xF) << 9)
            | ((round_number & 0xF) << 13)
            | (1 << 17)
            | (_proposal_fingerprint(proposal_word) << 18))


def _unpack_claim(value, proposal_word, round_number):
    if not ((value >> 17) & 1):
        return None
    if ((value >> 18) & 0x3FFF) != _proposal_fingerprint(proposal_word):
        return None
    generation = (value >> 9) & 0xF
    if generation != ((proposal_word >> 28) & 0xF):
        return None
    claim_round = (value >> 13) & 0xF
    claim_age = ((round_number & 0xF) - claim_round) & 0xF
    if claim_age > CLAIM_MAX_AGE:
        return None
    return ((value & 0x7) + 1, (value >> 3) & 0x3F)


def _in_envelope(origin, target, type_code, facing_index):
    """Raw dev23 turret geometry; heuristic distances elsewhere are Manhattan."""
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    forward_x, forward_y = FACING_DELTAS[facing_index]
    forward = dx * forward_x + dy * forward_y
    if forward <= 0:
        return False
    if type_code == INFRA_GUNNER:
        lateral = abs(dx * forward_y - dy * forward_x)
        return lateral == 0 and dx * dx + dy * dy <= 13
    lateral = abs(dx * forward_y - dy * forward_x)
    return lateral <= 1 and dx * dx + dy * dy <= 32


def _covered_by_unknown_facing(turret, tile):
    origin = (turret[0], turret[1])
    type_code = turret[2]
    for facing_index in range(4):
        if _in_envelope(origin, tile, type_code, facing_index):
            return True
    return False


class TurretPlanner:
    """Per-builder shared-cache reader and resumable scorer."""

    def __init__(self, width, height, team_core):
        self.width = width
        self.height = height
        self.team_core = (team_core.x, team_core.y)

        self.infra_memory = {}
        self.turret_memory = {}
        self.pending_infra = {}
        self.pending_turrets = {}
        self.current_proposal = None
        self.current_claim = None
        self._proposal_word = 0

        self._infra_records = [None] * 8
        self._turret_records = [None] * 4
        self._raw_infra_words = [0] * 4
        self._raw_turret_words = [0] * 2

        self._dependency_signature = None
        self._scan_context = None
        self._scan_cursor = 0
        self._scan_complete = False
        self._top = []
        self.score_cache = {}

    # ------------------------------------------------------------------ store

    def sync_and_observe(self, ct):
        """Read the next-round snapshot, verify visible entries, and retry one write."""
        now_epoch = _epoch(ct.get_current_round())
        writes = {}

        self._raw_infra_words = [
            ct.read_store(INFRA_SLOT_FIRST + i) for i in range(INFRA_SLOT_COUNT)
        ]
        self._infra_records = []
        shared_positions = set()
        for word in self._raw_infra_words:
            for half in range(2):
                record = _unpack_infra(_record_at(word, 16, half),
                                       self.width, self.height)
                self._infra_records.append(record)
                if record is None:
                    continue
                x, y, type_code, freshness = record
                if _age(now_epoch, freshness) <= MAX_FRESH_AGE:
                    old = self.infra_memory.get((x, y))
                    if (old is None
                            or _age(now_epoch, freshness) < _age(now_epoch, old[1])):
                        self.infra_memory[(x, y)] = (type_code, freshness)
                    shared_positions.add((x, y, type_code))

        for key, (_, freshness) in list(self.infra_memory.items()):
            if _age(now_epoch, freshness) > MAX_FRESH_AGE:
                del self.infra_memory[key]
        for key, record in list(self.pending_infra.items()):
            if (key[0], key[1], record[0]) in shared_positions:
                del self.pending_infra[key]

        self._raw_turret_words = [
            ct.read_store(TURRET_SLOT_FIRST + i) & 0x03FFFFFF
            for i in range(TURRET_SLOT_COUNT)
        ]
        self._turret_records = []
        shared_turrets = set()
        for word in self._raw_turret_words:
            for half in range(2):
                record = _unpack_turret(_record_at(word, 13, half),
                                        self.width, self.height)
                self._turret_records.append(record)
                if record is not None:
                    x, y, type_code = record
                    self.turret_memory[(x, y)] = type_code
                    shared_turrets.add(record)
        for key, type_code in list(self.pending_turrets.items()):
            if (key[0], key[1], type_code) in shared_turrets:
                del self.pending_turrets[key]

        self._proposal_word = ct.read_store(PROPOSAL_SLOT)
        self.current_proposal = _unpack_proposal(
            self._proposal_word, self.width, self.height
        )
        self.current_claim = None
        if self.current_proposal is not None:
            self.current_claim = _unpack_claim(
                ct.read_store(PROPOSAL_CHECK_SLOT), self._proposal_word,
                ct.get_current_round()
            )

        # empty or changed visible tiles explicitly clear stale cache records
        verify_infra = {key: value[0]
                        for key, value in self.infra_memory.items()}
        for record in self._infra_records:
            if record is not None:
                verify_infra[(record[0], record[1])] = record[2]
        for (x, y), type_code in list(verify_infra.items()):
            pos = Position(x, y)
            if not ct.is_in_vision(pos):
                continue
            building_id = ct.get_tile_building_id(pos)
            actual = None
            if building_id is not None and ct.get_team(building_id) != ct.get_team():
                actual = ENTITY_TO_INFRA.get(ct.get_entity_type(building_id))
            if actual != type_code:
                self.infra_memory.pop((x, y), None)
                self.pending_infra.pop((x, y), None)
                self._clear_infra_position(x, y, writes)

        for (x, y), type_code in list(self.turret_memory.items()):
            pos = Position(x, y)
            if not ct.is_in_vision(pos):
                continue
            building_id = ct.get_tile_building_id(pos)
            actual = None
            if building_id is not None and ct.get_team(building_id) == ct.get_team():
                actual = ENTITY_TO_INFRA.get(ct.get_entity_type(building_id))
            if actual != type_code:
                del self.turret_memory[(x, y)]
                self.pending_turrets.pop((x, y), None)
                self._clear_turret_position(x, y, writes)

        # Any builder may originate sightings.  Non-model infrastructure is ignored.
        for building_id in ct.get_nearby_buildings():
            pos = ct.get_position(building_id)
            type_code = ENTITY_TO_INFRA.get(ct.get_entity_type(building_id))
            if type_code is None:
                continue
            if ct.get_team(building_id) != ct.get_team():
                self.infra_memory[(pos.x, pos.y)] = (type_code, now_epoch)
                self.pending_infra[(pos.x, pos.y)] = (type_code, now_epoch)
            elif type_code in TURRET_TYPES:
                self.turret_memory[(pos.x, pos.y)] = type_code
                self.pending_turrets[(pos.x, pos.y)] = type_code

        self._prune_memories(now_epoch)
        self._flush_one_infra(writes, now_epoch)
        self._flush_one_turret(writes)
        for slot, word in writes.items():
            ct.write_store(slot, word & 0xFFFFFFFF)
            if INFRA_SLOT_FIRST <= slot < INFRA_SLOT_FIRST + INFRA_SLOT_COUNT:
                self._raw_infra_words[slot - INFRA_SLOT_FIRST] = word
            elif TURRET_SLOT_FIRST <= slot < TURRET_SLOT_FIRST + TURRET_SLOT_COUNT:
                self._raw_turret_words[slot - TURRET_SLOT_FIRST] = word

    def _prune_memories(self, now_epoch):
        if len(self.infra_memory) > 8:
            ordered = sorted(
                self.infra_memory.items(),
                key=lambda item: (_age(now_epoch, item[1][1]),
                                  -TARGET_VALUE[item[1][0]], item[0]),
            )
            keep = {key for key, _ in ordered[:8]}
            for key in list(self.infra_memory):
                if key not in keep:
                    del self.infra_memory[key]
                    self.pending_infra.pop(key, None)
        if len(self.turret_memory) > 4:
            enemy_core = self._enemy_core()
            ordered = sorted(self.turret_memory,
                             key=lambda pos: (_manhattan(pos, enemy_core), pos))
            keep = set(ordered[:4])
            for key in list(self.turret_memory):
                if key not in keep:
                    del self.turret_memory[key]
                    self.pending_turrets.pop(key, None)

    def _clear_infra_position(self, x, y, writes):
        for index, record in enumerate(self._infra_records):
            if record is None or record[:2] != (x, y):
                continue
            slot_offset, half = divmod(index, 2)
            slot = INFRA_SLOT_FIRST + slot_offset
            word = writes.get(slot, self._raw_infra_words[slot_offset])
            word = _replace_record(word, 16, half, 0)
            writes[slot] = word
            self._infra_records[index] = None

    def _clear_turret_position(self, x, y, writes):
        for index, record in enumerate(self._turret_records):
            if record is None or record[:2] != (x, y):
                continue
            slot_offset, half = divmod(index, 2)
            slot = TURRET_SLOT_FIRST + slot_offset
            word = writes.get(slot, self._raw_turret_words[slot_offset])
            word = _replace_record(word, 13, half, 0)
            writes[slot] = word
            self._turret_records[index] = None

    def _flush_one_infra(self, writes, now_epoch):
        if not self.pending_infra:
            return
        key, (type_code, freshness) = min(
            self.pending_infra.items(),
            key=lambda item: (_age(now_epoch, item[1][1]),
                              -TARGET_VALUE[item[1][0]], item[0]),
        )
        x, y = key
        matching = [i for i, record in enumerate(self._infra_records)
                    if record is not None and record[:2] == (x, y)]
        if matching:
            index = matching[0]
        else:
            empty = [i for i, record in enumerate(self._infra_records)
                     if record is None]
            if empty:
                # A stable hash spreads simultaneous observers across the eight records.
                start = (x * 31 + y * 7 + type_code) & 7
                index = min(empty, key=lambda i: (i - start) & 7)
            else:
                index = max(
                    range(8),
                    key=lambda i: (_age(now_epoch, self._infra_records[i][3]),
                                   -TARGET_VALUE[self._infra_records[i][2]]),
                )
        slot_offset, half = divmod(index, 2)
        slot = INFRA_SLOT_FIRST + slot_offset
        word = writes.get(slot, self._raw_infra_words[slot_offset])
        packed = _pack_infra(x, y, type_code, freshness)
        writes[slot] = _replace_record(word, 16, half, packed)
        self._infra_records[index] = (x, y, type_code, freshness)

    def _flush_one_turret(self, writes):
        if not self.pending_turrets:
            return
        key, type_code = min(self.pending_turrets.items())
        x, y = key
        matching = [i for i, record in enumerate(self._turret_records)
                    if record is not None and record[:2] == (x, y)]
        if matching:
            index = matching[0]
        else:
            empty = [i for i, record in enumerate(self._turret_records)
                     if record is None]
            if empty:
                index = empty[0]
            else:
                # with no freshness bits available, deterministic replacement is
                # the only collision-safe policy that still admits newly built turrets.
                index = (x * 5 + y * 3 + type_code) & 3
        slot_offset, half = divmod(index, 2)
        slot = TURRET_SLOT_FIRST + slot_offset
        word = writes.get(slot, self._raw_turret_words[slot_offset])
        packed = _pack_turret(x, y, type_code)
        writes[slot] = _replace_record(word, 13, half, packed)
        self._turret_records[index] = (x, y, type_code)

    # --------------------------------------------------------------- behaviour

    def can_afford(self, ct, proposal=None):
        proposal = proposal or self.current_proposal
        if proposal is None:
            return False
        if proposal.turret_type == INFRA_GUNNER:
            cost = ct.get_gunner_cost()
        else:
            cost = ct.get_sentinel_cost()
        return ct.get_global_resources() >= cost + TITANIUM_RESERVE

    def try_passive_build(self, ct):
        proposal = self.current_proposal
        if proposal is None or not self.can_afford(ct, proposal):
            return None
        pos = Position(proposal.x, proposal.y)
        if ct.get_position().distance_squared(pos) > 2:
            return None
        if ct.get_action_cooldown() != 0:
            return None
        if proposal.turret_type == INFRA_GUNNER:
            if not ct.can_build_gunner(pos, proposal.facing):
                return None
            ct.build_gunner(pos, proposal.facing)
        else:
            if not ct.can_build_sentinel(pos, proposal.facing):
                return None
            ct.build_sentinel(pos, proposal.facing)
        self.record_built(ct, proposal)
        return proposal

    def record_built(self, ct, proposal):
        key = (proposal.x, proposal.y)
        self.turret_memory[key] = proposal.turret_type
        self.pending_turrets[key] = proposal.turret_type
        matching = [i for i, record in enumerate(self._turret_records)
                    if record is not None and record[:2] == key]
        if matching:
            index = matching[0]
        else:
            empty = [i for i, record in enumerate(self._turret_records)
                     if record is None]
            index = (empty[0] if empty else
                     (proposal.x * 5 + proposal.y * 3
                      + proposal.turret_type) & 3)
        slot_offset, half = divmod(index, 2)
        packed = _pack_turret(proposal.x, proposal.y, proposal.turret_type)
        word = _replace_record(self._raw_turret_words[slot_offset],
                               13, half, packed)
        self._raw_turret_words[slot_offset] = word
        self._turret_records[index] = (
            proposal.x, proposal.y, proposal.turret_type
        )
        ct.write_store(TURRET_SLOT_FIRST + slot_offset, word)
        # stop same-round followers from perpetuating the now-occupied proposal
        ct.write_store(PROPOSAL_SLOT, 0)
        ct.write_store(PROPOSAL_CHECK_SLOT, 0)

    def should_pursue_urgent(self, ct, my_num):
        proposal = self.current_proposal
        if (proposal is None or my_num < 1 or my_num > 8
                or not proposal.urgent or not proposal.frontier
                or not self.can_afford(ct, proposal)
                or ct.get_action_cooldown() != 0
                or ct.get_move_cooldown() != 0):
            return False
        target = (proposal.x, proposal.y)
        my_pos = ct.get_position()
        my_distance = _manhattan((my_pos.x, my_pos.y), target)
        if my_pos.distance_squared(Position(*target)) <= 2:
            return False
        candidate = (my_distance, my_num)
        claimed = None
        if self.current_claim is not None:
            claimed = (self.current_claim[1], self.current_claim[0])
        spawn_count = ct.read_store(0)
        elected = (spawn_count > 0
                   and ct.get_current_round() % spawn_count + 1 == my_num)
        if (elected and (claimed is None or candidate < claimed
                         or self.current_claim[0] == my_num)):
            claim_word = _pack_claim(
                my_num, my_distance, proposal.generation,
                ct.get_current_round(), self._proposal_word
            )
            ct.write_store(PROPOSAL_CHECK_SLOT, claim_word)
        # One elected builder updates the monotone minimum each round.  A new
        # better claim becomes visible next round; once visible only that
        # builder paths.  Dead/non-idle claimants eventually age out.
        return self.current_claim is not None and self.current_claim[0] == my_num

    # ---------------------------------------------------------------- scoring

    def advance(self, ct, full_map, my_num):
        """Incrementally rescore only during the same 6000-us spare-cycle cap."""
        analysis_job = mapanalysis.job
        if (analysis_job is None or analysis_job.phase != mapanalysis.DONE
                or not mapanalysis.region_partition
                or ct.get_cpu_time_elapsed() >= CPU_BUDGET_US):
            return

        signature = self._make_dependency_signature(analysis_job.version)
        if signature != self._dependency_signature:
            self._start_scan(full_map, signature)

        total = self.width * self.height * 2
        while (self._scan_cursor < total
               and ct.get_cpu_time_elapsed() < CPU_BUDGET_US):
            item = self._scan_cursor
            self._scan_cursor += 1
            tile_index, kind = divmod(item, 2)
            x, y = divmod(tile_index, self.height)
            type_code = INFRA_GUNNER if kind == 0 else INFRA_SENTINEL
            proposal = self._score_tile(x, y, type_code, full_map)
            self.score_cache[(x, y, type_code)] = proposal
            if proposal is not None:
                self._top.append(proposal)
                self._top.sort(key=self._proposal_sort_key, reverse=True)
                del self._top[3:]

        if self._scan_cursor >= total:
            self._scan_complete = True
            self._publish_if_writer(ct, my_num)

    def _make_dependency_signature(self, analysis_version):
        infra = tuple(sorted((x, y, value[0])
                             for (x, y), value in self.infra_memory.items()))
        turrets = tuple(sorted((x, y, type_code)
                              for (x, y), type_code in self.turret_memory.items()))
        chokes = tuple(mapanalysis.chokes)
        return (analysis_version, infra, turrets, chokes)

    def _start_scan(self, full_map, signature):
        self._dependency_signature = signature
        self._scan_cursor = 0
        self._scan_complete = False
        self._top = []
        self.score_cache = {}
        self._scan_context = self._build_region_context(full_map)

    def _enemy_core(self):
        cores = [(pos, value[1]) for pos, value in self.infra_memory.items()
                 if value[0] == INFRA_CORE]
        if cores:
            return min(cores, key=lambda item: _manhattan(self.team_core, item[0]))[0]
        # slot 7's symmetry encoding belongs to the map layer and is not defined
        # here.  Until an exact core sighting arrives, rotational opposition is
        # the only estimate that consumes no extra store bits.
        return (self.width - 1 - self.team_core[0],
                self.height - 1 - self.team_core[1])

    def _build_region_context(self, full_map):
        partition = mapanalysis.region_partition
        regions = set(value for value in partition if value >= 0)
        graph = {region: set() for region in regions}
        choke_regions = {}

        for choke in mapanalysis.chokes:
            tile, clearance = choke[0], choke[1]
            adjacent = set()
            max_radius = max(1, clearance + 2)
            for radius in range(1, max_radius + 1):
                for dx in range(-radius, radius + 1):
                    dy = radius - abs(dx)
                    for signed_dy in ({dy, -dy} if dy else {0}):
                        x, y = tile[0] + dx, tile[1] + signed_dy
                        if 0 <= x < self.width and 0 <= y < self.height:
                            region = partition[x * self.height + y]
                            if region >= 0:
                                adjacent.add(region)
                if len(adjacent) >= 2:
                    break
            adjacent = tuple(sorted(adjacent))
            choke_regions[tile] = adjacent
            for left in adjacent:
                for right in adjacent:
                    if left != right:
                        graph[left].add(right)

        own_region = self._nearest_region(self.team_core, partition)
        reachable = set()
        if own_region >= 0:
            stack = [own_region]
            reachable.add(own_region)
            while stack:
                region = stack.pop()
                for other in graph.get(region, ()):
                    if other not in reachable:
                        reachable.add(other)
                        stack.append(other)

        enemy_core = self._enemy_core()
        own_distance = {region: self.width + self.height + 1 for region in regions}
        enemy_distance = dict(own_distance)
        for x in range(self.width):
            for y in range(self.height):
                region = partition[x * self.height + y]
                if region < 0:
                    continue
                own_distance[region] = min(own_distance[region],
                                           _manhattan((x, y), self.team_core))
                enemy_distance[region] = min(enemy_distance[region],
                                             _manhattan((x, y), enemy_core))
        enemy_side = {region for region in regions
                      if enemy_distance[region] < own_distance[region]}
        frontier_regions = set()
        frontier_chokes = {}
        for choke, adjacent in choke_regions.items():
            own_adjacent = [r for r in adjacent if r not in enemy_side]
            enemy_adjacent = [r for r in adjacent if r in enemy_side]
            if own_adjacent and enemy_adjacent:
                for region in own_adjacent:
                    frontier_regions.add(region)
                    frontier_chokes.setdefault(region, set()).add(choke)

        return {
            "partition": partition,
            "reachable": reachable,
            "enemy_core": enemy_core,
            "frontier_regions": frontier_regions,
            "frontier_chokes": frontier_chokes,
        }

    def _nearest_region(self, origin, partition):
        best = -1
        best_distance = self.width + self.height + 1
        for x in range(self.width):
            for y in range(self.height):
                region = partition[x * self.height + y]
                if region < 0:
                    continue
                distance = _manhattan(origin, (x, y))
                if distance < best_distance:
                    best, best_distance = region, distance
        return best

    def _score_tile(self, x, y, type_code, full_map):
        context = self._scan_context
        if full_map[x][y] != 0:
            return None
        tile = (x, y)
        if _manhattan(tile, self.team_core) <= CORE_SPAWN_RING_MANHATTAN:
            return None
        if tile in self.turret_memory or tile in self.infra_memory:
            return None
        region = context["partition"][x * self.height + y]
        if region < 0 or region not in context["reachable"]:
            return None

        targets = [(pos, value[0]) for pos, value in self.infra_memory.items()]
        best_facing = -1
        best_face_terms = None
        best_frontier_choke = False
        for facing_index in range(4):
            covered_value = sum(
                TARGET_VALUE[target_type]
                for target_pos, target_type in targets
                if _in_envelope(tile, target_pos, type_code, facing_index)
            )
            covered_chokes = [
                choke for choke in mapanalysis.chokes
                if _in_envelope(tile, choke[0], type_code, facing_index)
            ]
            choke_coverage = len(covered_chokes)
            frontier_choke = any(
                choke[0] in context["frontier_chokes"].get(region, ())
                for choke in covered_chokes
            )
            approach = self._approach_tiebreak(tile, facing_index)
            terms = (W_COVER * covered_value + W_CHOKE * choke_coverage,
                     covered_value, choke_coverage, approach, -facing_index)
            if best_face_terms is None or terms > best_face_terms:
                best_face_terms = terms
                best_facing = facing_index
                best_frontier_choke = frontier_choke

        face_score, covered_value, choke_coverage = best_face_terms[:3]
        # A defensive emplacement must attack remembered infrastructure or a
        # detected corridor; safety distance alone may not create backfield spam.
        if covered_value == 0 and choke_coverage == 0:
            return None

        mutual = sum(1 for turret in self._friendly_turrets()
                     if _covered_by_unknown_facing(turret, tile))
        exposure = sum(1 for turret in self._enemy_turrets()
                       if _covered_by_unknown_facing(turret, tile))
        safe_distance = _manhattan(tile, context["enemy_core"])
        frontier = region in context["frontier_regions"]
        score = (face_score + W_MUTUAL * mutual + W_SAFE * safe_distance
                 - W_EXPOSED * exposure
                 - (0 if frontier else W_FRONTIER_PENALTY))
        urgent = score >= URGENT_THRESHOLD and best_frontier_choke
        return Proposal(x, y, type_code, FACINGS[best_facing], score,
                        frontier, urgent, best_frontier_choke, 0)

    def _friendly_turrets(self):
        return [(x, y, type_code)
                for (x, y), type_code in self.turret_memory.items()]

    def _enemy_turrets(self):
        return [(x, y, value[0]) for (x, y), value in self.infra_memory.items()
                if value[0] in TURRET_TYPES]

    def _approach_tiebreak(self, tile, facing_index):
        enemy = self._scan_context["enemy_core"]
        dx = enemy[0] - tile[0]
        dy = enemy[1] - tile[1]
        face_dx, face_dy = FACING_DELTAS[facing_index]
        return dx * face_dx + dy * face_dy

    @staticmethod
    def _proposal_sort_key(proposal):
        # prefer exact model score; deterministic secondary keys keep every
        # builder converged even if its cache iteration order differs.
        return (proposal.score, proposal.frontier_choke,
                proposal.turret_type == INFRA_SENTINEL,
                -proposal.x, -proposal.y, -FACINGS.index(proposal.facing))

    def _publish_if_writer(self, ct, my_num):
        spawn_count = ct.read_store(0)
        if spawn_count <= 0 or my_num < 1:
            return
        elected = ct.get_current_round() % spawn_count + 1
        if elected != my_num:
            return
        proposal = self._top[0] if self._top else None
        value = _pack_proposal(proposal)
        if ct.read_store(PROPOSAL_SLOT) != value:
            ct.write_store(PROPOSAL_SLOT, value)
            ct.write_store(PROPOSAL_CHECK_SLOT, 0)

    def draw_debug(self, ct):
        proposals = self._top
        if not proposals and self.current_proposal is not None:
            proposals = [self.current_proposal]
        for proposal in proposals[:3]:
            ct.draw_indicator_dot(Position(proposal.x, proposal.y), 0, 80, 255)
