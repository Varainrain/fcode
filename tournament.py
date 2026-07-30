"""Tournament: OogwayBest vs top July 27 bots, seeds 1-2."""
import subprocess, re, sys

BATTLE = "/Users/MasterOogway/FCODE/bots/fcode/botBattleSeed.py"
BOTS = ["OogwayWIP", "frozen-erebus-v3", "uni-v1", "shield-v1",
        "seatdeny", "lastpop2", "canon-v1", "orion"]

results = {b: {"wins": 0, "games": 0} for b in BOTS}

for i in range(len(BOTS)):
    for j in range(i+1, len(BOTS)):
        a, b = BOTS[i], BOTS[j]
        print(f"{a} vs {b}")
        sys.stdout.flush()

        out = subprocess.run(
            [sys.executable, BATTLE, a, b, "1", "2"],
            capture_output=True, text=True, timeout=300,
            cwd="/Users/MasterOogway/FCODE/bots/fcode"
        )
        for line in out.stdout.split("\n"):
            for bot in (a, b):
                if line.startswith(f"{bot}:"):
                    m = re.search(r"(\d+)/(\d+)", line)
                    if m:
                        w, g = int(m.group(1)), int(m.group(2))
                        results[bot]["wins"] += w
                        results[bot]["games"] += g
                        print(f"  {bot}: {w}/{g}")

print(f"\n{'='*60}")
print("  FINAL STANDINGS")
print(f"{'='*60}")
for name, r in sorted(results.items(), key=lambda x: -x[1]["wins"]/max(x[1]["games"],1)):
    pct = 100 * r["wins"] / r["games"]
    print(f"  {name:20s}  {r['wins']:3d}/{r['games']:3d}  ({pct:5.1f}%)")
