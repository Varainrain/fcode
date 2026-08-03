"""Run all pairwise matchups between July 27 bots, seeds 1-2."""
import subprocess, re, sys, itertools

BATTLE = "/Users/MasterOogway/FCODE/bots/fcode/botBattleSeed.py"
BOTS = ["canon-v1", "frozen-erebus-v3", "lastpop2", "orion", "seatdeny", "shield-v1", "uni-v1"]

results = []
for a, b in itertools.combinations(BOTS, 2):
    print(f"{a} vs {b}")
    sys.stdout.flush()
    out = subprocess.run(
        [sys.executable, BATTLE, a, b, "1", "2"],
        capture_output=True, text=True, timeout=300,
        cwd="/Users/MasterOogway/FCODE/bots/fcode"
    )
    for line in out.stdout.split("\n"):
        if line.strip():
            print(f"  {line.strip()}")
    sys.stdout.flush()
