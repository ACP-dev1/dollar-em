# Dollaren og EM-obligationer i lokalvaluta

📄 **Artikel:** [`paper/paper.pdf`](paper/paper.pdf) · LaTeX-kilde: [`paper/paper.tex`](paper/paper.tex)

Albert Claes Poulsen, Økonomisk Institut, Københavns Universitet. Working paper, oktober 2026.

**Spørgsmål:** Hvor følsomme er emerging markets-obligationer i lokalvaluta over for den amerikanske dollar, og kommer følsomheden fra valutaen eller fra den lokale rente?

**Motivation:** Dollaren svækkedes gennem sommeren 2026, men vendte kraftigt i september efter Feds renteforhøjelse. Mange EM-cases bygger på en svagere dollar. Projektet kvantificerer, hvad en dollarvending betyder for et EM-lokalvalutaporteføljeafkast, og om effekten er symmetrisk.

## Data (månedlige, 2010 til i dag)

| Variabel | Kilde | Serie |
|---|---|---|
| Dollar, bredt | FRED | `DTWEXBGS`, Feds brede dollarindeks (indeholder også EM-valutaer) |
| Dollar, avancerede økonomier | FRED | `DTWEXAFEGS` (robusthed: ingen EM-valutaer) |
| Olie | FRED | `DCOILBRENTEU`, Brent |
| US-rente | FRED | `DGS10`, 10-årig statsrente |
| VIX | FRED | `VIXCLS` (eksplorativ kontrol for kriser) |
| EM-spotkurser | FRED | `DEXBZUS`, `DEXMXUS`, `DEXSFUS`, `DEXINUS`, `DEXCHUS`, `DEXMAUS`, `DEXTHUS` (BRL, MXN, ZAR, INR, CNY, MYR, THB) |
| EM lokalvaluta-obligationer | Yahoo | `EMLC` (VanEck J.P. Morgan EM Local Currency Bond ETF) |
| EM-valutakurv | Yahoo | `CEW` (WisdomTree Emerging Currency Strategy ETF, inkl. kort carry) |
| EM hård valuta | Yahoo | `EMB` (iShares J.P. Morgan USD EM Bond ETF) |

Alle serier måles ved månedens sidste handelsdag. ETF-kurserne er justeret for udlodninger.

EMLC's afkast deles i en valutadel og en restpost: $r^{rest} = r^{EMLC} - r^{FX}$, hvor valutaproxyen $r^{FX}$ er enten CEW eller en ligevægtet spotkurv af de syv GBI-EM-valutaer. Restposten indeholder lokal rente, men også vægtforskel og (for CEW) carry, så den er ikke en ren rentekanal.

## Hypoteser

Skrevet ned, før analysen blev kørt på de rigtige data (ikke dokumenteret med tidsstempler).

| | Hypotese | Forventet fortegn |
|---|---|---|
| H1 | Dollarbetaen er negativ og signifikant for EMLC, CEW og EMB | $\beta < 0$ |
| H2 | Lokalvaluta er mere dollarfølsom end hård valuta | $\beta^{EMLC} - \beta^{EMB} < 0$ |
| H3 | Over halvdelen af EMLC's dollarbeta kommer fra valutaen (CEW) | $\beta^{CEW}/\beta^{EMLC} > 0{,}5$ |
| H4 | Dollarstyrke gør mere ondt end dollarsvaghed gavner (EMLC) | $\lvert\beta^{op}\rvert > \lvert\beta^{ned}\rvert$ |
| H5 | Sidste måneds dollarændring forudsiger næste måneds afkast | $R^2_{OOS} > 0$, signifikant |
| H6 | Olie har positiv effekt, og dollarbetaen overlever kontrol for olie og US-renter | $\gamma^{olie} > 0$ |

Dommene er "understøttes" eller "understøttes ikke". Et ikke-signifikant resultat er fravær af evidens, ikke evidens for nul.

**Eksplorativt (ikke forhåndsfastlagt):** dollarindekset uden EM-valutaer, spotkurven som alternativ valutaproxy, asymmetri for CEW og asymmetri med kontrol for VIX.

## Metode

- OLS med Newey-West-standardfejl (3 lags).
- Asymmetri: separate betaer for måneder med stigende og faldende dollar, Wald-test af ens betaer.
- 36 måneders rullende beta.
- Forudsigelse: udvidende vindue (mindst 60 måneder), benchmark er det historiske gennemsnit på samme vindue, Clark-West-test.
- Episodeanalyse: modellen estimeres *uden* de seneste 3 måneder og sammenlignes med de faktiske afkast.

## Validering

`tests/monte_carlo.py` kører hele analysen på 2.000 syntetiske datasæt med kendte parametre:

| | Resultat (MC-standardfejl) |
|---|---|
| Gns. $\hat\beta^{op}$, $\hat\beta^{ned}$ (sand $-1{,}0$ og $-0{,}6$) | $-1{,}00$ og $-0{,}60$ |
| Clark-West, forkastelsesrate under nul (nominelt 5 %) | 3,2 % (0,4) |
| Asymmetritest, forkastelsesrate ved sand symmetri | 5,5 % (0,5) |
| Asymmetritest, styrke ved sand forskel 0,4 (EMLC / CEW) | 46,9 % (1,1) / 63,6 % (1,1) |

At betaerne for valutadel og restpost summerer til EMLC's beta er en regneidentitet og bruges ikke som validering.

## Kør

Data (`data/raw/`) og den færdige artikel (`paper/paper.pdf`) ligger allerede i mappen. Der skal altså ikke hentes noget for at læse resultaterne.

**Genkør analysen på de gemte data:**

```bash
python3 -m pip install -r requirements.txt
python3 run.py
```

**Hent nye data** (fx næste måned):

```bash
python3 run.py --refresh
```

Dollar, olie og rente hentes fra FRED, og ETF-kurserne fra Yahoo Finance. Ingen af dem kræver en API-nøgle. Giver hentningen `SSL: CERTIFICATE_VERIFY_FAILED` på Mac, så kør først `"/Applications/Python 3.13/Install Certificates.command"` én gang.

**Monte Carlo-validering** (ca. 6 minutter):

```bash
python3 tests/monte_carlo.py 2000
```

**Tjek data:**

```bash
python3 check_data.py
```

Udskriver dækning, huller, de største udsving og afkast i kendte krisemåneder (2013, 2015, 2020, 2022, 2026) til sammenligning med markedshistorien.

**PDF'en:** `run.py` laver `paper/paper.pdf`, hvis LaTeX er installeret. Ellers opdateres tabeller og tal i `paper/generated/`, men PDF'en skal kompileres separat. LaTeX på Mac: `brew install --cask basictex` (ca. 100 MB) eller MacTeX.

Resultater skrives til `results/`: `rapport.md` med tabeller og hypotesedomme, figurer og CSV-filer med alle estimater. Artiklen henter alle tal og domme fra `paper/generated/`, så teksten skal ikke rettes manuelt, når data opdateres.

Test med syntetiske data:

```bash
python3 tests/make_synthetic.py /tmp/synth
DOLLAR_EM_RAW=/tmp/synth python3 run.py
```

## Struktur

```
run.py                 kør hele analysen
check_data.py          tjek af de hentede data
data/raw/              rå data (hentet 23. oktober 2026)
src/data.py            datahentning og månedlige serier
src/analysis.py        regressioner, asymmetri, rullende beta, out-of-sample
src/report.py          figurer og rapport.md
src/latex.py           LaTeX-tabeller og tal-makroer til artiklen
paper/paper.tex        artiklen
paper/references.bib   litteratur
paper/generated/       genereres af run.py
tests/                 syntetiske data og Monte Carlo-validering
```

Test med syntetiske data:

```bash
python tests/make_synthetic.py /tmp/synth
DOLLAR_EM_RAW=/tmp/synth python run.py
```

## Begrænsninger

- Hverken CEW eller spotkurven matcher EMLC's landevægte. En ren opdeling kræver J.P. Morgan GBI-EM i både hedget og uhedget version.
- CEW handles sjældent og har uændrede slutkurser i nogle måneder, hvilket trækker dens beta mod nul.
- ETF'er har gebyrer og tracking error i forhold til de underliggende indeks.
- Samtidige regressioner viser eksponering, ikke kausalitet. Både dollaren og EM-aktiver drives af global risikovillighed.
