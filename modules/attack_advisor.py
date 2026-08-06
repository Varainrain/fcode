"""ATTACK/SIEGE advisors for the OogwayAttack chassis — engine 2.3.6.

MODULES.md contract: nothing in here takes a turn, moves, builds or fires. Every
function answers one question from observable game state and returns a value the
chassis arbiter is free to outvote. No map names, no opponent identity, no
side/seed assumptions.

Measured on 2026-08-06 against `bots/OogwayAttack` (engine 2.3.6, synced 15-map
pool). Read the gate receipts in each docstring before adopting: several of
these fix a mechanism that is provably broken and STILL do not move the win
rate, because the gate cannot resolve anything under about ten points (a
byte-identical null read 61% and 49% on two 120-game runs; pooled 240 games it
read 55%, CI 48.6-61.2). Mechanism receipts are therefore quoted alongside, and
they are the stronger evidence.

THE 2.3.6 COST LAW (measured, bots/probe_scale + probe_scale2):

    scale% = 100 + 20 x (living units - 1) + 1 x (living buildings)
    cost   = base cost x scale% / 100

so a gunner costs 20 Ti on turn 0 and 58-72 Ti by t40+. Every hardcoded
titanium threshold in the chassis was written against a flat 10-20 Ti gunner and
is now wrong in both directions. Ask the engine.
"""

# Engine constants that the advisors depend on (fcode 2.3.6, verified from
# GameConstants at runtime, not from any doc in this repo).
GUNNER_AMMO_COST = 4
CORE_AMMO_FLOOR = 28      # the chassis' own convert_ammo reserve in runCore


def gunner_seat_floor(ct, reserve=CORE_AMMO_FLOOR):
    """Titanium an attacker should hold before committing to a gunner seat.

    Replaces the hardcoded `>= 96` in runAttack (and `>= 30` in the harvester
    harass branch). 96 is roughly 5x the cost of a gunner at t0 - so the cheap
    early seats, taken before the enemy has any defence, are refused - and by
    t200 it is barely above the real cost, so passing it can still leave the
    bank under the core's own 28 Ti ammo-conversion floor.

    GATE RECEIPT (bots/oa_a2, 120 games vs OogwayAttack): 52%, CI 43.6-61.2 -
    inside the null band, no measurable effect. MECHANISM RECEIPT (bots/oa_trace,
    12 games): the flat gate refused an affordable seat on only 1.0% of attacker
    turns, so the defect is real but rare on this chassis. Adopt for correctness,
    not for points.
    """
    return ct.get_gunner_cost() + reserve


def pool_has_a_shot(ct):
    """True if the team's global ammo can pay for at least one gunner shot.

    Turrets fire from one pool that only the core refills, 1:1 from titanium,
    at most once per turn. A gunner seated while the pool is empty is 20-72 Ti
    of scenery; the same titanium left in the bank becomes ammo next turn.

    MECHANISM RECEIPT (bots/oa_trace, 12 games): 19.2% of all attacker turns ran
    with the pool below one shot. ⚠ GATE RECEIPT (bots/oa_a7, 240 games vs
    OogwayAttack): 47.1%, CI 40.9-53.4 — below the null. Withholding the seat
    does not pay: the turn spent not-seating is worth less than a gun that is
    briefly dry, because the pool refills the same turn the core converts. Use
    this to inform a scorer, not as a veto.
    """
    return ct.get_global_ammo() >= GUNNER_AMMO_COST


def recommended_ammo_ceiling(ct, per_turret_burst=3):
    """What the core's convert_ammo ceiling should be, instead of the flat 16.

    NOT OUR CALL SITE - this lives in runCore, which is chassis/econ territory.
    It is here because it is the offense's ammunition supply and it is the
    single largest throttle we measured: at 16 the whole team, attack and
    defence together, can fire four gunner shots per turn no matter how many
    turrets are standing. v44 already ran this line at 60.

    MECHANISM RECEIPT (bots/oa_trace vs bots/oa_trace4, same 6 maps and seed):
    ammo-dry attacker turns 8.4% -> 0.0% with the ceiling at 60, at the cost of
    seating ~40% fewer guns (8 -> 5) because the titanium goes to ammo instead.
    GATE RECEIPT (bots/oa_a4, 360 games vs OogwayAttack): 50.6%, CI 45.4-55.7 —
    dead level with the null. The throttle is real and relieving it is a wash,
    which localises the true constraint: at the margin the offense is TITANIUM
    bound, not ammo bound, and under the 2.3.6 cost law titanium is set by our
    own living unit/building count. Adopt for the burst capacity if you want it;
    do not expect points.
    """
    turrets = 0
    myTeam = ct.get_team()
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) == myTeam and ct.get_entity_type(b) in TURRETS:
            turrets += 1
    return max(16, GUNNER_AMMO_COST * per_turret_burst * max(1, turrets))


def first_entity_on_ray(ct, tiles):
    """The (kind, id) a shot down this facing would ACTUALLY hit, or (None, None).

    kind is 'builder' or 'building'. A gunner's shot stops at the first entity
    on the ray, but the chassis' rotation scorer in runGunner sums hits across
    every tile the ray covers, so a facing that passes through an enemy conveyor
    at range 1 and their core at range 2 scores a core hit it can never land.
    Feed each candidate facing's `get_attackable_tiles_from` output through this
    and score only what comes back.

    GATE RECEIPT (bots/oa_a9, 240 games vs OogwayAttack): 55.0%, CI 48.7-61.2 —
    the highest reading of the session and statistically level with the 53.3%
    null. So: no measured gain, no measured cost, and the scorer stops crediting
    facings with shots they cannot land. This is the one I would take on
    correctness grounds.
    """
    for tile in tiles:
        bbId = ct.get_tile_builder_bot_id(tile)
        if bbId is not None:
            return "builder", bbId
        tileId = ct.get_tile_building_id(tile)
        if tileId is not None:
            return "building", tileId
    return None, None


def enemy_builders_on(ct, tiles):
    """How many enemy BUILDER BOTS a facing covers.

    The rotation scorer only ever looked at get_tile_building_id, so enemy
    builders - the things that seat their guns and heal their core - were worth
    exactly zero. A facing covering two enemy builders scored (0,0,0,0) while a
    facing covering one enemy conveyor scored (0,0,0,1) and won the rotation.
    Rank this above the conveyor/harvester term, below core and turret terms.

    ⚠ GATE RECEIPT (bots/oa_a8, 240 games vs OogwayAttack): 45.8%, CI
    39.6-52.2 — the lowest reading of any candidate this session and the only
    one whose interval sits mostly below the null's. It does not separate, but
    do NOT adopt this on the evidence available: the plausible mechanism is that
    a rotation chasing mobile builders gives up standing core pressure. If you
    want it, rank builders strictly BELOW the core and turret terms and re-gate.
    """
    myTeam = ct.get_team()
    n = 0
    for tile in tiles:
        bbId = ct.get_tile_builder_bot_id(tile)
        if bbId is not None and ct.get_team(bbId) != myTeam:
            n += 1
    return n


def seat_is_taken(ct, spot):
    """True if another body is standing on this seat, making build_gunner illegal.

    MECHANISM RECEIPT (bots/oa_trace, 12 games): fires on 0.2% of attacker turns
    - the collision the code review predicted is real but almost never happens
    on this chassis. GATE RECEIPT (bots/oa_a3, 120 games): 52%, inside the null
    band. Recorded so nobody spends another session on it.
    """
    bbId = ct.get_tile_builder_bot_id(spot)
    return bbId is not None and bbId != ct.get_id()


# Imported late so this module has no hard dependency when only the pure
# arithmetic helpers above are wanted.
try:
    from fcode import EntityType
    TURRETS = (EntityType.GUNNER, EntityType.SENTINEL)
except Exception:  # pragma: no cover - only used by recommended_ammo_ceiling
    TURRETS = ()
