"""Attacking-builder state machine, gunner/sentinel spot-finding, ray-value
scoring, and turret-unit runtime (what an already-built gunner/sentinel does
on its own turn). Straight port of the current bot's siege logic, split into
this file and adapted to plain functions taking `player` explicitly.
"""

from fcode import Controller, Direction, EntityType, Environment, Position
from mapPathfinding import CARDINALS, DIRECTIONS, gunnerLines, sentinelLines
from eco import closest_claimant, core_footprint_manhattan

# facing -> (dx, dy, reach), derived from mapPathfinding's own tables so the
# reach per direction is defined in exactly one place.
GUN_RAY = {_d: (_dx, _dy, _k) for _dx, _dy, _k, _d in gunnerLines}
SENT_RAY = {_d: (_dx, _dy, _k) for _dx, _dy, _k, _d in sentinelLines}

sentinelAttackThreshold = 120
coreAttackThreshold = 2
alreadyGunnerThreshold = 1.2

C_SEARCH_CORE = (80, 120, 255)
C_MARCH_ATTACK = (255, 160, 60)
C_TURRET_SPOT = (255, 60, 255)
C_HEAL_GUNNER = (60, 255, 120)

def enemy_turret_coverage(ct: Controller, player) -> dict:
    enemyCoverage = {}
    myTeam = ct.get_team()

    for b in ct.get_nearby_buildings():
        bType = ct.get_entity_type(b)
        if ct.get_team(b) == myTeam or bType not in [EntityType.GUNNER, EntityType.SENTINEL]:
            continue
        bPos = ct.get_position(b)
        curDir = ct.get_direction(b)
        if bType == EntityType.GUNNER:
            for bDir in DIRECTIONS:
                tileScore = 1 if bDir == curDir else 0.5
                dx, dy = bDir.delta()
                maxK = 3 if bDir in CARDINALS else 2
                x, y = bPos.x, bPos.y
                for _ in range(maxK):
                    x += dx
                    y += dy
                    tilePos = Position(x, y)
                    if not (0 <= x < player.mapW and 0 <= y < player.mapH):
                        break
                    if not ct.is_in_vision(tilePos):
                        break
                    if ct.get_tile_env(tilePos) == Environment.WALL:
                        break
                    tileId = ct.get_tile_building_id(tilePos)
                    if tileId is not None:
                        if ct.get_team(tileId) != myTeam:
                            break
                    enemyCoverage[(x, y)] = enemyCoverage.get((x, y), 0) + tileScore
        else:
            maxK = 5 if  curDir in CARDINALS else 4
            dx, dy = curDir.delta()
            x, y = bPos.x, bPos.y
            for _ in range(maxK):
                x += dx
                y += dy
                if not (0 <= x < player.mapW and 0 <= y < player.mapH):
                    break
                enemyCoverage[(x, y)] = enemyCoverage.get((x, y), 0) + 1
                tilePos = Position(x, y)
                if not ct.is_in_vision(tilePos):
                    break
    return enemyCoverage

def get_attackable_tiles(ct: Controller, player, lines=None):
    enemyCore = player.mapPf.enemyCorePos
    coreCorners = [
        enemyCore, enemyCore.add(Direction.EAST), enemyCore.add(Direction.SOUTH),
        enemyCore.add(Direction.SOUTH).add(Direction.EAST)]
    coreAttackers = set()
    for corner in coreCorners:
        for spot in player.mapPf.gunnerSpots(corner, player.mapW, player.mapH, True, lines=lines):
            coreAttackers.add((spot[0], spot[1]))
    return coreAttackers

def find_gunner_spot(ct: Controller, player):
    enemyCoverage = enemy_turret_coverage(ct, player)
    coreAttackers = get_attackable_tiles(ct, player)
    bestAttacker, bestScore = None, None
    myLoc = ct.get_position()
    enemyCore = player.mapPf.enemyCorePos
    for spotPos, spotDir in coreAttackers:
        if not ct.is_in_vision(spotPos):
            continue
        if ct.get_tile_building_id(spotPos) is not None:
            continue
        if ct.get_tile_env(spotPos) == Environment.WALL:
            continue
        seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)
        if seatCov > 1:
            continue
        score = (seatCov,
                 myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))
        if bestScore is None or score < bestScore:
            bestScore, bestAttacker = score, (spotPos, spotDir)
    return bestAttacker

def find_sentinel_spot(ct: Controller, player):
    enemyCoverage = enemy_turret_coverage(ct, player)
    coreAttackers = get_attackable_tiles(ct, player, lines=sentinelLines)
    bestAttacker, bestScore = None, None
    myLoc = ct.get_position()
    enemyCore = player.mapPf.enemyCorePos
    for spotPos, spotDir in coreAttackers:
        if not ct.is_in_vision(spotPos):
            continue
        if ct.get_tile_building_id(spotPos) is not None:
            continue
        if ct.get_tile_env(spotPos) == Environment.WALL:
            continue
        seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)
        if seatCov > 0:
            continue
        score = (-spotPos.distance_squared(enemyCore), -myLoc.distance_squared(spotPos))
        if bestScore is None or score < bestScore:
            bestScore, bestAttacker = score, (spotPos, spotDir)
    return bestAttacker

def covered_tiles_by_turrets(ct: Controller, myTeam) -> set:
    covered = set()
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) != myTeam:
            continue
        bType = ct.get_entity_type(b)
        if bType in [EntityType.GUNNER, EntityType.SENTINEL]:
            bPos = ct.get_position(b)
            bDir = ct.get_direction(b)
            for t in ct.get_attackable_tiles_from(bPos, bDir, bType):
                if ct.can_fire_from(bPos, bDir, bType, t):
                    covered.add((t.x, t.y))
    return covered

def siege_sentinel_task(ct: Controller, player, myLoc) -> bool:
    if ct.get_global_resources() < ct.get_sentinel_cost() + sentinelAttackThreshold:
        return False
    sentinelStuff = find_sentinel_spot(ct, player)
    if sentinelStuff is None:
        return False
    sentinelSpot, sentinelDir = sentinelStuff
    player.draw_state(ct, C_TURRET_SPOT, sentinelSpot)
    if ct.can_build_sentinel(sentinelSpot, sentinelDir):
        ct.build_sentinel(sentinelSpot, sentinelDir)
    myDist = myLoc.distance_squared(sentinelSpot)
    if myDist < 1:
        player.mapPf.moveTo(ct, player.mapPf.teamCore)
    elif myDist > 1:
        player.mapPf.moveTo(ct, sentinelSpot)
    return True

def attack_harvester_with_gunner(ct: Controller, player) -> bool:
    myLoc = ct.get_position()
    myTeam = ct.get_team()
    covered = covered_tiles_by_turrets(ct, myTeam)
    harvester, harvesterDist = None, None
    for b in ct.get_nearby_buildings():
        if ct.get_entity_type(b) != EntityType.HARVESTER or ct.get_team(b) == myTeam:
            continue
        bPos = ct.get_position(b)
        if bPos in covered:
            continue
        d = myLoc.distance_squared(bPos)
        if harvesterDist is None or d < harvesterDist:
            harvesterDist, harvester = d, bPos
    if harvester is None:
        return False
    enemyCoverage = enemy_turret_coverage(ct, player)
    enemyCore = player.mapPf.enemyCorePos
    best, bestScore = None, None
    for spotPos, spotDir in player.mapPf.gunnerSpots(harvester, player.mapW, player.mapH, True):
        if not ct.is_in_vision(spotPos):
            continue
        if ct.get_tile_building_id(spotPos) is not None:
            continue
        if ct.get_tile_env(spotPos) == Environment.WALL:
            continue
        # Don't burn an ore tile that sits on OUR half. dist_to_core() is a
        # CORE-ONLY helper - it builds its 2x2 footprint from ct.get_position(),
        # so called from a builder it measures the builder against its own square
        # (returns 0 for the first corner, i.e. garbage). Compare against the
        # actual team core instead.
        teamCore = player.mapPf.teamCore
        if (ct.get_tile_env(spotPos) == Environment.ORE_TITANIUM
                and teamCore is not None
                and spotPos.distance_squared(teamCore) <= spotPos.distance_squared(enemyCore)):
            continue
        seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)
        if seatCov > 0.5:
            continue
        score = (seatCov,
                 -spotPos.distance_squared(enemyCore), myLoc.distance_squared(spotPos))
        if bestScore is None or score < bestScore:
            bestScore, best = score, (spotPos, spotDir)
    if best is None:
        return False
    spotPos, spotDir = best
    player.draw_state(ct, C_TURRET_SPOT, spotPos)
    if ct.can_build_gunner(spotPos, spotDir):
        ct.build_gunner(spotPos, spotDir)
    myDist = myLoc.distance_squared(spotPos)
    if myDist < 1:
        player.mapPf.moveTo(ct, player.mapPf.teamCore)
    elif myDist > 1:
        player.mapPf.moveTo(ct, spotPos)
    return True

def heal_team_turrets(ct: Controller, player) -> bool:
    myLoc = ct.get_position()
    myTeam = ct.get_team()
    best, bestKey = None, None
    enemyCoverage = enemy_turret_coverage(ct, player)
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) != myTeam:
            continue
        if ct.get_entity_type(b) not in (EntityType.GUNNER, EntityType.SENTINEL):
            continue
        if ct.get_hp(b) >= ct.get_max_hp(b):
            continue
        bPos = ct.get_position(b)
        seatCov = enemyCoverage.get((bPos.x, bPos.y), 0)
        missing = ct.get_max_hp(b) - ct.get_hp(b)
        if seatCov > 0.5:
            surviveTurns = ct.get_hp(b) // 8 # slight round down for average of sentinel and gunner
            manDist = abs(myLoc.x - bPos.x) + abs(myLoc.y - bPos.y) - 1 # need to be 1 away to heal
            if manDist > surviveTurns:
                continue
        key = (-missing, myLoc.distance_squared(bPos))
        if bestKey is None or key < bestKey:
            bestKey, best = key, bPos
    if best is None:
        return False
    player.draw_state(ct, C_HEAL_GUNNER, best)
    if myLoc.distance_squared(best) == 1 and ct.can_heal(best):
        ct.heal(best)
        return True
    player.mapPf.moveTo(ct, best)
    return True

CAP_ORE = 1            # attackers barrier-cap enemy-side ore
CAP_ORE_MARGIN = 1.2   # enemyDist * margin < teamDist => it is theirs
CAP_ORE_RESERVE = 15   # Ti left untouched after paying (barriers are base cost 3)
CAP_ORE_REACH = 20     # r^2 - only detour to ore this close (builder vision is 20)


def cap_enemy_ore(ct: Controller, player, myLoc) -> bool:
    """Barrier ENEMY-SIDE titanium ore so they cannot harvest it.

    A barrier is the cheapest building in the game (base cost 3) and an ore tile
    under one cannot take a harvester. Attackers already walk through the enemy
    half, so this is denial on the way to the core rather than a detour.

    Side test mirrors eco.ore_rank's rank-1 branch: enemyDist * 1.2 < teamDist.
    """
    if not CAP_ORE:
        return False
    teamCore = player.mapPf.teamCore
    enemyCore = player.mapPf.enemyCorePos
    if teamCore is None or enemyCore is None:
        return False
    if ct.get_global_resources() < ct.get_barrier_cost() + CAP_ORE_RESERVE:
        return False
    # Scan everything in vision, not just the 4 orthogonal neighbours. Capping
    # only what we happen to walk beside fired 0-9 times a game; attackers take a
    # direct line to the enemy core and rarely brush an ore tile.
    best = None
    bestD = None
    for tile in ct.get_nearby_tiles():
        try:
            if ct.get_tile_env(tile) != Environment.ORE_TITANIUM:
                continue
        except Exception:
            continue
        if ct.get_tile_building_id(tile) is not None:
            continue
        teamDist = teamCore.distance_squared(tile)
        enemyDist = enemyCore.distance_squared(tile)
        if not (enemyDist * CAP_ORE_MARGIN < teamDist):
            continue          # not theirs - leave it, ours to harvest later
        d = myLoc.distance_squared(tile)
        if d > CAP_ORE_REACH:
            continue
        if bestD is None or d < bestD:
            bestD, best = d, tile
    if best is None:
        return False
    if bestD == 1 and ct.can_build_barrier(best):
        ct.build_barrier(best)
        player.draw_state(ct, C_TURRET_SPOT, best)
        return True
    if bestD == 0:
        return False          # standing ON it - can_build_barrier needs adjacency
    # short detour: walk to it. Bounded by CAP_ORE_REACH so this never becomes
    # a cross-map errand instead of attacking.
    player.draw_state(ct, C_TURRET_SPOT, best)
    player.mapPf.moveTo(ct, best)
    return True


def run(ct: Controller, player):
    myLoc = ct.get_position()

    if siege_sentinel_task(ct, player, myLoc):
        return

    if ct.get_global_resources() >= 30 and attack_harvester_with_gunner(ct, player):
        return


    isGunnerAttackingCore = False
    for tile, tileDir in get_attackable_tiles(ct, player):
        if not ct.is_in_vision(tile):
            continue
        tId = ct.get_tile_building_id(tile)
        if tId is not None and ct.get_team(tId) == ct.get_team() \
                and ct.get_entity_type(tId) == EntityType.GUNNER:
            isGunnerAttackingCore = True
            break

    if ct.get_global_resources() >= ct.get_gunner_cost() * coreAttackThreshold or (isGunnerAttackingCore and ct.get_global_resources() > ct.get_gunner_cost() * alreadyGunnerThreshold):
        gunnerStuff = find_gunner_spot(ct, player)
        if gunnerStuff:
            gunnerSpot, gunnerDir = gunnerStuff
            player.draw_state(ct, C_TURRET_SPOT, gunnerSpot)
            if ct.can_build_gunner(gunnerSpot, gunnerDir):
                ct.build_gunner(gunnerSpot, gunnerDir)
            myDist = myLoc.distance_squared(gunnerSpot)
            if myDist < 1:
                player.mapPf.moveTo(ct, player.mapPf.teamCore)
            elif myDist > 1:
                player.mapPf.moveTo(ct, gunnerSpot)
            else:
                return
            
    # DENIAL, moved LAST: only fills attacker turns that would otherwise
    # do nothing, so it can never preempt the core siege.
    if cap_enemy_ore(ct, player, myLoc):
        return

    if heal_team_turrets(ct, player):
        return
    
    # removed entomb because it wasnt that good

    player.mapPf.moveTo(ct, player.mapPf.enemyCorePos)
    player.draw_state(ct, C_MARCH_ATTACK, player.mapPf.enemyCorePos)


def gunner_attacks_core(ct: Controller, player, gunnerTile: Position, gunnerId: int) -> bool:
    teamCore = player.mapPf.teamCore
    if teamCore is None:
        return False
    coreTiles = [teamCore, teamCore.add(Direction.EAST), teamCore.add(Direction.SOUTH),
                 teamCore.add(Direction.SOUTH).add(Direction.EAST)]
    for attackTile in ct.get_attackable_tiles_from(gunnerTile, ct.get_direction(gunnerId), EntityType.GUNNER):
        if attackTile in coreTiles:
            return True
    return False


def core_threat_spots(ct: Controller, player):
    compact = ct.read_store(7)
    teamCore = Position((compact >> 5) & 0x1F, compact & 0x1F)
    corners = [teamCore, teamCore.add(Direction.EAST), teamCore.add(Direction.SOUTH),
               teamCore.add(Direction.SOUTH).add(Direction.EAST)]
    spots = set()
    for corner in corners:
        for spotPos, spotDir in player.mapPf.gunnerSpots(corner, player.mapW, player.mapH, blocked=False):
            spots.add((spotPos.x, spotPos.y, spotDir))
    return spots


def run_gunner(ct: Controller, player):
    curTarget = ct.get_gunner_target()
    myDir = ct.get_direction()
    myPos = ct.get_position()
    myTeam = ct.get_team()
    if curTarget is not None:
        targetId = ct.get_tile_building_id(curTarget)
        bbId = ct.get_tile_builder_bot_id(curTarget)
        if bbId is not None and ct.get_team(bbId) == myTeam:
            return
        enemyBuilding = targetId is not None and ct.get_team(targetId) != myTeam
        enemyBuilder = bbId is not None and ct.get_team(bbId) != myTeam
        if enemyBuilding or enemyBuilder:
            if ct.can_fire(curTarget):
                ct.fire(curTarget)
                return
    if curTarget is not None:
        targetId = ct.get_tile_building_id(curTarget)
        if targetId is not None and ct.get_team(targetId) == myTeam and ct.get_entity_type(targetId) == EntityType.CONVEYOR:
            sawTeamConv = False
            for tile in ct.get_attackable_tiles_from(myPos, myDir, EntityType.GUNNER):
                tileId = ct.get_tile_building_id(tile)
                if tileId is None:
                    continue
                if ct.get_team(tileId) == myTeam and ct.get_entity_type(tileId) == EntityType.CONVEYOR:
                    sawTeamConv = True
                    continue
                if sawTeamConv and ct.get_team(tileId) != myTeam and ct.get_entity_type(tileId) == EntityType.GUNNER:
                    if gunner_attacks_core(ct, player, tile, tileId):
                        if ct.can_fire(curTarget):
                            ct.fire(curTarget)
                        return
                break
    threatSpots = core_threat_spots(ct, player)
    teamCore = player.mapPf.teamCore
    directionScores = []
    bestDir = myDir
    bestIsCoreDefense = False
    for directionIndex, d in enumerate(DIRECTIONS):
        coreHits = coreThreatHits = gunnerHits = builderThreatHits = otherHits = 0
        for tile in ct.get_attackable_tiles_from(myPos, d, EntityType.GUNNER):
            if not ct.can_fire_from(myPos, d, EntityType.GUNNER, tile):
                continue
            tileId = ct.get_tile_building_id(tile)
            if tileId is not None and ct.get_team(tileId) != myTeam:
                tType = ct.get_entity_type(tileId)
                if tType == EntityType.CORE:
                    coreHits += 1
                elif tType in (EntityType.GUNNER, EntityType.SENTINEL):
                    gunnerHits += 1
                    if tType == EntityType.GUNNER and (tile.x, tile.y, ct.get_direction(tileId)) in threatSpots:
                        coreThreatHits += 1
                else:
                    otherHits += 1
            elif tileId is None:
                # WAVE PLANTERS: an enemy builder in our home zone is walking
                # in to plant core-facing sentinels (Bisons: replant at t90
                # after we cleared the first four). Ranks below live turrets
                # (the active bleeders) but above eco targets.
                bbId = ct.get_tile_builder_bot_id(tile)
                if (bbId is not None and ct.get_team(bbId) != myTeam
                        and teamCore is not None
                        and tile.distance_squared(teamCore) <= 50):
                    builderThreatHits += 1
        score = (coreHits, coreThreatHits, gunnerHits, builderThreatHits, otherHits)
        directionScores.append((score, 1 if d == myDir else 0, -directionIndex, d, coreThreatHits > 0))
    if directionScores:
        bestEntry = max(directionScores)
        bestScore, _, _, bestDir, bestIsCoreDefense = bestEntry
    if bestDir != myDir:
        _, _, gunnerHits, builderThreatHits, _ = bestScore
        if bestIsCoreDefense:
            floor = 35
        elif gunnerHits > 0 or builderThreatHits > 0:
            floor = 50
        else:
            floor = 85
        if ct.get_global_resources() > floor and ct.can_rotate(bestDir):
            ct.rotate(bestDir)


def run_sentinel(ct: Controller, player):
    myTeam = ct.get_team()
    best = None
    bestScore = 0
    for tile in ct.get_attackable_tiles():
        if not ct.is_in_vision(tile):
            continue
        bId = ct.get_tile_building_id(tile)
        bbId = ct.get_tile_builder_bot_id(tile)
        if bbId is not None and ct.get_team(bbId) == myTeam:
            continue
        if bId is not None and ct.get_team(bId) == myTeam:
            continue
        if bId is None and bbId is None:
            continue
        tileScore = 2
        bType = EntityType.BUILDER_BOT
        if bId is not None:
            bType = ct.get_entity_type(bId)
        if bType in [EntityType.BARRIER, EntityType.CONVEYOR]:
            tileScore = 0
        if bType in [EntityType.CORE]:
            tileScore = 1
        if bType in [EntityType.GUNNER, EntityType.SENTINEL]:
            tileScore = 3

        if tileScore > bestScore:
            best = tile
            bestScore = tileScore

    if best is not None and ct.can_fire(best):
        ct.fire(best)
