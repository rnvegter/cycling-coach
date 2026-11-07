"""Schemagenerator: periodisering in blokken van 4 weken (3 opbouw + 1 herstel),
met per periode een trainingsfocus."""
from __future__ import annotations

from datetime import date, timedelta

from . import workouts

DAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]
FOCUSSEN = ("gemengd", "sweetspot", "zone2", "gepolariseerd")

KWALITEIT = {
    "ftp": {"basis": ["sweetspot", "tempo"], "opbouw": ["drempel", "vo2max"], "piek": ["vo2max", "drempel"]},
    "duur": {"basis": ["tempo", "sweetspot"], "opbouw": ["sweetspot", "drempel"], "piek": ["drempel", "sweetspot"]},
    "tocht": {"basis": ["tempo", "sweetspot"], "opbouw": ["sweetspot", "drempel"], "piek": ["drempel", "vo2max"]},
}
INTERVALSOORTEN = {"tempo", "sweetspot", "drempel", "vo2max", "openers"}


def round5(x: float) -> int:
    return int(5 * round(x / 5))


def weekfocus(doel: dict, start: date | None = None) -> list[tuple[int, str]]:
    """(bloknummer, focus) per week. Met `blokken` kun je focussen achter elkaar zetten.
    Bij een tocht met datum loopt het schema precies tot en met die week."""
    blokken = [dict(b) for b in (doel.get("blokken") or [])]
    if not blokken:
        blokken = [{"focus": doel.get("focus", "gemengd"), "weken": doel["weken"]}]
    if doel.get("type") == "tocht" and doel.get("evenement") and start:
        ev = date.fromisoformat(str(doel["evenement"]))
        totaal = ((ev - timedelta(days=ev.weekday())) - start).days // 7 + 1
        if totaal < 1:
            raise ValueError("De tochtdatum ligt vóór de start van het schema.")
        rest = sum(int(b["weken"]) for b in blokken[:-1])
        blokken[-1]["weken"] = max(1, totaal - rest)
    uit = []
    for b, blok in enumerate(blokken):
        if blok["focus"] not in FOCUSSEN:
            raise ValueError(f"Onbekende focus '{blok['focus']}', kies uit {', '.join(FOCUSSEN)}.")
        uit += [(b, blok["focus"])] * int(blok["weken"])
    return uit


def weekfasen(n: int, doel: str, focus: list[tuple[int, str]] | None = None) -> list[dict]:
    focus = focus or [(0, "gemengd")] * n
    meta = []
    for i in range(n):
        pos = i % 4
        herstelweek = pos == 3
        frac = i / n
        fase = "basis" if frac < 0.4 else "opbouw" if frac < 0.8 else "piek"
        factor = 0.65 if herstelweek else (0.9, 1.0, 1.1)[pos]
        if doel == "tocht" and i == n - 1:
            fase, factor, herstelweek = "taper", 0.6, False
        meta.append({"nr": i + 1, "fase": fase, "factor": factor, "herstel": herstelweek,
                     "blok": focus[i][0], "focus": focus[i][1]})

    # progressie (0..1) over de belastende weken: bij 'gemengd' per fase,
    # bij een vaste focus over het hele blok (bv. sweetspot 3×10 → 2×20)
    def sleutel(m):
        return (m["blok"], m["fase"]) if m["focus"] == "gemengd" else (m["blok"],)

    for k in {sleutel(m) for m in meta}:
        idx = [i for i, m in enumerate(meta)
               if sleutel(m) == k and not m["herstel"] and m["fase"] != "taper"]
        for j, i in enumerate(idx):
            meta[i]["p"] = j / (len(idx) - 1) if len(idx) > 1 else 0.5
    for m in meta:
        m.setdefault("p", 0.0)
    # Voortgang over het hele blok (los van de fase): daarop loopt de doelzwaarte op,
    # zodat de piek niet zwakker wordt dan het eind van de opbouw.
    for blok in {m["blok"] for m in meta}:
        idx = [i for i, m in enumerate(meta) if m["blok"] == blok and not m["herstel"] and m["fase"] != "taper"]
        for j, i in enumerate(idx):
            meta[i]["pb"] = j / (len(idx) - 1) if len(idx) > 1 else 0.5
    for m in meta:
        m.setdefault("pb", m["p"])
    return meta


def beschikbaar(week: dict, dag: str) -> int:
    return int((week.get(dag) or {}).get("minuten", 0) or 0)


def dagrollen(week: dict, max_q: int = 2) -> dict[int, str]:
    """Bepaal per beschikbare dag de rol: lang, q0/q1 (kwaliteit), duur of herstel."""
    dagen = [i for i, d in enumerate(DAGEN) if beschikbaar(week, d) >= 30]
    if not dagen:
        raise ValueError("Geen dagen met minstens 30 minuten beschikbaar.")
    mins = lambda i: beschikbaar(week, DAGEN[i])
    buiten = lambda i: bool(week[DAGEN[i]].get("buiten", False))
    lang = max(dagen, key=lambda i: (mins(i), buiten(i), i))
    rollen = {lang: "lang"}

    def buren(a: int, b: int) -> bool:
        return (a - b) % 7 in (1, 6)

    # kwaliteit nooit direct voor of na de lange rit (alleen als er niets anders is)
    kandidaten = [i for i in dagen if i != lang and mins(i) >= 45]
    pool = [i for i in kandidaten if not buren(i, lang)] or kandidaten
    gekozen: list[int] = []
    for i in sorted(pool, key=lambda i: (-mins(i), i)):
        if len(gekozen) >= max_q:
            break
        if not any(buren(i, g) for g in gekozen):
            gekozen.append(i)
    for k, i in enumerate(sorted(gekozen)):
        rollen[i] = f"q{k}"
    for i in dagen:
        if i in rollen:
            continue
        na_zwaar = rollen.get((i - 1) % 7, "").startswith(("q", "lang"))
        rollen[i] = "herstel" if na_zwaar and mins(i) <= 60 else "duur"
    return rollen


def standaard_omgeving(s: dict, vk: dict) -> str:
    if s.get("omgeving_vast"):
        return s["omgeving"]
    binnen = {"ftp_test"} | (INTERVALSOORTEN if vk.get("intervallen_binnen", True) else set())
    if not s["buiten_toegestaan"] or s["soort"] in binnen:
        return "binnen"
    return "buiten"


def _duur_min(avail: int, f: float) -> int:
    return max(30, min(avail, round5(avail * f)))


def _kies(rol: str, m: dict, doel: str, avail: int, nq: int, vk: dict) -> tuple[str, int]:
    f, focus = m["factor"], m["focus"]
    if rol == "lang":
        if m["fase"] == "taper":
            return "duur", min(avail, 60)
        tempo = ((focus == "gemengd" and m["fase"] in ("opbouw", "piek"))
                 or (focus == "zone2" and m["p"] >= 0.5 and not m["herstel"]))
        return ("lange_rit_tempo" if tempo else "lange_rit"), max(45, min(avail, round5(avail * f)))
    if rol.startswith("q"):
        k = int(rol[1:])
        if m["herstel"]:
            # Een ramp-test elke herstelweek (4 weken) is te vaak: elke 8 weken is de
            # standaard. 0 = nooit; vk['ftp_test'] = False werkt ook nog (oude config).
            elke = int(vk.get("ftp_test_weken", 8)) if vk.get("ftp_test", True) else 0
            if k == nq - 1 and elke and m["nr"] % elke == 0:
                return "ftp_test", 40
            return "duur", _duur_min(avail, f)
        if m["fase"] == "taper":
            return ("openers", min(avail, 60)) if k == 0 else ("herstel", min(avail, 45))
        if focus == "zone2":
            return "duur", _duur_min(avail, f)
        if focus == "sweetspot":
            return "sweetspot", avail
        if focus == "gepolariseerd":
            return ("vo2max", avail) if k == 0 else ("duur", _duur_min(avail, f))
        lijst = KWALITEIT[doel][m["fase"]]
        return lijst[k % len(lijst)], avail
    if rol == "herstel":
        return "herstel", min(avail, 45)
    return "duur", _duur_min(avail, f)


# Doelzwaarte per soort aan het begin en eind van een blok (zie workouts.zwaarte).
FOCUSNAAM = {"gemengd": "Gemengd", "sweetspot": "Sweetspot", "zone2": "Zone 2", "gepolariseerd": "Gepolariseerd"}

DOELZWAARTE = {"tempo": (3, 3), "sweetspot": (3, 4), "drempel": (4, 5), "vo2max": (4, 5)}


def opties(soort: str, minuten: int, p: float, fase: str = "") -> list[tuple[str, workouts.Training]]:
    """Alle vormen van deze soort die in de tijd passen: klassiek, bibliotheek en eigen."""
    from . import bibliotheek, eigen
    uit, namen = [], set()
    for k in range(bibliotheek.aantal(soort)):
        t = workouts.bouw(soort, minuten, p, fase, k) if k else workouts.BOUWERS[soort](minuten, p, fase)
        if t.soort == soort and t.naam not in namen:  # een variant die niet past valt terug op duur
            namen.add(t.naam)
            uit.append((f"v:{k}", t))
    for w in eigen.voor_soort(soort):
        if 0.6 * minuten <= w.minuten <= minuten + 5:
            uit.append((f"e:{w.id}", workouts.Training(soort, w.naam, w.training.blokken, w.training.toelichting,
                                                       {"eigen": w.id})))
    return uit


def doelzwaarte(s: dict, p: float | None = None) -> int | None:
    """Doelzwaarte voor deze week: loopt op over het blok; je RPE en readiness
    (p_mod) trekken hem omlaag of omhoog; herstelweek hooguit 3."""
    lo_hi = DOELZWAARTE.get(s["soort"])
    if not lo_hi:
        return None
    if p is None:
        p = max(0.0, min(1.0, s.get("pb", s.get("p", 0))))
    # Gewoon afronden (0,5 → 1); Python's round() rondt 0,5 af naar 0 (naar even).
    doel = lo_hi[0] + int((lo_hi[1] - lo_hi[0]) * p + 0.5)
    # Voelde deze soort duidelijk te zwaar (RPE) of is je readiness matig: een stap
    # terug. Duidelijk te licht: een stap verder. Ook aan het eind van een blok.
    mod = s.get("p_mod", 0)
    if mod <= -0.2:
        doel = max(2, doel - 1)
    elif mod >= 0.2:
        doel = min(5, doel + 1)
    if s.get("max_zwaarte"):
        doel = min(doel, s["max_zwaarte"])
    return min(doel, 3) if s.get("herstelweek") else doel


def training_voor(s: dict) -> workouts.Training | None:
    """De training voor een dag. Eén plek, zodat scherm, .zwo en intervals.icu altijd
    hetzelfde zien. Voor intervalsoorten: uit alle vormen die passen (ook je eigen
    workouts) die met een zwaarte zo dicht mogelijk bij het doel voor deze week;
    daartussen wisselt het per week. Een ruil die je zelf koos wint altijd."""
    if s["soort"] == "rust":
        return None
    p = max(0.0, min(1.0, s.get("p", 0) + s.get("p_mod", 0)))
    fase, seed = s.get("fase", ""), s.get("variant", 0)
    doel = doelzwaarte(s)
    if s.get("ruil") or (doel is not None and s.get("variatie", True)):
        kandidaten = opties(s["soort"], s["minuten"], p, fase)
        gekozen = next((t for k, t in kandidaten if k == s.get("ruil")), None)
        if gekozen:
            s["keuze"] = s["ruil"]
            return gekozen
        if doel is not None and kandidaten:
            afstand = [(abs(workouts.zwaarte(t)["score"] - doel), k, t) for k, t in kandidaten]
            beste = min(a for a, _, _ in afstand)
            pool = [(k, t) for a, k, t in afstand if a == beste]
            k, t = pool[seed % len(pool)]
            s["keuze"] = k
            return t
    s["keuze"] = None
    return workouts.bouw(s["soort"], s["minuten"], p, fase, seed)


def voeding(minuten: float, zwaarte: int, binnen: bool = False) -> str | None:
    """Algemene richtlijn uit de sportvoeding voor koolhydraten en drinken, oplopend
    met de duur. Geen persoonlijk advies. Voor buitenritten rekent cwem het met het
    weer uit (zie cwem_link); dit is de versie voor binnen, en voor buiten zonder cwem.
    Binnen zweet je meer: geen rijwind om af te koelen."""
    if minuten < (45 if binnen else 75):
        return None
    if minuten < 75:
        kh = None
    elif minuten < 90:
        kh = (30, 60) if zwaarte >= 3 else None
    elif minuten <= 150:
        kh = (40, 60)
    else:
        kh = (60, 90)
    uren = minuten / 60
    per_uur = (0.75, 1.0) if binnen else (0.5, 0.75)
    komma = lambda x: f"{round(x, 1):g}".replace(".", ",")  # noqa: E731
    liters = f"{komma(per_uur[0] * uren)}–{komma(per_uur[1] * uren)} liter"
    drinken = (f"{liters} drinken, met elektrolyten; zet de ventilator aan" if binnen
               else f"{liters} drinken; meer en met zout als het warm is")
    if not kh:
        return f"Voeding: water is genoeg; {drinken}."
    totaal = f"{round(kh[0] * uren / 10) * 10}–{round(kh[1] * uren / 10) * 10} g"
    tip = " Ben je dat niet gewend, bouw het op." if kh[1] >= 90 else ""
    return f"Voeding: {kh[0]}–{kh[1]} g koolhydraten per uur (totaal {totaal}), {drinken}.{tip}"


def cwem_link(s: dict, cwem_url: str, start: str) -> str:
    """Link naar cwem met deze rit erin: kleding, drinken en eten met het weer van je
    rijtijd. Tempo voor de kleding uit de zwaarte; de zwaarte zelf voor het eten."""
    from urllib.parse import urlencode
    z = int(s.get("zwaarte") or 3)
    q = {"date": s["datum"], "time": start, "hours": round((s.get("duur") or s["minuten"]) / 60, 2),
         "pace": "easy" if z <= 2 else "steady" if z == 3 else "hard", "effort": z, "name": s.get("naam", "")}
    return f"{cwem_url.rstrip('/')}/?{urlencode(q)}#ride"


def vul_in(s: dict) -> dict:
    if s["soort"] == "rust":
        s.update(naam="Rust", beschrijving="Geen training.", duur=0, tss=0, zwaarte=0, voeding=None)
        return s
    t = training_voor(s)
    s["naam"] = t.naam
    s["beschrijving"] = t.beschrijving()
    s["duur"] = round(t.minuten)
    z = workouts.zwaarte(t)
    s["tss"], s["zwaarte"] = z["tss"], z["score"]
    s["voeding"] = voeding(t.minuten, z["score"], binnen=s.get("omgeving") == "binnen")
    return s


def genereer(cfg: dict, start: date) -> list[dict]:
    start = start - timedelta(days=start.weekday())  # altijd op maandag beginnen
    doel = cfg["doel"]["type"]
    if doel not in KWALITEIT:
        raise ValueError(f"Onbekend doel '{doel}', kies ftp, duur of tocht.")
    week = cfg["week"]
    vk = cfg.get("voorkeuren", {}) or {}
    rollen = dagrollen(week, int(vk.get("max_kwaliteit_per_week", 2)))
    nq = sum(r.startswith("q") for r in rollen.values())
    focus = weekfocus(cfg["doel"], start)
    plan = []
    for w, m in enumerate(weekfasen(len(focus), doel, focus)):
        for i, rol in sorted(rollen.items()):
            dag = DAGEN[i]
            soort, minuten = _kies(rol, m, doel, beschikbaar(week, dag), nq, vk)
            s = {
                "datum": (start + timedelta(weeks=w, days=i)).isoformat(),
                "dag": dag, "week": w + 1, "fase": m["fase"], "focus": m["focus"],
                # Afwisseling: elke week een andere vorm; twee intervaldagen in
                # dezelfde week krijgen elk een andere.
                "variant": (w + 2 * int(rol[1:]) if rol.startswith("q") else w) if vk.get("variatie", True) else 0,
                "herstelweek": m["herstel"], "rol": rol, "p": round(m["p"], 2), "pb": round(m["pb"], 2),
                "basis_soort": soort, "basis_minuten": minuten,
                "soort": soort, "minuten": minuten,
                "buiten_toegestaan": bool(week[dag].get("buiten", False)),
                "status": "gepland", "notities": [],
            }
            s["variatie"] = vk.get("variatie", True)
            if rol.startswith("q") and rol != "q0":
                s["max_zwaarte"] = 4  # hooguit één training van zwaarte 5 per week
            if soort == "ftp_test":  # testen vergelijk je alleen in dezelfde vorm
                s["variant"] = 1 if vk.get("ftp_test_vorm") == "20min" else 0
            s["omgeving"] = standaard_omgeving(s, vk)
            plan.append(vul_in(s))
    return plan
