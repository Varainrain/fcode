"""probe_store - how wide is a store slot really?

v58's shareTiles packs 16 tiles x 12 bits = 192 bits and splits it into what the
comment calls "6 32 bit integers". If a slot is 10 bits (0-1023) as the FCL spec
summary says, every one of those writes truncates and the shared map is corrupt.
Write known values, read them back, report what survives.
"""
from fcode import Controller, EntityType

LOG = "/tmp/store_probe.txt"
TESTS = [1, 1023, 1024, 4095, 65535, 2 ** 31 - 1]


class Player:
    def __init__(self):
        self.done = False
        self.read = False

    def run(self, ct: Controller) -> None:
        if ct.get_entity_type() != EntityType.CORE:
            return
        if self.done and not self.read:
            self.read = True
            back = []
            for i, v in enumerate(TESTS):
                slot = 9 + (i % 7)
                try:
                    back.append("slot %d: wrote %d read %d" % (slot, v, ct.read_store(slot)))
                except Exception as exc:
                    back.append("slot %d read RAISED %s" % (slot, type(exc).__name__))
            try:
                open(LOG, "a").write(" | ".join(back) + ";")
            except Exception:
                pass
            return
        if self.done:
            return
        self.done = True
        out = []
        for i, v in enumerate(TESTS):
            slot = 9 + (i % 7)          # free slots only
            try:
                ct.write_store(slot, v)
                out.append("wrote %d -> slot %d" % (v, slot))
            except Exception as exc:
                out.append("wrote %d -> RAISED %s: %s" % (v, type(exc).__name__, exc))
        try:
            open(LOG, "a").write(" | ".join(out) + ";")
        except Exception:
            pass


