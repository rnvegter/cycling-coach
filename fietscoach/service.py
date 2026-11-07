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
INSTELBAAR = ("doel", "week", "voorkeuren", "weer", "uitzonderingen")


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
    return _lees("plan.json", [])


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


# --- schema maken ---------------------------------------------------------------

@onder_slot
def genereer(cfg: dict, start: date | None = None, vandaag: date | None = None) -> list[dict]:
    """Nieuw schema. Wat al voorbij is blijft staan (met je ritten en scores);
    vanaf vandaag komt het nieuwe schema ervoor in de plaats."""
    vandaag = vandaag or date.today()
    start = start or date.fromisoformat(str(cfg["doel"]["startdatum"]))
    nieuw = planner.genereer(cfg, start)
    v = vandaag.isoformat()
    oud = laad_plan()
    plan = ([s for s in oud if s["datum"] < v] + [s for s in nieuw if s["datum"] >= v]) if oud else nieuw
    _schrijf("plan.json", plan)
    return plan


def _extra_dagen(plan: list[dict], uitz: dict, vandaag: date, week: dict, vk: dict) -> None:
    """Een dag die normaal vrij is, maar waarop je nu wél tijd hebt, krijgt een duurrit."""
    v = vandaag.isoformat()
    bestaand = {s["datum"] for s in plan}
    for s in [s for s in plan if s.get("extra") and s["status"] == "gepland"
              and int(uitz.get(s["datum"], 0)) < 30]:
        plan.remove(s)
    for d, m in uitz.items():
        if d < v or d in bestaand or int(m) < 30:
            continue
        dt = date.fromisoformat(d)
        maandag = (dt - timedelta(days=dt.weekday())).isoformat()
        buur = next((s for s in plan if maandag <= s["datum"] <= (dt + timedelta(days=6 - dt.weekday())).isoformat()), None)
        if not buur:
            continue
        dag = planner.DAGEN[dt.weekday()]
        minuten = int(m) if not buur["herstelweek"] else planner.round5(int(m) * 0.65)
        s = {"datum": d, "dag": dag, "week": buur["week"], "fase": buur["fase"], "focus": buur.get("focus"),
             "herstelweek": buur["herstelweek"], "rol": "extra", "p": buur["p"], "extra": True,
             "variant": buur.get("variant", 0) + 1,
             "basis_soort": "duur", "basis_minuten": max(30, minuten), "soort": "duur",
             "minuten": max(30, minuten), "buiten_toegestaan": bool((week.get(dag) or {}).get("buiten", True)),
             "status": "gepland", "notities": []}
        s["omgeving"] = planner.standaard_omgeving(s, vk)
        plan.append(planner.vul_in(s))
    plan.sort(key=lambda s: s["datum"])


# --- bijsturen ----------------------------------------------------------------

@onder_slot
def bijsturen(cfg: dict, vandaag: date | None = None, ic: Intervals | None = None,
              verwachting: dict | None = None) -> list[str]:
    vandaag = vandaag or date.today()
    plan, status, fb = laad_plan(), laad_status(), laad_feedback()
    if not plan:
        return ["Nog geen schema. Maak eerst een schema."]
    vk = cfg.get("voorkeuren", {}) or {}
    week = cfg["week"]
    uitz = {str(k): int(v) for k, v in (cfg.get("uitzonderingen") or {}).items()}
    log: list[str] = []
    ic = ic or client(cfg)

    ritten, vorm = None, None
    if ic:
        try:
            acts = ic.activiteiten(vandaag - timedelta(days=28), vandaag)
            ritten = adapt.ritten_per_dag(acts)
            well = [w for w in ic.wellness(vandaag - timedelta(days=2), vandaag) if w.get("ctl") is not None]
            if well:
                laatste = well[-1]
                status.update(ctl=round(laatste["ctl"]), atl=round(laatste["atl"]))
                vorm = laatste["ctl"] - laatste["atl"]
                status["vorm"] = round(vorm)
                if eftp_uit(laatste):
                    status["eftp"] = eftp_uit(laatste)
            status["ftp"] = ic.ftp()
        except Exception as e:  # noqa: BLE001
            log.append(f"intervals.icu niet bereikbaar: {e}")
    else:
        log.append("Geen intervals.icu-sleutel ingesteld: alleen weer en je eigen invoer toegepast.")

    if ritten is not None:
        status["ritten"] = ritten
        log += adapt.markeer_en_herplan(plan, set(ritten), week, vandaag)
        for d, r in ritten.items():  # RPE uit intervals.icu overnemen als je hem daar al gaf
            if r.get("rpe") and d not in fb["rpe"]:
                fb["rpe"][d] = int(r["rpe"])
    ritten = status.get("ritten", {})
    for s in plan:
        sc = adapt.trainingsscore(s, ritten.get(s["datum"]))
        if sc:
            s["score"] = sc

    _extra_dagen(plan, uitz, vandaag, week, vk)
    tot = (vandaag + timedelta(days=HORIZON - 1)).isoformat()
    venster = adapt.reset_venster(plan, vandaag.isoformat(), tot, vk)
    for s in venster:
        s.pop("p_mod", None)
    week_kort = [s for s in venster if s["datum"] <= (vandaag + timedelta(days=6)).isoformat()]

    log += adapt.pas_uitzonderingen_toe(venster, uitz, week)
    log += adapt.pas_ongepland_toe(plan, venster, ritten, vandaag, week)
    log += adapt.pas_vorm_toe(week_kort, vorm)
    log += adapt.pas_readiness_toe(venster, fb["readiness"].get(vandaag.isoformat()), vandaag)

    niv = adapt.niveaus(plan, fb["rpe"])
    status["niveaus"] = {k: v[0] for k, v in niv.items()}
    in_venster = {id(s) for s in venster}
    for s in plan:
        if s["datum"] >= vandaag.isoformat() and s["status"] == "gepland":
            off, uitleg = niv.get(s["soort"], (0.0, ""))
            if id(s) in in_venster:
                s["p_mod"] = s.get("p_mod", 0) + off
                if uitleg:
                    s["notities"].append(uitleg)
            else:
                s["p_mod"] = off

    if verwachting is None:
        try:
            loc = cfg["locatie"]
            v = weather.verwachting(loc["lat"], loc["lon"])
            verwachting = lambda d, m: v.venster(d, starttijd(week, d), m)  # noqa: E731
        except Exception as e:  # noqa: BLE001
            log.append(f"Weerbericht niet beschikbaar: {e}")
            verwachting = {}
    log += adapt.pas_weer_toe([s for s in venster if s["soort"] != "rust"], verwachting, week, vk,
                              cfg.get("weer", {}) or {})

    for s in plan:
        if s["datum"] >= vandaag.isoformat() and s["status"] == "gepland":
            planner.vul_in(s)
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


def pas_toe(cfg: dict | None = None) -> str:
    """Na elke wijziging: bijsturen en, als dat kan, meteen synchroniseren."""
    cfg = cfg or laad_config()
    log = bijsturen(cfg)
    if client(cfg):
        try:
            log.append(sync(cfg))
        except Exception as e:  # noqa: BLE001
            log.append(f"Synchroniseren mislukt: {e}")
            with vergrendeld():
                st = laad_status()
                st["sync_fout"] = f"{datetime.now().isoformat(timespec='seconds')} {e}"
                _schrijf("status.json", st)
    return " ".join(log)


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
