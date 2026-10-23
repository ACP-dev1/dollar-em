"""Syntetiske data med KENDTE parametre, så man kan tjekke at pipelinen genfinder dem.

Sande værdier:
  CEW   : beta_op = -1.0, beta_ned = -0.6   (asymmetrisk)
  lokal : beta    = -0.3
  EMLC  : = CEW + lokal  -> beta_op = -1.3, beta_ned = -0.9
  EMB   : beta    = -0.4
  olie  : +0.08 på CEW
Ingen forudsigelseskraft (afkast afhænger kun af samtidige stød).

Brug:  python tests/make_synthetic.py <mappe>   (skriver CSV'er i samme format som cachen)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

TRUE = {"cew_op": -1.0, "cew_ned": -0.6, "lokal": -0.3, "emb": -0.4, "oil_cew": 0.08}


def simulate(seed: int = 7) -> dict[str, pd.Series]:
    """Månedlige niveauer (månedsslut) med kendte parametre."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2010-07-01", "2026-10-23")
    months = pd.date_range("2010-07-31", "2026-10-31", freq="ME")
    n = len(months)

    d_usd = rng.normal(0, 1.8, n)
    d_oil = rng.normal(0, 8.0, n)
    d_10y = rng.normal(0, 0.2, n)

    r_cew = 0.1 + TRUE["cew_op"] * np.maximum(d_usd, 0) + TRUE["cew_ned"] * np.minimum(d_usd, 0) \
        + TRUE["oil_cew"] * d_oil + rng.normal(0, 1.2, n)
    r_lok = 0.3 + TRUE["lokal"] * d_usd + rng.normal(0, 1.0, n)
    r_emb = 0.4 + TRUE["emb"] * d_usd + rng.normal(0, 1.5, n)

    def level(log_changes_pct, start):
        return start * np.exp(np.cumsum(log_changes_pct) / 100)

    fx_codes = ["fx_brl", "fx_mxn", "fx_zar", "fx_inr", "fx_cny", "fx_myr", "fx_thb"]
    # Spotkurven følger CEW's valutadel tæt; hver valuta = kurv + idiosynkratisk støj.
    # Valuta pr. USD, så niveauet er det inverse af valutaens værdi.
    spot_basket = r_cew - 0.1 + rng.normal(0, 0.4, n)
    series_fx = {}
    for code in fx_codes:
        own = spot_basket + rng.normal(0, 1.0, n)
        own = own - (own.mean() - spot_basket.mean())
        series_fx[code] = level(-own, 10)
    d_afe = 0.8 * d_usd + rng.normal(0, 0.8, n)
    vix = np.clip(18 + np.cumsum(rng.normal(0, 2, n)) * 0.3 + 3 * np.maximum(d_usd, 0), 9, 80)

    series = {
        "dollar": level(d_usd, 100),
        "brent": level(d_oil, 75),
        "us10y": 2.5 + np.cumsum(d_10y),
        "cew": level(r_cew, 20),
        "emlc": level(r_cew + r_lok, 30),
        "emb": level(r_emb, 100),
        "dollar_afe": level(d_afe, 100),
        "vix": vix,
        **series_fx,
    }
    return {k: pd.Series(v, index=months, name=k) for k, v in series.items()}


def main(outdir: Path, seed: int = 7) -> None:
    days = pd.bdate_range("2010-07-01", "2026-10-23")
    series = simulate(seed)
    outdir.mkdir(parents=True, exist_ok=True)
    for name, m in series.items():
        # læg månedsniveauet på månedens sidste handelsdag og fyld dagene ud
        d = m.reindex(days.union(m.index)).bfill().reindex(days).dropna()
        d.rename(name).to_frame().to_csv(outdir / f"{name}.csv")
    print(f"skrev {len(series)} syntetiske serier til {outdir}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
