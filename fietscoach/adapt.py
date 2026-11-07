"""Bijsturen: gemiste trainingen, vermoeidheid (vorm = CTL − ATL) en weer."""
from __future__ import annotations

from datetime import date, timedelta

from .planner import beschikbaar, round5, standaard_omgeving

VERPLAATSBAAR = {"tempo", "sweetspot", "drempel", "vo2max"}


def _maandag(d: date) -> date:
    return d - timedelta(days=d.weekday())


def markeer_en_herplan(plan: list[dict], rit_datums: set[str], week: dict, vandaag: date) -> list[str]:
    """Zet afgelopen trainingen op gedaan/gemist en schuif gemiste intervaltrainingen
    door naar een latere duurrit-dag in dezelfde week."""
    log = []
    v = vandaag.isoformat()
    for s in plan:
        if s["status"] == "gepland" and s["datum"] < v:
            if s["datum"] in rit_datums:
                s["status"] = "gedaan"
            else:
                s["status"] = "vervallen" if s["soort"] == "rust" else "gemist"
    ma = _maandag(vandaag).isoformat()
    for s in plan:
        if (s["status"] != "gemist" or s.get("verschoven") or s["datum"] < ma
                or s["basis_soort"] not in VERPLAATSBAAR):
            continue
        week_eind = (_maandag(vandaag) + timedelta(days=6)).isoformat()
        doelen = [t for t in plan if v <= t["datum"] <= week_eind and t["status"] == "gepland"
                  and t["rol"] in ("duur", "herstel", "extra") and not t.get("herkomst")
                  and beschikbaar(week, t["dag"]) >= 45]
        if not doelen:
            continue
        t = max(doelen, key=lambda x: beschikbaar(week, x["dag"]))
        t["basis_soort"] = s["basis_soort"]
        t["basis_minuten"] = min(beschikbaar(week, t["dag"]), s["basis_minuten"])
        t["herkomst"] = f"Verschoven van {s['dag']} (gemist)"
        s["verschoven"] = True
        log.append(f"Gemiste {s['basis_soort']} van {s['datum']} verschoven naar {t['datum']}.")
    return log


def reset_venster(plan: list[dict], van: str, tot: str, vk: dict) -> list[dict]:
    venster = [s for s in plan if van <= s["datum"] <= tot and s["status"] == "gepland"]
    for s in venster:
        s["soort"], s["minuten"] = s["basis_soort"], s["basis_minuten"]
        s["notities"] = [s["herkomst"]] if s.get("herkomst") else []
        s.pop("weer", None)
        s.pop("weer_slecht", None)
        s["omgeving"] = standaard_omgeving(s, vk)
    return sorted(venster, key=lambda s: s["datum"])


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
            if (t["week"] != wk or t is s or not t["buiten_toegestaan"]
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

from .workouts import VERWACHTE_IF, VERWACHTE_RPE  # noqa: E402

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
              and avail(t) >= nodig]
    if not opties:
        return None
    t = max(opties, key=avail)
    t["soort"], t["minuten"] = s["soort"], min(avail(t), s["minuten"])
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
                log.append(f"{oud['naam']} van {oud['dag']} {oud['datum'][8:10]}-{oud['datum'][5:7]} "
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
        r = uit.setdefault(d, {"minuten": 0, "load": 0, "if": None, "rpe": None, "naam": a.get("name", "")})
        r["minuten"] += round((a.get("moving_time") or 0) / 60)
        r["load"] += a.get("icu_training_load") or 0
        intens = a.get("icu_intensity")
        if intens:
            r["if"] = round(intens / 100 if intens > 3 else intens, 2)
        if a.get("icu_rpe"):
            r["rpe"] = a["icu_rpe"]
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


def pas_readiness_toe(venster: list[dict], readiness: dict | None, vandaag: date) -> list[str]:
    """Hoe voel je je vandaag? Benen en energie, elk 1 (slecht) tot 5 (top)."""
    if not readiness:
        return []
    score = (readiness["benen"] + readiness["energie"]) / 2
    if score > 3:
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
    uit["totaal"] = round(mean(uit.values()))
    return uit
