"""Web-app: uvicorn fietscoach.web:app --host 0.0.0.0 --port 8766"""
from __future__ import annotations

import re
from datetime import date, timedelta
from itertools import groupby
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import grafiek, inzicht, melding, planner, service, workouts

HIER = Path(__file__).parent
app = FastAPI(title="Fietscoach")


@app.middleware("http")
async def zelfde_herkomst(request: Request, call_next):
    """Formulieren alleen vanaf deze site zelf. Achter Authelia is de browser
    ingelogd; zonder deze controle zou een andere site via jouw browser acties
    kunnen uitvoeren (CSRF). Browsers sturen bij een POST altijd Origin mee;
    ontbreekt die en ook Referer, dan is het geen browser en laten we het door."""
    if request.method == "POST":
        from urllib.parse import urlsplit
        bron = request.headers.get("origin") or request.headers.get("referer")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if bron and urlsplit(bron).netloc != host:
            return Response("Verzoek van een andere site geweigerd.", status_code=403)
    return await call_next(request)
app.mount("/static", StaticFiles(directory=HIER / "static"), name="static")
templates = Jinja2Templates(directory=HIER / "templates")

DAGNAAM = {"ma": "Ma", "di": "Di", "wo": "Wo", "do": "Do", "vr": "Vr", "za": "Za", "zo": "Zo"}
MAAND = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
FOCUSNAAM = planner.FOCUSNAAM


def vandaag() -> date:  # los, zodat tests en schermafbeeldingen een dag kunnen kiezen
    return date.today()


def _training(s: dict) -> workouts.Training | None:
    return planner.training_voor(s)  # zelfde keuze als het schema en de sync


def profiel(s: dict, mini: bool = False) -> Markup:
    t = _training(s)
    if not t:
        return Markup("")
    svg = workouts.profiel_svg(t, 22 if mini else 64)
    if mini:
        svg = svg.replace('class="fc-profiel"', 'class="fc-profiel fc-profiel--mini"')
    return Markup(svg)


def datumlabel(d: str, lang: bool = False) -> str:
    dt = date.fromisoformat(d)
    dag = DAGNAAM[planner.DAGEN[dt.weekday()]]
    return f"{dag} {dt.day} {MAAND[dt.month - 1]}" if lang else f"{dag} {dt.day:02d}-{dt.month:02d}"


templates.env.globals.update(
    profiel_t=lambda t: Markup(workouts.profiel_svg(t)),
    zwaarte=workouts.zwaarte,
    klasse=lambda s: "t-" + workouts.SOORTKLASSE.get(s["soort"], "mild"),
    soortnaam=lambda s: workouts.SOORTNAAM.get(s["soort"], s["soort"]),
    profiel=profiel, datumlabel=datumlabel, focusnaam=FOCUSNAAM, dagnaam=DAGNAAM,
    zonelegenda=[("frozen", "Herstel"), ("cool", "Duur"), ("mild", "Tempo"), ("warm", "Sweetspot"),
                 ("hot", "Drempel"), ("baking", "VO2max")],
)


def _tijd(waarde) -> str | None:
    """HH:MM uit een formulierveld, of None als het leeg of onzin is."""
    try:
        h, m = str(waarde or "").split(":")[:2]
        return f"{int(h):02d}:{int(m):02d}" if 0 <= int(h) < 24 and 0 <= int(m) < 60 else None
    except ValueError:
        return None


def ruilopties(s: dict) -> list[tuple[str, str]]:
    """Andere trainingen voor deze dag: zelfde soort (met zwaarte), en lichter."""
    if s["soort"] == "rust":
        return []
    p = max(0.0, min(1.0, s.get("p", 0) + s.get("p_mod", 0)))
    uit = []
    for k, t in planner.opties(s["soort"], s["minuten"], p, s.get("fase", "")):
        z = workouts.zwaarte(t)["score"]
        uit.append((k, f"{t.naam} · zwaarte {z}{' · eigen' if k.startswith('e:') else ''}"))
    if s["soort"] not in ("duur", "herstel"):
        uit.append(("s:duur", "Lichter: duurrit"))
    if s["soort"] != "herstel":
        uit.append(("s:herstel", "Lichter: herstelrit"))
    return uit


templates.env.globals["ruilopties"] = ruilopties


def _hrv(status: dict, v: date) -> dict:
    from .adapt import objectieve_readiness
    score, uitleg = objectieve_readiness(status.get("wellness") or [], v)
    return {"score": score, "uitleg": uitleg}


def _terug(pad: str, msg: str) -> RedirectResponse:
    anker = "#eigen" if pad == "/bibliotheek" else ""
    return RedirectResponse(f"{pad}?msg={quote(msg)}{anker}", status_code=303)


def _context(request: Request, tab: str, msg: str | None) -> dict:
    try:
        cfg = service.laad_config()
    except FileNotFoundError:
        cfg = {"doel": {}, "week": {}}
    return {"request": request, "tab": tab, "msg": msg, "cfg": cfg, "status": service.laad_status(),
            "vandaag": vandaag().isoformat(), "plan": service.laad_plan(), "waarom": service.waarom_per_dag()}


@app.get("/")
def scherm_vandaag(request: Request, msg: str | None = None):
    ctx = _context(request, "vandaag", msg)
    plan, v = ctx["plan"], vandaag()
    fb = service.laad_feedback()
    maandag = (v - timedelta(days=v.weekday())).isoformat()
    zondag = (v + timedelta(days=6 - v.weekday())).isoformat()
    vandaag_s = next((s for s in plan if s["datum"] == v.isoformat()), None)
    volgende = next((s for s in plan if s["datum"] > v.isoformat() and s["soort"] != "rust"
                     and s["status"] == "gepland"), None)
    ctx.update(
        vandaag_s=vandaag_s, volgende=volgende,
        deze_week=[s for s in plan if maandag <= s["datum"] <= zondag],
        open_fb=service.open_feedback(plan, fb, v),
        readiness=fb["readiness"].get(v.isoformat()),
        hrv=_hrv(ctx["status"], v),
        ftp_test_gedaan=next((s for s in reversed(plan) if s["soort"] == "ftp_test" and s["status"] == "gedaan"
                              and s["datum"] >= (v - timedelta(days=10)).isoformat()), None),
        rpe=fb["rpe"],
        uitzonderingen=sorted((ctx["cfg"].get("uitzonderingen") or {}).items()),
        uitz=ctx["cfg"].get("uitzonderingen") or {},
        min_datum=v.isoformat(), max_datum=(v + timedelta(days=13)).isoformat(),
        ftp_hint=inzicht.ftp_hint(ctx["status"]),
        ftp_gezet=_recent(ctx["status"].get("ftp_gezet"), v, 3),
        terugblik=service.weekoverzicht(v) if v.weekday() <= 1 else None,
    )
    return templates.TemplateResponse(request, "vandaag.html", ctx)


def _recent(x: dict | None, v: date, dagen: int) -> dict | None:
    if x and x.get("datum") and x["datum"] >= (v - timedelta(days=dagen)).isoformat():
        return x
    return None


@app.get("/schema")
def scherm_schema(request: Request, msg: str | None = None):
    ctx = _context(request, "schema", msg)
    weken = [(wk, list(ss)) for wk, ss in groupby(ctx["plan"], key=lambda s: s["week"])]
    huidige = next((wk for wk, ss in weken if ss[-1]["datum"] >= ctx["vandaag"]), None)
    maxuren = max((sum(s.get("duur", 0) for s in ss) for _, ss in weken), default=1) or 1
    doel = ctx["cfg"].get("doel") or {}
    evenement = str(doel.get("evenement") or "") if doel.get("type") == "tocht" else None
    reeks = inzicht.fitheidsverloop(ctx["status"], ctx["plan"], vandaag())
    ctx.update(weken=weken, huidige=huidige, maxuren=maxuren, rpe=service.laad_feedback()["rpe"],
               grafiek=grafiek.fitheid(reeks, vandaag(), evenement or None))
    return templates.TemplateResponse(request, "schema.html", ctx)


@app.get("/instellingen")
def scherm_instellingen(request: Request, msg: str | None = None):
    ctx = _context(request, "instellingen", msg)
    doel = ctx["cfg"].get("doel", {})
    blokken = list(doel.get("blokken") or [{"focus": doel.get("focus", "gemengd"), "weken": doel.get("weken", 12)}])
    blokken += [{"focus": "", "weken": ""}] * (3 - len(blokken))
    ctx.update(blokken=blokken[:3], dagen=planner.DAGEN, focussen=planner.FOCUSSEN,
               kanalen=melding.kanalen(ctx["cfg"]), berichten_aan=service.berichten_aan(ctx["cfg"]))
    return templates.TemplateResponse(request, "instellingen.html", ctx)


@app.get("/bibliotheek")
def scherm_bibliotheek(request: Request, minuten: int = 60, msg: str | None = None):
    from . import bibliotheek, eigen
    ctx = _context(request, "bibliotheek", None)  # meldingen horen bij het blok onderaan
    ctx["eigen_msg"] = msg
    ctx["eigen"] = eigen.alle()
    ctx["eigen_soorten"] = eigen.SOORTEN
    minuten = max(45, min(120, minuten))
    groepen = [(soort, [t for _, _, t in rijen])
               for soort, rijen in groupby(bibliotheek.catalogus(minuten), key=lambda x: x[0])]
    # Eigen workouts ook bij hun soort, achter de ingebouwde vormen.
    per_soort = {}
    for w in ctx["eigen"]:
        per_soort.setdefault(w.soort, []).append(w.training)
    groepen = [(s, ts + per_soort.pop(s, [])) for s, ts in groepen] + sorted(per_soort.items())
    ctx.update(groepen=groepen, minuten=minuten)
    return templates.TemplateResponse(request, "bibliotheek.html", ctx)


# --- acties ---

@app.post("/eigen")
async def eigen_toevoegen(request: Request, achtergrond: BackgroundTasks):
    """Eigen workouts in bulk: losse .zwo-bestanden, een hele map, of .zip-bestanden."""
    from . import eigen
    f = await request.form()
    bestanden = []
    for b in f.getlist("bestanden"):
        if hasattr(b, "read") and b.filename:
            laag = b.filename.lower()
            if laag.endswith(".zwo"):
                bestanden.append((b.filename, await b.read(eigen.MAX_BYTES + 1)))
            elif laag.endswith(".zip"):
                bestanden.append((b.filename, await b.read(eigen.MAX_ZIP_TOTAAL)))
    if not bestanden:
        return _terug("/bibliotheek", "Niet opgeslagen: geen .zwo- of .zip-bestanden gekozen.")
    gelukt, mislukt = eigen.importeer(bestanden)
    if gelukt:
        _snel(achtergrond)
    tekst = f"{len(gelukt)} workout(s) toegevoegd."
    if len(gelukt) <= 5 and gelukt:
        tekst = "Toegevoegd: " + "; ".join(gelukt) + "."
    if mislukt:
        tekst += f" ✗ {len(mislukt)} niet: " + "; ".join(mislukt[:5]) + (" …" if len(mislukt) > 5 else "")
    return _terug("/bibliotheek", tekst)


@app.post("/eigen/soort")
async def eigen_soort(request: Request, achtergrond: BackgroundTasks):
    """Soort van één eigen workout zelf kiezen, of terug naar automatisch."""
    from . import eigen
    f = await request.form()
    soort = str(f.get("soort") or "auto")
    if not eigen.zet_soort(str(f.get("id") or ""), None if soort == "auto" else soort):
        return _terug("/bibliotheek", "Niet gevonden ✗")
    _snel(achtergrond)
    w = next(w for w in eigen.alle() if w.id == f.get("id"))
    return _terug("/bibliotheek", f"{w.naam}: {w.soort}" + (" (zelf gekozen)." if w.handmatig else " (automatisch)."))


@app.post("/eigen/automatisch")
async def eigen_automatisch(achtergrond: BackgroundTasks):
    """De knop: alle eigen workouts opnieuw automatisch indelen."""
    from . import eigen
    telling = eigen.alles_automatisch()
    _snel(achtergrond)
    if not telling:
        return _terug("/bibliotheek", "Nog geen eigen workouts.")
    deel = ", ".join(f"{n} {s}" for s, n in sorted(telling.items(), key=lambda x: -x[1]))
    return _terug("/bibliotheek", f"Automatisch ingedeeld: {deel}.")


@app.post("/eigen/alle-weg")
async def eigen_alle_weg(achtergrond: BackgroundTasks):
    from . import eigen
    n = eigen.verwijder_alle()
    _snel(achtergrond)
    return _terug("/bibliotheek", f"{n} eigen workout(s) verwijderd.")


@app.post("/eigen/weg")
async def eigen_weg(request: Request, achtergrond: BackgroundTasks):
    from . import eigen
    f = await request.form()
    if eigen.verwijder(str(f.get("id") or "")):
        _snel(achtergrond)
        return _terug("/bibliotheek", "Workout verwijderd.")
    return _terug("/bibliotheek", "Niet gevonden ✗")


# --- overige acties ------------------------------------------------------------

def _snel(achtergrond: BackgroundTasks) -> str:
    """Direct lokaal bijsturen met de caches; de sync naar intervals.icu daarna op de achtergrond."""
    log = service.pas_toe_snel()
    achtergrond.add_task(service.sync_veilig)
    return log


@app.post("/readiness")
async def readiness(request: Request, achtergrond: BackgroundTasks):
    f = await request.form()
    service.zet_readiness(vandaag().isoformat(), int(f["benen"]), int(f["energie"]))
    return _terug("/", _snel(achtergrond) or "Readiness opgeslagen.")


@app.post("/rpe")
async def rpe(request: Request, achtergrond: BackgroundTasks):
    f = await request.form()
    service.zet_rpe(str(f["datum"]), int(f["rpe"]))
    terug = str(f.get("terug") or "/")
    return _terug(terug if terug.startswith("/") else "/", ("RPE opgeslagen. " + _snel(achtergrond)).strip())


@app.post("/uitzondering")
async def uitzondering(request: Request, achtergrond: BackgroundTasks):
    f = await request.form()
    datum = str(f["datum"])
    weg = f.get("weg")
    minuten = None if weg else int(f.get("minuten") or 0)
    service.zet_uitzondering(service.laad_config(), datum, minuten)
    return _terug("/", _snel(achtergrond) or "Aangepast.")


@app.post("/ruil")
async def ruil(request: Request, achtergrond: BackgroundTasks):
    f = await request.form()
    keuze = str(f.get("keuze") or "auto")
    if not (keuze == "auto" or re.fullmatch(r"(v:\d+|e:[A-Za-z0-9._-]+|s:(duur|herstel))", keuze)):
        return _terug("/", "Onbekende keuze ✗")
    service.zet_ruil(str(f.get("datum") or ""), keuze)
    return _terug("/", _snel(achtergrond) or "Training gewijzigd.")


@app.post("/terug-naar-plan")
async def terug_naar_plan(request: Request, achtergrond: BackgroundTasks):
    f = await request.form()
    if service.terug_naar_plan(str(f.get("datum") or "")):
        service.pas_toe_snel()
        achtergrond.add_task(service.sync_veilig)
        return _terug(str(f.get("terug") or "/") if str(f.get("terug") or "/").startswith("/") else "/",
                      "Terug naar plan; de app zet de training weer in intervals.icu.")
    return _terug("/", "Niets terug te zetten.")


@app.post("/bijsturen")
def bijsturen():
    """De volledige ronde: ritten, wellness en weer vers ophalen, bijsturen en syncen."""
    return _terug("/", service.pas_toe() or "Bijgestuurd, niets te melden.")


@app.post("/genereer")
def genereer(achtergrond: BackgroundTasks):
    cfg = service.laad_config()
    try:
        plan = service.genereer(cfg)
    except ValueError as e:
        return _terug("/instellingen", f"Kon geen schema maken: {e}")
    achtergrond.add_task(service.sync_veilig)
    return _terug("/schema", f"Nieuw schema ({len(plan)} dagen); wordt naar intervals.icu gezet.")


@app.post("/instellingen")
async def instellingen_opslaan(request: Request, achtergrond: BackgroundTasks):
    f = await request.form()
    cfg = service.laad_config()
    blokken = []
    for i in range(3):
        focus, weken = f.get(f"focus{i}"), f.get(f"weken{i}")
        if focus and weken and int(weken) > 0:
            blokken.append({"focus": str(focus), "weken": int(weken)})
    if not blokken:
        return _terug("/instellingen", "Geef minstens één blok met een focus en een aantal weken.")
    cfg["doel"] = {
        "type": str(f["type"]), "startdatum": str(f["startdatum"]),
        "weken": sum(b["weken"] for b in blokken), "blokken": blokken,
        "evenement": str(f.get("evenement") or "") or None,
    }
    cfg["week"] = {d: {"minuten": int(f.get(f"min_{d}") or 0), "buiten": f.get(f"buiten_{d}") == "1",
                       "start": _tijd(f.get(f"start_{d}"))}
                   for d in planner.DAGEN}
    cfg["voorkeuren"] = {
        "max_kwaliteit_per_week": int(f.get("max_kwaliteit") or 2),
        "intervallen_binnen": f.get("intervallen_binnen") == "1",
        "ftp_test": int(f.get("ftp_test_weken") or 8) > 0,
        "ftp_test_weken": int(f.get("ftp_test_weken") or 8),
        "ftp_test_vorm": "20min" if f.get("ftp_test_vorm") == "20min" else "ramp",
        "variatie": f.get("variatie") == "1",
        "max_binnen_minuten": int(f.get("max_binnen") or 120),
    }
    cfg["weer"] = {
        "max_neerslag_mm": float(f.get("max_neerslag_mm") or 2),
        "max_neerslagkans": int(f.get("max_neerslagkans") or 60),
        "max_wind_kmh": int(f.get("max_wind_kmh") or 35),
        "min_temp": float(f.get("min_temp") or 0),
    }
    try:
        planner.genereer(cfg, date.fromisoformat(cfg["doel"]["startdatum"]))  # eerst proberen
    except ValueError as e:
        return _terug("/instellingen", f"Niet opgeslagen: {e}")
    service.bewaar_instellingen(cfg)
    plan = service.genereer(cfg)
    achtergrond.add_task(service.sync_veilig)
    return _terug("/schema", f"Opgeslagen; schema vanaf vandaag opnieuw opgebouwd ({len(plan)} dagen).")


@app.post("/afwezig")
async def afwezig(request: Request, achtergrond: BackgroundTasks):
    f = await request.form()
    cfg = service.laad_config()
    lijst = list(cfg.get("afwezig") or [])
    if f.get("weg") is not None:
        i = int(f["weg"])
        lijst = [p for k, p in enumerate(lijst) if k != i]
    else:
        van, tot = str(f.get("van") or ""), str(f.get("tot") or "")
        try:
            date.fromisoformat(van), date.fromisoformat(tot)
        except ValueError:
            return _terug("/instellingen", "Niet opgeslagen: geef een begin- en einddatum.")
        if tot < van:
            van, tot = tot, van
        lijst.append({"van": van, "tot": tot, "reden": str(f.get("reden") or "Afwezig")[:40]})
    cfg["afwezig"] = sorted((p for p in lijst if p["tot"] >= vandaag().isoformat()), key=lambda p: p["van"])
    service.bewaar_instellingen(cfg)
    return _terug("/instellingen", _snel(achtergrond) or "Afwezigheid bijgewerkt.")


@app.get("/zwo/{datum}")
def zwo(datum: str):
    s = next((s for s in service.laad_plan() if s["datum"] == datum), None)
    t = _training(s) if s else None
    if not t:
        return Response("Geen training op deze dag.", status_code=404)
    naam = f"fietscoach-{datum}.zwo"
    return Response(workouts.zwo(t), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{naam}"'})


@app.post("/ftp")
async def ftp(request: Request):
    f = await request.form()
    try:
        tekst = service.zet_ftp(service.laad_config(), int(str(f.get("ftp") or "0")))
    except ValueError as e:
        return _terug("/", f"FTP niet aangepast: {e}")
    except Exception as e:  # noqa: BLE001
        return _terug("/", f"FTP niet aangepast: intervals.icu gaf een fout ({e.__class__.__name__}).")
    return _terug("/", tekst)


@app.post("/berichten")
async def berichten(request: Request):
    f = await request.form()
    cfg = service.laad_config()
    cfg["berichten_aan"] = {"ochtend": f.get("ochtend") == "1", "week": f.get("week") == "1"}
    service.bewaar_instellingen(cfg)
    if f.get("test") is not None:
        uit = service.ochtendbericht(cfg, vandaag(), altijd=True)
        return _terug("/instellingen", "Testbericht: " + uit)
    return _terug("/instellingen", "Berichten opgeslagen.")


@app.post("/verbinding")
def verbinding(request: Request):
    from .intervals import verbindingstest
    try:
        ic = service.client(service.laad_config())
        if not ic:
            return _terug("/instellingen", "Niet getest: geen API-sleutel in /etc/fietscoach/config.yaml.")
        regels = verbindingstest(ic)
    except Exception as e:  # noqa: BLE001
        regels = [(False, f"Kon geen verbinding opzetten: {e.__class__.__name__}")]
    tekst = " · ".join(("✓ " if ok else "✗ ") + r for ok, r in regels)
    return _terug("/instellingen", ("Verbinding in orde: " if all(ok for ok, _ in regels) else "Verbinding mislukt: ") + tekst)


@app.get("/sw.js")
def service_worker():
    """Vanaf de root geserveerd, zodat hij voor de hele app geldt."""
    return Response((HIER / "static" / "sw.js").read_bytes(), media_type="text/javascript",
                    headers={"Cache-Control": "no-cache"})


@app.get("/ready")
def ready():
    """Draait de app en kan hij zijn gegevens lezen? Voor het updatescript; los van intervals.icu."""
    try:
        service.migreer()
        service.laad_config()
        service.laad_plan()
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "fout": str(e)}, status_code=503)
    return {"ok": True}


@app.get("/health")
def health():
    """Voor Uptime Kuma: 200 als de laatste sync recent en foutloos is, anders 503."""
    ok, info = service.gezondheid()
    return JSONResponse({"ok": ok, **info}, status_code=200 if ok else 503)


@app.get("/api/plan")
def api_plan():
    return service.laad_plan()
