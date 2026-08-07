"""Check everything the pipeline needs, and say exactly what to do about it.

    python -m autolab.doctor

Written because the first real launch failed three different ways in a row
(wrong directory, no engine on the Windows PATH, a dashboard bound inside WSL),
and none of those errors said what to fix.
"""
import socket
import sys
import time
from pathlib import Path

from . import engine, store
from .build_template import KNOB_SPEC, TEMPLATE

ROOT = Path(__file__).resolve().parent.parent
OK, BAD = "  ok  ", " FAIL "


def main():
    fails = []

    def check(cond, label, hint=""):
        print(("%s%s" % (OK if cond else BAD, label)))
        if not cond:
            fails.append((label, hint))
        return cond

    print(f"python {sys.version.split()[0]}  cwd={Path.cwd()}")
    print(f"repo   {ROOT}\n")

    check(Path.cwd() == ROOT or (Path.cwd() / "autolab").is_dir(),
          f"running from the repo ({ROOT})",
          f"cd {ROOT}  - `python -m autolab.*` only resolves from the repo root")

    maps = sorted(p.stem for p in (ROOT / "maps").glob("*.map26"))
    check(bool(maps), f"maps/ has {len(maps)} maps",
          "fcode maps sync  - and check the pool matches the league's 15")

    check(TEMPLATE.exists(), "bots/_template exists",
          "python -m autolab.build_template")

    mode = engine.detect()
    check(mode != "missing", f"fcode engine: {engine.describe()}",
          "the engine is not on PATH here and not reachable in WSL. Either\n"
          "         pip install the fcode CLI for THIS python, or set\n"
          "         AUTOLAB_ACTIVATE to the shell snippet that activates the venv\n"
          "         inside WSL (default: source ~/.venvs/fcode/bin/activate)")

    if mode != "missing" and maps and TEMPLATE.exists():
        # A real game is the only proof the shim actually works end to end.
        from . import runner
        try:
            runner.materialise("_doctor_a", runner.defaults())
            runner.materialise("_doctor_b", runner.defaults())
            t = time.time()
            # Two games, one per seat, with the SAME bot on both sides. Many
            # maps are seat-locked - identical code went 8/8 to the B seat on
            # antler, six of them t1000 tiebreaks - so a one-game probe on the
            # wrong map looks like a broken engine when nothing is wrong.
            g1 = runner.play("_doctor_a", "_doctor_b", maps[0], 1)
            g2 = runner.play("_doctor_b", "_doctor_a", maps[0], 2)
            ok = check(g1[0] is not None and g2[0] is not None,
                       f"played 2 real games on {maps[0]} in {time.time()-t:.0f}s "
                       f"(seat A: {g1[0]} {g1[1]} t{g1[2]}; "
                       f"seat B: {g2[0]} {g2[1]} t{g2[2]})",
                       "the engine's own output is printed above - read it")
            winner = g1[0]
            if not ok:
                text = (runner.LAST_OUTPUT["text"] or "").strip()
                print("        --- what the engine actually said ---")
                for line in (text.splitlines() or ["(no output at all)"])[-14:]:
                    print("        " + line)
                print("        -------------------------------------")
        except Exception as exc:                      # noqa: BLE001
            check(False, f"played a real game: {type(exc).__name__}: {exc}",
                  "see the traceback above")
        finally:
            import shutil
            for n in ("_doctor_a", "_doctor_b"):
                shutil.rmtree(ROOT / "bots" / n, ignore_errors=True)

    try:
        con = store.init()
        n = con.execute("SELECT COUNT(*) c FROM games").fetchone()["c"]
        con.close()
        check(True, f"database ok ({store.DB.name}, {n} games recorded)")
    except Exception as exc:                          # noqa: BLE001
        check(False, f"database: {exc}", f"check write access to {store.DB}")

    from .dash import PORT
    s = socket.socket()
    free = s.connect_ex(("127.0.0.1", PORT)) != 0
    s.close()
    print(f"{OK if free else '  --  '}dashboard port {PORT} "
          f"{'free' if free else 'already in use (dashboard already running?)'}")

    print()
    if fails:
        print("PROBLEMS:")
        for label, hint in fails:
            print(f"  - {label}")
            if hint:
                print(f"    -> {hint}")
        return 1
    print("all good. start it with:")
    print("    python -m autolab.runner        (leave running)")
    print(f"    python -m autolab.dash          (http://localhost:{PORT})")
    print(f"\nknob space: {len(KNOB_SPEC)} knobs, "
          f"lanes {sorted({v[4] for v in KNOB_SPEC.values()})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
