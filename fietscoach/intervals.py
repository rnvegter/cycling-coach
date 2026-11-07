"""Minimale client voor de intervals.icu API (https://intervals.icu/api/v1/docs)."""
from __future__ import annotations

from datetime import date

import httpx

BASE = "https://intervals.icu/api/v1"
PREFIX = "fietscoach-"


class Intervals:
    def __init__(self, athlete_id: str, api_key: str):
        self.aid = athlete_id or "0"  # 0 = de atleet van deze API-sleutel
        self.c = httpx.Client(base_url=BASE, auth=("API_KEY", api_key), timeout=30)

    def _get(self, pad: str, **params):
        r = self.c.get(f"/athlete/{self.aid}{pad}", params=params)
        r.raise_for_status()
        return r.json()

    def atleet(self) -> dict:
        return self._get("")

    def ftp(self) -> int | None:
        for s in self.atleet().get("sportSettings", []) or []:
            if "Ride" in (s.get("types") or []):
                return s.get("ftp")
        return None

    def wellness(self, van: date, tot: date) -> list[dict]:
        return self._get("/wellness", oldest=van.isoformat(), newest=tot.isoformat())

    def activiteiten(self, van: date, tot: date) -> list[dict]:
        return self._get("/activities", oldest=van.isoformat(), newest=tot.isoformat())

    def events(self, van: date, tot: date) -> list[dict]:
        return self._get("/events", oldest=van.isoformat(), newest=tot.isoformat())

    def upsert(self, events: list[dict]) -> list[dict]:
        r = self.c.post(f"/athlete/{self.aid}/events/bulk", params={"upsert": "true"}, json=events)
        r.raise_for_status()
        return r.json()

    def verwijder(self, event_id) -> None:
        self.c.delete(f"/athlete/{self.aid}/events/{event_id}").raise_for_status()


def naar_event(s: dict) -> dict:
    return {
        "category": "WORKOUT",
        "start_date_local": f"{s['datum']}T00:00:00",
        "type": "Ride" if s["omgeving"] == "buiten" else "VirtualRide",
        "name": s["naam"],
        "description": s["beschrijving"],
        "external_id": PREFIX + s["datum"],
    }
