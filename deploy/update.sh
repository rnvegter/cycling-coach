#!/usr/bin/env bash
# Fietscoach bijwerken naar de nieuwste versie uit GitHub.
#
#   fietscoach-update            alleen als er iets nieuws is
#   fietscoach-update --force    ook als je al up-to-date bent
#
# Wat het doet:
#   1. kijkt of er nieuwe commits zijn en laat zien welke
#   2. maakt eerst een kopie van je data en config (/var/backups/fietscoach)
#   3. zet de nieuwe code neer, werkt Python-pakketten en systemd-units bij
#   4. herstart en controleert of de app reageert
#   5. reageert hij niet: terug naar de vorige versie, en het script faalt
set -euo pipefail

# Dit script staat zelf in de checkout die het gaat vervangen. Bash leest een
# script terwijl het loopt, dus eerst een kopie maken en die uitvoeren.
if [ "${FIETSCOACH_UPDATE_KOPIE:-}" != "1" ]; then
  kopie=$(mktemp /tmp/fietscoach-update.XXXXXX)
  cp "$(readlink -f "$0")" "$kopie"
  FIETSCOACH_UPDATE_KOPIE=1 exec bash "$kopie" "$@"
fi
trap 'rm -f "$0"' EXIT

CODE=/opt/fietscoach
VENV=/opt/fietscoach-venv
ETC=/etc/fietscoach
DATA=/var/lib/fietscoach
BACKUPS=/var/backups/fietscoach
BEWAAR=10
BRANCH=main
PORT=8766
# shellcheck disable=SC1091
[ -f "$ETC/bron" ] && . "$ETC/bron"
# shellcheck disable=SC1091
[ -f "$ETC/omgeving" ] && . "$ETC/omgeving"

stap() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fout() { printf '\033[31mFout: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fout "draai dit als root."
[ -d "$CODE/.git" ] || fout "$CODE is geen git-checkout. Installeer eerst met install.sh."

gezond() {
  for _ in $(seq 1 20); do
    curl -fs -o /dev/null "http://127.0.0.1:$PORT/" && return 0
    sleep 1
  done
  return 1
}

zet_neer() {  # $1 = commit
  git -C "$CODE" reset -q --hard "$1"
  "$VENV/bin/pip" install -q -r "$CODE/requirements.txt"
  install -m 644 "$CODE"/deploy/fietscoach*.service "$CODE"/deploy/fietscoach*.timer /etc/systemd/system/
  systemctl daemon-reload
  systemctl restart fietscoach.service
}

stap "Zoeken naar updates ($BRANCH)"
git -C "$CODE" fetch -q origin "$BRANCH"
oud=$(git -C "$CODE" rev-parse HEAD)
nieuw=$(git -C "$CODE" rev-parse "origin/$BRANCH")
if [ "$oud" = "$nieuw" ] && [ "${1:-}" != "--force" ]; then
  echo "Al up-to-date: $(git -C "$CODE" log -1 --format='%h %s')"
  exit 0
fi
git -C "$CODE" log --format='  %h %s' "$oud..$nieuw" || true

stap "Back-up van data en config"
mkdir -p "$BACKUPS"
bestand="$BACKUPS/fietscoach-$(date +%Y%m%d-%H%M%S)-$(git -C "$CODE" rev-parse --short HEAD).tar.gz"
tar -czf "$bestand" -C / "${DATA#/}" "${ETC#/}"
chmod 600 "$bestand"
echo "$bestand"
# alleen de laatste $BEWAAR bewaren
# shellcheck disable=SC2012  # namen maken we zelf: fietscoach-datum-commit.tar.gz
ls -1t "$BACKUPS"/fietscoach-*.tar.gz 2>/dev/null | tail -n +$((BEWAAR + 1)) | xargs -r rm -f

stap "Nieuwe versie neerzetten"
zet_neer "$nieuw"

stap "Controle"
if gezond; then
  echo "Bijgewerkt naar $(git -C "$CODE" log -1 --format='%h %s')"
  exit 0
fi

echo "De nieuwe versie reageert niet; ik zet de vorige terug."
journalctl -u fietscoach -n 20 --no-pager 2>/dev/null || true
zet_neer "$oud"
gezond || fout "ook de vorige versie start niet. Data-back-up: $bestand"
fout "update teruggedraaid naar $(git -C "$CODE" log -1 --format='%h'). Je data is niet aangeraakt."
