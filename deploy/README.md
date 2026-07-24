# Always-on arena worker (VPS)

Put the arena engine on your own VPS so no home PC ever needs to be on. The
box only runs `fcode run` matches locally and posts results — bots stay on
a machine you own (same privacy as your laptop; nothing goes to Vercel).
You do NOT need Claude on the VPS — just Python + this repo.

## Windows VPS (Scheduled Task)

In an elevated PowerShell:

```
# 1. Python (if missing): winget install Python.Python.3.12  (reopen PowerShell)
# 2. clone the private fcode repo with a read-only token so `git pull` works unattended
cd C:\
git clone https://<TOKEN>@github.com/Varainrain/fcode.git
cd fcode
# 3. install the worker as an always-on task
powershell -ExecutionPolicy Bypass -File deploy\vps-setup.ps1 -Url https://warroom-hq.vercel.app -Key 593C-5B2R-56MG-34MH
```

Runs at boot, restarts on crash, pulls new bots from `main`, grinds the
ladder. Watch: `Get-Content C:\fcode\worker.log -Wait -Tail 20`.

## Linux VPS (systemd) — Ubuntu/Debian

## Setup (once, ~3 min)

1. Clone the private fcode repo onto the VPS with a token so unattended
   `git pull` keeps working. Make a GitHub **fine-grained PAT** (read-only,
   this repo) and:

   ```
   sudo git clone https://<TOKEN>@github.com/Varainrain/fcode.git /opt/fcode
   ```

2. Run the installer (installs python/pip/git + the fcode engine, writes a
   root-only secret file, installs and starts a systemd service):

   ```
   sudo bash /opt/fcode/deploy/vps-setup.sh https://warroom-hq.vercel.app 593C-5B2R-56MG-34MH /opt/fcode
   ```

That's it — the worker now runs 24/7, restarts on crash/reboot, pulls new
bots from `main` every ~2 min, and (with Auto League on) grinds the ladder
forever.

## Manage

```
journalctl -u warroom-worker -f        # live logs
sudo systemctl restart warroom-worker  # after a manual change
sudo systemctl stop warroom-worker     # pause
```

## Notes

- A small VPS (1 vCPU) plays matches slower — the worker scales to core
  count automatically. Totally fine, just fewer games/hour.
- No `fcode login` needed: local `fcode run` doesn't touch the ladder.
- Update the engine when the league does: SSH in, `pip3 install ...
  fcode==<new>` and `sudo systemctl restart warroom-worker`.
