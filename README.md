# Fietscoach

Eigen JOIN-achtige trainingsplanner. Maakt een periodiseringsschema (basis → opbouw → piek, elke 4e week herstel), stuurt dagelijks bij en zet de trainingen via intervals.icu klaar op je **Wahoo** (buiten) en in **Zwift** op de **Kickr** (binnen, ERG).

## Wat het doet

Werkt zoals JOIN, maar draait op je eigen server en ziet eruit als cwem (zelfde kleuren, letters en kaarten). De zeven kleuren van de cwem-temperatuurschaal staan hier voor trainingszones: blauw = herstel, groenblauw = duur, olijf = tempo, geel = sweetspot, oranje = drempel, oranjerood = VO2max.

**Vier schermen**
- **Vandaag**: FTP, eFTP, fitheid, vermoeidheid en vorm; readiness invullen; de training van vandaag met profielgrafiek, weer en aanpassingen; openstaande feedback (RPE); deze week; een andere tijd op een dag.
- **Schema**: alle weken met focus, uren en per training de opbouw en (na het rijden) de score.
- **Bibliotheek**: alle 27 trainingsvormen met profiel en uitleg, te bekijken op 45, 60 of 90 minuten.
- **Instellingen**: doel (FTP, duur of een tocht met datum), focusblokken, je gewone week, voorkeuren en weergrenzen. Opslaan bouwt het schema vanaf vandaag opnieuw op; het verleden blijft staan.

**Wat het schema laat meebewegen**
- **Focus per blok**: `gemengd`, `sweetspot` (3×10 → 2×20 min), `zone2` of `gepolariseerd`. Elke vierde week herstel; een ramp-test standaard elke 8 weken (instelbaar: 4, 8, 12 of nooit). Na de test stelt de app de nieuwe FTP voor op basis van de eFTP uit intervals.icu.
- **Afwisseling**: elke week een andere vorm van dezelfde soort, bv. sweetspot als blokken, met uitschieters, als ladder of op wisselende cadans; drempel als over-unders, piramide of met harde start; VO2max als 30/15's, 40/20's of piramide; duurritten met spin-ups, sprints of krachtblokjes. Uit te zetten in Instellingen. Alles in % FTP, met cadansdoelen waar dat hoort (ook in de .zwo). Korte harde stukken (sprints, 30/15's, 40/20's, uitschieters) zijn zonder ERG (`freeride`): een trainer reageert een paar seconden te laat, en bij blokken onder een minuut rijd je anders een groot deel op het verkeerde vermogen.
- **RPE na elke rit** (1–10): voelde een soort training zwaarder dan bedoeld, dan wordt de volgende van die soort lichter, en andersom. Heb je de RPE al in intervals.icu gegeven, dan wordt die overgenomen.
- **Readiness** (benen en energie, 1–5): bij 3 of lager wordt vandaag lichter; bij 2 of lager ook morgen. Levert je horloge HRV en rusthartslag aan intervals.icu, dan telt dat automatisch mee: duidelijk lagere HRV of hogere rusthartslag dan je gemiddelde van de 28 dagen ervoor = minder hersteld.
- **Afwezig** (vakantie, reis): een periode in Instellingen, ook ver vooruit. Geen trainingen; na 5 dagen of langer eerst drie dagen zonder intervallen.
- **Duur van vandaag aanpassen**: op de kaart van de training kies je vlak voor het rijden 30–120 minuten (lange rit 60–240) of *Overslaan*. Intervaltrainingen krijgen meer of minder herhalingen; overslaan schuift ze naar later in de week. Daarna gaat de nieuwe versie meteen naar intervals.icu.
- **Andere tijd op een dag**: geen tijd → een intervaltraining of lange rit schuift naar een andere dag in die week; meer tijd → langere duurrit; een normaal vrije dag met tijd krijgt een extra duurrit.
- **Ongeplande zware rit** (clubrit, tocht: ≥ 2 uur, load ≥ 80 of RPE ≥ 8) → de dag erna wordt herstel.
- **Gereden is niet gedaan**: een training telt als gedaan als intervals.icu de rit eraan koppelde, of als de rit minstens 60% van de geplande duur was. Een woon-werkrit op een intervaldag telt dus niet.
- **Gemiste intervaltraining** → naar een latere duurdag in dezelfde week, in dezelfde vorm.
- **Vorm** (fitheid − vermoeidheid) onder −20 of −30 → de komende week korter.
- **Weer per rit** (Open-Meteo, uurverwachting): alleen de uren waarin je rijdt tellen (starttijd per buitendag in Instellingen, standaard 09:30 in het weekend en 18:30 doordeweeks). Regen, harde wind of vorst in dát tijdvak → naar Zwift; de lange rit eerst naar een droge dag, beoordeeld over zijn eigen duur. Bij buitenritten een link naar cwem voor kledingadvies (`cwem_url` in `config.yaml`).
- **Trainingsscore** na elke rit: duur en intensiteit (gepland tegenover gereden), elk 0–100.
- **eFTP** uit intervals.icu, met een seintje als die duidelijk boven je FTP ligt.
- **.zwo-download** per training, als reserve voor Zwift.

Elke ochtend om 05:30 en met de knop **Bijsturen**: ritten, wellness en weer vers ophalen, bijsturen en de komende 14 dagen naar intervals.icu (type *Ride* = buiten/Wahoo, *VirtualRide* = Zwift). Na invoer in het scherm (RPE, readiness, duur, afwezigheid) is het schema direct bijgewerkt met de laatst opgehaalde gegevens; de sync naar intervals.icu gaat dan op de achtergrond.

**Hoe het schema tot stand komt.** De generator maakt een basisschema (`basis.json`), dat nooit wordt bijgestuurd. Bij elke wijziging wordt het schema dat je ziet (`plan.json`) daar opnieuw uit afgeleid met al je invoer: ritten, RPE, readiness, uitzonderingen, afwezigheid, vorm en weer. Zelfde invoer, zelfde uitkomst; niets stapelt zich op.

## Installatie

De broncode staat in een privé GitHub-repo (`rnvegter/cycling-coach`). In de container komt een *deploy key* (alleen lezen), die je één keer in GitHub toevoegt (*Settings → Deploy keys*). Een token is niet nodig. Er zijn drie routes.

### A. Container maken, zelf clonen en installeren (aanrader)

Op de Proxmox-host. Het script staat in de repo; kopieer het naar de host (bv. de *Raw*-weergave op GitHub in een bestand plakken):

```
bash lxc-maken.sh
```

Dit maakt een Debian 12-LXC (1 core, 512 MB, 4 GB, unprivileged, Europe/Amsterdam), installeert git, maakt de deploy key, wacht tot je die in GitHub hebt gezet en clonet de repo naar `/opt/fietscoach`. Daarna:

```
pct exec <CTID> -- bash /opt/fietscoach/deploy/install.sh
```

Instelbaar met omgevingsvariabelen, bv. een vast IP of Debian 13:

```
IP=192.168.0.217/24 GW=192.168.0.1 DEBIAN=13 bash lxc-maken.sh
```

Andere opties: `CTID`, `HOSTNAME_CT`, `STORAGE`, `BRIDGE`, `REPO`, `BRANCH`.

### B. Met de Debian-container van de community scripts

Op de Proxmox-host (kies bij de vragen 4 GB schijf):

```
bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/debian.sh)"
```

Dan in de container (`pct enter <CTID>`), één voor één:

```
apt update
```
```
apt install -y git openssh-client
```
```
ssh-keygen -t ed25519 -N "" -f /root/.ssh/fietscoach_deploy
```
```
cat /root/.ssh/fietscoach_deploy.pub
```

Zet die sleutel als deploy key in GitHub. Dan:

```
printf 'Host github-fietscoach\n  HostName github.com\n  User git\n  IdentityFile /root/.ssh/fietscoach_deploy\n  IdentitiesOnly yes\n' >> /root/.ssh/config
```
```
git clone git@github-fietscoach:rnvegter/cycling-coach.git /opt/fietscoach
```
```
bash /opt/fietscoach/deploy/install.sh
```

`install.sh` herkent de clone en de sleutel en zet de tijdzone zelf goed.

### C. Alles in één keer

`deploy/proxmox-create.sh` (samen met `install.sh` in één map op de host) maakt de container en installeert direct:

```
bash proxmox-create.sh
```

### Wat waar staat

| Wat | Waar |
|---|---|
| Broncode (git, alleen-lezen) | `/opt/fietscoach` |
| Python-omgeving | `/opt/fietscoach-venv` |
| Sleutel en locatie | `/etc/fietscoach/config.yaml` |
| Je data (plan, instellingen, RPE, readiness) | `/var/lib/fietscoach` |
| Kopie vóór elke update | `/var/backups/fietscoach` (laatste 10) |

De app draait op poort 8766. Open hem en vul **Instellingen** in.

## Verbinding met intervals.icu testen

In **Instellingen → Verbinding testen**, of in de container:

```
sudo -u fietscoach FIETSCOACH_CONFIG=/etc/fietscoach/config.yaml FIETSCOACH_DATA=/var/lib/fietscoach /opt/fietscoach-venv/bin/python -m fietscoach.cli test
```

Alleen lezen. Je ziet per stap (atleet, wellness, ritten, kalender) of het lukt en welke velden binnenkomen; bij een fout de HTTP-code met uitleg (401 = sleutel klopt niet).

## Bewaken met Uptime Kuma

`GET /health` geeft 200 als de laatste sync naar intervals.icu minder dan 36 uur oud is en foutloos ging, anders 503 met de reden. Maak in Uptime Kuma een HTTP-monitor op `http://<ip-lxc>:8766/health`.

## Bijwerken

Push je wijzigingen naar GitHub en draai in de container:

```
fietscoach-update
```

Of vanaf de Proxmox-host:

```
pct exec <CTID> -- fietscoach-update
```

Het script laat zien welke commits er nieuw zijn en kopieert eerst je data en config naar `/var/backups/fietscoach`. Daarna zet het de nieuwe code neer, werkt pakketten en systemd-units bij en herstart de app. Reageert de nieuwe versie niet binnen 20 seconden op `/ready`, dan gaat hij automatisch terug naar de vorige versie en meldt het script een fout. Je data wordt daarbij niet aangeraakt.

## Ontwikkelen

- Tests: `pip install -r requirements.txt pytest` en `python -m pytest`. Bij elke push draaien de tests (Python 3.11 en 3.13) en shellcheck in GitHub Actions.
- Afhankelijkheden staan vast in `requirements.txt`; de directe staan in `requirements.in`.
- Lettertypes (Barlow Condensed, IBM Plex) worden zelf geserveerd uit `fietscoach/static/fonts` (SIL Open Font License); er gaan geen verzoeken naar Google.
- Formulieren worden alleen geaccepteerd vanaf de site zelf (controle op `Origin`, ook achter Caddy via `X-Forwarded-Host`).

## Back-up

- **Hele container** (aanrader): Proxmox *Datacenter → Backup*, dagelijks, modus *Snapshot*, naar je QNAP-share. Je Borg-back-up naar Hetzner neemt die mee.
- **Alleen de data**: `/var/lib/fietscoach` en `/etc/fietscoach`. Elke update maakt hier al een kopie van in `/var/backups/fietscoach`.
- Terugzetten van een data-kopie:
  ```
  systemctl stop fietscoach
  ```
  ```
  tar -xzf /var/backups/fietscoach/<bestand>.tar.gz -C /
  ```
  ```
  systemctl start fietscoach
  ```

## Achter Caddy (met Authelia)

De app heeft zelf geen login, dus zet hem achter Authelia, net als je andere diensten:

```
fietscoach.dockerapp.org {
    import authelia
    reverse_proxy <ip-van-de-lxc>:8766
}
```

(Pas `import authelia` aan naar hoe je de forward_auth in je Caddyfile hebt opgezet.)

## intervals.icu koppelen aan Wahoo en Zwift

Ga in intervals.icu naar *Settings* → *Connections* en zet bij **Wahoo** en **Zwift** het doorsturen van geplande trainingen aan. Daarna:

- **Wahoo**: de training van vandaag staat onder *Plan/Workouts* op je ELEMNT (even synchroniseren in de Wahoo-app).
- **Zwift**: de training staat onder *Workouts* → *Custom Workouts* (map van intervals.icu) en rijdt in ERG op je Kickr.

## Handig

- Logboek: `journalctl -u fietscoach -n 50` en `journalctl -u fietscoach-dagelijks -n 50`
- Handmatig bijsturen:
  ```
  sudo -u fietscoach FIETSCOACH_CONFIG=/etc/fietscoach/config.yaml FIETSCOACH_DATA=/var/lib/fietscoach /opt/fietscoach-venv/bin/python -m fietscoach.cli dagelijks
  ```
- Na een FTP-test: zet je nieuwe FTP in intervals.icu. Alle doelen staan in % FTP, dus de wattages schuiven vanzelf mee.
- Doel, focus, beschikbaarheid en voorkeuren stel je in het scherm **Instellingen** in. In `config.yaml` staan alleen je sleutel en locatie.
