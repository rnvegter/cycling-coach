"""Weersverwachting per dag via Open-Meteo (gratis, geen API-sleutel)."""
from __future__ import annotations

import httpx

URL = "https://api.open-meteo.com/v1/forecast"


def verwachting(lat: float, lon: float, dagen: int = 8) -> dict[str, dict]:
    params = {
        "latitude": lat, "longitude": lon, "timezone": "Europe/Amsterdam",
        "forecast_days": dagen,
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum,"
                 "precipitation_probability_max,wind_speed_10m_max",
    }
    r = httpx.get(URL, params=params, timeout=20)
    r.raise_for_status()
    d = r.json()["daily"]
    uit = {}
    for i, dag in enumerate(d["time"]):
        uit[dag] = {
            "temp_min": d["temperature_2m_min"][i],
            "temp_max": d["temperature_2m_max"][i],
            "neerslag_mm": d["precipitation_sum"][i] or 0.0,
            "neerslagkans": d["precipitation_probability_max"][i] or 0,
            "wind_kmh": d["wind_speed_10m_max"][i] or 0.0,
        }
    return uit
