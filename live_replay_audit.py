"""Batch-audit live Florent replay files for general weakness categories.

The tool queries match metadata, then decodes local replay files to compare
core-race timing, turret pressure, healing, builds, and attrition across wins
and losses.

Example:
  python live_replay_audit.py REPLAY_DIR \
      --team-id 56ced8d6-c986-4ebd-9b0b-ff53de527a85 \
      --fcode /mnt/c/Users/subodh/Downloads/.venv/bin/fcode

Run it inside WSL when --fcode is a WSL path.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess

from replay_stats import PAYLOAD_TYPE, signed, walk


MATCH_ID_RE = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"_game_(\d+)\.replay26$",
    re.IGNORECASE,
)


def first_varint(message, field, default=None):
    return message.get((field, "v"), [default])[0]


def first_message(message, field):
    values = message.get((field, "m"), [])
    return walk(values[0]) if values else {}


def position(message):
    return (
        first_varint(message, 1, 0),
        first_varint(message, 2, 0),
    )


def core_tiles(top_left):
    x, y = top_left
    return {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}


def distance_sq_to_tiles(pos, tiles):
    return min((pos[0] - x) ** 2 + (pos[1] - y) ** 2 for x, y in tiles)


def fetch_match(fcode, match_id):
    output = subprocess.check_output(
        [fcode, "match", "info", match_id, "--json"],
        text=True,
        encoding="utf-8",
    )
    return json.loads(output)


def spawned_entity(create_payload):
    outer = walk(create_payload) or {}
    entity = (
        walk(outer[(1, "m")][0])
        if (1, "m") in outer
        else outer
    ) or {}
    entity_id = first_varint(entity, 1)
    team = first_varint(entity, 2, 0)
    pos = position(first_message(entity, 3))
    entity_type = "?"
    for field, wire_type in entity:
        if wire_type == "m" and field >= 10:
            entity_type = PAYLOAD_TYPE.get(field, f"type{field}")
            break
    return entity_id, team, pos, entity_type


def audit_replay(path, metadata, team_id):
    match = metadata["match"]
    game_number = int(MATCH_ID_RE.match(path.name).group(2))
    game = next(g for g in metadata["games"] if g["gameNumber"] == game_number)
    our_team = 0 if match["teamAId"] == team_id else 1
    enemy_team = 1 - our_team
    opponent = (
        match["teamBName"] if our_team == 0 else match["teamAName"]
    )

    top = walk(path.read_bytes())
    header = first_message(top, 1)
    turns = top.get((3, "m"), [])

    entities = {}
    position_occupants = defaultdict(list)
    cores = {}
    hp = {}
    for core_blob in header.get((4, "m"), []):
        core = walk(core_blob) or {}
        entity_id = first_varint(core, 1)
        team = first_varint(core, 2, 0)
        pos = position(first_message(core, 3))
        max_hp = first_varint(core, 4, 500)
        entities[entity_id] = {
            "team": team,
            "type": "core",
            "pos": pos,
            "alive": True,
        }
        cores[team] = entity_id
        hp[entity_id] = max_hp

    our_core_tiles = core_tiles(entities[cores[our_team]]["pos"])
    enemy_core_tiles = core_tiles(entities[cores[enemy_team]]["pos"])

    builds = defaultdict(Counter)
    deaths = defaultdict(Counter)
    first_build = defaultdict(dict)
    core_damage = defaultdict(int)
    core_healing = defaultdict(int)
    first_core_damage = {}
    first_core_shot = {}
    core_shots = defaultdict(int)
    core_shots_by_round = defaultdict(Counter)
    core_attack_sources = defaultdict(Counter)
    near_home_turret_builds = defaultdict(int)
    near_enemy_turret_builds = defaultdict(int)
    builder_deaths_before_core_damage = defaultdict(int)

    def current_entity_at(pos):
        for entity_id in reversed(position_occupants.get(pos, [])):
            entity = entities.get(entity_id)
            if entity and entity["alive"]:
                return entity
        return None

    for round_index, turn_blob in enumerate(turns, start=1):
        turn = walk(turn_blob) or {}
        for event_blob in turn.get((1, "m"), []):
            event = walk(event_blob) or {}
            if (1, "m") in event:
                entity_id, team, pos, entity_type = spawned_entity(
                    event[(1, "m")][0]
                )
                entities[entity_id] = {
                    "team": team,
                    "type": entity_type,
                    "pos": pos,
                    "alive": True,
                }
                position_occupants[pos].append(entity_id)
                builds[team][entity_type] += 1
                first_build[team].setdefault(entity_type, round_index)
                if entity_type in ("gunner", "sentinel"):
                    if distance_sq_to_tiles(pos, core_tiles(
                            entities[cores[team]]["pos"])) <= 36:
                        near_home_turret_builds[team] += 1
                    if distance_sq_to_tiles(pos, core_tiles(
                            entities[cores[1 - team]]["pos"])) <= 36:
                        near_enemy_turret_builds[team] += 1
            elif (2, "m") in event and (1, "v") in event:
                entity_id = first_varint(event, 1)
                entity = entities.get(entity_id)
                move = walk(event[(2, "m")][0]) or {}
                if entity:
                    entity["pos"] = position(move)
            elif (5, "m") in event:
                damage = walk(event[(5, "m")][0]) or {}
                entity_id = first_varint(damage, 1)
                delta = signed(first_varint(damage, 2, 0))
                entity = entities.get(entity_id)
                if entity and entity["type"] == "core":
                    team = entity["team"]
                    hp[entity_id] = hp.get(entity_id, 500) + delta
                    if delta < 0:
                        core_damage[team] += -delta
                        first_core_damage.setdefault(team, round_index)
                    elif delta > 0:
                        core_healing[team] += delta
            elif (12, "m") in event:
                fire = walk(event[(12, "m")][0]) or {}
                source = position(first_message(fire, 1))
                target = position(first_message(fire, 2))
                shooter = current_entity_at(source)
                if target in our_core_tiles:
                    victim_team = our_team
                elif target in enemy_core_tiles:
                    victim_team = enemy_team
                else:
                    victim_team = None
                if victim_team is not None:
                    core_shots[victim_team] += 1
                    core_shots_by_round[victim_team][round_index] += 1
                    first_core_shot.setdefault(victim_team, round_index)
                    if shooter:
                        source_key = (
                            shooter["team"],
                            shooter["type"],
                            source,
                        )
                    else:
                        source_key = ("?", "?", source)
                    core_attack_sources[victim_team][source_key] += 1
            elif (3, "m") in event or (13, "m") in event:
                field = 3 if (3, "m") in event else 13
                death = walk(event[(field, "m")][0]) or {}
                entity_id = first_varint(death, 1)
                entity = entities.get(entity_id)
                if entity and entity["alive"]:
                    entity["alive"] = False
                    team = entity["team"]
                    entity_type = entity["type"]
                    deaths[team][entity_type] += 1
                    if (
                        entity_type == "builder"
                        and team not in first_core_damage
                    ):
                        builder_deaths_before_core_damage[team] += 1

    our_result = "W" if game["winnerId"] == team_id else "L"
    our_attackers = {
        key for key in core_attack_sources[enemy_team]
        if key[0] == our_team
    }
    home_attackers = {
        key for key in core_attack_sources[our_team]
        if key[0] == enemy_team
    }
    return {
        "match": match["id"][:8],
        "opponent": opponent,
        "game": game_number,
        "map": game["mapName"],
        "result": our_result,
        "condition": game["winCondition"],
        "turns": game["turnsPlayed"],
        "side": "A" if our_team == 0 else "B",
        "our_builders": builds[our_team]["builder"],
        "enemy_builders": builds[enemy_team]["builder"],
        "our_harvesters": builds[our_team]["harvester"],
        "enemy_harvesters": builds[enemy_team]["harvester"],
        "our_gunners": builds[our_team]["gunner"],
        "enemy_gunners": builds[enemy_team]["gunner"],
        "our_sentinels": builds[our_team]["sentinel"],
        "enemy_sentinels": builds[enemy_team]["sentinel"],
        "our_builder_deaths": deaths[our_team]["builder"],
        "enemy_builder_deaths": deaths[enemy_team]["builder"],
        "our_early_builder_deaths": builder_deaths_before_core_damage[our_team],
        "enemy_early_builder_deaths": builder_deaths_before_core_damage[enemy_team],
        "damage_to_our_core": core_damage[our_team],
        "damage_to_enemy_core": core_damage[enemy_team],
        "our_core_healing": core_healing[our_team],
        "enemy_core_healing": core_healing[enemy_team],
        "enemy_heal_fraction": round(
            core_healing[enemy_team] / core_damage[enemy_team], 3
        ) if core_damage[enemy_team] else 0.0,
        "first_home_shot": first_core_shot.get(our_team),
        "first_enemy_core_shot": first_core_shot.get(enemy_team),
        "home_attacker_count": len(home_attackers),
        "our_core_attacker_count": len(our_attackers),
        "max_home_shots_round": max(
            core_shots_by_round[our_team].values(), default=0
        ),
        "max_enemy_core_shots_round": max(
            core_shots_by_round[enemy_team].values(), default=0
        ),
        "our_near_home_turrets": near_home_turret_builds[our_team],
        "enemy_near_home_turrets": near_home_turret_builds[enemy_team],
        "our_forward_turrets": near_enemy_turret_builds[our_team],
        "enemy_forward_turrets": near_enemy_turret_builds[enemy_team],
        "first_our_gunner": first_build[our_team].get("gunner"),
        "first_enemy_gunner": first_build[enemy_team].get("gunner"),
    }


def print_table(rows):
    columns = [
        "opponent", "map", "result", "turns", "side",
        "damage_to_our_core", "damage_to_enemy_core",
        "first_home_shot", "first_enemy_core_shot",
        "home_attacker_count", "our_core_attacker_count",
        "max_home_shots_round", "enemy_heal_fraction",
        "our_harvesters", "enemy_harvesters",
        "our_gunners", "enemy_gunners",
    ]
    widths = {
        column: max(
            len(column),
            *(len(str(row.get(column, ""))) for row in rows),
        )
        for column in columns
    }
    print(" ".join(column.ljust(widths[column]) for column in columns))
    for row in rows:
        print(" ".join(
            str(row.get(column, "") if row.get(column) is not None else "-")
            .ljust(widths[column])
            for column in columns
        ))


def aggregate(rows):
    print("\nLOSS CATEGORIES")
    categories = Counter()
    for row in rows:
        if row["result"] != "L":
            continue
        if row["turns"] >= 1000:
            categories["round-1000 economy"] += 1
        if row["condition"] == "core_destroyed":
            categories["core destroyed"] += 1
        if row["home_attacker_count"] >= 2:
            categories["multi-turret home pressure"] += 1
        if (
            row["damage_to_enemy_core"] >= 150
            and row["enemy_heal_fraction"] >= 0.75
        ):
            categories["siege damage mostly/fully healed"] += 1
        if row["damage_to_enemy_core"] >= 400:
            categories["lost after major enemy-core damage"] += 1
    for category, count in categories.most_common():
        print(f"  {category}: {count}")

    print("\nBY OPPONENT")
    for opponent in sorted({row["opponent"] for row in rows}):
        group = [row for row in rows if row["opponent"] == opponent]
        wins = sum(row["result"] == "W" for row in group)
        core_losses = sum(
            row["result"] == "L" and row["condition"] == "core_destroyed"
            for row in group
        )
        print(
            f"  {opponent}: {wins}/{len(group)} wins, "
            f"{core_losses} core losses"
        )

    print("\nLOSS MAPS")
    loss_maps = Counter(
        row["map"] for row in rows if row["result"] == "L"
    )
    for map_name, count in loss_maps.most_common():
        print(f"  {map_name}: {count}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("replay_dir", type=Path)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--fcode", default="fcode")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    replay_files = sorted(args.replay_dir.glob("*.replay26"))
    grouped = defaultdict(list)
    for path in replay_files:
        match = MATCH_ID_RE.match(path.name)
        if match:
            grouped[match.group(1)].append(path)

    rows = []
    for match_id, paths in grouped.items():
        metadata = fetch_match(args.fcode, match_id)
        for path in paths:
            rows.append(audit_replay(path, metadata, args.team_id))
    rows.sort(key=lambda row: (
        row["opponent"], row["match"], row["game"]
    ))

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print_table(rows)
        aggregate(rows)


if __name__ == "__main__":
    main()
