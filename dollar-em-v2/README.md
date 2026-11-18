# Dollar og EM-obligationer i lokalvaluta, version 2

Kode til paperet *Dollarfølsomheden i emerging markets-obligationer i lokalvaluta: lande, euroinvestorer og forudsigelighed* (Albert Claes Poulsen, november 2026).

## Indhold

| Fil | Indhold |
|---|---|
| `hent_gratis_data.py` | Henter data (ECB, FRED, BIS, Yahoo, DBnomics), bygger afkast pr. land for fire investortyper og vægter med EMLC's historiske vægte |
| `analyse_v2.py` | Alle regressioner, robusthedstest, prognoser, tværsnitsstrategier og afdækningsregel. Skriver tabeller og figurer til `resultater/` |
| `paper/EM_Paper_v2.tex` | Paperet. Indlæser tabeller og figurer fra `resultater/` |

## Kørsel

```
pip install pandas numpy requests openpyxl yfinance scipy matplotlib
echo "DIN_FRED_NØGLE" > fred_key.txt          # gratis på fred.stlouisfed.org
python hent_gratis_data.py                     # første gang (henter alt)
python hent_gratis_data.py --genbrug           # senere (genbruger rådata)
python analyse_v2.py                           # tabeller, figurer, noegletal.json
cd paper && cp -r ../resultater . && pdflatex EM_Paper_v2.tex && pdflatex EM_Paper_v2.tex
```

## Data, der skal ligge i `data/manuelt/` (ikke på GitHub)

- `yield10_<VALUTA>.csv` for BRL, CNY, COP, IDR, INR, MXN, MYR, THB: 10-årige statsrenter ved månedsslut fra investing.com (kolonner `dato,vaerdi`).
- `vaegte_historisk.csv`: EMLC's valutavægte fra fondens SEC-indberetninger (N-PORT 2019–2026, N-Q/N-CSR 2010–2019).

Rådata fra investing.com og andre kilder må ikke videredistribueres. Læg `data/` og `fred_key.txt` i `.gitignore`.

## Fastlagte specifikationer

Prædiktorer, fortegn, estimationsvindue (60 mdr.), holdout (2022–2026) og strategiregler står øverst i `analyse_v2.py` og blev fastlagt, før prognoserne blev kørt.
