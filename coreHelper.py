from fcode import *


def spawnBots(numSpawned: int, ct: Controller) -> bool:
    currentTitanium = ct.get_global_resources()
    if numSpawned < 6 and currentTitanium >= 320:
        return True
    if numSpawned > 5 and currentTitanium >= 400 * ct.get_scale_percent() / 100:
        return True
    return False


def findThreats(ct: Controller) -> list:
    threats = []
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
