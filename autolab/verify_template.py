"""Prove bots/_template with DEFAULT knobs is the chassis, byte for byte.

If this does not hold, every search result is measured against a bot that is not
the bot we ship, and the whole pipeline is worthless. So it is checked
structurally rather than by playing games: substitute each knob's default back
into the template, drop the injected KNOBS line and any block that is provably
dead at the defaults (`if 0 and ...`, `if 0:`), and diff against the chassis.

    python -m autolab.verify_template [chassis=OogwayAttack]
"""
import difflib
import re
import sys
from pathlib import Path

from .build_template import KNOB_SPEC, TEMPLATE

ROOT = Path(__file__).resolve().parent.parent


def fold_defaults(text):
    """Replace KNOBS["X"] with X's default, then remove provably dead code."""
    for k, spec in KNOB_SPEC.items():
        text = text.replace(f'KNOBS["{k}"]', str(spec[0]))
    lines = text.split("\n")
    out, skip_indent = [], None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("KNOBS = {") and stripped.endswith("# autolab"):
            continue
        if skip_indent is not None:
            indent = len(line) - len(line.lstrip())
            if stripped and indent > skip_indent:
                continue                      # body of a dead `if 0:`
            skip_indent = None
        if stripped.startswith("if 0 and ") and stripped.endswith(":"):
            skip_indent = len(line) - len(line.lstrip())
            continue
        if stripped == "if 0:":
            skip_indent = len(line) - len(line.lstrip())
            continue
        out.append(line)
    return "\n".join(out)


def main(chassis="OogwayAttack"):
    bad = []
    for fname in ("main.py", "mapPathfinding.py"):
        src = (ROOT / "bots" / chassis / fname).read_text(encoding="utf-8")
        tpl = (TEMPLATE / fname).read_text(encoding="utf-8")
        if fold_defaults(tpl) != src:
            bad.append((fname, src, fold_defaults(tpl)))
    if not bad:
        print(f"OK - bots/_template at default knobs is byte-identical to "
              f"bots/{chassis} in main.py AND mapPathfinding.py "
              f"({len(KNOB_SPEC)} knobs fold away cleanly)")
        return 0
    fname, src, folded = bad[0]
    diff = list(difflib.unified_diff(
        src.splitlines(), folded.splitlines(),
        fromfile=f"bots/{chassis}/{fname}", tofile="template@defaults", lineterm=""))
    print("MISMATCH - the template is NOT the chassis at default knobs:\n")
    print("\n".join(diff[:60]))
    print(f"\n({len(diff)} diff lines) - fix autolab/build_template.py")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "OogwayAttack"))
