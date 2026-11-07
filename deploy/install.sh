#!/usr/bin/env bash
# Fietscoach installeren of bijwerken, vanuit een git-clone.
#
# Eerste keer (in een Debian 12/13-container, als root):
#   git clone <repo> /opt/fietscoach
#   bash /opt/fietscoach/deploy/install.sh
#
# Bijwerken:
#   cd /opt/fietscoach && git pull && bash deploy/install.sh
#
# Het script werkt met de code zoals die in de clone staat; het haalt zelf
# niets op uit git. Opnieuw draaien is veilig: config en data blijven staan,
# en vóór elke run wordt de data gekopieerd naar /var/backups/fietscoach.
#
# Waar alles staat:
#   <clone>/                     de code (waar je hem clonet; bv. /opt/fietscoach)
#   <clone>/.venv                Python-omgeving (in .gitignore)
#   /etc/fietscoach/config.yaml  sleutel en locatie (alleen root en de dienst)
#   /var/lib/fietscoach          data: plan, instellingen, je RPE en readiness
#   /var/backups/fietscoach      kopie van data en config vóór elke run (laatste 10)
set -euo pipefail
export LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive

CODE="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
VENV="$CODE/.venv"
PORT="${PORT:-8766}"
TIJDZONE="${TIJDZONE:-Europe/Amsterdam}"
ETC=/etc/fietscoach
DATA=/var/lib/fietscoach
BACKUPS=/var/backups/fietscoach

stap() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fout() { printf '\n\033[31mFout: %s\033[0m\n' "$*" >&2; exit 1; }
let_op() { printf '\033[33mLet op: %s\033[0m\n' "$*"; }

# --- controles vooraf -------------------------------------------------------------

stap "Controles"
[ "$(id -u)" -eq 0 ] || fout "draai dit als root."
if command -v pveversion >/dev/null 2>&1 || [ -d /etc/pve ]; then
  fout "dit is een Proxmox-host. Installeer Fietscoach in een container (LXC), niet op de host zelf."
fi
if [ ! -f "$CODE/requirements.txt" ] || [ ! -d "$CODE/fietscoach" ]; then
  fout "$CODE lijkt geen Fietscoach-clone."
fi
[ -r /etc/os-release ] || fout "geen /etc/os-release: is dit wel Debian?"
# shellcheck disable=SC1091
. /etc/os-release
if [ "${ID:-}" != "debian" ]; then
  let_op "dit is ${PRETTY_NAME:-onbekend}, niet Debian; ik ga door, maar het is gemaakt voor Debian 12/13."
fi
staat=$(systemctl is-system-running 2>/dev/null || true)
case "$staat" in
  running|degraded|starting|initializing) ;;
  *) fout "systemd draait niet ('${staat:-geen antwoord}'). Zet in Proxmox bij de container Options → Features → 'nesting' aan en herstart de container." ;;
esac
versie=$(git -C "$CODE" log -1 --format='%h %s' 2>/dev/null || echo "onbekend (geen git?)")
echo "Code: $CODE"
echo "Versie: $versie"
if [ -n "$(git -C "$CODE" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
  let_op "er zijn lokale wijzigingen in $CODE; die worden gebruikt zoals ze zijn."
fi

stap "Pakketten"
apt-get update -qq || fout "apt-get update mislukt; controleer netwerk en pakketbronnen."
apt-get install -y -qq --no-install-recommends \
  ca-certificates curl tzdata python3 python3-venv >/dev/null \
  || fout "pakketten installeren mislukt (ca-certificates, curl, tzdata, python3, python3-venv)."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fout "Python $(python3 -V 2>&1) is te oud; minimaal 3.11 (Debian 12 of 13)."
python3 -V

# Een container staat vaak op UTC. Dan is "vandaag" na middernacht nog gisteren
# en draait de ochtendtimer een uur te laat.
stap "Tijdzone $TIJDZONE"
[ -f "/usr/share/zoneinfo/$TIJDZONE" ] || fout "onbekende tijdzone $TIJDZONE"
ln -sf "/usr/share/zoneinfo/$TIJDZONE" /etc/localtime
echo "$TIJDZONE" > /etc/timezone

stap "Gebruiker, mappen en configuratie"
id fietscoach >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin fietscoach
install -d -o fietscoach -g fietscoach -m 750 "$DATA"
install -d -m 750 "$BACKUPS"
install -d -o root -g fietscoach -m 750 "$ETC"
eerste_keer=0
if [ ! -f "$ETC/config.yaml" ]; then
  eerste_keer=1
  cp "$CODE/config.example.yaml" "$ETC/config.yaml"
  if [ -n "${INTERVALS_API_KEY:-}" ]; then
    sed -i "s|PLAK-HIER-JE-SLEUTEL|${INTERVALS_API_KEY}|" "$ETC/config.yaml"
  fi
fi
chown root:fietscoach "$ETC/config.yaml"
chmod 640 "$ETC/config.yaml"
echo "PORT=$PORT" > "$ETC/omgeving"
# De dienst moet de code kunnen lezen, ook als je hem ergens anders clonet.
chmod -R o+rX "$CODE" 2>/dev/null || true

if [ "$eerste_keer" -eq 0 ]; then
  stap "Back-up van data en config"
  bestand="$BACKUPS/fietscoach-$(date +%Y%m%d-%H%M%S).tar.gz"
  tar -czf "$bestand" -C / "${DATA#/}" "${ETC#/}"
  chmod 600 "$bestand"
  echo "$bestand"
  # shellcheck disable=SC2012  # namen maken we zelf
  ls -1t "$BACKUPS"/fietscoach-*.tar.gz | tail -n +11 | xargs -r rm -f
fi

stap "Python-omgeving"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" || fout "venv maken mislukt; is python3-venv geïnstalleerd?"
fi
"$VENV/bin/pip" install -q --upgrade pip || fout "pip bijwerken mislukt (geen toegang tot pypi.org?)."
"$VENV/bin/pip" install -q -r "$CODE/requirements.txt" || fout "Python-pakketten installeren mislukt."

stap "Diensten"
# De units in de repo gaan uit van /opt/fietscoach; hier komt het echte pad in.
for unit in "$CODE"/deploy/fietscoach*.service "$CODE"/deploy/fietscoach*.timer; do
  sed -e "s|/opt/fietscoach-venv|$VENV|g" -e "s|/opt/fietscoach|$CODE|g" "$unit" \
    > "/etc/systemd/system/$(basename "$unit")"
done
rm -f /usr/local/bin/fietscoach-update  # van een oudere versie
systemctl daemon-reload
systemctl enable -q fietscoach.service fietscoach-dagelijks.timer
systemctl restart fietscoach.service
systemctl restart fietscoach-dagelijks.timer

stap "Controle"
for _ in $(seq 1 20); do
  curl -fs -o /dev/null "http://127.0.0.1:$PORT/ready" && break
  sleep 1
done
if ! curl -fs -o /dev/null "http://127.0.0.1:$PORT/ready"; then
  journalctl -u fietscoach -n 15 --no-pager 2>/dev/null || true
  vorige=$(cat "$ETC/werkende-versie" 2>/dev/null || true)
  if [ -n "$vorige" ]; then
    fout "de app reageert niet. Terug naar de laatst werkende versie:
  cd $CODE && git checkout ${vorige:0:7} && bash deploy/install.sh
Zegt de oude versie dat de gegevens te nieuw zijn, zet dan eerst de back-up van zojuist terug:
  systemctl stop fietscoach && tar -xzf ${bestand:-/var/backups/fietscoach/<nieuwste>.tar.gz} -C /
(en later terug naar de nieuwste met: git checkout main && git pull)"
  fi
  fout "de app reageert niet. Kijk met: journalctl -u fietscoach -n 50"
fi
git -C "$CODE" rev-parse HEAD > "$ETC/werkende-versie" 2>/dev/null || true

ip=$( (ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1) 2>/dev/null || true)
echo
echo "Klaar. Fietscoach draait op http://${ip:-<ip-van-de-container>}:$PORT"
if grep -q "PLAK-HIER-JE-SLEUTEL" "$ETC/config.yaml"; then
  echo
  echo "Nog doen: je API-sleutel van intervals.icu invullen en de app herstarten:"
  echo "  nano $ETC/config.yaml"
  echo "  systemctl restart fietscoach"
fi
cat <<EOF

  Bijwerken:   cd $CODE && git pull && bash deploy/install.sh
  Logboek:     journalctl -u fietscoach -n 50
  Daarna:      Instellingen → Verbinding testen
EOF
