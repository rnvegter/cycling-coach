import re
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from fietscoach import planner, service, workouts

ROOT = Path(__file__).resolve().parents[1]
VOORBEELD = yaml.safe_load((ROOT / "config.example.yaml").read_text())
CFG = {**VOORBEELD,
       "doel": {"type": "ftp", "startdatum": "2026-11-09", "weken": 12, "focus": "gemengd"},
       "week": {"ma": {"minuten": 0}, "di": {"minuten": 60}, "wo": {"minuten": 45},
                "do": {"minuten": 75}, "vr": {"minuten": 0},
                "za": {"minuten": 180, "buiten": True}, "zo": {"minuten": 90, "buiten": True}}}
STAP = re.compile(r"^- (\d+m)?(\d+s)? (ramp \d+-\d+%|\d+%)$")


@pytest.fixture(autouse=True)
def tmpdata(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DATA", tmp_path)


def test_syntax_alle_trainingen():
    for soort in workouts.BOUWERS:
        for m in (45, 60, 75, 90, 180):
            for p in (0, 0.5, 1):
                t = workouts.bouw(soort, m, p, "opbouw")
                for regel in t.beschrijving().splitlines():
                    if regel.startswith("-"):
                        assert STAP.match(regel), (soort, regel)
                if soort not in ("ftp_test",):
                    assert abs(t.minuten - max(m, 40 if soort == "openers" else 0)) <= 6, (soort, m, t.minuten)


def test_dagrollen():
    r = planner.dagrollen(CFG["week"], 2)
    named = {planner.DAGEN[i]: v for i, v in r.items()}
    assert named["za"] == "lang"
    assert sum(v.startswith("q") for v in named.values()) == 2
    assert "vr" not in named and "ma" not in named
    assert named["zo"] == "duur"  # geen intervallen direct na de lange rit


def test_plan():
    plan = planner.genereer(CFG, date(2026, 11, 11))
    assert plan[0]["datum"] == "2026-11-10"  # di van de week van 9 nov
    assert len(plan) == 12 * 5
    wk4 = [s for s in plan if s["week"] == 4]
    assert all(s["herstelweek"] for s in wk4)
    # standaard elke 8 weken een ramp-test: niet in week 4, wel in week 8
    assert not any(s["soort"] == "ftp_test" for s in wk4)
    assert any(s["soort"] == "ftp_test" for s in plan if s["week"] == 8)
    assert sum(s["soort"] == "ftp_test" for s in plan) == 1
    assert {s["fase"] for s in plan} == {"basis", "opbouw", "piek"}
    assert all(s["omgeving"] == "binnen" for s in plan if s["soort"] in workouts.OPTIES)


def test_tocht_taper():
    cfg = {**CFG, "doel": {**CFG["doel"], "type": "tocht", "weken": 8}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    laatste = [s for s in plan if s["week"] == 8]
    assert any(s["soort"] == "openers" for s in laatste)


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


def test_bijsturen_en_sync():
    service.genereer(CFG, date(2026, 11, 9))
    vandaag = date(2026, 11, 13)  # vrijdag week 1; di gereden, do gemist
    ic = NepIntervals(ritten=["2026-11-10", "2026-11-11"], ctl=60, atl=95)  # vorm -35
    log = service.bijsturen(CFG, vandaag, ic, weer(vandaag, slecht={"2026-11-14"}))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-10"]["status"] == "gedaan"
    assert plan["2026-11-12"]["status"] == "gemist"
    # gemiste intervaltraining (do) naar zondag (duurdag, buiten toegestaan)
    assert plan["2026-11-15"]["herkomst"].startswith("Verschoven")
    # zaterdag regen: lange rit niet naar zondag (die heeft nu een interval) → binnen, afgekapt
    za = plan["2026-11-14"]
    assert za["omgeving"] == "binnen" and za["minuten"] <= 120
    assert any("Vorm" in l for l in log)
    msg = service.sync(CFG, vandaag, ic)
    assert ic.upserts and all(e["external_id"].startswith("fietscoach-") for e in ic.upserts)
    # dagen zonder training in de horizon worden opgeruimd op ons eigen id
    assert all(d.startswith("fietscoach-") for d in ic.deleted)
    assert not set(ic.deleted) & {e["external_id"] for e in ic.upserts}
    assert "trainingen" in msg
    # tweede keer bijsturen is stabiel
    service.bijsturen(CFG, vandaag, ic, weer(vandaag, slecht={"2026-11-14"}))
    plan2 = {s["datum"]: s for s in service.laad_plan()}
    assert plan2["2026-11-15"]["soort"] == plan["2026-11-15"]["soort"]
    assert plan2["2026-11-14"]["minuten"] == za["minuten"]


def test_lange_rit_verplaatst():
    cfg = {**CFG, "week": {**CFG["week"], "zo": {"minuten": 150, "buiten": True}}}
    service.genereer(cfg, date(2026, 11, 9))
    vandaag = date(2026, 11, 13)
    ic = NepIntervals(ritten=["2026-11-10", "2026-11-11", "2026-11-12"], ctl=60, atl=60)
    service.bijsturen(cfg, vandaag, ic, weer(vandaag, slecht={"2026-11-14"}))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-15"]["soort"] == "lange_rit"
    assert plan["2026-11-15"]["omgeving"] == "buiten"
    assert plan["2026-11-14"]["soort"] == "duur"


def _cfg(**doel):
    return {**VOORBEELD, "doel": {"type": "ftp", "startdatum": "2026-11-09", **doel}}


def test_voorbeeldconfig_blokken():
    plan = planner.genereer(VOORBEELD, date(2026, 11, 9))
    assert {s["week"] for s in plan} == set(range(1, 13))
    q = [s for s in plan if s["rol"].startswith("q") and not s["herstelweek"]]
    assert all(s["soort"] == "duur" for s in q if s["week"] <= 4)        # zone 2-blok
    assert all(s["soort"] == "sweetspot" for s in q if s["week"] >= 5)   # sweetspot-blok
    namen = [s["naam"] for s in q if s["week"] >= 5]
    assert namen[0] == "Sweetspot 3×10m" and namen[-1] == "Sweetspot 2×20m"
    # di en do intervallen, zondag duur
    assert {s["dag"] for s in q} == {"di", "do"}
    assert all(s["rol"] == "duur" for s in plan if s["dag"] == "zo")


def test_sweetspot_2x20_past_in_60_min():
    t = workouts.bouw("sweetspot", 60, 1.0)
    assert t.naam == "Sweetspot 2×20m" and round(t.minuten) == 60


def test_zone2_geen_intervallen():
    plan = planner.genereer(_cfg(weken=8, focus="zone2"), date(2026, 11, 9))
    assert not any(s["soort"] in planner.INTERVALSOORTEN for s in plan)
    assert any(s["soort"] == "lange_rit_tempo" for s in plan)


def test_gepolariseerd():
    plan = planner.genereer(_cfg(weken=4, focus="gepolariseerd"), date(2026, 11, 9))
    wk1 = {s["dag"]: s["soort"] for s in plan if s["week"] == 1}
    assert wk1["di"] == "vo2max" and wk1["do"] == "duur"


def test_een_doordeweekse_sessie():
    cfg = {**_cfg(weken=4, focus="sweetspot"),
           "week": {"di": {"minuten": 60}, "za": {"minuten": 180, "buiten": True},
                    "zo": {"minuten": 90, "buiten": True}}}
    wk1 = {s["dag"]: s["soort"] for s in planner.genereer(cfg, date(2026, 11, 9)) if s["week"] == 1}
    assert wk1 == {"di": "sweetspot", "za": "lange_rit", "zo": "duur"}


# --- JOIN-achtige functies ------------------------------------------------------

from fietscoach import adapt  # noqa: E402


def _plan_wk1(vandaag, ritten=(), **kw):
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    ic = NepIntervals(ritten=list(ritten), ctl=60, atl=60)
    log = service.bijsturen(CFG | kw, vandaag, ic, weer(vandaag))
    return {s["datum"]: s for s in service.laad_plan()}, log


def test_rpe_maakt_volgende_zelfde_soort_lichter():
    # wk1: di sweetspot, do tempo. Di gereden, voelde als 10 (bedoeld 7).
    plan, _ = _plan_wk1(date(2026, 11, 12), ritten=["2026-11-10"])
    assert plan["2026-11-10"]["soort"] == "sweetspot"
    service.zet_rpe("2026-11-10", 10)
    niv = adapt.niveaus(service.laad_plan(), service.laad_feedback()["rpe"])
    assert niv["sweetspot"][0] < 0 and "lichter" in niv["sweetspot"][1]
    plan2, _ = _plan_wk1(date(2026, 11, 12), ritten=["2026-11-10"])
    volgende_ss = next(s for d, s in sorted(plan2.items()) if d > "2026-11-12" and s["soort"] == "sweetspot")
    assert volgende_ss["p_mod"] < 0


def test_score_na_rit():
    plan, _ = _plan_wk1(date(2026, 11, 12), ritten=["2026-11-10"])
    sc = plan["2026-11-10"]["score"]
    assert set(sc) == {"duur", "intensiteit", "totaal"} and 0 <= sc["totaal"] <= 100


def test_geen_tijd_verplaatst_sleuteltraining():
    cfg = CFG | {"uitzonderingen": {"2026-11-12": 0}}  # do (tempo) kan niet
    service.genereer(cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.bijsturen(cfg, date(2026, 11, 10), NepIntervals([], 60, 60), weer(date(2026, 11, 10)))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-12"]["soort"] == "rust"
    assert plan["2026-11-15"]["soort"] in planner.INTERVALSOORTEN  # naar zondag
    assert any("verplaatst" in n for n in plan["2026-11-15"]["notities"])


def test_extra_dag_met_tijd():
    cfg = CFG | {"uitzonderingen": {"2026-11-13": 90}}  # vrijdag normaal vrij
    service.genereer(cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.bijsturen(cfg, date(2026, 11, 10), NepIntervals([], 60, 60), weer(date(2026, 11, 10)))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-13"]["soort"] == "duur" and plan["2026-11-13"]["minuten"] == 90
    cfg["uitzonderingen"] = {}
    service.bijsturen(cfg, date(2026, 11, 10), NepIntervals([], 60, 60), weer(date(2026, 11, 10)))
    assert "2026-11-13" not in {s["datum"] for s in service.laad_plan()}


def test_ongeplande_zware_rit():
    class Clubrit(NepIntervals):
        def activiteiten(self, v, t):
            return [{"start_date_local": "2026-11-11T09:00:00", "type": "Ride",
                     "moving_time": 3 * 3600, "icu_training_load": 160}]
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    log = service.bijsturen(CFG, date(2026, 11, 12), Clubrit([], 60, 60), weer(date(2026, 11, 12)))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-11"]["status"] in ("gemist", "gedaan")  # wo stond herstel, er is wél gereden
    # wo stond in het schema: geen 'ongepland'. Nu een dag zonder schema: vrijdag.

    class Vrijdagrit(NepIntervals):
        def activiteiten(self, v, t):
            return [{"start_date_local": "2026-11-13T09:00:00", "type": "Ride",
                     "moving_time": 3 * 3600, "icu_training_load": 160}]
    log = service.bijsturen(CFG, date(2026, 11, 14), Vrijdagrit([], 60, 60), weer(date(2026, 11, 14)))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-14"]["soort"] == "herstel"
    assert any("Ongeplande rit" in r for r in log)


def test_readiness_laag():
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.zet_readiness("2026-11-10", 1, 2)
    service.bijsturen(CFG, date(2026, 11, 10), NepIntervals([], 60, 60), weer(date(2026, 11, 10)))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-10"]["soort"] == "duur"  # sweetspot werd rustig duur
    assert plan["2026-11-11"]["soort"] == "herstel"


def test_tochtdatum_bepaalt_lengte():
    cfg = _cfg(type="tocht", weken=99, focus="gemengd", evenement="2027-01-30")
    plan = planner.genereer(cfg, date(2026, 11, 9))
    assert plan[-1]["datum"] <= "2027-01-31" and plan[-1]["fase"] == "taper"


def test_zwo_geldig_xml():
    import xml.etree.ElementTree as ET
    for soort in workouts.BOUWERS:
        ET.fromstring(workouts.zwo(workouts.bouw(soort, 75, 0.5, "opbouw")))


def test_schermen(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    cfg = dict(VOORBEELD)
    monkeypatch.setattr(service, "laad_config", lambda *a: cfg)
    monkeypatch.setattr(service, "pas_toe", lambda *a: "ok")
    monkeypatch.setattr(service, "bewaar_instellingen", lambda c: cfg.update(c))
    c = TestClient(web.app)
    assert "Nog geen schema" in c.get("/").text
    service.genereer(cfg, date.today())
    r = c.get("/")
    assert r.status_code == 200 and "Hoe voel je je vandaag?" in r.text and "fc-profiel" in r.text
    assert "Week 1" in c.get("/schema").text
    assert "Een gewone week" in c.get("/instellingen").text
    assert c.get("/static/styles.css").status_code == 200
    # readiness invullen
    r = c.post("/readiness", data={"benen": "2", "energie": "3"}, follow_redirects=False)
    assert r.status_code == 303 and service.laad_feedback()["readiness"]
    # instellingen opslaan → nieuw schema met sweetspot
    form = {"type": "ftp", "startdatum": date.today().isoformat(), "focus0": "sweetspot", "weken0": "6",
            "max_kwaliteit": "2", "intervallen_binnen": "1", "max_binnen": "120", "variatie": "1",
            "max_neerslag_mm": "2", "max_neerslagkans": "60", "max_wind_kmh": "35", "min_temp": "0",
            "min_di": "60", "min_do": "60", "min_za": "180", "buiten_za": "1", "min_zo": "90", "buiten_zo": "1"}
    r = c.post("/instellingen", data=form, follow_redirects=False)
    assert r.status_code == 303 and "Opgeslagen" in r.headers["location"].replace("%20", " ")
    plan = service.laad_plan()
    assert max(s["week"] for s in plan) == 6
    toekomst = [s for s in plan if s["datum"] >= date.today().isoformat()]
    assert {s["soort"] for s in toekomst if s["rol"].startswith("q") and not s["herstelweek"]} == {"sweetspot"}
    s = next(s for s in plan if s["soort"] == "sweetspot")
    r = c.get(f"/zwo/{s['datum']}")
    assert r.status_code == 200 and "<workout>" in r.text and ("<IntervalsT" in r.text or "<SteadyState" in r.text)


# --- bibliotheek ------------------------------------------------------------------

from fietscoach import bibliotheek  # noqa: E402

STAP_RPM = re.compile(r"^- ([A-Z][a-z]+ )?(\d+m)?(\d+s)? (ramp \d+-\d+%|\d+%|freeride)( \d+rpm)?$")


@pytest.mark.parametrize("soort", sorted(bibliotheek.BIBLIOTHEEK))
def test_alle_varianten(soort):
    import xml.etree.ElementTree as ET
    for v in range(bibliotheek.aantal(soort)):
        for m in (30, 45, 60, 90, 150, 240):
            for p in (0, 0.5, 1):
                t = workouts.bouw(soort, m, p, "opbouw", v)
                for regel in t.beschrijving().splitlines():
                    if regel.startswith("-"):
                        assert STAP_RPM.match(regel), (soort, v, regel)
                assert abs(t.minuten - m) <= (6 if v == 0 else 1.01), (soort, v, m, t.minuten)
                ET.fromstring(workouts.zwo(t))


def test_afwisseling_in_sweetspotblok():
    plan = planner.genereer(_cfg(weken=8, focus="sweetspot"), date(2026, 11, 9))
    ss = [s["naam"].split(" ")[1] for s in plan if s["soort"] == "sweetspot"]
    assert len(set(ss)) >= 3, ss
    # twee sweetspotdagen in dezelfde week zijn verschillend
    wk1 = [s["naam"] for s in plan if s["week"] == 1 and s["soort"] == "sweetspot"]
    assert len(wk1) == 2 and wk1[0] != wk1[1]


def test_variatie_uit():
    cfg = _cfg(weken=4, focus="sweetspot") | {"voorkeuren": {"variatie": False}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    assert all(s["naam"].startswith("Sweetspot ") and "×" in s["naam"] for s in plan if s["soort"] == "sweetspot")


def test_cadans_in_zwo():
    t = workouts.bouw("tempo", 60, 0.5, "", 2)  # krachttempo
    assert "65rpm" in t.beschrijving() and 'Cadence="65"' in workouts.zwo(t)


def test_bibliotheekscherm(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(VOORBEELD))
    r = TestClient(web.app).get("/bibliotheek?minuten=90")
    assert r.status_code == 200 and "Over-unders" in r.text and r.text.count("fc-profiel") >= 15


# --- duur van vandaag aanpassen ---------------------------------------------------

@pytest.mark.parametrize("minuten,verwacht", [(45, 45), (90, 90)])
def test_duur_vandaag_aanpassen(minuten, verwacht):
    # di 10 nov staat een sweetspot van 60 min; kies vlak voor de training een andere duur
    cfg = CFG | {"uitzonderingen": {"2026-11-10": minuten}}
    service.genereer(cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.bijsturen(cfg, date(2026, 11, 10), NepIntervals([], 60, 60), weer(date(2026, 11, 10)))
    s = next(s for s in service.laad_plan() if s["datum"] == "2026-11-10")
    assert s["soort"] == "sweetspot" and s["minuten"] == verwacht and abs(s["duur"] - verwacht) <= 1


def test_duurknoppen_op_vandaag(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    cfg = dict(VOORBEELD, uitzonderingen={})
    monkeypatch.setattr(service, "laad_config", lambda *a: cfg)
    monkeypatch.setattr(service, "pas_toe", lambda *a: "ok")
    monkeypatch.setattr(service, "bewaar_instellingen", lambda c: cfg.update(c))
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 10))
    service.genereer(cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    c = TestClient(web.app)
    html = c.get("/").text
    assert "Duur aanpassen" in html and 'value="2026-11-10"' in html
    gepland = next(s for s in service.laad_plan() if s["datum"] == "2026-11-10")["minuten"]
    assert gepland == 55  # week 1 rijdt op 90%: geen 'ronde' knop
    assert f'name="minuten" value="{gepland}" aria-pressed="true"' in html
    assert html.count('aria-pressed="true"') == 1
    r = c.post("/uitzondering", data={"datum": "2026-11-10", "minuten": "45"}, follow_redirects=False)
    assert r.status_code == 303


# --- contract met intervals.icu (vorm volgens de openbare documentatie) -----------

import base64  # noqa: E402
import json as _json  # noqa: E402

import httpx  # noqa: E402

from fietscoach.intervals import Intervals, eftp_uit, verbindingstest  # noqa: E402

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


def test_contract_bijsturen_en_sync():
    server = NepServer()
    ic = _client(server)
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.bijsturen(CFG, date(2026, 11, 9), ic, weer(date(2026, 11, 9)))
    st = service.laad_status()
    assert st["ftp"] == 272 and st["eftp"] == 284 and st["ctl"] == 51 and st["vorm"] == -10
    assert st["ritten"]["2026-11-08"]["if"] == 0.66 and "2026-11-07" not in st["ritten"]  # hardlopen telt niet
    service.sync(CFG, date(2026, 11, 9), ic)
    upsert = next(r for r in server.verzoeken if r.url.path.endswith("/events/bulk"))
    events = _json.loads(upsert.content)
    assert all(e["category"] == "WORKOUT" and e["external_id"].startswith("fietscoach-") for e in events)
    assert {e["type"] for e in events} <= {"Ride", "VirtualRide"}
    delete = next(r for r in server.verzoeken if r.url.path.endswith("/bulk-delete"))
    assert all(set(x) == {"external_id"} for x in _json.loads(delete.content))
    ok, info = service.gezondheid()
    assert ok and info["uren_sinds_sync"] < 1


def test_verbindingstest_goed_en_fout():
    regels = verbindingstest(_client(NepServer()), date(2026, 11, 9))
    assert all(ok for ok, _ in regels) and len(regels) == 4
    assert "FTP fiets 272" in regels[0][1] and "eFTP 284" in regels[1][1]
    assert "icu_intensity" in regels[2][1] and "1 van Fietscoach" in regels[3][1]
    fout = verbindingstest(_client(NepServer(status=401)), date(2026, 11, 9))
    assert fout == [(False, "Atleet: HTTP 401 sleutel klopt niet")]


def test_eftp_oude_vorm():
    assert eftp_uit({"sportInfo": [{"type": "Ride", "eftp": 250.4}]}) == 250
    assert eftp_uit({}) is None


def test_gezondheid_zonder_sync():
    ok, info = service.gezondheid()
    assert not ok and "nooit" in info["reden"]


def test_health_en_verbindingsknop(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    c = TestClient(web.app)
    r = c.get("/health")
    assert r.status_code == 503 and r.json()["ok"] is False
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(VOORBEELD))
    monkeypatch.setattr(service, "client", lambda cfg: _client(NepServer()))
    r = c.post("/verbinding", follow_redirects=False)
    assert r.status_code == 303 and "in%20orde" in r.headers["location"]


# --- gelijktijdig schrijven -------------------------------------------------------

def test_geen_verloren_invoer_bij_gelijktijdig_schrijven():
    """Twee 'gebruikers' (timer en scherm) die tegelijk feedback opslaan."""
    import threading
    start = date(2026, 1, 1)

    def schrijf(offset):
        for i in range(150):
            service.zet_rpe((start + timedelta(days=offset + 2 * i)).isoformat(), 5)

    t = [threading.Thread(target=schrijf, args=(k,)) for k in (0, 1)]
    [x.start() for x in t]
    [x.join() for x in t]
    assert len(service.laad_feedback()["rpe"]) == 300


def test_geen_verloren_invoer_tussen_processen():
    """Zoals de ochtendtimer (eigen proces) naast de webapp."""
    import multiprocessing as mp
    ctx = mp.get_context("fork")

    def schrijf(offset, pad):
        service.DATA = pad
        for i in range(100):
            service.zet_rpe((date(2026, 1, 1) + timedelta(days=offset + 2 * i)).isoformat(), 5)

    p = [ctx.Process(target=schrijf, args=(k, service.DATA)) for k in (0, 1)]
    [x.start() for x in p]
    [x.join() for x in p]
    assert all(x.exitcode == 0 for x in p)
    assert len(service.laad_feedback()["rpe"]) == 200


# --- weer per rit -----------------------------------------------------------------

from fietscoach.weather import Verwachting  # noqa: E402


def _uren(datum, regen_uren=(), vorst_uren=(), wind=20):
    uur = {}
    for h in range(24):
        uur[f"{datum}T{h:02d}:00"] = {"temp": -2 if h in vorst_uren else 8, "neerslag": 3.0 if h in regen_uren else 0.0,
                                      "kans": 90 if h in regen_uren else 10, "wind": wind}
    return uur


def test_venster_telt_alleen_ritduur():
    d = "2026-11-14"
    v = Verwachting({d: {"temp_min": -2, "temp_max": 8, "neerslag_mm": 9, "neerslagkans": 90, "wind_kmh": 20}},
                    _uren(d, regen_uren=(21, 22, 23), vorst_uren=(4, 5, 6)))
    w = v.venster(d, "09:30", 160)  # 09:30–12:10 raakt uur 9, 10, 11 en 12
    assert w["neerslag_mm"] == 0 and w["temp_min"] == 8 and w["venster"] == "09:30–12:10"
    w = v.venster(d, "20:00", 120)  # avondrit 20–22 raakt het regenuur van 21:00
    assert w["neerslag_mm"] == 3.0 and w["neerslagkans"] == 90
    assert v.venster("2026-12-31", "09:30", 60) is None  # buiten de verwachting
    assert Verwachting({d: {"x": 1}}).venster(d, "09:30", 60) == {"x": 1}  # zonder uurdata: dagwaarden


def test_avondregen_stuurt_ochtendrit_niet_naar_binnen():
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    vandaag = date(2026, 11, 13)
    uur = {}
    for i in range(3):
        d = (vandaag + timedelta(days=i)).isoformat()
        uur |= _uren(d, regen_uren=(20, 21, 22, 23) if d == "2026-11-14" else ())
    dag = {d[:10]: {"temp_min": 8, "temp_max": 8, "neerslag_mm": 12, "neerslagkans": 90, "wind_kmh": 20} for d in uur}
    v = Verwachting(dag, uur)
    service.bijsturen(CFG, vandaag, NepIntervals([], 60, 60),
                      lambda d, m: v.venster(d, service.starttijd(CFG["week"], d), m))
    za = next(s for s in service.laad_plan() if s["datum"] == "2026-11-14")
    assert za["soort"] == "lange_rit" and za["omgeving"] == "buiten", za["notities"]
    assert za["weer"].startswith("09:30–")
    # met alleen dagwaarden (zoals vroeger) was hij naar Zwift gegaan
    service.bijsturen(CFG, vandaag, NepIntervals([], 60, 60), dag)
    za = next(s for s in service.laad_plan() if s["datum"] == "2026-11-14")
    assert za["omgeving"] == "binnen"


def test_starttijd():
    assert service.starttijd({}, "2026-11-14") == "09:30"
    assert service.starttijd({}, "2026-11-10") == "18:30"
    assert service.starttijd({"za": {"start": "08:00"}}, "2026-11-14") == "08:00"


def test_units_draaien_op_lokale_tijd():
    for f in ("fietscoach.service", "fietscoach-dagelijks.service"):
        assert "Environment=TZ=Europe/Amsterdam" in (ROOT / "deploy" / f).read_text()


def test_starttijd_opslaan_en_cwem_link(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    cfg = dict(VOORBEELD, uitzonderingen={})
    monkeypatch.setattr(service, "laad_config", lambda *a: cfg)
    monkeypatch.setattr(service, "pas_toe", lambda *a: "ok")
    monkeypatch.setattr(service, "bewaar_instellingen", lambda c: cfg.update(c))
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 14))
    c = TestClient(web.app)
    form = {"type": "ftp", "startdatum": "2026-11-09", "focus0": "zone2", "weken0": "4",
            "min_za": "180", "buiten_za": "1", "start_za": "08:15", "min_di": "60", "start_di": "25:99"}
    c.post("/instellingen", data=form, follow_redirects=False)
    assert cfg["week"]["za"]["start"] == "08:15" and cfg["week"]["di"]["start"] is None
    service.genereer(cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    html = c.get("/").text
    assert "https://cwem.dockerapp.org/#ride" in html  # zaterdag: buiten
    assert 'name="start_za"' in c.get("/instellingen").text


def test_korte_harde_stukken_zonder_erg():
    """Niets korter dan een minuut boven 110% in ERG; in .zwo als FreeRide."""
    for soort in bibliotheek.BIBLIOTHEEK:
        for v in range(bibliotheek.aantal(soort)):
            for m in (45, 60, 90, 150):
                t = workouts.bouw(soort, m, 0.5, "opbouw", v)
                for b in t.blokken:
                    for st in b.stappen:
                        hoog = (max(st.pct) if isinstance(st.pct, tuple) else st.pct) > 110
                        if hoog and st.minuten < 1:
                            assert st.vrij, (t.naam, st)
    t = workouts.bouw("vo2max", 60, 0.5, "", 1)  # 30/15's
    assert "- Hard 30s freeride" in t.beschrijving() and "<FreeRide" in workouts.zwo(t)


@pytest.mark.parametrize("elke,weken", [(4, [4, 8, 12]), (8, [8]), (12, [12]), (0, [])])
def test_ftp_test_interval(elke, weken):
    cfg = CFG | {"voorkeuren": {"ftp_test_weken": elke}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    assert sorted(s["week"] for s in plan if s["soort"] == "ftp_test") == weken


# --- gereden is niet gedaan, afwezigheid, HRV -------------------------------------

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


def test_woon_werkrit_telt_niet_als_intervaltraining():
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    # di: sweetspot 60 → 20 min woon-werk. do: tempo 75 → 25 min, maar door intervals.icu gekoppeld.
    ic = RittenNep([_rit("2026-11-10", 20), _rit("2026-11-12", 25, gepaard=True)])
    service.bijsturen(CFG, date(2026, 11, 13), ic, weer(date(2026, 11, 13)))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-10"]["status"] == "gemist"
    assert any("te kort" in n for n in plan["2026-11-10"]["notities"])
    assert plan["2026-11-12"]["status"] == "gedaan"
    # de gemiste sweetspot schuift naar zondag, met de vorm van dinsdag
    assert plan["2026-11-15"]["herkomst"].startswith("Verschoven van di")
    assert plan["2026-11-15"]["variant"] == plan["2026-11-10"]["variant"]


def test_afwezigheid_en_rustig_opstarten():
    cfg = CFG | {"afwezig": [{"van": "2026-11-16", "tot": "2026-11-22", "reden": "Vakantie"}]}
    service.genereer(cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.bijsturen(cfg, date(2026, 11, 10), NepIntervals([], 60, 60), weer(date(2026, 11, 10)))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert all(plan[d]["soort"] == "rust" for d in plan if "2026-11-16" <= d <= "2026-11-22")
    assert plan["2026-11-24"]["soort"] == "duur"  # di na terugkomst: geen intervallen
    assert any("opstarten" in n for n in plan["2026-11-24"]["notities"])
    assert plan["2026-11-26"]["soort"] in planner.INTERVALSOORTEN  # do weer gewoon
    # ook buiten het venster van 14 dagen staat het goed (afgeleid, niet ter plekke)
    assert plan["2026-11-21"]["naam"] == "Rust"
    # sync stuurt niets voor afwezige dagen
    ic = NepIntervals([], 60, 60)
    service.sync(cfg, date(2026, 11, 10), ic)
    assert not {e["external_id"] for e in ic.upserts} & {f"fietscoach-2026-11-{d}" for d in range(16, 23)}


def test_readiness_uit_hrv():
    from fietscoach import adapt as a
    basis = [{"id": f"2026-10-{d:02d}", "hrv": 50 + (d % 3), "restingHR": 50 + (d % 2)} for d in range(10, 31)]
    goed, uitleg = a.objectieve_readiness(basis + [{"id": "2026-11-01", "hrv": 51, "restingHR": 50}], date(2026, 11, 1))
    assert goed is None and "HRV 51" in uitleg
    een, _ = a.objectieve_readiness(basis + [{"id": "2026-11-01", "hrv": 40, "restingHR": 50}], date(2026, 11, 1))
    twee, _ = a.objectieve_readiness(basis + [{"id": "2026-11-01", "hrv": 40, "restingHR": 60}], date(2026, 11, 1))
    assert een == 2.5 and twee == 2.0
    assert a.objectieve_readiness(basis[:3] + [{"id": "2026-11-01", "hrv": 40}], date(2026, 11, 1))[0] is None
    assert a.readiness_score({"benen": 4, "energie": 4}, 2.5) == 2.5


def test_lage_hrv_maakt_vandaag_lichter():
    well = [{"id": (date(2026, 11, 10) - timedelta(days=i)).isoformat(), "hrv": 50 + i % 3, "restingHR": 50,
             "ctl": 60, "atl": 60} for i in range(1, 22)]
    well.append({"id": "2026-11-10", "hrv": 38, "restingHR": 61, "ctl": 60, "atl": 60})
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.bijsturen(CFG, date(2026, 11, 10), RittenNep([], sorted(well, key=lambda w: w["id"])), weer(date(2026, 11, 10)))
    di = next(s for s in service.laad_plan() if s["datum"] == "2026-11-10")
    assert di["soort"] == "duur" and any("Readiness laag" in n for n in di["notities"])


def test_afleiden_is_herhaalbaar_en_raakt_basis_niet():
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    basis_voor = _json.dumps(service.laad_basis(), sort_keys=True)
    cfg = CFG | {"uitzonderingen": {"2026-11-12": 0}}
    for _ in range(3):
        service.bijsturen(cfg, date(2026, 11, 13), RittenNep([_rit("2026-11-10", 20)]), weer(date(2026, 11, 13)))
    een = _json.dumps(service.laad_plan(), sort_keys=True)
    service.bijsturen(cfg, date(2026, 11, 13), RittenNep([_rit("2026-11-10", 20)]), weer(date(2026, 11, 13)))
    assert _json.dumps(service.laad_plan(), sort_keys=True) == een
    assert _json.dumps(service.laad_basis(), sort_keys=True) == basis_voor


# --- webapp: beveiliging, snelheid, afwezigheid ----------------------------------

@pytest.fixture
def web_cfg(monkeypatch):
    from fietscoach import web
    cfg = dict(VOORBEELD, uitzonderingen={}, afwezig=[])
    monkeypatch.setattr(service, "laad_config", lambda *a: cfg)
    monkeypatch.setattr(service, "bewaar_instellingen", lambda c: cfg.update(c))
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 10))
    return cfg


def test_andere_site_mag_geen_formulier_sturen(web_cfg):
    from fastapi.testclient import TestClient
    from fietscoach import web
    service.genereer(web_cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    c = TestClient(web.app)
    r = c.post("/rpe", data={"datum": "2026-11-10", "rpe": "5"}, headers={"Origin": "https://kwaad.example"},
               follow_redirects=False)
    assert r.status_code == 403 and "2026-11-10" not in service.laad_feedback()["rpe"]
    r = c.post("/rpe", data={"datum": "2026-11-10", "rpe": "5"}, headers={"Origin": "http://testserver"},
               follow_redirects=False)
    assert r.status_code == 303 and service.laad_feedback()["rpe"]["2026-11-10"] == 5
    # achter Caddy: X-Forwarded-Host telt
    r = c.post("/rpe", data={"datum": "2026-11-11", "rpe": "6"},
               headers={"Origin": "https://fiets.example", "X-Forwarded-Host": "fiets.example"}, follow_redirects=False)
    assert r.status_code == 303
    r = c.post("/rpe", data={"datum": "2026-11-11", "rpe": "6", "terug": "https://kwaad.example"},
               headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert r.headers["location"].startswith("/?")  # geen open redirect


def test_invoer_is_direct_en_sync_op_achtergrond(web_cfg, monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    service.genereer(web_cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    aanroepen = []
    monkeypatch.setattr(service, "sync_veilig", lambda *a: aanroepen.append("sync") or "")
    netwerk = []
    monkeypatch.setattr(service, "client", lambda cfg: netwerk.append("intervals") or None)
    monkeypatch.setattr(service.weather, "verwachting", lambda *a: netwerk.append("weer"))
    r = TestClient(web.app).post("/uitzondering", data={"datum": "2026-11-10", "minuten": "45"}, follow_redirects=False)
    assert r.status_code == 303 and aanroepen == ["sync"]
    assert "intervals" not in netwerk  # geen ritten/wellness ophalen bij een klik
    s = next(s for s in service.laad_plan() if s["datum"] == "2026-11-10")
    assert s["minuten"] == 45


def test_afwezigheid_via_scherm(web_cfg, monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    monkeypatch.setattr(service, "sync_veilig", lambda *a: "")
    service.genereer(web_cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    c = TestClient(web.app)
    c.post("/afwezig", data={"van": "2026-11-20", "tot": "2026-11-16", "reden": "Skiën"}, follow_redirects=False)
    assert web_cfg["afwezig"] == [{"van": "2026-11-16", "tot": "2026-11-20", "reden": "Skiën"}]  # omgedraaid
    assert "Skiën" in c.get("/instellingen").text
    assert next(s for s in service.laad_plan() if s["datum"] == "2026-11-17")["soort"] == "rust"
    c.post("/afwezig", data={"weg": "0"}, follow_redirects=False)
    assert web_cfg["afwezig"] == []
    r = c.post("/afwezig", data={"van": "", "tot": ""}, follow_redirects=False)
    assert "Niet%20opgeslagen" in r.headers["location"]


def test_ready_en_lettertypes(web_cfg):
    from fastapi.testclient import TestClient
    from fietscoach import web
    c = TestClient(web.app)
    assert c.get("/ready").json() == {"ok": True}
    html = c.get("/").text
    assert "googleapis" not in html and "/static/fonts/fonts.css" in html
    css = c.get("/static/fonts/fonts.css").text
    for bestand in re.findall(r'url\("([^"]+)"\)', css):
        r = c.get("/static/fonts/" + bestand)
        assert r.status_code == 200 and r.content[:4] == b"wOF2", bestand


def test_hrv_en_ftp_voorstel_op_vandaag(web_cfg, monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    monkeypatch.setattr(web, "vandaag", lambda: date(2027, 1, 7))
    cfg = web_cfg | {"doel": {**web_cfg["doel"], "startdatum": "2026-11-09"}}
    monkeypatch.setattr(service, "laad_config", lambda *a: cfg)
    service.genereer(cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    test = next(s for s in service.laad_plan() if s["soort"] == "ftp_test")  # do 31 dec, week 8
    well = [{"id": (date(2027, 1, 7) - timedelta(days=i)).isoformat(), "hrv": 50, "restingHR": 50,
             "ctl": 55, "atl": 50, "eftp": 281} for i in range(20, 0, -1)]
    well.append({"id": "2027-01-07", "hrv": 39, "restingHR": 50, "ctl": 55, "atl": 50, "eftp": 281})
    ic = RittenNep([_rit(test["datum"], 40, gepaard=True)], well)
    service.bijsturen(cfg, date(2027, 1, 7), ic, weer(date(2027, 1, 7)))
    html = TestClient(web.app).get("/").text
    assert "Ramp-test gereden" in html and "281 W" in html
    assert "HRV 39 (normaal 50)" in html and "minder hersteld" in html


def test_verbindingstest_crasht_niet_op_opzetfout(monkeypatch, capsys):
    from fietscoach import cli
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(VOORBEELD))
    monkeypatch.setattr(service, "client", lambda cfg: (_ for _ in ()).throw(PermissionError("ca-bestand")))
    monkeypatch.setattr("sys.argv", ["fietscoach", "test"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 1 and "Kon geen verbinding opzetten: PermissionError" in capsys.readouterr().out


def test_oude_installatie_stapt_over_op_basis():
    """Vóór deze versie bestond alleen plan.json (met bijsturingen erin)."""
    plan = planner.genereer(CFG, date(2026, 11, 9))
    for s in plan:  # zoals de oude code het achterliet: bijgestuurde velden in het plan
        s.update(status="gepland", soort="herstel" if s["datum"] == "2026-11-10" else s["soort"],
                 notities=["oud"], weer="oud", p_mod=-0.3)
    service._schrijf("plan.json", plan)
    assert not (service.DATA / "basis.json").exists()
    service.bijsturen(CFG, date(2026, 11, 9), NepIntervals([], 60, 60), weer(date(2026, 11, 9)))
    basis = service.laad_basis()
    assert (service.DATA / "basis.json").exists() and len(basis) == len(plan)
    di = next(s for s in service.laad_plan() if s["datum"] == "2026-11-10")
    assert di["soort"] == di["basis_soort"] == "sweetspot"  # oude bijsturing niet blijvend
    assert "oud" not in di["notities"]


# --- onderzoeksprotocollen --------------------------------------------------------

def _vorm(soort, naam_begin, minuten=75, p=1.0):
    for v in range(1, bibliotheek.aantal(soort)):
        t = workouts.bouw(soort, minuten, p, "opbouw", v)
        if t.naam.startswith(naam_begin):
            return t
    raise AssertionError(f"{naam_begin} niet gevonden")


def test_ronnestad_zoals_in_de_studie():
    t = _vorm("vo2max", "30/15's Rønnestad", 60, 1.0)
    sets = [b for b in t.blokken if b.titel and b.titel.startswith("Set")]
    assert len(sets) == 3 and all(b.herhalingen == 13 for b in sets)
    werk, rust = sets[0].stappen
    assert (werk.minuten, rust.minuten) == (0.5, 0.25) and rust.pct == werk.pct // 2  # herstel op de helft
    tussen = [b for b in t.blokken if not b.titel and b.stappen[0].minuten == 3]
    assert len(tussen) == 2  # 3 min tussen de sets
    assert "Rønnestad" in t.toelichting and round(t.minuten) == 60


def test_seiler_helgerud_sit_tabata():
    s8 = _vorm("vo2max", "Seiler 4×8m", 60, 1.0)
    assert [(st.minuten, st.pct) for st in s8.blokken[1].stappen] == [(8, 105), (2, 55)] and s8.blokken[1].herhalingen == 4
    s16 = _vorm("drempel", "Seiler", 120, 1.0)
    assert s16.blokken[1].stappen[0].minuten == 16 and s16.blokken[1].stappen[1].minuten == 2
    h = _vorm("vo2max", "4×4 Helgerud", 60, 1.0)
    assert [(st.minuten, st.pct) for st in h.blokken[1].stappen] == [(4, 110), (3, 55)] and h.blokken[1].herhalingen == 4
    sit = _vorm("vo2max", "Sprintintervallen", 60, 1.0)
    sprint, herstel = sit.blokken[1].stappen
    assert sprint.minuten == 0.5 and sprint.vrij and herstel.minuten == 4 and sit.blokken[1].herhalingen == 6
    tab = _vorm("vo2max", "Tabata", 60, 0.0)
    blok = tab.blokken[1]
    assert blok.herhalingen == 8 and [st.minuten * 60 for st in blok.stappen] == [20, 10] and blok.stappen[0].vrij
    for t in (s8, s16, h, sit, tab):
        assert any(j in t.toelichting for j in ("2013", "2007", "2005", "1996")), t.naam  # bron genoemd


def test_twintig_minuten_test():
    t = workouts.bouw("ftp_test", 40, 0, "", 1)
    assert t.naam == "FTP-test 20 minuten" and "95%" in t.toelichting
    titels = [b.titel for b in t.blokken]
    assert "5 minuten maximaal" in titels and "20 minuten test" in titels
    assert next(b for b in t.blokken if b.titel == "20 minuten test").stappen[0].vrij
    import xml.etree.ElementTree as ET
    ET.fromstring(workouts.zwo(t))
    plan = planner.genereer(CFG | {"voorkeuren": {"ftp_test_vorm": "20min"}}, date(2026, 11, 9))
    test = next(s for s in plan if s["soort"] == "ftp_test")
    assert test["naam"] == "FTP-test 20 minuten"
    plan = planner.genereer(CFG, date(2026, 11, 9))
    assert next(s for s in plan if s["soort"] == "ftp_test")["naam"] == "FTP-test (ramp)"


def test_bibliotheek_toont_protocollen_en_tests(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(VOORBEELD))
    html = TestClient(web.app).get("/bibliotheek?minuten=90").text
    for naam in ("Rønnestad", "Helgerud", "Seiler 4×8m", "Sprintintervallen", "Tabata", "FTP-test 20 minuten", "FTP-test (ramp)"):
        assert naam in html, naam


# --- eigen workouts (.zwo) ----------------------------------------------------------

import io  # noqa: E402
import zipfile  # noqa: E402

from fietscoach import eigen  # noqa: E402


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


def test_zwo_inlezen():
    t, meta = eigen.lees_zwo(VO2_ZWO, "x.zwo")
    assert meta["naam"] == "Test VO2" and meta["onbekend"] == ["Onbekend"]  # textevent genegeerd, onbekend gemeld
    assert round(t.minuten) == 10 + 2 + 24 + 5 + 0 + 1 + 8  # 20 s MaxEffort ≈ 0
    iv = next(b for b in t.blokken if b.titel == "Intervallen")
    assert iv.herhalingen == 6 and [(s.pct, s.rpm) for s in iv.stappen] == [(112, 100), (50, 85)]
    stappen = [s for b in t.blokken for s in b.stappen]
    assert any(s.vrij and s.cue == "Voluit" for s in stappen) and any(s.vrij and not s.cue for s in stappen)
    assert stappen[0].minuten == 10  # 600.0001 s afgerond
    assert "- 3x" not in t.toelichting and "Testworkout – 3x" in t.toelichting  # geen nep-stap voor intervals.icu
    for regel in t.beschrijving().splitlines():
        if regel.startswith("-"):
            assert STAP_RPM.match(regel), regel
    import xml.etree.ElementTree as ET
    ET.fromstring(workouts.zwo(t))


def test_zwo_indeling():
    assert eigen.indeling(eigen.lees_zwo(VO2_ZWO)[0]) == "vo2max"
    assert eigen.indeling(eigen.lees_zwo(DUUR_ZWO)[0]) == "duur"
    assert eigen.indeling(eigen.lees_zwo(DREMPEL_ZWO)[0]) == "drempel"


@pytest.mark.parametrize("data,fout", [
    (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workout_file><workout/></workout_file>', "ENTITY"),
    (b"<html><body>geen workout</body></html>", "geen Zwift-workout"),
    (b"dit is geen xml", "geen geldige XML"),
    (_zwo("Loop", '<SteadyState Duration="60" Power="1"/>', sport="run"), "geen fietsworkout"),
    (_zwo("Leeg", '<Onbekend Duration="60"/>'), "geen stappen"),
    (b"<workout_file>" + b" " * (300 * 1024) + b"</workout_file>", "te groot"),
])
def test_zwo_weigert_onzin(data, fout):
    with pytest.raises(eigen.OngeldigBestand, match=fout):
        eigen.lees_zwo(data)


def _zip(bestanden):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for naam, data in bestanden:
            z.writestr(naam, data)
    return buf.getvalue()


def test_bulkimport_zip_en_bijwerken():
    zipdata = _zip([("map/sub/vo2.zwo", VO2_ZWO), ("map/duur.zwo", DUUR_ZWO), ("__MACOSX/._duur.zwo", b"rommel"),
                    ("leesmij.txt", b"x"), ("kapot.zwo", b"<html/>")])
    gelukt, mislukt = eigen.importeer([("export.zip", zipdata), ("drempel.zwo", DREMPEL_ZWO), ("foto.jpg", b"x")])
    assert len(gelukt) == 3 and all("nieuw" in g for g in gelukt)
    assert mislukt == ["kapot.zwo: geen Zwift-workout (workout_file met workout ontbreekt)"]
    assert sorted(w.id for w in eigen.alle()) == ["drempel", "duur", "vo2"]
    gelukt, _ = eigen.importeer([("duur.zwo", DUUR_ZWO)])
    assert "bijgewerkt" in gelukt[0] and len(eigen.alle()) == 3


def test_zip_bom_en_te_veel():
    groot = _zip([("groot.zwo", b"<workout_file>" + b"x" * (eigen.MAX_BYTES + 10) + b"</workout_file>")])
    _, mislukt = eigen.importeer([("a.zip", groot)])
    assert "te groot" in mislukt[0]
    bom = _zip([(f"w{i}.zwo", b"0" * 70_000) for i in range(1000)])
    _, mislukt = eigen.importeer([("bom.zip", bom)])
    assert "64 MB" in mislukt[0] and eigen.alle() == []
    _, mislukt = eigen.importeer([("x.zip", b"geen zip")])
    assert "geen geldig zip" in mislukt[0]


def test_eigen_workouts_in_het_schema():
    eigen.importeer([("drempel.zwo", DREMPEL_ZWO)])  # 10 + 3×13 + 6 = 55 min, drempel
    cfg = _cfg(weken=8, focus="gemengd") | {"week": {"di": {"minuten": 60}, "do": {"minuten": 75},
                                                      "za": {"minuten": 180, "buiten": True}}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    drempel = [s for s in plan if s["soort"] == "drempel"]
    eigen_namen = [s for s in drempel if s["naam"] == "Test drempel"]
    assert eigen_namen, [s["naam"] for s in drempel]
    assert all(s["duur"] == 55 for s in eigen_namen)
    assert any(s["naam"] != "Test drempel" for s in drempel)  # afwisseling blijft
    # te lang voor de beschikbare tijd: dan nooit
    plan = planner.genereer(cfg | {"week": {"di": {"minuten": 45}, "do": {"minuten": 45},
                                            "za": {"minuten": 180, "buiten": True}}}, date(2026, 11, 9))
    assert not any(s["naam"] == "Test drempel" for s in plan)


def test_bulk_via_scherm(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(VOORBEELD))
    monkeypatch.setattr(service, "sync_veilig", lambda *a: "")
    c = TestClient(web.app)
    bestanden = [("bestanden", ("vo2.zwo", VO2_ZWO, "application/xml")),
                 ("bestanden", ("map/duur.zwo", DUUR_ZWO, "application/xml")),         # uit een gekozen map
                 ("bestanden", ("map/notities.txt", b"x", "text/plain")),               # overgeslagen
                 ("bestanden", ("set.zip", _zip([("drempel.zwo", DREMPEL_ZWO)]), "application/zip"))]
    r = c.post("/eigen", files=bestanden, follow_redirects=False)
    assert r.status_code == 303 and "Toegevoegd" in r.headers["location"].replace("%20", " ")
    html = c.get("/bibliotheek").text
    assert "3 eigen workouts" in html and "Test drempel" in html and "Auteur: Test" in html
    r = c.post("/eigen/alle-weg", follow_redirects=False)
    assert eigen.alle() == []


def test_bulk_via_opdrachtregel(tmp_path, monkeypatch, capsys):
    from fietscoach import cli
    map_ = tmp_path / "export"
    (map_ / "sub").mkdir(parents=True)
    (map_ / "vo2.zwo").write_bytes(VO2_ZWO)
    (map_ / "sub" / "duur.zwo").write_bytes(DUUR_ZWO)
    (map_ / "lees.txt").write_text("x")
    zipbestand = tmp_path / "meer.zip"
    zipbestand.write_bytes(_zip([("drempel.zwo", DREMPEL_ZWO)]))
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(VOORBEELD))
    monkeypatch.setattr("sys.argv", ["fietscoach", "importeer", str(map_), str(zipbestand)])
    cli.main()
    uit = capsys.readouterr().out
    assert "3 toegevoegd, 0 niet." in uit and len(eigen.alle()) == 3


# --- indeling van eigen workouts ---------------------------------------------------

def test_soort_zelf_kiezen_en_alles_automatisch():
    eigen.importeer([("drempel.zwo", DREMPEL_ZWO), ("duur.zwo", DUUR_ZWO)])
    assert {w.id: (w.soort, w.handmatig) for w in eigen.alle()} == {"drempel": ("drempel", False), "duur": ("duur", False)}
    assert eigen.zet_soort("drempel", "sweetspot")
    w = next(w for w in eigen.alle() if w.id == "drempel")
    assert (w.soort, w.auto, w.handmatig) == ("sweetspot", "drempel", True)
    assert [x.id for x in eigen.voor_soort("sweetspot")] == ["drempel"] and not eigen.voor_soort("drempel")
    assert not eigen.zet_soort("bestaat-niet", "tempo")
    eigen.zet_soort("duur", "onzin")  # onbekende soort = automatisch
    assert next(w for w in eigen.alle() if w.id == "duur").handmatig is False
    assert eigen.alles_automatisch() == {"drempel": 1, "duur": 1}
    assert all(not w.handmatig and w.soort == w.auto for w in eigen.alle())
    assert not (service.DATA / "workouts" / eigen.INDELING).exists()


def test_handmatige_soort_telt_in_het_schema():
    eigen.importeer([("drempel.zwo", DREMPEL_ZWO)])  # 55 min, automatisch drempel
    eigen.zet_soort("drempel", "sweetspot")
    cfg = _cfg(weken=8, focus="sweetspot") | {"week": {"di": {"minuten": 60}, "do": {"minuten": 60},
                                                        "za": {"minuten": 180, "buiten": True}}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    assert any(s["naam"] == "Test drempel" and s["soort"] == "sweetspot" for s in plan)
    eigen.alles_automatisch()
    plan = planner.genereer(cfg, date(2026, 11, 9))
    assert not any(s["naam"] == "Test drempel" for s in plan)  # drempel past niet in een sweetspotblok


def test_verwijderen_ruimt_keuze_op():
    eigen.importeer([("drempel.zwo", DREMPEL_ZWO)])
    eigen.zet_soort("drempel", "tempo")
    assert eigen.verwijder("drempel")
    eigen.importeer([("drempel.zwo", DREMPEL_ZWO)])
    assert next(w for w in eigen.alle() if w.id == "drempel").handmatig is False


def test_indeling_via_scherm(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(VOORBEELD))
    monkeypatch.setattr(service, "sync_veilig", lambda *a: "")
    eigen.importeer([("drempel.zwo", DREMPEL_ZWO), ("vo2.zwo", VO2_ZWO)])
    c = TestClient(web.app)
    html = c.get("/bibliotheek").text
    assert "Alles automatisch indelen" in html and "Automatisch (Drempel)" in html
    # eigen workout staat ook in de sectie van zijn soort, gemarkeerd
    drempel_sectie = html.split(">Drempel <")[1].split("wx-heading")[0]
    assert "Test drempel" in drempel_sectie and "eigen ·" in drempel_sectie
    r = c.post("/eigen/soort", data={"id": "drempel", "soort": "sweetspot"}, follow_redirects=False)
    assert "zelf%20gekozen" in r.headers["location"]
    html = c.get("/bibliotheek").text
    assert "Test drempel" in html.split(">Sweetspot <")[1].split("wx-heading")[0] and "✎" in html
    r = c.post("/eigen/automatisch", follow_redirects=False)
    loc = r.headers["location"].replace("%20", " ").replace("%3A", ":").replace("%2C", ",")
    assert "Automatisch ingedeeld: 1 drempel, 1 vo2max" in loc or "Automatisch ingedeeld: 1 vo2max, 1 drempel" in loc
    assert all(not w.handmatig for w in eigen.alle())


# --- zwaarte ------------------------------------------------------------------------

def _vast(*stappen):
    return workouts.Training("x", "x", [workouts.Blok(None, [workouts.Stap(m, p) for m, p in stappen])])


def test_belasting_bekende_waarden():
    assert workouts.belasting(_vast((60, 100))) == (1.0, 100)   # een uur op FTP
    assert workouts.belasting(_vast((60, 70))) == (0.7, 49)
    assert workouts.belasting(_vast((30, 100), (30, 100))) == (1.0, 100)
    # 10 s sprint in een uur zone 2: het 30 s-gemiddelde dempt de piek
    met_sprint = workouts.Training("x", "x", [workouts.Blok(None, [
        workouts.Stap(30, 65), workouts.Stap(10 / 60, 200, vrij=True), workouts.Stap(30 - 10 / 60, 65)])])
    assert workouts.belasting(met_sprint)[0] < 0.70


@pytest.mark.parametrize("soort,minuten,score", [
    ("herstel", 60, 1), ("duur", 60, 2), ("sweetspot", 60, 3), ("drempel", 60, 4),
    ("vo2max", 60, 5), ("ftp_test", 40, 5), ("lange_rit", 150, 3), ("lange_rit", 240, 4)])
def test_zwaarte_schaal(soort, minuten, score):
    z = workouts.zwaarte(workouts.bouw(soort, minuten, 0.5, "opbouw"))
    assert z["score"] == score, (soort, z)


def test_zwaarte_in_bibliotheek(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(VOORBEELD))
    eigen.importeer([("vo2.zwo", VO2_ZWO)])
    html = TestClient(web.app).get("/bibliotheek").text
    # elke ingebouwde vorm, de eigen workout twee keer (bij zijn soort en in het eigen blok), de legenda
    assert html.count('class="fc-zwaarte z') == len(bibliotheek.catalogus(60)) + 2 + 1
    assert 'title="Zwaarte 1/5 · IF 0.52' in html  # herstel
    assert re.search(r'Zwaarte [1-5]/5 · IF \d\.\d\d · TSS \d+', html)


# --- wijzigingen in intervals.icu respecteren ------------------------------------

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


def test_jouw_wijzigingen_in_intervals_blijven_staan():
    kal = Kalender()
    ic = _client(kal)
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.sync(CFG, date(2026, 11, 9), ic)
    di, do, za = "fietscoach-2026-11-10", "fietscoach-2026-11-12", "fietscoach-2026-11-14"
    assert {di, do, za} <= set(kal.events)
    origineel_do = dict(kal.events[do])

    # Jij, in intervals.icu: dinsdag naar woensdag, donderdag andere naam, zaterdag weg.
    kal.events[di]["start_date_local"] = "2026-11-11T00:00:00"
    kal.events[do]["name"] = "Mijn eigen versie"
    kal.events.pop(za)

    melding = service.sync(CFG, date(2026, 11, 9), ic)
    assert "3 door jou gewijzigd" in melding
    assert kal.events[di]["start_date_local"] == "2026-11-11T00:00:00"  # niet teruggezet
    assert kal.events[do]["name"] == "Mijn eigen versie"                 # niet overschreven
    assert za not in kal.events                                          # niet opnieuw aangemaakt

    service.bijsturen(CFG, date(2026, 11, 9), ic, weer(date(2026, 11, 9)), ververs=False)
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-10"]["intervals_bewerkt"] == "verplaatst"
    assert any("verplaatst naar 11-11" in n for n in plan["2026-11-10"]["notities"])
    assert plan["2026-11-12"]["intervals_bewerkt"] == "aangepast"
    assert plan["2026-11-14"]["intervals_bewerkt"] == "verwijderd"

    # Nog een sync verandert niets aan jouw keuzes (ook niet als het plan zelf wijzigt).
    service.sync(CFG, date(2026, 11, 9), ic)
    assert kal.events[do]["name"] == "Mijn eigen versie" and za not in kal.events

    # Terug naar plan: de volgende sync zet het plan weer neer.
    assert service.terug_naar_plan("2026-11-12") and service.terug_naar_plan("2026-11-14")
    assert not service.terug_naar_plan("2026-11-13")
    service.sync(CFG, date(2026, 11, 9), ic)
    assert kal.events[do]["name"] == origineel_do["name"] and za in kal.events
    assert kal.events[di]["start_date_local"] == "2026-11-11T00:00:00"  # die blijft jouw keuze


def test_terug_naar_plan_via_scherm(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    kal = Kalender()
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(CFG))
    monkeypatch.setattr(service, "client", lambda cfg: _client(kal))
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 9))
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.sync(CFG, date(2026, 11, 9))
    kal.events["fietscoach-2026-11-10"]["name"] = "Anders"
    service.sync(CFG, date(2026, 11, 9))
    service.bijsturen(CFG, date(2026, 11, 9), ververs=False, weer_ophalen=False)
    html = TestClient(web.app).get("/").text
    assert "Terug naar plan" in html and "In intervals.icu aangepast (Anders)" in html
    r = TestClient(web.app).post("/terug-naar-plan", data={"datum": "2026-11-10"}, follow_redirects=False)
    assert r.status_code == 303 and "Terug%20naar%20plan" in r.headers["location"]
    assert "fietscoach-2026-11-10" not in service.laad_status()["intervals_bewerkt"]


# --- afwisseling op zwaarte -------------------------------------------------------

def _zw(s):
    return workouts.zwaarte(planner.training_voor(s))["score"]


@pytest.mark.parametrize("focus", ["gemengd", "gepolariseerd", "sweetspot"])
def test_zwaarte_loopt_op_en_max_een_vijf_per_week(focus):
    cfg = _cfg(weken=12, focus=focus) | {"week": {"di": {"minuten": 60}, "do": {"minuten": 60},
                                                   "za": {"minuten": 180, "buiten": True}}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    per_week = {}
    for s in plan:
        if s["soort"] in planner.DOELZWAARTE:
            per_week.setdefault(s["week"], []).append((s, _zw(s)))
    for wk, rij in per_week.items():
        assert sum(z == 5 for _, z in rij) <= 1, (wk, rij)
        for s, z in rij:
            if s["herstelweek"]:
                assert z <= 3
            assert abs(z - planner.doelzwaarte(s)) <= 1, (s["naam"], z, planner.doelzwaarte(s))
    eerste = [z for s, z in per_week[min(per_week)] if s["rol"] == "q0"]
    laatste = [z for s, z in per_week[max(per_week)] if s["rol"] == "q0"]
    assert laatste[0] >= eerste[0]


def test_eigen_vijf_alleen_als_het_doel_vijf_is():
    zwaar = _zwo("Zwaar eigen", '<Warmup Duration="600" PowerLow="0.5" PowerHigh="0.75"/>'
                 '<IntervalsT Repeat="8" OnDuration="180" OffDuration="120" OnPower="1.15" OffPower="0.5"/>'
                 '<Cooldown Duration="300" PowerLow="0.6" PowerHigh="0.45"/>')
    eigen.importeer([("zwaar.zwo", zwaar)])
    w = eigen.alle()[0]
    assert w.soort == "vo2max" and workouts.zwaarte(w.training)["score"] == 5 and round(w.minuten) == 55
    cfg = _cfg(weken=12, focus="gepolariseerd") | {"week": {"di": {"minuten": 60}, "za": {"minuten": 180, "buiten": True}}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    for s in plan:
        if s["soort"] == "vo2max" and s.get("keuze") == "e:zwaar":
            assert planner.doelzwaarte(s) == 5
    assert any(s.get("keuze") == "e:zwaar" for s in plan)  # en hij komt ook echt voorbij


def test_scherm_en_schema_kiezen_hetzelfde(monkeypatch):
    from fietscoach import web
    eigen.importeer([("drempel.zwo", DREMPEL_ZWO)])
    service.genereer(_cfg(weken=12, focus="gemengd"), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    for s in service.laad_plan():
        t = web._training(s)
        if t:
            assert t.naam == s["naam"] and t.beschrijving() == s["beschrijving"], s["datum"]


def test_zware_rpe_verlaagt_de_doelzwaarte():
    service.genereer(_cfg(weken=12, focus="gemengd"), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    plan = service.laad_plan()
    s = next(x for x in plan if x["soort"] == "vo2max" and x["rol"] == "q0" and x.get("pb", 0) >= 0.6)
    voor = planner.doelzwaarte(s)
    s["p_mod"] = -0.4  # zoals na een paar VO2-trainingen met RPE 10
    assert voor == 5 and planner.doelzwaarte(s) == 4
    s["p_mod"] = -0.3  # readiness matig
    assert planner.doelzwaarte(s) == 4
    s["p_mod"] = 0.3   # voelde te licht; 5 is het maximum
    assert planner.doelzwaarte(s) == 5


def test_doelzwaarte_rondt_gewoon_af():
    s = {"soort": "vo2max", "pb": 0.5}
    assert planner.doelzwaarte(s) == 5  # niet 4 (Python's round(0.5) == 0)


# --- voeding, TSS per week, ruilen ----------------------------------------------

def test_voedingsadvies_alleen_bij_lange_ritten():
    assert planner.voeding(60, 4) is None
    assert "water is genoeg" in planner.voeding(80, 2)
    assert "30–60 g" in planner.voeding(80, 3)
    assert "40–60 g" in planner.voeding(120, 2) and "totaal 80–120 g" in planner.voeding(120, 2)
    lang = planner.voeding(240, 2)
    assert "60–90 g" in lang and "bouw het op" in lang


def test_plan_heeft_tss_en_voeding():
    cfg = _cfg(weken=4) | {"week": {"di": {"minuten": 60}, "za": {"minuten": 180, "buiten": True}}}
    service.genereer(cfg, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    plan = service.laad_plan()
    za = next(s for s in plan if s["datum"] == "2026-11-14")
    assert za["tss"] > 100 and "koolhydraten" in za["voeding"]
    di = next(s for s in plan if s["datum"] == "2026-11-10")
    assert di["voeding"] is None and di["tss"] > 0


def test_schema_toont_tss_per_week(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 9))
    service.genereer(_cfg(weken=4), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    assert "TSS " in TestClient(web.app).get("/schema").text


def test_training_ruilen(monkeypatch):
    from fastapi.testclient import TestClient
    from fietscoach import web
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 10))
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(CFG))
    service.genereer(_cfg(weken=4), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    s = next(x for x in service.laad_plan() if x["datum"] == "2026-11-10")
    opties = web.ruilopties(s)
    assert ("s:herstel", "Lichter: herstelrit") in opties
    andere = next(k for k, _ in opties if k.startswith("v:") and k != s.get("keuze"))
    service.zet_ruil("2026-11-10", andere)
    service.bijsturen(CFG, date(2026, 11, 10), ververs=False, weer_ophalen=False)
    na = next(x for x in service.laad_plan() if x["datum"] == "2026-11-10")
    assert na["ruil"] == andere and "Zelf gekozen training" in na["notities"]
    t = planner.training_voor(na)
    assert t.naam == na["naam"] and na["keuze"] == andere
    service.zet_ruil("2026-11-10", "s:herstel")
    service.bijsturen(CFG, date(2026, 11, 10), ververs=False, weer_ophalen=False)
    na = next(x for x in service.laad_plan() if x["datum"] == "2026-11-10")
    assert na["soort"] == "herstel"
    r = TestClient(web.app).post("/ruil", data={"datum": "2026-11-10", "keuze": "x;rm"}, follow_redirects=False)
    assert "Onbekende" in r.headers["location"].replace("%20", " ")
    TestClient(web.app).post("/ruil", data={"datum": "2026-11-10", "keuze": "auto"})
    assert "2026-11-10" not in service.laad_feedback()["ruil"]
