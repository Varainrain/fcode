"""fp1 gunner behaviour, mixed into Player as GunnerBot.

Spec (botStrategy.md §5): "attack current enemy in your firing range if it
exists. otherwise rotate to attack other harvesters, cores, gunners, sentinels,
loaded conveyors. If you have none of those things to rotate to, and there is no
enemy in your current firing range (ct.get_gunner_target()), then you self
destruct."

So the turn is exactly three ordered decisions: FIRE, else ROTATE, else DESTRUCT.
Rotation preference is the §5 table: harvester 5, core 4, gunner/sentinel 3,
loaded conveyor or splitter 2, builder bot 1, barrier or empty conveyor 0 - and a
0 is never a reason to pay for a rotation.

No exception handlers anywhere (an uncaught exception permanently destroys the
unit, so every raising call is guarded by a vision/type test instead):
  - ct.can_fire(None) raises TypeError, hence the `cur is not None` test.
  - get_tile_building_id / get_tile_builder_bot_id raise outside vision, hence
    the is_in_vision test before either.
  - get_stored_resource raises on anything without storage, hence it is only
    called once the building is known to be a CONVEYOR or SPLITTER.
"""

from fcode import Controller, EntityType, Environment
from mapPathfinding import DIRECTIONS
CORE_TI = 120      # below this the enemy core is not worth the ammo


class GunnerBot:
    """Gunner behaviour. All per-unit state is `self.*`, created in one place:
    Player.__init__ in main.py (this mixin owns `rotations`)."""

    def run_gunner(self, ct: Controller) -> None:
        myPos = ct.get_position()
        myTeam = ct.get_team()

        # 1. FIRE. get_gunner_target() returns the closest TARGETABLE tile in the
        # facing line and does NOT filter by team, so it must be checked before
        # firing: measured on drumlin, 21 of 24 shots went into OUR OWN CORE.
        cur = ct.get_gunner_target()
        curOk = cur is not None and self._gun_enemy(ct, cur, myTeam)
        if curOk and ct.can_fire(cur):
            ct.fire(cur)
            return

        # 2. ROTATE, to the facing whose line holds the best-ranked enemy.
        myDir = ct.get_direction()
        bestDir, bestRank = None, 0
        for d in DIRECTIONS:
            if d == myDir:
                continue
            rank = self._gun_rank(ct, myPos, d, myTeam)
            if rank > bestRank:
                bestRank, bestDir = rank, d
        # Titanium floor before paying: a rotation costs 10 Ti AND sets the action
        # cooldown to 1 (half a gunner's base cost, and a lost shot), so it must
        # not be paid out of titanium the economy still needs. There is NO cap on
        # the number of rotations. can_rotate() also re-checks affordability.
        if bestDir is not None and ct.get_global_resources() > 35 and ct.can_rotate(bestDir):
            ct.rotate(bestDir)
            self.rotations += 1
            return

        # 3. DESTRUCT: nothing enemy in the firing line and nothing worth turning
        # to. Note a gunner that HAS a live enemy in its line but cannot fire this
        # turn (no ammo, cooldown) is not idle and is kept.
        if not curOk and bestDir is None:
            # Nothing shootable and nothing worth rotating to RIGHT NOW - but do
            # not give up if a transient blocker (a builder bot) is the only thing
            # standing between us and a real target.
            if self._gun_worth_holding(ct, myPos, myTeam):
                self.idleTurns = 0
                return
            self.idleTurns += 1
            if self.idleTurns > 3:
                ct.self_destruct()
        else:
            self.idleTurns = 0

    def _gun_good_target(self, ct: Controller, bId) -> bool:
        """The satisfactory-target set: harvester, core, turret, BUILDER BOT,
        LOADED conveyor or splitter. Excludes empty conveyors and barriers (a
        3 Ti wall is never worth 4 ammo).

        BUILDERS WERE EXCLUDED ON AN OBSOLETE FACT. The old note here read
        "they self-heal +4/turn against our 7 and simply walk away" - but
        engine 2.3.0 REMOVED self-heal: heal targets an ORTHOGONALLY ADJACENT
        tile, never the healer's own, so a lone builder cannot heal itself at
        all. It is 40hp against our 7 per shot, i.e. six shots, and it is the
        thing that plants every sentinel and barrier that kills us. This was
        already measured once (commit bc596f1: retargeting gunners onto
        builders PROMOTED 55% vs fp14 and 60% vs jav1 - "killing tenders beats
        chipping what tenders maintain") and the result never reached this
        lineage. Every autopsy this session ends the same way: they plant
        turrets next to our core and we cannot answer. The planter is the
        answer."""
        bType = ct.get_entity_type(bId)
        if bType == EntityType.CORE:
            # Keeping a gunner alive for a core we cannot afford to finish is how it
            # ends up neither firing nor self-destructing.
            return ct.get_global_resources() > CORE_TI
        if bType in (EntityType.HARVESTER,
                     EntityType.GUNNER, EntityType.SENTINEL,
                     EntityType.BUILDER_BOT):
            return True
        if bType in (EntityType.CONVEYOR, EntityType.SPLITTER):
            # get_stored_resource RAISES on anything without storage, so it is
            # reached only once the type is known.
            return ct.get_stored_resource(bId) is not None
        return False

    def _gun_worth_holding(self, ct: Controller, myPos, myTeam) -> bool:
        """Is there ANY direction whose line holds a target worth waiting for?

        Deliberately MORE PERMISSIVE than the fire test: this ray stops only at a
        wall or one of OUR OWN buildings, both permanent. A builder bot in the way
        is transient and must not cost us the gunner."""
        for d in DIRECTIONS:
            tiles = list(ct.get_attackable_tiles_from(myPos, d,
                                                     EntityType.GUNNER))
            tiles.sort(key=lambda t: myPos.distance_squared(t))
            for t in tiles:
                if not ct.is_in_vision(t):
                    continue
                if ct.get_tile_env(t) == Environment.WALL:
                    break       # permanent: nothing past it is ever reachable
                bId = ct.get_tile_building_id(t)
                if bId is None:
                    continue
                if ct.get_team(bId) == myTeam:
                    break       # our own building: also permanent
                if self._gun_good_target(ct, bId):
                    return True
        return False

    def run_sentinel(self, ct: Controller) -> None:
        """Sentinel runtime: fire the best-ranked enemy on the facing line.
        Core 9 (the whole point - 28 hits kill it and no wall blocks us),
        turrets 3, harvester 2, builder 2 (tenders ARE the heal loop),
        barrier/conveyor 0 (2 shots x 10 ammo for a 3 Ti wall - never)."""
        myTeam = ct.get_team()
        best, bestRank = None, 0
        for t in ct.get_attackable_tiles():
            if not ct.is_in_vision(t):
                continue
            bId = ct.get_tile_building_id(t)
            bbId = ct.get_tile_builder_bot_id(t)
            if bId is not None and ct.get_team(bId) == myTeam:
                continue
            if bbId is not None and ct.get_team(bbId) == myTeam:
                continue
            rank = 0
            if bbId is not None:
                rank = 2
            if bId is not None:
                bType = ct.get_entity_type(bId)
                if bType == EntityType.CORE:
                    rank = 9
                elif bType in (EntityType.GUNNER, EntityType.SENTINEL):
                    rank = 3
                elif bType == EntityType.HARVESTER:
                    rank = max(rank, 2)
            if rank > bestRank:
                bestRank, best = rank, t
        if best is not None and ct.can_fire(best):
            ct.fire(best)

    # ------------------------------------------------------------------ helpers

    def _gun_enemy(self, ct: Controller, tile, myTeam) -> bool:
        """True only if `tile` positively holds an enemy AND nothing of ours.
        Positive identification, not merely "not ours": an unknown tile must never
        be fired at. Both halves are load-bearing - MEASURED on drumlin, one shot
        went into a tile holding an enemy CONVEYOR with OUR OWN BUILDER standing on
        it (builder bots may stand on conveyors, splitters and the allied core), so
        checking only the building would have shot our own unit."""
        if not ct.is_in_vision(tile):
            return False
        bId = ct.get_tile_building_id(tile)
        if bId is not None and ct.get_team(bId) == myTeam:
            return False
        bbId = ct.get_tile_builder_bot_id(tile)
        if bbId is not None and ct.get_team(bbId) == myTeam:
            return False
        if bId is not None and ct.get_entity_type(bId) == EntityType.CORE \
                and ct.get_global_resources() <= CORE_TI:
            # A 500-hp core costs ~720 Ti of ammo to kill and out-heals one gunner.
            # Too poor to finish it means it is not a target at all.
            return bbId is not None
        return bId is not None or bbId is not None

    def _gun_rank(self, ct: Controller, myPos, d, myTeam) -> int:
        """Rank of the best thing a gunner at myPos facing d could hit.
        get_attackable_tiles_from() is the RAW geometric pattern (it ignores
        occupancy and walls), so can_fire_from() is what decides reachability -
        for a gunner that admits only the first occupied tile in the line, since
        gunners are blocked by the first non-empty tile.

        harvester 5 > core 4 > gunner/sentinel 3 > loaded conveyor/splitter 2 >
        builder bot 1 > barrier or empty conveyor 0, i.e. never worth 4 ammo
        against a 3 Ti wall. A tile is scored on the best of its building and its
        builder bot, since an enemy builder can stand on an enemy conveyor."""
        best = 0
        for t in ct.get_attackable_tiles_from(myPos, d, EntityType.GUNNER):
            if not ct.can_fire_from(myPos, d, EntityType.GUNNER, t):
                continue
            if not ct.is_in_vision(t):
                continue
            bId = ct.get_tile_building_id(t)
            if bId is not None and ct.get_team(bId) == myTeam:
                continue
            bbId = ct.get_tile_builder_bot_id(t)
            if bbId is not None and ct.get_team(bbId) == myTeam:
                continue        # our own builder is standing there - see _gun_enemy
            # SNIPER EXPERIMENT: builders are the linchpin of every bot we
            # have decoded - they heal cores and turrets, rebuild seats and
            # lay economy. The stock table calls them "not a good target"
            # because they self-heal +4 against our 7 and walk away; this
            # variant tests the opposite bet, that killing the tender beats
            # chipping what the tender maintains.
            rank = 6 if bbId is not None else 0
            if bId is not None:
                bType = ct.get_entity_type(bId)
                if bType == EntityType.HARVESTER:
                    bRank = 5
                elif bType == EntityType.CORE:
                    bRank = 4 if ct.get_global_resources() > CORE_TI else 0
                elif bType in (EntityType.GUNNER, EntityType.SENTINEL):
                    bRank = 3
                elif bType in (EntityType.CONVEYOR, EntityType.SPLITTER):
                    # get_stored_resource RAISES on anything without storage, so it
                    # is reached only once the type is known. An EMPTY conveyor is
                    # not worth turning to.
                    bRank = 2 if ct.get_stored_resource(bId) is not None else 0
                else:
                    bRank = 0       # barrier, launcher
                if bRank > rank:
                    rank = bRank
            if rank > best:
                best = rank
        return best
