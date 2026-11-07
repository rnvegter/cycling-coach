"""Trainingsbibliotheek.

Alle doelen staan in % FTP. intervals.icu rekent ze om naar watt met jouw FTP
en stuurt ze als ERG-training naar Zwift (Kickr) of als gestructureerde
training naar je Wahoo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

WARMUP = 12
COOLDOWN = 8


def fmt_duur(minuten: float) -> str:
    sec = round(minuten * 60)
    m, s = divmod(sec, 60)
    if m and s:
        return f"{m}m{s}s"
    if m:
        return f"{m}m"
    return f"{s}s"


def fmt_uren(minuten: float) -> str:
    m = int(round(minuten))
    return f"{m // 60}u{m % 60:02d}" if m >= 60 else f"{m}m"


@dataclass
class Stap:
    minuten: float
    pct: int | tuple[int, int]  # tuple = ramp van..tot
    rpm: int | None = None       # cadansdoel, bv. 65 voor krachtwerk of 110 voor spin-ups
    vrij: bool = False           # ERG uit (intervals.icu 'freeride'); pct is dan alleen richtwaarde
    cue: str | None = None       # aanwijzing op het scherm, bv. "Sprint"

    def tekst(self) -> str:
        cad = f" {self.rpm}rpm" if self.rpm else ""
        cue = f"{self.cue} " if self.cue else ""
        if self.vrij:
            # Een trainer in ERG reageert een paar seconden te laat: bij blokken
            # korter dan een minuut rijd je dan een groot deel op het verkeerde
            # vermogen. Daarom ERG uit en zelf op gevoel/wattage rijden.
            return f"- {cue}{fmt_duur(self.minuten)} freeride{cad}"
        if isinstance(self.pct, tuple):
            return f"- {cue}{fmt_duur(self.minuten)} ramp {self.pct[0]}-{self.pct[1]}%{cad}"
        return f"- {cue}{fmt_duur(self.minuten)} {self.pct}%{cad}"


@dataclass
class Blok:
    titel: str | None
    stappen: list[Stap]
    herhalingen: int = 1

    @property
    def minuten(self) -> float:
        return sum(s.minuten for s in self.stappen) * self.herhalingen

    def tekst(self) -> str:
        kop = self.titel or ""
        if self.herhalingen > 1:
            kop = f"{kop} {self.herhalingen}x".strip()
        regels = ([kop] if kop else []) + [s.tekst() for s in self.stappen]
        return "\n".join(regels)


@dataclass
class Training:
    soort: str
    naam: str
    blokken: list[Blok]
    toelichting: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def minuten(self) -> float:
        return sum(b.minuten for b in self.blokken)

    def beschrijving(self) -> str:
        delen = [self.toelichting] if self.toelichting else []
        delen += [b.tekst() for b in self.blokken]
        return "\n\n".join(delen)


# --- bouwstenen -------------------------------------------------------------

def _wu() -> Blok:
    return Blok("Warming-up", [Stap(WARMUP, (50, 75))])


def _cd() -> Blok:
    return Blok("Cooling-down", [Stap(COOLDOWN, (65, 45))])


def herstel(minuten: int, p: float = 0, fase: str = "") -> Training:
    return Training(
        "herstel",
        f"Herstelrit {fmt_uren(minuten)}",
        [Blok(None, [Stap(minuten, 52)])],
        "Heel rustig rondtrappen, hoge cadans. Zone 1.",
    )


def duur(minuten: int, p: float = 0, fase: str = "", tempo: bool = False,
         naam: str = "Duurrit", soort: str = "duur") -> Training:
    inloop, uitloop = 10, 5
    kern = minuten - inloop - uitloop
    blokken = [Blok(None, [Stap(inloop, (50, 65))])]
    toel = "Rustig duurvermogen, zone 2. Je moet kunnen praten."
    if tempo and kern >= 70:
        t = 15 if p < 0.5 else 20
        voor = (kern - 2 * (t + 5)) // 2
        blokken.append(Blok(None, [Stap(voor, 68)]))
        blokken.append(Blok("Tempo", [Stap(t, 82), Stap(5, 65)], 2))
        na = kern - voor - 2 * (t + 5)
        if na > 0:
            blokken.append(Blok(None, [Stap(na, 68)]))
        toel = "Duurrit met twee tempoblokken in het midden. Tempo = stevig maar beheerst."
    else:
        blokken.append(Blok(None, [Stap(kern, 68)]))
    blokken.append(Blok(None, [Stap(uitloop, (60, 50))]))
    return Training(soort, f"{naam} {fmt_uren(minuten)}", blokken, toel)


def lange_rit(minuten: int, p: float = 0, fase: str = "") -> Training:
    return duur(minuten, p, fase, naam="Lange rit", soort="lange_rit")


def lange_rit_tempo(minuten: int, p: float = 0, fase: str = "") -> Training:
    return duur(minuten, p, fase, tempo=True, naam="Lange rit", soort="lange_rit_tempo")


# (werk_min, rust_min, %FTP, min_herh, max_herh), van makkelijk naar zwaar
OPTIES = {
    "tempo": [(10, 5, 82, 2, 4), (15, 5, 83, 2, 3), (20, 5, 85, 2, 3)],
    "sweetspot": [(10, 5, 88, 3, 4), (12, 4, 89, 3, 4), (15, 5, 90, 2, 3), (20, 4, 90, 2, 3)],
    "drempel": [(6, 4, 98, 3, 5), (8, 4, 98, 3, 5), (10, 5, 100, 2, 4), (12, 5, 100, 2, 3)],
    "vo2max": [(3, 3, 112, 4, 6), (4, 4, 112, 3, 5), (5, 5, 110, 3, 5)],
}
LABELS = {"tempo": "Tempo", "sweetspot": "Sweetspot", "drempel": "Drempel", "vo2max": "VO2max"}
TOELICHTING = {
    "tempo": "Tempo-intervallen (zone 3). Stevig, maar je houdt het lang vol.",
    "sweetspot": "Sweetspot (88–94% FTP). Zwaar maar duurzaam; houd cadans rond 90.",
    "drempel": "Drempelintervallen rond FTP. Gelijkmatig rijden, niet te hard starten.",
    "vo2max": "VO2max-intervallen. Kort en zwaar; de rust is écht rust.",
}


def intervallen(soort: str, minuten: int, p: float = 0, fase: str = "") -> Training:
    opties = OPTIES[soort]
    wu = 10 if minuten <= 60 else WARMUP  # korte sessie: kortere warming-up
    # de rust na het laatste blok telt mee als uitrijden; daarna nog min. 2 min
    budget = minuten - wu - 2
    start = min(int(p * len(opties)), len(opties) - 1)
    for i in range(start, -1, -1):
        werk, rust, pct, lo, hi = opties[i]
        herh = min(hi, int(budget // (werk + rust)))
        if herh >= lo:
            break
    else:
        return duur(minuten)  # te weinig tijd: dan een duurrit
    rest = minuten - wu - herh * (werk + rust)
    cd = min(rest, COOLDOWN)
    blokken = [Blok("Warming-up", [Stap(wu, (50, 75))]),
               Blok("Hoofdblok", [Stap(werk, pct), Stap(rust, 55)], herh)]
    if rest - cd >= 3:
        blokken.append(Blok("Duur", [Stap(rest - cd, 65)]))
    elif rest - cd > 0:
        cd = rest
    blokken.append(Blok("Cooling-down", [Stap(cd, (65, 45))]))
    return Training(soort, f"{LABELS[soort]} {herh}×{fmt_duur(werk)}", blokken, TOELICHTING[soort])


def openers(minuten: int, p: float = 0, fase: str = "") -> Training:
    minuten = max(minuten, 40)
    blokken = [Blok("Warming-up", [Stap(10, (50, 70))]),
               Blok("Openers", [Stap(1, 110), Stap(2, 55)], 3),
               Blok(None, [Stap(minuten - 10 - 9 - 8, 65)]),
               _cd()]
    return Training("openers", f"Openers {fmt_uren(minuten)}", blokken,
                    "Benen wakker maken voor je tocht: kort en scherp, verder rustig.")


def ftp_test(minuten: int = 0, p: float = 0, fase: str = "") -> Training:
    ramp = [Stap(1, 50 + 6 * i) for i in range(16)]  # 50% → 140%
    blokken = [Blok("Warming-up", [Stap(8, (45, 60))]),
               Blok("Ramp – tot je niet meer kunt", ramp),
               Blok("Cooling-down", [Stap(8, (55, 40))])]
    return Training(
        "ftp_test", "FTP-test (ramp)", blokken,
        "Ramp test in ERG op de Kickr. Ga door tot je het vermogen niet meer kunt "
        "trappen. Nieuwe FTP ≈ 75% van je beste minuut. Zet die daarna in intervals.icu.",
    )


def ftp_test_20(minuten: int = 0, p: float = 0, fase: str = "") -> Training:
    """De 20-minutentest volgens Allen en Coggan (Training and Racing with a Power Meter):
    warming-up met snel trappen, 5 minuten maximaal, herstel, dan 20 minuten zo hard als
    je volhoudt. FTP ≈ 95% van het gemiddelde over die 20 minuten."""
    blokken = [Blok("Warming-up", [Stap(20, (50, 70))]),
               Blok("Snel trappen", [Stap(1, 70, 110), Stap(1, 50)], 3),
               Blok(None, [Stap(5, 55)]),
               Blok("5 minuten maximaal", [Stap(5, 115, vrij=True, cue="Maximaal")]),
               Blok(None, [Stap(10, 50)]),
               Blok("20 minuten test", [Stap(20, 100, vrij=True, cue="Test")]),
               Blok("Cooling-down", [Stap(10, (60, 45))])]
    return Training(
        "ftp_test", "FTP-test 20 minuten", blokken,
        "Zonder ERG: rijd de 5 en de 20 minuten zelf zo gelijkmatig mogelijk, niet te hard starten. "
        "Nieuwe FTP ≈ 95% van je gemiddelde vermogen over de 20 minuten. Protocol van Allen en Coggan; "
        "langer dan de ramp-test, maar dichter bij wat je echt een uur volhoudt.",
    )


BOUWERS = {
    "herstel": herstel,
    "duur": duur,
    "lange_rit": lange_rit,
    "lange_rit_tempo": lange_rit_tempo,
    "openers": openers,
    "ftp_test": ftp_test,
    **{s: (lambda m, p=0, fase="", _s=s: intervallen(_s, m, p, fase)) for s in OPTIES},
}

KWALITEITSSOORTEN = set(OPTIES) | {"openers", "ftp_test"}


def bouw(soort: str, minuten: int, p: float = 0, fase: str = "", variant: int = 0) -> Training:
    """Variant 0 is de klassieke vorm; hogere nummers komen uit de bibliotheek.
    Bij de FTP-test kiest variant de testvorm (0 = ramp, 1 = 20 minuten), niet de week."""
    if soort == "ftp_test":
        return ftp_test_20() if variant % 2 == 1 else ftp_test(minuten, p, fase)
    if variant:
        from . import bibliotheek
        t = bibliotheek.bouw(soort, minuten, p, variant)
        if t:
            return t
    return BOUWERS[soort](minuten, p, fase)


# --- JOIN-achtige extra's: zones, profiel, verwachte inspanning, .zwo ----------

# Zelfde zeven banden als de temperatuurschaal van cwem, hier voor intensiteit.
def zoneklasse(pct: float) -> str:
    for grens, naam in ((55, "frozen"), (66, "cold"), (76, "cool"), (88, "mild"),
                        (95, "warm"), (106, "hot")):
        if pct < grens:
            return naam
    return "baking"


SOORTKLASSE = {
    "herstel": "frozen", "duur": "cool", "lange_rit": "cool", "lange_rit_tempo": "mild",
    "tempo": "mild", "sweetspot": "warm", "drempel": "hot", "openers": "hot",
    "vo2max": "baking", "ftp_test": "baking", "rust": "frozen",
}
SOORTNAAM = {
    "herstel": "Herstel", "duur": "Duur", "lange_rit": "Lange rit", "lange_rit_tempo": "Lange rit + tempo",
    "tempo": "Tempo", "sweetspot": "Sweetspot", "drempel": "Drempel", "openers": "Openers",
    "vo2max": "VO2max", "ftp_test": "FTP-test", "rust": "Rust",
}
# Wat een training zou moeten voelen (RPE 1–10) en de verwachte intensiteitsfactor.
VERWACHTE_RPE = {"herstel": 2, "duur": 4, "lange_rit": 5, "lange_rit_tempo": 6, "tempo": 6,
                 "sweetspot": 7, "drempel": 8, "openers": 4, "vo2max": 9, "ftp_test": 10}
VERWACHTE_IF = {"herstel": 0.55, "duur": 0.66, "lange_rit": 0.67, "lange_rit_tempo": 0.72,
                "tempo": 0.74, "sweetspot": 0.80, "drempel": 0.83, "openers": 0.68,
                "vo2max": 0.82, "ftp_test": 0.80}


def segmenten(t: Training) -> list[tuple[float, float, float]]:
    """Plat profiel: (minuten, %van, %tot) per stap, herhalingen uitgeschreven."""
    uit = []
    for b in t.blokken:
        for _ in range(b.herhalingen):
            for s in b.stappen:
                lo, hi = s.pct if isinstance(s.pct, tuple) else (s.pct, s.pct)
                uit.append((s.minuten, lo, hi))
    return uit


def profiel_svg(t: Training, hoogte: int = 64) -> str:
    """Trainingsprofiel als SVG: breedte = tijd, hoogte = % FTP, kleur = zone."""
    seg = segmenten(t)
    totaal = sum(m for m, _, _ in seg) or 1
    top = max(150, max(max(lo, hi) for _, lo, hi in seg) + 10)
    x, delen = 0.0, []
    for m, lo, hi in seg:
        w = m / totaal * 1000
        y1, y2 = hoogte - lo / top * hoogte, hoogte - hi / top * hoogte
        klasse = zoneklasse((lo + hi) / 2)
        delen.append(f'<path d="M{x:.1f} {hoogte} L{x:.1f} {y1:.1f} L{x + w:.1f} {y2:.1f} '
                     f'L{x + w:.1f} {hoogte} Z" style="fill:var(--t-{klasse})"/>')
        x += w
    ftp_y = hoogte - 100 / top * hoogte
    delen.append(f'<line x1="0" x2="1000" y1="{ftp_y:.1f}" y2="{ftp_y:.1f}" '
                 f'style="stroke:var(--text-dim)" stroke-dasharray="6 6" stroke-width="1"/>')
    return (f'<svg class="fc-profiel" viewBox="0 0 1000 {hoogte}" preserveAspectRatio="none" '
            f'role="img" aria-label="Trainingsprofiel">{"".join(delen)}</svg>')


def zwo(t: Training) -> str:
    """Zwift-workout (.zwo) als reserve, voor als de sync via intervals.icu hapert."""
    from xml.sax.saxutils import escape
    regels = []
    laatste = len(t.blokken) - 1
    for bi, b in enumerate(t.blokken):
        st = b.stappen
        if b.herhalingen > 1 and len(st) == 2 and not any(isinstance(s.pct, tuple) or s.rpm or s.vrij for s in st):
            regels.append(f'<IntervalsT Repeat="{b.herhalingen}" OnDuration="{round(st[0].minuten * 60)}" '
                          f'OffDuration="{round(st[1].minuten * 60)}" OnPower="{st[0].pct / 100:.2f}" '
                          f'OffPower="{st[1].pct / 100:.2f}"/>')
            continue
        for _ in range(b.herhalingen):
            for si, s in enumerate(st):
                sec = round(s.minuten * 60)
                if s.vrij:
                    regels.append(f'<FreeRide Duration="{sec}" FlatRoad="1"/>')
                    continue
                if isinstance(s.pct, tuple):
                    tag = ("Warmup" if bi == 0 and si == 0 else
                           "Cooldown" if bi == laatste and si == len(st) - 1 else "Ramp")
                    regels.append(f'<{tag} Duration="{sec}" PowerLow="{s.pct[0] / 100:.2f}" '
                                  f'PowerHigh="{s.pct[1] / 100:.2f}"/>')
                else:
                    cad = f' Cadence="{s.rpm}"' if s.rpm else ""
                    regels.append(f'<SteadyState Duration="{sec}" Power="{s.pct / 100:.2f}"{cad}/>')
    return ("<workout_file>\n  <author>Fietscoach</author>\n"
            f"  <name>{escape(t.naam)}</name>\n  <description>{escape(t.toelichting)}</description>\n"
            "  <sportType>bike</sportType>\n  <workout>\n    "
            + "\n    ".join(regels) + "\n  </workout>\n</workout_file>\n")
