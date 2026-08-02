"""Instrumentation-only bot: records the exact order run() is called.

Answers two things I asserted without checking:
  1. Is the bot passed as BOT_A actually Team A?
  2. Within a round, do ALL of Team A's units act before ANY of Team B's,
     i.e. is there a genuine team-level turn order?

Both sides run this same code, so the shared append-only log interleaves both
teams and shows the true global execution order. Does nothing else -- the log
is the whole point.
"""
import os

LOG = os.environ.get("PROBE_LOG", "/tmp/probe_order.log")


class Player:
    def __init__(self):
        self._f = None

    def run(self, ct) -> None:
        try:
            r = ct.get_current_round()
            if r > 6:          # a few rounds is plenty; keep the log small
                return
            team = ct.get_team()
            etype = ct.get_entity_type()
            with open(LOG, "a") as f:
                f.write(f"round={r} team={team} type={etype} id={ct.get_id()}\n")
            # Spawn a few builders so there is a real multi-unit ordering to
            # observe: team-blocked (all A then all B) vs interleaved by id.
            if str(etype).endswith("CORE") and ct.get_action_cooldown() == 0:
                pos = ct.get_position()
                for d in ct.get_nearby_tiles(dist_sq=2):
                    if ct.can_spawn(d):
                        ct.spawn_builder(d)
                        break
        except Exception:
            pass
