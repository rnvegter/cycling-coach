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

    def verwijder(self, i):
        self.deleted.append(i)


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
    assert ic.deleted == [1]
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
