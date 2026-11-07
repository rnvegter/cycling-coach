"""Geometrie voor de fitheidsgrafiek. De lijnen komen in een SVG die meeschaalt
(preserveAspectRatio=none, lijndikte vast); tekst staat er in HTML overheen, zodat
letters op telefoon en computer even groot blijven. Alles in procenten."""
from __future__ import annotations

import math
from datetime import date

MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def _stap(bereik: float) -> int:
    for s in (5, 10, 20, 25, 50, 100):
        if bereik / s <= 5:
            return s
    return 200


def _pad(punten: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in punten)


def fitheid(reeks: list[dict], vandaag: date, evenement: str | None = None) -> dict | None:
    """Bovenste paneel: fitheid en vermoeidheid. Onderste paneel: vorm (eigen as).
    Gemeten deel doorgetrokken, voorspeld deel gestippeld."""
    if len(reeks) < 2:
        return None
    n = len(reeks)
    x = [i / (n - 1) * 100 for i in range(n)]

    hoog = max(max(r["fit"], r["moe"]) for r in reeks)
    stap = _stap(max(hoog, 10))
    top = max(stap, math.ceil(hoog / stap) * stap)
    y = lambda v: 100 - v / top * 100  # noqa: E731

    vmin = min(min(r["vorm"] for r in reeks), -10)
    vmax = max(max(r["vorm"] for r in reeks), 10)
    vstap = _stap(vmax - vmin)
    vmin, vmax = math.floor(vmin / vstap) * vstap, math.ceil(vmax / vstap) * vstap
    yv = lambda v: (vmax - v) / (vmax - vmin) * 100  # noqa: E731

    # Laatste gemeten punt: daar sluit de stippellijn aan.
    k = max((i for i, r in enumerate(reeks) if not r["voorspeld"]), default=0)

    def lijn(veld, schaal):
        p = [(x[i], schaal(r[veld])) for i, r in enumerate(reeks)]
        return {"gemeten": _pad(p[:k + 1]), "voorspeld": _pad(p[k:]) if k < n - 1 else ""}

    datums = [r["datum"] for r in reeks]
    v = vandaag.isoformat()
    vi = next((i for i, d in enumerate(datums) if d >= v), None)

    # Maandlabels op de 1e, plus een streepje per week (maandag) is te druk: alleen maanden.
    xlabels = []
    for i, d in enumerate(datums):
        dt = date.fromisoformat(d)
        if dt.day == 1 or i == 0:
            if i == 0 and dt.day > 24:
                continue
            xlabels.append({"x": x[i], "tekst": MAANDEN[dt.month - 1]})

    ev = None
    if evenement and datums[0] <= evenement <= datums[-1]:
        ev = x[datums.index(evenement)]
    laatste = reeks[k]
    eind = reeks[-1]
    return {
        "fit": lijn("fit", y), "moe": lijn("moe", y), "vorm": lijn("vorm", yv),
        "nul": yv(0),
        "yticks": [{"y": y(t), "tekst": t} for t in range(0, top + 1, stap)],
        "vticks": [{"y": yv(t), "tekst": f"{t:+d}" if t else "0"} for t in range(vmin, vmax + 1, vstap)],
        "xlabels": xlabels,
        "vandaag": x[vi] if vi is not None else None,
        "evenement": ev,
        "nu": {"fit": laatste["fit"], "moe": laatste["moe"], "vorm": laatste["vorm"]},
        "eind": {"fit": eind["fit"], "vorm": eind["vorm"], "datum": eind["datum"], "y_fit": y(eind["fit"]),
                 "y_moe": y(eind["moe"])},
        "data": [[r["datum"], r["fit"], r["moe"], r["vorm"], r["tss"], int(r["voorspeld"])] for r in reeks],
    }
