"""Tjek af de hentede data. Kør:  python3 check_data.py

Udskriver dækning, huller, de største månedlige bevægelser og afkast i kendte
krisemåneder, så man kan sammenholde med det, man ved om markedet.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from data import build_monthly, load_raw  # noqa: E402

pd.set_option("display.width", 200, "display.max_columns", None, "display.max_colwidth", 60, "display.precision", 2)

raw = load_raw()

print("\n=== 1. Dækning af de rå (daglige) serier ===")
rows = []
for k, s in raw.items():
    gaps = s.index.to_series().diff().dt.days
    rows.append({
        "serie": k, "start": s.index.min().date(), "slut": s.index.max().date(), "obs": len(s),
        "min": s.min(), "max": s.max(), "største hul (dage)": int(gaps.max()),
        "dubletter": int(s.index.duplicated().sum()), "uændret 5+ dage i træk":
        int((s.diff().eq(0).astype(int).groupby(s.diff().ne(0).cumsum()).sum() >= 5).sum()),
    })
print(pd.DataFrame(rows).set_index("serie"))

df = build_monthly(raw)
print(f"\n=== 2. Månedlige data: {df.index.min():%Y-%m} til {df.index.max():%Y-%m}, N = {len(df)} ===")
print(df.describe().T[["mean", "std", "min", "max"]])

print("\n=== 3. De 5 største månedlige bevægelser pr. variabel ===")
for c in ["r_emlc", "r_cew", "r_emb", "d_dollar"]:
    top = df[c].abs().nlargest(5).index
    print(f"{c:9s} " + "  ".join(f"{d:%Y-%m}: {df.at[d, c]:+.1f}" for d in top))

print("\n=== 4. Kendte episoder (bør stemme med markedshistorien) ===")
episodes = {
    "2013-06": "Taper tantrum: EM-obligationer faldt, dollaren steg",
    "2015-08": "Kinas devaluering: EM-valuta faldt kraftigt",
    "2020-03": "Covid-krak: stort fald i EM, dollaren steg markant",
    "2022-09": "Stærk dollar-top: EM lokalvaluta faldt",
    "2026-09": "Fed-forhøjelse: dollaren steg",
}
cols = ["d_dollar", "r_emlc", "r_cew", "r_emb", "d_oil", "d_us10y"]
ep = df.loc[[pd.Timestamp(m) + pd.offsets.MonthEnd(0) for m in episodes if pd.Timestamp(m) + pd.offsets.MonthEnd(0) in df.index], cols]
ep.index = [f"{d:%Y-%m}  {episodes[f'{d:%Y-%m}']}" for d in ep.index]
print(ep)

print("\n=== 5. Korrelationer ===")
print(df[["d_dollar", "r_emlc", "r_cew", "r_emb", "d_oil", "d_us10y"]].corr().round(2))

print("\n=== 6. Advarsler ===")
warn = []
for c in ["r_emlc", "r_cew", "r_emb"]:
    big = df.index[df[c].abs() > 20]
    if len(big):
        warn.append(f"{c}: månedsafkast over 20 % i {[f'{d:%Y-%m}' for d in big]} (tjek for datafejl)")
if (df[["r_emlc", "r_cew", "r_emb"]] == 0).any().any():
    warn.append("Nogle månedsafkast er præcis 0 (mulige manglende kurser)")
print("\n".join(warn) if warn else "Ingen advarsler.")
