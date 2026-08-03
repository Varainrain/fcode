"""Scope tests for the earlier verified-damage recall threshold."""

from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "bots" / "exp_meta_recall450"
PARENT = ROOT / "bots" / "meta-generalist-v1"


def constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }


def normalized_tree(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "RECALL_CORE_HP"):
            node.value = ast.Constant(value=0)
    return ast.dump(tree, include_attributes=False)


def test_threshold_moves_only_fifty_hp_earlier():
    assert constants(PARENT / "main.py")["RECALL_CORE_HP"] == 400
    assert constants(CANDIDATE / "main.py")["RECALL_CORE_HP"] == 450


def test_exact_v9_scope():
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (CANDIDATE / name).read_bytes() == (PARENT / name).read_bytes()
    assert normalized_tree(CANDIDATE / "main.py") == normalized_tree(
        PARENT / "main.py")


def test_no_fingerprints():
    source = (CANDIDATE / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_threshold_moves_only_fifty_hp_earlier()
    test_exact_v9_scope()
    test_no_fingerprints()
