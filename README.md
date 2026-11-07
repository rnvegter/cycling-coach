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
- **Focus per blok**: `gemengd`, `sweetspot` (3×10 → 2×20 min), `zone2` of `gepolariseerd`. Elke vierde week herstel met een ramp-test.
- **Afwisseling**: elke week een andere vorm van dezelfde soort, bv. sweetspot als blokken, met uitschieters, als ladder of op wisselende cadans; drempel als over-unders, piramide of met harde start; VO2max als 30/15's, 40/20's of piramide; duurritten met spin-ups, sprints of krachtblokjes. Uit te zetten in Instellingen. Alles in % FTP, met cadansdoelen waar dat hoort (ook in de .zwo).
- **RPE na elke rit** (1–10): voelde een soort training zwaarder dan bedoeld, dan wordt de volgende van die soort lichter, en andersom. Heb je de RPE al in intervals.icu gegeven, dan wordt die overgenomen.
- **Readiness** (benen en energie, 1–5): bij 3 of lager wordt vandaag lichter; bij 2 of lager ook morgen.
- **Andere tijd op een dag**: geen tijd → een intervaltraining of lange rit schuift naar een andere dag in die week; meer tijd → langere duurrit; een normaal vrije dag met tijd krijgt een extra duurrit.
- **Ongeplande zware rit** (clubrit, tocht: ≥ 2 uur, load ≥ 80 of RPE ≥ 8) → de dag erna wordt herstel.
- **Gemiste intervaltraining** → naar een latere duurdag in dezelfde week.
- **Vorm** (fitheid − vermoeidheid) onder −20 of −30 → de komende week korter.
- **Weer** (Open-Meteo): regen, harde wind of vorst → naar Zwift; de lange rit eerst naar een droge dag.
- **Trainingsscore** na elke rit: duur en intensiteit (gepland tegenover gereden), elk 0–100.
- **eFTP** uit intervals.icu, met een seintje als die duidelijk boven je FTP ligt.
- **.zwo-download** per training, als reserve voor Zwift.

Elke ochtend om 05:30 en na elke invoer in het scherm: bijsturen en de komende 14 dagen naar intervals.icu (type *Ride* = buiten/Wahoo, *VirtualRide* = Zwift).

## Installatie

De broncode staat in een eigen GitHub-repo (standaard `rnvegter/cycling-coach`). Is die privé, dan maakt het installatiescript een *deploy key* (alleen lezen) en vraagt je die één keer in GitHub toe te voegen. Een token is niet nodig.

### Snelste weg: alles vanaf de Proxmox-host

Zet `deploy/install.sh` en `deploy/proxmox-create.sh` samen in één map op de host (bv. met `scp` of door de repo daar te clonen) en draai:

```
bash proxmox-create.sh
```

Dit maakt een Debian 12-LXC (1 core, 512 MB, 4 GB, DHCP op `vmbr0`), installeert alles en vraagt om je API-sleutel van intervals.icu. Instelbaar met omgevingsvariabelen, bijvoorbeeld een vast IP:

```
IP=192.168.0.217/24 GW=192.168.0.1 bash proxmox-create.sh
```

Andere opties: `CTID`, `HOSTNAME_CT`, `STORAGE`, `BRIDGE`, `REPO`, `BRANCH`, `INTERVALS_API_KEY`.

### Of: in een bestaande container

In een Debian 12-LXC, als root:

```
bash install.sh
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

## Bijwerken

Push je wijzigingen naar GitHub en draai in de container:

```
fietscoach-update
```

Of vanaf de Proxmox-host:

```
pct exec <CTID> -- fietscoach-update
```

Het script laat zien welke commits er nieuw zijn en kopieert eerst je data en config naar `/var/backups/fietscoach`. Daarna zet het de nieuwe code neer, werkt pakketten en systemd-units bij en herstart de app. Reageert de nieuwe versie niet binnen 20 seconden, dan gaat hij automatisch terug naar de vorige versie en meldt het script een fout. Je data wordt daarbij niet aangeraakt.

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
