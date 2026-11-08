from helpers import *  # noqa: F403


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



# --- rit van vandaag ---------------------------------------------------------------

def test_rit_van_vandaag_telt_meteen_na_bijsturen():
    """Bug: Bijsturen haalde ritten op tot en met gisteren (intervals.icu geeft
    activiteiten tot de dag vóór 'newest'), en markeerde alleen dagen vóór vandaag.
    Een rit van vandaag bleef dus tot morgen 'gepland'."""
    kal = Kalender()

    class MetRitVandaag(type(kal)):
        def __call__(self, req):
            if req.url.path.endswith("/activities"):
                self.newest = req.url.params["newest"]
                # zoals intervals.icu: tot de dag vóór newest
                ritten = [{"id": "i9", "start_date_local": "2026-11-10T18:40:00", "type": "VirtualRide",
                           "moving_time": 3600, "icu_training_load": 58, "icu_intensity": 84,
                           "paired_event_id": 101}]
                return httpx.Response(200, json=[r for r in ritten if r["start_date_local"][:10] < self.newest])
            return super().__call__(req)

    server = MetRitVandaag()
    ic = _client(server)
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.sync(CFG, date(2026, 11, 10), ic)
    assert "fietscoach-2026-11-10" in server.events
    service.bijsturen(CFG, date(2026, 11, 10), ic, weer(date(2026, 11, 10)))
    di = next(s for s in service.laad_plan() if s["datum"] == "2026-11-10")
    assert server.newest == "2026-11-11"
    assert di["status"] == "gedaan" and di["score"]
    # De sync laat de training van vandaag staan: intervals.icu heeft je rit eraan gekoppeld.
    service.sync(CFG, date(2026, 11, 10), ic)
    assert "fietscoach-2026-11-10" in server.events


def test_vandaag_zonder_rit_blijft_gepland():
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.bijsturen(CFG, date(2026, 11, 10), NepIntervals([]), weer(date(2026, 11, 10)))
    di = next(s for s in service.laad_plan() if s["datum"] == "2026-11-10")
    assert di["status"] == "gepland"
    # gereden: meteen afgerond
    service.bijsturen(CFG, date(2026, 11, 10), NepIntervals(["2026-11-10"]), weer(date(2026, 11, 10)))
    di = next(s for s in service.laad_plan() if s["datum"] == "2026-11-10")
    assert di["status"] == "gedaan"
