from helpers import *  # noqa: F403


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
    assert "FTP-test gereden" in html and "281 W" in html and "Zet FTP op 281 W" in html
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
    # dinsdag 60 min op Zwift: geen eten, wel drinken (binnen zweet je meer)
    assert "water is genoeg" in di["voeding"] and "0,8–1 liter" in di["voeding"] and di["tss"] > 0



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



# --- extra training ------------------------------------------------------------------

def test_extra_training_toevoegen_en_weghalen(monkeypatch):
    from fastapi.testclient import TestClient

    from fietscoach import web
    kal = Kalender()
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(CFG))
    monkeypatch.setattr(service, "client", lambda cfg: _client(kal))
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 9))
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    c = TestClient(web.app)
    assert "Extra training" in c.get("/").text

    # Vrijdag 13-11 is vrij: sweetspot op Zwift erbij.
    r = c.post("/extra", data={"datum": "2026-11-13", "minuten": "45", "soort": "sweetspot", "omgeving": "binnen"},
               follow_redirects=False)
    assert "toegevoegd" in r.headers["location"]
    vr = next(s for s in service.laad_plan() if s["datum"] == "2026-11-13")
    assert vr["soort"] == "sweetspot" and vr["omgeving"] == "binnen" and vr["handmatig"] and vr["tss"] > 0
    assert vr["week"] == 1 and "Extra training, zelf toegevoegd" in vr["notities"]
    # donderdag 12-11 is tempo: waarschuwing voor twee intensieve dagen achter elkaar
    assert any("Gisteren staat ook een intensieve training" in n for n in vr["notities"])
    service.sync(CFG, date(2026, 11, 9))
    assert "fietscoach-2026-11-13" in kal.events
    assert "Extra training weghalen" in c.get("/schema").text

    # Op een dag met een training: weigeren.
    r = c.post("/extra", data={"datum": "2026-11-10", "minuten": "60", "soort": "duur"}, follow_redirects=False)
    assert "Niet toegevoegd" in r.headers["location"].replace("%20", " ")
    # Te ver vooruit of onzin
    assert service.zet_extra("2026-12-31", 60, vandaag=date(2026, 11, 9))
    assert service.zet_extra("2026-11-13", 5, vandaag=date(2026, 11, 9))

    # Weghalen, ook uit intervals.icu
    r = c.post("/extra", data={"datum": "2026-11-13", "weg": "1", "terug": "https://elders.example"},
               follow_redirects=False)
    assert r.headers["location"].startswith("/?")
    assert not any(s["datum"] == "2026-11-13" for s in service.laad_plan())
    service.sync(CFG, date(2026, 11, 9))
    assert "fietscoach-2026-11-13" not in kal.events


def test_extra_duurrit_wordt_niet_gekaapt_en_buiten_blijft_buiten():
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.zet_extra("2026-11-13", 60, "duur", "buiten", vandaag=date(2026, 11, 9))
    # dinsdag-sweetspot gemist: die mag niet naar de zelf toegevoegde vrijdag
    plan = {s["datum"]: s for s in service.laad_plan()}
    ritten = {}
    status = {"ritten": ritten}
    service._schrijf("status.json", status)
    service.bijsturen(CFG, date(2026, 11, 11), ververs=False,
                      verwachting=lambda d, m: {"temp_min": 3, "temp_max": 6, "neerslag_mm": 9, "neerslagkans": 95,
                                                "wind_kmh": 20})
    plan = {s["datum"]: s for s in service.laad_plan()}
    vr = plan["2026-11-13"]
    assert vr["soort"] == "duur" and vr["omgeving"] == "buiten"
    assert any(n.startswith("Let op het weer") for n in vr["notities"])


def test_voeding_binnen_en_cwem_link_voor_buiten(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from fietscoach import inzicht
    assert planner.voeding(40, 3, binnen=True) is None
    binnen = planner.voeding(60, 4, binnen=True)
    assert "ventilator" in binnen and "elektrolyten" in binnen
    assert planner.voeding(60, 4) is None  # buiten pas vanaf 75 min
    assert "1–1,5 liter" in planner.voeding(120, 2)

    s = {"datum": "2026-11-14", "minuten": 135, "duur": 135, "zwaarte": 3, "naam": "Lange rit 2u15"}
    url = planner.cwem_link(s, "https://cwem.example/", "09:30")
    u = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert u.fragment == "ride" and q == {"date": "2026-11-14", "time": "09:30", "hours": "2.25",
                                          "pace": "steady", "effort": "3", "name": "Lange rit 2u15"}
    assert "pace=hard" in planner.cwem_link(s | {"zwaarte": 5}, "https://c", "18:30")
    assert "pace=easy" in planner.cwem_link(s | {"zwaarte": 1}, "https://c", "18:30")

    # Ochtendbericht: buiten de cwem-link in plaats van de eigen regel.
    plan = [s | {"soort": "lange_rit", "status": "gepland", "omgeving": "buiten", "voeding": "Voeding: x",
                 "notities": []}]
    _, tekst = inzicht.ochtendtekst(plan, {}, {"rpe": {}}, date(2026, 11, 14), url)
    assert "Kleding, eten en drinken: https://cwem.example/?" in tekst and "Voeding: x" not in tekst
    _, tekst = inzicht.ochtendtekst(plan, {}, {"rpe": {}}, date(2026, 11, 14))
    assert "Voeding: x" in tekst


def test_groen_vinkje_bij_afgeronde_rit(monkeypatch):
    from fastapi.testclient import TestClient

    from fietscoach import web
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 13))
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    # dinsdag gereden (gekoppeld in intervals.icu), donderdag niet
    service._schrijf("status.json", {"ritten": {"2026-11-10": {"minuten": 60, "load": 55, "if": 0.8,
                                                               "rpe": None, "naam": "Zwift", "gepaard": True}}})
    service.bijsturen(CFG, date(2026, 11, 13), ververs=False, weer_ophalen=False)
    html = TestClient(web.app).get("/schema").text
    assert html.count("fc-klaar") == 1 and html.count(">Afgerond</b>") == 1
    i = html.index(">Afgerond</b>")
    assert "di 10-11" in html[i - 900:i].lower()
    # woensdag en donderdag zijn voorbij en niet gereden
    assert html.count(">Overgeslagen</b>") == 2 and "Gemist" not in html


def test_vandaag_toont_afgerond_na_rit(monkeypatch):
    from fastapi.testclient import TestClient

    from fietscoach import web
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 10))
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.bijsturen(CFG, date(2026, 11, 10), NepIntervals(["2026-11-10"]), weer(date(2026, 11, 10)))
    html = TestClient(web.app).get("/").text
    assert ">Afgerond</b> · score" in html and "vergeet je RPE niet" in html
    assert "Duur aanpassen" not in html.split("Deze week")[0]
