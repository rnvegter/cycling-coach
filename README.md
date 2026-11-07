# Fietscoach

Eigen JOIN-achtige trainingsplanner. Maakt een periodiseringsschema (basis → opbouw → piek, elke 4e week herstel), stuurt dagelijks bij en zet de trainingen via intervals.icu klaar op je **Wahoo** (buiten) en in **Zwift** op de **Kickr** (binnen, ERG).

## Wat het doet

Werkt zoals JOIN, maar draait op je eigen server en ziet eruit als cwem (zelfde kleuren, letters en kaarten). De zeven kleuren van de cwem-temperatuurschaal staan hier voor trainingszones: blauw = herstel, groenblauw = duur, olijf = tempo, geel = sweetspot, oranje = drempel, oranjerood = VO2max.

**Vier schermen**
- **Vandaag**: FTP, eFTP, fitheid, vermoeidheid en vorm; readiness invullen; de training van vandaag met profielgrafiek, weer, voedingsadvies en aanpassingen; een andere training kiezen; openstaande feedback (RPE); deze week; een andere tijd op een dag.
- **Schema**: een grafiek van fitheid, vermoeidheid en vorm (de afgelopen zes weken gemeten, daarna voorspeld als je het schema volgt, met je tocht als die er is); alle weken met focus, uren, TSS gepland en gereden, en per training de opbouw en (na het rijden) de score.
- **Bibliotheek**: alle 34 trainingsvormen met profiel, uitleg en een **zwaarte van 1 tot 5**, te bekijken op 45, 60 of 90 minuten. De zwaarte volgt uit de intensiteit (IF, genormaliseerd vermogen per seconde met een 30 s-gemiddelde, zodat korte sprints niet overdrijven): < 0,60 = 1, < 0,72 = 2, < 0,82 = 3, < 0,87 = 4, daarboven 5. Lange ritten tellen zwaarder: TSS ≥ 100 minstens 3, ≥ 180 minstens 4. Daaronder protocollen uit gepubliceerd onderzoek, met bron: 30/15's (Rønnestad 2015/2020), 4×8 en 4×16 (Seiler 2013), 4×4 (Helgerud 2007), sprintintervallen 4–6×30 s (Burgomaster/Gibala 2005), Tabata (1996) en de 20-minutentest (Allen & Coggan).
- **Instellingen**: doel (FTP, duur of een tocht met datum), focusblokken, je gewone week, voorkeuren en weergrenzen. Opslaan bouwt het schema vanaf vandaag opnieuw op; het verleden blijft staan.

**Wat het schema laat meebewegen**
- **Focus per blok**: `gemengd`, `sweetspot` (3×10 → 2×20 min), `zone2` of `gepolariseerd`. Elke vierde week herstel; een FTP-test standaard elke 8 weken (instelbaar: 4, 8, 12 of nooit), als ramp-test of als 20-minutentest. Altijd dezelfde vorm, zodat de uitslagen vergelijkbaar zijn. Na de test stelt de app de nieuwe FTP voor op basis van de eFTP uit intervals.icu.
- **Afwisseling**: elke week een andere vorm van dezelfde soort, bv. sweetspot als blokken, met uitschieters, als ladder of op wisselende cadans; drempel als over-unders, piramide of met harde start; VO2max als 30/15's, 40/20's of piramide; duurritten met spin-ups, sprints of krachtblokjes. Uit te zetten in Instellingen. Alles in % FTP, met cadansdoelen waar dat hoort (ook in de .zwo). Korte harde stukken (sprints, 30/15's, 40/20's, uitschieters) zijn zonder ERG (`freeride`): een trainer reageert een paar seconden te laat, en bij blokken onder een minuut rijd je anders een groot deel op het verkeerde vermogen.
- **Zwaarte loopt op**: binnen een blok van vier weken kiest de app trainingen met oplopende zwaarte (sweetspot 3→4, drempel en VO2max 4→5), hoogstens één training van zwaarte 5 per week, en in de herstelweek niet boven 3. Een te zware RPE of een matige readiness zet de zwaarte een stap terug.
- **Andere training kiezen**: op de kaart van vandaag (en de volgende training) een andere vorm van dezelfde soort, met zwaarte, ook je eigen workouts; of lichter (duurrit, herstelrit). *Automatisch* zet het terug.
- **Eten en drinken**: voor **buitenritten** doet cwem dit, omdat drinken vooral van het weer afhangt. De knop *Kleding, eten en drinken in cwem* (en de link in het ochtendbericht) geeft de rit mee: datum, starttijd, duur, tempo en zwaarte. cwem toont dan naast je kleding het aantal bidons (met of zonder elektrolyten, op basis van temperatuur en luchtvochtigheid in je rijtijd) en hoeveel eten. Voor **binnenritten** (vanaf 45 min) en buiten zonder `cwem_url` geeft Fietscoach zelf een algemene richtlijn: koolhydraten per uur oplopend met de duur, en binnen 0,75–1 liter per uur met elektrolyten, omdat je zonder rijwind meer zweet. Geen persoonlijk advies.
- **RPE na elke rit** (1–10): voelde een soort training zwaarder dan bedoeld, dan wordt de volgende van die soort lichter, en andersom. Heb je de RPE al in intervals.icu gegeven, dan wordt die overgenomen.
- **Readiness** (benen en energie, 1–5): bij 3 of lager wordt vandaag lichter; bij 2 of lager ook morgen. Levert je horloge HRV en rusthartslag aan intervals.icu, dan telt dat automatisch mee: duidelijk lagere HRV of hogere rusthartslag dan je gemiddelde van de 28 dagen ervoor = minder hersteld.
- **Afwezig** (vakantie, reis): een periode in Instellingen, ook ver vooruit. Geen trainingen; na 5 dagen of langer eerst drie dagen zonder intervallen.
- **Duur van vandaag aanpassen**: op de kaart van de training kies je vlak voor het rijden 30–120 minuten (lange rit 60–240) of *Overslaan*. Intervaltrainingen krijgen meer of minder herhalingen; overslaan schuift ze naar later in de week. Daarna gaat de nieuwe versie meteen naar intervals.icu.
- **Extra training**: toch tijd en zin? Op Vandaag kies je een dag zonder training (tot twee weken vooruit), de duur, de soort (duurrit, herstel, tempo, sweetspot, drempel, VO2max) en Zwift, buiten of "weer beslist". Hij past zich aan je fase en zwaarte aan, gaat naar intervals.icu en telt mee in TSS en fitheid. Naast een andere intensieve dag krijg je een waarschuwing. Het schema gebruikt hem niet om gemiste trainingen naartoe te schuiven. Weghalen kan met een knop bij de training.
- **Andere tijd op een dag**: geen tijd → een intervaltraining of lange rit schuift naar een andere dag in die week; meer tijd → langere duurrit; een normaal vrije dag met tijd krijgt een extra duurrit.
- **Ongeplande zware rit** (clubrit, tocht: ≥ 2 uur, load ≥ 80 of RPE ≥ 8) → de dag erna wordt herstel.
- **Gereden is niet gedaan**: een training telt als gedaan als intervals.icu de rit eraan koppelde, of als de rit minstens 60% van de geplande duur was. Een woon-werkrit op een intervaldag telt dus niet.
- **Gemiste intervaltraining** → naar een latere duurdag in dezelfde week, in dezelfde vorm.
- **Vorm** (fitheid − vermoeidheid) onder −20 of −30 → de komende week korter.
- **Weer per rit** (Open-Meteo, uurverwachting): alleen de uren waarin je rijdt tellen (starttijd per buitendag in Instellingen, standaard 09:30 in het weekend en 18:30 doordeweeks). Regen, harde wind of vorst in dát tijdvak → naar Zwift; de lange rit eerst naar een droge dag, beoordeeld over zijn eigen duur. Bij buitenritten een link naar cwem voor kledingadvies (`cwem_url` in `config.yaml`).
- **Trainingsscore** na elke rit: duur en intensiteit (gepland tegenover gereden), elk 0–100.
- **eFTP** uit intervals.icu, met een seintje als die duidelijk boven (> 3%) of ruim onder (> 8%) je FTP ligt. Na een FTP-test of bij een hogere eFTP zet je met één knop de nieuwe FTP in intervals.icu. Oude ritten houden hun FTP. Zwift en je Wahoo rekenen met hun eigen FTP: pas die zelf aan, de app herinnert je eraan.
- **Weekterugblik**: op maandag en dinsdag op Vandaag, en zondag om 20:00 als bericht: gereden tegenover gepland (uren, TSS), gemiddelde RPE, verandering in fitheid en wat de komende week brengt.
- **.zwo-download** per training, als reserve voor Zwift.

Elke ochtend om 07:00 (dan zitten HRV en rusthartslag van de nacht er meestal in) en met de knop **Bijsturen**: ritten, wellness en weer vers ophalen, bijsturen en de komende 14 dagen naar intervals.icu (type *Ride* = buiten/Wahoo, *VirtualRide* = Zwift). Na invoer in het scherm (RPE, readiness, duur, afwezigheid) is het schema direct bijgewerkt met de laatst opgehaalde gegevens; de sync naar intervals.icu gaat dan op de achtergrond.

**Je eigen wijzigingen in intervals.icu blijven staan.** Verplaats, wijzig of verwijder je een training van Fietscoach in intervals.icu, dan overschrijft de sync dat niet meer. Op de dag staat wat er veranderd is, met de knop **Terug naar plan**.

**Waarom ziet een dag er zo uit?** Elke keer dat een geplande training verandert (weer, readiness, RPE, minder tijd, ruilen) wordt dat met de reden bewaard in `geschiedenis.jsonl`. Onder elke training staat *Waarom zo?* met de wijzigingen sinds het laatste nieuwe schema.

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

## Eigen workouts (.zwo)

Workouts die je zelf hebt, bijvoorbeeld geëxporteerd uit Zwift of een andere app, voeg je toe in **Bibliotheek → Eigen workouts**. Dat kan in bulk:

- meerdere .zwo-bestanden tegelijk kiezen;
- een hele map kiezen (op een computer);
- een of meer .zip-bestanden uploaden (submappen mogen; andere bestanden worden overgeslagen);
- of in de container, voor een map met bestanden:
  ```
  sudo -u fietscoach FIETSCOACH_CONFIG=/etc/fietscoach/config.yaml FIETSCOACH_DATA=/var/lib/fietscoach /opt/fietscoach/.venv/bin/python -m fietscoach.cli importeer /pad/naar/map
  ```

Elk bestand wordt gecontroleerd (geldige fietsworkout, geen XML-entities, max. 256 kB; een zip max. 1000 workouts en 64 MB uitgepakt). Dezelfde bestandsnaam opnieuw = bijwerken. De workout wordt automatisch ingedeeld op de tijd in elke zone: minstens 5 min boven 105% = VO2max, 10 min 95–105% = drempel, 10 min 88–95% = sweetspot, 15 min 76–88% = tempo, anders duur. Je eigen workouts staan ook bij hun soort in de bibliotheek (gemarkeerd als *eigen*). Per workout kun je de soort zelf kiezen (✎ = zelf gekozen); de knop **Alles automatisch indelen** past de regels opnieuw toe op alle eigen workouts en zet je eigen keuzes terug. In het schema doet een workout mee in de afwisseling van zijn soort, maar alleen op dagen waar hij past: niet langer dan je beschikbare tijd (+5 min) en niet korter dan 60% ervan.

De bestanden staan in `/var/lib/fietscoach/workouts`, bij je data en dus ook in de back-ups, maar **niet in de repo**: het zijn jouw bestanden, en zo verspreid je ze niet mee als de repo ooit openbaar wordt.

## Berichten op je telefoon

Elke ochtend na de ochtendronde (alleen op trainingsdagen) een bericht met de training, binnen of buiten, het weer in je rijtijd, wat er is bijgestuurd en voedingsadvies. Op zondag om 20:00 de weekterugblik. Tik op het bericht en de app opent.

Twee kanalen, kies er een of beide en zet ze in `/etc/fietscoach/config.yaml` onder `berichten:` (zie `config.example.yaml`):

- **ntfy**: installeer de ntfy-app, abonneer op een eigen, onraadbaar topic (bv. `fietscoach-8f3k2m9x`) en zet dat topic in de config. Met ntfy.sh is iedereen die het topic kent mee te lezen; wil je dat niet, gebruik dan een eigen ntfy-server met een token (kan in een eigen LXC).
- **Telegram**: maak een bot via @BotFather, stuur hem een bericht, en zoek je chat-id op via `https://api.telegram.org/bot<token>/getUpdates`.

Zet ook `app_url` op het adres van de app. Herstart daarna:

```
systemctl restart fietscoach
```

In **Instellingen → Berichten** zet je het ochtendbericht en de weekterugblik aan of uit en stuur je een testbericht.

## Als app op je telefoon

Open de app in Safari (iPhone: *Deel → Zet op beginscherm*) of Chrome (Android: *menu → App installeren*). Je krijgt een eigen icoon en een scherm zonder adresbalk. Zonder verbinding zie je de laatst geladen versie van elk scherm, met een melding; wijzigen kan dan niet. Dit werkt alleen via https (achter Caddy), niet via `http://<ip>:8766`.

## Verbinding met intervals.icu testen

In **Instellingen → Verbinding testen**, of in de container:

```
sudo -u fietscoach FIETSCOACH_CONFIG=/etc/fietscoach/config.yaml FIETSCOACH_DATA=/var/lib/fietscoach /opt/fietscoach/.venv/bin/python -m fietscoach.cli test
```

Alleen lezen. Je ziet per stap (atleet, wellness, ritten, kalender) of het lukt en welke velden binnenkomen; bij een fout de HTTP-code met uitleg (401 = sleutel klopt niet).

## Rooktest: werkt alles echt?

Na de installatie, en na een grote update:

```
sudo -u fietscoach FIETSCOACH_CONFIG=/etc/fietscoach/config.yaml FIETSCOACH_DATA=/var/lib/fietscoach /opt/fietscoach/.venv/bin/python -m fietscoach.cli rooktest --opname /tmp/fietscoach-opname
```

Controleert Python, Debian-versie, tijdzone, de datamap en de versie van de gegevens; leest bij intervals.icu en verwerkt je ritten zoals de ochtendronde doet; zet één **proeftraining** 330 dagen vooruit in je kalender (*Fietscoach rooktest (mag weg)*) om te zien of intervals.icu de trainingstekst begrijpt, en haalt hem meteen weer weg; en vraagt het weer voor morgen op bij Open-Meteo. Eindigt met ✓ of ✗ per stap.

Met `--opname` worden de antwoorden bewaard, met persoonlijke velden (naam, e-mail, locatie, id's, notities) vervangen door `<weg>`. Kijk ze na; in `tests/fixtures/echt/` draaien de tests er dan ook op.

## Bewaken met Uptime Kuma

`GET /health` geeft 200 als de laatste sync naar intervals.icu minder dan 36 uur oud is en foutloos ging, anders 503 met de reden. Maak in Uptime Kuma een HTTP-monitor op `http://<ip-lxc>:8766/health`.

## Ontwikkelen

- Tests: `pip install -r requirements.txt pytest` en `python -m pytest`. Per onderdeel een bestand in `tests/` (planner, bijsturen, bibliotheek, eigen, zwaarte, intervals, weer, web, opslag, rooktest); gedeelde nepdiensten in `tests/helpers.py`.
- Bij elke push in GitHub Actions: tests (Python 3.11 en 3.13), `ruff check` en shellcheck. Dependabot stelt eens per maand nieuwere versies voor.
- **Versie van de gegevens**: `versie.json` in de datamap. Verandert de vorm van de bestanden, dan verhoog je `SCHEMA` in `service.py` en voeg je een stap toe aan `MIGRATIES`; die draait vanzelf bij de volgende start. Zijn de gegevens nieuwer dan de code (na terugzetten van een oudere versie), dan weigert de app met een duidelijke melding in plaats van iets kapot te maken.
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
