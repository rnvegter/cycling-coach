from helpers import *  # noqa: F403


def test_rooktest_alles_groen_en_opname_zonder_persoonsgegevens(monkeypatch, tmp_path):
    from fietscoach import rooktest
    kal = ProefKalender()
    monkeypatch.setattr(service, "client", lambda cfg: _client(kal))
    monkeypatch.setattr(rooktest.sys, "version_info", (3, 13))
    monkeypatch.setattr("httpx.get", lambda *a, **kw: httpx.Response(
        200, json=_openmeteo(), request=httpx.Request("GET", "https://api.open-meteo.com")))
    map_ = tmp_path / "opname"
    regels = rooktest.rooktest(CFG, map_)
    tekst = "\n".join(r for _, r in regels)
    fout = [r for ok, r in regels if not ok and not r.startswith("Tijdzone")]
    assert not fout, tekst
    assert "Proeftraining begrepen" in tekst and "Proeftraining weer verwijderd" in tekst
    assert rooktest.PROEF_ID not in kal.events
    bestanden = {p.name for p in map_.glob("*.json")}
    assert {"atleet.json", "wellness.json", "activities.json", "openmeteo.json", "event_proef.json"} <= bestanden
    alles = "".join(p.read_text() for p in map_.glob("*.json"))
    assert "52.38" not in alles and "geheim" not in alles
    assert _json.loads((map_ / "atleet.json").read_text()).get("name") in (None, "<weg>")



def test_rooktest_meldt_kapotte_sleutel(monkeypatch):
    from fietscoach import rooktest
    monkeypatch.setattr(service, "client", lambda cfg: _client(NepServer(status=401)))
    monkeypatch.setattr("httpx.get", lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("weg")))
    regels = rooktest.rooktest(CFG)
    assert any(not ok and "sleutel klopt niet" in r for ok, r in regels)
    assert any(not ok and r.startswith("Weer") for ok, r in regels)



def test_anoniem():
    from fietscoach import rooktest
    x = rooktest.anoniem({"name": "Niels", "id": "i788828", "icu_training_load": 50,
                          "start_latlng": [52.1, 4.6], "sub": [{"email": "a@b"}] * 40})
    assert x["name"] == "<weg>" and x["id"] == "i0" and x["icu_training_load"] == 50
    assert x["start_latlng"] == "<weg>" and len(x["sub"]) == 15 and x["sub"][0]["email"] == "<weg>"



@pytest.mark.skipif(not ECHT.is_dir(), reason="nog geen opgenomen antwoorden (fietscoach rooktest --opname)")
def test_opgenomen_antwoorden_worden_begrepen():
    """Draait op echte (geanonimiseerde) antwoorden van intervals.icu en Open-Meteo."""
    from fietscoach import intervals as iv
    from fietscoach import weather as wt
    lees = lambda n: _json.loads((ECHT / n).read_text()) if (ECHT / n).exists() else None  # noqa: E731
    if (a := lees("activities.json")) is not None:
        ritten = adapt.ritten_per_dag(a)
        for r in ritten.values():
            assert r["minuten"] >= 0
    if (w := lees("wellness.json")) is not None:
        met = [x for x in w if x.get("ctl") is not None]
        assert not met or iv.eftp_uit(met[-1]) is None or iv.eftp_uit(met[-1]) > 50
    if (o := lees("openmeteo.json")) is not None:
        v = wt.uit_json(o)
        d = next(iter(v.dag))
        assert v.venster(d, "10:00", 90)

