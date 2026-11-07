#!/usr/bin/env bash
# Fietscoach installeren in een Debian 12-container (LXC).
#
#   bash install.sh
#
# Of zonder vragen, bv. vanuit proxmox-create.sh:
#   REPO=https://github.com/rnvegter/cycling-coach.git INTERVALS_API_KEY=xxx bash install.sh
#
# Indeling (zoals cwem: code alleen-lezen, data apart):
#   /opt/fietscoach            broncode (git checkout, eigendom van root)
#   /opt/fietscoach-venv       Python-omgeving
#   /etc/fietscoach/config.yaml  sleutel en locatie (alleen root en de dienst)
#   /var/lib/fietscoach        data: plan, instellingen, je RPE en readiness
#   /var/backups/fietscoach    kopie van de data vóór elke update
set -euo pipefail

REPO="${REPO:-https://github.com/rnvegter/cycling-coach.git}"
BRANCH="${BRANCH:-main}"
PORT="${PORT:-8766}"
CODE=/opt/fietscoach
VENV=/opt/fietscoach-venv
ETC=/etc/fietscoach
DATA=/var/lib/fietscoach
SLEUTEL=/root/.ssh/fietscoach_deploy

stap() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fout() { printf '\033[31mFout: %s\033[0m\n' "$*" >&2; exit 1; }
interactief() { [ -t 0 ]; }

[ "$(id -u)" -eq 0 ] || fout "draai dit als root."

stap "Pakketten installeren"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3-venv python3-pip curl ca-certificates openssh-client >/dev/null

# --- broncode ophalen -----------------------------------------------------------
# Publieke repo: gewoon via https. Private repo: een deploy key (alleen lezen) die
# je één keer in GitHub toevoegt. Een token is niet nodig.
ssh_url() {  # https://github.com/eigenaar/repo(.git) → git@github-fietscoach:eigenaar/repo.git
  local pad="${REPO#https://github.com/}"
  pad="${pad%.git}"
  echo "git@github-fietscoach:${pad}.git"
}

kan_lezen() { GIT_TERMINAL_PROMPT=0 git ls-remote "$1" >/dev/null 2>&1; }

stap "Broncode ophalen uit $REPO"
BRON="$REPO"
if ! kan_lezen "$BRON"; then
  [[ "$REPO" == https://github.com/* ]] || fout "kan $REPO niet lezen."
  echo "De repo is niet publiek bereikbaar; ik zet een deploy key op."
  mkdir -p /root/.ssh && chmod 700 /root/.ssh
  [ -f "$SLEUTEL" ] || ssh-keygen -q -t ed25519 -N "" -C "fietscoach@$(hostname)" -f "$SLEUTEL"
  if ! grep -q "Host github-fietscoach" /root/.ssh/config 2>/dev/null; then
    cat >> /root/.ssh/config <<EOF
Host github-fietscoach
  HostName github.com
  User git
  IdentityFile $SLEUTEL
  IdentitiesOnly yes
EOF
    chmod 600 /root/.ssh/config
  fi
  ssh-keyscan -q github.com >> /root/.ssh/known_hosts 2>/dev/null
  BRON="$(ssh_url)"
  pad="${REPO#https://github.com/}"; pad="${pad%.git}"
  until kan_lezen "$BRON"; do
    echo
    echo "Voeg deze sleutel toe als deploy key (alleen lezen, 'Allow write access' uit):"
    echo "  https://github.com/${pad}/settings/keys/new"
    echo
    cat "$SLEUTEL.pub"
    echo
    interactief || fout "deploy key nog niet toegevoegd; draai het script opnieuw als dat gedaan is."
    read -r -p "Druk op Enter als de sleutel is toegevoegd… "
  done
fi

if [ -d "$CODE/.git" ]; then
  git -C "$CODE" remote set-url origin "$BRON"
  git -C "$CODE" fetch -q origin "$BRANCH"
  git -C "$CODE" reset -q --hard "origin/$BRANCH"
else
  [ -e "$CODE" ] && fout "$CODE bestaat al en is geen git-checkout. Verplaats het eerst."
  git clone -q --branch "$BRANCH" "$BRON" "$CODE"
fi
echo "Versie: $(git -C "$CODE" log -1 --format='%h %s')"

stap "Python-omgeving"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$CODE/requirements.txt"

stap "Gebruiker, mappen en configuratie"
id fietscoach >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin fietscoach
install -d -o fietscoach -g fietscoach -m 750 "$DATA"
install -d -m 750 /var/backups/fietscoach
install -d -o root -g fietscoach -m 750 "$ETC"
if [ ! -f "$ETC/config.yaml" ]; then
  cp "$CODE/config.example.yaml" "$ETC/config.yaml"
  sleutel="${INTERVALS_API_KEY:-}"
  if [ -z "$sleutel" ] && interactief; then
    read -r -p "API-sleutel van intervals.icu (Settings → Developer Settings; leeg = later): " sleutel
  fi
  if [ -n "$sleutel" ]; then
    sed -i "s|PLAK-HIER-JE-SLEUTEL|${sleutel}|" "$ETC/config.yaml"
  else
    echo "Geen sleutel ingevuld. Later: nano $ETC/config.yaml en systemctl restart fietscoach"
  fi
fi
chown root:fietscoach "$ETC/config.yaml"
chmod 640 "$ETC/config.yaml"
echo "PORT=$PORT" > "$ETC/omgeving"

stap "Diensten"
install -m 644 "$CODE"/deploy/fietscoach*.service "$CODE"/deploy/fietscoach*.timer /etc/systemd/system/
ln -sf "$CODE/deploy/update.sh" /usr/local/bin/fietscoach-update
cat > "$ETC/bron" <<EOF
REPO=$REPO
BRANCH=$BRANCH
EOF
systemctl daemon-reload
systemctl enable -q fietscoach.service fietscoach-dagelijks.timer
systemctl restart fietscoach.service
systemctl start fietscoach-dagelijks.timer

stap "Controle"
for _ in $(seq 1 20); do
  curl -fs -o /dev/null "http://127.0.0.1:$PORT/" && break
  sleep 1
done
curl -fsS -o /dev/null "http://127.0.0.1:$PORT/" || fout "de app reageert niet. Kijk met: journalctl -u fietscoach -n 50"

ip=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<EOF

Klaar. Fietscoach draait op http://${ip:-<ip>}:$PORT
  Bijwerken:   fietscoach-update
  Logboek:     journalctl -u fietscoach -n 50
  Config:      $ETC/config.yaml
  Data:        $DATA
EOF
