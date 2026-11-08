"""Overzichten uit het schema en intervals.icu: fitheidsverloop met vooruitblik,
weekterugblik en de tekst van het ochtendbericht. Alles puur: geen opslag, geen netwerk."""
from __future__ import annotations

import math
from datetime import date, timedelta

from .workouts import SOORTNAAM

K_FIT = 1 - math.exp(-1 / 42)   # zoals intervals.icu: fitheid over 42 dagen
K_MOE = 1 - math.exp(-1 / 7)    # vermoeidheid over 7 dagen


def _d(x: date | str) -> date:
    return x if isinstance(x, date) else date.fromisoformat(x)


def fitheidsverloop(status: dict, plan: list[dict], vandaag: date,
                    terug: int = 42, vooruit: int = 84) -> list[dict]:
    """Gemeten fitheid en vermoeidheid van de afgelopen weken, daarna voorspeld met de
    geplande belasting (TSS) van het schema. Per dag: datum, fit, moe, vorm, tss, voorspeld."""
    gemeten = [r for r in status.get("fitheid") or [] if r[0] <= vandaag.isoformat()]
    if not gemeten:
        return []
    van = (vandaag - timedelta(days=terug)).isoformat()
    uit = [{"datum": d, "fit": c, "moe": a, "vorm": round(c - a, 1), "tss": None, "voorspeld": False}
           for d, c, a in gemeten if d >= van]
    per_dag = {s["datum"]: s for s in plan}
    ritten = status.get("ritten") or {}

    d0, fit, moe = gemeten[-1]
    dag = _d(d0)
    eind = min(_d(plan[-1]["datum"]) if plan else vandaag, vandaag + timedelta(days=vooruit))

    def belasting(d: str) -> float:
        if d < vandaag.isoformat():
            return float((ritten.get(d) or {}).get("load") or 0)
        s = per_dag.get(d)
        if s and s.get("status") == "gepland" and s["soort"] != "rust":
            return float(s.get("tss") or 0)
        return float((ritten.get(d) or {}).get("load") or 0) if d == vandaag.isoformat() else 0.0

    # Vandaag gemeten, maar de training van vandaag nog niet gereden: die telt nog mee.
    if d0 == vandaag.isoformat():
        s = per_dag.get(d0)
        if s and s.get("status") == "gepland" and s["soort"] != "rust" and s.get("tss"):
            fit += (s["tss"] - fit) * K_FIT
            moe += (s["tss"] - moe) * K_MOE
            uit[-1] = {"datum": d0, "fit": round(fit, 1), "moe": round(moe, 1), "vorm": round(fit - moe, 1),
                       "tss": s["tss"], "voorspeld": True}
    while dag < eind:
        dag += timedelta(days=1)
        d = dag.isoformat()
        t = belasting(d)
        fit += (t - fit) * K_FIT
        moe += (t - moe) * K_MOE
        uit.append({"datum": d, "fit": round(fit, 1), "moe": round(moe, 1), "vorm": round(fit - moe, 1),
                    "tss": round(t), "voorspeld": True})
    return uit


def _fit_op(status: dict, datum: str) -> float | None:
    kandidaten = [r for r in status.get("fitheid") or [] if r[0] <= datum]
    return kandidaten[-1][1] if kandidaten else None


def weekterugblik(plan: list[dict], status: dict, fb: dict, maandag: date) -> dict:
    """Wat er in de week van `maandag` gepland en gereden is, en wat er volgende week komt."""
    van, tot = maandag.isoformat(), (maandag + timedelta(days=6)).isoformat()
    week = [s for s in plan if van <= s["datum"] <= tot and s["soort"] != "rust" and s["status"] != "afwezig"]
    ritten = {d: r for d, r in (status.get("ritten") or {}).items() if van <= d <= tot}
    gedaan = [s for s in week if s["status"] == "gedaan"]
    gemist = [s for s in week if s["status"] in ("gemist", "vervallen")]
    rpe = [fb["rpe"][s["datum"]] for s in gedaan if s["datum"] in fb.get("rpe", {})]
    fit_van = _fit_op(status, (maandag - timedelta(days=1)).isoformat())
    fit_tot = _fit_op(status, tot)

    volgende_maandag = (maandag + timedelta(days=7)).isoformat()
    volgende_zondag = (maandag + timedelta(days=13)).isoformat()
    nw = [s for s in plan if volgende_maandag <= s["datum"] <= volgende_zondag and s["soort"] != "rust"]
    volgende = None
    if nw:
        zwaarste = max(nw, key=lambda s: (s.get("zwaarte") or 0, s.get("tss") or 0))
        volgende = {"focus": nw[0].get("focus"), "fase": nw[0].get("fase"), "herstel": nw[0].get("herstelweek"),
                    "trainingen": len(nw), "minuten": sum(s.get("duur") or 0 for s in nw),
                    "tss": sum(s.get("tss") or 0 for s in nw), "zwaarste": zwaarste.get("naam"),
                    "zwaarste_dag": zwaarste["datum"]}

    n, k = len(week), len(gedaan)
    extra = [d for d in ritten if d not in {s["datum"] for s in gedaan}]
    if not n:
        oordeel = "Geen trainingen gepland."
    elif k == n:
        oordeel = "Alles gereden."
    elif k == 0:
        oordeel = "Geen van de trainingen gereden."
    else:
        oordeel = f"{k} van de {n} trainingen gereden."
    if extra:
        oordeel += f" Plus {len(extra)} {'rit' if len(extra) == 1 else 'ritten'} buiten het schema."
    return {
        "van": van, "tot": tot, "gepland": n, "gedaan": k,
        "gemist": [SOORTNAAM.get(s["soort"], s["soort"]) for s in gemist],
        "minuten_gepland": sum(s.get("duur") or 0 for s in week),
        "minuten_gereden": sum(r.get("minuten") or 0 for r in ritten.values()),
        "tss_gepland": round(sum(s.get("tss") or 0 for s in week)),
        "tss_gereden": round(sum(r.get("load") or 0 for r in ritten.values())),
        "rpe": round(sum(rpe) / len(rpe), 1) if rpe else None,
        "fit_van": fit_van, "fit_tot": fit_tot,
        "fit_verschil": round(fit_tot - fit_van) if fit_van is not None and fit_tot is not None else None,
        "volgende": volgende, "oordeel": oordeel,
    }


def _uren(minuten: float) -> str:
    u, m = divmod(int(round(minuten)), 60)
    return f"{u}u{m:02d}" if u else f"{m} min"


def weektekst(w: dict, focusnaam: dict) -> tuple[str, str]:
    """Titel en tekst voor het bericht op zondagavond."""
    titel = f"Week {_d(w['van']):%d-%m}: {w['oordeel'].split('.')[0].lower()}"
    regels = [w["oordeel"],
              f"Tijd: {_uren(w['minuten_gereden'])} gereden, {_uren(w['minuten_gepland'])} gepland.",
              f"Belasting (TSS): {w['tss_gereden']} gereden, {w['tss_gepland']} gepland."]
    if w["gemist"]:
        regels.append("Overgeslagen: " + ", ".join(w["gemist"]) + ".")
    if w["rpe"] is not None:
        regels.append(f"Gemiddelde RPE: {w['rpe']}.")
    if w["fit_verschil"] is not None:
        regels.append(f"Fitheid {w['fit_van']:.0f} → {w['fit_tot']:.0f} ({w['fit_verschil']:+d}).")
    v = w["volgende"]
    if v:
        soort = "herstelweek" if v["herstel"] else focusnaam.get(v["focus"], v["fase"] or "").lower()
        regels.append(f"Volgende week ({soort}): {v['trainingen']} trainingen, {_uren(v['minuten'])}, "
                      f"TSS {round(v['tss'])}. Zwaarste: {v['zwaarste']}.")
    return titel, "\n".join(regels)


def ochtendtekst(plan: list[dict], status: dict, fb: dict, vandaag: date,
                 cwem: str | None = None) -> tuple[str, str] | None:
    """Titel en tekst voor het ochtendbericht; None op een rustdag."""
    v = vandaag.isoformat()
    s = next((x for x in plan if x["datum"] == v), None)
    if not s or s["soort"] == "rust" or s.get("status") != "gepland":
        return None
    waar = "Zwift" if s.get("omgeving") == "binnen" else "buiten"
    titel = f"Vandaag: {s['naam']} · {s.get('duur')} min · {waar}"
    regels = []
    if s.get("omgeving") == "buiten" and s.get("weer"):
        regels.append(f"Weer: {s['weer']}")
    regels += list(s.get("notities") or [])
    if cwem and s.get("omgeving") == "buiten":
        regels.append(f"Kleding, eten en drinken: {cwem}")
    elif s.get("voeding"):
        regels.append(s["voeding"])
    open_rpe = [x for x in plan if x["status"] == "gedaan" and x["datum"] < v
                and x["datum"] >= (vandaag - timedelta(days=7)).isoformat() and x["datum"] not in fb.get("rpe", {})]
    if open_rpe:
        regels.append(f"Nog {len(open_rpe)} {'rit' if len(open_rpe) == 1 else 'ritten'} zonder RPE.")
    hint = ftp_hint(status)
    if hint:
        regels.append(hint["tekst"])
    regels.append("Hoe voel je je? Vul je readiness in voor je vertrekt.")
    return titel, "\n".join(regels)


def ftp_hint(status: dict) -> dict | None:
    """Seintje als de eFTP duidelijk van je FTP afwijkt. 'richting' is 'hoger' of 'lager'."""
    e, f = status.get("eftp"), status.get("ftp")
    if not e or not f:
        return None
    if e > f * 1.03:
        return {"richting": "hoger", "waarde": e,
                "tekst": f"Je eFTP ({e} W) ligt duidelijk boven je FTP ({f} W); overweeg je FTP op te hogen."}
    if e < f * 0.92:
        return {"richting": "lager", "waarde": e,
                "tekst": f"Je eFTP ({e} W) ligt ruim onder je FTP ({f} W). Dat kan komen doordat je een "
                         "tijd geen zware inspanningen deed; twijfel je, doe dan de FTP-test."}
    return None
