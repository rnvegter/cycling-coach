#!/usr/bin/env bash
# Fietscoach installeren in een kale Debian 13-container (LXC).
#
# Vooraf, in Proxmox: een Debian 13-LXC, unprivileged, met 'nesting' aan
# (nodig voor systemd), 1 core, 512 MB, 4 GB. Bijvoorbeeld met het community
# script ct/debian.sh of via 'Create CT' met het debian-13-standard sjabloon.
#
# Dan in de container, als root:
#   bash install.sh
#
# Zonder vragen (bv. opnieuw draaien):
#   INTERVALS_API_KEY=xxx bash install.sh
#
# Opnieuw draaien is veilig: bestaande config, data en sleutel blijven staan.
#
# Indeling (code alleen-lezen, data apart):
#   /opt/fietscoach              broncode (git checkout, eigendom van root)
#   /opt/fietscoach-venv         Python-omgeving
#   /etc/fietscoach/config.yaml  sleutel en locatie (alleen root en de dienst)
#   /var/lib/fietscoach          data: plan, instellingen, je RPE en readiness
#   /var/backups/fietscoach      kopie van de data vóór elke update
set -euo pipefail
export LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive

REPO="${REPO:-https://github.com/rnvegter/cycling-coach.git}"
BRANCH="${BRANCH:-main}"
PORT="${PORT:-8766}"
TIJDZONE="${TIJDZONE:-Europe/Amsterdam}"
CODE=/opt/fietscoach
VENV=/opt/fietscoach-venv
ETC=/etc/fietscoach
DATA=/var/lib/fietscoach
SLEUTEL=/root/.ssh/fietscoach_deploy

stap() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fout() { printf '\n\033[31mFout: %s\033[0m\n' "$*" >&2; exit 1; }
let_op() { printf '\033[33mLet op: %s\033[0m\n' "$*"; }

# Vragen gaan via de terminal, ook als het script zelf via een pijp of
# 'pct exec' binnenkomt. Geen terminal: dan kan er niets gevraagd worden.
vraag() {  # $1 = prompt, uitkomst in $ANTWOORD
  ANTWOORD=""
  if [ -r /dev/tty ] && { true < /dev/tty; } 2>/dev/null; then
    read -r -p "$1" ANTWOORD < /dev/tty || true
    return 0
  fi
  return 1
}

# --- controles vooraf -------------------------------------------------------------

stap "Controles"
[ "$(id -u)" -eq 0 ] || fout "draai dit als root."
[ -r /etc/os-release ] || fout "geen /etc/os-release: is dit wel Debian?"
# shellcheck disable=SC1091
. /etc/os-release
if [ "${ID:-}" != "debian" ]; then
  let_op "dit is ${PRETTY_NAME:-onbekend}, niet Debian; ik ga door, maar het is getest voor Debian 13."
else
  case "${VERSION_ID:-}" in
    13) echo "Debian 13 (${VERSION_CODENAME:-trixie})" ;;
    12) echo "Debian 12 werkt ook." ;;
    *) let_op "Debian ${VERSION_ID:-?}: getest voor Debian 13." ;;
  esac
fi
staat=$(systemctl is-system-running 2>/dev/null || true)
case "$staat" in
  running|degraded|starting|initializing) echo "systemd: $staat" ;;
  *) fout "systemd draait niet ('${staat:-geen antwoord}'). Zet in Proxmox bij de container Options → Features → 'nesting' aan en herstart de container." ;;
esac
getent hosts github.com >/dev/null 2>&1 || fout "geen internet of DNS in de container (github.com onbekend)."

stap "Pakketten installeren"
apt-get update -qq || fout "apt-get update mislukt; controleer netwerk en /etc/apt/sources.list(.d)."
apt-get install -y -qq --no-install-recommends \
  git openssh-client ca-certificates curl tzdata iproute2 python3 python3-venv >/dev/null \
  || fout "pakketten installeren mislukt (git, openssh-client, curl, tzdata, iproute2, python3, python3-venv)."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fout "Python $(python3 -V 2>&1) is te oud; minimaal 3.11 (Debian 12 of 13)."
echo "$(python3 -V), $(git --version)"

# Een LXC staat vaak op UTC. Dan is "vandaag" na middernacht nog gisteren en
# draait de ochtendtimer een uur te laat.
stap "Tijdzone $TIJDZONE"
[ -f "/usr/share/zoneinfo/$TIJDZONE" ] || fout "onbekende tijdzone $TIJDZONE"
ln -sf "/usr/share/zoneinfo/$TIJDZONE" /etc/localtime
echo "$TIJDZONE" > /etc/timezone
date

# --- broncode ophalen -------------------------------------------------------------
# Publieke repo: via https. Privé-repo: een deploy key (alleen lezen) die je één
# keer in GitHub toevoegt. Een token is niet nodig.

kan_lezen() { GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="ssh -o BatchMode=yes" git ls-remote "$1" >/dev/null 2>&1; }

stap "Broncode ophalen uit $REPO"
BRON="$REPO"
if ! kan_lezen "$BRON"; then
  [[ "$REPO" == https://github.com/* ]] || fout "kan $REPO niet lezen."
  pad="${REPO#https://github.com/}"
  pad="${pad%.git}"
  echo "De repo is privé; ik gebruik een deploy key."
  install -d -m 700 /root/.ssh
  if [ ! -f "$SLEUTEL" ]; then
    ssh-keygen -q -t ed25519 -N "" -C "fietscoach@$(cat /etc/hostname 2>/dev/null || echo lxc)" -f "$SLEUTEL" \
      || fout "ssh-keygen mislukt."
  fi
  if ! grep -q "^Host github-fietscoach" /root/.ssh/config 2>/dev/null; then
    printf 'Host github-fietscoach\n  HostName github.com\n  User git\n  IdentityFile %s\n  IdentitiesOnly yes\n' \
      "$SLEUTEL" >> /root/.ssh/config
  fi
  chmod 600 /root/.ssh/config
  grep -q "^github.com " /root/.ssh/known_hosts 2>/dev/null || ssh-keyscan -q -t ed25519,rsa github.com >> /root/.ssh/known_hosts 2>/dev/null \
    || fout "kan de sleutel van github.com niet ophalen (poort 22 geblokkeerd?)."
  BRON="git@github-fietscoach:${pad}.git"
  until kan_lezen "$BRON"; do
    echo
    echo "Voeg deze sleutel toe als deploy key (alleen lezen, 'Allow write access' uit):"
    echo "  https://github.com/${pad}/settings/keys/new"
    echo
    cat "$SLEUTEL.pub"
    echo
    vraag "Druk op Enter als de sleutel is toegevoegd (of typ 'stop')… " \
      || fout "deploy key nog niet toegevoegd en geen terminal om te wachten. Voeg hem toe en draai het script opnieuw."
    [ "$ANTWOORD" = "stop" ] && fout "gestopt. Draai het script opnieuw als de sleutel in GitHub staat."
  done
fi

if [ -d "$CODE/.git" ]; then
  git -C "$CODE" remote set-url origin "$BRON"
  git -C "$CODE" fetch -q origin "$BRANCH"
  git -C "$CODE" reset -q --hard "origin/$BRANCH"
else
  [ -e "$CODE" ] && fout "$CODE bestaat al en is geen git-checkout. Verplaats het eerst."
  git clone -q --branch "$BRANCH" "$BRON" "$CODE" || fout "clonen mislukt."
fi
echo "Versie: $(git -C "$CODE" log -1 --format='%h %s')"

stap "Python-omgeving"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" || fout "venv maken mislukt; is python3-venv geïnstalleerd?"
fi
"$VENV/bin/pip" install -q --upgrade pip || fout "pip bijwerken mislukt (geen toegang tot pypi.org?)."
"$VENV/bin/pip" install -q -r "$CODE/requirements.txt" || fout "Python-pakketten installeren mislukt."

stap "Gebruiker, mappen en configuratie"
id fietscoach >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin fietscoach
install -d -o fietscoach -g fietscoach -m 750 "$DATA"
install -d -m 750 /var/backups/fietscoach
install -d -o root -g fietscoach -m 750 "$ETC"
if [ ! -f "$ETC/config.yaml" ]; then
  cp "$CODE/config.example.yaml" "$ETC/config.yaml"
  sleutel="${INTERVALS_API_KEY:-}"
  if [ -z "$sleutel" ] && vraag "API-sleutel van intervals.icu (Settings → Developer Settings; leeg = later): "; then
    sleutel="$ANTWOORD"
  fi
  if [ -n "$sleutel" ]; then
    sed -i "s|PLAK-HIER-JE-SLEUTEL|${sleutel}|" "$ETC/config.yaml"
  else
    let_op "geen sleutel ingevuld. Later: nano $ETC/config.yaml en systemctl restart fietscoach"
  fi
fi
chown root:fietscoach "$ETC/config.yaml"
chmod 640 "$ETC/config.yaml"
echo "PORT=$PORT" > "$ETC/omgeving"
printf 'REPO=%s\nBRANCH=%s\n' "$REPO" "$BRANCH" > "$ETC/bron"

stap "Diensten"
install -m 644 "$CODE"/deploy/fietscoach*.service "$CODE"/deploy/fietscoach*.timer /etc/systemd/system/
ln -sf "$CODE/deploy/update.sh" /usr/local/bin/fietscoach-update
systemctl daemon-reload
systemctl enable -q fietscoach.service fietscoach-dagelijks.timer
systemctl restart fietscoach.service
systemctl start fietscoach-dagelijks.timer

stap "Controle"
for _ in $(seq 1 20); do
  curl -fs -o /dev/null "http://127.0.0.1:$PORT/ready" && break
  sleep 1
done
curl -fsS -o /dev/null "http://127.0.0.1:$PORT/ready" || fout "de app reageert niet. Kijk met: journalctl -u fietscoach -n 50"

# Alleen voor de melding; mag de installatie nooit laten mislukken.
ip=$( (ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1) 2>/dev/null || true)
cat <<EOF

Klaar. Fietscoach draait op http://${ip:-<ip-van-de-container>}:$PORT
  Eerst:       Instellingen → Verbinding testen
  Bijwerken:   fietscoach-update
  Logboek:     journalctl -u fietscoach -n 50
  Config:      $ETC/config.yaml
  Data:        $DATA
EOF
