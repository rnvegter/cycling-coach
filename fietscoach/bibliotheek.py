"""Workoutbibliotheek: varianten per trainingssoort, zodat niet elke sweetspot-
training 3×12 is. Allemaal eigen opbouwen op basis van gangbare trainingsvormen,
in % FTP, en ze passen zich aan de beschikbare tijd en de progressie (p) aan.

Een variant krijgt het 'budget' (minuten tussen warming-up en cooling-down) en p,
en geeft (label, blokken, toelichting) terug, of None als hij niet past.
Variant 0 is steeds de klassieke vorm uit workouts.py.
"""
from __future__ import annotations

from typing import Callable

from .workouts import COOLDOWN, WARMUP, Blok, Stap, Training, fmt_duur, fmt_uren

Hoofd = tuple[str, list[Blok], str]
Variant = Callable[[float, float], Hoofd | None]


def _kies(opties: list, p: float):
    """Optie op basis van progressie: p=0 de lichtste, p=1 de zwaarste."""
    return opties[min(int(p * len(opties)), len(opties) - 1)]


def _past(budget: float, blokken: list[Blok]) -> bool:
    return sum(b.minuten for b in blokken) <= budget


def _sets(maak, budget: float, p: float, opties: list) -> tuple | None:
    """Probeer de optie die bij p hoort en daarna lichtere tot er één past."""
    start = min(int(p * len(opties)), len(opties) - 1)
    for i in range(start, -1, -1):
        uit = maak(*opties[i])
        if uit and _past(budget, uit[1]):
            return uit
    return None


# --- tempo -----------------------------------------------------------------------

def tempo_versnellingen(budget, p):
    def maak(blokken, lengte):
        herh = lengte // 4
        bl = []
        for i in range(blokken):
            bl.append(Blok(f"Tempo {i + 1}", [Stap(3 + 40 / 60, 80), Stap(20 / 60, 108)], herh))
            bl.append(Blok(None, [Stap(5, 60)]))
        return f"Tempo met versnellingen {blokken}×{lengte}m", bl, \
            "Tempo met elke vier minuten een korte versnelling. Na de versnelling direct terug naar tempo, niet uitrusten."
    return _sets(maak, budget, p, [(2, 12), (2, 16), (3, 12), (3, 16), (2, 24)])


def tempo_kracht(budget, p):
    def maak(herh, lengte):
        return f"Krachttempo {herh}×{lengte}m", \
            [Blok("Kracht", [Stap(lengte, 80, 65), Stap(4, 60, 90)], herh)], \
            "Tempo op lage cadans (60–70 rpm), stil op het zadel, romp ontspannen. Herstel op normale cadans."
    return _sets(maak, budget, p, [(3, 8), (3, 10), (4, 10), (3, 14)])


def tempo_oplopend(budget, p):
    def maak(blokken, deel):
        bl = []
        for i in range(blokken):
            bl.append(Blok(f"Blok {i + 1}", [Stap(deel, 76), Stap(deel, 80), Stap(deel, 85)]))
            bl.append(Blok(None, [Stap(5, 60)]))
        return f"Oplopend tempo {blokken}×{3 * deel}m", bl, \
            "Elk blok in drie trappen van rustig tempo naar stevig tempo. Leer het tempo vast te houden als het zwaar wordt."
    return _sets(maak, budget, p, [(2, 4), (2, 5), (3, 4), (2, 7), (3, 5)])


# --- sweetspot -------------------------------------------------------------------

def ss_uitschieters(budget, p):
    def maak(blokken, lengte):
        bl = []
        for i in range(blokken):
            bl.append(Blok(f"Sweetspot {i + 1}", [Stap(2.75, 90), Stap(0.25, 125, vrij=True, cue="Uitschieter")], lengte // 3))
            bl.append(Blok(None, [Stap(5, 55)]))
        return f"Sweetspot met uitschieters {blokken}×{lengte}m", bl, \
            "Sweetspot met elke drie minuten een uitschieter van 15 seconden (ERG uit, rond 125%). Daarna meteen terug naar sweetspot: zo leer je herstellen onder belasting."
    return _sets(maak, budget, p, [(2, 12), (3, 12), (2, 15), (3, 15), (2, 18)])


def ss_ladder(budget, p):
    def maak(*treden):
        pcts = [88, 90, 92, 92][:len(treden)]
        stappen = []
        for t, pct in zip(treden, pcts):
            stappen += [Stap(t, pct), Stap(4, 55)]
        return f"Sweetspotladder {'-'.join(map(str, treden))}", [Blok("Ladder", stappen)], \
            "Elke trede iets langer en iets zwaarder. De laatste is het lastigst; hou hem gelijkmatig."
    return _sets(maak, budget, p, [(6, 8, 10), (8, 10, 12), (10, 12, 15), (8, 10, 12, 15)])


def ss_cadans(budget, p):
    def maak(blokken, lengte):
        bl = []
        for i in range(blokken):
            bl.append(Blok(f"Blok {i + 1}", [Stap(3, 89, 95), Stap(3, 89, 75)], lengte // 6))
            bl.append(Blok(None, [Stap(5, 55)]))
        return f"Sweetspot op cadans {blokken}×{lengte}m", bl, \
            "Zelfde vermogen, wisselende cadans: drie minuten rond 95 rpm, drie minuten rond 75 rpm. In ERG blijft het wattage gelijk."
    return _sets(maak, budget, p, [(2, 12), (3, 12), (2, 18), (3, 18)])


# --- drempel ---------------------------------------------------------------------

def drempel_over_unders(budget, p):
    def maak(sets, herh):
        bl = []
        for i in range(sets):
            bl.append(Blok(f"Set {i + 1}", [Stap(2, 95), Stap(1, 106)], herh))
            bl.append(Blok(None, [Stap(5, 55)]))
        return f"Over-unders {sets}×{herh * 3}m", bl, \
            "Net onder en net boven je drempel. Het 'boven'-stuk verzuurt; het 'onder'-stuk is géén rust."
    return _sets(maak, budget, p, [(2, 3), (3, 3), (2, 4), (3, 4), (4, 4)])


def drempel_piramide(budget, p):
    def maak(*treden):
        midden = len(treden) // 2
        stappen = []
        for i, t in enumerate(treden):
            stappen += [Stap(t, 100 if i == midden else 97), Stap(3, 55)]
        return f"Drempelpiramide {'-'.join(map(str, treden))}", [Blok("Piramide", stappen)], \
            "Op naar het langste blok in het midden en weer terug. Verdeel je krachten: de tweede helft is het zwaarst."
    return _sets(maak, budget, p, [(3, 5, 3), (4, 6, 4), (3, 5, 7, 5, 3), (4, 6, 8, 6, 4)])


def drempel_lang(budget, p):
    def maak(herh, lengte, pct):
        return f"Lange drempel {herh}×{lengte}m", \
            [Blok("Hoofdblok", [Stap(lengte, pct), Stap(6, 55)], herh)], \
            "Lange blokken net onder FTP. Mentaal werk: rustig ademen, cadans stabiel."
    return _sets(maak, budget, p, [(2, 12, 96), (2, 15, 96), (2, 20, 96), (3, 15, 97)])


def drempel_harde_start(budget, p):
    def maak(herh, lengte):
        return f"Drempel met harde start {herh}×{lengte}m", \
            [Blok("Hoofdblok", [Stap(1, 115), Stap(lengte - 1, 98), Stap(4, 55)], herh)], \
            "Elk blok begint met één harde minuut en zakt dan naar drempel. Zoals een aanval gevolgd door doorrijden."
    return _sets(maak, budget, p, [(3, 6), (4, 6), (3, 8), (4, 8), (3, 10)])


# --- VO2max ------------------------------------------------------------------------

def vo2_kort(werk_s: int, rust_s: int, pct: int, opties: list):
    def variant(budget, p):
        def maak(sets, herh):
            bl = []
            for i in range(sets):
                bl.append(Blok(f"Set {i + 1}", [Stap(werk_s / 60, pct, vrij=True, cue="Hard"),
                                                Stap(rust_s / 60, 50, vrij=True, cue="Rustig")], herh))
                bl.append(Blok(None, [Stap(5, 55)]))
            return f"{werk_s}/{rust_s}'s {sets}×{herh}", bl, (
                f"Korte blokken van {werk_s} seconden rond {pct}% FTP met {rust_s} seconden rustig trappen. "
                f"De sets rijd je zonder ERG (op gevoel of wattage): de trainer is te traag voor zulke korte wissels.")
        return _sets(maak, budget, p, opties)
    return variant


def vo2_piramide(budget, p):
    def maak(*treden):
        pct = {2: 115, 3: 112, 4: 110, 5: 108}
        stappen = []
        for t in treden:
            stappen += [Stap(t, pct.get(t, 110)), Stap(t, 50)]
        return f"VO2-piramide {'-'.join(map(str, treden))}", [Blok("Piramide", stappen)], \
            "Herstel even lang als het blok ervoor. Kortere blokken iets harder."
    return _sets(maak, budget, p, [(2, 3, 2), (2, 3, 4, 3, 2), (3, 4, 5, 4, 3)])


def vo2_harde_start(budget, p):
    def maak(herh):
        return f"VO2 met harde start {herh}×4m", \
            [Blok("Hoofdblok", [Stap(1, 125), Stap(3, 108), Stap(4, 50)], herh)], \
            "Vlieg erin en hou dan vast. De eerste minuut voelt makkelijk; de laatste minuut telt."
    return _sets(maak, budget, p, [(3,), (4,), (5,), (6,)])


# --- duur en lange rit -----------------------------------------------------------

def _duur_met(naam: str, blok: list[Stap], blokduur: float, toel: str, soort: str = "duur"):
    """Zone 2 met elke ~10 minuten een kort element (spin-up, sprint, kracht)."""
    def variant(budget, p):
        herh = int(budget // blokduur)
        if herh < 2:
            return None
        herh = min(herh, 6 + int(p * 4))
        rest = budget - herh * blokduur
        bl = [Blok(naam, blok, herh)]
        if rest >= 1:
            bl.append(Blok(None, [Stap(rest, 68)]))
        return naam, bl, toel
    return variant


DUUR = [
    _duur_met("Duur met spin-ups", [Stap(9, 68), Stap(1, 65, 110)], 10,
              "Zone 2 met elke tien minuten een minuut hoge cadans (110+ rpm) zonder meer vermogen. Souplesse."),
    _duur_met("Duur met sprints", [Stap(9 + 50 / 60, 68), Stap(10 / 60, 180, vrij=True, cue="Sprint")], 10,
              "Zone 2 met elke tien minuten een sprint van 10 seconden. Zit of sta, maar vol gas. "
              "De sprint is zonder ERG, anders remt de trainer je af."),
    _duur_met("Duur met kracht", [Stap(10, 68), Stap(5, 75, 60)], 15,
              "Zone 2 met krachtblokjes van vijf minuten op 60 rpm. Rustig vermogen, zware versnelling."),
]


def lang_sterk_eindigen(budget, p):
    eind = 20 if p < 0.5 else 30
    if budget < eind + 40:
        return None
    return "Lange rit, sterk eindigen", \
        [Blok(None, [Stap(budget - eind, 68)]), Blok("Sterk eindigen", [Stap(eind, 82)])], \
        "Rustig opbouwen en het laatste stuk op tempo, als het al zwaar is. Train je voor tochten."


def lang_heuvels(budget, p):
    herh = min(int(budget // 18), 4 + int(p * 3))
    if herh < 3:
        return None
    rest = budget - herh * 18
    bl = [Blok("Heuvel", [Stap(6, 84, 70), Stap(12, 68)], herh)]
    if rest >= 1:
        bl.append(Blok(None, [Stap(rest, 68)]))
    return "Lange rit met klimmetjes", bl, \
        "Duurrit met blokken van zes minuten 'klimmen': tempo op lage cadans. Buiten: zoek een paar bruggen of dijken."


def herstel_spinups(budget, p):
    herh = int(budget // 8)
    if herh < 2:
        return None
    rest = budget - herh * 8
    bl = [Blok("Souplesse", [Stap(7, 52), Stap(1, 55, 105)], herh)]
    if rest >= 1:
        bl.append(Blok(None, [Stap(rest, 52)]))
    return "Herstel met souplesse", bl, "Heel rustig, met af en toe een minuut hoge cadans om de benen los te maken."


BIBLIOTHEEK: dict[str, list[Variant]] = {
    "tempo": [tempo_versnellingen, tempo_kracht, tempo_oplopend],
    "sweetspot": [ss_uitschieters, ss_ladder, ss_cadans],
    "drempel": [drempel_over_unders, drempel_piramide, drempel_lang, drempel_harde_start],
    "vo2max": [vo2_kort(30, 15, 120, [(2, 8), (2, 10), (3, 10), (3, 13)]),
               vo2_kort(40, 20, 118, [(2, 6), (2, 8), (3, 8), (3, 10)]),
               vo2_piramide, vo2_harde_start],
    "duur": DUUR,
    "lange_rit": DUUR,
    "lange_rit_tempo": [lang_sterk_eindigen, lang_heuvels],
    "herstel": [herstel_spinups],
}

# Volledige trainingen (warming-up/cooling-down erbij) voor duurvormen hebben
# een eigen in- en uitloop; intervalvormen de standaard warming-up.
DUURVORMEN = {"duur", "lange_rit", "lange_rit_tempo", "herstel"}


def aantal(soort: str) -> int:
    """Aantal vormen voor deze soort, inclusief de klassieke (variant 0)."""
    return 1 + len(BIBLIOTHEEK.get(soort, []))


def bouw(soort: str, minuten: int, p: float, variant: int) -> Training | None:
    lijst = BIBLIOTHEEK.get(soort)
    if not lijst:
        return None
    keuze = variant % aantal(soort)
    if keuze == 0:
        return None  # klassiek
    if soort in DUURVORMEN:
        inloop, uitloop = (10, 5) if soort != "herstel" else (0, 0)
    else:
        inloop, uitloop = (10 if minuten <= 60 else WARMUP), 2
    budget = minuten - inloop - uitloop
    # de gekozen variant, anders de volgende die past
    for i in range(len(lijst)):
        uit = lijst[(keuze - 1 + i) % len(lijst)](budget, p)
        if uit:
            break
    else:
        return None
    label, hoofd, toel = uit
    blokken: list[Blok] = []
    if inloop:
        blokken.append(Blok("Warming-up" if soort not in DUURVORMEN else None,
                            [Stap(inloop, (50, 75) if soort not in DUURVORMEN else (50, 65))]))
    blokken += hoofd
    rest = minuten - inloop - sum(b.minuten for b in hoofd)
    if soort in DUURVORMEN:
        if rest > 0:
            blokken.append(Blok(None, [Stap(rest, (60, 50))]))
    else:
        cd = min(rest, COOLDOWN)
        if rest - cd >= 3:
            blokken.append(Blok("Duur", [Stap(rest - cd, 65)]))
        else:
            cd = rest
        if cd > 0:
            blokken.append(Blok("Cooling-down", [Stap(cd, (65, 45))]))
    if soort in DUURVORMEN and soort != "herstel":
        label = f"{label} {fmt_uren(minuten)}"
        if soort.startswith("lange_rit") and label.startswith("Duur met"):
            label = label.replace("Duur met", "Lange rit met", 1)
    return Training(soort, label, blokken, toel)


def catalogus(minuten: int = 60, p: float = 0.5) -> list[tuple[str, int, Training]]:
    """Alle vormen per soort, voor het scherm Bibliotheek."""
    from .workouts import bouw as bouw_klassiek
    uit = []
    for soort in ("herstel", "duur", "lange_rit_tempo", "tempo", "sweetspot", "drempel", "vo2max"):
        m = 150 if soort.startswith("lange") else minuten
        for v in range(aantal(soort)):
            t = bouw_klassiek(soort, m, p, "opbouw", v)
            if not any(t.naam == x[2].naam for x in uit):
                uit.append((soort, v, t))
    return uit


__all__ = ["BIBLIOTHEEK", "aantal", "bouw", "catalogus", "fmt_duur"]
