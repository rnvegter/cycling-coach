from helpers import *  # noqa: F403


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

