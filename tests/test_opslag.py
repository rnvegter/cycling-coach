from helpers import *  # noqa: F403


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



def test_migratie_van_oude_installatie(tmp_path):
    oud = [{"datum": "2026-11-10", "basis_soort": "duur", "basis_minuten": 60, "soort": "herstel",
            "minuten": 45, "notities": ["x"], "status": "gepland"}]
    (tmp_path / "plan.json").write_text(_json.dumps(oud))
    (tmp_path / "feedback.json").write_text(_json.dumps({"rpe": {}}))
    assert service.gegevensversie() == 0
    log = service.migreer()
    assert len(log) == 2 and service.gegevensversie() == service.SCHEMA
    assert service.laad_basis()[0]["soort"] == "duur"
    assert _json.loads((tmp_path / "feedback.json").read_text())["ruil"] == {}
    assert service.migreer() == []  # tweede keer niets



def test_nieuwe_installatie_krijgt_huidige_versie(tmp_path):
    service.genereer(_cfg(weken=4), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    assert _json.loads((tmp_path / "versie.json").read_text())["schema"] == service.SCHEMA



def test_gegevens_van_nieuwere_versie_weigeren(tmp_path):
    (tmp_path / "versie.json").write_text(_json.dumps({"schema": service.SCHEMA + 1}))
    with pytest.raises(service.DataTeNieuw):
        service.migreer()



def test_geschiedenis_legt_uit_waarom(monkeypatch):
    from fastapi.testclient import TestClient

    from fietscoach import web
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 10))
    service.genereer(_cfg(weken=4), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    assert service.geschiedenis() == []  # eerste schema: niets te vergelijken
    cfg = _cfg(weken=4) | {"uitzonderingen": {"2026-11-12": 30}}
    service.bijsturen(cfg, date(2026, 11, 10), ververs=False, weer_ophalen=False)
    w = service.waarom_per_dag()
    assert "2026-11-12" in w and w["2026-11-12"][0]["van"] != w["2026-11-12"][0]["naar"]
    assert "Waarom zo?" in TestClient(web.app).get("/").text
    service.genereer(_cfg(weken=4), date(2026, 11, 9), vandaag=date(2026, 11, 10))
    assert service.geschiedenis()[-1]["waarom"] == ["Nieuw schema gemaakt"]
    assert service.waarom_per_dag() == {}



def test_geschiedenis_blijft_klein(monkeypatch):
    monkeypatch.setattr(service, "MAX_GESCHIEDENIS", 10)
    for i in range(30):
        service.schrijf_geschiedenis([{"tijd": "2026-11-10T08:00:00", "datum": "2026-11-11",
                                       "van": "a", "naar": str(i), "waarom": ["x"]}])
    assert len(service.geschiedenis()) <= 12 and service.geschiedenis()[-1]["naar"] == "29"

