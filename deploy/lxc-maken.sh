#!/usr/bin/env bash
# Op de Proxmox-host: alleen de container klaarzetten, zodat je daarna zelf
# installeert vanuit een git-clone.
#
#   bash lxc-maken.sh
#
# Wat het doet:
#   1. Debian-LXC aanmaken (1 core, 512 MB, 4 GB, unprivileged, nesting, Europe/Amsterdam)
#   2. git en ssh installeren
#   3. een deploy key aanmaken (alleen lezen) en wachten tot je die in GitHub zet
#   4. de repo clonen naar /opt/fietscoach
# Daarna in de container:  bash /opt/fietscoach/deploy/install.sh
#
# Instelbaar (standaard tussen haakjes):
#   CTID (eerstvolgende vrije)  HOSTNAME_CT (fietscoach)  STORAGE (local-lvm)
#   BRIDGE (vmbr0)  IP (dhcp, of bv. 192.168.0.217/24)  GW (bij vast IP)
#   DEBIAN (12; 13 kan ook)  REPO (rnvegter/cycling-coach)  BRANCH (main)
set -euo pipefail

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
HOSTNAME_CT="${HOSTNAME_CT:-fietscoach}"
STORAGE="${STORAGE:-local-lvm}"
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-dhcp}"
GW="${GW:-}"
DEBIAN="${DEBIAN:-12}"
REPO="${REPO:-rnvegter/cycling-coach}"
BRANCH="${BRANCH:-main}"

stap() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fout() { printf '\033[31mFout: %s\033[0m\n' "$*" >&2; exit 1; }
in_ct() { pct exec "$CTID" -- bash -c "$1"; }

command -v pct >/dev/null || fout "dit script hoort op de Proxmox-host."
pct status "$CTID" >/dev/null 2>&1 && fout "container $CTID bestaat al."

stap "Debian $DEBIAN-sjabloon"
pveam update >/dev/null
SJABLOON=$(pveam available --section system | awk -v v="debian-$DEBIAN-standard" '$2 ~ v {print $2}' | sort -V | tail -1)
[ -n "$SJABLOON" ] || fout "geen debian-$DEBIAN-standard sjabloon gevonden."
pveam list local | grep -q "$SJABLOON" || pveam download local "$SJABLOON"

stap "Container $CTID ($HOSTNAME_CT) aanmaken"
net="name=eth0,bridge=$BRIDGE,ip=$IP"
[ "$IP" != "dhcp" ] && [ -n "$GW" ] && net="$net,gw=$GW"
pct create "$CTID" "local:vztmpl/$SJABLOON" \
  --hostname "$HOSTNAME_CT" --cores 1 --memory 512 --swap 256 \
  --rootfs "$STORAGE:4" --net0 "$net" \
  --unprivileged 1 --features nesting=1 --onboot 1 --timezone Europe/Amsterdam \
  --tags fietscoach \
  --description "Fietscoach – trainingsschema (intervals.icu → Wahoo/Zwift)"
pct start "$CTID"

stap "Wachten op netwerk"
for _ in $(seq 1 30); do
  in_ct "getent hosts github.com" >/dev/null 2>&1 && break
  sleep 2
done
in_ct "getent hosts github.com" >/dev/null || fout "container heeft geen internet."

stap "git en ssh installeren"
in_ct "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq git openssh-client ca-certificates curl >/dev/null"

stap "Deploy key"
# Zelfde sleutel en ssh-alias als install.sh gebruikt, zodat die de clone herkent.
# shellcheck disable=SC2016  # $(hostname) e.d. moeten in de container uitgevoerd worden
in_ct 'mkdir -p /root/.ssh && chmod 700 /root/.ssh
[ -f /root/.ssh/fietscoach_deploy ] || ssh-keygen -q -t ed25519 -N "" -C "fietscoach@$(hostname)" -f /root/.ssh/fietscoach_deploy
grep -q "Host github-fietscoach" /root/.ssh/config 2>/dev/null || cat >> /root/.ssh/config <<EOF
Host github-fietscoach
  HostName github.com
  User git
  IdentityFile /root/.ssh/fietscoach_deploy
  IdentitiesOnly yes
EOF
chmod 600 /root/.ssh/config
ssh-keyscan -q github.com >> /root/.ssh/known_hosts 2>/dev/null'

BRON="git@github-fietscoach:${REPO}.git"
until in_ct "GIT_TERMINAL_PROMPT=0 git ls-remote $BRON >/dev/null 2>&1"; do
  echo
  echo "Voeg deze sleutel toe als deploy key (alleen lezen, 'Allow write access' uit):"
  echo "  https://github.com/${REPO}/settings/keys/new"
  echo
  in_ct "cat /root/.ssh/fietscoach_deploy.pub"
  echo
  read -r -p "Druk op Enter als de sleutel is toegevoegd… "
done

stap "Repo clonen naar /opt/fietscoach"
in_ct "git clone -q --branch $BRANCH $BRON /opt/fietscoach && git -C /opt/fietscoach log -1 --format='Versie: %h %s'"

ip=$(in_ct "hostname -I" | awk '{print $1}')
cat <<EOF

Container $CTID staat klaar (${ip:-ip onbekend}). Nu installeren:

  pct enter $CTID
  bash /opt/fietscoach/deploy/install.sh

Of in één keer vanaf de host:

  pct exec $CTID -- bash /opt/fietscoach/deploy/install.sh
EOF
