from fcode import *

# replace the workforce only after the whole team is gutted.
REPLACE_UNIT_THRESHOLD = 6
# dont let the replacement path fire during the normal opening
REPLACE_MIN_ROUND = 30
# keep this titanium after paying for a replacement builder.
REPLACE_RESERVE = 60


def spawnBots(numSpawned: int, ct: Controller) -> bool:
    currentTitanium = ct.get_global_resources()
    # 350 hoard keeps the opening lean (low scale, defense fund intact).
    # the mid-war clause fixes the other failure: 4 builders starving at
    # r130+ because war spending never lets ti back over 350
    if numSpawned < 5 and (currentTitanium >= 350
            or (ct.get_current_round() >= 60
                and currentTitanium >= ct.get_builder_bot_cost() + 60)):
        return True
    if numSpawned > 4 and currentTitanium >= 400 * ct.get_scale_percent() / 100:
        return True
    if (ct.get_current_round() >= REPLACE_MIN_ROUND
            and ct.get_unit_count() <= REPLACE_UNIT_THRESHOLD
            and currentTitanium >= ct.get_builder_bot_cost() + REPLACE_RESERVE):
        return True
    return False


def findThreats(ct: Controller) -> list:
    threats = []
    curRound = ct.get_current_round()
    for i in ct.get_nearby_buildings(8):
        if (ct.get_entity_type(i) == EntityType.LAUNCHER and
                ct.get_team(i) != ct.get_team()):
            threats.append(ct.get_position(i))
    return threats


def findTeamCore(ct: Controller):
    for i in ct.get_nearby_buildings():
        if ct.get_entity_type(i) == EntityType.CORE and ct.get_team(i) == ct.get_team():
            return ct.get_position(i)


def findEnemyCore(ct: Controller):
    for i in ct.get_nearby_buildings():
        if ct.get_entity_type(i) == EntityType.CORE and ct.get_team(i) != ct.get_team():
            return ct.get_position(i)
