#!/usr/bin/env bash
# Op de Proxmox-host: maakt een Debian 12-LXC aan en installeert Fietscoach erin.
#
#   bash proxmox-create.sh
#
# Instelbaar met omgevingsvariabelen (standaard tussen haakjes):
#   CTID (eerstvolgende vrije)  HOSTNAME_CT (fietscoach)  STORAGE (local-lvm)
#   BRIDGE (vmbr0)  IP (dhcp, of bv. 192.168.0.217/24)  GW (alleen bij vast IP)
#   REPO (https://github.com/rnvegter/cycling-coach.git)  BRANCH (main)
#   INTERVALS_API_KEY (wordt anders gevraagd)
#
# Klein: 1 core, 512 MB, 4 GB. Unprivileged, met nesting (nodig voor systemd).
set -euo pipefail

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
HOSTNAME="${HOSTNAME_CT:-fietscoach}"
STORAGE="${STORAGE:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-dhcp}"
GW="${GW:-}"
REPO="${REPO:-https://github.com/rnvegter/cycling-coach.git}"
BRANCH="${BRANCH:-main}"
HIER="$(cd "$(dirname "$0")" && pwd)"

stap() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fout() { printf '\033[31mFout: %s\033[0m\n' "$*" >&2; exit 1; }

command -v pct >/dev/null || fout "dit script hoort op de Proxmox-host."
[ -f "$HIER/install.sh" ] || fout "install.sh moet naast dit script staan."

stap "Debian 12-sjabloon"
pveam update >/dev/null
SJABLOON=$(pveam available --section system | awk '/debian-12-standard/ {print $2}' | sort -V | tail -1)
[ -n "$SJABLOON" ] || fout "geen debian-12-standard sjabloon gevonden."
pveam list local | grep -q "$SJABLOON" || pveam download local "$SJABLOON"

stap "Container $CTID ($HOSTNAME) aanmaken"
net="name=eth0,bridge=$BRIDGE,ip=$IP"
[ "$IP" != "dhcp" ] && [ -n "$GW" ] && net="$net,gw=$GW"
pct create "$CTID" "local:vztmpl/$SJABLOON" \
  --hostname "$HOSTNAME" --cores 1 --memory 512 --swap 256 \
  --rootfs "$STORAGE:4" --net0 "$net" \
  --unprivileged 1 --features nesting=1 --onboot 1 \
  --description "Fietscoach – trainingsschema (intervals.icu → Wahoo/Zwift)"
pct start "$CTID"

stap "Wachten op netwerk"
for _ in $(seq 1 30); do
  pct exec "$CTID" -- getent hosts github.com >/dev/null 2>&1 && break
  sleep 2
done
pct exec "$CTID" -- getent hosts github.com >/dev/null || fout "container heeft geen internet."

stap "Installeren in de container"
pct push "$CTID" "$HIER/install.sh" /root/install.sh --perms 700
pct exec "$CTID" -- env REPO="$REPO" BRANCH="$BRANCH" INTERVALS_API_KEY="${INTERVALS_API_KEY:-}" \
  bash /root/install.sh

cat <<EOF

Container $CTID is klaar. Handig:
  pct enter $CTID                   in de container
  pct exec $CTID -- fietscoach-update   bijwerken vanaf de host
  vzdump $CTID --storage <naam> --mode snapshot   back-up van de hele container
EOF
