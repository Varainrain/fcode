"""DEFENSE ADVISOR — the gated defense stack as pure decision functions.

Contract (MODULES.md): a module never takes a turn, it answers questions.
No control flow, no moveTo, no returns-that-eat-turns. The chassis arbiter
calls these and decides. Every function is stateless except the documented
store slots (14 = healer claim; nothing else).

Gate receipts for what these encode (all on-chassis, 84-168g + scrims):
  - sentinel-line seal + triage ...... Pantheon 4-1 (was 0-5)   [v33/v34/v37]
  - split-duty healer (slot 14) ...... OopsGotYourElo 4-1        [v42]
  - anti-entombment placement veto ... Besvikomat 4-1            [v44]
  - home-sentinel rotation floor ..... sporks loss autopsy fix   [v39]

Owner: ic3d + Claude. Integrator: Oogway (chassis). See DEFENSE-INTEGRATION.md
for exact call sites in OogwayPlus and the two measured ways NOT to hook it.
"""

from fcode import Controller, Direction, EntityType, Environment, Position

HEAL_TRIAGE_HP = 350      # below this, shields yield to heals entirely
HEAL_CLAIM_HP = 480       # below this, ONE unit per round becomes the healer
HEAL_CLAIM_SLOT = 14      # store: claim round (self-expiring)
MIN_OPEN_EXITS = 3        # never wall the core pocket below this many exits


def shield_tiles(core: Position, mapW: int, mapH: int):
    """The 12-tile sentinel-line seal for a core at `core` (top-left of 2x2):
    4 diagonal corner tiles (kill diagonal lines) + 8 cardinal lane tiles at
    distance 2 (kill straight lines; d1 ring stays free for spawns/heals).
    Pure geometry — cache per game."""
    cand = [
        Position(core.x - 1, core.y - 1), Position(core.x + 2, core.y - 1),
        Position(core.x - 1, core.y + 2), Position(core.x + 2, core.y + 2),
        Position(core.x,     core.y - 2), Position(core.x + 1, core.y - 2),
        Position(core.x,     core.y + 3), Position(core.x + 1, core.y + 3),
        Position(core.x - 2, core.y),     Position(core.x - 2, core.y + 1),
        Position(core.x + 3, core.y),     Position(core.x + 3, core.y + 1),
    ]
    return [p for p in cand if 0 <= p.x < mapW and 0 <= p.y < mapH]


def next_shield_gap(ct: Controller, core: Position, mapW: int, mapH: int):
    """The next seal tile needing a barrier, or None.
    None also when the core is in triage (< HEAL_TRIAGE_HP): armoring a
    corpse was the 0-heal bug — heals outrank armor once it matters."""
    try:
        cid = ct.get_tile_building_id(core)
        if cid is not None and ct.get_hp(cid) < HEAL_TRIAGE_HP:
            return None
    except Exception:
        pass
    for sp in shield_tiles(core, mapW, mapH):
        try:
            if not ct.is_in_vision(sp):
                continue
            if ct.get_tile_building_id(sp) is not None:
                continue
            if ct.get_tile_env(sp) != Environment.EMPTY:
                continue
        except Exception:
            continue
        return sp
    return None


def claim_heal_duty(ct: Controller, core: Position) -> bool:
    """True exactly once per round for ONE unit while the core is hurt.
    All-heal locks measured 42% (everyone nurses a scratch while the siege
    turret keeps firing); one healer + everyone else fighting measured
    4-1 vs the team that out-healed us. Claim is a round-stamp in slot 14,
    self-expiring — no cleanup needed, crashes cannot wedge it."""
    try:
        cid = ct.get_tile_building_id(core)
        if cid is None or ct.get_hp(cid) >= HEAL_CLAIM_HP:
            return False
        rnd = ct.get_current_round()
        if ct.read_store(HEAL_CLAIM_SLOT) >= rnd:
            return False
        ct.write_store(HEAL_CLAIM_SLOT, rnd + 1)
        return True
    except Exception:
        return False


def would_entomb(ct: Controller, core: Position, spot: Position,
                 myTeam, mapW: int, mapH: int) -> bool:
    """Placement VETO: would an impassable building at `spot` leave the core
    pocket with fewer than MIN_OPEN_EXITS open tiles? (0788a40d g1: our own
    conveyors + defensive gunners sealed every exit; all 14 builders parked
    450 turns; we lost without the enemy touching our core.) Own barriers
    count as OPEN — they are passable to our own units. Call this before
    ANY conveyor/gunner/harvester build within 3 of the core."""
    dmin = min(abs(spot.x - c[0]) + abs(spot.y - c[1])
               for c in ((core.x, core.y), (core.x + 1, core.y),
                         (core.x, core.y + 1), (core.x + 1, core.y + 1)))
    if dmin > 3:
        return False
    openExits = 0
    for dx in (-1, 0, 1, 2):
        for dy in (-1, 0, 1, 2):
            if 0 <= dx <= 1 and 0 <= dy <= 1:
                continue
            q = Position(core.x + dx, core.y + dy)
            if not (0 <= q.x < mapW and 0 <= q.y < mapH):
                continue
            if q.x == spot.x and q.y == spot.y:
                continue
            try:
                if not ct.is_in_vision(q):
                    continue
                if ct.get_tile_env(q) != Environment.EMPTY:
                    continue
                bid = ct.get_tile_building_id(q)
                if bid is None:
                    openExits += 1
                elif (ct.get_team(bid) == myTeam
                        and ct.get_entity_type(bid) == EntityType.BARRIER):
                    openExits += 1
            except Exception:
                continue
    return openExits < MIN_OPEN_EXITS


def sentinel_is_core_threat(core: Position, tile: Position) -> bool:
    """For the gunner rotation scorer: an enemy SENTINEL within manhattan 7
    of OUR core counts as a core threat (rotate at the cheap floor).
    SCOPED — the unscoped version let every gunner map-wide rotate at the
    cheap floor and bled the bank (17%). Radius is the whole fix."""
    return abs(tile.x - core.x) + abs(tile.y - core.y) <= 7
