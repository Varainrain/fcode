"""gatestats — confidence intervals for lab win rates.

Added 2026-08-23 after the sensitivity sweep embarrassed us: at threshold 50
hybrid9 uses spear mode on ONE of twenty maps, making it nearly identical to
fp28, yet the two measured 56% and 46%. Ten points apart, same bot. At n=60 a
win rate carries a 95% interval of about +/-13 points, so "55% PROMOTE" and
"50% neutral" are NOT distinguishable - and this project has been promoting on
exactly that margin all campaign.

    python gatestats.py 79 150 [label]      # wins, games
"""
import math
import sys


def ci(w, n):
    p = w / n
    se = math.sqrt(p * (1 - p) / n)
    return p, 1.96 * se


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print(f"{'n':>6}{'95% CI half-width':>20}{'min win% to beat 50':>22}")
        for n in (30, 60, 100, 150, 300, 600):
            h = 1.96 * math.sqrt(0.25 / n) * 100
            print(f"{n:>6}{h:>19.1f}%{50 + h:>21.1f}%")
        return
    w, n = int(sys.argv[1]), int(sys.argv[2])
    label = sys.argv[3] if len(sys.argv) > 3 else ''
    p, h = ci(w, n)
    lo, hi = 100 * (p - h), 100 * (p + h)
    verdict = ('BEATS baseline' if lo > 50 else
               'LOSES to baseline' if hi < 50 else
               'INDISTINGUISHABLE from 50%')
    print(f"{label} {w}/{n} = {100*p:.1f}%  95% CI [{lo:.1f}, {hi:.1f}]  -> {verdict}")


main()
