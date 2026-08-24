"""versionwatch — alarm if the ACTIVE submission changes before the lock.

Written after six stale autoeval.py processes kept flipping the active bot:
`pkill` is a bash builtin and does not kill Windows processes, so three
"stopped" reports were all wrong, and every one of those processes carried
--final 198 and would have overridden the intended finals bot at 08:15.

This only REPORTS. It never activates anything - a teammate may legitimately
change the bot, and a watchdog that fights them would be worse than the bug.

    python versionwatch.py 205
"""
import re
import subprocess
import sys
import time
import datetime as dt


def active():
    p = subprocess.run(["fcode", "status"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    m = re.search(r"Active bot:\s*v(\d+)", (p.stdout or "") + (p.stderr or ""))
    return m.group(1) if m else None


want = sys.argv[1] if len(sys.argv) > 1 else "205"
print(f"watching for changes away from v{want}", flush=True)
last = None
while True:
    cur = active()
    stamp = dt.datetime.now().strftime("%H:%M")
    if cur != last:
        flag = "OK" if cur == want else "*** CHANGED ***"
        print(f"[{stamp}] active = v{cur}  {flag}", flush=True)
        last = cur
    time.sleep(300)
