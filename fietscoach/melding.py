"""Berichten naar je telefoon: via ntfy (eigen server of ntfy.sh) en/of Telegram.

In config.yaml:
  berichten:
    app_url: https://fietscoach.voorbeeld.nl   # tik op het bericht opent de app
    ntfy:     {url: https://ntfy.sh, topic: mijn-geheime-topic, token: ""}
    telegram: {token: "123:ABC", chat_id: "123456"}
"""
from __future__ import annotations

import httpx


def kanalen(cfg: dict) -> list[str]:
    b = cfg.get("berichten") or {}
    uit = []
    if (b.get("ntfy") or {}).get("topic"):
        uit.append("ntfy")
    t = b.get("telegram") or {}
    if t.get("token") and t.get("chat_id"):
        uit.append("telegram")
    return uit


def stuur(cfg: dict, titel: str, tekst: str, pad: str = "/", client: httpx.Client | None = None,
          tags: tuple[str, ...] = ("bike",)) -> list[tuple[str, bool, str]]:
    """Stuur naar alle ingestelde kanalen. Geeft per kanaal (naam, gelukt, uitleg)."""
    b = cfg.get("berichten") or {}
    app = str(b.get("app_url") or "").rstrip("/")
    klik = app + pad if app else None
    c = client or httpx.Client(timeout=15, headers={"User-Agent": "fietscoach"})
    uit = []
    for kanaal in kanalen(cfg):
        try:
            if kanaal == "ntfy":
                n = b["ntfy"]
                kop = {"Authorization": f"Bearer {n['token']}"} if n.get("token") else {}
                # JSON in plaats van headers: dan mogen titels gewoon – en é bevatten.
                body = {"topic": str(n["topic"]), "title": titel, "message": tekst, "tags": list(tags)}
                if klik:
                    body["click"] = klik
                r = c.post(str(n.get("url") or "https://ntfy.sh").rstrip("/"), json=body, headers=kop)
            else:
                t = b["telegram"]
                r = c.post(f"https://api.telegram.org/bot{t['token']}/sendMessage",
                           json={"chat_id": str(t["chat_id"]), "disable_web_page_preview": True,
                                 "text": f"{titel}\n\n{tekst}" + (f"\n\n{klik}" if klik else "")})
            r.raise_for_status()
            uit.append((kanaal, True, "verstuurd"))
        except httpx.HTTPStatusError as e:
            uit.append((kanaal, False, f"HTTP {e.response.status_code}"))
        except httpx.HTTPError as e:
            uit.append((kanaal, False, f"geen verbinding ({e.__class__.__name__})"))
        except (KeyError, TypeError) as e:
            uit.append((kanaal, False, f"instelling ontbreekt: {e}"))
    return uit
