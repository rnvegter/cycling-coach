from helpers import *  # noqa: F403

from fietscoach import grafiek, inzicht, melding


def _fitheid(vandaag, dagen=30, ctl=40.0, atl=45.0):
    return [[(vandaag - timedelta(days=dagen - 1 - i)).isoformat(), ctl, atl] for i in range(dagen)]


# --- fitheidsverloop en grafiek --------------------------------------------------

def test_fitheid_vooruitblik_volgt_het_schema():
    v = date(2026, 11, 10)
    service.genereer(_cfg(weken=8), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    plan = service.laad_plan()
    status = {"fitheid": _fitheid(v, ctl=40, atl=45)}
    r = inzicht.fitheidsverloop(status, plan, v)
    gemeten = [x for x in r if not x["voorspeld"]]
    voorspeld = [x for x in r if x["voorspeld"]]
    assert len(gemeten) == 29 and voorspeld[0]["datum"] == v.isoformat()  # vandaag nog te rijden
    assert voorspeld[-1]["datum"] <= (v + timedelta(days=84)).isoformat()
    # Zonder training zakt fitheid; met het schema blijft het bergop of gelijk.
    leeg = inzicht.fitheidsverloop(status, [], v)
    assert leeg == [x for x in leeg if not x["voorspeld"]]
    assert max(x["fit"] for x in voorspeld) > 40
    # Rustdag: alleen afname, met de tijdconstanten van intervals.icu.
    rust = next(x for x in voorspeld if x["tss"] == 0)
    vorige = r[r.index(rust) - 1]
    assert abs(rust["fit"] - vorige["fit"] * (1 - inzicht.K_FIT)) < 0.11


def test_fitheid_zonder_gegevens():
    assert inzicht.fitheidsverloop({}, [], date(2026, 11, 10)) == []
    assert grafiek.fitheid([], date(2026, 11, 10)) is None


def test_grafiek_geometrie():
    v = date(2026, 11, 10)
    service.genereer(_cfg(weken=8), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    r = inzicht.fitheidsverloop({"fitheid": _fitheid(v, dagen=50)}, service.laad_plan(), v)
    g = grafiek.fitheid(r, v, evenement="2026-12-20")
    for lijn in ("fit", "moe", "vorm"):
        for p in (g[lijn]["gemeten"] + " " + g[lijn]["voorspeld"]).split():
            x, y = map(float, p.split(","))
            assert 0 <= x <= 100 and 0 <= y <= 100
    assert g["yticks"][0]["tekst"] == 0 and g["yticks"][-1]["y"] == 0
    assert 0 < g["vandaag"] < 100 and 0 < g["evenement"] < 100 and 0 <= g["nul"] <= 100
    assert [lab["tekst"] for lab in g["xlabels"]][:2] == ["okt", "nov"]
    assert len(g["data"]) == len(r)


def test_schema_toont_grafiek(monkeypatch):
    from fastapi.testclient import TestClient

    from fietscoach import web
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 10))
    service.genereer(_cfg(weken=8), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    st = service.laad_status() | {"fitheid": _fitheid(date(2026, 11, 10))}
    service._schrijf("status.json", st)
    html = TestClient(web.app).get("/schema").text
    assert "Fitheid en vorm" in html and "fc-l--voorspeld" in html and "Als tabel" in html


def test_bijsturen_bewaart_fitheid_en_houdt_wellness_kort():
    class Lang(NepServer):
        def __call__(self, req):
            if req.url.path.endswith("/wellness"):
                return httpx.Response(200, json=[
                    {"id": (date(2026, 11, 10) - timedelta(days=89 - i)).isoformat(), "ctl": 30 + i / 10, "atl": 35,
                     "hrv": 50} for i in range(90)])
            return super().__call__(req)
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service.bijsturen(CFG, date(2026, 11, 10), _client(Lang()), weer(date(2026, 11, 10)))
    st = service.laad_status()
    assert len(st["fitheid"]) == 90 and len(st["wellness"]) == 29


# --- FTP ----------------------------------------------------------------------

def test_ftp_hint():
    assert inzicht.ftp_hint({"ftp": 220, "eftp": 231})["richting"] == "hoger"
    assert inzicht.ftp_hint({"ftp": 220, "eftp": 173})["richting"] == "lager"
    assert inzicht.ftp_hint({"ftp": 220, "eftp": 215}) is None
    assert inzicht.ftp_hint({"ftp": None, "eftp": 215}) is None


def test_ftp_terugschrijven(monkeypatch):
    from fastapi.testclient import TestClient

    from fietscoach import web
    server = NepServer()
    monkeypatch.setattr(service, "client", lambda cfg: _client(server))
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(CFG))
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 10))
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    service._schrijf("status.json", {"ftp": 220, "eftp": 231})
    html = TestClient(web.app).get("/").text
    assert "Zet FTP op 231 W" in html
    r = TestClient(web.app).post("/ftp", data={"ftp": "231"}, follow_redirects=False)
    assert "231" in r.headers["location"]
    put = next(q for q in server.verzoeken if q.method == "PUT")
    assert put.url.path == "/api/v1/athlete/0/sport-settings/Ride" and _json.loads(put.content) == {"ftp": 231}
    st = service.laad_status()
    assert st["ftp"] == 231 and st["ftp_gezet"]["van"] == 220
    html = TestClient(web.app).get("/").text
    assert "Zet hem in Zwift en op je Wahoo ook op 231 W" in html
    r = TestClient(web.app).post("/ftp", data={"ftp": "9999"}, follow_redirects=False)
    assert "niet aangepast" in r.headers["location"].replace("%20", " ")


# --- weekterugblik -----------------------------------------------------------------

def test_weekterugblik():
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    plan = service.laad_plan()
    week = [s for s in plan if "2026-11-09" <= s["datum"] <= "2026-11-15" and s["soort"] != "rust"]
    week[0]["status"] = "gedaan"
    week[1]["status"] = "gemist"
    status = {"ritten": {week[0]["datum"]: {"minuten": 62, "load": 55},
                         "2026-11-11": {"minuten": 30, "load": 20}},
              "fitheid": [["2026-11-08", 40.0, 40.0], ["2026-11-15", 43.4, 50.0]]}
    fb = {"rpe": {week[0]["datum"]: 6}}
    w = inzicht.weekterugblik(plan, status, fb, date(2026, 11, 9))
    assert w["gepland"] == len(week) and w["gedaan"] == 1 and len(w["gemist"]) == 1
    assert w["tss_gereden"] == 75 and w["minuten_gereden"] == 92 and w["rpe"] == 6 and w["fit_verschil"] == 3
    assert "Plus 1 rit buiten het schema" in w["oordeel"]
    assert w["volgende"]["trainingen"] > 0 and w["volgende"]["zwaarste"]
    titel, tekst = inzicht.weektekst(w, planner.FOCUSNAAM)
    assert titel.startswith("Week 09-11") and "Fitheid 40 → 43 (+3)" in tekst and "Volgende week" in tekst


def test_terugblik_op_maandag_op_vandaag(monkeypatch):
    from fastapi.testclient import TestClient

    from fietscoach import web
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 16))
    assert "Vorige week" in TestClient(web.app).get("/").text
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 18))
    assert "Vorige week" not in TestClient(web.app).get("/").text


# --- berichten ------------------------------------------------------------------------

def test_ochtendtekst():
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    plan = service.laad_plan()
    za = next(s for s in plan if s["datum"] == "2026-11-14")
    za.update(omgeving="buiten", weer="8–10 °C, droog")
    titel, tekst = inzicht.ochtendtekst(plan, {"ftp": 220, "eftp": 240}, {"rpe": {}}, date(2026, 11, 14))
    assert titel.startswith("Vandaag: ") and "buiten" in titel
    assert "Weer: 8–10 °C" in tekst and "koolhydraten" in tekst and "eFTP" in tekst and "readiness" in tekst
    assert inzicht.ochtendtekst(plan, {}, {"rpe": {}}, date(2026, 11, 9)) is None  # maandag = rust


def test_stuur_naar_ntfy_en_telegram():
    verzoeken = []

    def server(req):
        verzoeken.append(req)
        return httpx.Response(200, json={})
    cfg = {"berichten": {"app_url": "https://fc.example/", "ntfy": {"url": "https://ntfy.example", "topic": "geheim-x",
                                                                     "token": "tk"},
                         "telegram": {"token": "123:AB", "chat_id": "42"}}}
    uit = melding.stuur(cfg, "Vandaag: Sweetspot – 3×10", "regel", "/", httpx.Client(transport=httpx.MockTransport(server)))
    assert [(k, ok) for k, ok, _ in uit] == [("ntfy", True), ("telegram", True)]
    n, t = verzoeken
    assert n.url == "https://ntfy.example" and n.headers["authorization"] == "Bearer tk"
    body = _json.loads(n.content)
    assert body == {"topic": "geheim-x", "title": "Vandaag: Sweetspot – 3×10", "message": "regel",
                    "tags": ["bike"], "click": "https://fc.example/"}
    assert t.url.path == "/bot123:AB/sendMessage" and _json.loads(t.content)["chat_id"] == "42"


def test_stuur_meldt_fouten_zonder_geheimen():
    cfg = {"berichten": {"telegram": {"token": "123:GEHEIM", "chat_id": "42"}}}
    c = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(401)))
    [(k, ok, uitleg)] = melding.stuur(cfg, "t", "x", client=c)
    assert not ok and uitleg == "HTTP 401" and "GEHEIM" not in uitleg
    assert melding.kanalen({}) == [] and melding.kanalen({"berichten": {"ntfy": {"topic": ""}}}) == []


def test_ochtendbericht_aan_uit_en_test(monkeypatch):
    from fastapi.testclient import TestClient

    from fietscoach import web
    verstuurd = []
    monkeypatch.setattr(melding, "stuur", lambda cfg, titel, tekst, pad="/", **kw: verstuurd.append(titel) or [("ntfy", True, "verstuurd")])
    cfg = dict(CFG) | {"berichten": {"ntfy": {"topic": "x"}}}
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(cfg))
    service.genereer(CFG, date(2026, 11, 9), vandaag=date(2026, 11, 8))
    assert service.ochtendbericht(cfg, date(2026, 11, 9)).startswith("Rustdag")
    assert "ntfy ✓" in service.ochtendbericht(cfg, date(2026, 11, 10)) and verstuurd[-1].startswith("Vandaag")
    assert service.laad_status()["bericht_ochtend"]["ok"]
    assert service.ochtendbericht(cfg | {"berichten_aan": {"ochtend": False}}, date(2026, 11, 10)) == "Ochtendbericht staat uit."
    html = TestClient(web.app).get("/instellingen").text
    assert "Testbericht sturen" in html and "Via ntfy" in html
    r = TestClient(web.app).post("/berichten", data={"ochtend": "1", "test": "1"}, follow_redirects=False)
    assert "Testbericht" in r.headers["location"].replace("%20", " ")
    assert service._lees("instellingen.json", {})["berichten_aan"] == {"ochtend": True, "week": False}


def test_dagelijks_breekt_niet_op_bericht(monkeypatch, capsys):
    from fietscoach import cli
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(CFG))
    monkeypatch.setattr(service, "bijsturen", lambda cfg: ["ok"])
    monkeypatch.setattr(service, "sync", lambda cfg: "gesynct")
    monkeypatch.setattr(service, "ochtendbericht", lambda cfg: 1 / 0)
    monkeypatch.setattr("sys.argv", ["fietscoach", "dagelijks"])
    cli.main()
    assert "Ochtendbericht mislukt" in capsys.readouterr().out


# --- installeerbare app -------------------------------------------------------------

def test_pwa():
    from fastapi.testclient import TestClient

    from fietscoach import web
    c = TestClient(web.app)
    m = c.get("/static/manifest.webmanifest")
    assert m.status_code == 200 and _json.loads(m.text)["start_url"] == "/"
    for icoon in _json.loads(m.text)["icons"]:
        assert c.get(icoon["src"]).status_code == 200
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"] and "skipWaiting" in sw.text
    html = c.get("/").text
    assert 'rel="manifest"' in html and "serviceWorker" in html and 'crossorigin="use-credentials"' in html


def test_ophalen_elk_uur_zonder_bericht(monkeypatch, capsys):
    from fietscoach import cli
    aangeroepen = []
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(CFG))
    monkeypatch.setattr(service, "pas_toe", lambda cfg: aangeroepen.append("pas_toe") or "")
    monkeypatch.setattr(service, "ochtendbericht", lambda *a, **k: aangeroepen.append("bericht"))
    monkeypatch.setattr("sys.argv", ["fietscoach", "ophalen"])
    cli.main()
    assert aangeroepen == ["pas_toe"] and "Opgehaald" in capsys.readouterr().out
