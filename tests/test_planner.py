from helpers import *  # noqa: F403


def test_syntax_alle_trainingen():
    for soort in workouts.BOUWERS:
        for m in (45, 60, 75, 90, 180):
            for p in (0, 0.5, 1):
                t = workouts.bouw(soort, m, p, "opbouw")
                for regel in t.beschrijving().splitlines():
                    if regel.startswith("-"):
                        assert STAP.match(regel), (soort, regel)
                if soort not in ("ftp_test",):
                    assert abs(t.minuten - max(m, 40 if soort == "openers" else 0)) <= 6, (soort, m, t.minuten)



def test_dagrollen():
    r = planner.dagrollen(CFG["week"], 2)
    named = {planner.DAGEN[i]: v for i, v in r.items()}
    assert named["za"] == "lang"
    assert sum(v.startswith("q") for v in named.values()) == 2
    assert "vr" not in named and "ma" not in named
    assert named["zo"] == "duur"  # geen intervallen direct na de lange rit



def test_plan():
    plan = planner.genereer(CFG, date(2026, 11, 11))
    assert plan[0]["datum"] == "2026-11-10"  # di van de week van 9 nov
    assert len(plan) == 12 * 5
    wk4 = [s for s in plan if s["week"] == 4]
    assert all(s["herstelweek"] for s in wk4)
    # standaard elke 8 weken een ramp-test: niet in week 4, wel in week 8
    assert not any(s["soort"] == "ftp_test" for s in wk4)
    assert any(s["soort"] == "ftp_test" for s in plan if s["week"] == 8)
    assert sum(s["soort"] == "ftp_test" for s in plan) == 1
    assert {s["fase"] for s in plan} == {"basis", "opbouw", "piek"}
    assert all(s["omgeving"] == "binnen" for s in plan if s["soort"] in workouts.OPTIES)



def test_tocht_taper():
    cfg = {**CFG, "doel": {**CFG["doel"], "type": "tocht", "weken": 8}}
    plan = planner.genereer(cfg, date(2026, 11, 9))
    laatste = [s for s in plan if s["week"] == 8]
    assert any(s["soort"] == "openers" for s in laatste)



def test_bijsturen_en_sync():
    service.genereer(CFG, date(2026, 11, 9))
    vandaag = date(2026, 11, 13)  # vrijdag week 1; di gereden, do gemist
    ic = NepIntervals(ritten=["2026-11-10", "2026-11-11"], ctl=60, atl=95)  # vorm -35
    log = service.bijsturen(CFG, vandaag, ic, weer(vandaag, slecht={"2026-11-14"}))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-10"]["status"] == "gedaan"
    assert plan["2026-11-12"]["status"] == "gemist"
    # gemiste intervaltraining (do) naar zondag (duurdag, buiten toegestaan)
    assert plan["2026-11-15"]["herkomst"].startswith("Verschoven")
    # zaterdag regen: lange rit niet naar zondag (die heeft nu een interval) → binnen, afgekapt
    za = plan["2026-11-14"]
    assert za["omgeving"] == "binnen" and za["minuten"] <= 120
    assert any("Vorm" in regel for regel in log)
    msg = service.sync(CFG, vandaag, ic)
    assert ic.upserts and all(e["external_id"].startswith("fietscoach-") for e in ic.upserts)
    # dagen zonder training in de horizon worden opgeruimd op ons eigen id
    assert all(d.startswith("fietscoach-") for d in ic.deleted)
    assert not set(ic.deleted) & {e["external_id"] for e in ic.upserts}
    assert "trainingen" in msg
    # tweede keer bijsturen is stabiel
    service.bijsturen(CFG, vandaag, ic, weer(vandaag, slecht={"2026-11-14"}))
    plan2 = {s["datum"]: s for s in service.laad_plan()}
    assert plan2["2026-11-15"]["soort"] == plan["2026-11-15"]["soort"]
    assert plan2["2026-11-14"]["minuten"] == za["minuten"]



def test_lange_rit_verplaatst():
    cfg = {**CFG, "week": {**CFG["week"], "zo": {"minuten": 150, "buiten": True}}}
    service.genereer(cfg, date(2026, 11, 9))
    vandaag = date(2026, 11, 13)
    ic = NepIntervals(ritten=["2026-11-10", "2026-11-11", "2026-11-12"], ctl=60, atl=60)
    service.bijsturen(cfg, vandaag, ic, weer(vandaag, slecht={"2026-11-14"}))
    plan = {s["datum"]: s for s in service.laad_plan()}
    assert plan["2026-11-15"]["soort"] == "lange_rit"
    assert plan["2026-11-15"]["omgeving"] == "buiten"
    assert plan["2026-11-14"]["soort"] == "duur"



def test_voorbeeldconfig_blokken():
    plan = planner.genereer(VOORBEELD, date(2026, 11, 9))
    assert {s["week"] for s in plan} == set(range(1, 13))
    q = [s for s in plan if s["rol"].startswith("q") and not s["herstelweek"]]
    assert all(s["soort"] == "duur" for s in q if s["week"] <= 4)        # zone 2-blok
    assert all(s["soort"] == "sweetspot" for s in q if s["week"] >= 5)   # sweetspot-blok
    namen = [s["naam"] for s in q if s["week"] >= 5]
    assert namen[0] == "Sweetspot 3×10m" and namen[-1] == "Sweetspot 2×20m"
    # di en do intervallen, zondag duur
    assert {s["dag"] for s in q} == {"di", "do"}
    assert all(s["rol"] == "duur" for s in plan if s["dag"] == "zo")



def test_sweetspot_2x20_past_in_60_min():
    t = workouts.bouw("sweetspot", 60, 1.0)
    assert t.naam == "Sweetspot 2×20m" and round(t.minuten) == 60



def test_zone2_geen_intervallen():
    plan = planner.genereer(_cfg(weken=8, focus="zone2"), date(2026, 11, 9))
    assert not any(s["soort"] in planner.INTERVALSOORTEN for s in plan)
    assert any(s["soort"] == "lange_rit_tempo" for s in plan)



def test_gepolariseerd():
    plan = planner.genereer(_cfg(weken=4, focus="gepolariseerd"), date(2026, 11, 9))
    wk1 = {s["dag"]: s["soort"] for s in plan if s["week"] == 1}
    assert wk1["di"] == "vo2max" and wk1["do"] == "duur"



def test_een_doordeweekse_sessie():
    cfg = {**_cfg(weken=4, focus="sweetspot"),
           "week": {"di": {"minuten": 60}, "za": {"minuten": 180, "buiten": True},
                    "zo": {"minuten": 90, "buiten": True}}}
    wk1 = {s["dag"]: s["soort"] for s in planner.genereer(cfg, date(2026, 11, 9)) if s["week"] == 1}
    assert wk1 == {"di": "sweetspot", "za": "lange_rit", "zo": "duur"}

