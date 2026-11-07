"""Web-app: uvicorn fietscoach.web:app --host 0.0.0.0 --port 8766"""
from __future__ import annotations

from datetime import date, timedelta
from itertools import groupby
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import planner, service, workouts

HIER = Path(__file__).parent
app = FastAPI(title="Fietscoach")
app.mount("/static", StaticFiles(directory=HIER / "static"), name="static")
templates = Jinja2Templates(directory=HIER / "templates")

DAGNAAM = {"ma": "Ma", "di": "Di", "wo": "Wo", "do": "Do", "vr": "Vr", "za": "Za", "zo": "Zo"}
MAAND = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
FOCUSNAAM = {"gemengd": "Gemengd", "sweetspot": "Sweetspot", "zone2": "Zone 2", "gepolariseerd": "Gepolariseerd"}


def vandaag() -> date:  # los, zodat tests en schermafbeeldingen een dag kunnen kiezen
    return date.today()


def _training(s: dict) -> workouts.Training | None:
    if s["soort"] == "rust":
        return None
    p = max(0.0, min(1.0, s.get("p", 0) + s.get("p_mod", 0)))
    return workouts.bouw(s["soort"], s["minuten"], p, s.get("fase", ""), s.get("variant", 0))


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
    klasse=lambda s: "t-" + workouts.SOORTKLASSE.get(s["soort"], "mild"),
    soortnaam=lambda s: workouts.SOORTNAAM.get(s["soort"], s["soort"]),
    profiel=profiel, datumlabel=datumlabel, focusnaam=FOCUSNAAM, dagnaam=DAGNAAM,
    zonelegenda=[("frozen", "Herstel"), ("cool", "Duur"), ("mild", "Tempo"), ("warm", "Sweetspot"),
                 ("hot", "Drempel"), ("baking", "VO2max")],
)


def _terug(pad: str, msg: str) -> RedirectResponse:
    return RedirectResponse(f"{pad}?msg={quote(msg)}", status_code=303)


def _context(request: Request, tab: str, msg: str | None) -> dict:
    try:
        cfg = service.laad_config()
    except FileNotFoundError:
        cfg = {"doel": {}, "week": {}}
    return {"request": request, "tab": tab, "msg": msg, "cfg": cfg, "status": service.laad_status(),
            "vandaag": vandaag().isoformat(), "plan": service.laad_plan()}


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
        rpe=fb["rpe"],
        uitzonderingen=sorted((ctx["cfg"].get("uitzonderingen") or {}).items()),
        min_datum=v.isoformat(), max_datum=(v + timedelta(days=13)).isoformat(),
    )
    return templates.TemplateResponse(request, "vandaag.html", ctx)


@app.get("/schema")
def scherm_schema(request: Request, msg: str | None = None):
    ctx = _context(request, "schema", msg)
    weken = [(wk, list(ss)) for wk, ss in groupby(ctx["plan"], key=lambda s: s["week"])]
    huidige = next((wk for wk, ss in weken if ss[-1]["datum"] >= ctx["vandaag"]), None)
    maxuren = max((sum(s.get("duur", 0) for s in ss) for _, ss in weken), default=1) or 1
    ctx.update(weken=weken, huidige=huidige, maxuren=maxuren, rpe=service.laad_feedback()["rpe"])
    return templates.TemplateResponse(request, "schema.html", ctx)


@app.get("/instellingen")
def scherm_instellingen(request: Request, msg: str | None = None):
    ctx = _context(request, "instellingen", msg)
    doel = ctx["cfg"].get("doel", {})
    blokken = list(doel.get("blokken") or [{"focus": doel.get("focus", "gemengd"), "weken": doel.get("weken", 12)}])
    blokken += [{"focus": "", "weken": ""}] * (3 - len(blokken))
    ctx.update(blokken=blokken[:3], dagen=planner.DAGEN, focussen=planner.FOCUSSEN)
    return templates.TemplateResponse(request, "instellingen.html", ctx)


@app.get("/bibliotheek")
def scherm_bibliotheek(request: Request, minuten: int = 60):
    from . import bibliotheek
    ctx = _context(request, "bibliotheek", None)
    minuten = max(45, min(120, minuten))
    groepen = [(soort, [t for _, _, t in rijen])
               for soort, rijen in groupby(bibliotheek.catalogus(minuten), key=lambda x: x[0])]
    ctx.update(groepen=groepen, minuten=minuten)
    return templates.TemplateResponse(request, "bibliotheek.html", ctx)


# --- acties -------------------------------------------------------------------

@app.post("/readiness")
async def readiness(request: Request):
    f = await request.form()
    service.zet_readiness(vandaag().isoformat(), int(f["benen"]), int(f["energie"]))
    return _terug("/", service.pas_toe())


@app.post("/rpe")
async def rpe(request: Request):
    f = await request.form()
    service.zet_rpe(str(f["datum"]), int(f["rpe"]))
    return _terug(str(f.get("terug") or "/"), "RPE opgeslagen. " + service.pas_toe())


@app.post("/uitzondering")
async def uitzondering(request: Request):
    f = await request.form()
    datum = str(f["datum"])
    weg = f.get("weg")
    minuten = None if weg else int(f.get("minuten") or 0)
    cfg = service.zet_uitzondering(service.laad_config(), datum, minuten)
    return _terug("/", service.pas_toe(cfg))


@app.post("/bijsturen")
def bijsturen():
    return _terug("/", service.pas_toe() or "Bijgestuurd, niets te melden.")


@app.post("/genereer")
def genereer():
    cfg = service.laad_config()
    try:
        plan = service.genereer(cfg)
    except ValueError as e:
        return _terug("/instellingen", f"Kon geen schema maken: {e}")
    return _terug("/schema", f"Nieuw schema ({len(plan)} dagen). " + service.pas_toe(cfg))


@app.post("/instellingen")
async def instellingen_opslaan(request: Request):
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
    cfg["week"] = {d: {"minuten": int(f.get(f"min_{d}") or 0), "buiten": f.get(f"buiten_{d}") == "1"}
                   for d in planner.DAGEN}
    cfg["voorkeuren"] = {
        "max_kwaliteit_per_week": int(f.get("max_kwaliteit") or 2),
        "intervallen_binnen": f.get("intervallen_binnen") == "1",
        "ftp_test": f.get("ftp_test") == "1",
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
    return _terug("/schema", f"Opgeslagen; schema vanaf vandaag opnieuw opgebouwd ({len(plan)} dagen). "
                  + service.pas_toe(cfg))


@app.get("/zwo/{datum}")
def zwo(datum: str):
    s = next((s for s in service.laad_plan() if s["datum"] == datum), None)
    t = _training(s) if s else None
    if not t:
        return Response("Geen training op deze dag.", status_code=404)
    naam = f"fietscoach-{datum}.zwo"
    return Response(workouts.zwo(t), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{naam}"'})


@app.get("/api/plan")
def api_plan():
    return service.laad_plan()
