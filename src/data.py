"""Datahentning og konstruktion af månedlige serier.

Kilder (alle gratis, ingen API-nøgle):
  FRED   DTWEXBGS     Feds brede, handelsvægtede dollarindeks (26 partnere, inkl. EM)
  FRED   DCOILBRENTEU Brent-olie, USD pr. tønde
  FRED   DGS10        Amerikansk 10-årig statsrente, pct.
  Yahoo  EMLC         VanEck J.P. Morgan EM Local Currency Bond ETF (lokalvaluta-obligationer, målt i USD)
  Yahoo  EMB          iShares J.P. Morgan USD EM Bond ETF (hård valuta, ingen valutarisiko)
  Yahoo  CEW          WisdomTree Emerging Currency Strategy ETF (ligevægtet EM-valutakurv inkl. kort carry)

Robusthed:
  FRED   DTWEXAFEGS   Dollar mod avancerede økonomier (ingen EM-valutaer i indekset)
  FRED   VIXCLS       VIX, kontrol for global risikoaversion/kriser
  FRED   DEX..US      Spotkurser (valuta pr. USD) for de syv GBI-EM-valutaer, Fed offentliggør:
                      BRL, MXN, ZAR, INR, CNY, MYR, THB. Bruges til en spot-valutakurv uden carry.

Rå data caches i data/raw/ så analysen kan genkøres uden netværk. Man kan
også lægge sine egne CSV-filer der (fx BankInvests fondskurser), se README.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

# DOLLAR_EM_RAW kan pege på en anden mappe (bruges af testen med syntetiske data)
RAW_DIR = Path(os.environ.get("DOLLAR_EM_RAW", Path(__file__).resolve().parents[1] / "data" / "raw"))

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
FX_SERIES = {
    "fx_brl": "DEXBZUS", "fx_mxn": "DEXMXUS", "fx_zar": "DEXSFUS", "fx_inr": "DEXINUS",
    "fx_cny": "DEXCHUS", "fx_myr": "DEXMAUS", "fx_thb": "DEXTHUS",
}
FRED_SERIES = {
    "dollar": "DTWEXBGS", "brent": "DCOILBRENTEU", "us10y": "DGS10",
    "dollar_afe": "DTWEXAFEGS", "vix": "VIXCLS", **FX_SERIES,
}
ETF_TICKERS = {"emlc": "EMLC", "emb": "EMB", "cew": "CEW"}
START = "2006-01-01"


def _cache_path(name: str) -> Path:
    return RAW_DIR / f"{name}.csv"


def _read_cache(name: str) -> pd.Series:
    df = pd.read_csv(_cache_path(name), index_col=0, parse_dates=True)
    return df.iloc[:, 0].rename(name)


def _write_cache(s: pd.Series, name: str) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    s.rename(name).to_frame().to_csv(_cache_path(name))


def fetch_fred(series_id: str) -> pd.Series:
    # requests bruger certifi's certifikater. Det undgår SSL-fejl på Python fra python.org (macOS),
    # hvor pandas' indbyggede urllib ikke kan verificere forbindelsen.
    import io

    import requests

    r = requests.get(FRED_URL.format(series_id), timeout=60, headers={"User-Agent": "dollar-em/1.0"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True, na_values=".")
    return pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()


def fetch_etfs(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf  # importeres kun når der faktisk hentes

    px = yf.download(tickers, start=START, auto_adjust=True, progress=False)["Close"]
    if isinstance(px, pd.Series):
        px = px.to_frame(tickers[0])
    return px.dropna(how="all")


def load_raw(refresh: bool = False) -> dict[str, pd.Series]:
    """Returnerer daglige niveauer. Henter kun det, der ikke allerede er cachet."""
    names = list(FRED_SERIES) + list(ETF_TICKERS)
    missing = [n for n in names if refresh or not _cache_path(n).exists()]

    for name in [n for n in missing if n in FRED_SERIES]:
        print(f"  henter {FRED_SERIES[name]} fra FRED")
        _write_cache(fetch_fred(FRED_SERIES[name]), name)

    etf_missing = [n for n in missing if n in ETF_TICKERS]
    if etf_missing:
        tickers = [ETF_TICKERS[n] for n in etf_missing]
        print(f"  henter {', '.join(tickers)} fra Yahoo Finance")
        px = fetch_etfs(tickers)
        for n in etf_missing:
            _write_cache(px[ETF_TICKERS[n]].dropna(), n)

    return {n: _read_cache(n) for n in names}


def build_monthly(raw: dict[str, pd.Series]) -> pd.DataFrame:
    """Månedlige variable, alle i procent (log-ændringer for priser og dollar).

    r_emlc, r_emb, r_cew : månedligt afkast i USD
    r_spot               : ligevægtet spotafkast i USD på syv GBI-EM-valutaer (uden carry)
    r_lokal              : r_emlc - r_cew, restpost (rente + vægtforskel + carry-forskel)
    r_lokal_spot         : r_emlc - r_spot, restpost med spotkurven som valutaproxy
    d_dollar             : log-ændring i Feds brede dollarindeks (positiv = stærkere dollar)
    d_dollar_afe         : log-ændring i dollaren mod avancerede økonomier
    d_oil                : log-ændring i Brent
    d_us10y              : ændring i 10-årig rente, procentpoint
    d_vix                : ændring i VIX, point
    """
    # Alle serier skæres ved den fælles seneste dato. Ellers dækker den sidste (ufuldstændige)
    # måned forskellige perioder for fx dollaren (FRED, forsinket) og ETF'erne (Yahoo, dagligt).
    common_end = min(v.index.max() for v in raw.values())
    me = {k: v.loc[:common_end].resample("ME").last() for k, v in raw.items()}

    def logret(s: pd.Series) -> pd.Series:
        return 100 * np.log(s).diff()

    df = pd.DataFrame(
        {
            "r_emlc": logret(me["emlc"]),
            "r_emb": logret(me["emb"]),
            "r_cew": logret(me["cew"]),
            "d_dollar": logret(me["dollar"]),
            "d_oil": logret(me["brent"]),
            "d_us10y": me["us10y"].diff(),
            "d_dollar_afe": logret(me["dollar_afe"]),
            "d_vix": me["vix"].diff(),
        }
    )
    # Valuta pr. USD: en stigning er en svækkelse af valutaen, så afkastet i USD er minus log-ændringen
    fx = pd.DataFrame({k: -logret(me[k]) for k in FX_SERIES})
    df["r_spot"] = fx.mean(axis=1, skipna=False)
    df["r_lokal"] = df["r_emlc"] - df["r_cew"]
    df["r_lokal_spot"] = df["r_emlc"] - df["r_spot"]

    # Sidste måned er ufuldstændig, hvis vi er midt i den. Den markeres men smides ikke.
    df.attrs["last_obs"] = {k: v.index.max() for k, v in raw.items()}
    return df.dropna()
