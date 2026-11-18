"""
hent_gratis_data.py  -  EM-projekt v2 uden Bloomberg.

Henter gratis data (ECB, FRED, BIS, Yahoo), bygger månedlige afkast pr. land
for fire investortyper og kører dollar-regressionerne pr. land.

FRED-nøgle (gratis, anbefalet): opret en konto på fred.stlouisfed.org, gå til
"My Account" -> "API Keys" -> "Request API Key", og læg nøglen i en fil fred_key.txt
i samme mappe som scriptet.

Installation (én gang):
    pip install pandas numpy requests openpyxl yfinance

Kørsel:
    python hent_gratis_data.py              # hent data, byg afkast, kør regressioner
    python hent_gratis_data.py --kun-hent   # hent kun rådata
    python hent_gratis_data.py --dollar broad   # brug Fed's brede indeks i stedet for AFE
    python hent_gratis_data.py --demo       # test med syntetiske data (ingen internet)

Output i mappen data/gratis/:
    raa_maanedlig.csv     alle rådata, ultimo måned
    panel_afkast.csv      afkast pr. land og måned (langt format)
    regressioner.csv      dollarbeta pr. land og afkasttype (+ vægtet aggregat)
    validering.txt        korrelation mellem eget aggregat og EMLC-ETF'en
    log.csv               hvilke serier der blev hentet, fra hvilken kilde, og hvad der mangler

Mangler en serie (fx en 10-årig rente, som FRED ikke har), kan du selv lægge en CSV
i data/manuelt/<navn>.csv med kolonnerne  dato,vaerdi  - den bruges så i stedet.
Navnene står i log.csv (fx yield10_BRL.csv). Valgfrit: data/manuelt/vaegte.csv med
kolonnerne  valuta,vaegt  (fx fra JPM's GBI-EM-factsheet); ellers bruges lige vægte.

Konventioner: afkast er log-afkast i procent pr. måned. Valutakurser er lokal valuta
pr. USD. Renter i procent p.a.
"""

import argparse
import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("data/gratis")
MANUELT = Path("data/manuelt")
START = "2003-01-01"
LOEBETID = 10          # år, for den generiske statsobligation
NW_LAGS = 3            # Newey-West lags (som i v1)

# valuta: (ISO2-landekode, FRED-serie for spot lokal/USD eller None, i ECB?)
LANDE = {
    "CNY": ("CN", "DEXCHUS", True),
    "INR": ("IN", "DEXINUS", True),
    "IDR": ("ID", None, True),
    "MYR": ("MY", "DEXMAUS", True),
    "THB": ("TH", "DEXTHUS", True),
    "MXN": ("MX", "DEXMXUS", True),
    "BRL": ("BR", "DEXBZUS", True),
    "COP": ("CO", None, False),
    "ZAR": ("ZA", "DEXSFUS", True),
    "PLN": ("PL", None, True),
    "CZK": ("CZ", None, True),
    "HUF": ("HU", None, True),
}

FRED_GLOBAL = {
    "USD_BROAD": "DTWEXBGS",      # Fed brede dollarindeks (inkl. EM)
    "USD_AFE": "DTWEXAFEGS",      # Fed dollarindeks mod avancerede økonomier (uden EM)
    "USD_PER_EUR_FRED": "DEXUSEU",
    "VIX": "VIXCLS",
    "BRENT": "DCOILBRENTEU",
    "US2Y": "DGS2",
    "US10Y": "DGS10",
    "DE10Y": "IRLTLT01DEM156N",
}

LOG = []


def log(navn, kilde, ok, note=""):
    LOG.append(dict(serie=navn, kilde=kilde, ok=ok, note=note))
    print(f"  {'ok ' if ok else '-- '} {navn:22s} {kilde:10s} {note}")


# ---------------------------------------------------------------------------
# Hentning
# ---------------------------------------------------------------------------
SIDSTE_FEJL = {"msg": ""}
VAERT_FEJL = {}          # vært -> antal fejl i træk (springes over efter 2)


def _get(url, timeout=20):
    import requests
    from urllib.parse import urlparse
    vaert = urlparse(url).netloc
    if VAERT_FEJL.get(vaert, 0) >= 2:
        SIDSTE_FEJL["msg"] = f"{vaert} svarer ikke - springes over"
        return None
    for forsoeg in range(2):
        try:
            r = requests.get(url, timeout=(10, timeout), headers={"User-Agent": "Mozilla/5.0"})
            VAERT_FEJL[vaert] = 0
            if r.status_code == 200 and r.text.strip():
                return r.text
            SIDSTE_FEJL["msg"] = f"HTTP {r.status_code}"
            if r.status_code in (400, 404):
                return None
        except Exception as e:
            SIDSTE_FEJL["msg"] = f"{type(e).__name__}: {str(e)[:100]}"
            if "Timeout" in type(e).__name__ or "Connection" in type(e).__name__:
                VAERT_FEJL[vaert] = VAERT_FEJL.get(vaert, 0) + 1
                if VAERT_FEJL[vaert] >= 2:
                    return None
        time.sleep(2)
    return None


def manuel(navn):
    p = MANUELT / f"{navn}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").values,
                  index=pd.to_datetime(df.iloc[:, 0], dayfirst=False, errors="coerce"))
    return s.dropna().sort_index()


def fred_noegle():
    import os
    k = os.environ.get("FRED_API_KEY")
    p = Path("fred_key.txt")
    if not k and p.exists():
        k = p.read_text().strip()
    return k or None


def fred(serie_id):
    """FRED: officielt API, hvis der er en nøgle (anbefalet), ellers CSV-download."""
    noegle = fred_noegle()
    if noegle:
        import json
        url = ("https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={serie_id}&api_key={noegle}&file_type=json&observation_start={START}")
        txt = _get(url)
        if txt is None:
            return None
        obs = json.loads(txt).get("observations", [])
        if not obs:
            return None
        s = pd.Series(pd.to_numeric([o["value"] for o in obs], errors="coerce"),
                      index=pd.to_datetime([o["date"] for o in obs]))
        s = s.dropna()
        return s if len(s) else None
    txt = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={serie_id}")
    if txt is None or "<html" in txt[:200].lower():
        return None
    df = pd.read_csv(io.StringIO(txt))
    s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").values,
                  index=pd.to_datetime(df.iloc[:, 0]))
    s = s.dropna()
    return s if len(s) else None


def ecb_fx(valuta):
    """Daglig ECB-referencekurs: valuta pr. EUR."""
    url = (f"https://data-api.ecb.europa.eu/service/data/EXR/D.{valuta}.EUR.SP00.A"
           f"?format=csvdata&startPeriod={START}")
    txt = _get(url)
    if txt is None:
        return None
    df = pd.read_csv(io.StringIO(txt))
    if "TIME_PERIOD" not in df or "OBS_VALUE" not in df:
        return None
    s = pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").values,
                  index=pd.to_datetime(df["TIME_PERIOD"]))
    return s.dropna().sort_index()


def bis_styringsrente(iso2):
    """Månedlig styringsrente fra BIS (WS_CBPOL)."""
    for url in (f"https://stats.bis.org/api/v1/data/WS_CBPOL/M.{iso2}/all?format=csv",
                f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.{iso2}?format=csv"):
        txt = _get(url)
        if txt is None:
            continue
        try:
            df = pd.read_csv(io.StringIO(txt))
            tcol = "TIME_PERIOD" if "TIME_PERIOD" in df else df.columns[-2]
            vcol = "OBS_VALUE" if "OBS_VALUE" in df else df.columns[-1]
            s = pd.Series(pd.to_numeric(df[vcol], errors="coerce").values,
                          index=pd.to_datetime(df[tcol].astype(str)))
            s = s.dropna().sort_index()
            if len(s):
                return s
        except Exception:
            continue
    return None


def bis_reer(iso2):
    """Månedlig real effektiv valutakurs (bred kurv) fra BIS (WS_EER)."""
    for url in (f"https://stats.bis.org/api/v1/data/WS_EER/M.R.B.{iso2}/all?format=csv",
                f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_EER/1.0/M.R.B.{iso2}?format=csv"):
        txt = _get(url)
        if txt is None:
            continue
        try:
            df = pd.read_csv(io.StringIO(txt))
            tcol = "TIME_PERIOD" if "TIME_PERIOD" in df else df.columns[-2]
            vcol = "OBS_VALUE" if "OBS_VALUE" in df else df.columns[-1]
            s = pd.Series(pd.to_numeric(df[vcol], errors="coerce").values,
                          index=pd.to_datetime(df[tcol].astype(str)))
            s = s.dropna().sort_index()
            if len(s):
                return s
        except Exception:
            continue
    return None


def dbnomics_tot(iso2):
    """IMF Commodity Terms of Trade (Gruss & Kebhaj) via DBnomics: netto-råvarebytteforhold
    vægtet med andel af BNP, rullende vægte (ingen look-ahead). Månedlig."""
    import json
    txt = _get(f"https://api.db.nomics.world/v22/series/IMF/PCTOT/M.{iso2}.xm_gdp.R_RW_IX"
               "?observations=1&format=json")
    if txt is None:
        return None
    docs = json.loads(txt).get("series", {}).get("docs", [])
    if not docs:
        return None
    d = docs[0]
    s = pd.Series(pd.to_numeric(d["value"], errors="coerce"),
                  index=pd.PeriodIndex(d["period"], freq="M").to_timestamp(how="end").normalize())
    s = s.dropna()
    return s if len(s) else None


def yahoo(symbol):
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        df = yf.download(symbol, start=START, auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        s = df["Close"]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        s.index = pd.to_datetime(s.index).tz_localize(None)
        return s.dropna()
    except Exception:
        return None


def hent(navn, forsoeg):
    """forsoeg: liste af (kildenavn, funktion). Manuel fil vinder altid."""
    s = manuel(navn)
    if s is not None:
        log(navn, "manuel", True, f"{s.index.min():%Y-%m} til {s.index.max():%Y-%m}")
        return s
    SIDSTE_FEJL["msg"] = ""
    for kilde, f in forsoeg:
        try:
            s = f()
        except Exception:
            s = None
        if s is not None and len(s):
            log(navn, kilde, True, f"{s.index.min():%Y-%m} til {s.index.max():%Y-%m}")
            return s
    grund = f" [{SIDSTE_FEJL['msg']}]" if SIDSTE_FEJL["msg"] else ""
    log(navn, "/".join(k for k, _ in forsoeg) or "-", False,
        f"MANGLER: læg data/manuelt/{navn}.csv{grund}")
    return None


def ultimo(s):
    try:
        return s.resample("ME").last()
    except ValueError:  # ældre pandas
        return s.resample("M").last()


def hent_alt():
    print("Henter data ...")
    print("  FRED: " + ("API-nøgle fundet" if fred_noegle() else
          "ingen API-nøgle (læg den i fred_key.txt) - prøver CSV-download"))
    serier = {}

    # Dollar og globale serier (FRED)
    for navn, sid in FRED_GLOBAL.items():
        serier[navn] = hent(navn, [("FRED", lambda sid=sid: fred(sid))])

    # EUR/USD fra ECB (USD pr. EUR)
    serier["USD_PER_EUR"] = hent("USD_PER_EUR", [("ECB", lambda: ecb_fx("USD")),
                                                 ("FRED", lambda: fred("DEXUSEU"))])
    usd_per_eur = serier["USD_PER_EUR"]

    # Styringsrenter for USA og euroområdet (BIS)
    serier["POL_US"] = hent("POL_US", [("BIS", lambda: bis_styringsrente("US"))])
    serier["POL_EA"] = hent("POL_EA", [("BIS", lambda: bis_styringsrente("XM"))])

    for ccy, (iso, fred_fx, i_ecb) in LANDE.items():
        # Spot: lokal valuta pr. USD. ECB (via EUR-kryds) -> FRED -> Yahoo
        kilder = []
        if i_ecb and usd_per_eur is not None:
            def via_ecb(ccy=ccy):
                lok_per_eur = ecb_fx(ccy)
                if lok_per_eur is None:
                    return None
                df = pd.concat([lok_per_eur, usd_per_eur], axis=1, join="inner").dropna()
                return df.iloc[:, 0] / df.iloc[:, 1]
            kilder.append(("ECB", via_ecb))
        if fred_fx:
            kilder.append(("FRED", lambda sid=fred_fx: fred(sid)))
        kilder.append(("Yahoo", lambda ccy=ccy: yahoo(f"{ccy}=X")))
        serier[f"SPOT_{ccy}"] = hent(f"SPOT_{ccy}", kilder)

        # 10-årig statsrente: FRED (OECD) -> manuel
        serier[f"yield10_{ccy}"] = hent(
            f"yield10_{ccy}", [("FRED", lambda iso=iso: fred(f"IRLTLT01{iso}M156N"))])

        # Styringsrente (BIS)
        serier[f"POL_{ccy}"] = hent(f"POL_{ccy}", [("BIS", lambda iso=iso: bis_styringsrente(iso))])

        # Real effektiv valutakurs (BIS) - bruges til value-prædiktoren
        serier[f"REER_{ccy}"] = hent(f"REER_{ccy}", [("BIS", lambda iso=iso: bis_reer(iso))])

        # Råvarebytteforhold (IMF via DBnomics) - P7
        serier[f"TOT_{ccy}"] = hent(f"TOT_{ccy}", [("DBnomics", lambda iso=iso: dbnomics_tot(iso))])

        # Inflation år-over-år (FRED/OECD)
        serier[f"CPI_{ccy}"] = hent(
            f"CPI_{ccy}", [("FRED", lambda iso=iso: fred(f"CPALTT01{iso}M659N"))])

    # Validering: ETF'er (Yahoo, udbyttejusteret)
    serier["EMLC"] = hent("EMLC", [("Yahoo", lambda: yahoo("EMLC"))])
    serier["EMB"] = hent("EMB", [("Yahoo", lambda: yahoo("EMB"))])

    hentet = {k: ultimo(v) for k, v in serier.items() if v is not None}
    if not hentet:
        pd.DataFrame(LOG).to_csv(OUT / "log.csv", index=False)
        sys.exit("\nIngen serier kunne hentes. Tjek internetforbindelsen (og evt. firewall/VPN).")
    df = pd.concat(hentet, axis=1, sort=True)
    df = df[df.index >= START]
    df.index.name = "dato"
    return df


# ---------------------------------------------------------------------------
# Afkast
# ---------------------------------------------------------------------------
def par_obligation_afkast(y_foer, y_nu, n=LOEBETID):
    """Månedligt afkast (log, %) på en par-obligation med n års løbetid.
    Købt til par ved y_foer (kupon = y_foer), værdisat en måned senere ved y_nu."""
    c = y_foer / 100.0
    y = y_nu / 100.0
    m = n - 1 / 12
    with np.errstate(divide="ignore", invalid="ignore"):
        pris = np.where(np.abs(y) > 1e-8,
                        c / y * (1 - (1 + y) ** (-m)) + (1 + y) ** (-m),
                        1 + c * m)
    simpel = pris - 1 + c / 12
    ud = 100 * np.log1p(simpel)
    # manglende rente i en af månederne -> manglende afkast (ikke et opdigtet tal)
    return np.where(np.isnan(c) | np.isnan(y), np.nan, ud)


def byg_afkast(raa, dollar="afe"):
    rows = []
    usd_eur = raa["USD_PER_EUR"]
    i_us = raa.get("POL_US")
    i_ea = raa.get("POL_EA")
    for ccy in LANDE:
        if f"SPOT_{ccy}" not in raa or f"yield10_{ccy}" not in raa:
            print(f"  springer {ccy} over (mangler spot eller rente)")
            continue
        S = raa[f"SPOT_{ccy}"]
        y = raa[f"yield10_{ccy}"]
        i_c = raa.get(f"POL_{ccy}")
        S_eur = S * usd_eur                         # lokal valuta pr. EUR

        d = pd.DataFrame(index=raa.index)
        d["r_LC"] = par_obligation_afkast(y.shift(1), y)
        d["fx_USD"] = 100 * np.log(S.shift(1) / S)
        d["fx_EUR"] = 100 * np.log(S_eur.shift(1) / S_eur)
        d["A_USD_uafd"] = d["r_LC"] + d["fx_USD"]
        d["B_EUR_uafd"] = d["r_LC"] + d["fx_EUR"]
        if i_c is not None and i_us is not None:
            d["H_USD_afd"] = d["r_LC"] + (i_us.shift(1) - i_c.shift(1)) / 12
        if i_c is not None and i_ea is not None:
            d["D_EUR_afd"] = d["r_LC"] + (i_ea.shift(1) - i_c.shift(1)) / 12
        if i_us is not None and i_ea is not None:
            d["C_EUR_USDhedged"] = d["A_USD_uafd"] + (i_ea.shift(1) - i_us.shift(1)) / 12
        d["valuta"] = ccy
        rows.append(d.reset_index())

    panel = pd.concat(rows, ignore_index=True)
    idx = raa["USD_AFE"] if dollar == "afe" else raa["USD_BROAD"]
    dusd = (100 * np.log(idx / idx.shift(1))).rename("dUSD")
    panel = panel.merge(dusd.reset_index(), on="dato", how="left")
    panel["dEURUSD"] = panel["dato"].map(100 * np.log(usd_eur / usd_eur.shift(1)))
    return panel


def vaegte(datoer=None):
    """Historiske vægte (data/manuelt/vaegte_historisk.csv: dato,valuta,vaegt) har forrang.
    Hver måned bruger de senest kendte vægte (ingen look-ahead); før første observation
    bruges den første. Ellers faste vægte fra vaegte.csv, ellers lige vægte."""
    ph = MANUELT / "vaegte_historisk.csv"
    if ph.exists() and datoer is not None:
        h = pd.read_csv(ph, parse_dates=["dato"])
        p = h.pivot_table(index="dato", columns="valuta", values="vaegt").sort_index()
        idx = pd.DatetimeIndex(sorted(set(pd.to_datetime(datoer))))
        W = p.reindex(p.index.union(idx)).ffill().bfill().reindex(idx).fillna(0.0)
        print(f"  historiske vægte fra {ph} ({len(p)} tidspunkter, {p.index.min():%Y-%m} til {p.index.max():%Y-%m})")
        return W
    p = MANUELT / "vaegte.csv"
    if p.exists():
        w = pd.read_csv(p)
        w = dict(zip(w.iloc[:, 0].str.upper(), w.iloc[:, 1].astype(float)))
        print(f"  faste vægte fra {p}")
        return w
    print("  lige vægte (læg data/manuelt/vaegte.csv eller vaegte_historisk.csv)")
    return {c: 1.0 for c in LANDE}


def aggregat(panel, w):
    kol = [c for c in panel.columns if c not in ("dato", "valuta", "dUSD", "dEURUSD")]
    rows = []
    for dato, g in panel.groupby("dato"):
        wd = w.loc[dato].to_dict() if isinstance(w, pd.DataFrame) else w
        row = {"dato": dato}
        for k in kol:
            gg = g[["valuta", k]].dropna()
            ww = gg.valuta.map(wd).fillna(0.0)
            if ww.sum() <= 0:
                continue
            row[k] = np.average(gg[k], weights=ww)   # renormaliseret til tilgængelige lande
        row["dUSD"] = g["dUSD"].iloc[0]
        row["dEURUSD"] = g["dEURUSD"].iloc[0]
        rows.append(row)
    a = pd.DataFrame(rows)
    a["valuta"] = "AGGREGAT"
    return a


def ols_nw(y, x, lags=NW_LAGS):
    """OLS med Newey-West (Bartlett) standardfejl. Returnerer beta, t, R2, N."""
    y = np.asarray(y, float)
    X = np.column_stack([np.ones(len(x)), np.asarray(x, float)])
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        G = Xe[l:].T @ Xe[:-l]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv * n / (n - k)   # småprøvekorrektion
    se = np.sqrt(np.diag(V))
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    return b[1], b[1] / se[1], r2, n


def regressioner(panel):
    afkast = [c for c in panel.columns if c not in ("dato", "valuta", "dUSD", "dEURUSD")]
    res = []
    for ccy, g in panel.groupby("valuta", sort=False):
        for k in afkast:
            d = g[["dato", "dUSD", k]].dropna()
            if len(d) < 36:
                continue
            beta, t, r2, n = ols_nw(d[k].values, d["dUSD"].values)
            res.append(dict(valuta=ccy, afkast=k, beta=beta, t=t, R2=r2, N=n,
                            fra=d["dato"].min().date(), til=d["dato"].max().date()))
    return pd.DataFrame(res)


def valider(agg, raa, dollar="afe"):
    """Sammenligner eget USD-aggregat med ETF'erne: korrelation, hældning,
    tracking error og dollarbeta på samme periode."""
    linjer = []
    idx = raa["USD_AFE"] if dollar == "afe" else raa["USD_BROAD"]
    dusd = (100 * np.log(idx / idx.shift(1))).rename("dUSD")
    a = agg.set_index("dato")["A_USD_uafd"].rename("eget")
    for etf in ("EMLC", "EMB"):
        if etf not in raa:
            linjer.append(f"{etf}: ikke hentet")
            continue
        r = (100 * np.log(raa[etf] / raa[etf].shift(1))).rename(etf)
        d = pd.concat([a, r, dusd], axis=1, join="inner").dropna()
        if len(d) < 24:
            linjer.append(f"{etf}: for få fælles måneder ({len(d)})")
            continue
        korr = d["eget"].corr(d[etf])
        haeldning, t_h, _, _ = ols_nw(d[etf].values, d["eget"].values)
        te = (d[etf] - d["eget"]).std() * np.sqrt(12)
        b_eget, t_eget, _, _ = ols_nw(d["eget"].values, d["dUSD"].values)
        b_etf, t_etf, _, _ = ols_nw(d[etf].values, d["dUSD"].values)
        linjer += [
            f"{etf}  ({d.index.min():%Y-%m} til {d.index.max():%Y-%m}, N={len(d)})",
            f"  Korrelation med eget aggregat:        {korr:6.3f}",
            f"  Hældning ({etf} på eget aggregat):    {haeldning:6.2f}  (t={t_h:.1f}, bør være ca. 1)",
            f"  Tracking error, årlig:                {te:6.2f} pp",
            f"  Dollarbeta, eget aggregat:            {b_eget:6.2f}  (t={t_eget:.1f})",
            f"  Dollarbeta, {etf}:                     {b_etf:6.2f}  (t={t_etf:.1f})",
        ]
    return "\n".join(linjer)


# ---------------------------------------------------------------------------
def demo_data():
    """Syntetiske data til test uden internet."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2006-01-31", "2026-10-31", freq="ME")
    n = len(idx)
    dusd = rng.normal(0, 1.5, n)
    raa = pd.DataFrame(index=idx)
    raa["USD_AFE"] = 100 * np.exp(np.cumsum(dusd) / 100)
    raa["USD_BROAD"] = raa["USD_AFE"]
    raa["USD_PER_EUR"] = 1.2 * np.exp(np.cumsum(-1.2 * dusd + rng.normal(0, 1, n)) / 100)
    raa["POL_US"] = 2.0
    raa["POL_EA"] = 1.0
    for i, ccy in enumerate(LANDE):
        beta = -1.3 if ccy not in ("PLN", "CZK", "HUF") else -1.15
        raa[f"SPOT_{ccy}"] = (5 + i) * np.exp(np.cumsum(-beta * dusd + rng.normal(0, 2, n)) / 100)
        raa[f"yield10_{ccy}"] = 6 + np.cumsum(0.05 * dusd + rng.normal(0, 0.15, n)) / 5
        raa[f"POL_{ccy}"] = 5.0
    raa["EMLC"] = 100 * np.exp(np.cumsum(-1.6 * dusd + rng.normal(0, 1, n)) / 100)
    raa.index.name = "dato"
    return raa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kun-hent", action="store_true")
    ap.add_argument("--dollar", choices=["afe", "broad"], default="afe",
                    help="dollarindeks: afe (uden EM, standard) eller broad (som i v1)")
    ap.add_argument("--demo", action="store_true", help="test med syntetiske data")
    ap.add_argument("--genbrug", action="store_true",
                    help="genbrug data/gratis/raa_maanedlig.csv (ingen download) + manuelle filer")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    MANUELT.mkdir(parents=True, exist_ok=True)

    if args.demo:
        raa = demo_data()
    elif args.genbrug:
        raa = pd.read_csv(OUT / "raa_maanedlig.csv", index_col=0, parse_dates=True)
        for p in sorted(MANUELT.glob("*.csv")):
            if p.stem.startswith("vaegte"):
                continue
            s_m = manuel(p.stem)
            if s_m is not None and len(s_m):
                raa[p.stem] = ultimo(s_m).reindex(raa.index)
                log(p.stem, "manuel", True, f"{s_m.index.min():%Y-%m} til {s_m.index.max():%Y-%m}")
        # hent nye serier, der ikke fandtes ved sidste fulde kørsel
        for ccy, (iso, _, _) in LANDE.items():
            if f"TOT_{ccy}" not in raa:
                s_t = hent(f"TOT_{ccy}", [("DBnomics", lambda iso=iso: dbnomics_tot(iso))])
                if s_t is not None:
                    raa[f"TOT_{ccy}"] = ultimo(s_t).reindex(raa.index)
        raa.to_csv(OUT / "raa_maanedlig.csv")
    else:
        raa = hent_alt()
        pd.DataFrame(LOG).to_csv(OUT / "log.csv", index=False)
    raa.to_csv(OUT / "raa_maanedlig.csv")
    mangler = [r["serie"] for r in LOG if not r["ok"]]
    if mangler:
        print(f"\n{len(mangler)} serier mangler (se {OUT/'log.csv'}): {', '.join(mangler)}")
    if args.kun_hent:
        return

    noedvendige = ["USD_PER_EUR", "USD_AFE" if args.dollar == "afe" else "USD_BROAD"]
    mangler_noed = [k for k in noedvendige if k not in raa]
    if mangler_noed:
        sys.exit(f"\nKan ikke bygge afkast: mangler {mangler_noed}. Tjek internetforbindelsen "
                 f"eller læg filerne i {MANUELT}/ og kør igen.")

    print("\nBygger afkast ...")
    panel = byg_afkast(raa, args.dollar)
    agg = aggregat(panel, vaegte(panel['dato'].unique()))
    alle = pd.concat([panel, agg], ignore_index=True)
    alle.to_csv(OUT / "panel_afkast.csv", index=False)

    print("Kører regressioner ...")
    reg = regressioner(alle)
    reg.to_csv(OUT / "regressioner.csv", index=False)
    vis = reg[reg.afkast.isin(["fx_USD", "r_LC", "A_USD_uafd", "B_EUR_uafd"])]
    tabel = vis.pivot(index="valuta", columns="afkast", values="beta")
    print(f"\nDollarbeta pr. land (dollarindeks: {args.dollar.upper()}):")
    print(tabel.round(2).to_string())

    v = valider(agg, raa, args.dollar)
    (OUT / "validering.txt").write_text(v, encoding="utf-8")
    print("\nValidering:\n" + v)
    print(f"\nFærdig. Filer i {OUT.resolve()}")


if __name__ == "__main__":
    main()
