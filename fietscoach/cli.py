"""Opdrachtregel: python -m fietscoach.cli [genereer|bijsturen|sync|dagelijks|toon|test|rooktest|importeer]"""
from __future__ import annotations

import argparse
from datetime import date

from . import service


def importeer(paden: list[str]) -> None:
    """Eigen workouts in bulk uit bestanden, zips en mappen (mappen doorzocht met submappen)."""
    import os
    import shutil
    from pathlib import Path

    from . import eigen
    if not paden:
        raise SystemExit("Geef één of meer .zwo-bestanden, .zip-bestanden of mappen.")
    bestanden = []
    for pad in map(Path, paden):
        kandidaten = sorted(pad.rglob("*")) if pad.is_dir() else [pad]
        for k in kandidaten:
            if k.is_file() and k.suffix.lower() in (".zwo", ".zip"):
                bestanden.append((k.name, k.read_bytes()))
    gelukt, mislukt = eigen.importeer(bestanden)
    for r in gelukt:
        print("✓ " + r)
    for r in mislukt:
        print("✗ " + r)
    print(f"{len(gelukt)} toegevoegd, {len(mislukt)} niet.")
    # Draait dit als root, geef de bestanden dan aan de eigenaar van de datamap,
    # zodat de webapp (gebruiker fietscoach) ze later ook kan bijwerken.
    m = eigen.map_bron() if eigen.map_bron else None
    if m and m.is_dir() and os.geteuid() == 0:
        st = m.parent.stat()
        for p in [m, *m.glob("*.zwo")]:
            shutil.chown(p, st.st_uid, st.st_gid)


def main() -> None:
    ap = argparse.ArgumentParser(prog="fietscoach")
    ap.add_argument("opdracht", choices=["genereer", "bijsturen", "sync", "dagelijks", "toon", "test",
                                         "rooktest", "importeer"])
    ap.add_argument("--opname", help="bij rooktest: map waarin de antwoorden (zonder persoonsgegevens) komen")
    ap.add_argument("--start", help="startdatum JJJJ-MM-DD (bij genereer)")
    ap.add_argument("paden", nargs="*", help="bij importeer: .zwo-bestanden, .zip-bestanden of mappen")
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
    elif a.opdracht == "importeer":
        importeer(a.paden)
        print(service.pas_toe_snel(cfg) or "Schema bijgewerkt.")
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
    elif a.opdracht == "rooktest":
        from pathlib import Path

        from .rooktest import rooktest
        regels = rooktest(cfg, Path(a.opname) if a.opname else None)
        for ok, r in regels:
            print(("✓ " if ok else "✗ ") + r)
        if a.opname:
            print(f"Antwoorden bewaard in {a.opname} (persoonlijke velden vervangen door <weg>).")
        raise SystemExit(0 if all(ok for ok, _ in regels) else 1)
    elif a.opdracht == "sync":
        print(service.sync(cfg))
    else:
        for s in service.laad_plan():
            print(f"{s['datum']} {s['dag']} wk{s['week']:>2} {s['omgeving']:<6} {s['naam']}")


if __name__ == "__main__":
    main()
