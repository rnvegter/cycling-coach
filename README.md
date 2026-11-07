# Fietscoach

Eigen JOIN-achtige trainingsplanner. Maakt een periodiseringsschema (basis → opbouw → piek, elke 4e week herstel), stuurt dagelijks bij en zet de trainingen via intervals.icu klaar op je **Wahoo** (buiten) en in **Zwift** op de **Kickr** (binnen, ERG).

## Wat het doet

Werkt zoals JOIN, maar draait op je eigen server en ziet eruit als cwem (zelfde kleuren, letters en kaarten). De zeven kleuren van de cwem-temperatuurschaal staan hier voor trainingszones: blauw = herstel, groenblauw = duur, olijf = tempo, geel = sweetspot, oranje = drempel, oranjerood = VO2max.

**Vier schermen**
- **Vandaag**: FTP, eFTP, fitheid, vermoeidheid en vorm; readiness invullen; de training van vandaag met profielgrafiek, weer en aanpassingen; openstaande feedback (RPE); deze week; een andere tijd op een dag.
- **Schema**: alle weken met focus, uren en per training de opbouw en (na het rijden) de score.
- **Bibliotheek**: alle 34 trainingsvormen met profiel en uitleg, te bekijken op 45, 60 of 90 minuten. Daaronder protocollen uit gepubliceerd onderzoek, met bron: 30/15's (Rønnestad 2015/2020), 4×8 en 4×16 (Seiler 2013), 4×4 (Helgerud 2007), sprintintervallen 4–6×30 s (Burgomaster/Gibala 2005), Tabata (1996) en de 20-minutentest (Allen & Coggan).
- **Instellingen**: doel (FTP, duur of een tocht met datum), focusblokken, je gewone week, voorkeuren en weergrenzen. Opslaan bouwt het schema vanaf vandaag opnieuw op; het verleden blijft staan.

**Wat het schema laat meebewegen**
- **Focus per blok**: `gemengd`, `sweetspot` (3×10 → 2×20 min), `zone2` of `gepolariseerd`. Elke vierde week herstel; een FTP-test standaard elke 8 weken (instelbaar: 4, 8, 12 of nooit), als ramp-test of als 20-minutentest. Altijd dezelfde vorm, zodat de uitslagen vergelijkbaar zijn. Na de test stelt de app de nieuwe FTP voor op basis van de eFTP uit intervals.icu.
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

Je installeert en werkt bij met gewone git-opdrachten. Uitgangspunt: een Debian 12- of 13-container (LXC), **niet** de Proxmox-host zelf. Het script weigert daar te draaien.

### 1. Container

Bijvoorbeeld met het community script op de Proxmox-host:

```
bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/debian.sh)"
```

Neem 4 GB schijf, unprivileged, met **nesting aan** (*Options → Features*), anders draait systemd niet. Ga daarna de container in (`pct enter <CTID>`); alles hieronder doe je daar als root.

### 2. Clonen

```
apt update
```
```
apt install -y git
```

De repo is privé, dus git moet kunnen inloggen. Kies één manier:

- **Deploy key** (alleen lezen, aanrader):
  ```
  ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519
  ```
  ```
  cat /root/.ssh/id_ed25519.pub
  ```
  Zet die sleutel in GitHub bij *cycling-coach → Settings → Deploy keys → Add deploy key*. Dan:
  ```
  git clone git@github.com:rnvegter/cycling-coach.git /opt/fietscoach
  ```
- **Repo openbaar maken**: er staan geen geheimen in (je sleutel en data staan buiten de repo). Dan:
  ```
  git clone https://github.com/rnvegter/cycling-coach.git /opt/fietscoach
  ```

### 3. Installeren

```
bash /opt/fietscoach/deploy/install.sh
```

Het script installeert Python en een paar basispakketten, zet de tijdzone op Europe/Amsterdam, maakt de Python-omgeving in de clone (`.venv`), de gebruiker `fietscoach`, de config en de diensten, en controleert of de app reageert. Vul daarna je API-sleutel van intervals.icu in en herstart:

```
nano /etc/fietscoach/config.yaml
```
```
systemctl restart fietscoach
```

Open `http://<ip-van-de-container>:8766` en klik in **Instellingen** eerst op **Verbinding testen**.

### Wat waar staat

| Wat | Waar |
|---|---|
| Code (je git-clone) | `/opt/fietscoach` (of waar je hem clonet) |
| Python-omgeving | `/opt/fietscoach/.venv` |
| Sleutel en locatie | `/etc/fietscoach/config.yaml` |
| Je data (plan, instellingen, RPE, readiness) | `/var/lib/fietscoach` |
| Kopie vóór elke installatie-run | `/var/backups/fietscoach` (laatste 10) |

## Bijwerken

```
cd /opt/fietscoach
```
```
git pull
```
```
bash deploy/install.sh
```

Het script kopieert eerst je data en config naar `/var/backups/fietscoach`, werkt de Python-pakketten en diensten bij, herstart en controleert of de app reageert. Lukt dat niet, dan noemt het de laatst werkende versie en hoe je daarheen teruggaat, bijvoorbeeld:

```
git checkout 1a2b3c4 && bash deploy/install.sh
```

## Verbinding met intervals.icu testen

In **Instellingen → Verbinding testen**, of in de container:

```
sudo -u fietscoach FIETSCOACH_CONFIG=/etc/fietscoach/config.yaml FIETSCOACH_DATA=/var/lib/fietscoach /opt/fietscoach/.venv/bin/python -m fietscoach.cli test
```

Alleen lezen. Je ziet per stap (atleet, wellness, ritten, kalender) of het lukt en welke velden binnenkomen; bij een fout de HTTP-code met uitleg (401 = sleutel klopt niet).

## Bewaken met Uptime Kuma

`GET /health` geeft 200 als de laatste sync naar intervals.icu minder dan 36 uur oud is en foutloos ging, anders 503 met de reden. Maak in Uptime Kuma een HTTP-monitor op `http://<ip-lxc>:8766/health`.

## Ontwikkelen

- Tests: `pip install -r requirements.txt pytest` en `python -m pytest`. Bij elke push draaien de tests (Python 3.11 en 3.13) en shellcheck in GitHub Actions.
- Afhankelijkheden staan vast in `requirements.txt`; de directe staan in `requirements.in`.
- Lettertypes (Barlow Condensed, IBM Plex) worden zelf geserveerd uit `fietscoach/static/fonts` (SIL Open Font License); er gaan geen verzoeken naar Google.
- Formulieren worden alleen geaccepteerd vanaf de site zelf (controle op `Origin`, ook achter Caddy via `X-Forwarded-Host`).

## Back-up

- **Hele container** (aanrader): Proxmox *Datacenter → Backup*, dagelijks, modus *Snapshot*, naar je QNAP-share. Je Borg-back-up naar Hetzner neemt die mee.
- **Alleen de data**: `/var/lib/fietscoach` en `/etc/fietscoach`. Elke run van `install.sh` maakt hier al een kopie van in `/var/backups/fietscoach`.
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
  sudo -u fietscoach FIETSCOACH_CONFIG=/etc/fietscoach/config.yaml FIETSCOACH_DATA=/var/lib/fietscoach /opt/fietscoach/.venv/bin/python -m fietscoach.cli dagelijks
  ```
- Na een FTP-test: zet je nieuwe FTP in intervals.icu. Alle doelen staan in % FTP, dus de wattages schuiven vanzelf mee.
- Doel, focus, beschikbaarheid en voorkeuren stel je in het scherm **Instellingen** in. In `config.yaml` staan alleen je sleutel en locatie.
