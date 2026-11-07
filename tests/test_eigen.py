from helpers import *  # noqa: F403


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

