"""Finding the fcode engine, from whichever side of the WSL boundary you are on.

On this machine the engine is installed in a WSL venv and is NOT on the Windows
PATH, while the repo lives on the Windows filesystem. So `python -m autolab.*`
from cmd.exe imports fine and then dies at the first `fcode` call with
WinError 2. Rather than making you remember which shell to be in, this resolves
the engine once and shims through WSL when it has to.

Override either piece with environment variables:
    AUTOLAB_ACTIVATE   shell snippet that puts fcode on PATH inside WSL
                       (default: source ~/.venvs/fcode/bin/activate)
    AUTOLAB_ENGINE     force a mode: native | wsl
"""
import os
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTIVATE = os.environ.get("AUTOLAB_ACTIVATE",
                          "source ~/.venvs/fcode/bin/activate")
_MODE = None


def wsl_root():
    """C:\\Users\\x\\repo -> /mnt/c/Users/x/repo (already-posix paths pass through)."""
    p = str(ROOT)
    if len(p) > 2 and p[1] == ":":
        return "/mnt/" + p[0].lower() + p[2:].replace("\\", "/")
    return p


def detect(force=None):
    """'native' if fcode is on PATH here, 'wsl' if it is reachable inside WSL."""
    global _MODE
    if force:
        _MODE = force
    if _MODE:
        return _MODE
    forced = os.environ.get("AUTOLAB_ENGINE")
    if forced:
        _MODE = forced
        return _MODE
    if shutil.which("fcode"):
        _MODE = "native"
        return _MODE
    if shutil.which("wsl"):
        probe = subprocess.run(
            ["wsl", "-e", "bash", "-lc",
             f"{ACTIVATE} >/dev/null 2>&1; command -v fcode"],
            capture_output=True, encoding="utf-8", errors="replace")
        if (probe.stdout or "").strip():
            _MODE = "wsl"
            return _MODE
    _MODE = "missing"
    return _MODE


def run(args, timeout=None):
    """Run `fcode <args>` and return stdout+stderr combined.

    Both streams, deliberately: the engine reports bot validation failures and
    crashes on stderr, and a caller that only reads stdout sees "no Winner line"
    with no idea why. That is the silent-failure class this repo keeps losing
    days to.
    """
    mode = detect()
    if mode == "native":
        out = subprocess.run(["fcode", *args], capture_output=True,
                             encoding="utf-8", errors="replace",
                             cwd=ROOT, timeout=timeout)
    elif mode == "wsl":
        inner = "cd %s && %s && fcode %s" % (
            shlex.quote(wsl_root()), ACTIVATE,
            " ".join(shlex.quote(a) for a in args))
        out = subprocess.run(["wsl", "-e", "bash", "-lc", inner],
                             capture_output=True, encoding="utf-8",
                             errors="replace", timeout=timeout)
    else:
        out = None
    if out is not None:
        return (out.stdout or "") + (out.stderr or "")
    raise RuntimeError(
        "fcode engine not found. It is not on this PATH and not reachable in "
        "WSL with AUTOLAB_ACTIVATE=%r. Run `python -m autolab.doctor`." % ACTIVATE)


def scratch_replay(tag):
    """A per-game replay path, so concurrent games do not fight over one file.

    Every `fcode run` writes a replay; with no --replay flag they all write
    ./replay.replay26 and the losers of that race die with "failed to write
    replay ... (os error 22)" AFTER playing the whole game, producing no Winner
    line. Under the WSL shim this also keeps the write on the Linux filesystem
    instead of drvfs, which is faster.
    """
    if detect() == "wsl":
        return f"/tmp/autolab_replays/{tag}.replay26"
    d = ROOT / "autolab" / "_replays"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{tag}.replay26")


def prepare_scratch():
    if detect() == "wsl":
        subprocess.run(["wsl", "-e", "bash", "-lc", "mkdir -p /tmp/autolab_replays"],
                       capture_output=True)
    else:
        (ROOT / "autolab" / "_replays").mkdir(parents=True, exist_ok=True)


def describe():
    mode = detect()
    if mode == "native":
        return f"native ({shutil.which('fcode')})"
    if mode == "wsl":
        return f"wsl shim (cd {wsl_root()}; {ACTIVATE})"
    return "MISSING"
