"""Opdrachtregel: python -m fietscoach.cli [genereer|bijsturen|sync|dagelijks|toon]"""
from __future__ import annotations

import argparse
from datetime import date

from . import service


def main() -> None:
    ap = argparse.ArgumentParser(prog="fietscoach")
    ap.add_argument("opdracht", choices=["genereer", "bijsturen", "sync", "dagelijks", "toon", "test"])
    ap.add_argument("--start", help="startdatum JJJJ-MM-DD (bij genereer)")
    a = ap.parse_args()
    cfg = service.laad_config()
    if a.opdracht == "genereer":
        plan = service.genereer(cfg, date.fromisoformat(a.start) if a.start else None)
        print(f"Schema gemaakt: {len(plan)} trainingen.")
    elif a.opdracht in ("bijsturen", "dagelijks"):
        for regel in service.bijsturen(cfg):
            print(regel)
        if a.opdracht == "dagelijks":
            print(service.sync(cfg))
    elif a.opdracht == "test":
        from .intervals import verbindingstest
        try:
            ic = service.client(cfg)
            if not ic:
                raise SystemExit("Geen API-sleutel in de config.")
            regels = verbindingstest(ic)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001  bv. een onleesbaar certificaatbestand
            regels = [(False, f"Kon geen verbinding opzetten: {e.__class__.__name__}: {e}")]
        for ok, r in regels:
            print(("✓ " if ok else "✗ ") + r)
        raise SystemExit(0 if all(ok for ok, _ in regels) else 1)
    elif a.opdracht == "sync":
        print(service.sync(cfg))
    else:
        for s in service.laad_plan():
            print(f"{s['datum']} {s['dag']} wk{s['week']:>2} {s['omgeving']:<6} {s['naam']}")


if __name__ == "__main__":
    main()
