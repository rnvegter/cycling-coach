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
    assert any(s["soort"] == "ftp_test" for s in wk4)
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
    assert r.status_code == 200 and "<IntervalsT" in r.text


# --- bibliotheek ------------------------------------------------------------------

from fietscoach import bibliotheek  # noqa: E402

STAP_RPM = re.compile(r"^- (\d+m)?(\d+s)? (ramp \d+-\d+%|\d+%)( \d+rpm)?$")


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
