"""Rooktest: werkt alles écht, in deze container, met de echte diensten?

Leest bij intervals.icu en Open-Meteo, en zet één proeftraining ver in de toekomst in
je kalender die meteen weer verdwijnt. Zo zie je of intervals.icu onze trainingstekst
begrijpt. Met een opnamemap worden de antwoorden (zonder persoonlijke gegevens)
bewaard, zodat de tests met echte antwoorden kunnen draaien.
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import adapt, intervals, planner, service, weather

PROEF_ID = intervals.PREFIX + "rooktest"

# Sleutels waarvan de waarde persoonlijk is of iets over je zegt.
GEHEIM = re.compile(
    r"^(e?mail|name|firstname|lastname|bio|city|state|country|timezone|locale|sex|dob|"
    r"lat|lng|lon|latitude|longitude|start_latlng|end_latlng|latlng|polyline|map|"
    r"profile.*|avatar.*|.*strava.*|.*garmin.*|.*_token|api_key|gear|device_name|"
    r"icu_athlete_id|athlete_id|external_id|oauth.*|password|url|.*_url|weight|icu_weight|"
    r"height|description|notes?|comments?|plan_.*|workout_filename)$", re.I)


def anoniem(x, sleutel: str = ""):
    """Persoonlijke velden vervangen; structuur en getallen voor de training blijven."""
    if isinstance(x, dict):
        return {k: ("<weg>" if GEHEIM.match(k) and v not in (None, "", [], {}) else anoniem(v, k))
                for k, v in x.items()}
    if isinstance(x, list):
        return [anoniem(v, sleutel) for v in x[:15]]
    if isinstance(x, str):
        return re.sub(r"\bi\d{3,}\b", "i0", x)
    return x


def _neem_op(map_: Path | None):
    if not map_:
        return None
    map_.mkdir(parents=True, exist_ok=True)

    def schrijf(naam: str, j) -> None:
        naam = re.sub(r"[^a-z0-9_-]+", "_", naam.lower()).strip("_") or "antwoord"
        (map_ / f"{naam}.json").write_text(json.dumps(anoniem(j), ensure_ascii=False, indent=1), encoding="utf-8")
    return schrijf


def _systeem() -> list[tuple[bool, str]]:
    uit = []
    distro = "onbekend"
    try:
        for regel in Path("/etc/os-release").read_text().splitlines():
            if regel.startswith("PRETTY_NAME="):
                distro = regel.split("=", 1)[1].strip('"')
    except OSError:
        pass
    uit.append((sys.version_info >= (3, 11), f"Python {platform.python_version()} op {distro}"))
    tz = os.environ.get("TZ") or time.tzname[0]
    offset = datetime.now().astimezone().utcoffset()
    uit.append((offset in (timedelta(hours=1), timedelta(hours=2)),
                f"Tijdzone {tz} (UTC{offset.total_seconds() / 3600:+.0f})"))
    try:
        service.DATA.mkdir(parents=True, exist_ok=True)
        p = service.DATA / ".rooktest"
        p.write_text("ok")
        p.unlink()
        uit.append((True, f"Datamap {service.DATA.resolve()} is schrijfbaar"))
    except OSError as e:
        uit.append((False, f"Datamap {service.DATA}: {e}"))
    try:
        log = service.migreer()
        uit.append((True, f"Gegevens schema {service.gegevensversie()}" + (f" ({'; '.join(log)})" if log else "")))
    except Exception as e:  # noqa: BLE001
        uit.append((False, f"Gegevens: {e}"))
    return uit


def _intervals(cfg: dict, opname, vandaag: date) -> list[tuple[bool, str]]:
    ic = service.client(cfg)
    if not ic:
        return [(False, "intervals.icu: geen API-sleutel in de config")]
    ic.opname = opname
    uit = intervals.verbindingstest(ic, vandaag)
    if not all(ok for ok, _ in uit):
        return uit

    # Dezelfde verwerking als de ochtendronde, op echte gegevens.
    try:
        ritten = adapt.ritten_per_dag(ic.activiteiten(vandaag - timedelta(days=28), vandaag))
        gepaard = sum(1 for r in ritten.values() if r.get("gepaard"))
        uit.append((True, f"Ritten verwerkt: {len(ritten)} dagen, {gepaard} gekoppeld aan een geplande training"))
    except Exception as e:  # noqa: BLE001
        uit.append((False, f"Ritten verwerken: {e.__class__.__name__}: {e}"))

    # Proeftraining: begrijpt intervals.icu onze tekst? Ver weg en meteen weer weg.
    proefdag = (vandaag + timedelta(days=330)).isoformat()
    t = planner.workouts.bouw("sweetspot", 60, 0.5, "opbouw")
    ev = intervals.naar_event({"datum": proefdag, "omgeving": "binnen",
                               "naam": "Fietscoach rooktest (mag weg)", "beschrijving": t.beschrijving()})
    ev["external_id"] = PROEF_ID
    try:
        ic.upsert([ev])
        terug = [e for e in ic.events(date.fromisoformat(proefdag), date.fromisoformat(proefdag))
                 if e.get("external_id") == PROEF_ID]
        if not terug:
            uit.append((False, "Proeftraining: geplaatst maar niet teruggevonden"))
        else:
            e = terug[0]
            if opname:
                opname("event_proef", e)
            stappen = len((e.get("workout_doc") or {}).get("steps") or [])
            last = e.get("icu_training_load")
            verwacht = round(planner.workouts.zwaarte(t)["tss"])
            ok = stappen > 0 and bool(last)
            uit.append((ok, f"Proeftraining begrepen: {stappen} blokken, belasting {last or '?'} "
                            f"(wij rekenen {verwacht})" if ok else
                            "Proeftraining: intervals.icu las geen stappen uit de tekst"))
    except Exception as e:  # noqa: BLE001
        uit.append((False, f"Proeftraining plaatsen: {e.__class__.__name__}: {e}"))
    finally:
        try:
            ic.verwijder_extern([PROEF_ID])
            weg = not [e for e in ic.events(date.fromisoformat(proefdag), date.fromisoformat(proefdag))
                       if e.get("external_id") == PROEF_ID]
            uit.append((weg, "Proeftraining weer verwijderd" if weg else
                        f"Proeftraining staat nog op {proefdag}; verwijder hem met de hand"))
        except Exception as e:  # noqa: BLE001
            uit.append((False, f"Proeftraining verwijderen: {e}; staat op {proefdag}"))
    return uit


def _weer(cfg: dict, opname, vandaag: date) -> list[tuple[bool, str]]:
    import httpx
    loc = cfg.get("locatie") or {}
    if "lat" not in loc:
        return [(False, "Weer: geen locatie in de config")]
    try:
        r = httpx.get(weather.URL, timeout=20, params={
            "latitude": loc["lat"], "longitude": loc["lon"], "timezone": "Europe/Amsterdam", "forecast_days": 3,
            "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum,"
                     "precipitation_probability_max,wind_speed_10m_max",
            "hourly": "temperature_2m,precipitation,precipitation_probability,wind_speed_10m"})
        r.raise_for_status()
        j = r.json()
        if opname:
            opname("openmeteo", j | {"latitude": 52.0, "longitude": 5.0})
        v = weather.uit_json(j)
        morgen = (vandaag + timedelta(days=1)).isoformat()
        w = v.venster(morgen, service.starttijd(cfg.get("week") or {}, morgen), 90)
        if not w:
            return [(False, "Weer: geen uurverwachting voor morgen")]
        return [(True, f"Weer morgen tijdens je rit: {w['temp_min']:.0f}–{w['temp_max']:.0f} °C, "
                       f"wind {w['wind_kmh']:.0f} km/u, kans op regen {w['neerslagkans']}%")]
    except Exception as e:  # noqa: BLE001
        return [(False, f"Weer (Open-Meteo): {e.__class__.__name__}: {e}")]


def rooktest(cfg: dict, opnamemap: Path | None = None, vandaag: date | None = None) -> list[tuple[bool, str]]:
    vandaag = vandaag or date.today()
    opname = _neem_op(opnamemap)
    return _systeem() + _intervals(cfg, opname, vandaag) + _weer(cfg, opname, vandaag)
