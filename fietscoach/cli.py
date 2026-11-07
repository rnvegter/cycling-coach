"""Opdrachtregel: python -m fietscoach.cli [genereer|bijsturen|sync|dagelijks|toon]"""
from __future__ import annotations

import argparse
from datetime import date

from . import service


def main() -> None:
    ap = argparse.ArgumentParser(prog="fietscoach")
    ap.add_argument("opdracht", choices=["genereer", "bijsturen", "sync", "dagelijks", "toon"])
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
    elif a.opdracht == "sync":
        print(service.sync(cfg))
    else:
        for s in service.laad_plan():
            print(f"{s['datum']} {s['dag']} wk{s['week']:>2} {s['omgeving']:<6} {s['naam']}")


if __name__ == "__main__":
    main()
