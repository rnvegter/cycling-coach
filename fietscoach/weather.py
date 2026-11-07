"""Weersverwachting via Open-Meteo (gratis, geen sleutel), per rit in plaats van per dag.

Een dagtotaal zegt weinig: regen om 22:00 of nachtvorst om 06:00 hoeft je rit
om 09:30 niet te raken. Daarom halen we de uurverwachting op en vatten die samen
over het tijdvak waarin je rijdt (starttijd + duur). Zonder uurdata valt het
terug op de dagwaarden.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import httpx

URL = "https://api.open-meteo.com/v1/forecast"


class Verwachting:
    def __init__(self, dag: dict[str, dict], uur: dict[str, dict] | None = None):
        self.dag = dag            # "2026-11-10" -> samenvatting van het etmaal
        self.uur = uur or {}      # "2026-11-10T09:00" -> waarden van dat uur

    def venster(self, datum: str, start: str, minuten: int) -> dict | None:
        """Samenvatting over [start, start+minuten). Telt elk uur dat de rit raakt."""
        try:
            t0 = datetime.fromisoformat(f"{datum}T{start}")
        except ValueError:
            return self.dag.get(datum)
        t1 = t0 + timedelta(minutes=max(minuten, 1))
        uren, t = [], t0.replace(minute=0)
        while t < t1:
            u = self.uur.get(t.strftime("%Y-%m-%dT%H:00"))
            if u:
                uren.append(u)
            t += timedelta(hours=1)
        if not uren:
            return self.dag.get(datum)
        return {
            "temp_min": min(u["temp"] for u in uren),
            "temp_max": max(u["temp"] for u in uren),
            "neerslag_mm": round(sum(u["neerslag"] for u in uren), 1),
            "neerslagkans": max(u["kans"] for u in uren),
            "wind_kmh": max(u["wind"] for u in uren),
            "venster": f"{t0:%H:%M}–{t1:%H:%M}",
        }


def verwachting(lat: float, lon: float, dagen: int = 8) -> Verwachting:
    params = {
        "latitude": lat, "longitude": lon, "timezone": "Europe/Amsterdam", "forecast_days": dagen,
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum,"
                 "precipitation_probability_max,wind_speed_10m_max",
        "hourly": "temperature_2m,precipitation,precipitation_probability,wind_speed_10m",
    }
    r = httpx.get(URL, params=params, timeout=20)
    r.raise_for_status()
    j = r.json()
    d = j["daily"]
    dag = {}
    for i, t in enumerate(d["time"]):
        dag[t] = {
            "temp_min": d["temperature_2m_min"][i], "temp_max": d["temperature_2m_max"][i],
            "neerslag_mm": d["precipitation_sum"][i] or 0.0,
            "neerslagkans": d["precipitation_probability_max"][i] or 0,
            "wind_kmh": d["wind_speed_10m_max"][i] or 0.0,
        }
    uur = {}
    h = j.get("hourly") or {}
    for i, t in enumerate(h.get("time", [])):
        if h["temperature_2m"][i] is None:
            continue
        uur[t] = {"temp": h["temperature_2m"][i], "neerslag": h["precipitation"][i] or 0.0,
                  "kans": h["precipitation_probability"][i] or 0, "wind": h["wind_speed_10m"][i] or 0.0}
    return Verwachting(dag, uur)
