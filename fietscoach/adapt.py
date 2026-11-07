"""Bijsturen: gemiste trainingen, vermoeidheid (vorm = CTL − ATL) en weer."""
from __future__ import annotations

from datetime import date, timedelta

from .planner import beschikbaar, round5, standaard_omgeving

VERPLAATSBAAR = {"tempo", "sweetspot", "drempel", "vo2max"}


def _maandag(d: date) -> date:
    return d - timedelta(days=d.weekday())


def basis_kopie(basis: list[dict], vk: dict) -> list[dict]:
    """Verse werkkopie van het basisschema. Het schema wordt elke keer opnieuw
    afgeleid uit basis + invoer; niets aan de basis wordt ooit ter plekke gewijzigd."""
    uit = []
    for b in basis:
        s = {k: v for k, v in b.items() if k not in ("weer", "weer_slecht", "p_mod", "herkomst",
                                                      "verschoven", "score", "naam", "beschrijving", "duur")}
        s.update(soort=b["basis_soort"], minuten=b["basis_minuten"], status="gepland", notities=[])
        s["omgeving"] = standaard_omgeving(s, vk)
        uit.append(s)
    return sorted(uit, key=lambda s: s["datum"])


def is_gedaan(s: dict, rit: dict | None) -> bool:
    """Gereden is niet automatisch gedaan: een woon-werkrit op een intervaldag telt
    niet. Gedaan als intervals.icu de rit aan de geplande training koppelde, of
    als de rit minstens 60% van de geplande duur was."""
    if not rit:
        return False
    if rit.get("gepaard"):
        return True
    return rit["minuten"] >= 0.6 * max(s["basis_minuten"], 1)


def markeer(plan: list[dict], ritten: dict[str, dict], vandaag: date, afwezig, vanaf: str = "") -> None:
    v = vandaag.isoformat()
    for s in plan:
        if not (vanaf <= s["datum"] < v):
            continue
        rit = ritten.get(s["datum"])
        if afwezig(s["datum"]):
            s["status"] = "afwezig"
        elif s["soort"] == "rust":
            s["status"] = "gedaan" if rit else "vervallen"
        elif is_gedaan(s, rit):
            s["status"] = "gedaan"
        else:
            s["status"] = "gemist"
            if rit:
                s["notities"].append(f"Wel gereden ({rit['minuten']} min), maar te kort voor deze training")


def herplan_gemist(plan: list[dict], week: dict, vandaag: date) -> list[str]:
    """Gemiste intervaltraining van deze week naar een latere duurdag in dezelfde week."""
    log = []
    v = vandaag.isoformat()
    ma = _maandag(vandaag).isoformat()
    zo = (_maandag(vandaag) + timedelta(days=6)).isoformat()
    for s in plan:
        if s["status"] != "gemist" or s["datum"] < ma or s["basis_soort"] not in VERPLAATSBAAR:
            continue
        doelen = [t for t in plan if v <= t["datum"] <= zo and t["status"] == "gepland"
                  and t["rol"] in ("duur", "herstel", "extra") and t["soort"] in ("duur", "herstel")
                  and not t.get("handmatig")
                  and not t.get("herkomst") and beschikbaar(week, t["dag"]) >= 45]
        if not doelen:
            continue
        t = max(doelen, key=lambda x: beschikbaar(week, x["dag"]))
        t["soort"] = s["basis_soort"]
        t["minuten"] = min(beschikbaar(week, t["dag"]), s["basis_minuten"])
        t["variant"] = s.get("variant", 0)  # dezelfde vorm als die je miste, niet die van de dag
        t["herkomst"] = f"Verschoven van {s['dag']} (gemist)"
        t["notities"].append(t["herkomst"])
        s["verschoven"] = True
        log.append(f"Gemiste {s['basis_soort']} van {s['dag']} naar {t['dag']}.")
    return log


def afwezigheid(perioden: list[dict]):
    """Functie datum -> periode of None. Perioden: [{"van": "...", "tot": "...", "reden": "..."}]."""
    lijst = [(str(p["van"]), str(p["tot"]), p.get("reden") or "Afwezig") for p in perioden or []]

    def op(datum: str):
        return next(((v, t, r) for v, t, r in lijst if v <= datum <= t), None)
    op.perioden = lijst
    return op


def pas_afwezigheid_toe(plan: list[dict], afwezig, vandaag: date) -> list[str]:
    """Afwezig: geen trainingen. Na een afwezigheid van 5+ dagen eerst drie dagen
    zonder intervallen, zodat je niet koud in een zware training stapt."""
    v = vandaag.isoformat()
    log = []
    for s in plan:
        if s["datum"] >= v and s["status"] == "gepland" and afwezig(s["datum"]):
            s["soort"], s["minuten"] = "rust", 0
            s["notities"].append(afwezig(s["datum"])[2])
    for van, tot, reden in afwezig.perioden:
        lengte = (date.fromisoformat(tot) - date.fromisoformat(van)).days + 1
        if lengte < 5:
            continue
        eind = date.fromisoformat(tot)
        na = {(eind + timedelta(days=i)).isoformat() for i in range(1, 4)}
        for s in plan:
            if s["datum"] in na and s["datum"] >= v and s["status"] == "gepland" and (
                    s["soort"] in VERPLAATSBAAR or s["soort"] in ("lange_rit_tempo", "openers")):
                s["soort"] = "duur" if s["soort"] != "lange_rit_tempo" else "lange_rit"
                s["notities"].append("Rustig weer opstarten na afwezigheid")
        if tot >= v:
            log.append(f"{reden}: {van[8:10]}-{van[5:7]} t/m {tot[8:10]}-{tot[5:7]}.")
    return log


def objectieve_readiness(wellness: list[dict], vandaag: date) -> tuple[float | None, str]:
    """Readiness uit HRV en rusthartslag (als je horloge die aan intervals.icu levert).
    Vergeleken met je eigen gemiddelde van de 28 dagen ervoor: HRV duidelijk lager
    of rusthartslag duidelijk hoger = minder hersteld."""
    from statistics import mean, pstdev
    v = vandaag.isoformat()
    vandaag_w = next((w for w in wellness if w.get("id") == v), None)
    if not vandaag_w:
        return None, ""
    eerder = [w for w in wellness if w.get("id", "") < v]
    signalen, uitleg = 0, []
    for veld, naam, slecht in (("hrv", "HRV", -1), ("restingHR", "rusthartslag", 1)):
        reeks = [w[veld] for w in eerder if w.get(veld)]
        nu = vandaag_w.get(veld)
        if not nu or len(reeks) < 7:
            continue
        gem, sd = mean(reeks), pstdev(reeks)
        drempel = max(sd, 0.05 * gem if veld == "hrv" else 3)
        afwijkend = (nu < gem - drempel) if slecht < 0 else (nu > gem + drempel)
        uitleg.append(f"{naam} {nu:.0f} (normaal {gem:.0f})")
        signalen += afwijkend
    if not uitleg:
        return None, ""
    score = {0: None, 1: 2.5, 2: 2.0}[signalen]
    return score, " · ".join(uitleg)


def pas_vorm_toe(venster: list[dict], vorm: float | None) -> list[str]:
    if vorm is None:
        return []
    if vorm < -30:
        factor, schrap = 0.8, True
    elif vorm < -20:
        factor, schrap = 0.9, False
    else:
        return []
    q = 0
    for s in venster:
        s["minuten"] = max(30, round5(s["minuten"] * factor))
        if schrap and s["rol"].startswith("q") and s["soort"] in VERPLAATSBAAR:
            q += 1
            if q == 2:
                s["soort"] = "duur"
                s["notities"].append("Interval vervangen door duurrit (veel vermoeidheid)")
        s["notities"].append(f"Ingekort: vorm {vorm:+.0f}")
    return [f"Vorm {vorm:+.0f}: komende 7 dagen {round((1 - factor) * 100)}% korter"
            + (" en één intervaltraining minder." if schrap else ".")]


def weerredenen(w: dict, wc: dict) -> list[str]:
    r = []
    if (w.get("neerslag_mm") or 0) > wc.get("max_neerslag_mm", 2.0):
        r.append(f"regen {w['neerslag_mm']:.1f} mm")
    elif (w.get("neerslagkans") or 0) > wc.get("max_neerslagkans", 60):
        r.append(f"regenkans {w['neerslagkans']:.0f}%")
    if (w.get("wind_kmh") or 0) > wc.get("max_wind_kmh", 35):
        r.append(f"wind {w['wind_kmh']:.0f} km/u")
    if w.get("temp_min") is not None and w["temp_min"] < wc.get("min_temp", 0):
        r.append(f"min {w['temp_min']:.0f}°C (gladheid)")
    return r


def _weerlabel(w: dict) -> str:
    v = f"{w['venster']} · " if w.get("venster") else ""
    return (f"{v}{w['temp_min']:.0f}–{w['temp_max']:.0f}°C, {w['neerslag_mm']:.1f} mm "
            f"({w['neerslagkans']:.0f}%), wind {w['wind_kmh']:.0f} km/u")


def pas_weer_toe(venster: list[dict], verwachting, week: dict, vk: dict, wc: dict) -> list[str]:
    """verwachting: functie (datum, minuten) -> weer over dat ritvenster, of een
    dict datum -> weer (dagwaarden; oudere vorm, gebruikt in tests)."""
    weer_voor = verwachting if callable(verwachting) else (lambda d, m: verwachting.get(d))
    log = []
    for s in venster:
        w = weer_voor(s["datum"], s["minuten"])
        if not w:
            continue
        s["weer"] = _weerlabel(w)
        s["weer_slecht"] = weerredenen(w, wc)

    # lange rit naar een droge dag in dezelfde week verplaatsen; die dag wordt
    # beoordeeld over de duur van de lange rit, niet van de duurrit die er stond
    for s in venster:
        if not s["soort"].startswith("lange_rit") or not s["buiten_toegestaan"] or not s.get("weer_slecht"):
            continue
        wk = s["week"]
        opties = []
        for t in venster:
            if (t["week"] != wk or t is s or not t["buiten_toegestaan"] or t.get("handmatig")
                    or t["soort"] not in ("duur", "herstel")
                    or beschikbaar(week, t["dag"]) < 0.75 * s["minuten"]):
                continue
            w = weer_voor(t["datum"], min(beschikbaar(week, t["dag"]), s["minuten"]))
            if w and not weerredenen(w, wc):
                opties.append((t, w))
        if not opties:
            continue
        t, w = max(opties, key=lambda x: beschikbaar(week, x[0]["dag"]))
        t_min = t["minuten"]
        t["soort"], t["minuten"] = s["soort"], min(beschikbaar(week, t["dag"]), s["minuten"])
        t["weer"], t["weer_slecht"] = _weerlabel(w), []
        t["notities"].append(f"Lange rit hierheen verplaatst (slecht weer op {s['dag']})")
        s["soort"], s["minuten"] = "duur", min(beschikbaar(week, s["dag"]), max(t_min, 45))
        w2 = weer_voor(s["datum"], s["minuten"])
        if w2:
            s["weer"], s["weer_slecht"] = _weerlabel(w2), weerredenen(w2, wc)
        s["notities"].append(f"Lange rit verplaatst naar {t['dag']}")
        log.append(f"Lange rit van {s['dag']} naar {t['dag']} vanwege het weer.")

    max_binnen = int(vk.get("max_binnen_minuten", 120))
    for s in venster:
        if s.get("omgeving_vast"):  # zelf gekozen bij een extra training: niet overrulen
            if s["omgeving"] == "buiten" and s.get("weer_slecht"):
                s["notities"].append("Let op het weer: " + ", ".join(s["weer_slecht"]))
            continue
        omg = standaard_omgeving(s, vk)
        if omg == "buiten" and s.get("weer_slecht"):
            omg = "binnen"
            s["notities"].append("Naar Zwift: " + ", ".join(s["weer_slecht"]))
        s["omgeving"] = omg
        if omg == "binnen" and s["minuten"] > max_binnen:
            s["minuten"] = max_binnen
            s["notities"].append(f"Binnen ingekort tot {max_binnen} min")
    return log


# --- JOIN-achtige bijsturing -------------------------------------------------

from statistics import mean  # noqa: E402

from .workouts import SOORTNAAM, VERWACHTE_IF, VERWACHTE_RPE  # noqa: E402

LANG = ("lange_rit", "lange_rit_tempo")


def niveaus(plan: list[dict], rpe: dict[str, int]) -> dict[str, tuple[float, str]]:
    """Per trainingssoort een bijstelling van de zwaarte (−0.4..+0.4) op basis van
    hoe de laatste drie trainingen van die soort voelden ten opzichte van verwacht."""
    per_soort: dict[str, list[tuple[str, int, int]]] = {}
    for s in sorted(plan, key=lambda x: x["datum"]):
        if s["status"] == "gedaan" and s["datum"] in rpe and s["soort"] in VERWACHTE_RPE:
            per_soort.setdefault(s["soort"], []).append((s["datum"], int(rpe[s["datum"]]), VERWACHTE_RPE[s["soort"]]))
    uit = {}
    for soort, rijen in per_soort.items():
        laatste = rijen[-3:]
        verschil = mean(v - r for _, r, v in laatste)  # positief = voelde lichter dan bedoeld
        offset = max(-0.4, min(0.4, verschil * 0.12))
        _, r, v = laatste[-1]
        if offset >= 0.1:
            uitleg = f"Iets zwaarder: vorige keer RPE {r}, bedoeld {v}"
        elif offset <= -0.1:
            uitleg = f"Iets lichter: vorige keer RPE {r}, bedoeld {v}"
        else:
            uitleg = ""
        uit[soort] = (round(offset, 2), uitleg)
    return uit


def _verplaats(s: dict, venster: list[dict], avail, reden: str) -> dict | None:
    """Zet de sleuteltraining van s op een latere duur-/hersteldag in dezelfde week."""
    lang = s["soort"] in LANG
    nodig = 0.75 * s["minuten"] if lang else 45
    opties = [t for t in venster if t["week"] == s["week"] and t["datum"] > s["datum"]
              and t["soort"] in ("duur", "herstel") and t["rol"] in ("duur", "herstel", "extra")
              and not t.get("handmatig")
              and avail(t) >= nodig]
    if not opties:
        return None
    t = max(opties, key=avail)
    t["soort"], t["minuten"] = s["soort"], min(avail(t), s["minuten"])
    t["variant"] = s.get("variant", 0)
    t["notities"].append(f"{reden} — verplaatst van {s['dag']}")
    return t


def pas_uitzonderingen_toe(venster: list[dict], uitz: dict[str, int], week: dict) -> list[str]:
    """Andere beschikbaarheid op een datum: korter, langer of helemaal niet."""
    log = []

    def avail(t):
        return int(uitz.get(t["datum"], beschikbaar(week, t["dag"])))

    for s in venster:
        if s["datum"] not in uitz:
            continue
        m = int(uitz[s["datum"]])
        if m < 30:
            oud = dict(s)
            s["soort"], s["minuten"] = "rust", 0
            s["notities"].append("Geen tijd deze dag")
            if oud["soort"] in VERPLAATSBAAR or oud["soort"] in LANG:
                t = _verplaats(oud, venster, avail, "Geen tijd op " + oud["dag"])
                log.append(f"{SOORTNAAM.get(oud['soort'], oud['soort'])} van {oud['dag']} {oud['datum'][8:10]}-{oud['datum'][5:7]} "
                           + (f"naar {t['dag']} {t['datum'][8:10]}-{t['datum'][5:7]}." if t
                              else "vervalt: geen ruimte in die week."))
        elif m < s["minuten"]:
            s["minuten"] = m
            s["notities"].append(f"Aangepast aan {m} min beschikbaar")
        elif m > s["minuten"]:
            if s["soort"] in ("duur", *LANG):
                s["minuten"] = round5(m * (0.65 if s["herstelweek"] else 1.0))
            elif s["soort"] == "herstel":
                s["minuten"] = min(m, 60)  # herstel blijft kort
            elif s["soort"] != "ftp_test":
                s["minuten"] = m  # meer herhalingen of extra duur, binnen de grenzen van de vorm
            if s["minuten"] > s["basis_minuten"]:
                s["notities"].append(f"Verlengd: {m} min beschikbaar")
    return log


def ritten_per_dag(activiteiten: list[dict]) -> dict[str, dict]:
    uit: dict[str, dict] = {}
    for a in activiteiten:
        if "Ride" not in (a.get("type") or ""):
            continue
        d = a["start_date_local"][:10]
        r = uit.setdefault(d, {"minuten": 0, "load": 0, "if": None, "rpe": None, "naam": a.get("name", ""),
                               "gepaard": False})
        r["minuten"] += round((a.get("moving_time") or 0) / 60)
        r["load"] += a.get("icu_training_load") or 0
        intens = a.get("icu_intensity")
        if intens:
            r["if"] = round(intens / 100 if intens > 3 else intens, 2)
        if a.get("icu_rpe"):
            r["rpe"] = a["icu_rpe"]
        if a.get("paired_event_id"):
            r["gepaard"] = True
        if a.get("compliance") is not None:
            r["compliance"] = a["compliance"]
    return uit


def pas_ongepland_toe(plan: list[dict], venster: list[dict], ritten: dict[str, dict],
                      vandaag: date, week: dict) -> list[str]:
    """Een zware rit die niet in het schema stond (clubrit, tocht): de dag erna rustiger."""
    log = []
    gepland = {s["datum"] for s in plan if s["soort"] != "rust"}

    def avail(t):
        return beschikbaar(week, t["dag"])

    for d, r in sorted(ritten.items()):
        if d in gepland or not (vandaag - timedelta(days=2)).isoformat() <= d <= vandaag.isoformat():
            continue
        zwaar = r["load"] >= 80 or r["minuten"] >= 120 or (r["rpe"] or 0) >= 8
        if not zwaar:
            continue
        morgen = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        s = next((x for x in venster if x["datum"] == morgen and x["soort"] != "rust"), None)
        if not s:
            continue
        if s["soort"] in VERPLAATSBAAR or s["soort"] in LANG:
            _verplaats(dict(s), venster, avail, "Na ongeplande zware rit")
        s["soort"], s["minuten"] = "herstel", min(s["minuten"], 45)
        s["notities"].append(f"Rustig na ongeplande rit op {d[8:10]}-{d[5:7]} ({r['minuten']} min)")
        log.append(f"Ongeplande rit {d[8:10]}-{d[5:7]} ({r['minuten']} min, load {r['load']:.0f}): "
                   f"de dag erna wordt herstel.")
    return log


def readiness_score(handmatig: dict | None, objectief: float | None) -> float | None:
    """Laagste van wat je zelf invult (benen en energie, 1–5) en wat HRV/rusthartslag zeggen."""
    scores = [x for x in ((handmatig["benen"] + handmatig["energie"]) / 2 if handmatig else None, objectief)
              if x is not None]
    return min(scores) if scores else None


def pas_readiness_toe(venster: list[dict], score: float | None, vandaag: date) -> list[str]:
    """Readiness 1 (slecht) tot 5 (top). Bij 3 of lager vandaag lichter, bij 2 of lager ook morgen."""
    if score is None or score > 3:
        return []
    dagen = {vandaag.isoformat(), (vandaag + timedelta(days=1)).isoformat()}
    if score > 2:
        dagen = {vandaag.isoformat()}
    for s in venster:
        if s["datum"] not in dagen or s["soort"] == "rust":
            continue
        if score <= 2:
            if s["soort"] in ("duur", "herstel"):
                s["soort"], s["minuten"] = "herstel", min(s["minuten"], 45)
            else:
                s["soort"], s["minuten"] = "duur", min(60, max(30, round5(s["minuten"] * 0.7)))
            s["notities"].append(f"Readiness laag ({score:.1f}/5): rustig aan")
        else:
            s["p_mod"] = s.get("p_mod", 0) - 0.3
            s["notities"].append(f"Readiness matig ({score:.1f}/5): iets lichter")
    return [f"Readiness {score:.1f}/5 verwerkt."]


def trainingsscore(s: dict, rit: dict | None) -> dict | None:
    """Gepland tegenover gereden: duur en intensiteit, elk 0–100, plus het gemiddelde."""
    if not rit or s["status"] != "gedaan" or not s.get("duur"):
        return None
    r = rit["minuten"] / s["duur"] if s["duur"] else 0
    duur = round(100 * min(r, 1 / r)) if r > 0 else 0
    uit = {"duur": duur}
    verwacht = VERWACHTE_IF.get(s["soort"])
    if rit.get("if") and verwacht:
        uit["intensiteit"] = max(0, round(100 - abs(rit["if"] - verwacht) / verwacht * 250))
    if rit.get("compliance") is not None:  # intervals.icu's eigen vergelijking met de geplande training
        uit["intervals"] = round(rit["compliance"])
    uit["totaal"] = round(mean(uit.values()))
    return uit
