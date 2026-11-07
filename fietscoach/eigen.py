"""Eigen workouts: .zwo-bestanden die je zelf toevoegt (bv. geëxporteerd uit Zwift
of een andere app). Ze staan in de datamap (/var/lib/fietscoach/workouts), niet
in de repo: het zijn jouw bestanden, en zo verspreid je ze niet mee als de repo
ooit openbaar wordt.

Elk bestand wordt omgezet naar dezelfde Training-vorm als de eigen bibliotheek,
dus ook naar intervals.icu-tekst en terug naar .zwo. Het wordt automatisch
ingedeeld bij een trainingssoort (duur, tempo, sweetspot, drempel, VO2max) op
basis van hoeveel tijd je in welke zone zit, en doet mee in de afwisseling van
het schema als het in de beschikbare tijd van die dag past.
"""
from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .workouts import Blok, Stap, Training

MAX_BYTES = 256 * 1024            # per workout
MAX_ZIP_BESTANDEN = 1000          # per .zip
MAX_ZIP_TOTAAL = 64 * 1024 * 1024  # uitgepakt, per .zip (tegen zip-bommen)
ZONES = [("vo2max", 105, 5), ("drempel", 95, 10), ("sweetspot", 88, 10), ("tempo", 76, 15)]
SOORTEN = ("herstel", "duur", "tempo", "sweetspot", "drempel", "vo2max")  # waar je zelf uit kunt kiezen
INDELING = "indeling.json"  # handmatige keuzes per workout

# Wordt door service gezet; een functie zodat tests de datamap kunnen wisselen.
map_bron: Callable[[], Path] | None = None


class OngeldigBestand(ValueError):
    pass


@dataclass
class EigenWorkout:
    id: str            # bestandsnaam zonder .zwo
    naam: str
    auteur: str
    soort: str         # waar hij in het schema meedoet
    training: Training
    auto: str = ""     # wat de automatische indeling zegt
    handmatig: bool = False

    @property
    def minuten(self) -> float:
        return self.training.minuten


def _sec(e: ET.Element, attr: str = "Duration") -> float:
    try:
        return max(0.0, round(float(e.get(attr) or 0)))
    except ValueError:
        return 0.0


def _pct(e: ET.Element, attr: str) -> int:
    try:
        return max(0, round(float(e.get(attr) or 0) * 100))
    except ValueError:
        return 0


def _rpm(e: ET.Element, attr: str = "Cadence") -> int | None:
    try:
        v = round(float(e.get(attr))) if e.get(attr) else None
    except ValueError:
        return None
    return v if v and 30 <= v <= 160 else None


def _schoon(tekst: str, lengte: int = 400) -> str:
    """Eén regel, zonder iets dat intervals.icu als stap of herhaling zou lezen."""
    t = re.sub(r"\s+", " ", tekst or "").strip()
    t = re.sub(r"(^|\s)-(?=\s|\d)", r"\1–", t)
    return t[:lengte]


def lees_zwo(data: bytes, bestandsnaam: str = "") -> tuple[Training, dict]:
    """.zwo → Training. Weigert bestanden die geen workout zijn of XML-entities
    gebruiken (bescherming tegen 'billion laughs' en het inlezen van bestanden)."""
    if len(data) > MAX_BYTES:
        raise OngeldigBestand("bestand is te groot voor een workout")
    kop = data[:2048].lower()
    if b"<!doctype" in kop or b"<!entity" in data.lower():
        raise OngeldigBestand("bestand bevat een DOCTYPE of ENTITY; die accepteer ik niet")
    try:
        wortel = ET.fromstring(data)
    except ET.ParseError as e:
        raise OngeldigBestand(f"geen geldige XML ({e})") from None
    if wortel.tag != "workout_file" or wortel.find("workout") is None:
        raise OngeldigBestand("geen Zwift-workout (workout_file met workout ontbreekt)")
    if (wortel.findtext("sportType") or "bike").strip().lower() not in ("bike", ""):
        raise OngeldigBestand("geen fietsworkout")

    blokken: list[Blok] = []
    losse: list[Stap] = []

    def sluit():
        if losse:
            blokken.append(Blok(None, list(losse)))
            losse.clear()

    onbekend = set()
    for e in wortel.find("workout"):
        sec = _sec(e)
        if e.tag in ("Warmup", "Cooldown", "Ramp"):
            if sec:
                lo, hi = _pct(e, "PowerLow"), _pct(e, "PowerHigh")
                losse.append(Stap(sec / 60, (lo, hi) if lo != hi else lo, _rpm(e)))
        elif e.tag == "SteadyState":
            if sec:
                losse.append(Stap(sec / 60, _pct(e, "Power"), _rpm(e)))
        elif e.tag == "FreeRide":
            if sec:
                losse.append(Stap(sec / 60, 60, _rpm(e), vrij=True))
        elif e.tag == "MaxEffort":
            if sec:
                losse.append(Stap(sec / 60, 150, vrij=True, cue="Voluit"))
        elif e.tag == "IntervalsT":
            aan, uit = _sec(e, "OnDuration"), _sec(e, "OffDuration")
            herh = int(float(e.get("Repeat") or 1))
            if aan and herh > 0:
                sluit()
                stappen = [Stap(aan / 60, _pct(e, "OnPower"), _rpm(e))]
                if uit:
                    stappen.append(Stap(uit / 60, _pct(e, "OffPower"), _rpm(e, "CadenceResting")))
                blokken.append(Blok("Intervallen", stappen, herh))
        elif e.tag.lower() != "textevent":  # tekstmeldingen negeren we bewust
            onbekend.add(e.tag)
    sluit()
    if not blokken:
        raise OngeldigBestand("geen stappen gevonden die ik ken")
    meta = {
        "naam": _schoon(wortel.findtext("name") or Path(bestandsnaam).stem or "Eigen workout", 80),
        "auteur": _schoon(wortel.findtext("author") or "", 80),
        "beschrijving": _schoon(wortel.findtext("description") or ""),
        "onbekend": sorted(onbekend),
    }
    toel = meta["beschrijving"] or "Eigen workout."
    if meta["auteur"]:
        toel += f" (Auteur: {meta['auteur']}.)"
    return Training("eigen", meta["naam"], blokken, toel), meta


def tijd_per_zone(t: Training) -> dict[str, float]:
    """Minuten boven elke zonegrens. Vrije stappen (ERG uit) tellen alleen als ze
    kort en hard bedoeld zijn: anders zijn het warming-up of herstel."""
    uit = {z: 0.0 for z, _, _ in ZONES}
    for b in t.blokken:
        for _ in range(b.herhalingen):
            for s in b.stappen:
                pct = sum(s.pct) / 2 if isinstance(s.pct, tuple) else s.pct
                if s.vrij and not s.cue:
                    continue
                for z, grens, _ in ZONES:
                    if pct >= grens:
                        uit[z] += s.minuten
                        break
    return uit


def indeling(t: Training) -> str:
    """Zwaarste zone waarin je genoeg tijd doorbrengt: ≥5 min boven 105%, ≥10 min
    95–105%, ≥10 min 88–95%, ≥15 min 76–88%; anders duur."""
    tijden = tijd_per_zone(t)
    for z, _, minimaal in ZONES:
        if tijden[z] >= minimaal:
            return z
    return "duur"


def _map() -> Path | None:
    return map_bron() if map_bron else None


_cache: dict = {"sleutel": None, "lijst": []}


def _handmatig() -> dict[str, str]:
    m = _map()
    p = m / INDELING if m else None
    if not p or not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return {k: v for k, v in d.items() if v in SOORTEN} if isinstance(d, dict) else {}


def _bewaar_handmatig(d: dict[str, str]) -> None:
    m = _map()
    if not m:
        return
    m.mkdir(parents=True, exist_ok=True)
    p = m / INDELING
    if d:
        p.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
    elif p.exists():
        p.unlink()


def alle() -> list[EigenWorkout]:
    m = _map()
    if not m or not m.is_dir():
        return []
    bestanden = sorted(m.glob("*.zwo"))
    keuzes = m / INDELING
    sleutel = (str(m), keuzes.stat().st_mtime_ns if keuzes.exists() else 0) + tuple(
        (p.name, p.stat().st_mtime_ns) for p in bestanden)
    if _cache["sleutel"] == sleutel:
        return _cache["lijst"]
    handmatig = _handmatig()
    lijst = []
    for p in bestanden:
        try:
            t, meta = lees_zwo(p.read_bytes(), p.name)
        except (OngeldigBestand, OSError):
            continue
        auto = indeling(t)
        soort = handmatig.get(p.stem, auto)
        t.soort = soort
        t.extra["eigen"] = p.stem
        lijst.append(EigenWorkout(p.stem, meta["naam"], meta["auteur"], soort, t, auto, p.stem in handmatig))
    _cache.update(sleutel=sleutel, lijst=lijst)
    return lijst


def zet_soort(id_: str, soort: str | None) -> bool:
    """Handmatige soort voor één workout; None of 'auto' = terug naar automatisch."""
    if not any(w.id == id_ for w in alle()):
        return False
    d = _handmatig()
    if soort in SOORTEN:
        d[id_] = soort
    else:
        d.pop(id_, None)
    _bewaar_handmatig(d)
    return True


def alles_automatisch() -> dict[str, int]:
    """De knop: alle handmatige keuzes weg, iedere workout opnieuw automatisch ingedeeld.
    Geeft het aantal per soort terug."""
    _bewaar_handmatig({})
    _cache["sleutel"] = None
    telling: dict[str, int] = {}
    for w in alle():
        telling[w.soort] = telling.get(w.soort, 0) + 1
    return telling


def voor_soort(soort: str) -> list[EigenWorkout]:
    return [w for w in alle() if w.soort == soort]


def kies(soort: str, minuten: int, start: int) -> Training | None:
    """Eigen workout voor deze soort die past: niet langer dan de beschikbare tijd
    (+5 min speling) en niet korter dan 60% ervan. Begint bij 'start' en roteert."""
    lijst = voor_soort(soort)
    for i in range(len(lijst)):
        w = lijst[(start + i) % len(lijst)]
        if 0.6 * minuten <= w.minuten <= minuten + 5:
            return Training(soort, w.naam, w.training.blokken, w.training.toelichting, {"eigen": w.id})
    return None


def veilige_naam(bestandsnaam: str) -> str:
    stam = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(bestandsnaam).stem).strip("._")[:60]
    return (stam or "workout") + ".zwo"


def bewaar(data: bytes, bestandsnaam: str) -> EigenWorkout:
    """Controleer en bewaar een geüpload bestand. Gooit OngeldigBestand bij onzin."""
    t, meta = lees_zwo(data, bestandsnaam)
    m = _map()
    if not m:
        raise OngeldigBestand("geen map voor eigen workouts ingesteld")
    m.mkdir(parents=True, exist_ok=True)
    doel = m / veilige_naam(bestandsnaam)
    doel.write_bytes(data)
    return EigenWorkout(doel.stem, meta["naam"], meta["auteur"], indeling(t), t)


def _uit_zip(data: bytes, zipnaam: str):
    """(naam, inhoud) van elke .zwo in een zip, waar die ook in de mappen staat."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise OngeldigBestand("geen geldig zip-bestand") from None
    leden = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(".zwo")
             and not Path(i.filename).name.startswith(("._", "."))]  # macOS-rommel overslaan
    if len(leden) > MAX_ZIP_BESTANDEN:
        raise OngeldigBestand(f"meer dan {MAX_ZIP_BESTANDEN} workouts in één zip")
    if sum(i.file_size for i in leden) > MAX_ZIP_TOTAAL:
        raise OngeldigBestand("zip pakt uit tot meer dan 64 MB; zo groot zijn workouts niet")
    for i in leden:
        if i.file_size > MAX_BYTES:
            yield Path(i.filename).name, None  # te groot: wordt hieronder gemeld
            continue
        yield Path(i.filename).name, z.read(i)


def importeer(bestanden) -> tuple[list[str], list[str]]:
    """Bulkimport. bestanden: (naam, inhoud) van .zwo- en .zip-bestanden. Andere
    bestanden (zoals uit een gekozen map) worden stil overgeslagen.
    Geeft (gelukt, mislukt) terug als leesbare regels."""
    gelukt, mislukt = [], []
    bestaand = {w.id for w in alle()}

    def een(naam: str, data: bytes | None):
        if data is None:
            mislukt.append(f"{naam}: bestand is te groot voor een workout")
            return
        try:
            w = bewaar(data, naam)
        except OngeldigBestand as e:
            mislukt.append(f"{naam}: {e}")
            return
        nieuw = "bijgewerkt" if w.id in bestaand else "nieuw"
        bestaand.add(w.id)
        gelukt.append(f"{w.naam} ({w.soort}, {round(w.minuten)} min, {nieuw})")

    for naam, data in bestanden:
        laag = naam.lower()
        if laag.endswith(".zip"):
            try:
                for n, d in _uit_zip(data, naam):
                    een(n, d)
            except OngeldigBestand as e:
                mislukt.append(f"{naam}: {e}")
        elif laag.endswith(".zwo"):
            een(Path(naam).name, data if len(data) <= MAX_BYTES else None)
    return gelukt, mislukt


def verwijder_alle() -> int:
    m = _map()
    if not m or not m.is_dir():
        return 0
    n = 0
    for p in m.glob("*.zwo"):
        p.unlink()
        n += 1
    _bewaar_handmatig({})
    return n


def verwijder(id_: str) -> bool:
    m = _map()
    if not m or not re.fullmatch(r"[A-Za-z0-9._-]+", id_):
        return False
    p = m / f"{id_}.zwo"
    if p.is_file():
        p.unlink()
        d = _handmatig()
        if d.pop(id_, None):
            _bewaar_handmatig(d)
        return True
    return False
