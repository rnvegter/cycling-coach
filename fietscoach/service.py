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
import json
import os
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from . import adapt, planner, weather
from .intervals import PREFIX, Intervals, eftp_uit, naar_event

CONFIG = Path(os.environ.get("FIETSCOACH_CONFIG", "config.yaml"))
DATA = Path(os.environ.get("FIETSCOACH_DATA", "data"))
HORIZON = 14  # dagen vooruit: bijsturen en naar intervals.icu
INSTELBAAR = ("doel", "week", "voorkeuren", "weer", "uitzonderingen", "afwezig")
WEER_GELDIG_UUR = 3     # zo lang gebruiken we een opgehaald weerbericht bij invoer in het scherm
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
    start = start or date.fromisoformat(str(cfg["doel"]["startdatum"]))
    nieuw = planner.genereer(cfg, start)
    v = vandaag.isoformat()
    oud = laad_basis()
    basis = ([x for x in oud if x["datum"] < v] + [x for x in nieuw if x["datum"] >= v]) if oud else nieuw
    _schrijf("basis.json", basis)
    bijsturen(cfg, vandaag, ververs=False, weer_ophalen=False)
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
    for s in plan:
        if s["soort"] != "rust" and s["status"] == "gepland":
            s["omgeving"] = s.get("omgeving") or planner.standaard_omgeving(s, vk)
        planner.vul_in(s)
        sc = adapt.trainingsscore(s, ritten.get(s["datum"]))
        if sc:
            s["score"] = sc
    return plan, log


def starttijd(week: dict, datum: str) -> str:
    """Wanneer je op die dag vertrekt; standaard 09:30 in het weekend, 18:30 doordeweeks."""
    dag = planner.DAGEN[date.fromisoformat(datum).weekday()]
    return (week.get(dag) or {}).get("start") or ("09:30" if dag in ("za", "zo") else "18:30")


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
              verwachting=None, ververs: bool = True, weer_ophalen: bool | str = True) -> list[str]:
    """ververs=True (ochtendtimer, knop Bijsturen): ritten, wellness en weer vers ophalen.
    ververs=False (invoer in het scherm): alleen de caches gebruiken, dus direct klaar."""
    vandaag = vandaag or date.today()
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
                well = ic.wellness(vandaag - timedelta(days=28), vandaag)
                status["wellness"] = [{k: w.get(k) for k in ("id", "hrv", "restingHR")} for w in well]
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

    plan, extra = afleiden(basis, cfg, status, fb, verwachting, vandaag, laad_plan())
    log += extra
    status["bijgestuurd"] = datetime.now().strftime("%d-%m %H:%M")
    status["bijgestuurd_iso"] = datetime.now().isoformat(timespec="seconds")
    status["log"] = log
    _schrijf("plan.json", plan)
    _schrijf("status.json", status)
    bewaar_feedback(fb)
    return log


def sync(cfg: dict, vandaag: date | None = None, ic: Intervals | None = None) -> str:
    vandaag = vandaag or date.today()
    ic = ic or client(cfg)
    if not ic:
        return "Geen intervals.icu-sleutel ingesteld."
    tot = vandaag + timedelta(days=HORIZON)
    sessies = [s for s in laad_plan() if vandaag.isoformat() <= s["datum"] < tot.isoformat()
               and s["status"] == "gepland" and s["soort"] != "rust"]
    events = [naar_event(s) for s in sessies]
    if events:
        ic.upsert(events)
    # Dagen in de horizon zonder training: ons eigen event (als dat er staat) weg.
    gewenst = {e["external_id"] for e in events}
    weg_ids = [PREFIX + (vandaag + timedelta(days=i)).isoformat() for i in range(HORIZON)]
    weg = ic.verwijder_extern([e for e in weg_ids if e not in gewenst])
    with vergrendeld():
        status = laad_status()
        status["gesynct"] = datetime.now().strftime("%d-%m %H:%M")
        status["gesynct_iso"] = datetime.now().isoformat(timespec="seconds")
        status.pop("sync_fout", None)
        _schrijf("status.json", status)
    return f"{len(events)} trainingen naar intervals.icu gezet" + (f", {weg} oude verwijderd." if weg else ".")


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


# --- invoer vanuit het scherm ---------------------------------------------------

@onder_slot
def zet_rpe(datum: str, rpe: int) -> None:
    fb = laad_feedback()
    fb["rpe"][datum] = max(1, min(10, int(rpe)))
    bewaar_feedback(fb)


@onder_slot
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
