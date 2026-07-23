"""IC3D bot — V16 "CLEAN REWRITE".

Every builder is a MINER first: rush titanium, build harvesters, wire them
home with short verified conveyor chains. Aggression and defense are simple,
opportunistic layers on top — no fragile multi-role state machines.

Verified mechanics this bot is built on (all tested empirically):
  - Harvester on ore outputs a 10-stack every 4 rounds to ANY adjacent
    building; first stack immediately. Adjacent-to-core harvesters need NO
    conveyors at all.
  - Wire chain: builder walks home in CARDINAL steps laying a conveyor under
    its own feet facing the direction of travel; last link faces the core.
  - Fed turret: a harvester DIRECTLY adjacent to a gunner/sentinel feeds it.
  - Sentinels/gunners must fire at ENEMY-OCCUPIED tiles (can_fire() is true
    for empty tiles too — firing there wastes the shot).
  - Launchers grab ADJACENT enemy builders and throw them within range²26
    (~5 tiles). Throwing "across the map" silently fails — that was the bug
    that made our launchers useless.
  - A position jump >1 tile means WE were launched: reset nav state.
  - A builder frozen ~55+ rounds is a zombie: self-destruct, respawn fresh.

Store slots:
  0 CORE_X | 1 CORE_Y | 2 HARV_COUNT | 3 (free) | 4 SPAWN_INDEX
  5 ENEMY_CORE | 6 THREAT | 7 THREAT_ROUND | 8 TURRET_ROUND

V43: SCRIPTED SMALL-MAP OPENING — on maps with area <= 260 (sprint, duel,
pinch, crossfire) the first two builders mass a fed-sentinel wall from turn 1
(economy later); the core holds the crew at 2 so sentinels stay cheap (+20%
scale each, same as a builder). Triggered by map AREA because the core-dist
point-mirror guess silently missed pinch (reflection map) and crossfire
(dist² 164 > the old 150 threshold) in every earlier "small map" check.
"""

import random

from fcode import Controller, Direction, EntityType, Environment, Position, Team

# flip to True for local stall-ledger telemetry (never ship True — file I/O
# per turn would eat the CPU budget; the server may also sandbox writes)
ECON_DEBUG = False


def _elog(line):
    open("econ_debug.log", "a").write(line + chr(10))

random.seed(20260711)  # reproducible runs (unseeded RNG made testing useless)

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

S_CORE_X, S_CORE_Y = 0, 1
S_HARV = 2
S_THREAT_TYPE = 3       # 1 = the broadcast threat is a SENTINEL, else 0
S_SPAWN = 4
S_ENEMY_CORE = 5
S_THREAT, S_THREAT_R, S_TURRET_R = 6, 7, 8
S_CREW = 9              # builders spawned so far (core-written)
S_TAXI, S_TAXI_R = 11, 12   # launcher taxi: requested destination + round
S_TAXI_ID = 13              # taxi: the REQUESTER's unit id — only they fly
S_GUN_N = 14                # cumulative defensive GUNNER builds (team-wide)
S_DEATH = 15                # core-inferred KILL ZONE: where own builders
                            # keep vanishing (packed pos, 0 = none) — the
                            # camped choke the walkers must route around

# Big-map defensive gunner budget for the WHOLE game. Oogway's sentinel
# roam farms our rebuild loop: every sniped gunner freed a live-count slot
# and the replacement cost +10% more (atoll: 62 gunner builds, 3 harvesters
# — gunner #62 costs ~340x base). Past the cap we concede local duels and
# keep mining: a lost harvester costs less than a lost Ti race.
# 2.2: tightened 12→6 — the Besvikomat gunner rush WANTS a home gunner
# war (cg_atoll: 26 counter-guns, 0 mined all game while their 2 leftover
# builders mined 4590). The war belongs to OUR siegers at THEIR core.
GUN_CAP = 6

# Siege doctrine knobs (the barrier-vs-gunner bake-off; variants override
# these three numbers only): rush gunners planted on arrival at their core,
# whether to barrier-seal their spawn ring, fed sentinels planted post-seal.
SIEGE_RUSH_GUNS = 3
SIEGE_SEAL = True
SIEGE_SENTS = 3

MAX_BUILDERS = 5        # +20% cost scaling per builder: keep the crew small
SIEGER_INDEX = 1        # FIRST builder rushes the enemy core immediately
RUSH_TI = 350           # once this rich (and nothing to claim/wire), sentinel-rush
RESERVE = 5             # never spend our last few Ti
THREAT_RAD_SQ = 100     # "near our core" = within 10 tiles
LAUNCH_RAD_SQ = 26      # launcher throw range (from the docs)

# SMALL-MAP SCRIPTED OPENING (the anti-blitz tempo answer). Trigger on map
# AREA, not core distance: the point-mirror guess is wrong on reflection-
# symmetric maps (pinch: guess dist²208, real 144) and crossfire is dist²164
# — both silently missed every "core-dist²<=150" small-map check we ever
# shipped. Area <= 260 selects exactly sprint(100)/duel(144)/pinch(252)/
# crossfire(256), and it's known on turn 1 from the map dims.
SMALL_AREA = 260
WALL_QUOTA = 8          # fed sentinels the opening tries to stand up
WALL_SPAWN_ROUND = 20   # core resumes spawning miners at quota or here —
#                         the 500-Ti bank is spent by ~t13; holding longer
#                         just delays the economy (crossfire: 2370 vs 7620)
WALL_LAST_ROUND = 80    # opening hard-stops here; economy takes over


def pack(p: Position) -> int:
    return ((p.x + 1) << 16) | (p.y + 1)


def unpack(v: int):
    if v == 0:
        return None
    return Position((v >> 16) - 1, (v & 0xFFFF) - 1)


def ncard(d: Direction) -> Direction:
    return {
        Direction.NORTH: Direction.NORTH, Direction.NORTHEAST: Direction.NORTH,
        Direction.EAST: Direction.EAST, Direction.SOUTHEAST: Direction.EAST,
        Direction.SOUTH: Direction.SOUTH, Direction.SOUTHWEST: Direction.SOUTH,
        Direction.WEST: Direction.WEST, Direction.NORTHWEST: Direction.WEST,
        Direction.CENTRE: Direction.NORTH,
    }[d]


# All launch-throw offsets within range²26, farthest first (best fling).
THROW_OFFSETS = sorted(
    [(dx, dy) for dx in range(-5, 6) for dy in range(-5, 6)
     if 4 < dx * dx + dy * dy <= LAUNCH_RAD_SQ],
    key=lambda o: -(o[0] * o[0] + o[1] * o[1]),
)


class Player:
    def __init__(self):
        # core
        self.num_spawned = 0
        # shared
        self.w = self.h = None
        self.team = None
        # builder nav
        self.role = None
        self.target = None
        self.last_pos = None
        self.stuck = 0
        self.core_pos = None
        self.core_tiles = None
        self.enemy_core = None
        self.explore_dir = None
        self.seen_ore = set()   # remembered unclaimed ore tiles (territory)
        # wiring state
        self.wiring = False
        self.wire_src = None
        self.wire_started = False
        # battery assembly (harvester + adjacent turret over 2 turns)
        self.batt_step = 0
        self.batt_G = None
        self.batt_dir = None
        self.batt_sent = False
        # defense bookkeeping
        self.launchers_built = 0
        self.gunners_built = 0
        # sieger
        self.siege_sents = 0
        self.sealed = set()
        # spawn index (1-based) + small-map flag
        self.idx = 0
        self.small = False
        # map memory for BFS
        self.walls = set()
        self.blocked = {}   # pos -> round learned (expires)
        # gradient field (BFS dist-to-core) for loop-free conveyor routing
        self.grad = None
        self.grad_round = -99
        self.grad_walls = -1
        self.last_claim = None

    # ------------------------------------------------------------ plumbing

    def run(self, ct: Controller) -> None:
        try:
            self._run(ct)
        except Exception as e:  # noqa: BLE001 — a crash forfeits the game
            import sys
            print(f"[ERR] {type(e).__name__}: {e}", file=sys.stderr)
        if ECON_DEBUG:
            try:
                self._econ_probe(ct)
            except Exception:
                pass

    def _econ_probe(self, ct) -> None:
        """IC3D_ECON_DEBUG=1 telemetry: each unit, every 5 rounds, logs every
        visible friendly harvester's logistics state — wired (has an
        accepting cardinal neighbour) and jammed (its output conveyor is
        holding a stack right now). Post-processed into the stall ledger."""
        rnd = ct.get_current_round()
        if rnd % 5:
            return
        for b in ct.get_nearby_buildings():
            if self._enemy(ct, b) or \
                    ct.get_entity_type(b) != EntityType.HARVESTER:
                continue
            hp = ct.get_position(b)
            wired, jammed = 0, 0
            for d in CARDINALS:
                n = hp.add(d)
                if not self._inb(n) or not ct.is_in_vision(n):
                    continue
                nb = ct.get_tile_building_id(n)
                if nb is None or self._enemy(ct, nb):
                    continue
                et2 = ct.get_entity_type(nb)
                if et2 == EntityType.CORE:
                    wired = 1
                    break
                if et2 in (EntityType.CONVEYOR, EntityType.SPLITTER):
                    wired = 1
                    try:
                        if ct.get_stored_resource(nb) is not None:
                            jammed += 1
                        else:
                            jammed = 0
                            break  # an EMPTY output exists: not jammed
                    except Exception:
                        pass
            _elog("%d %d %d w%d j%d" % (rnd, hp.x, hp.y, wired,
                                        1 if (wired and jammed) else 0))

    def _run(self, ct: Controller) -> None:
        if self.w is None:
            self.w = ct.get_map_width()
            self.h = ct.get_map_height()
            self.team = ct.get_team()
            self.small = self.w * self.h <= SMALL_AREA
        t = ct.get_entity_type()
        if t == EntityType.CORE:
            self._core(ct)
        elif t == EntityType.BUILDER_BOT:
            self._builder(ct)
        elif t == EntityType.GUNNER:
            self._gunner(ct)
        elif t == EntityType.SENTINEL:
            self._sentinel(ct)
        elif t == EntityType.LAUNCHER:
            self._launcher(ct)

    def _inb(self, p: Position) -> bool:
        return 0 <= p.x < self.w and 0 <= p.y < self.h

    def _enemy(self, ct, eid) -> bool:
        return ct.get_team(eid) != self.team

    def _read_core(self, ct) -> None:
        if self.core_pos is None:
            x, y = ct.read_store(S_CORE_X), ct.read_store(S_CORE_Y)
            if x or y:
                self.core_pos = Position(x, y)
                self.core_tiles = {Position(x + a, y + b) for a in (0, 1) for b in (0, 1)}

    def _enemy_core_guess(self) -> Position:
        if self.enemy_core is not None:
            return self.enemy_core
        if self.core_pos is None:
            return Position(self.w // 2, self.h // 2)
        return Position(self.w - 2 - self.core_pos.x, self.h - 2 - self.core_pos.y)

    def _find_enemy_core(self, ct):
        """Resolve the REAL enemy core: shared store first, own vision second
        (and broadcast a sighting). Returns None while unconfirmed."""
        if self.enemy_core is None:
            st = unpack(ct.read_store(S_ENEMY_CORE))
            if st is not None:
                self.enemy_core = st
            else:
                for b in ct.get_nearby_buildings():
                    if self._enemy(ct, b) and \
                            ct.get_entity_type(b) == EntityType.CORE:
                        self.enemy_core = ct.get_position(b)
                        ct.write_store(S_ENEMY_CORE, pack(self.enemy_core))
                        break
        return self.enemy_core

    def _guess_candidate(self, ct) -> Position:
        """Maps are symmetric by REFLECTION or rotation — the enemy core is
        at one of THREE mirrors of ours. The old point-mirror-only guess sent
        the twins rush wave to an empty corner (real core at the y-mirror);
        6 siege sentinels ringed vacant ground while she won the Ti race.
        Rank candidates by proximity to the last observed threat (her units
        come FROM her side); cross off candidates found empty."""
        if self.core_pos is None:
            return Position(self.w // 2, self.h // 2)
        x, y = self.core_pos.x, self.core_pos.y
        cands = [Position(self.w - 2 - x, self.h - 2 - y),
                 Position(self.w - 2 - x, y),
                 Position(x, self.h - 2 - y)]
        dead = getattr(self, "dead_cands", set())
        alive = [c for c in cands if (c.x, c.y) not in dead and self._inb(c)]
        if not alive:
            self.dead_cands = set()
            alive = [c for c in cands if self._inb(c)]
        th = unpack(ct.read_store(S_THREAT))
        if th is not None:
            alive.sort(key=lambda c: c.distance_squared(th))
        return alive[0]

    def _touch_core(self, ct, p: Position):
        """Direction from p to an adjacent tile of OUR core footprint, if any."""
        for d in CARDINALS:
            n = p.add(d)
            if not self._inb(n):
                continue
            b = ct.get_tile_building_id(n)
            if b is not None and not self._enemy(ct, b) and ct.get_entity_type(b) == EntityType.CORE:
                return d
        return None

    # ---------------------------------------------------------------- core

    def _core(self, ct: Controller) -> None:
        p = ct.get_position()
        ct.write_store(S_CORE_X, p.x)
        ct.write_store(S_CORE_Y, p.y)
        ct.write_store(S_CREW, self.num_spawned)
        # 2.2.0 GLOBAL AMMO: turrets fire from a team-wide pool only the
        # core can fill (1:1 Ti, once per turn, FREE action — never costs a
        # spawn). No pool = every turret is scrap; every converted Ti is Ti
        # the economy never sees. Policy: small standing buffer so gunners
        # (2/shot) always answer; deepen under an active turret threat
        # (sentinel shots cost 10). Convert surplus only — never starve the
        # builder budget.
        try:
            ammo = ct.get_global_ammo()
            want = 80 if self._turret_threat(ct) else 30
            if ammo < want:
                surplus = (ct.get_global_resources()
                           - ct.get_builder_bot_cost() - 40)
                amt = min(want - ammo, surplus, 50)
                if amt > 0 and ct.can_convert_ammo(amt):
                    ct.convert_ammo(amt)
        except Exception:
            pass
        # THE CORE WATCHES ITS OWN BACK: threat detection used to rely on our
        # builders' vision — when a siege killed the home units first, nobody
        # was left to SEE it, the threat flag went stale, and no recall fired
        # (deaths at t162-290 with zero response). The core has vision²36 and
        # never dies early: it broadcasts sieges itself, every single round.
        # PRIORITISED threat broadcast: the first-found enemy used to win the
        # flag — her creeping BUILDERS in front hogged it while her SENTINELS
        # behind them shelled the core from range²32 (sprint replay: we built
        # 30 gunners at the dancers and never once targeted the artillery).
        # Priority: sentinel > gunner/launcher > builder; nearest within class.
        best_ep, best_key = None, None
        for eid in ct.get_nearby_entities():
            if not self._enemy(ct, eid):
                continue
            et = ct.get_entity_type(eid)
            ep = ct.get_position(eid)
            if et == EntityType.SENTINEL:
                rank = 0
            elif et == EntityType.GUNNER:
                rank = 1
            elif et == EntityType.LAUNCHER:
                # launchers deal ZERO damage — they only throw builders.
                # Ranking them turret-grade let Oogway's 20-launcher spam
                # bait us into 34 gunners / 3 harvesters on atoll (0-3
                # there, all Ti races). Track position, never siege-flag.
                rank = 2
            elif et == EntityType.BUILDER_BOT:
                rank = 3
            else:
                continue
            key = (rank, ep.distance_squared(p))
            if best_key is None or key < best_key:
                best_key, best_ep = key, ep
        if best_ep is not None:
            ct.write_store(S_THREAT, pack(best_ep))
            ct.write_store(S_THREAT_R, ct.get_current_round())
            # broadcast the TYPE too: builders (vision²20) often can't see a
            # sentinel shelling from range²32, so their counter-sentinel
            # check silently failed and they answered with out-ranged
            # gunners (twins loss t150: 17 gunners, 0 counter-sentinels).
            ct.write_store(S_THREAT_TYPE, 1 if best_key[0] == 0 else 0)
            # A REAL turret (sentinel/gunner, rank<=1) is a siege signal. An
            # enemy BUILDER near the core is turret-GRADE only on SMALL maps
            # (blitzes plant fast). On BIG maps the econ swarms (Pendolino
            # 30 builders, Oogway) ALWAYS have a builder near our core —
            # flagging that as a "siege" made us bleed economy into useless
            # gunners (hive vs Pendolino: 18 gunners built, 0 enemy turrets,
            # 4 harvesters, lost the Ti race). Only real turrets siege.
            # Builder near core: small maps flag unconditionally (blitzes
            # too fast to sort); big maps flag only PLANTERS (bare-ground
            # builders — Barbie's runestone t97 blitz), never miners on ore
            # (Pendolino/Oogway econ swarms — the v71 phantom-siege bleed).
            if best_key[0] <= 1 or (best_ep.distance_squared(p) <= 36
                                    and (self.small or self._planter(ct, best_ep))):
                ct.write_store(S_TURRET_R, ct.get_current_round())
        # big maps take a bigger crew: Atlas covers longship with 8 builders
        # and 13 harvesters against our hard 5 (4 harvesters all game). The
        # gradient grid wires in parallel, so extra miners now pay for
        # themselves; small maps keep the lean wall crew.
        max_b = MAX_BUILDERS if self.small else 14
        # PEACE DIVIDEND (small maps): the wall doctrine holds the crew at
        # 5 to keep sentinels cheap — right against blitzers, but an econ
        # opponent never triggers it and out-claims us 5:1 (Oogway
        # crossfire: 26 builders vs our hard 5; we mined 2.3 Ti/round even
        # unopposed). No turret threat by t100 = the blitz isn't coming —
        # expand to a mining crew.
        if (self.small and ct.get_current_round() > 100
                and not self._turret_threat(ct)):
            max_b = 10
        if (self.num_spawned >= 7 and ct.get_global_resources()
                < ct.get_builder_bot_cost() + 100):
            return  # crew beyond 7 comes from surplus only
        if self.num_spawned >= max_b or ct.get_unit_count() >= 45:
            return
        # SMALL-MAP OPENING: builders add +20% cost scale EACH — the same as
        # a sentinel. Hold the crew at 2 while the wall goes up so sentinels
        # stay cheap; miners spawn once the wall stands (or the window ends).
        if self.small and self.num_spawned >= 2 and \
                ct.get_current_round() <= WALL_SPAWN_ROUND:
            sents = 0
            for b in ct.get_nearby_buildings():
                if not self._enemy(ct, b) and \
                        ct.get_entity_type(b) == EntityType.SENTINEL:
                    sents += 1
            quota = WALL_QUOTA
            if self.w * self.h > 150 and not ct.read_store(S_TURRET_R):
                quota = 3  # lean insurance until contact (pinch-class only)
            if sents < quota:
                return
        # SPAWN SAFETY: an enemy turret covering our doorstep means every
        # respawned builder dies on arrival (replay: 12 deaths on one tile,
        # t53-67 — a titanium hemorrhage). Hold spawns while it's hot.
        # ...but CAP the hold: a parked (even ammo-dry) enemy sentinel kept
        # this gate closed for ~990 straight rounds on pinch — 2 builders all
        # game, titanium race unwinnable. 12 rounds of caution, then spawn.
        # DOORSTEP-DEATH STREAK: the 12-round cap alone can't tell a DRY
        # parked sentinel (pinch: safe to spawn past it) from a FED one
        # (runestone d52785ff g1: 13 spawns one-shot on the same tile
        # t33-47, +20% cost each — economy dead by t50). Evidence decides:
        # if the last spawns VANISHED within 2 rounds, she's fed — hold
        # until the threat goes stale, no cap. If spawns survive, spawn on.
        rnd = ct.get_current_round()
        own_b = 0
        cur = {}
        for e in ct.get_nearby_entities():
            if self._enemy(ct, e):
                continue
            if ct.get_entity_type(e) == EntityType.BUILDER_BOT:
                own_b += 1
                cur[e] = ct.get_position(e)
        # KILL-ZONE INFERENCE: the rush camps one choke and one-clips every
        # walker crossing it (cg_atoll: 11 deaths on one tile t45-57). The
        # core watches its own builders VANISH: 2+ vanishing points within
        # dsq9 in 25 rounds = a kill zone, published for miners to detour.
        prev = getattr(self, "own_seen", {})
        spots = getattr(self, "death_spots", [])
        for uid, up in prev.items():
            if uid not in cur and up.distance_squared(p) <= 18:
                spots.append((up, rnd))
        self.death_spots = [(sp, r0) for (sp, r0) in spots if rnd - r0 <= 25]
        self.own_seen = cur
        zone = None
        for (sp, _) in self.death_spots:
            if sum(1 for (sq, _) in self.death_spots
                   if sq.distance_squared(sp) <= 9) >= 2:
                zone = sp
                break
        # fresh spawns die BEFORE the core ever observes them (spawned
        # after our turn, dead before the next) — id-tracking is blind to
        # spawn-camping. The count-based streak sees it, and the camp is
        # wherever we last spawned.
        if (zone is None and getattr(self, "death_streak", 0) >= 2
                and getattr(self, "last_spawn_pos", None) is not None):
            zone = self.last_spawn_pos
        ct.write_store(S_DEATH, pack(zone) if zone is not None else 0)
        if getattr(self, "last_spawn_r", 0) and rnd == self.last_spawn_r + 2:
            if own_b <= getattr(self, "alive_at_spawn", 0):
                self.death_streak = getattr(self, "death_streak", 0) + 1
            else:
                self.death_streak = 0
        tr = ct.read_store(S_TURRET_R)
        if not tr or rnd - tr > 20:
            self.death_streak = 0
        tp = unpack(ct.read_store(S_THREAT)) if tr else None
        if tr and rnd - tr <= 8 and tp is not None \
                and tp.distance_squared(p) <= 40:
            self.spawn_hold = getattr(self, "spawn_hold", 0) + 1
            if self.spawn_hold <= 12 or getattr(self, "death_streak", 0) >= 2:
                return
        else:
            self.spawn_hold = 0
        if ct.get_global_resources() < ct.get_builder_bot_cost():
            return
        # under threat, spawn on the tile FARTHEST from the shooter — not a
        # random one that may sit in her band
        dirs = random.sample(DIRECTIONS, len(DIRECTIONS))
        if tp is not None and rnd - tr <= 8:
            dirs.sort(key=lambda d: -p.add(d).distance_squared(tp))
        for d in dirs:
            sp = p.add(d)
            if self._inb(sp) and ct.can_spawn(sp):
                ct.spawn_builder(sp)
                self.num_spawned += 1
                self.last_spawn_r = rnd
                self.last_spawn_pos = sp
                self.alive_at_spawn = own_b
                return

    # ------------------------------------------------------------- builder

    def _builder(self, ct: Controller) -> None:
        pos = ct.get_position()
        self._read_core(ct)

        # remember walls for BFS + ORE for territory memory. On big sparse
        # maps (hive 25x25: ~16 ore one-per-region) blind exploration only
        # ever claims the ~5 tiles near home — we mine ~6.5k vs the top
        # bots' 14k. A miner that walks PAST distant ore now remembers it
        # and comes back, so the whole map's ore gets claimed over time.
        for tile in ct.get_nearby_tiles():
            env = ct.get_tile_env(tile)
            if env == Environment.WALL:
                self.walls.add(tile)
            elif env == Environment.ORE_TITANIUM:
                if ct.get_tile_building_id(tile) is None:
                    self.seen_ore.add(tile)
                else:
                    self.seen_ore.discard(tile)  # claimed: forget it
        now = ct.get_current_round()
        for k in [k for k, r in self.blocked.items() if now - r > 40]:
            del self.blocked[k]

        # one-time role (core spawns <=1 builder/round: no races).
        # The user's doctrine: ONE sealer circles their core with barriers,
        # ONE or TWO defend our core (two on small maps where blitzes land),
        # the rest go claim titanium.
        if self.role is None:
            idx = ct.read_store(S_SPAWN) + 1
            ct.write_store(S_SPAWN, idx)
            self.idx = idx
            if self.small:
                # scripted opening: the first two builders mass the sentinel
                # wall (no sieger — a rusher walking into HER wall is a
                # donated builder); later spawns run the home doctrine.
                if idx <= 2:
                    self.role = "wall"
                elif idx == 3:
                    self.role = "defender"
                else:
                    self.role = "miner"
            elif idx in (1, 2):
                # TWO dedicated siegers on big maps: early forward counter-
                # pressure (sentinels at THEIR core force them to defend,
                # not siege ours). One sieger (v69) wasn't enough — Barbie
                # sieged freely and core-killed our thin economy. Dedicated
                # siegers establish pressure EARLIER than the old part-time
                # miner rush AND free every miner for full economy.
                self.role = "sieger"
            elif idx in (3, 4):
                self.role = "defender"
            else:
                self.role = "miner"

        # launched by an enemy? (normal move <=1 tile) -> reset stale nav
        if self.last_pos is not None and pos.distance_squared(self.last_pos) > 2:
            self.wiring = False
            self.wire_src = None
            self.wire_started = False
            self.batt_step = 0
            self.target = None
            self.explore_dir = None
            self.stuck = 0

        self.stuck = self.stuck + 1 if self.last_pos == pos else 0
        self.last_pos = pos

        # zombie escape: frozen for ages = boxed in and useless forever
        if self.stuck > 55:
            try:
                ct.self_destruct()
            except Exception:
                pass
            return

        self._scan_threat(ct)

        if self.role == "sieger":
            self._sieger(ct)
        elif self.role == "wall":
            self._wall(ct)
        elif self.role == "defender":
            self._defender(ct)
        else:
            self._miner(ct)

    def _scan_threat(self, ct) -> None:
        """Broadcast enemies near OUR core so miners mount a defense."""
        if self.core_pos is None:
            return
        for eid in ct.get_nearby_entities():
            if not self._enemy(ct, eid):
                continue
            et = ct.get_entity_type(eid)
            ep = ct.get_position(eid)
            dsq = ep.distance_squared(self.core_pos)
            # launchers excluded: 0 damage, throw-only — not turret-grade
            turret = et in (EntityType.GUNNER, EntityType.SENTINEL)
            close_builder = et == EntityType.BUILDER_BOT and dsq <= 36
            # SMALL MAPS (cores close): a blitz plants turrets by t40-70 — too
            # fast to answer after the fact. Treat their BUILDER near our core
            # as a lethal (turret-grade) threat so defenses go up in time.
            small_map = (self.core_pos is not None and
                         self.core_pos.distance_squared(self._enemy_core_guess()) <= 150)
            if (turret and dsq <= THREAT_RAD_SQ) or close_builder:
                ct.write_store(S_THREAT, pack(ep))
                ct.write_store(S_THREAT_R, ct.get_current_round())
                ct.write_store(S_THREAT_TYPE,
                               1 if et == EntityType.SENTINEL else 0)
                if turret or (close_builder
                              and (small_map or self._planter(ct, ep))):
                    ct.write_store(S_TURRET_R, ct.get_current_round())
                return

    def _threat(self, ct):
        r = ct.read_store(S_THREAT_R)
        if r and ct.get_current_round() - r <= 12:
            return unpack(ct.read_store(S_THREAT))
        return None

    def _turret_threat(self, ct) -> bool:
        r = ct.read_store(S_TURRET_R)
        return bool(r and ct.get_current_round() - r <= 20)

    def _planter(self, ct, ep: Position) -> bool:
        """Blitz-vs-swarm discriminator for an enemy builder near our core.
        Pendolino/Oogway ECON builders near the core are MINING — standing
        on or beside ore. Barbie's BLITZ builder is on bare ground (it came
        to plant a turret: runestone kill t97 once big-map builders stopped
        flagging). Bare ground ⇒ planter ⇒ turret-grade."""
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                t = Position(ep.x + dx, ep.y + dy)
                if (0 <= t.x < self.w and 0 <= t.y < self.h
                        and ct.is_in_vision(t)
                        and ct.get_tile_env(t) == Environment.ORE_TITANIUM):
                    return False
        return True

    # ----------------------------------------------------- small-map wall

    def _cork_tiles(self, ct):
        """Corridor gaps on WALL-BAND maps (pinch: rows 8-9 are 12/14 wall
        with a 2-wide gap). The gap is the map's only land route — corking
        it with 3-Ti barriers stops enemy trunks AND builders cold (enemy
        builders cannot remove barriers: impassable means they cannot stand
        on one to attack it). We reopen at will with free destroy().
        Detection uses learned walls; can_build_barrier validates at build
        time, so unseen tiles just get skipped."""
        rows = {}
        for wpos in self.walls:
            rows[wpos.y] = rows.get(wpos.y, 0) + 1
        best = None
        for y, n in rows.items():
            if n >= self.w - 4 and 2 < y < self.h - 3:
                if best is None or (self.core_pos is not None and
                                    abs(y - self.core_pos.y) <
                                    abs(best - self.core_pos.y)):
                    best = y
        if best is None:
            return []
        gaps = []
        for x in range(self.w):
            t = Position(x, best)
            if t not in self.walls:
                gaps.append(t)
        return gaps if 0 < len(gaps) <= 3 else []

    def _wall_aim(self, ct):
        """Where the opening points its sentinels: the freshest threat first
        (her advancing wall IS the fight — can_fire_from locks onto it), then
        the enemy core once seen, then the mirrored guess. On reflection-
        symmetric maps (pinch!) the point-mirror guess is wrong, so first
        contact must re-aim the wall — never bake the guess into a facing we
        can't change (sentinels never rotate)."""
        if self.enemy_core is None:
            st = unpack(ct.read_store(S_ENEMY_CORE))
            if st is not None:
                self.enemy_core = st
            else:
                for b in ct.get_nearby_buildings():
                    if self._enemy(ct, b) and \
                            ct.get_entity_type(b) == EntityType.CORE:
                        self.enemy_core = ct.get_position(b)
                        ct.write_store(S_ENEMY_CORE, pack(self.enemy_core))
                        break
        th = self._threat(ct)
        if th is not None:
            return th
        if self.enemy_core is not None:
            return self.enemy_core
        return self._enemy_core_guess()

    def _wall_sents(self, ct) -> int:
        """Live friendly sentinels near home — the wall's real strength (a
        lifetime counter would keep 'counting' sentinels she already shot)."""
        if self.core_pos is None:
            return 0
        n = 0
        for b in ct.get_nearby_buildings():
            if (not self._enemy(ct, b)
                    and ct.get_entity_type(b) == EntityType.SENTINEL
                    and ct.get_position(b).distance_squared(self.core_pos)
                    <= THREAT_RAD_SQ):
                n += 1
        return n

    def _wall(self, ct: Controller) -> None:
        """SCRIPTED SMALL-MAP OPENING: on the four blitz maps Barbie stands
        ~12 fed sentinels by t40 and our reactive counters arrive too few,
        too late. Both opening builders mass fed sentinel batteries between
        our core and hers from turn 1 — economy comes after. The wall
        harvesters become that economy: they read as orphans, so the miners
        wire them home once the crew spawns."""
        pos = ct.get_position()
        aim = self._wall_aim(ct)

        # finish a battery in progress
        if self.batt_step > 0:
            if ct.get_action_cooldown() == 0:
                self._battery(ct, aim, self.batt_sent)
            return

        sents = self._wall_sents(ct)
        # ADAPTIVE QUOTA on pinch-class maps (area > 200): 3 sentinels of
        # insurance up front; the full wall only once a turret threat has
        # EVER been flagged. Pure-econ opponents (Pendolino) never trip it
        # — the old unconditional 8 was ~450 Ti of race handicap, and pinch
        # was the one map EVERY rival still farmed us on.
        quota = WALL_QUOTA
        # lean-until-contact EVERYWHERE: Ijti (1487!) took sprint+duel Ti
        # races off the unconditional full wall — per-GAME Elo makes every
        # dropped game vs the bottom half pure rating bleed. Blitzers trip
        # the flag by t10 and get the full wall exactly as before.
        # blitz maps (area<=150: sprint/duel) keep the FULL wall — Oogway
        # cracked the lean one at t115, Barbie at t101: contact->snap-back
        # is too slow when the rush lands by t15. Lean stays for
        # pinch-class maps where the threat is economic, not blitz.
        lean = self.w * self.h > 150 and not ct.read_store(S_TURRET_R)
        if lean:
            quota = 3
        # CONVERT only at the FULL quota or the window's end. On a lean
        # quota the openers STAND BY in wall role (claiming/wiring below)
        # — v63 converted them at 3, so when the pod arrived and the quota
        # snapped to 8 there was nobody left to build it (Pendolino ported
        # their pod to pinch: CD t202/271/271 through the lean wall).
        if sents >= WALL_QUOTA or ct.get_current_round() > WALL_LAST_ROUND:
            self.role = "defender" if self.idx == 1 else "miner"
            self.target = None
            return
        standby = sents >= quota  # lean quota met: hold, don't build more

        # standing on an enemy conveyor: free kill
        b = ct.get_tile_building_id(pos)
        if b is not None and self._enemy(ct, b):
            if ct.get_action_cooldown() == 0 and ct.can_fire(pos):
                ct.fire(pos)
                return

        # UNDER BOMBARDMENT (both f23a916a losses = a sentinel parked beside
        # the wall, outside every fixed facing, shelling the core unanswered):
        # opener #1 heal-tanks the core, opener #2 builds an ENGAGEABLE
        # counter-battery on the parked gun; both heal when it's dire.
        hurt = self._core_hurt(ct)
        th = self._threat(ct)
        if hurt > 0 and self.idx == 1 and self._heal_core(ct):
            return
        if (th is not None and self._turret_threat(ct)
                and ct.get_action_cooldown() == 0):
            _, engage = self._live_defense(ct, th)
            if engage < 1:
                th_s = bool(ct.read_store(S_THREAT_TYPE))
                if not th_s and self._counter_gun(ct, th):
                    return  # 2.2: instant free-placement counter for gunners
                if self._battery(ct, th, sentinel=th_s, must_engage=True):
                    return
        if hurt > 40 and self._heal_core(ct):
            return

        have = ct.get_global_resources()
        # SPAWN BUDGET: with the heal drain + wall spending the bank never
        # reached a builder's cost — sprint (64d5fe7c g1) ran the whole game
        # on 2 builders, no miners, and lost the race by 14%. Once the
        # opening window closes, a small crew banks a builder before any
        # further wall spending.
        reserve = RESERVE
        if (ct.read_store(S_CREW) < 4
                and ct.get_current_round() > WALL_SPAWN_ROUND):
            reserve += ct.get_builder_bot_cost()
        pair = ct.get_sentinel_cost() + ct.get_harvester_cost() + reserve
        if ct.get_action_cooldown() == 0:
            # a fresh harvester+sentinel pair beats hanging every sentinel
            # off one feeder: a harvester makes one 10-stack (= ONE sentinel
            # shot) per 4 rounds, shared by everything adjacent.
            if not standby and have >= pair and \
                    self._battery(ct, aim, sentinel=True):
                return
            if (not standby and have >= ct.get_sentinel_cost() + reserve
                    and self._turret_by_harvester(ct, aim, sentinel=True)):
                return
            # can't afford a sentinel: claim adjacent ore anyway — every
            # wall harvester is future ammo AND future economy (+5% scale)
            if (have >= ct.get_harvester_cost() + reserve
                    and self._build_harvester(ct)):
                return
            # one launcher once the wall has teeth: flings her wall-builders
            if sents >= 3:
                live_l, _ = self._live_defense(ct)
                if live_l < 1 and self._build_launcher(ct):
                    return
            self._heal(ct)
        # WAITING ON TITANIUM: wire the wall harvesters home. Without this
        # the opening starves itself — harvesters feeding only sentinels
        # deliver nothing, and 2.5/round passive can never buy the next
        # 60-Ti sentinel (or the 80-Ti miners after it). First lab run:
        # duel/crossfire/pinch all 0/4 vs champion on pure titanium.
        # THE CORK: on corridor maps, plug the wall-band gap with barriers
        # (Pendolino pinch kill = trunk THROUGH the gap feeding a shielded
        # splitter pod at our ring, CD t202-327 through both wall designs).
        if sents >= 2 and ct.get_action_cooldown() == 0 and \
                ct.get_global_resources() >= ct.get_barrier_cost() + RESERVE:
            for t in self._cork_tiles(ct):
                try:
                    if ct.is_in_vision(t) and ct.get_tile_building_id(t) is not None:
                        continue  # already corked (or something stands there)
                except Exception:
                    pass
                if pos.distance_squared(t) <= 2:
                    if ct.can_build_barrier(t):
                        ct.build_barrier(t)
                        return
                    continue
                self.target = t
                self._step_toward(ct, t)
                return

        # ECONOMY INTERLEAVE: after 4 sentinels (enough early defense), wire
        # wall harvesters to the CORE even while we could afford more — they
        # then ALTERNATE feeding sentinel + core, giving titanium delivery.
        # Without this the full sprint wall delivers 0 to core and LOSES the
        # titanium tiebreak vs econ opponents (Pendolino/Ijti: 4647 vs 2151,
        # us 0 mined — pendmic reproduces it). Blitz defense keeps its first
        # 4 sentinels + snap-back; the reactive layer covers the rest.
        if have < pair or standby or sents >= 4:
            if self.wiring:
                self._wire_step(ct)
                return
            orphan = self._find_orphan_harvester(ct)
            if orphan is not None:
                if abs(pos.x - orphan.x) + abs(pos.y - orphan.y) == 1:
                    self.wiring = True
                    self.wire_src = orphan
                    self.wire_started = True
                    self.wire_len = 0
                    self._wire_step(ct)
                    return
                feeds = [orphan.add(d) for d in CARDINALS
                         if self._inb(orphan.add(d))
                         and ct.is_tile_passable(orphan.add(d))]
                if feeds:
                    goal = min(feeds, key=lambda q: q.distance_squared(pos))
                    self.target = goal
                    self._step_toward(ct, goal)
                    return

        # position: stand by free ore on OUR side (all builds above happen
        # adjacent to us), else hold the lane a few tiles toward them.
        if self.core_pos is not None:
            goal, best = None, None
            for t in ct.get_nearby_tiles():
                if ct.get_tile_env(t) != Environment.ORE_TITANIUM:
                    continue
                if ct.get_tile_building_id(t) is not None:
                    continue
                if t.distance_squared(self.core_pos) > 50:
                    continue
                d = t.distance_squared(pos)
                if best is None or d < best:
                    best, goal = d, t
            if goal is not None and pos.distance_squared(goal) > 2:
                self.target = goal
                self._step_toward(ct, goal)
                return
            if goal is None:
                d = self.core_pos.direction_to(aim)
                if d != Direction.CENTRE:
                    dx, dy = d.delta()
                    anchor = Position(
                        min(max(self.core_pos.x + dx * 3, 1), self.w - 2),
                        min(max(self.core_pos.y + dy * 3, 1), self.h - 2))
                    if pos.distance_squared(anchor) > 2:
                        self.target = anchor
                        self._step_toward(ct, anchor)
                        return
        # shuffle if stuck so the opening never freezes
        if self.stuck >= 6:
            for d in random.sample(CARDINALS, len(CARDINALS)):
                if self._inb(pos.add(d)) and ct.can_move(d):
                    ct.move(d)
                    return

    # ----------------------------------------------------------- defender

    def _defender(self, ct: Controller) -> None:
        """Dedicated home defense (the user's doctrine): stay by our core,
        keep a launcher + garrison sentinel standing, answer turret pushes
        with engageable batteries, and never wander off. HARD CAP on turret
        count -- V34's uncapped honest-defense counting planted 11 sentinels
        in one game and bled the economy dry."""
        pos = ct.get_position()

        # free sabotage: standing on an enemy conveyor/splitter -> shoot it
        b = ct.get_tile_building_id(pos)
        if b is not None and self._enemy(ct, b):
            if ct.get_action_cooldown() == 0 and ct.can_fire(pos):
                ct.fire(pos)
                return

        # finish a defense battery in progress
        if self.batt_step > 0:
            if ct.get_action_cooldown() == 0:
                self._battery(ct, self._threat(ct), self.batt_sent)
            return

        # starve leech pods near home first — free and decisive
        if self._feed_denial(ct):
            return

        # under a turret siege: cut the SAFE trunk tiles feeding it (this
        # may step outside the guard ring — it's bounded to dsq 64 of core)
        if self._cut_trunk(ct):
            return

        # POD EXCURSION, band-aware take two: stand-off pods with their own
        # harvester leave must_engage with no legal spot from the ring
        # (runestone t122: ZERO turrets built). Walk to the pod AROUND its
        # published kill band (_step_safe) and build the counter fed by HER
        # ore once close. The naive version tripled kills-against; the safe
        # walk holds position when no band-free path exists.
        th_x = self._threat(ct)
        if (th_x is not None and self._turret_threat(ct)
                and self.core_pos is not None
                and pos.distance_squared(self.core_pos) <= 64
                and pos.distance_squared(th_x) > 10):
            _, engage_x = self._live_defense(ct, th_x)
            if engage_x == 0:
                self.target = th_x
                self._step_safe(ct, th_x)
                return

        if self.core_pos is None:
            self._move(ct)
            return

        # stay home: drift back inside the guard ring
        if pos.distance_squared(self.core_pos) > 20:
            self.target = self.core_pos
            self._step_toward(ct, self.core_pos)
            return

        # hard ceiling on ALL live turrets near home (engageable or not)
        _, live_all = self._live_defense(ct)

        # standing kit: one launcher + one garrison sentinel, always
        if ct.get_action_cooldown() == 0:
            liveL, _ = self._live_defense(ct)
            if liveL < 1 and self._build_launcher(ct):
                return
            # GUNNER garrison: sentinels can NEVER rotate (rotate() is a
            # gunner-only API) — a fixed sentinel aimed at a guessed approach
            # is scrap the moment the attack comes from anywhere else. Gunners
            # rotate for 10 Ti: they are the ONLY adaptive defense.
            if live_all < 1 and self._battery(ct, self._enemy_core_guess(), sentinel=False):
                return

        # turret push: build batteries that can actually ENGAGE, capped
        th = self._threat(ct)
        # small maps: the standing wall already occupies the live_all budget —
        # a cap of 4 would silence every reactive battery behind it
        if (th is not None and ct.get_action_cooldown() == 0
                and self._turret_threat(ct)
                and live_all < (10 if self.small else 8)):
            _, engage = self._live_defense(ct, th)
            # V34-era caps (4 turrets, 2 engaged) were poverty-era tuning —
            # Barbie now sieges with TWO 2-3-sentinel pods on opposite
            # flanks (runestone t195: 664 core dmg, our answer was 2
            # gunners). Grid econ affords a defense that scales to pods.
            if engage < 3:
                # trust the CORE's broadcast type: the builder's own vision
                # (r²20) usually can't reach a sentinel shelling from r²32
                th_sent = bool(ct.read_store(S_THREAT_TYPE))
                try:
                    tb = ct.get_tile_building_id(th) if ct.is_in_vision(th) else None
                    th_sent = th_sent or (tb is not None and self._enemy(ct, tb)
                                          and ct.get_entity_type(tb) == EntityType.SENTINEL)
                except Exception:
                    pass
                # enemy SENTINEL sieges from range²32 — gunners (range²13)
                # can NEVER reach it (replay data: 16 gunners dealt ~0 dmg).
                # Answer with our own sentinel AIMED AT HERS: hers can't move
                # or rotate either, and ours shoots back at equal range.
                if self._battery(ct, th, sentinel=th_sent, must_engage=True):
                    return
                if self._turret_by_harvester(ct, th, sentinel=th_sent):
                    return

        # a shelled core outranks everything idle: repair it (4hp/Ti beats
        # a sentinel's 6dmg/3r many times over)
        if self._core_hurt(ct) > 0 and self._heal_core(ct):
            return
        if self._chain_medic(ct):
            return

        # idle: claim adjacent ore (free money at home), heal, hold position
        if ct.get_action_cooldown() == 0 and self._build_harvester(ct):
            return
        if ct.get_action_cooldown() == 0:
            self._heal(ct)
        # unstick: shuffle within the ring rather than freezing
        if self.stuck >= 8:
            for d in random.sample(CARDINALS, len(CARDINALS)):
                n = pos.add(d)
                if (self._inb(n) and n.distance_squared(self.core_pos) <= 20
                        and ct.can_move(d)):
                    ct.move(d)
                    return

    # -------------------------------------------------------------- miner

    def _miner(self, ct: Controller) -> None:
        pos = ct.get_position()

        # free sabotage: standing on an enemy conveyor/splitter -> shoot it
        b = ct.get_tile_building_id(pos)
        if b is not None and self._enemy(ct, b):
            if ct.get_action_cooldown() == 0 and ct.can_fire(pos):
                ct.fire(pos)
                return

        # finish a defense battery in progress
        if self.batt_step > 0:
            if ct.get_action_cooldown() == 0:
                self._battery(ct, self._threat(ct), self.batt_sent)
            return

        # starve leech pods near home first — free and decisive
        if self._feed_denial(ct):
            return

        # repair cut logistics: healing out-economizes his cutters 8:1
        if self._chain_medic(ct):
            return

        # LOCAL LEECH DEFENSE: Barbie's big-map creep parks sentinels next
        # to OUR harvesters (they drink our ore as ammo) far from the core —
        # outside every core-centric trigger (ad0b1fb9 g3/g4/g5: 3-6 leeches,
        # zero answered). A parked 30hp sentinel loses the duel to a fed
        # gunner (reload 1 vs 3) built right where we already stand. NO
        # CHASING (the V34/V39 graves): only threats in own vision, and the
        # counter is built adjacent to us off harvesters already here.
        if (ct.get_action_cooldown() == 0
                and getattr(self, "local_ctr", 0) < 3):
            lt = self._local_turret_threat(ct)
            if lt is not None:
                # 2.2: free-placement counter-gun first — faster and
                # cheaper than the legacy fed-battery paths below
                if self._counter_gun(ct, lt):
                    self.local_ctr = getattr(self, "local_ctr", 0) + 1
                    return
                if self._turret_by_harvester(ct, lt, sentinel=False,
                                             must_engage=True):
                    self.local_ctr = getattr(self, "local_ctr", 0) + 1
                    return
                if self._battery(ct, lt, sentinel=False, must_engage=True):
                    self.local_ctr = getattr(self, "local_ctr", 0) + 1
                    return
                # gunner can't reach (she escorts pods with a gunner that
                # kills approaching builders — d5185334 g1): answer from
                # OUTSIDE her escort's range with a sentinel (r²32 vs 13;
                # the pod is parked, fixed facing is fine)
                if self._turret_by_harvester(ct, lt, sentinel=True,
                                             must_engage=True):
                    self.local_ctr = getattr(self, "local_ctr", 0) + 1
                    return
                if self._battery(ct, lt, sentinel=True, must_engage=True):
                    self.local_ctr = getattr(self, "local_ctr", 0) + 1
                    return

        # EMERGENCY ASSIST: the dedicated defenders are the first line, but a
        # turret siege that PERSISTS 60+ rounds means they are losing it —
        # Barbie 0-5'd V35's pure role split (kills t102-242) because nobody
        # reinforced. Nearby miners drop mining, help win the turret war, and
        # go back to mining when the siege flag clears.
        if self._turret_threat(ct) and self.core_pos is not None:
            first = getattr(self, "siege_start", None)
            if first is None:
                self.siege_start = ct.get_current_round()
            if ct.get_current_round() - self.siege_start >= 25:
                d_home = pos.distance_squared(self.core_pos)
                th = self._threat(ct)
                # assist radius 400→144: recalling every miner on the map
                # was the Atlas pinning (longship: 4 harvesters all game
                # while they ran 13) — only the NEAR miners reinforce; far
                # ones keep funding the war
                if d_home > THREAT_RAD_SQ and d_home <= 144:
                    self.wiring = False
                    self.target = self.core_pos
                    self._step_toward(ct, self.core_pos)
                    return
                if (th is not None and d_home <= THREAT_RAD_SQ
                        and ct.get_action_cooldown() == 0):
                    _, live_all = self._live_defense(ct)
                    _, engage = self._live_defense(ct, th)
                    if engage < 4 and live_all < (10 if self.small else 8):
                        th_sent2 = bool(ct.read_store(S_THREAT_TYPE))
                        try:
                            tb2 = ct.get_tile_building_id(th) if ct.is_in_vision(th) else None
                            th_sent2 = th_sent2 or (tb2 is not None and self._enemy(ct, tb2)
                                                    and ct.get_entity_type(tb2) == EntityType.SENTINEL)
                        except Exception:
                            pass
                        if self._battery(ct, th, sentinel=th_sent2, must_engage=True):
                            return
                        if self._turret_by_harvester(ct, th, sentinel=th_sent2):
                            return
        else:
            self.siege_start = None

        # CLAIM AND WIRE IMMEDIATELY. Docs truth that killed claim-first: a
        # harvester with no accepting neighbour is fully STALLED — it makes
        # NOTHING until its stack is received. Every claimed-but-unwired
        # harvester was zero income for as long as it sat there.
        claimed = ct.get_action_cooldown() == 0 and self._build_harvester(ct)
        if claimed and self.last_claim is not None and not self.wiring:
            if not self._touching_network(ct, self.last_claim):
                self.wiring = True
                self.wire_src = self.last_claim
                self.wire_started = False
                self.wire_len = 0

        # FINISH THE CHAIN FIRST: visible free ore used to abort wiring
        # mid-chain ("claiming outranks wiring") — on big maps ore is always
        # visible somewhere, so half the harvesters never got their last-mile
        # link (scouted in Barbie games 1 and 4). Complete, then claim more.
        if self.wiring:
            self._wire_step(ct)
            return

        free_ore = self._nearest_free_ore(ct)
        if free_ore is not None:
            self.noore = 0
            if not claimed and ct.get_action_cooldown() == 0:
                self._heal(ct)
            # stand next to the ore to claim it
            sa, sd = None, None
            for d in DIRECTIONS:
                a = free_ore.add(d)
                if not self._inb(a) or a == pos:
                    continue
                if ct.is_in_vision(a) and not ct.is_tile_passable(a):
                    continue
                dd = a.distance_squared(pos)
                if sd is None or dd < sd:
                    sd, sa = dd, a
            if pos.distance_squared(free_ore) > 2 and sa is not None:
                self.target = sa
                self._step_toward(ct, sa)
            return

        # nothing to claim in sight -> WIRE: finish a chain in progress, else
        # adopt the nearest orphaned harvester and wire it home.
        if self.wiring:
            self._wire_step(ct)
            return
        orphan = self._find_orphan_harvester(ct)
        if orphan is not None:
            if abs(pos.x - orphan.x) + abs(pos.y - orphan.y) == 1:
                self.wiring = True
                self.wire_src = orphan
                self.wire_started = True
                self.wire_len = 0
                self._wire_step(ct)
                return
            feeds = [orphan.add(d) for d in CARDINALS
                     if self._inb(orphan.add(d)) and ct.is_tile_passable(orphan.add(d))]
            if feeds:
                goal = min(feeds, key=lambda q: q.distance_squared(pos))
                self.target = goal
                self._step_toward(ct, goal)
                return

        # economy claimed AND wired, and we're rich -> SENTINEL RUSH their core.
        # (but never while a turret sieges our home: marching out and getting
        # recalled every few turns was the "circling our own core" bug)
        # ⭐⭐ TERRITORY: keep MINING until the map is SATURATED, don't rush
        # off at RUSH_TI. Miners marching at the enemy core the moment they
        # hit 350 Ti FROZE the whole economy at t200 (aurora: 14 harvesters
        # then nothing for 800 turns) — disabling that rush 5x'd the mined
        # total (aurora 5380→25180, above Oogway's 14-18k). The sieger (idx
        # 1) still kills; miners only join the rush once they've gone DRY —
        # explored a while without finding any claimable ore (true
        # saturation), so we never trade live economy for a premature rush.
        if self._has_claimable_ore(ct) or self._nearest_free_ore(ct) is not None:
            self.dry = 0
        else:
            self.dry = getattr(self, "dry", 0) + 1
        saturated = getattr(self, "dry", 0) > 40
        # BIG MAPS: miners are PURE ECONOMY — the two dedicated siegers carry
        # counter-pressure, so miners never rush and mine at full 3.7x. Small
        # maps keep their rush wave.
        _ = saturated
        if (ct.get_global_resources() >= RUSH_TI and not self._turret_threat(ct)
                and self.small):
            # SMALL MAPS: sweep for ore before committing to a rush. The wall
            # openers claim the home ore, so fresh miners see none in vision
            # and marched off rich at ~t20, leaving all mid-map ore unclaimed
            # for 1000 rounds (crossfire: 5 harvesters, 2370 vs 7620 mined).
            if self.small:
                self.noore = getattr(self, "noore", 0) + 1
                if self.noore < 25:
                    self._move(ct)
                    return
            ecore = self._find_enemy_core(ct)
            if ecore is None:
                # UNCONFIRMED: walk a mirror candidate but NEVER plant blind —
                # the twins rush wave sieged an empty corner (point-mirror
                # guess on a reflection-symmetric map) for ~360 wasted Ti.
                cand = self._guess_candidate(ct)
                if pos.distance_squared(cand) <= 8:
                    # arrived, no core here: cross it off, try the next
                    self.dead_cands = getattr(self, "dead_cands", set())
                    self.dead_cands.add((cand.x, cand.y))
                    cand = self._guess_candidate(ct)
                self.target = cand
                self._step_toward(ct, cand)
                return
            if pos.distance_squared(ecore) <= 20 and ct.get_action_cooldown() == 0:
                if self._battery(ct, ecore, sentinel=True):
                    return
                # all nearby ore is already OURS (claim-first): plant the
                # sentinel next to an EXISTING friendly harvester — it feeds it
                # exactly the same as a fresh one.
                if self._sentinel_by_harvester(ct, ecore):
                    return
            self.target = ecore
            self._step_toward(ct, ecore)
            return

        if ct.get_action_cooldown() == 0:
            self._heal(ct)
        # LAUNCHER TAXI (cte's decoded trick: 5-launcher highways hurl their
        # builders to the contested middle by t14): a miner with a FAR
        # target standing beside a friendly launcher requests a throw and
        # holds still one round for pickup. Bounded wait so a busy launcher
        # never freezes the miner.
        if (self.target is not None
                and pos.distance_squared(self.target) > 16):
            near_l = False
            for b in ct.get_nearby_buildings(2):
                if not self._enemy(ct, b) and \
                        ct.get_entity_type(b) == EntityType.LAUNCHER:
                    near_l = True
                    break
            if near_l:
                self.taxi_wait = getattr(self, "taxi_wait", 0) + 1
                if self.taxi_wait <= 2:
                    ct.write_store(S_TAXI, pack(self.target))
                    ct.write_store(S_TAXI_R, ct.get_current_round())
                    ct.write_store(S_TAXI_ID, ct.get_id())
                    return  # hold for pickup
            else:
                self.taxi_wait = 0
        self._move(ct)

    def _has_claimable_ore(self, ct) -> bool:
        """Is there still unclaimed ore worth mining on OUR half? (remembered
        ore, culled of anything now seen occupied). Keeps miners expanding
        the economy instead of rushing off while ore sits idle."""
        if not self.seen_ore or self.core_pos is None:
            return False
        ec = self._enemy_core_guess()
        for t in self.seen_ore:
            if t.distance_squared(self.core_pos) <= t.distance_squared(ec):
                if not (ct.is_in_vision(t)
                        and ct.get_tile_building_id(t) is not None):
                    return True
        return False

    def _sentinel_by_harvester(self, ct, aim) -> bool:
        return self._turret_by_harvester(ct, aim, sentinel=True)

    def _feed_denial(self, ct) -> bool:
        """DEAD as of 2.2.0: turrets fire from the global ammo pool — enemy
        sentinels no longer drink adjacent harvesters' ore, so destroying
        our own feeder is pure self-harm now. Kept for git archaeology."""
        return False

    def _feed_denial_LEGACY(self, ct) -> bool:
        """FEED DENIAL v2 (V39 postmortem applied): an enemy SENTINEL sitting
        cardinally adjacent to OUR harvester drinks its ore as ammo — the
        leech. Near home, DELETE the feeder (destroy() is free and instant):
        every sentinel in the pod runs dry after one more shot. Longship
        (c684c634 g3): two pods of 3+4 sentinels around two of our harvesters
        flanking the core, 1026 core dmg, zero counters possible (home ore
        all claimed, pod squeezed out every turret spot). V39's graves:
        no cross-map trips (approach <= dsq 18, home <= dsq 64 only), and
        _build_harvester refuses ore beside an enemy turret (no re-leech)."""
        if self.core_pos is None:
            return False
        pos = ct.get_position()
        for b in ct.get_nearby_buildings():
            if self._enemy(ct, b) or \
                    ct.get_entity_type(b) != EntityType.HARVESTER:
                continue
            hp = ct.get_position(b)
            if hp.distance_squared(self.core_pos) > 64:
                continue
            if pos.distance_squared(hp) > 18:
                continue
            leeched = False
            for d in CARDINALS:
                n = hp.add(d)
                if not self._inb(n) or not ct.is_in_vision(n):
                    continue
                try:
                    nb = ct.get_tile_building_id(n)
                except Exception:
                    continue
                if nb is not None and self._enemy(ct, nb) and \
                        ct.get_entity_type(nb) == EntityType.SENTINEL:
                    leeched = True
                    break
            if not leeched:
                continue
            if pos.distance_squared(hp) <= 2:
                try:
                    ct.destroy(hp)
                    return True
                except Exception:
                    return False
            self.target = hp
            self._step_toward(ct, hp)
            return True
        return False

    def _enemy_band(self, ct, aim):
        """(pos, facing) of an enemy SENTINEL at `aim`, else None. VERIFIED:
        get_direction() works CROSS-TEAM (mechtest probe) — her band is
        public information, and sentinels can never rotate."""
        try:
            if aim is None or not ct.is_in_vision(aim):
                return None
            b = ct.get_tile_building_id(aim)
            if b is None or not self._enemy(ct, b):
                return None
            if ct.get_entity_type(b) != EntityType.SENTINEL:
                return None
            return aim, ct.get_direction(b)
        except Exception:
            return None

    def _in_band(self, band, tile: Position) -> bool:
        """Is tile inside a sentinel's kill band (3-wide facing line, r²32)?"""
        if band is None:
            return False
        sp, sd = band
        if tile.distance_squared(sp) > 32:
            return False
        dx, dy = sd.delta()
        lx, ly = sp.x, sp.y
        for _ in range(6):
            lx += dx
            ly += dy
            if max(abs(tile.x - lx), abs(tile.y - ly)) <= 1:
                return True
        return False

    def _cut_trunk(self, ct) -> bool:
        """cte's kill pattern = a conveyor TRUNK feeding turrets on our core
        ring. Their conveyor directions are PUBLIC (get_direction is cross-
        team), and so are their sentinel bands: while a turret siege is
        live, walk onto a SAFE trunk tile near home — outside every visible
        sentinel band and gunner reach — and eat it (own-tile fire). Dry
        siege turrets are scrap. V34's cutter died under the guns; band
        intel is what makes this version safe."""
        if self.core_pos is None or not self._turret_threat(ct):
            return False
        pos = ct.get_position()
        sents, guns = [], []
        for b in ct.get_nearby_buildings():
            if not self._enemy(ct, b):
                continue
            et = ct.get_entity_type(b)
            bp = ct.get_position(b)
            if et == EntityType.SENTINEL:
                try:
                    sents.append((bp, ct.get_direction(b)))
                except Exception:
                    pass
            elif et == EntityType.GUNNER:
                guns.append(bp)
        # THE TRUNK PLUG (first choice): a conveyor pushes its stack into
        # ANY building on its output tile — including OURS — and a full
        # turret refuses input, which stalls the conveyor behind it, which
        # stalls the whole trunk, which stalls their harvesters (blocked-
        # harvester rule). One 10-Ti gunner on the trunk's output tile
        # drinks a free ammo load from THEIR ore and freezes the line.
        plug, plug_d, pd = None, None, None
        best, bd = None, None
        for b in ct.get_nearby_buildings():
            if not self._enemy(ct, b):
                continue
            if ct.get_entity_type(b) not in (EntityType.CONVEYOR,
                                             EntityType.SPLITTER):
                continue
            bp = ct.get_position(b)
            if bp.distance_squared(self.core_pos) > 169:
                continue
            if any(self._in_band(s, bp) for s in sents):
                continue
            if any(bp.distance_squared(g) <= 13 for g in guns):
                continue
            try:
                flow = ct.get_direction(b)
                out = bp.add(flow)
                if (self._inb(out) and ct.is_tile_empty(out)
                        and not any(self._in_band(s, out) for s in sents)
                        and not any(out.distance_squared(g) <= 13
                                    for g in guns)):
                    dd = out.distance_squared(pos)
                    if pd is None or dd < pd:
                        pd, plug, plug_d = dd, out, flow
            except Exception:
                pass
            dd = bp.distance_squared(pos)
            if bd is None or dd < bd:
                bd, best = dd, bp
        if (plug is not None and ct.get_action_cooldown() == 0
                and ct.get_global_resources() >=
                ct.get_gunner_cost() + RESERVE):
            if pos.distance_squared(plug) <= 2:
                # face DOWNSTREAM (= flow direction): the feeding conveyor
                # sits behind us, a legal ammo side; existence is the weapon
                if ct.can_build_gunner(plug, plug_d):
                    ct.build_gunner(plug, plug_d)
                    return True
            else:
                self.target = plug
                self._step_toward(ct, plug)
                return True
        if best is None:
            return False
        self.target = best
        self._step_toward(ct, best)
        return True

    def _chain_medic(self, ct) -> bool:
        """Oogway's 25-35 builder swarm wins Ti races by CUTTING chains
        (334-862 conveyor dmg per game, match 498d8594). Healing beats
        cutting 8:1: his cut is 2 dmg for 2 Ti, our heal 4 hp for 1 Ti.
        Seek and repair meaningfully damaged logistics nearby."""
        pos = ct.get_position()
        best, bd = None, None
        for b in ct.get_nearby_buildings():
            if self._enemy(ct, b):
                continue
            if ct.get_entity_type(b) not in (EntityType.CONVEYOR,
                                             EntityType.SPLITTER,
                                             EntityType.HARVESTER):
                continue
            try:
                if ct.get_max_hp(b) - ct.get_hp(b) < 6:
                    continue
            except Exception:
                continue
            bp = ct.get_position(b)
            dd = bp.distance_squared(pos)
            if bd is None or dd < bd:
                bd, best = dd, bp
        if best is None:
            return False
        if pos.distance_squared(best) <= 2:
            if ct.get_action_cooldown() == 0 and ct.can_heal(best):
                ct.heal(best)
                return True
            return False
        if bd <= 32:
            self.target = best
            self._step_toward(ct, best)
            return True
        return False

    def _counter_gun(self, ct, tp: Position) -> bool:
        """2.2 counter-battery: place a POOL-FED gunner to kill the enemy
        turret at tp — no feeder needed anymore, so placement is free and
        instant. Geometry rules learned the hard way (garrison-v1 REJECT,
        pendmic 27%): never inside its kill lane (facings are public; a
        gunner's lane is a straight ray — perpendicular is a free 4-shot
        kill), never on our spawn ring (dsq<=8 of core — impassable gunners
        there strangle our own spawns/wiring), never facing our own core
        (the engine will hit friendlies)."""
        if not self.small and ct.read_store(S_GUN_N) >= GUN_CAP:
            return False
        if ct.get_global_resources() < ct.get_gunner_cost() + RESERVE:
            return False
        pos = ct.get_position()
        lane = set()
        try:
            b = ct.get_tile_building_id(tp) if ct.is_in_vision(tp) else None
            if b is not None:
                fd = ct.get_direction(b)
                cur = tp
                for _ in range(4):
                    cur = cur.add(fd)
                    lane.add(cur)
        except Exception:
            pass
        for d in DIRECTIONS:
            G = pos.add(d)
            if not self._inb(G) or not ct.is_tile_empty(G):
                continue
            if G in lane or G.distance_squared(tp) > 13:
                continue
            if (self.core_pos is not None
                    and G.distance_squared(self.core_pos) <= 8):
                continue
            facing = None
            for f in DIRECTIONS:
                try:
                    if not ct.can_fire_from(G, f, EntityType.GUNNER, tp):
                        continue
                    if (self.core_pos is not None and ct.can_fire_from(
                            G, f, EntityType.GUNNER, self.core_pos)):
                        continue
                    facing = f
                    break
                except Exception:
                    continue
            if facing is None:
                continue
            if ct.can_build_gunner(G, facing):
                ct.build_gunner(G, facing)
                ct.write_store(S_GUN_N, ct.read_store(S_GUN_N) + 1)
                return True
        return False

    def _local_turret_threat(self, ct):
        """Nearest enemy TURRET in this unit's OWN vision that no friendly
        turret in sight already reaches. Barbie's big-map creep parks
        sentinels adjacent to OUR harvesters deep in our territory — they
        drink OUR ore as ammo (cross-team output is real; quarry replay
        ad0b1fb9 g5: 4 sentinels nested on our cluster, no supply line of
        hers in sight) — far outside the core-centric threat radius, so
        nobody ever answered."""
        pos = ct.get_position()
        best, bd = None, None
        friends = []
        for b in ct.get_nearby_buildings():
            et = ct.get_entity_type(b)
            if et not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            bp = ct.get_position(b)
            if self._enemy(ct, b):
                dd = bp.distance_squared(pos)
                if bd is None or dd < bd:
                    bd, best = dd, bp
            else:
                friends.append((bp, 32 if et == EntityType.SENTINEL else 13))
        if best is None:
            return None
        for fp, rng in friends:
            if fp.distance_squared(best) <= rng:
                return None  # already answered
        return best

    def _turret_by_harvester(self, ct, aim, sentinel=True,
                             must_engage=False) -> bool:
        """Build a fed turret (sentinel OR gunner) on an empty tile adjacent to
        an EXISTING friendly harvester (its output feeds it like a battery).
        Defense wants GUNNERS (only turret that can rotate); offense at the
        immobile enemy core can use sentinels."""
        if not sentinel and not self.small \
                and ct.read_store(S_GUN_N) >= GUN_CAP:
            return False  # big-map gunner budget spent: mine, don't churn
        cost = ct.get_sentinel_cost() if sentinel else ct.get_gunner_cost()
        want = EntityType.SENTINEL if sentinel else EntityType.GUNNER
        if ct.get_global_resources() < cost + RESERVE:
            return False
        pos = ct.get_position()
        # place OUTSIDE the enemy sentinel's band when possible (facing is
        # public via get_direction and she can never rotate — an out-of-band
        # counter shoots her with impunity), then closest to the aim
        band = self._enemy_band(ct, aim)
        dirs = (sorted(DIRECTIONS,
                       key=lambda d: (self._in_band(band, pos.add(d)),
                                      pos.add(d).distance_squared(aim)))
                if aim is not None else list(DIRECTIONS))
        for dG in dirs:
            G = pos.add(dG)
            if not self._inb(G) or not ct.is_tile_empty(G):
                continue
            feeders = []
            for d in CARDINALS:
                n = G.add(d)
                if not self._inb(n) or not ct.is_in_vision(n):
                    continue
                nb = ct.get_tile_building_id(n)
                # ANY-TEAM harvester feeds us: cross-team output cuts both
                # ways — HER pod harvester arms OUR counter-turret placed
                # beside it (fjord 47429e39 g4: her self-fed pod shelled
                # 2,380 ore of ammo while we had zero feeders left at home;
                # her own ore is the one feeder she can't deny us).
                if nb is not None and \
                        ct.get_entity_type(nb) == EntityType.HARVESTER:
                    feeders.append(n)
            if not feeders:
                continue

            def starves(f):
                # a CARDINAL-facing turret cannot accept ammo from the tile
                # it faces; diagonal facings feed from all four sides
                return (f in CARDINALS and len(feeders) == 1
                        and G.add(f) == feeders[0])

            facing = None
            if aim is not None:
                for f in DIRECTIONS:
                    if starves(f):
                        continue
                    try:
                        if ct.can_fire_from(G, f, want, aim):
                            facing = f
                            break
                    except Exception:
                        pass
            if facing is None:
                if must_engage:
                    continue  # this spot can't hit the target: try another
                f = (G.direction_to(aim) if aim is not None and G != aim
                     else Direction.NORTH)
                if f == Direction.CENTRE:
                    f = Direction.NORTH
                if starves(f):
                    f = f.rotate_right()  # diagonal: still forward, feeds fine
                facing = f
            can = (ct.can_build_sentinel(G, facing) if sentinel
                   else ct.can_build_gunner(G, facing))
            if can:
                if sentinel:
                    ct.build_sentinel(G, facing)
                else:
                    ct.build_gunner(G, facing)
                    ct.write_store(S_GUN_N, ct.read_store(S_GUN_N) + 1)
                return True
        return False

    def _nearest_free_ore(self, ct):
        pos = ct.get_position()
        # ore inside the published kill zone does not exist: the rush camps
        # the contested cluster precisely so our miners walk in and die for
        # it (cg_atoll: 11 deaths on one tile — every victim was TARGETING
        # the ore under the guns; path-avoidance can't help when the GOAL
        # is the trap). Other exits and clusters are free.
        dz = unpack(ct.read_store(S_DEATH))
        best, bd = None, None
        for t in ct.get_nearby_tiles():
            if ct.get_tile_env(t) != Environment.ORE_TITANIUM:
                continue
            if ct.get_tile_building_id(t) is not None:
                continue
            if dz is not None and t.distance_squared(dz) <= 13:
                continue
            dd = t.distance_squared(pos)
            if bd is None or dd < bd:
                bd, best = dd, t
        return best

    def _find_orphan_harvester(self, ct):
        """Nearest friendly harvester in vision with NO adjacent friendly
        conveyor/splitter/core — i.e. it can't deliver anything."""
        pos = ct.get_position()
        best, bd = None, None
        for b in ct.get_nearby_buildings():
            if self._enemy(ct, b) or ct.get_entity_type(b) != EntityType.HARVESTER:
                continue
            hp = ct.get_position(b)
            connected = False
            for d in CARDINALS:
                n = hp.add(d)
                if not self._inb(n):
                    continue
                if not ct.is_in_vision(n):
                    connected = True  # unknown neighbour: assume fine, no false orphans
                    break
                nb = ct.get_tile_building_id(n)
                if nb is None or self._enemy(ct, nb):
                    continue
                if ct.get_entity_type(nb) in (EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.CORE):
                    connected = True
                    break
            # (Tried once: dedicating battery feeders to ammo on tiny maps —
            # REVERTED. It starved the whole sprint economy (nothing built
            # t8-t120, death t130 < the t165 baseline): the attrition war is
            # won by INCOME + rebuilds, not fire rate. f99ee2fa g2.)
            if connected:
                continue
            dd = hp.distance_squared(pos)
            if bd is None or dd < bd:
                bd, best = dd, hp
        return best

    def _build_harvester(self, ct) -> bool:
        if ct.get_global_resources() < ct.get_harvester_cost() + RESERVE:
            return False
        pos = ct.get_position()
        for d in DIRECTIONS:
            bp = pos.add(d)
            if not self._inb(bp) or not ct.can_build_harvester(bp):
                continue
            # never claim ore under an enemy turret's nose — the harvester
            # would FEED it (cross-team output = the leech), and rebuilding
            # a denied feeder just re-taps the pod (V39's death spiral)
            leech = False
            for d2 in CARDINALS:
                n = bp.add(d2)
                if not self._inb(n) or not ct.is_in_vision(n):
                    continue
                try:
                    nb = ct.get_tile_building_id(n)
                except Exception:
                    continue
                if nb is not None and self._enemy(ct, nb) and \
                        ct.get_entity_type(nb) in (EntityType.SENTINEL,
                                                   EntityType.GUNNER):
                    leech = True
                    break
            if leech:
                continue
            self.last_claim = bp
            ct.build_harvester(bp)
            ct.write_store(S_HARV, ct.read_store(S_HARV) + 1)
            # CLAIM-first: don't stop to wire — the wiring pass (orphan repair)
            # connects it once there's nothing left to claim nearby.
            self.target = None
            return True
        return False

    def _grad(self, ct):
        """BFS distance-to-core field over non-wall tiles (4-connected, the
        topology conveyor flow actually uses). Cached per unit; recomputed
        when new walls are learned. This is the loop-proof of the whole
        grid: every conveyor points strictly DOWN this field, so cycles and
        serpentines are impossible by construction, and any two chains that
        meet merge into a legal shared trunk."""
        now = ct.get_current_round()
        if (self.grad is not None and len(self.walls) == self.grad_walls
                and now - self.grad_round < 60):
            return self.grad
        try:
            if ct.get_cpu_time_elapsed() > 5000 and self.grad is not None:
                return self.grad  # out of budget this turn: stale is fine
        except Exception:
            pass
        from collections import deque
        dist = {}
        q = deque()
        for t in (self.core_tiles or []):
            dist[t] = 0
            q.append(t)
        while q:
            cur = q.popleft()
            dc = dist[cur]
            for d in CARDINALS:
                n = cur.add(d)
                if n in dist or not self._inb(n) or n in self.walls:
                    continue
                dist[n] = dc + 1
                q.append(n)
        self.grad = dist
        self.grad_round = now
        self.grad_walls = len(self.walls)
        return dist

    def _touching_network(self, ct, hp: Position) -> bool:
        """Does this harvester already have someone to output to?
        (Docs truth: a harvester with no accepting neighbour is fully
        STALLED — it produces NOTHING until its stack is received.)"""
        for d in CARDINALS:
            n = hp.add(d)
            if not self._inb(n) or not ct.is_in_vision(n):
                continue
            try:
                nb = ct.get_tile_building_id(n)
            except Exception:
                continue
            if nb is not None and not self._enemy(ct, nb) and \
                    ct.get_entity_type(nb) in (EntityType.CONVEYOR,
                                               EntityType.SPLITTER,
                                               EntityType.CORE):
                return True
        return False

    def _wire_step(self, ct: Controller) -> None:
        """GRADIENT WIRING: walk down the BFS dist-to-core field laying a
        conveyor under our feet at each step, pointing down-gradient. The
        moment any cardinal neighbour is a friendly conveyor/splitter/core
        with LOWER dist, point into it and STOP — the chain has merged into
        the network (a conveyor accepts from its 3 non-output sides), and
        shared trunks form wherever paths coincide."""
        if self.core_pos is None:
            self.wiring = False
            return
        pos = ct.get_position()

        # first conveyor must sit cardinally adjacent to the harvester
        if not self.wire_started and self.wire_src is not None:
            if abs(pos.x - self.wire_src.x) + abs(pos.y - self.wire_src.y) == 1:
                self.wire_started = True
            else:
                feeds = [self.wire_src.add(d) for d in CARDINALS
                         if self._inb(self.wire_src.add(d)) and ct.is_tile_passable(self.wire_src.add(d))]
                if not feeds:
                    self.wiring = False
                    return
                goal = min(feeds, key=lambda q: q.distance_squared(pos))
                self._step_toward(ct, goal)
                return

        grad = self._grad(ct)
        d_here = grad.get(pos)
        if d_here is None:
            self.wiring = False
            return

        # length sanity: safety net against pathological detours
        self.wire_len = getattr(self, "wire_len", 0)
        if self.wire_src is not None:
            src_d = grad.get(self.wire_src, d_here)
            if self.wire_len > src_d + 8:
                self.wiring = False
                self.wire_len = 0
                return

        here_b = ct.get_tile_building_id(pos)

        # MERGE/FINISH: any down-gradient neighbour that's already network?
        cands = sorted(CARDINALS, key=lambda c: grad.get(pos.add(c), 1 << 20))
        for c in cands:
            n = pos.add(c)
            if not self._inb(n) or grad.get(n, 1 << 20) >= d_here:
                continue
            nb = ct.get_tile_building_id(n)
            if nb is None or self._enemy(ct, nb):
                continue
            if ct.get_entity_type(nb) in (EntityType.CONVEYOR,
                                          EntityType.SPLITTER,
                                          EntityType.CORE):
                # BUSY-TRUNK VETO (big maps): a conveyor moves ONE stack of
                # 10/turn (spec) — ~4 harvesters saturate a line, and
                # everything upstream of a full trunk STALLS (produces
                # nothing). If the conveyor we'd merge into is holding a
                # stack RIGHT NOW, it's loaded: keep laying our own line
                # instead and merge somewhere emptier (or reach the core
                # ring). Point-sample of utilization — cheap, local, and
                # biased against exactly the overloaded trunks.
                if (not self.small
                        and ct.get_entity_type(nb) != EntityType.CORE):
                    try:
                        if ct.get_stored_resource(nb) is not None:
                            continue
                    except Exception:
                        pass
                    # INPUT-DEGREE VETO: facings are public — count the
                    # conveyors already pointing INTO the merge candidate.
                    # 2+ inbound = the line is claimed by other feeders
                    # (spec: 10 Ti/turn capacity, each feeder offers 2.5)
                    # — lay a parallel line instead of oversubscribing.
                    ins = 0
                    for d2 in CARDINALS:
                        m2 = n.add(d2)
                        if m2 == pos or not self._inb(m2) \
                                or not ct.is_in_vision(m2):
                            continue
                        mb = ct.get_tile_building_id(m2)
                        if mb is None or self._enemy(ct, mb):
                            continue
                        if ct.get_entity_type(mb) in (EntityType.CONVEYOR,
                                                      EntityType.SPLITTER):
                            try:
                                if m2.add(ct.get_direction(mb)) == n:
                                    ins += 1
                            except Exception:
                                pass
                    if ins >= 2:
                        continue
                if here_b is not None:
                    # our own conveyor already sits here: chain complete
                    self.wiring = False
                    self.target = None
                    self.wire_len = 0
                    return
                if ct.can_build_conveyor(pos, c):
                    ct.build_conveyor(pos, c)
                    self.wiring = False
                    self.target = None
                    self.wire_len = 0
                    return
                # momentarily short on Ti: wait here, bounded
                self.wire_wait = getattr(self, "wire_wait", 0) + 1
                if self.wire_wait > 30:
                    self.wiring = False
                    self.wire_wait = 0
                return

        # ADVANCE: lay a conveyor pointing down-gradient and walk on.
        # NEVER move off an empty tile without paving it (action cooldown or
        # a short bank would leave a silent hole in the chain — retry).
        for c in cands:
            n = pos.add(c)
            if not self._inb(n) or grad.get(n, 1 << 20) >= d_here:
                continue
            if not ct.can_move(c):
                continue  # occupied/impassable: try the next-best descent
            if here_b is None:
                if ct.get_global_resources() >= ct.get_conveyor_cost() and \
                        ct.can_build_conveyor(pos, c):
                    ct.build_conveyor(pos, c)
                    self.wire_len += 1
                else:
                    return  # can't pave this tile right now: wait, retry
            ct.move(c)
            self.lat_run = 0  # descent achieved: lateral budget resets
            return
        # SIDEWAYS ESCAPE (big maps): every descent is vetoed (busy trunk)
        # or blocked — the strictly-monotone router used to abort here,
        # which is why chains could never reach a PARALLEL corridor
        # (crossfire ledger: 71% of harvesters jammed on one shared line).
        # Take up to 2 consecutive EQUAL-gradient steps, empty tiles only
        # (never lateral into network — that's how cycles would form; our
        # own chain can't loop because we pave only empty tiles and always
        # point forward). Budget resets on every real descent.
        if not self.small and getattr(self, "lat_run", 0) < 2:
            for c in cands:
                n = pos.add(c)
                if not self._inb(n) or grad.get(n, 1 << 20) != d_here:
                    continue
                nb2 = ct.get_tile_building_id(n) if ct.is_in_vision(n) else 0
                if nb2 is not None:
                    continue  # lateral onto EMPTY, verified tiles only
                if not ct.can_move(c):
                    continue
                if here_b is None:
                    if ct.get_global_resources() >= ct.get_conveyor_cost() \
                            and ct.can_build_conveyor(pos, c):
                        ct.build_conveyor(pos, c)
                        self.wire_len += 1
                    else:
                        return
                ct.move(c)
                self.lat_run = getattr(self, "lat_run", 0) + 1
                return
        # no legal descent (boxed in by buildings): give up cleanly —
        # the orphan pass will retry from a different approach later
        if self.stuck >= 4:
            self.wiring = False
            self.wire_len = 0

    def _core_ring_tile(self, pos: Position) -> Position:
        if self.core_tiles is None:
            return self.core_pos or Position(self.w // 2, self.h // 2)
        best, bd = None, None
        for t in self.core_tiles:
            for d in CARDINALS:
                a = t.add(d)
                if a in self.core_tiles or not self._inb(a):
                    continue
                dd = a.distance_squared(pos)
                if bd is None or dd < bd:
                    bd, best = dd, a
        return best if best is not None else self.core_pos

    def _move(self, ct: Controller) -> None:
        if ct.get_move_cooldown() != 0:
            return
        pos = ct.get_position()
        if self.target is None or pos == self.target or self.stuck >= 3:
            self.target = self._pick_target(ct)
        if self.target is None:
            return
        self._step_toward(ct, self.target)

    def _pick_target(self, ct) -> Position:
        pos = ct.get_position()
        # nearest FREE ore — but if we're stuck, the nearest is unusable:
        # explore instead of parking next to covered ore forever.
        if self.stuck < 3:
            best, bd = None, None
            for t in ct.get_nearby_tiles():
                if ct.get_tile_env(t) != Environment.ORE_TITANIUM:
                    continue
                if ct.get_tile_building_id(t) is not None:
                    continue
                dd = t.distance_squared(pos)
                if bd is None or dd < bd:
                    bd, best = dd, t
            if best is not None:
                # stand NEXT to the ore (can't build under our own feet)
                sa, sd = None, None
                for d in DIRECTIONS:
                    a = best.add(d)
                    if not self._inb(a):
                        continue
                    if a == pos:
                        return pos
                    if ct.is_in_vision(a) and not ct.is_tile_passable(a):
                        continue
                    dd = a.distance_squared(pos)
                    if sd is None or dd < sd:
                        sd, sa = dd, a
                return sa if sa is not None else best
        # REMEMBERED ORE: nothing minable in sight, but we've walked past
        # unclaimed ore before — go to the nearest one. Cull stale memory
        # (tiles we can now see are taken). This is the hive territory fix:
        # 16 scattered ore all get claimed, not just the 5 near home.
        if self.seen_ore:
            for t in list(self.seen_ore):
                if ct.is_in_vision(t) and ct.get_tile_building_id(t) is not None:
                    self.seen_ore.discard(t)
            # only chase ore on OUR HALF (closer to our core than theirs) —
            # chasing remembered ore into the enemy half starved the SECOND
            # player's home economy into a death spiral (hive 2nd-player:
            # 1900 mined, 5 units). Each side claims its own territory.
            ec = self._enemy_core_guess()
            dz = unpack(ct.read_store(S_DEATH))  # camped ore doesn't exist
            cands = [t for t in self.seen_ore if t != pos
                     and (dz is None or t.distance_squared(dz) > 13)
                     and (self.core_pos is None
                          or t.distance_squared(self.core_pos)
                          <= t.distance_squared(ec))]
            if cands:
                goal = min(cands, key=lambda t: t.distance_squared(pos))
                sa, sd = None, None
                for d in DIRECTIONS:
                    a = goal.add(d)
                    if not self._inb(a) or a == pos:
                        continue
                    if ct.is_in_vision(a) and not ct.is_tile_passable(a):
                        continue
                    dd = a.distance_squared(pos)
                    if sd is None or dd < sd:
                        sd, sa = dd, a
                return sa if sa is not None else goal

        # explore: persistent per-builder heading, clamped to the interior.
        # If the clamped target lands (almost) where we already are — heading
        # points into a wall/corner — ROTATE until it leads somewhere real.
        # Without this, builders orbit a corner forever (quarry: 4 miners
        # circled (2,2) for 800 rounds while 6 harvesters sat unwired).
        if self.explore_dir is None:
            self.explore_dir = DIRECTIONS[ct.get_id() % len(DIRECTIONS)]
            # half the crew RUSHES THE MAP CENTER first — that's where the
            # contested titanium is, and losing the middle loses econ races.
            if ct.get_id() % 2 == 0 and ct.get_current_round() < 120:
                centre = Position(self.w // 2, self.h // 2)
                if pos.distance_squared(centre) > 9:
                    return centre
        elif self.stuck >= 2:
            self.explore_dir = random.choice(DIRECTIONS)
        for _ in range(8):
            dx, dy = self.explore_dir.delta()
            t = Position(
                min(max(pos.x + dx * 7, 2), self.w - 3),
                min(max(pos.y + dy * 7, 2), self.h - 3),
            )
            if t.distance_squared(pos) > 9:
                return t
            self.explore_dir = self.explore_dir.rotate_right()
        return Position(self.w // 2, self.h // 2)

    def _step_toward(self, ct, goal: Position) -> None:
        # 2.2.0: movement is 4-way only (diagonals raise GameError) — BFS
        # and every fallback walk are cardinal now
        pos = ct.get_position()
        d = None
        # miners detour around the published kill zone (small disc — the
        # rush camps ONE choke; other exits are free). Fall back to the
        # direct path if no safe one exists — never strand.
        if getattr(self, "role", "") == "miner":
            dz = unpack(ct.read_store(S_DEATH))
            if dz is not None:
                avoid = set()
                for ox in range(-3, 4):
                    for oy in range(-3, 4):
                        t = Position(dz.x + ox, dz.y + oy)
                        if self._inb(t) and t.distance_squared(dz) <= 13:
                            avoid.add(t)
                avoid.discard(pos)
                if goal not in avoid:
                    d = self._bfs_step(ct, goal, cardinal=True, avoid=avoid)
        if d is None:
            d = self._bfs_step(ct, goal, cardinal=True)
        if d is not None:
            n = pos.add(d)
            if self._inb(n) and ct.can_move(d):
                ct.move(d)
                return
            self.blocked[n] = ct.get_current_round()  # learn the obstacle
        for e in sorted(CARDINALS,
                        key=lambda c: pos.add(c).distance_squared(goal)):
            if e != d:
                n = pos.add(e)
                if self._inb(n) and ct.can_move(e):
                    ct.move(e)
                    return

    def _bfs_step(self, ct, goal: Position, cardinal: bool, avoid=None):
        start = ct.get_position()
        if start == goal:
            return None
        from collections import deque
        dirs = CARDINALS if cardinal else DIRECTIONS
        prev = {start: start}
        q = deque([start])
        best, bd = start, start.distance_squared(goal)
        found = False
        budget = 1200
        while q and budget > 0:
            budget -= 1
            cur = q.popleft()
            if cur == goal:
                found = True
                break
            dd = cur.distance_squared(goal)
            if dd < bd:
                bd, best = dd, cur
            for d in dirs:
                n = cur.add(d)
                if n in prev or not self._inb(n):
                    continue
                if n != goal and (n in self.walls or n in self.blocked
                                  or (avoid is not None and n in avoid)):
                    continue
                prev[n] = cur
                q.append(n)
        dest = goal if found else best
        if dest == start:
            return None
        node = dest
        while prev[node] != start:
            node = prev[node]
        return start.direction_to(node)

    def _band_tiles(self, ct):
        """Every tile covered by a VISIBLE enemy sentinel's kill band —
        facings are public (get_direction is cross-team) and sentinels
        never rotate, so this is exact, standing intel."""
        tiles = set()
        for b in ct.get_nearby_buildings():
            if not self._enemy(ct, b):
                continue
            if ct.get_entity_type(b) != EntityType.SENTINEL:
                continue
            try:
                sp = ct.get_position(b)
                sd = ct.get_direction(b)
            except Exception:
                continue
            dx, dy = sd.delta()
            lx, ly = sp.x, sp.y
            for _ in range(6):
                lx += dx
                ly += dy
                for ox in (-1, 0, 1):
                    for oy in (-1, 0, 1):
                        t = Position(lx + ox, ly + oy)
                        if self._inb(t) and t.distance_squared(sp) <= 32:
                            tiles.add(t)
        return tiles

    def _step_safe(self, ct, goal: Position) -> None:
        """_step_toward that walks AROUND known sentinel bands. This is what
        the naive pod excursion lacked (kills-against tripled: defenders
        walked straight through the kill zone they could have read)."""
        pos = ct.get_position()
        avoid = self._band_tiles(ct)
        avoid.discard(pos)
        d = self._bfs_step(ct, goal, cardinal=True, avoid=avoid)
        if d is not None:
            n = pos.add(d)
            if self._inb(n) and ct.can_move(d):
                ct.move(d)
                return
            self.blocked[n] = ct.get_current_round()
        # no band-free path: hold position rather than feed the guns
        return

    # ------------------------------------------------------- defense builds

    def _live_defense(self, ct, th=None):
        """(launchers, turrets) of OURS currently ALIVE near our core. Lifetime
        counters never noticed our defenses being destroyed -> we never rebuilt
        while Oogway ground us down (kills at t210-817).
        With `th`: count only turrets whose RANGE covers the threat — a turret
        that can't reach the attacker is not defense (cte kills: our garrison
        'defended' from across the base while their turrets ate the core)."""
        L = T = 0
        if self.core_pos is None:
            return 0, 0
        for b in ct.get_nearby_buildings():
            if self._enemy(ct, b):
                continue
            et = ct.get_entity_type(b)
            bp = ct.get_position(b)
            if bp.distance_squared(self.core_pos) > THREAT_RAD_SQ:
                continue
            if et == EntityType.LAUNCHER:
                L += 1
            elif et in (EntityType.GUNNER, EntityType.SENTINEL):
                if th is not None:
                    reach = 32 if et == EntityType.SENTINEL else 13
                    if bp.distance_squared(th) > reach:
                        continue
                T += 1
        return L, T

    def _build_launcher(self, ct) -> bool:
        if ct.get_global_resources() < ct.get_launcher_cost() + RESERVE:
            return False
        pos = ct.get_position()
        # don't stack: skip if a friendly launcher is already nearby
        for b in ct.get_nearby_buildings():
            if not self._enemy(ct, b) and ct.get_entity_type(b) == EntityType.LAUNCHER:
                if ct.get_position(b).distance_squared(pos) <= 25:
                    self.launchers_built = 1
                    return False
        for d in DIRECTIONS:
            bp = pos.add(d)
            if self._inb(bp) and ct.can_build_launcher(bp):
                ct.build_launcher(bp)
                self.launchers_built += 1
                return True
        return False

    def _battery(self, ct, aim, sentinel: bool, must_engage: bool = False) -> bool:
        """Fed turret: harvester on ore + turret DIRECTLY adjacent (verified).
        must_engage: only build if some facing can actually HIT `aim` from the
        spot — replay data (pinch, 71fcaf46 g2): we built 32 'counter'
        sentinels that could never reach the threat and dealt ~100 dmg total.
        Scrap factories lose games."""
        pos = ct.get_position()
        if self.batt_step == 2:
            ok = (ct.can_build_sentinel(self.batt_G, self.batt_dir) if self.batt_sent
                  else ct.can_build_gunner(self.batt_G, self.batt_dir))
            if ok:
                if self.batt_sent:
                    ct.build_sentinel(self.batt_G, self.batt_dir)
                else:
                    ct.build_gunner(self.batt_G, self.batt_dir)
                    ct.write_store(S_GUN_N, ct.read_store(S_GUN_N) + 1)
                self.gunners_built += 1
            self.batt_step = 0
            return ok
        if not sentinel and not self.small \
                and ct.read_store(S_GUN_N) >= GUN_CAP:
            return False  # big-map gunner budget spent: mine, don't churn
        cost = ct.get_sentinel_cost() if sentinel else ct.get_gunner_cost()
        if ct.get_global_resources() < cost + ct.get_harvester_cost() + RESERVE:
            return False
        want = EntityType.SENTINEL if sentinel else EntityType.GUNNER
        # prefer turret tiles OUTSIDE the enemy sentinel's (public, fixed)
        # kill band — she can't rotate to answer an out-of-band counter
        band = self._enemy_band(ct, aim)
        g_dirs = sorted(DIRECTIONS,
                        key=lambda d: self._in_band(band, pos.add(d)))
        for dO in DIRECTIONS:
            O = pos.add(dO)
            if not self._inb(O) or not ct.can_build_harvester(O):
                continue
            for dG in g_dirs:
                G = pos.add(dG)
                if G == O or not self._inb(G) or G.distance_squared(O) > 2:
                    continue
                if not ct.is_tile_empty(G):
                    continue
                # a CARDINAL-facing turret cannot accept ammo from the tile
                # it faces — never face the feeder O (diagonals feed from
                # all four sides, so they are always safe)
                feed_starved = (lambda f: f in CARDINALS and G.add(f) == O)
                facing = ncard(O.direction_to(G))  # points away from O
                if aim is not None and G != aim:
                    f = G.direction_to(aim)
                    if f != Direction.CENTRE:
                        facing = f.rotate_right() if feed_starved(f) else f
                engaged = False
                if aim is not None:
                    for f in DIRECTIONS:
                        if feed_starved(f):
                            continue
                        try:
                            if ct.can_fire_from(G, f, want, aim):
                                facing = f
                                engaged = True
                                break
                        except Exception:
                            pass
                if must_engage and not engaged:
                    continue  # can't hit the threat from here: don't build scrap
                # never leave a turret whose lane covers OUR OWN core (the
                # engine happily targets friendlies — see _gunner). This
                # fixup used to grab ANY core-safe facing — silently
                # discarding the ENGAGED one (the "gunner facing the
                # opposite way" in ad0b1fb9 g3). Prefer a facing that both
                # engages and avoids the core; under must_engage, skip the
                # spot if none exists.
                if self.core_pos is not None:
                    try:
                        if ct.can_fire_from(G, facing, want, self.core_pos):
                            safe_any, safe_eng = None, None
                            for f in DIRECTIONS:
                                if feed_starved(f):
                                    continue
                                if ct.can_fire_from(G, f, want, self.core_pos):
                                    continue
                                if safe_any is None:
                                    safe_any = f
                                if aim is not None:
                                    try:
                                        if ct.can_fire_from(G, f, want, aim):
                                            safe_eng = f
                                            break
                                    except Exception:
                                        pass
                            if safe_eng is not None:
                                facing = safe_eng
                            elif must_engage or safe_any is None:
                                continue
                            else:
                                facing = safe_any
                    except Exception:
                        pass
                can = (ct.can_build_sentinel(G, facing) if sentinel
                       else ct.can_build_gunner(G, facing))
                if not can:
                    continue
                ct.build_harvester(O)
                ct.write_store(S_HARV, ct.read_store(S_HARV) + 1)
                self.batt_G, self.batt_dir, self.batt_sent = G, facing, sentinel
                self.batt_step = 2
                self.target = pos
                return True
        return False

    def _core_hurt(self, ct) -> int:
        """Our core's missing HP (0 if healthy or out of vision)."""
        for b in ct.get_nearby_buildings():
            if not self._enemy(ct, b) and \
                    ct.get_entity_type(b) == EntityType.CORE:
                try:
                    return ct.get_max_hp(b) - ct.get_hp(b)
                except Exception:
                    return 0
        return 0

    def _heal_core(self, ct) -> bool:
        """Stand by the core and pump HP into it. 4 HP per 1 Ti per action:
        two builders healing out-repair a sentinel's 6 dmg/round for 2 Ti —
        the sprint loss (f23a916a g1) was 630 core damage with nobody on
        repair duty."""
        if self.core_tiles is None:
            return False
        pos = ct.get_position()
        if ct.get_action_cooldown() == 0:
            for t in self.core_tiles:
                if pos.distance_squared(t) <= 2:
                    try:
                        if ct.can_heal(t):
                            ct.heal(t)
                            return True
                    except Exception:
                        pass
        ring = self._core_ring_tile(pos)
        if ring is not None and pos != ring:
            self.target = ring
            self._step_toward(ct, ring)
            return True
        return False

    def _heal(self, ct) -> None:
        pos = ct.get_position()
        for d in DIRECTIONS:
            c = pos.add(d)
            if self._inb(c) and ct.can_heal(c):
                ct.heal(c)
                return

    # -------------------------------------------------------------- sieger

    def _sieger(self, ct: Controller) -> None:
        """Harass the enemy core: destroy their conveyors, wall their ring with
        barriers, and plant a fed sentinel aimed at the core when ore is free."""
        pos = ct.get_position()

        # record the enemy core once seen
        if self.enemy_core is None:
            st = unpack(ct.read_store(S_ENEMY_CORE))
            if st is not None:
                self.enemy_core = st
            else:
                for b in ct.get_nearby_buildings():
                    if self._enemy(ct, b) and ct.get_entity_type(b) == EntityType.CORE:
                        self.enemy_core = ct.get_position(b)
                        ct.write_store(S_ENEMY_CORE, pack(self.enemy_core))
                        break

        # standing on an enemy conveyor: kill it (own-tile fire). Near their
        # core this is always right — ring conveyors must die to be walled,
        # and post-seal the sealer's whole job is eating their network. Only
        # skip while still RACING across the map (far from their core).
        b = ct.get_tile_building_id(pos)
        if b is not None and self._enemy(ct, b):
            if pos.distance_squared(self._enemy_core_guess()) <= 50:
                if ct.get_action_cooldown() == 0 and ct.can_fire(pos):
                    ct.fire(pos)
                return
            # mid-race: just step off and keep moving (handled below)

        # finish a siege battery in progress
        if self.batt_step > 0:
            if ct.get_action_cooldown() == 0:
                self._battery(ct, self.enemy_core, True)
            return

        ecore = self._enemy_core_guess()

        # 2.2 GUNNER RUSH (Besvikomat's own weapon, mirrored): pool-fed
        # gunners need no feeder — plant them straight onto THEIR spawn
        # ring the moment we arrive. Every spawn they make gets one-clipped
        # (reload 1); their crew must respond or die, and either way their
        # economy stops. Cheaper and faster than the legacy fed-sentinel
        # siege below, which stays as the follow-up once guns stand.
        if (self.enemy_core is not None
                and ct.get_action_cooldown() == 0
                and getattr(self, "rush_guns", 0) < SIEGE_RUSH_GUNS
                and pos.distance_squared(self.enemy_core) <= 60
                and ct.get_global_resources()
                >= ct.get_gunner_cost() + RESERVE):
            spots = sorted(
                (pos.add(dG) for dG in DIRECTIONS),
                key=lambda t: t.distance_squared(self.enemy_core))
            for G in spots:
                if not self._inb(G) or not ct.is_tile_empty(G):
                    continue
                if G.distance_squared(self.enemy_core) > 13:
                    continue
                facing = ncard(G.direction_to(self.enemy_core))
                try:
                    for fc in CARDINALS:
                        if ct.can_fire_from(G, fc, EntityType.GUNNER,
                                            self.enemy_core):
                            facing = fc
                            break
                except Exception:
                    pass
                if ct.can_build_gunner(G, facing):
                    ct.build_gunner(G, facing)
                    self.rush_guns = getattr(self, "rush_guns", 0) + 1
                    return

        if self.enemy_core is not None:
            # BARRIERS FIRST (the user's doctrine): circle their core ring
            # with barriers the moment we arrive — the seal chokes spawns and
            # deliveries. Conveyor sabotage comes right after; the kill damage
            # comes from the miners' fed sentinels, not from this builder.
            near = pos.distance_squared(self.enemy_core)
            ax, ay = self.enemy_core.x, self.enemy_core.y
            foot = {Position(ax + a, ay + b2) for a in (0, 1) for b2 in (0, 1)}
            ring = [Position(x, y) for x in range(ax - 1, ax + 3)
                    for y in range(ay - 1, ay + 3)
                    if Position(x, y) not in foot and self._inb(Position(x, y))]
            if not SIEGE_SEAL:
                # gunner doctrine: no wall. Close to gun-planting range and
                # fall through to conveyor sabotage / patrol pressure below.
                ring = []
                if near > 8:
                    self.target = self.enemy_core
                    self._step_toward(ct, self.enemy_core)
                    return
            # RE-SEAL: 'sealed' used to be forever — every barrier she shot
            # out stayed marked done and the seal silently decayed. A sealed
            # ring tile seen EMPTY goes back on the wall list. (Her builders
            # can't remove barriers at all — impassable means they can't
            # stand on one to attack it — only turret fire breaks a seal,
            # so a MAINTAINED seal is spawn+delivery denial that sticks.)
            self.ring_tries = getattr(self, "ring_tries", {})
            for r in list(self.sealed):
                if r in ring and ct.is_in_vision(r):
                    try:
                        if (ct.get_tile_env(r) != Environment.WALL
                                and ct.get_tile_building_id(r) is None
                                and ct.get_tile_builder_bot_id(r) is None):
                            self.sealed.discard(r)
                            self.ring_tries[r] = 0
                    except Exception:
                        pass
            todo = []
            for r in ring:
                if r in self.sealed:
                    continue
                if ct.is_in_vision(r):
                    if ct.get_tile_env(r) == Environment.WALL:
                        self.sealed.add(r)  # nature sealed it
                        continue
                    rb = ct.get_tile_building_id(r)
                    if rb is not None:
                        if self._enemy(ct, rb) and ct.get_entity_type(rb) in (
                                EntityType.CONVEYOR, EntityType.SPLITTER):
                            todo.append(r)  # kill it (stand on it), then wall
                        else:
                            self.sealed.add(r)  # their turret/our stuff: skip
                        continue
                todo.append(r)
            if near > 10 and any(pos.distance_squared(r) > 2 for r in todo):
                # not at the ring yet: close in before anything else
                if not todo or min(r.distance_squared(pos) for r in todo) > 2:
                    self.target = self.enemy_core
                    self._step_toward(ct, self.enemy_core)
                    return
            # wall any adjacent unsealed ring tile; tiles we repeatedly CAN'T
            # wall (enemy builder standing there) get skipped after retries —
            # a partial circle + moving on to the attack beats freezing.
            self.ring_tries = getattr(self, "ring_tries", {})
            if ct.get_action_cooldown() == 0 and ct.get_global_resources() >= ct.get_barrier_cost() + RESERVE:
                for r in todo:
                    if pos.distance_squared(r) <= 2 and r != pos:
                        if ct.can_build_barrier(r):
                            ct.build_barrier(r)
                            self.sealed.add(r)
                            return
                        self.ring_tries[r] = self.ring_tries.get(r, 0) + 1
                        if self.ring_tries[r] > 10:
                            self.sealed.add(r)  # give up on this tile
            todo = [r for r in todo if r not in self.sealed]
            # navigate to the nearest unsealed ring tile
            if todo:
                goal = min(todo, key=lambda r: r.distance_squared(pos))
                if goal == pos:
                    # we're STANDING on the tile we need to wall (just killed a
                    # conveyor here) — step OFF it so we can barrier it next
                    # turn. Without this the sieger froze here forever.
                    for d in DIRECTIONS:
                        n = pos.add(d)
                        if self._inb(n) and n not in foot and ct.can_move(d):
                            ct.move(d)
                            return
                    return
                self.target = goal
                self._step_toward(ct, goal)
                return
            # ring complete -> the user's doctrine, in order:
            # (1) KEEP BREAKING their conveyors RIGHT NEXT TO their core
            #     (their supply reroutes here constantly; stand on them and
            #     the own-tile fire at the top of _sieger kills them),
            # (2) once none are visible near the core, plant fed sentinels
            #     aimed at it (ore-fed; enemy conveyors/harvesters verified
            #     NOT to feed our turrets), (3) then hunt any conveyor.
            near_cut, far_cut = None, None
            near_d, far_d = None, None
            for b2 in ct.get_nearby_buildings():
                if not self._enemy(ct, b2):
                    continue
                if ct.get_entity_type(b2) not in (EntityType.CONVEYOR, EntityType.SPLITTER):
                    continue
                bp = ct.get_position(b2)
                dd = bp.distance_squared(pos)
                if bp.distance_squared(self.enemy_core) <= 18:
                    if near_d is None or dd < near_d:
                        near_d, near_cut = dd, bp
                elif far_d is None or dd < far_d:
                    far_d, far_cut = dd, bp
            if near_cut is not None:
                self.target = near_cut
                self._step_toward(ct, near_cut)
                return
            self.siege_sents = getattr(self, "siege_sents", 0)
            if (self.siege_sents < SIEGE_SENTS and ct.get_action_cooldown() == 0
                    and ct.get_global_resources() >=
                    ct.get_sentinel_cost() + ct.get_harvester_cost() + RESERVE):
                if self._battery(ct, self.enemy_core, sentinel=True):
                    self.siege_sents += 1
                    return
                if self._sentinel_by_harvester(ct, self.enemy_core):
                    self.siege_sents += 1
                    return
            if far_cut is not None:
                self.target = far_cut
                self._step_toward(ct, far_cut)
                return
            # nothing visible to attack: PATROL around their core (rotating
            # waypoints) — standing still froze the sieger until game end.
            self._patrol_i = (getattr(self, "_patrol_i", 0) + 1) % len(DIRECTIONS)
            dx, dy = DIRECTIONS[self._patrol_i].delta()
            wp = Position(
                min(max(self.enemy_core.x + dx * 3, 1), self.w - 2),
                min(max(self.enemy_core.y + dy * 3, 1), self.h - 2),
            )
            self.target = wp
            self._step_toward(ct, wp)
            return

        # march at the enemy core
        if self.stuck > 40:
            # can't reach them (walled/boxed): stop wasting the unit
            self.role = "miner"
            return
        self.target = ecore
        self._step_toward(ct, ecore)

    # ------------------------------------------------------------- turrets

    def _rotate_to_threat(self, ct, range_sq) -> None:
        """A wrong-facing turret is dead weight (scouted: 'our sentinels were
        not shooting' while cte's siege chewed the core). If a live threat is
        in range but not in our firing arc, ROTATE toward it (gunner rotate =
        10 Ti + 1 cooldown; try the same call for sentinels)."""
        if ct.get_action_cooldown() != 0:
            return
        if not self._may_rotate(ct):
            return
        r = ct.read_store(S_THREAT_R)
        if not r or ct.get_current_round() - r > 12:
            return
        th = unpack(ct.read_store(S_THREAT))
        if th is None:
            return
        pos = ct.get_position()
        if pos.distance_squared(th) > range_sq:
            return
        try:
            if any(t.distance_squared(th) == 0 for t in ct.get_attackable_tiles()):
                return  # already covering it; just no ammo or timing
            d = ncard(pos.direction_to(th))
            if ct.can_rotate(d):
                ct.rotate(d)
                self.rot_round = ct.get_current_round()
                self.rot_since_fire = getattr(self, "rot_since_fire", 0) + 1
        except Exception:
            pass

    def _may_rotate(self, ct) -> bool:
        """Rotation discipline: 10 Ti each. Pinch replay (0ca946bc g3): our 3
        gunners emitted 444 rotations ≈ 4,400 Ti — more than the titanium
        margin we lost by. Never rotate dry (nothing to shoot after turning),
        and never thrash (two enemies on alternating sides = a 10 Ti/round
        metronome)."""
        try:
            if ct.get_global_ammo() == 0:
                return False
        except Exception:
            pass
        # a DANCING enemy re-baits every rotation (sprint-as-B: 219 rotations
        # = 2,190 Ti even WITH the 4-round spacing). Three turns without
        # landing a shot = stop chasing; parked guns still die (they get
        # shot after one rotation, which resets the count).
        if getattr(self, "rot_since_fire", 0) >= 3:
            return False
        return ct.get_current_round() - getattr(self, "rot_round", -9) >= 4

    def _gunner_retarget(self, ct) -> None:
        """Rotate toward the nearest enemy WE can see (own turret vision),
        instead of the single shared threat flag — that flag is stale and
        points at ONE position while Barbie sieges with several sentinels
        from different sides. rotate() = 10 Ti, gunner-only."""
        if ct.get_action_cooldown() != 0:
            return
        if not self._may_rotate(ct):
            return
        pos = ct.get_position()
        best, bd = None, None
        try:
            home = (self.core_pos is not None and
                    pos.distance_squared(self.core_pos) <= THREAT_RAD_SQ)
            for eid in ct.get_nearby_entities():
                if not self._enemy(ct, eid):
                    continue
                # OUTPOST gunners never rotate to chase builder bots:
                # 10 Ti per turn-chase vs Oogway's 25-35 builder swarm =
                # 125 gunner-events on hive (~1000+ Ti). Shots at whatever
                # crosses the lane stay free-ish (2 Ti) and his respawns
                # cost ~150+ at swarm scale. HOME gunners still turn —
                # rushers must be faced (the blanket ban was 6-kills-
                # against poison).
                if (not home and ct.get_entity_type(eid)
                        == EntityType.BUILDER_BOT):
                    continue
                ep = ct.get_position(eid)
                dd = ep.distance_squared(pos)
                if dd <= 13 and (bd is None or dd < bd):
                    bd, best = dd, ep
        except Exception:
            return
        if best is None:
            self._rotate_to_threat(ct, 13)  # fall back to the broadcast flag
            return
        try:
            if any(t == best for t in ct.get_attackable_tiles()):
                return  # already facing it — just ammo/cooldown timing
            d = pos.direction_to(best)
            if d != Direction.CENTRE and ct.can_rotate(d):
                ct.rotate(d)
                self.rot_round = ct.get_current_round()
                self.rot_since_fire = getattr(self, "rot_since_fire", 0) + 1
                return
            d = ncard(d)
            if ct.can_rotate(d):
                ct.rotate(d)
                self.rot_round = ct.get_current_round()
                self.rot_since_fire = getattr(self, "rot_since_fire", 0) + 1
        except Exception:
            pass

    def _gunner(self, ct: Controller) -> None:
        t = ct.get_gunner_target()
        if t is None or not ct.can_fire(t):
            self._gunner_retarget(ct)
            return
        # NEVER shoot friendlies: get_gunner_target() returns whatever is in
        # the lane, INCLUDING OUR OWN CORE — a wrongly-faced gunner shot our
        # core dead by t62 (sprint) before this check existed.
        try:
            b = ct.get_tile_building_id(t)
            u = ct.get_tile_builder_bot_id(t)
        except Exception:
            return
        eb = b is not None and self._enemy(ct, b)
        eu = u is not None and self._enemy(ct, u)
        if not (eb or eu):
            self._gunner_retarget(ct)
            return
        ct.fire(t)
        self.rot_since_fire = 0

    def _sentinel(self, ct: Controller) -> None:
        # fire ONLY at enemy-occupied tiles (can_fire is true for empty tiles
        # too — wasting shots on nothing was the bug that broke our sieges).
        pos = ct.get_position()
        best, key = None, None
        for t in ct.get_attackable_tiles():
            if not ct.can_fire(t):
                continue
            b = ct.get_tile_building_id(t)
            u = ct.get_tile_builder_bot_id(t)
            eb = b is not None and self._enemy(ct, b)
            eu = u is not None and self._enemy(ct, u)
            if not (eb or eu):
                continue
            core = eb and ct.get_entity_type(b) == EntityType.CORE
            k = (0 if core else 1, t.distance_squared(pos))
            if key is None or k < key:
                key, best = k, t
        if best is not None:
            ct.fire(best)
        # (no rotate here: rotate() is GUNNER-ONLY in the API — sentinels are
        # fixed forever at build-time facing. That's why defense is gunners
        # now and sentinels are offense-only, aimed at the immobile core.)

    def _launcher(self, ct: Controller) -> None:
        """Fling adjacent ENEMY builders away. Throws must land within range²26
        of the launcher — aiming across the map silently failed forever (the
        'launchers do nothing' bug). Throw as far as legal, biased away from
        our core so the attacker loses the most ground."""
        pos = ct.get_position()
        self._read_core(ct)
        away = self._enemy_core_guess()
        for d in DIRECTIONS:
            adj = pos.add(d)
            if not self._inb(adj):
                continue
            bid = ct.get_tile_builder_bot_id(adj)
            if bid is None or not self._enemy(ct, bid):
                continue
            # candidate landing spots: farthest first, prefer toward enemy side
            cands = []
            for dx, dy in THROW_OFFSETS:
                t = Position(pos.x + dx, pos.y + dy)
                if not self._inb(t):
                    continue
                bias = t.distance_squared(self.core_pos) if self.core_pos else 0
                cands.append((-(dx * dx + dy * dy), -bias, t))
            cands.sort()
            for _, _, t in cands:
                if ct.can_launch(adj, t):
                    ct.launch(adj, t)
                    return

        # TAXI SERVICE: no enemy to fling — throw a requesting FRIENDLY
        # builder toward its stored destination (cte's launcher-highway
        # mobility, decoded from their fjord opening: center harvesters by
        # t14 via thrown builders). Land as close to the goal as legal.
        r = ct.read_store(S_TAXI_R)
        if not r or ct.get_current_round() - r > 2:
            return
        goal = unpack(ct.read_store(S_TAXI))
        rider = ct.read_store(S_TAXI_ID)
        if goal is None or not rider:
            return
        for d in DIRECTIONS:
            adj = pos.add(d)
            if not self._inb(adj):
                continue
            bid = ct.get_tile_builder_bot_id(adj)
            if bid is None or self._enemy(ct, bid):
                continue
            # ONLY the requester flies — the first live version threw ANY
            # adjacent friendly builder, i.e. usually a DEFENDER off the
            # ring mid-siege (cte 1-4 on V56 while labs said 60% PROMOTE:
            # mimics siege too gently to expose it)
            if bid != rider:
                continue
            if adj.distance_squared(goal) <= 2:
                continue  # already basically there
            best_t, best_d = None, adj.distance_squared(goal)
            for dx, dy in THROW_OFFSETS:
                t = Position(pos.x + dx, pos.y + dy)
                if not self._inb(t):
                    continue
                dd = t.distance_squared(goal)
                if dd < best_d and ct.can_launch(adj, t):
                    best_d, best_t = dd, t
            if best_t is not None:
                ct.launch(adj, best_t)
                ct.write_store(S_TAXI_R, 0)  # served
                return
