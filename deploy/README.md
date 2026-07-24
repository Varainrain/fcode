# Always-on arena worker (VPS)

Put the arena engine on your own VPS so no home PC ever needs to be on. The
box only runs `fcode run` matches locally and posts results — bots stay on
a machine you own (same privacy as your laptop; nothing goes to Vercel).

## Setup (once, ~3 min on Ubuntu/Debian)

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
