"""Gedeelde gegevens en nepdiensten voor de tests."""
import base64
import io
import json as _json
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest  # noqa: F401  (herexport voor de testmodules)
import yaml

from fietscoach import adapt, bibliotheek, eigen, planner, service, workouts  # noqa: F401
from fietscoach.intervals import Intervals, eftp_uit, verbindingstest  # noqa: F401
from fietscoach.weather import Verwachting  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


VOORBEELD = yaml.safe_load((ROOT / "config.example.yaml").read_text())


CFG = {**VOORBEELD,
       "doel": {"type": "ftp", "startdatum": "2026-11-09", "weken": 12, "focus": "gemengd"},
       "week": {"ma": {"minuten": 0}, "di": {"minuten": 60}, "wo": {"minuten": 45},
                "do": {"minuten": 75}, "vr": {"minuten": 0},
                "za": {"minuten": 180, "buiten": True}, "zo": {"minuten": 90, "buiten": True}}}


STAP = re.compile(r"^- (\d+m)?(\d+s)? (ramp \d+-\d+%|\d+%)$")


class NepIntervals:
    def __init__(self, ritten, ctl=60, atl=95):
        self.ritten, self.ctl, self.atl = ritten, ctl, atl
        self.upserts, self.deleted = [], []
        self.bestaand = [{"id": 1, "external_id": "fietscoach-2026-11-30"}, {"id": 2, "external_id": "ander"}]

    def activiteiten(self, v, t):
        return [{"start_date_local": d + "T10:00:00", "type": "VirtualRide", "moving_time": 3600,
                 "icu_training_load": 60, "icu_intensity": 80} for d in self.ritten]

    def wellness(self, v, t):
        return [{"ctl": self.ctl, "atl": self.atl}]

    def ftp(self):
        return 270

    def upsert(self, ev):
        self.upserts += ev

    def events(self, v, t):
        return self.bestaand

    def verwijder_extern(self, ids):
        self.deleted += ids
        return len(ids)


def weer(start, slecht=()):
    out = {}
    for i in range(8):
        d = (start + timedelta(days=i)).isoformat()
        out[d] = {"temp_min": 5, "temp_max": 10, "neerslag_mm": 8 if d in slecht else 0,
                  "neerslagkans": 90 if d in slecht else 10, "wind_kmh": 20}
    return out


def _cfg(**doel):
    return {**VOORBEELD, "doel": {"type": "ftp", "startdatum": "2026-11-09", **doel}}




def _plan_wk1(vandaag, ritten=(), **kw):
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    ic = NepIntervals(ritten=list(ritten), ctl=60, atl=60)
    log = service.bijsturen(CFG | kw, vandaag, ic, weer(vandaag))
    return {s["datum"]: s for s in service.laad_plan()}, log



STAP_RPM = re.compile(r"^- ([A-Z][a-z]+ )?(\d+m)?(\d+s)? (ramp \d+-\d+%|\d+%|freeride)( \d+rpm)?$")





ATLEET = {"id": "i123", "name": "Test Rijder", "sportSettings": [
    {"types": ["Run"], "ftp": None}, {"types": ["Ride", "VirtualRide"], "ftp": 272}]}


WELLNESS = [{"id": "2026-11-09", "ctl": 51.2, "atl": 60.8, "eftp": 284.4, "restingHR": 52}]


RITTEN = [{"id": "i1", "start_date_local": "2026-11-08T09:12:00", "type": "Ride", "moving_time": 7236,
           "icu_training_load": 86, "icu_intensity": 65.5914, "icu_rpe": 3},
          {"id": "i2", "start_date_local": "2026-11-07T18:00:00", "type": "Run", "moving_time": 1800}]


class NepServer:
    def __init__(self, status=200):
        self.verzoeken, self.status = [], status

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.verzoeken.append(req)
        assert req.headers["authorization"] == "Basic " + base64.b64encode(b"API_KEY:geheim").decode()
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "nee"})
        pad = req.url.path
        if pad == "/api/v1/athlete/0":
            return httpx.Response(200, json=ATLEET)
        if pad.endswith("/wellness"):
            return httpx.Response(200, json=WELLNESS)
        if pad.endswith("/activities"):
            return httpx.Response(200, json=RITTEN)
        if pad.endswith("/events") and req.method == "GET":
            return httpx.Response(200, json=[{"id": 9, "external_id": "fietscoach-2026-11-10"}])
        if pad.endswith("/events/bulk"):
            assert req.url.params["upsert"] == "true"
            return httpx.Response(200, json=[{"id": 1} for _ in _json.loads(req.content)])
        if pad.endswith("/events/bulk-delete") and req.method == "PUT":
            return httpx.Response(200, json=len(_json.loads(req.content)))
        return httpx.Response(404)


def _client(server):
    return Intervals("0", "geheim", transport=httpx.MockTransport(server))




def _uren(datum, regen_uren=(), vorst_uren=(), wind=20):
    uur = {}
    for h in range(24):
        uur[f"{datum}T{h:02d}:00"] = {"temp": -2 if h in vorst_uren else 8, "neerslag": 3.0 if h in regen_uren else 0.0,
                                      "kans": 90 if h in regen_uren else 10, "wind": wind}
    return uur


class RittenNep(NepIntervals):
    def __init__(self, acts, wellness=None):
        super().__init__([], 60, 60)
        self.acts, self.well = acts, wellness

    def activiteiten(self, v, t):
        return self.acts

    def wellness(self, v, t):
        return self.well if self.well is not None else super().wellness(v, t)


def _rit(d, minuten, gepaard=False):
    return {"start_date_local": d + "T08:00:00", "type": "Ride", "moving_time": minuten * 60,
            "icu_training_load": minuten, **({"paired_event_id": 77} if gepaard else {})}


def _vorm(soort, naam_begin, minuten=75, p=1.0):
    for v in range(1, bibliotheek.aantal(soort)):
        t = workouts.bouw(soort, minuten, p, "opbouw", v)
        if t.naam.startswith(naam_begin):
            return t
    raise AssertionError(f"{naam_begin} niet gevonden")




def _zwo(naam, stappen, auteur="Test", sport="bike"):
    return (f'<workout_file><author>{auteur}</author><name>{naam}</name>'
            f'<description>Testworkout - 3x hard. Rustig beginnen.</description><sportType>{sport}</sportType>'
            f'<workout>{stappen}</workout></workout_file>').encode()


VO2_ZWO = _zwo("Test VO2", '<Warmup Duration="600.0001" PowerLow="0.5" PowerHigh="0.75" pace="0"/>'
               '<SteadyState Duration="120" Power="0.6" Cadence="95"/>'
               '<IntervalsT Repeat="6" OnDuration="120" OffDuration="120" OnPower="1.12" OffPower="0.5" Cadence="100" CadenceResting="85"/>'
               '<FreeRide Duration="300" FlatRoad="1"/><MaxEffort Duration="20"/>'
               '<Ramp Duration="60" PowerLow="0.6" PowerHigh="1.2"/><Cooldown Duration="480" PowerLow="0.6" PowerHigh="0.4"/>'
               '<textevent timeoffset="0" message="hoi"/><Onbekend Duration="10"/>')


DUUR_ZWO = _zwo("Test duur", '<Warmup Duration="300" PowerLow="0.5" PowerHigh="0.65"/><SteadyState Duration="2400" Power="0.7"/>'
                '<Cooldown Duration="300" PowerLow="0.6" PowerHigh="0.45"/>')


DREMPEL_ZWO = _zwo("Test drempel", '<Warmup Duration="600" PowerLow="0.5" PowerHigh="0.75"/>'
                   '<IntervalsT Repeat="3" OnDuration="600" OffDuration="180" OnPower="0.98" OffPower="0.55"/>'
                   '<Cooldown Duration="360" PowerLow="0.6" PowerHigh="0.45"/>')


def _zip(bestanden):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for naam, data in bestanden:
            z.writestr(naam, data)
    return buf.getvalue()


def _vast(*stappen):
    return workouts.Training("x", "x", [workouts.Blok(None, [workouts.Stap(m, p) for m, p in stappen])])


class Kalender(NepServer):
    """intervals.icu met een echte kalender in het geheugen (upsert, lijst, bulk-delete)."""
    def __init__(self):
        super().__init__()
        self.events, self.volgnr = {}, 100

    def __call__(self, req):
        pad = req.url.path
        if pad.endswith("/events") and req.method == "GET":
            return httpx.Response(200, json=list(self.events.values()))
        if pad.endswith("/events/bulk"):
            for e in _json.loads(req.content):
                bestaand = self.events.get(e["external_id"])
                self.volgnr += 1
                self.events[e["external_id"]] = {**e, "id": bestaand["id"] if bestaand else self.volgnr}
            return httpx.Response(200, json=[])
        if pad.endswith("/bulk-delete"):
            n = 0
            for x in _json.loads(req.content):
                n += self.events.pop(x["external_id"], None) is not None
            return httpx.Response(200, json=n)
        return super().__call__(req)


def _zw(s):
    return workouts.zwaarte(planner.training_voor(s))["score"]


class ProefKalender(Kalender):
    """Zoals intervals.icu: leest stappen uit de tekst en rekent een belasting uit."""
    def __call__(self, req):
        r = super().__call__(req)
        if req.url.path.endswith("/events/bulk"):
            for e in self.events.values():
                stappen = [x for x in e["description"].splitlines() if x.startswith("-")]
                e.update(workout_doc={"steps": [{} for _ in stappen]}, icu_training_load=55)
        return r


def _openmeteo(req_dagen=3):
    dagen = [(date.today() + timedelta(days=i)).isoformat() for i in range(req_dagen)]
    uren = [f"{d}T{h:02d}:00" for d in dagen for h in range(24)]
    return {"latitude": 52.38, "longitude": 4.64,
            "daily": {"time": dagen, "temperature_2m_min": [4] * 3, "temperature_2m_max": [11] * 3,
                      "precipitation_sum": [0] * 3, "precipitation_probability_max": [10] * 3,
                      "wind_speed_10m_max": [18] * 3},
            "hourly": {"time": uren, "temperature_2m": [8] * len(uren), "precipitation": [0] * len(uren),
                       "precipitation_probability": [5] * len(uren), "wind_speed_10m": [12] * len(uren)}}


ECHT = Path(__file__).parent / "fixtures" / "echt"


__all__ = [n for n in dir() if not n.startswith('__')]
