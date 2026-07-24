#!/usr/bin/env bash
# EREBUS arena worker -> always-on systemd service on a Linux VPS.
#
# Prereqs (once): clone the PRIVATE fcode repo onto the box so it has bots/ +
# maps/, e.g. with a GitHub personal-access-token URL so `git pull` keeps
# working unattended:
#   sudo git clone https://<TOKEN>@github.com/Varainrain/fcode.git /opt/fcode
#
# Then:
#   sudo bash /opt/fcode/deploy/vps-setup.sh https://warroom-hq.vercel.app <WARROOM_KEY> /opt/fcode
#
# Ubuntu/Debian. Re-run any time to update settings.
set -euo pipefail

URL="${1:?usage: vps-setup.sh <arena-url> <warroom-key> [repo-dir]}"
KEY="${2:?missing warroom key}"
REPODIR="${3:-/opt/fcode}"
RUNUSER="${SUDO_USER:-root}"

if [ ! -f "$REPODIR/warroom_worker.py" ] || [ ! -d "$REPODIR/bots" ]; then
  echo "!! $REPODIR is not the fcode repo (need warroom_worker.py + bots/ + maps/)"
  echo "   clone it first, then re-run."
  exit 1
fi

echo "== installing deps =="
apt-get update -y
apt-get install -y python3 python3-pip git
# fcode engine (test.pypi index for the pre-release, real pypi for its deps)
pip3 install --break-system-packages \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  fcode==2.3.0.dev26 || \
pip3 install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  fcode==2.3.0.dev26

echo "== writing secret env (root-only) =="
cat >/etc/warroom.env <<EOF
WARROOM_URL=$URL
WARROOM_KEY=$KEY
WARROOM_NAME=vps
EOF
chmod 600 /etc/warroom.env

echo "== installing systemd service =="
cat >/etc/systemd/system/warroom-worker.service <<EOF
[Unit]
Description=EREBUS arena worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUNUSER
WorkingDirectory=$REPODIR
EnvironmentFile=/etc/warroom.env
ExecStart=/usr/bin/python3 -u warroom_worker.py
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now warroom-worker

echo
echo "== done. the worker is now running 24/7 =="
echo "   live logs:   journalctl -u warroom-worker -f"
echo "   restart:     sudo systemctl restart warroom-worker"
echo "   stop:        sudo systemctl stop warroom-worker"
