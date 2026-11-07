from helpers import *  # noqa: F403


def test_belasting_bekende_waarden():
    assert workouts.belasting(_vast((60, 100))) == (1.0, 100)   # een uur op FTP
    assert workouts.belasting(_vast((60, 70))) == (0.7, 49)
    assert workouts.belasting(_vast((30, 100), (30, 100))) == (1.0, 100)
    # 10 s sprint in een uur zone 2: het 30 s-gemiddelde dempt de piek
    met_sprint = workouts.Training("x", "x", [workouts.Blok(None, [
        workouts.Stap(30, 65), workouts.Stap(10 / 60, 200, vrij=True), workouts.Stap(30 - 10 / 60, 65)])])
    assert workouts.belasting(met_sprint)[0] < 0.70



@pytest.mark.parametrize("soort,minuten,score", [
    ("herstel", 60, 1), ("duur", 60, 2), ("sweetspot", 60, 3), ("drempel", 60, 4),
    ("vo2max", 60, 5), ("ftp_test", 40, 5), ("lange_rit", 150, 3), ("lange_rit", 240, 4)])
def test_zwaarte_schaal(soort, minuten, score):
    z = workouts.zwaarte(workouts.bouw(soort, minuten, 0.5, "opbouw"))
    assert z["score"] == score, (soort, z)



def test_zwaarte_in_bibliotheek(monkeypatch):
    from fastapi.testclient import TestClient

    from fietscoach import web
    monkeypatch.setattr(service, "laad_config", lambda *a: dict(VOORBEELD))
    eigen.importeer([("vo2.zwo", VO2_ZWO)])
    html = TestClient(web.app).get("/bibliotheek").text
    # elke ingebouwde vorm, de eigen workout twee keer (bij zijn soort en in het eigen blok), de legenda
    assert html.count('class="fc-zwaarte z') == len(bibliotheek.catalogus(60)) + 2 + 1
    assert 'title="Zwaarte 1/5 · IF 0.52' in html  # herstel
    assert re.search(r'Zwaarte [1-5]/5 · IF \d\.\d\d · TSS \d+', html)



@pytest.mark.parametrize("focus", ["gemengd", "gepolariseerd", "sweetspot"])
def test_zwaarte_loopt_op_en_max_een_vijf_per_week(focus):
    cfg = _cfg(weken=12, focus=focus) | {"week": {"di": {"minuten": 60}, "do": {"minuten": 60},
                                                   "za": {"minuten": 180, "buiten": True}}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    per_week = {}
    for s in plan:
        if s["soort"] in planner.DOELZWAARTE:
            per_week.setdefault(s["week"], []).append((s, _zw(s)))
    for wk, rij in per_week.items():
        assert sum(z == 5 for _, z in rij) <= 1, (wk, rij)
        for s, z in rij:
            if s["herstelweek"]:
                assert z <= 3
            assert abs(z - planner.doelzwaarte(s)) <= 1, (s["naam"], z, planner.doelzwaarte(s))
    eerste = [z for s, z in per_week[min(per_week)] if s["rol"] == "q0"]
    laatste = [z for s, z in per_week[max(per_week)] if s["rol"] == "q0"]
    assert laatste[0] >= eerste[0]



def test_eigen_vijf_alleen_als_het_doel_vijf_is():
    zwaar = _zwo("Zwaar eigen", '<Warmup Duration="600" PowerLow="0.5" PowerHigh="0.75"/>'
                 '<IntervalsT Repeat="8" OnDuration="180" OffDuration="120" OnPower="1.15" OffPower="0.5"/>'
                 '<Cooldown Duration="300" PowerLow="0.6" PowerHigh="0.45"/>')
    eigen.importeer([("zwaar.zwo", zwaar)])
    w = eigen.alle()[0]
    assert w.soort == "vo2max" and workouts.zwaarte(w.training)["score"] == 5 and round(w.minuten) == 55
    cfg = _cfg(weken=12, focus="gepolariseerd") | {"week": {"di": {"minuten": 60}, "za": {"minuten": 180, "buiten": True}}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    for s in plan:
        if s["soort"] == "vo2max" and s.get("keuze") == "e:zwaar":
            assert planner.doelzwaarte(s) == 5
    assert any(s.get("keuze") == "e:zwaar" for s in plan)  # en hij komt ook echt voorbij



def test_scherm_en_schema_kiezen_hetzelfde(monkeypatch):
    from fietscoach import web
    eigen.importeer([("drempel.zwo", DREMPEL_ZWO)])
    service.genereer(_cfg(weken=12, focus="gemengd"), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    for s in service.laad_plan():
        t = web._training(s)
        if t:
            assert t.naam == s["naam"] and t.beschrijving() == s["beschrijving"], s["datum"]



def test_zware_rpe_verlaagt_de_doelzwaarte():
    service.genereer(_cfg(weken=12, focus="gemengd"), date(2026, 11, 9), vandaag=date(2026, 11, 8))
    plan = service.laad_plan()
    s = next(x for x in plan if x["soort"] == "vo2max" and x["rol"] == "q0" and x.get("pb", 0) >= 0.6)
    voor = planner.doelzwaarte(s)
    s["p_mod"] = -0.4  # zoals na een paar VO2-trainingen met RPE 10
    assert voor == 5 and planner.doelzwaarte(s) == 4
    s["p_mod"] = -0.3  # readiness matig
    assert planner.doelzwaarte(s) == 4
    s["p_mod"] = 0.3   # voelde te licht; 5 is het maximum
    assert planner.doelzwaarte(s) == 5



def test_doelzwaarte_rondt_gewoon_af():
    s = {"soort": "vo2max", "pb": 0.5}
    assert planner.doelzwaarte(s) == 5  # niet 4 (Python's round(0.5) == 0)

