"""Client voor de intervals.icu API.

Gecontroleerd tegen de openbare documentatie (forum.intervals.icu: 'API access',
'Uploading planned workouts', 'API Integration Cookbook'):
  - Basic auth met gebruikersnaam API_KEY; athlete-id 0 = eigenaar van de sleutel
  - POST /athlete/{id}/events/bulk?upsert=true   upsert op external_id
  - PUT  /athlete/{id}/events/bulk-delete        [{"external_id": ...}], onbekende worden genegeerd
  - Activiteit: moving_time (s), icu_training_load, icu_intensity (in procenten), icu_rpe
  - Wellness: ctl, atl, eftp (los veld; oudere voorbeelden noemen sportInfo)
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx

BASE = "https://intervals.icu/api/v1"
PREFIX = "fietscoach-"


class Intervals:
    def __init__(self, athlete_id: str, api_key: str, transport: httpx.BaseTransport | None = None):
        self.aid = athlete_id or "0"
        self.c = httpx.Client(base_url=BASE, auth=("API_KEY", api_key), timeout=30,
                              transport=transport, headers={"User-Agent": "fietscoach"})

    def _get(self, pad: str, **params):
        r = self.c.get(f"/athlete/{self.aid}{pad}", params=params)
        r.raise_for_status()
        return r.json()

    def atleet(self) -> dict:
        return self._get("")

    def ftp(self) -> int | None:
        for s in self.atleet().get("sportSettings", []) or []:
            if "Ride" in (s.get("types") or []):
                return s.get("ftp")
        return None

    def wellness(self, van: date, tot: date) -> list[dict]:
        return self._get("/wellness", oldest=van.isoformat(), newest=tot.isoformat())

    def activiteiten(self, van: date, tot: date) -> list[dict]:
        return self._get("/activities", oldest=van.isoformat(), newest=tot.isoformat())

    def events(self, van: date, tot: date) -> list[dict]:
        return self._get("/events", oldest=van.isoformat(), newest=tot.isoformat())

    def upsert(self, events: list[dict]) -> list[dict]:
        r = self.c.post(f"/athlete/{self.aid}/events/bulk", params={"upsert": "true"}, json=events)
        r.raise_for_status()
        return r.json()

    def verwijder_extern(self, external_ids: list[str]) -> int:
        """Verwijder events op ons eigen id; ids die niet bestaan worden genegeerd."""
        if not external_ids:
            return 0
        r = self.c.put(f"/athlete/{self.aid}/events/bulk-delete",
                       json=[{"external_id": e} for e in external_ids])
        r.raise_for_status()
        try:
            return int(r.json())
        except (ValueError, TypeError):
            return 0


def eftp_uit(wellness: dict) -> int | None:
    """eFTP staat als los veld in wellness; val terug op sportInfo (oudere vorm)."""
    if wellness.get("eftp"):
        return round(wellness["eftp"])
    for sp in wellness.get("sportInfo") or []:
        if sp.get("type") == "Ride" and sp.get("eftp"):
            return round(sp["eftp"])
    return None


def naar_event(s: dict) -> dict:
    return {
        "category": "WORKOUT",
        "start_date_local": f"{s['datum']}T00:00:00",
        "type": "Ride" if s["omgeving"] == "buiten" else "VirtualRide",
        "name": s["naam"],
        "description": s["beschrijving"],
        "external_id": PREFIX + s["datum"],
    }


def verbindingstest(ic: Intervals, vandaag: date | None = None) -> list[tuple[bool, str]]:
    """Alleen lezen. Geeft per stap (gelukt, uitleg) terug."""
    vandaag = vandaag or date.today()
    uit: list[tuple[bool, str]] = []

    def stap(naam, f):
        try:
            uit.append((True, f"{naam}: {f()}"))
            return True
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            hint = {401: "sleutel klopt niet", 403: "geen toegang (verkeerd athlete-id?)",
                    404: "niet gevonden (verkeerd athlete-id?)"}.get(code, "")
            uit.append((False, f"{naam}: HTTP {code} {hint}".rstrip()))
        except httpx.HTTPError as e:
            uit.append((False, f"{naam}: geen verbinding ({e.__class__.__name__})"))
        return False

    def atleet():
        a = ic.atleet()
        ftp = next((s.get("ftp") for s in a.get("sportSettings") or [] if "Ride" in (s.get("types") or [])), None)
        return f"{a.get('name') or a.get('id')}, FTP fiets {ftp or 'niet ingesteld'}"

    def well():
        w = [x for x in ic.wellness(vandaag - timedelta(days=3), vandaag) if x.get("ctl") is not None]
        if not w:
            return "geen fitheidsgegevens in de laatste dagen"
        x = w[-1]
        return f"fitheid {x['ctl']:.0f}, vermoeidheid {x['atl']:.0f}, eFTP {eftp_uit(x) or 'onbekend'}"

    def acts():
        a = [x for x in ic.activiteiten(vandaag - timedelta(days=28), vandaag) if "Ride" in (x.get("type") or "")]
        if not a:
            return "geen fietsritten in 28 dagen"
        x = a[-1]
        velden = [v for v in ("moving_time", "icu_training_load", "icu_intensity", "icu_rpe") if x.get(v) is not None]
        return f"{len(a)} ritten; laatste heeft {', '.join(velden) or 'geen bruikbare velden'}"

    def evs():
        e = ic.events(vandaag, vandaag + timedelta(days=14))
        eigen = sum(1 for x in e if str(x.get("external_id") or "").startswith(PREFIX))
        return f"{len(e)} in de kalender, waarvan {eigen} van Fietscoach"

    if stap("Atleet", atleet):
        stap("Wellness", well)
        stap("Ritten", acts)
        stap("Kalender", evs)
    return uit
