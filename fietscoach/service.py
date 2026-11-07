"""Samenhang: instellingen en plan laden/bewaren, bijsturen en synchroniseren.

Bestanden in de datamap:
  plan.json         het schema (één regel per trainingsdag)
  status.json       laatste stand uit intervals.icu (FTP, eFTP, fitheid, ritten)
  instellingen.json wat je in het scherm Instellingen invult (wint van config.yaml)
  feedback.json     je RPE per rit en je readiness per dag
"""
from __future__ import annotations

import copy
import fcntl
import functools
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from . import adapt, eigen, planner, weather
from .intervals import PREFIX, Intervals, eftp_uit, naar_event

CONFIG = Path(os.environ.get("FIETSCOACH_CONFIG", "config.yaml"))
DATA = Path(os.environ.get("FIETSCOACH_DATA", "data"))
HORIZON = 14  # dagen vooruit: bijsturen en naar intervals.icu

# Eigen .zwo-workouts staan bij de data, niet in de repo. Een functie zodat
# tests (en een andere FIETSCOACH_DATA) de map kunnen wisselen.
eigen.map_bron = lambda: DATA / "workouts"
INSTELBAAR = ("doel", "week", "voorkeuren", "weer", "uitzonderingen", "afwezig", "berichten_aan")
WEER_GELDIG_UUR = 3     # zo lang gebruiken we een opgehaald weerbericht bij invoer in het scherm
FITHEID_DAGEN = 90      # zo ver terug halen we fitheid en vermoeidheid op, voor de grafiek
FROZEN_DAGEN = 21       # ouder dan dit: status uit het vorige plan (ritten halen we 28 dagen terug)


# --- vergrendeling ----------------------------------------------------------------
# De ochtendtimer (eigen proces) en de webapp (meerdere threads) lezen en schrijven
# dezelfde bestanden. Zonder slot overschrijft de een de ander: bewezen met
# test_geen_verloren_invoer_bij_gelijktijdig_schrijven. Een bestandsslot regelt het
# tussen processen; de RLock binnen het proces, en maakt het herintreedbaar
# (pas_toe → bijsturen → _schrijf).

_slot = threading.RLock()
_diepte = threading.local()


@contextmanager
def vergrendeld():
    with _slot:
        d = getattr(_diepte, "n", 0)
        fd = None
        if d == 0:
            DATA.mkdir(parents=True, exist_ok=True)
            fd = os.open(DATA / ".slot", os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        _diepte.n = d + 1
        try:
            yield
        finally:
            _diepte.n = d
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


def onder_slot(f):
    @functools.wraps(f)
    def omhulsel(*a, **kw):
        with vergrendeld():
            return f(*a, **kw)
    return omhulsel


# --- opslag -------------------------------------------------------------------

def _lees(naam: str, standaard):
    p = DATA / naam
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else standaard


def _schrijf(naam: str, inhoud) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = DATA / (naam + ".tmp")
    tmp.write_text(json.dumps(inhoud, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(DATA / naam)


# --- versie van de gegevens -----------------------------------------------------
# Verhoog SCHEMA en voeg een stap toe aan MIGRATIES als de vorm van de bestanden
# in DATA verandert. Elke stap brengt de gegevens van versie n naar n+1.

SCHEMA = 2


class DataTeNieuw(RuntimeError):
    pass


def _naar_1() -> None:
    laad_basis()  # oude installaties: basis.json uit plan.json halen


def _naar_2() -> None:
    fb = _lees("feedback.json", None)
    if fb is not None:
        fb.setdefault("ruil", {})
        _schrijf("feedback.json", fb)


MIGRATIES = {0: _naar_1, 1: _naar_2}
_gemigreerd: set[str] = set()


def gegevensversie() -> int:
    v = _lees("versie.json", None)
    if v is not None:
        return int(v.get("schema", 0))
    return 0 if (DATA / "plan.json").exists() or (DATA / "basis.json").exists() else SCHEMA


@onder_slot
def migreer() -> list[str]:
    """Brengt de bestanden in DATA naar de huidige vorm. Veilig om vaak aan te roepen."""
    if str(DATA) in _gemigreerd:
        return []
    v, log = gegevensversie(), []
    if v > SCHEMA:
        raise DataTeNieuw(f"De gegevens zijn van een nieuwere versie (schema {v}, deze app kent {SCHEMA}). "
                          "Update de app, of zet de back-up van vóór de update terug.")
    while v < SCHEMA:
        MIGRATIES[v]()
        v += 1
        log.append(f"Gegevens bijgewerkt naar schema {v}.")
    if v != _lees("versie.json", {}).get("schema") and DATA.exists():
        _schrijf("versie.json", {"schema": v})
    _gemigreerd.add(str(DATA))
    return log


# --- geschiedenis ------------------------------------------------------------------

GESCHIEDENIS = "geschiedenis.jsonl"
MAX_GESCHIEDENIS = 1000


def _kort(s: dict) -> str:
    if s["soort"] == "rust":
        return "Rust"
    waar = "Zwift" if s.get("omgeving") == "binnen" else "buiten"
    return f"{s.get('naam', s['soort'])} · {s.get('duur', s.get('minuten'))} min · {waar}"


def wijzigingen(oud: list[dict], nieuw: list[dict], vandaag: date, bron: str) -> list[dict]:
    """Wat er voor vandaag en later veranderd is, met de reden die de bijsturing gaf."""
    v = vandaag.isoformat()
    tijd = datetime.now().isoformat(timespec="seconds")
    if bron == "nieuw":
        return [{"tijd": tijd, "datum": None, "van": None, "naar": None, "waarom": ["Nieuw schema gemaakt"]}] \
            if oud else []
    was = {s["datum"]: s for s in oud}
    uit = []
    for s in nieuw:
        o = was.get(s["datum"])
        if s["datum"] < v or not o or s.get("status") != "gepland":
            continue
        if _kort(o) == _kort(s):
            continue
        nieuwe = [n for n in s.get("notities", []) if n not in o.get("notities", [])]
        uit.append({"tijd": tijd, "datum": s["datum"], "van": _kort(o), "naar": _kort(s),
                    "waarom": nieuwe or s.get("notities") or ["Bijgestuurd"]})
    return uit


def schrijf_geschiedenis(regels: list[dict]) -> None:
    if not regels:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    p = DATA / GESCHIEDENIS
    with open(p, "a", encoding="utf-8") as f:
        for r in regels:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    alles = p.read_text(encoding="utf-8").splitlines()
    if len(alles) > MAX_GESCHIEDENIS * 1.2:
        tmp = DATA / (GESCHIEDENIS + ".tmp")
        tmp.write_text("\n".join(alles[-MAX_GESCHIEDENIS:]) + "\n", encoding="utf-8")
        tmp.replace(p)


def geschiedenis(n: int = 200) -> list[dict]:
    p = DATA / GESCHIEDENIS
    if not p.exists():
        return []
    uit = []
    for regel in p.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            uit.append(json.loads(regel))
        except ValueError:
            continue
    return uit


def waarom_per_dag() -> dict[str, list[dict]]:
    """Per datum de wijzigingen, nieuwste eerst, sinds het laatste nieuwe schema."""
    per: dict[str, list[dict]] = {}
    for r in reversed(geschiedenis()):
        if r.get("datum") is None:
            break
        per.setdefault(r["datum"], []).append(r)
    return per


def laad_config(pad: Path | None = None) -> dict:
    with open(pad or CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    for k, v in _lees("instellingen.json", {}).items():
        if k in INSTELBAAR:
            cfg[k] = v
    cfg.setdefault("uitzonderingen", {})
    return cfg


@onder_slot
def bewaar_instellingen(cfg: dict) -> None:
    _schrijf("instellingen.json", {k: cfg.get(k) for k in INSTELBAAR if cfg.get(k) is not None})


def laad_plan() -> list[dict]:
    """Het afgeleide schema: basis + al je invoer, zoals het scherm en de sync het zien."""
    return _lees("plan.json", [])


def laad_basis() -> list[dict]:
    """Het schema zoals de generator het maakte. Wordt nooit bijgestuurd, alleen vervangen.
    Oudere installaties hadden alleen plan.json: daar halen we de basis eenmalig uit."""
    basis = _lees("basis.json", None)
    if basis is None:
        oud = _lees("plan.json", [])
        basis = [{k: v for k, v in x.items() if k not in ("status", "score", "notities", "weer", "weer_slecht",
                                                         "p_mod", "herkomst", "verschoven")}
                 | {"soort": x["basis_soort"], "minuten": x["basis_minuten"]}
                 for x in oud if "basis_soort" in x]
        if basis:
            _schrijf("basis.json", basis)
    return basis


def laad_status() -> dict:
    return _lees("status.json", {})


def laad_feedback() -> dict:
    fb = _lees("feedback.json", {})
    fb.setdefault("rpe", {})
    fb.setdefault("readiness", {})
    fb.setdefault("ruil", {})
    fb.setdefault("extra", {})
    return fb


def bewaar_feedback(fb: dict) -> None:
    _schrijf("feedback.json", fb)


def client(cfg: dict) -> Intervals | None:
    ic = cfg.get("intervals") or {}
    sleutel = os.environ.get("INTERVALS_API_KEY") or ic.get("api_key")
    if not sleutel or str(sleutel).startswith("PLAK"):
        return None
    return Intervals(str(ic.get("athlete_id", "0")), sleutel)


def starttijd(week: dict, datum: str) -> str:
    """Wanneer je op die dag vertrekt; standaard 09:30 in het weekend, 18:30 doordeweeks."""
    dag = planner.DAGEN[date.fromisoformat(datum).weekday()]
    return (week.get(dag) or {}).get("start") or ("09:30" if dag in ("za", "zo") else "18:30")


# --- schema maken ---

@onder_slot
def genereer(cfg: dict, start: date | None = None, vandaag: date | None = None) -> list[dict]:
    """Nieuw basisschema. Wat al voorbij is blijft staan; vanaf vandaag het nieuwe.
    Daarna meteen afleiden (zonder netwerk), zodat het scherm klopt."""
    vandaag = vandaag or date.today()
    migreer()
    start = start or date.fromisoformat(str(cfg["doel"]["startdatum"]))
    nieuw = planner.genereer(cfg, start)
    v = vandaag.isoformat()
    oud = laad_basis()
    basis = ([x for x in oud if x["datum"] < v] + [x for x in nieuw if x["datum"] >= v]) if oud else nieuw
    _schrijf("basis.json", basis)
    bijsturen(cfg, vandaag, ververs=False, weer_ophalen=False, bron="nieuw")
    return laad_plan()


def _extra_dagen(plan: list[dict], uitz: dict, vandaag: date, week: dict, vk: dict) -> None:
    """Een dag die normaal vrij is, maar waarop je nu wél tijd hebt, krijgt een duurrit."""
    v = vandaag.isoformat()
    bestaand = {s["datum"] for s in plan}
    for d, m in uitz.items():
        if d < v or d in bestaand or int(m) < 30:
            continue
        dt = date.fromisoformat(d)
        maandag = (dt - timedelta(days=dt.weekday())).isoformat()
        zondag = (dt + timedelta(days=6 - dt.weekday())).isoformat()
        buur = next((s for s in plan if maandag <= s["datum"] <= zondag), None)
        if not buur:
            continue
        dag = planner.DAGEN[dt.weekday()]
        minuten = max(30, int(m) if not buur["herstelweek"] else planner.round5(int(m) * 0.65))
        s = {"datum": d, "dag": dag, "week": buur["week"], "fase": buur["fase"], "focus": buur.get("focus"),
             "herstelweek": buur["herstelweek"], "rol": "extra", "p": buur["p"], "extra": True,
             "variant": buur.get("variant", 0) + 1, "basis_soort": "duur", "basis_minuten": minuten,
             "soort": "duur", "minuten": minuten, "buiten_toegestaan": bool((week.get(dag) or {}).get("buiten", True)),
             "status": "gepland", "notities": []}
        s["omgeving"] = planner.standaard_omgeving(s, vk)
        plan.append(s)
    plan.sort(key=lambda s: s["datum"])


EXTRA_SOORTEN = ("duur", "herstel", "tempo", "sweetspot", "drempel", "vo2max")


def _handmatige_extra(plan: list[dict], extra: dict, week: dict) -> None:
    """Zelf toegevoegde trainingen op een dag zonder training. Week, fase en opbouw
    komen van de dichtstbijzijnde training, zodat zwaarte en variant kloppen."""
    if not plan:
        return
    bestaand = {s["datum"] for s in plan}
    for d, e in sorted(extra.items()):
        if d in bestaand:
            continue
        dt = date.fromisoformat(d)
        maandag = (dt - timedelta(days=dt.weekday())).isoformat()
        zondag = (dt + timedelta(days=6 - dt.weekday())).isoformat()
        buren = [s for s in plan if maandag <= s["datum"] <= zondag] or plan
        buur = min(buren, key=lambda s: abs((date.fromisoformat(s["datum"]) - dt).days))
        soort = e.get("soort") if e.get("soort") in EXTRA_SOORTEN else "duur"
        dag = planner.DAGEN[dt.weekday()]
        waar = e.get("omgeving")
        s = {"datum": d, "dag": dag, "week": buur["week"], "fase": buur["fase"], "focus": buur.get("focus"),
             "herstelweek": buur["herstelweek"], "rol": "extra", "p": buur["p"], "pb": buur.get("pb", buur["p"]),
             "extra": True, "handmatig": True, "variant": buur.get("variant", 0) + 2,
             "variatie": buur.get("variatie", True), "basis_soort": soort, "basis_minuten": int(e["minuten"]),
             "soort": soort, "minuten": int(e["minuten"]),
             "buiten_toegestaan": waar != "binnen",
             "status": "gepland", "notities": ["Extra training, zelf toegevoegd"]}
        if waar in ("binnen", "buiten"):
            s["omgeving"] = waar
            s["omgeving_vast"] = True
        plan.append(s)
        bestaand.add(d)
    plan.sort(key=lambda s: s["datum"])


def _waarschuw_extra(plan: list[dict]) -> None:
    """Een zelf toegevoegde intensieve training naast een andere intensieve: zeg het erbij."""
    zwaar = planner.INTERVALSOORTEN | {"ftp_test", "lange_rit_tempo"}
    per_dag = {s["datum"]: s for s in plan}
    for s in plan:
        if not s.get("handmatig") or s["status"] != "gepland" or s["soort"] not in zwaar:
            continue
        dt = date.fromisoformat(s["datum"])
        for delta, naam in ((-1, "Gisteren"), (1, "Morgen")):
            b = per_dag.get((dt + timedelta(days=delta)).isoformat())
            if b and b["soort"] in zwaar and b["status"] in ("gepland", "gedaan"):
                s["notities"].append(f"{naam} staat ook een intensieve training; twee dagen achter elkaar is zwaar")


def afleiden(basis: list[dict], cfg: dict, status: dict, fb: dict, verwachting,
             vandaag: date, oud: list[dict]) -> tuple[list[dict], list[str]]:
    """Het hele schema opnieuw uit basis + invoer. Puur: zelfde invoer, zelfde uitkomst."""
    vk = cfg.get("voorkeuren", {}) or {}
    week = cfg["week"]
    uitz = {str(k): int(v) for k, v in (cfg.get("uitzonderingen") or {}).items()}
    afwezig = adapt.afwezigheid(cfg.get("afwezig") or [])
    ritten = status.get("ritten", {}) or {}
    log: list[str] = []
    v = vandaag.isoformat()

    plan = adapt.basis_kopie(basis, vk)
    _handmatige_extra(plan, fb.get("extra") or {}, week)
    # Lang geleden: die ritten halen we niet meer op, dus de status van toen bewaren.
    grens = (vandaag - timedelta(days=FROZEN_DAGEN)).isoformat()
    vorig = {x["datum"]: x for x in oud}
    for s in plan:
        if s["datum"] < grens and s["datum"] in vorig:
            for k in ("status", "score"):
                if k in vorig[s["datum"]]:
                    s[k] = vorig[s["datum"]][k]
    adapt.markeer(plan, ritten, vandaag, afwezig, vanaf=grens)
    log += adapt.herplan_gemist(plan, week, vandaag)
    _extra_dagen(plan, uitz, vandaag, week, vk)
    log += adapt.pas_afwezigheid_toe(plan, afwezig, vandaag)

    tot = (vandaag + timedelta(days=HORIZON - 1)).isoformat()
    venster = [s for s in plan if v <= s["datum"] <= tot and s["status"] == "gepland"]
    week_kort = [s for s in venster if s["datum"] <= (vandaag + timedelta(days=6)).isoformat()]
    log += adapt.pas_uitzonderingen_toe(venster, uitz, week)
    log += adapt.pas_ongepland_toe(plan, venster, ritten, vandaag, week)
    log += adapt.pas_vorm_toe([s for s in week_kort if s["soort"] != "rust"], status.get("vorm"))
    objectief, _ = adapt.objectieve_readiness(status.get("wellness") or [], vandaag)
    score = adapt.readiness_score(fb["readiness"].get(v), objectief)
    log += adapt.pas_readiness_toe(venster, score, vandaag)

    # Zelf gekozen andere training (ruilen op de kaart van vandaag) wint.
    for s in venster:
        k = fb["ruil"].get(s["datum"])
        if not k or s["soort"] == "rust":
            continue
        if k.startswith("s:"):
            s["soort"] = k[2:]
            s["notities"].append("Zelf gekozen: " + {"duur": "duurrit", "herstel": "herstelrit"}.get(k[2:], k[2:]))
        else:
            s["ruil"] = k
            s["notities"].append("Zelf gekozen training")

    _waarschuw_extra(plan)  # ook gisteren gereden telt mee

    niv = adapt.niveaus(plan, fb["rpe"])
    in_venster = {id(s) for s in venster}
    for s in plan:
        if s["datum"] >= v and s["status"] == "gepland":
            off, uitleg = niv.get(s["soort"], (0.0, ""))
            s["p_mod"] = s.get("p_mod", 0) + off
            if uitleg and id(s) in in_venster:
                s["notities"].append(uitleg)

    if verwachting:
        log += adapt.pas_weer_toe([s for s in venster if s["soort"] != "rust"], verwachting, week, vk,
                                  cfg.get("weer", {}) or {})
    bewerkt = status.get("intervals_bewerkt", {}) or {}
    for s in plan:
        b = bewerkt.get(PREFIX + s["datum"])
        if b and s["status"] == "gepland":
            s["intervals_bewerkt"] = b["wat"]
            if b["wat"] == "verplaatst":
                d = b.get("datum", "")
                s["notities"].append(f"In intervals.icu verplaatst naar {d[8:10]}-{d[5:7]}; dat laten we zo")
            elif b["wat"] == "verwijderd":
                s["notities"].append("In intervals.icu verwijderd; dat laten we zo")
            else:
                s["notities"].append(f"In intervals.icu aangepast ({b.get('naam', '')}); dat laten we zo")
    for s in plan:
        if s["soort"] != "rust" and s["status"] == "gepland":
            s["omgeving"] = s.get("omgeving") or planner.standaard_omgeving(s, vk)
        planner.vul_in(s)
        sc = adapt.trainingsscore(s, ritten.get(s["datum"]))
        if sc:
            s["score"] = sc
    return plan, log


def _weer(cfg: dict, ophalen: bool):
    """Uurverwachting uit de cache (weer.json); vers ophalen als gevraagd of als hij oud is.
    Lukt ophalen niet, dan de cache zolang die niet ouder dan twee dagen is."""
    cache = _lees("weer.json", None)
    leeftijd = None
    if cache:
        leeftijd = (datetime.now() - datetime.fromisoformat(cache["opgehaald"])).total_seconds() / 3600
    if ophalen and (leeftijd is None or leeftijd > WEER_GELDIG_UUR or ophalen == "altijd"):
        try:
            loc = cfg["locatie"]
            v = weather.verwachting(loc["lat"], loc["lon"])
            cache = {"opgehaald": datetime.now().isoformat(timespec="seconds"), "dag": v.dag, "uur": v.uur}
            _schrijf("weer.json", cache)
            leeftijd = 0
        except Exception:  # noqa: BLE001
            pass
    if not cache or leeftijd is None or leeftijd > 48:
        return None
    v = weather.Verwachting(cache["dag"], cache["uur"])
    return lambda d, m: v.venster(d, starttijd(cfg["week"], d), m)


# --- bijsturen ----------------------------------------------------------------

@onder_slot
def bijsturen(cfg: dict, vandaag: date | None = None, ic: Intervals | None = None,
              verwachting=None, ververs: bool = True, weer_ophalen: bool | str = True,
              bron: str = "bijsturen") -> list[str]:
    """ververs=True (ochtendtimer, knop Bijsturen): ritten, wellness en weer vers ophalen.
    ververs=False (invoer in het scherm): alleen de caches gebruiken, dus direct klaar."""
    vandaag = vandaag or date.today()
    migreer()
    basis = laad_basis()
    if not basis:
        return ["Nog geen schema. Maak eerst een schema."]
    status, fb = laad_status(), laad_feedback()
    log: list[str] = []

    if ververs:
        ic = ic or client(cfg)
        if ic:
            try:
                acts = ic.activiteiten(vandaag - timedelta(days=28), vandaag)
                status["ritten"] = adapt.ritten_per_dag(acts)
                well = ic.wellness(vandaag - timedelta(days=FITHEID_DAGEN), vandaag)
                grens = (vandaag - timedelta(days=28)).isoformat()
                status["wellness"] = [{k: w.get(k) for k in ("id", "hrv", "restingHR")}
                                      for w in well if w.get("id", "") >= grens]
                status["fitheid"] = [[w["id"], round(w["ctl"], 1), round(w["atl"], 1)]
                                     for w in well if w.get("id") and w.get("ctl") is not None and w.get("atl") is not None]
                met_ctl = [w for w in well if w.get("ctl") is not None]
                if met_ctl:
                    laatste = met_ctl[-1]
                    status.update(ctl=round(laatste["ctl"]), atl=round(laatste["atl"]),
                                  vorm=round(laatste["ctl"] - laatste["atl"]))
                    if eftp_uit(laatste):
                        status["eftp"] = eftp_uit(laatste)
                status["ftp"] = ic.ftp()
                status["intervals_opgehaald"] = datetime.now().isoformat(timespec="seconds")
                for d, r in status["ritten"].items():  # RPE uit intervals.icu overnemen
                    if r.get("rpe") and d not in fb["rpe"]:
                        fb["rpe"][d] = int(r["rpe"])
            except Exception as e:  # noqa: BLE001
                log.append(f"intervals.icu niet bereikbaar: {e}")
        else:
            log.append("Geen intervals.icu-sleutel ingesteld: alleen weer en je eigen invoer toegepast.")

    if verwachting is None:
        verwachting = _weer(cfg, ("altijd" if ververs else True) if weer_ophalen else False)
        if verwachting is None and weer_ophalen:
            log.append("Geen weerbericht beschikbaar.")

    vorig = laad_plan()
    plan, extra = afleiden(basis, cfg, status, fb, verwachting, vandaag, vorig)
    log += extra
    schrijf_geschiedenis(wijzigingen(vorig, plan, vandaag, bron))
    status["bijgestuurd"] = datetime.now().strftime("%d-%m %H:%M")
    status["bijgestuurd_iso"] = datetime.now().isoformat(timespec="seconds")
    status["log"] = log
    _schrijf("plan.json", plan)
    _schrijf("status.json", status)
    bewaar_feedback(fb)
    return log


def vingerafdruk(datum: str, naam: str, soort: str, beschrijving: str) -> dict:
    """Wat we van een event onthouden om te zien of jij het in intervals.icu wijzigde."""
    tekst = " ".join((beschrijving or "").split())
    return {"datum": datum[:10], "naam": (naam or "").strip(), "type": soort or "",
            "tekst": hashlib.sha1(tekst.encode()).hexdigest()[:12]}


def _vingerafdruk_event(e: dict) -> dict:
    return vingerafdruk(e.get("start_date_local") or "", e.get("name") or "", e.get("type") or "",
                        e.get("description") or "")


def sync(cfg: dict, vandaag: date | None = None, ic: Intervals | None = None) -> str:
    """Komende 14 dagen naar intervals.icu. Trainingen die jij daar (of via je Wahoo
    of Zwift) verplaatste, aanpaste of verwijderde, laten we met rust: jouw keuze
    wint van het plan, tot je in de app op 'Terug naar plan' klikt."""
    vandaag = vandaag or date.today()
    ic = ic or client(cfg)
    if not ic:
        return "Geen intervals.icu-sleutel ingesteld."
    tot = vandaag + timedelta(days=HORIZON)
    status = laad_status()
    gepusht: dict = status.get("gepusht", {}) or {}
    bewerkt: dict = status.get("intervals_bewerkt", {}) or {}
    v = vandaag.isoformat()

    # 1. Wat staat er nu in de kalender van ons? Ruim genomen: een verplaatste
    #    training kan buiten de 14 dagen zijn gezet.
    huidig = {}
    for e in ic.events(vandaag - timedelta(days=1), tot + timedelta(days=28)):
        ext = str(e.get("external_id") or "")
        if ext.startswith(PREFIX):
            huidig[ext] = e
    for ext, vorige in gepusht.items():
        if ext in bewerkt or ext[len(PREFIX):] < v:
            continue
        e = huidig.get(ext)
        if e is None:
            bewerkt[ext] = {"wat": "verwijderd", "sinds": datetime.now().isoformat(timespec="seconds")}
        elif _vingerafdruk_event(e) != vorige:
            nu = _vingerafdruk_event(e)
            wat = "verplaatst" if nu["datum"] != vorige["datum"] else "aangepast"
            bewerkt[ext] = {"wat": wat, "datum": nu["datum"], "naam": nu["naam"],
                            "sinds": datetime.now().isoformat(timespec="seconds")}

    # 2. Plan neerzetten, behalve wat jij hebt gewijzigd.
    sessies = [s for s in laad_plan() if v <= s["datum"] < tot.isoformat()
               and s["status"] == "gepland" and s["soort"] != "rust"]
    events = [naar_event(s) for s in sessies if PREFIX + s["datum"] not in bewerkt]
    if events:
        ic.upsert(events)
    for e in events:
        gepusht[e["external_id"]] = vingerafdruk(e["start_date_local"], e["name"], e["type"], e["description"])

    # 3. Dagen zonder training: ons event weg, maar niet als jij het had gewijzigd.
    gewenst = {e["external_id"] for e in events}
    weg_ids = [PREFIX + (vandaag + timedelta(days=i)).isoformat() for i in range(HORIZON)]
    weg_ids = [e for e in weg_ids if e not in gewenst and e not in bewerkt]
    weg = ic.verwijder_extern(weg_ids)
    for e in weg_ids:
        gepusht.pop(e, None)

    # Oude administratie opruimen.
    grens = (vandaag - timedelta(days=2)).isoformat()
    gepusht = {k: x for k, x in gepusht.items() if k[len(PREFIX):] >= grens}
    bewerkt = {k: x for k, x in bewerkt.items() if k[len(PREFIX):] >= grens}
    with vergrendeld():
        status = laad_status()
        status.update(gepusht=gepusht, intervals_bewerkt=bewerkt)
        status["gesynct"] = datetime.now().strftime("%d-%m %H:%M")
        status["gesynct_iso"] = datetime.now().isoformat(timespec="seconds")
        status.pop("sync_fout", None)
        _schrijf("status.json", status)
    tekst = f"{len(events)} trainingen naar intervals.icu gezet" + (f", {weg} oude verwijderd" if weg else "")
    eigen_keuze = [k for k in bewerkt if k[len(PREFIX):] >= v]
    if eigen_keuze:
        tekst += f"; {len(eigen_keuze)} door jou gewijzigd en ongemoeid gelaten"
    return tekst + "."


@onder_slot
def terug_naar_plan(datum: str) -> bool:
    """Jouw wijziging in intervals.icu loslaten: de volgende sync zet het plan terug."""
    status = laad_status()
    ext = PREFIX + datum
    bewerkt = status.get("intervals_bewerkt", {}) or {}
    if ext not in bewerkt:
        return False
    bewerkt.pop(ext)
    (status.get("gepusht") or {}).pop(ext, None)
    status["intervals_bewerkt"] = bewerkt
    _schrijf("status.json", status)
    return True


def sync_veilig(cfg: dict | None = None) -> str:
    """Sync die nooit een fout gooit; een fout komt in status (en daarmee in /health)."""
    cfg = cfg or laad_config()
    if not client(cfg):
        return ""
    try:
        return sync(cfg)
    except Exception as e:  # noqa: BLE001
        with vergrendeld():
            st = laad_status()
            st["sync_fout"] = f"{datetime.now().isoformat(timespec='seconds')} {e}"
            _schrijf("status.json", st)
        return f"Synchroniseren mislukt: {e}"


def pas_toe(cfg: dict | None = None, ververs: bool = True) -> str:
    """Bijsturen en synchroniseren in één keer (ochtendtimer en de knop Bijsturen)."""
    cfg = cfg or laad_config()
    log = bijsturen(cfg, ververs=ververs)
    s = sync_veilig(cfg)
    return " ".join(log + ([s] if s else []))


def pas_toe_snel(cfg: dict | None = None) -> str:
    """Na invoer in het scherm: direct lokaal bijsturen met de caches. De sync naar
    intervals.icu doet de webapp daarna op de achtergrond (sync_veilig)."""
    cfg = cfg or laad_config()
    return " ".join(bijsturen(cfg, ververs=False))


def gezondheid(nu: datetime | None = None, max_uren: int = 36) -> tuple[bool, dict]:
    """Voor Uptime Kuma: gezond als de laatste sync recent is en er geen fout openstaat."""
    nu = nu or datetime.now()
    st = laad_status()
    info = {k: st.get(k) for k in ("gesynct_iso", "bijgestuurd_iso", "sync_fout")}
    if not st.get("gesynct_iso"):
        return False, info | {"reden": "nog nooit gesynchroniseerd"}
    leeftijd = (nu - datetime.fromisoformat(st["gesynct_iso"])).total_seconds() / 3600
    info["uren_sinds_sync"] = round(leeftijd, 1)
    if st.get("sync_fout"):
        return False, info | {"reden": "laatste sync mislukt"}
    if leeftijd > max_uren:
        return False, info | {"reden": f"langer dan {max_uren} uur geen sync"}
    return True, info


# --- berichten -----------------------------------------------------------------------

def berichten_aan(cfg: dict) -> dict:
    return {"ochtend": True, "week": True} | (cfg.get("berichten_aan") or {})


def _verstuur(cfg: dict, soort: str, titel: str, tekst: str, pad: str) -> str:
    from . import melding
    if not melding.kanalen(cfg):
        return "Geen berichtkanaal ingesteld (ntfy of Telegram in config.yaml)."
    uitslag = melding.stuur(cfg, titel, tekst, pad)
    with vergrendeld():
        st = laad_status()
        st[f"bericht_{soort}"] = {"tijd": datetime.now().isoformat(timespec="seconds"),
                                  "ok": all(ok for _, ok, _ in uitslag),
                                  "uitslag": [f"{k}: {u}" for k, _, u in uitslag]}
        _schrijf("status.json", st)
    return " · ".join(f"{k} {'✓' if ok else '✗ ' + u}" for k, ok, u in uitslag)


def ochtendbericht(cfg: dict, vandaag: date | None = None, altijd: bool = False) -> str:
    """Na de ochtendronde: de training van vandaag. Op een rustdag geen bericht."""
    from . import inzicht
    if not altijd and not berichten_aan(cfg)["ochtend"]:
        return "Ochtendbericht staat uit."
    vandaag = vandaag or date.today()
    plan = laad_plan()
    s = next((x for x in plan if x["datum"] == vandaag.isoformat()), None)
    link = (planner.cwem_link(s, str(cfg["cwem_url"]), starttijd(cfg.get("week") or {}, s["datum"]))
            if s and cfg.get("cwem_url") and s.get("omgeving") == "buiten" else None)
    inhoud = inzicht.ochtendtekst(plan, laad_status(), laad_feedback(), vandaag, link)
    if not inhoud:
        if not altijd:
            return "Rustdag: geen ochtendbericht."
        inhoud = ("Fietscoach: testbericht", "Vandaag geen training. Zo ziet een bericht eruit.")
    return _verstuur(cfg, "ochtend", *inhoud, "/")


def weekoverzicht(vandaag: date | None = None) -> dict:
    """Terugblik op de week waarin `vandaag` valt (op maandag en dinsdag: de vorige week)."""
    from . import inzicht
    vandaag = vandaag or date.today()
    maandag = vandaag - timedelta(days=vandaag.weekday())
    if vandaag.weekday() <= 1:
        maandag -= timedelta(days=7)
    return inzicht.weekterugblik(laad_plan(), laad_status(), laad_feedback(), maandag)


def weekbericht(cfg: dict, vandaag: date | None = None) -> str:
    from . import inzicht
    if not berichten_aan(cfg)["week"]:
        return "Weekterugblik staat uit."
    w = weekoverzicht(vandaag)
    return _verstuur(cfg, "week", *inzicht.weektekst(w, planner.FOCUSNAAM), "/")


# --- invoer vanuit het scherm ---------------------------------------------------

@onder_slot
def zet_rpe(datum: str, rpe: int) -> None:
    fb = laad_feedback()
    fb["rpe"][datum] = max(1, min(10, int(rpe)))
    bewaar_feedback(fb)


@onder_slot
@onder_slot
def zet_ftp(cfg: dict, ftp: int, vandaag: date | None = None) -> str:
    """Nieuwe FTP in intervals.icu zetten. Alle trainingen staan in % FTP, dus het schema
    hoeft niet opnieuw; Zwift en je Wahoo rekenen met hun eigen FTP-instelling."""
    if not 80 <= int(ftp) <= 600:
        raise ValueError("FTP moet tussen 80 en 600 W liggen")
    ic = client(cfg)
    if not ic:
        raise ValueError("geen intervals.icu-sleutel ingesteld")
    ic.zet_ftp(int(ftp))
    status = laad_status()
    status["ftp_gezet"] = {"datum": (vandaag or date.today()).isoformat(), "van": status.get("ftp"), "naar": int(ftp)}
    status["ftp"] = int(ftp)
    _schrijf("status.json", status)
    return f"FTP in intervals.icu op {int(ftp)} W gezet."


@onder_slot
def zet_extra(datum: str, minuten: int | None, soort: str = "duur", omgeving: str = "auto",
              vandaag: date | None = None) -> str | None:
    """Extra training toevoegen (minuten) of weghalen (None). Geeft een foutmelding of None."""
    vandaag = vandaag or date.today()
    fb = laad_feedback()
    if minuten is None:
        fb["extra"].pop(datum, None)
    else:
        try:
            d = date.fromisoformat(datum)
        except ValueError:
            return "geen geldige datum"
        if not vandaag <= d <= vandaag + timedelta(days=HORIZON - 1):
            return f"kies een dag vanaf vandaag tot {HORIZON} dagen vooruit"
        if not 20 <= int(minuten) <= 360:
            return "duur tussen 20 en 360 minuten"
        bezet = next((s for s in laad_plan() if s["datum"] == datum and not s.get("handmatig")
                      and s["soort"] != "rust" and s["status"] not in ("afwezig",)), None)
        if bezet and datum not in fb["extra"]:
            return (f"op die dag staat al {bezet['naam']}; kies daar 'Andere training' of pas de duur aan")
        fb["extra"][datum] = {"minuten": int(minuten),
                              "soort": soort if soort in EXTRA_SOORTEN else "duur",
                              "omgeving": omgeving if omgeving in ("binnen", "buiten") else "auto"}
    grens = (vandaag - timedelta(days=FROZEN_DAGEN)).isoformat()
    fb["extra"] = {d: e for d, e in fb["extra"].items() if d >= grens}
    bewaar_feedback(fb)
    return None


@onder_slot
def zet_ruil(datum: str, keuze: str | None) -> None:
    """Andere training voor een dag: 'v:3' of 'e:id' (zelfde soort), 's:duur' of
    's:herstel' (lichter), of None voor terug naar automatisch."""
    fb = laad_feedback()
    if keuze and keuze != "auto":
        fb["ruil"][datum] = keuze
    else:
        fb["ruil"].pop(datum, None)
    vandaag = date.today().isoformat()
    fb["ruil"] = {d: k for d, k in fb["ruil"].items() if d >= vandaag}
    bewaar_feedback(fb)


def zet_readiness(datum: str, benen: int, energie: int) -> None:
    fb = laad_feedback()
    fb["readiness"][datum] = {"benen": max(1, min(5, int(benen))), "energie": max(1, min(5, int(energie)))}
    bewaar_feedback(fb)


@onder_slot
def zet_uitzondering(cfg: dict, datum: str, minuten: int | None) -> dict:
    cfg = copy.deepcopy(cfg)
    uitz = cfg.setdefault("uitzonderingen", {}) or {}
    if minuten is None:
        uitz.pop(datum, None)
    else:
        uitz[datum] = max(0, int(minuten))
    vandaag = date.today().isoformat()
    cfg["uitzonderingen"] = {d: m for d, m in uitz.items() if d >= vandaag}
    bewaar_instellingen(cfg)
    return cfg


def open_feedback(plan: list[dict], fb: dict, vandaag: date, dagen: int = 7) -> list[dict]:
    """Gereden trainingen van de afgelopen week zonder RPE (zoals JOINs 'Pending feedback')."""
    van = (vandaag - timedelta(days=dagen)).isoformat()
    return [s for s in plan if van <= s["datum"] < vandaag.isoformat() + "~"
            and s["status"] == "gedaan" and s["datum"] not in fb["rpe"]]
