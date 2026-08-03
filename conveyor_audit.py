"""Audit economic conveyor topology in a local .replay26.

Reports living conveyors, facing-proven core connections, dead ends, and
harvesters with a connected output chain at selected rounds. Direction values
1/3/5/7 are the replay protocol's N/E/S/W enum values.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from replay_stats import PAYLOAD_TYPE, pos_of, walk


DIRECTION_DELTA = {
    1: (0, -1),
    3: (1, 0),
    5: (0, 1),
    7: (-1, 0),
}


def replay_state(path: Path, snapshot_rounds):
    top = walk(path.read_bytes())
    map_message = walk(top[(1, "m")][0]) or {}
    cores = {}
    for raw_core in map_message.get((4, "m"), []):
        core = walk(raw_core) or {}
        team = core.get((2, "v"), [0])[0]
        cores[team] = pos_of(core[(3, "m")][0])

    entities = {}
    snapshots = {}
    turns = top[(3, "m")]
    wanted = set(snapshot_rounds) | {len(turns) - 1}
    for round_number, raw_turn in enumerate(turns):
        turn = walk(raw_turn) or {}
        for raw_event in turn.get((1, "m"), []):
            event = walk(raw_event) or {}
            if (1, "m") in event:
                outer = walk(event[(1, "m")][0]) or {}
                created = (
                    walk(outer[(1, "m")][0])
                    if (1, "m") in outer else outer
                ) or {}
                entity_id = created.get((1, "v"), [None])[0]
                entity_type = None
                facing = None
                for field, name in PAYLOAD_TYPE.items():
                    if (field, "m") not in created:
                        continue
                    entity_type = name
                    if name == "conveyor":
                        payload = walk(created[(field, "m")][0]) or {}
                        facing = payload.get((1, "v"), [None])[0]
                entities[entity_id] = {
                    "team": created.get((2, "v"), [0])[0],
                    "type": entity_type,
                    "position": pos_of(created[(3, "m")][0]),
                    "facing": facing,
                    "born": round_number,
                    "alive": True,
                }
            elif (3, "m") in event or (13, "m") in event:
                field = (3, "m") if (3, "m") in event else (13, "m")
                death = walk(event[field][0]) or {}
                entity_id = death.get((1, "v"), [None])[0]
                if entity_id in entities:
                    entities[entity_id]["alive"] = False
        if round_number in wanted:
            snapshots[round_number] = {
                entity_id: record.copy()
                for entity_id, record in entities.items()
            }
    return cores, len(turns), snapshots


def topology(core, entities, team):
    footprint = {
        (core[0] + dx, core[1] + dy)
        for dx in (0, 1) for dy in (0, 1)
    }
    conveyors = {
        record["position"]: record
        for record in entities.values()
        if record["alive"] and record["team"] == team
        and record["type"] == "conveyor"
    }
    harvesters = {
        record["position"]
        for record in entities.values()
        if record["alive"] and record["team"] == team
        and record["type"] == "harvester"
    }
    connected = set()
    changed = True
    while changed:
        changed = False
        for position, record in conveyors.items():
            if position in connected or record["facing"] not in DIRECTION_DELTA:
                continue
            dx, dy = DIRECTION_DELTA[record["facing"]]
            output = (position[0] + dx, position[1] + dy)
            if output in footprint or output in connected:
                connected.add(position)
                changed = True

    dead_ends = set()
    for position, record in conveyors.items():
        delta = DIRECTION_DELTA.get(record["facing"])
        if delta is None:
            dead_ends.add(position)
            continue
        output = (position[0] + delta[0], position[1] + delta[1])
        if output not in footprint and output not in conveyors:
            dead_ends.add(position)

    cycle_components = set()
    cycle_conveyors = set()
    for start in conveyors:
        path = []
        path_index = {}
        position = start
        while position in conveyors:
            if position in path_index:
                cycle = frozenset(path[path_index[position]:])
                cycle_components.add(cycle)
                cycle_conveyors.update(cycle)
                break
            path_index[position] = len(path)
            path.append(position)
            facing = conveyors[position]["facing"]
            delta = DIRECTION_DELTA.get(facing)
            if delta is None:
                break
            position = (position[0] + delta[0], position[1] + delta[1])

    served = set()
    backfeed_roots = set()
    for harvester in harvesters:
        for position, record in conveyors.items():
            if abs(position[0] - harvester[0]) + abs(position[1] - harvester[1]) != 1:
                continue
            delta = DIRECTION_DELTA.get(record["facing"])
            if delta is None:
                continue
            output = (position[0] + delta[0], position[1] + delta[1])
            if output == harvester:
                backfeed_roots.add((harvester, position))
            if output != harvester and position in connected:
                served.add(harvester)
                break
    return {
        "conveyors": len(conveyors),
        "connected": len(connected),
        "disconnected": len(conveyors) - len(connected),
        "dead_ends": len(dead_ends),
        "cycles": len(cycle_components),
        "cycle_conveyors": len(cycle_conveyors),
        "backfeed_roots": len(backfeed_roots),
        "harvesters": len(harvesters),
        "served": len(served),
        "orphan_positions": sorted(harvesters - served),
        "post40_conveyors": sum(
            record["born"] >= 40 for record in conveyors.values()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("replay", type=Path)
    parser.add_argument("--rounds", default="40,80,100,500,999")
    args = parser.parse_args()
    rounds = [int(value) for value in args.rounds.split(",") if value]
    cores, turn_count, snapshots = replay_state(args.replay, rounds)
    print(f"{args.replay} ({turn_count} rounds)")
    for round_number in sorted(snapshots):
        print(f"round {round_number}")
        for team in sorted(cores):
            print(f"  {'AB'[team]} {topology(cores[team], snapshots[round_number], team)}")


if __name__ == "__main__":
    main()
