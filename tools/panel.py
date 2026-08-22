"""panel.py - gate a candidate against a DIVERSE ARCHETYPE PANEL, not mirrors.

Why: fp-vs-fp mirror gates saturated - every single-knob change landed at
48-53% and told us nothing, and two bots shipped on those "neutral" gates
went 0-5 on the ladder. A panel of genuinely different opponents (rush,
grind, waves, fortress, eco, spear, teammate builds, old champions) has far
more discriminating power, and the archive holds 300+ of them.

    python panel.py <candidate> [baseline] [seeds]

Runs the candidate against every panel bot, and the baseline too when given,
then prints per-opponent win rates and the aggregate. A candidate that beats
the baseline ACROSS ARCHETYPES is a real improvement; one that only wins the
mirror is noise.
"""
import subprocess
import sys
import re

PANEL = [
    ("jav1", "creep/grind"),
    ("wavebot", "wave siege"),
    ("v143base", "kick rush"),
    ("rusher", "gunner rush"),
    ("kfort", "fortress/defense"),
    ("citadel", "eco+defense"),
    ("beanbot", "eco cage (Bean)"),
    ("spear2", "sentinel spear (adgato)"),
    ("chimera36", "our old champion"),
    ("v179dl", "teammate live build"),
]

CAND = sys.argv[1] if len(sys.argv) > 1 else "fp14"
BASE = sys.argv[2] if len(sys.argv) > 2 else None
SEEDS = sys.argv[3] if len(sys.argv) > 3 else "2"


def run(bot, opp):
    """One lab batch; returns (wins, games) or None if the pairing failed."""
    try:
        out = subprocess.run(
            [sys.executable, "lab.py", bot, opp, SEEDS],
            capture_output=True, text=True, timeout=1800).stdout
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"(\d+) games\s*\|\s*\S+ wins (\d+)", out)
    if not m:
        return None
    return int(m.group(2)), int(m.group(1))


def main():
    print(flush=True) or print(f"PANEL  candidate={CAND}" + (f"  baseline={BASE}" if BASE else "")
          + f"  seeds={SEEDS}\n")
    print(f"{'opponent':<12} {'archetype':<24} {CAND:>10}"
          + (f" {BASE:>10}  delta" if BASE else ""))
    cw = cg = bw = bg = 0
    for opp, kind in PANEL:
        c = run(CAND, opp)
        if c is None:
            print(f"{opp:<12} {kind:<24} {'--':>10}")
            continue
        cw += c[0]
        cg += c[1]
        line = f"{opp:<12} {kind:<24} {100*c[0]/c[1]:9.0f}%"
        if BASE:
            b = run(BASE, opp)
            if b:
                bw += b[0]
                bg += b[1]
                line += (f" {100*b[0]/b[1]:9.0f}%"
                         f"  {100*c[0]/c[1] - 100*b[0]/b[1]:+5.0f}")
        print(line, flush=True)
    print()
    if cg:
        print(f"AGGREGATE {CAND}: {cw}/{cg} = {100*cw/cg:.1f}%")
    if BASE and bg:
        print(f"AGGREGATE {BASE}: {bw}/{bg} = {100*bw/bg:.1f}%")
        print(flush=True) or print(f"PANEL DELTA: {100*cw/cg - 100*bw/bg:+.1f} points")


main()
