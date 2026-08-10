"""Deterministic tests for the early-siege variant.

The whole hypothesis is one constant, so the tests exist to prove that it is
ONLY that constant — a one-line experiment that quietly changed something else
would make its gate result uninterpretable.
"""

from pathlib import Path
import difflib
import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "bots" / "generalist-v3" / "main.py"
CHILD = ROOT / "bots" / "exp_early_siege" / "main.py"


def load(bot_name, module_name):
    bot_dir = ROOT / "bots" / bot_name
    sys.path.insert(0, str(bot_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, bot_dir / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


CHILD_MOD = load("exp_early_siege", "exp_early_siege_main")
PARENT_MOD = load("generalist-v3", "generalist_v3_main")


def test_siege_starts_earlier():
    assert PARENT_MOD.SIEGE_START == 45
    assert CHILD_MOD.SIEGE_START == 25
    assert CHILD_MOD.SIEGE_START < PARENT_MOD.SIEGE_START


def test_no_other_constant_moved():
    """Titanium floors, wall duty and role slots must be untouched."""
    for name in (
        "SIEGE_TITANIUM_FLOOR", "HOME_DEFENDER_HOLD_ROUNDS",
        "SLOT_WALLER_ID", "SLOT_SIEGER_1_ID", "SLOT_SIEGER_2_ID",
        "SLOT_ENEMY_CORE", "SLOT_SIEGER_2_COUNTER_TARGET",
        "SLOT_HOME_DEFENDER_ID", "SLOT_HOME_THREAT",
    ):
        assert getattr(CHILD_MOD, name) == getattr(PARENT_MOD, name), name


def test_titanium_floor_still_gates_every_build():
    """The siege got earlier, not cheaper."""
    assert CHILD_MOD.SIEGE_TITANIUM_FLOOR == 120
    source = CHILD.read_text(encoding="utf-8")
    assert source.count("get_global_resources() > SIEGE_TITANIUM_FLOOR") == 2


def test_only_the_constant_line_differs():
    parent = PARENT.read_text(encoding="utf-8").splitlines()
    child = CHILD.read_text(encoding="utf-8").splitlines()
    changed = [
        line for line in difflib.unified_diff(parent, child, lineterm="", n=0)
        if line.startswith(("+", "-"))
        and not line.startswith(("+++", "---"))
        and not line[1:].lstrip().startswith("#")
    ]
    assert changed == ["-SIEGE_START = 45", "+SIEGE_START = 25"], changed
