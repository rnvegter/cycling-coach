from helpers import *  # noqa: F403


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

