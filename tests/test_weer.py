from helpers import *  # noqa: F403


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

