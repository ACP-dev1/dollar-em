"""
analyse_v2.py  -  EM-projekt v2: dollarfølsomhed pr. land, euro- vs. dollarinvestor og prognoser.

Kræver, at hent_gratis_data.py er kørt først (data/gratis/raa_maanedlig.csv findes).
Kørsel (i samme mappe som hent_gratis_data.py):
    python analyse_v2.py

Output i resultater/:
    tab_*.tex      tabeller (indsættes direkte i paperet med \\input)
    fig_*.pdf      figurer
    noegletal.json alle tal, der citeres i teksten

Alle specifikationer (prædiktorer, fortegn, vinduer, evalueringsperioder) er fastlagt
øverst i filen, før koden blev kørt på data.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import hent_gratis_data as hg

RES = Path("resultater")
RES.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Fastlagte specifikationer
# ---------------------------------------------------------------------------
NW = 3                      # Newey-West lags (som i v1)
MIN_TRAEN = 60              # mindste estimationsvindue i måneder (som i v1)
GAMMA = 3                   # risikoaversion i timing-strategien
MAX_VAEGT = 1.5             # maks. vægt i EM i timing-strategien
SPLIT = "2021-12-31"        # evaluering: før og efter 2022 (holdout)
UNDERPERIODE = "2014-12-31" # robusthed: 2006-2014 vs. 2015-2026
PRAEDIKTORER = ["carry", "dmom", "fxmom", "value", "vix"]
FORTEGN = {"carry": 1, "dmom": -1, "fxmom": 1, "value": 1, "vix": 1}
HOVEDMODEL = ["carry", "dmom", "vix"]
LANDE = list(hg.LANDE)
NAVN = {"CNY": "Kina", "INR": "Indien", "IDR": "Indonesien", "MYR": "Malaysia",
        "THB": "Thailand", "MXN": "Mexico", "BRL": "Brasilien", "COP": "Colombia",
        "ZAR": "Sydafrika", "PLN": "Polen", "CZK": "Tjekkiet", "HUF": "Ungarn"}
NAVN_PRAED = {"carry": "Carry", "dmom": "Dollar-momentum", "fxmom": "Valuta-momentum",
              "value": "Value (REER)", "vix": "VIX"}

N = {}  # nøgletal til teksten


# ---------------------------------------------------------------------------
# Hjælpefunktioner
# ---------------------------------------------------------------------------
def ols(y, X, lags=NW):
    """OLS med konstant og Newey-West kovarians. Returnerer (b, V, R2, n)."""
    y = np.asarray(y, float)
    X = np.column_stack([np.ones(len(y)), np.asarray(X, float).reshape(len(y), -1)])
    n, k = X.shape
    XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ y
    e = y - X @ b
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for l in range(1, lags + 1):
        G = Xe[l:].T @ Xe[:-l]
        S += (1 - l / (lags + 1)) * (G + G.T)
    V = XtXi @ S @ XtXi * n / (n - k)
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    return b, V, r2, n


def beta(df, ycol, xcol="dUSD"):
    d = df[[ycol, xcol]].dropna()
    b, V, r2, n = ols(d[ycol].values, d[xcol].values)
    return dict(b=b[1], t=b[1] / np.sqrt(V[1, 1]), r2=r2, n=n)


def stjerner(t):
    t = abs(t)
    return "^{***}" if t > 2.576 else "^{**}" if t > 1.96 else "^{*}" if t > 1.645 else ""


def f(x, d=2, sig=None):
    """Tal med dansk decimalkomma i matematiktilstand."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "--"
    s = f"{x:.{d}f}".replace(".", "{,}").replace("-", "-")
    return f"${s}{stjerner(sig) if sig is not None else ''}$"


def ft(t):
    return f"$({t:.2f})$".replace(".", "{,}")


def gem_tabel(navn, linjer):
    (RES / f"tab_{navn}.tex").write_text("\n".join(linjer) + "\n", encoding="utf-8")


def wald_lige(b, V, i, j):
    from scipy import stats
    d = b[i] - b[j]
    v = V[i, i] + V[j, j] - 2 * V[i, j]
    w = d * d / v
    return float(1 - stats.chi2.cdf(w, 1))


# ---------------------------------------------------------------------------
# 1. Data og afkast
# ---------------------------------------------------------------------------
raa = pd.read_csv(hg.OUT / "raa_maanedlig.csv", index_col=0, parse_dates=True)
for p in sorted(hg.MANUELT.glob("yield10_*.csv")):
    s = hg.manuel(p.stem)
    if s is not None and len(s):
        raa[p.stem] = hg.ultimo(s).reindex(raa.index)

panel = hg.byg_afkast(raa, "afe")
W = hg.vaegte(panel["dato"].unique())
agg = hg.aggregat(panel, W).set_index("dato")
panel_b = hg.byg_afkast(raa, "broad")
agg_b = hg.aggregat(panel_b, W).set_index("dato")

upe = raa["USD_PER_EUR"]
dEURUSD = 100 * np.log(upe / upe.shift(1))
agg["dEURUSD"] = dEURUSD.reindex(agg.index)

# EMLC-ETF i USD og i EUR
emlc = raa["EMLC"]
etf = pd.DataFrame({"EMLC_USD": 100 * np.log(emlc / emlc.shift(1))})
etf["EMLC_EUR"] = etf["EMLC_USD"] - dEURUSD
etf["dUSD"] = agg["dUSD"]
etf["dUSD_broad"] = agg_b["dUSD"]

i_us = raa["POL_US"].shift(1) / 12
i_ea = raa["POL_EA"].shift(1) / 12

N["periode"] = [str(agg.dropna(subset=["A_USD_uafd", "dUSD"]).index.min().date()),
                str(agg.index.max().date())]
N["n_agg"] = int(agg["A_USD_uafd"].notna().sum())

# ---------------------------------------------------------------------------
# 2. Landeregressioner
# ---------------------------------------------------------------------------
rows = []
for c in LANDE:
    g = panel[panel.valuta == c].set_index("dato")
    r = {"valuta": c}
    for k in ["A_USD_uafd", "fx_USD", "r_LC", "B_EUR_uafd", "D_EUR_afd", "C_EUR_USDhedged"]:
        if k in g:
            r[k] = beta(g, k)
    r["start"] = str(g.join(agg["dUSD"].rename("dU"), how="left")[["A_USD_uafd", "dU"]].dropna().index.min().date())
    rows.append(r)
aggrow = {"valuta": "AGG"}
for k in ["A_USD_uafd", "fx_USD", "r_LC", "B_EUR_uafd", "D_EUR_afd", "C_EUR_USDhedged"]:
    aggrow[k] = beta(agg, k)
rows.append(aggrow)

orden = sorted(LANDE, key=lambda c: next(r for r in rows if r["valuta"] == c)["A_USD_uafd"]["b"])
lines = [r"\begin{tabular}{lcccccc}", r"\toprule",
         r" & $\beta^{USD}$ & $\beta^{FX}$ & $\beta^{LC}$ & Valutaandel & $R^2$ & Start \\",
         r"\midrule"]
for c in orden + ["AGG"]:
    r = next(x for x in rows if x["valuta"] == c)
    if c == "AGG":
        lines.append(r"\midrule")
    a, fx, lc = r["A_USD_uafd"], r["fx_USD"], r["r_LC"]
    andel = 100 * fx["b"] / a["b"] if abs(a["b"]) > 0.2 else np.nan
    navn = "Vægtet aggregat" if c == "AGG" else NAVN[c]
    start = r.get("start", N["periode"][0])[:7]
    lines.append(f"{navn} & {f(a['b'], sig=a['t'])} & {f(fx['b'], sig=fx['t'])} & {f(lc['b'], sig=lc['t'])} & "
                 f"{f(andel, 0)}\\,\\% & {f(a['r2'])} & {start} \\\\")
    lines.append(f" & {ft(a['t'])} & {ft(fx['t'])} & {ft(lc['t'])} & & & \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
gem_tabel("lande_usd", lines)

# Euro vs dollar pr. land
b_eur = beta(agg.assign(x=agg["dEURUSD"]), "x")
N["beta_eurusd"] = b_eur
lines = [r"\begin{tabular}{lcccc}", r"\toprule",
         r" & A: USD, uafd. & B: EUR, uafd. & C: EUR, USD-hedged & D: EUR, fuldt afd. \\",
         r"\midrule"]
for c in orden + ["AGG"]:
    r = next(x for x in rows if x["valuta"] == c)
    if c == "AGG":
        lines.append(r"\midrule")
    navn = "Vægtet aggregat" if c == "AGG" else NAVN[c]
    cells = [r[k] for k in ["A_USD_uafd", "B_EUR_uafd", "C_EUR_USDhedged", "D_EUR_afd"]]
    lines.append(navn + " & " + " & ".join(f(x["b"], sig=x["t"]) for x in cells) + r" \\")
    lines.append(" & " + " & ".join(ft(x["t"]) for x in cells) + r" \\")
lines += [r"\bottomrule", r"\end{tabular}"]
gem_tabel("lande_investor", lines)

N["lande"] = {r["valuta"]: {k: {kk: round(float(vv), 3) for kk, vv in v.items()}
                            for k, v in r.items() if isinstance(v, dict)} for r in rows}

# ---------------------------------------------------------------------------
# 3. Aggregat: fire investorer, to dollarindeks, ETF
# ---------------------------------------------------------------------------
inv = [("A_USD_uafd", "A: USD, uafdækket"), ("B_EUR_uafd", "B: EUR, uafdækket"),
       ("C_EUR_USDhedged", "C: EUR, USD-hedged andelsklasse"), ("D_EUR_afd", "D: EUR, fuldt afdækket")]
lines = [r"\begin{tabular}{lcccc}", r"\toprule",
         r" & \multicolumn{2}{c}{AFE-indeks (uden EM)} & \multicolumn{2}{c}{Bredt indeks (inkl. EM)} \\",
         r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}",
         r"Investor & $\beta$ & $R^2$ & $\beta$ & $R^2$ \\", r"\midrule"]
N["agg"] = {}
for k, navn in inv:
    x1, x2 = beta(agg, k), beta(agg_b, k)
    N["agg"][k] = {"afe": x1, "broad": x2}
    lines.append(f"{navn} & {f(x1['b'], sig=x1['t'])} & {f(x1['r2'])} & {f(x2['b'], sig=x2['t'])} & {f(x2['r2'])} \\\\")
    lines.append(f" & {ft(x1['t'])} & & {ft(x2['t'])} & \\\\")
lines.append(r"\midrule")
for k, navn in [("EMLC_USD", "EMLC-ETF, USD-investor"), ("EMLC_EUR", "EMLC-ETF, EUR-investor")]:
    x1 = beta(etf, k, "dUSD")
    x2 = beta(etf, k, "dUSD_broad")
    N["agg"][k] = {"afe": x1, "broad": x2}
    lines.append(f"{navn} & {f(x1['b'], sig=x1['t'])} & {f(x1['r2'])} & {f(x2['b'], sig=x2['t'])} & {f(x2['r2'])} \\\\")
    lines.append(f" & {ft(x1['t'])} & & {ft(x2['t'])} & \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
gem_tabel("aggregat", lines)
N["n_emlc"] = int(etf["EMLC_USD"].notna().sum())

# ---------------------------------------------------------------------------
# 4. Robusthed: delperioder, asymmetri, kontroller
# ---------------------------------------------------------------------------
def delperiode(df, k, a, b):
    d = df.loc[a:b]
    return beta(d, k)


rob = {}
lines = [r"\begin{tabular}{lcccc}", r"\toprule",
         r" & \multicolumn{2}{c}{A: USD, uafdækket} & \multicolumn{2}{c}{B: EUR, uafdækket} \\",
         r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}",
         r" & $\beta$ & $t$ & $\beta$ & $t$ \\", r"\midrule"]
spec = [("Hele perioden", None), ("2006--2014", ("2006-01-01", UNDERPERIODE)),
        ("2015--2026", ("2015-01-01", "2030-01-01")), ("Uden 2020", "ex2020")]
for navn, s in spec:
    vals = []
    for k in ["A_USD_uafd", "B_EUR_uafd"]:
        if s is None:
            x = beta(agg, k)
        elif s == "ex2020":
            x = beta(agg[agg.index.year != 2020], k)
        else:
            x = delperiode(agg, k, *s)
        vals.append(x)
    rob[navn] = vals
    lines.append(f"{navn} & {f(vals[0]['b'], sig=vals[0]['t'])} & {ft(vals[0]['t'])} & "
                 f"{f(vals[1]['b'], sig=vals[1]['t'])} & {ft(vals[1]['t'])} \\\\")

# asymmetri
lines.append(r"\midrule")
asym = {}
for k in ["A_USD_uafd", "B_EUR_uafd"]:
    d = agg[[k, "dUSD"]].dropna()
    X = np.column_stack([np.maximum(d["dUSD"], 0), np.minimum(d["dUSD"], 0)])
    b, V, r2, n = ols(d[k].values, X)
    asym[k] = dict(op=b[1], t_op=b[1] / np.sqrt(V[1, 1]), ned=b[2], t_ned=b[2] / np.sqrt(V[2, 2]),
                   p=wald_lige(b, V, 1, 2), n_op=int((d["dUSD"] > 0).sum()), n_ned=int((d["dUSD"] <= 0).sum()))
lines.append(f"$\\beta^{{op}}$ (stigende dollar) & {f(asym['A_USD_uafd']['op'], sig=asym['A_USD_uafd']['t_op'])} & "
             f"{ft(asym['A_USD_uafd']['t_op'])} & {f(asym['B_EUR_uafd']['op'], sig=asym['B_EUR_uafd']['t_op'])} & "
             f"{ft(asym['B_EUR_uafd']['t_op'])} \\\\")
lines.append(f"$\\beta^{{ned}}$ (faldende dollar) & {f(asym['A_USD_uafd']['ned'], sig=asym['A_USD_uafd']['t_ned'])} & "
             f"{ft(asym['A_USD_uafd']['t_ned'])} & {f(asym['B_EUR_uafd']['ned'], sig=asym['B_EUR_uafd']['t_ned'])} & "
             f"{ft(asym['B_EUR_uafd']['t_ned'])} \\\\")
lines.append(f"$p$-værdi, $\\beta^{{op}}=\\beta^{{ned}}$ & {f(asym['A_USD_uafd']['p'])} & & {f(asym['B_EUR_uafd']['p'])} & \\\\")

# kontroller
lines.append(r"\midrule")
ctrl = pd.DataFrame({"dVIX": raa["VIX"].diff(), "dUS10Y": raa["US10Y"].diff(),
                     "dOlie": 100 * np.log(raa["BRENT"] / raa["BRENT"].shift(1))}).reindex(agg.index)
kontrol = {}
for k in ["A_USD_uafd", "B_EUR_uafd"]:
    d = pd.concat([agg[[k, "dUSD"]], ctrl], axis=1).dropna()
    b, V, r2, n = ols(d[k].values, d[["dUSD", "dVIX", "dUS10Y", "dOlie"]].values)
    se = np.sqrt(np.diag(V))
    kontrol[k] = dict(zip(["c", "dUSD", "dVIX", "dUS10Y", "dOlie"], b), t=dict(zip(["c", "dUSD", "dVIX", "dUS10Y", "dOlie"], b / se)), r2=r2)
for var, navn in [("dUSD", r"$\Delta$USD, med kontroller"), ("dVIX", r"$\Delta$VIX"),
                  ("dUS10Y", r"$\Delta y^{US}_{10}$"), ("dOlie", r"$\Delta$Olie")]:
    a, bb = kontrol["A_USD_uafd"], kontrol["B_EUR_uafd"]
    lines.append(f"{navn} & {f(a[var], sig=a['t'][var])} & {ft(a['t'][var])} & {f(bb[var], sig=bb['t'][var])} & {ft(bb['t'][var])} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
gem_tabel("robusthed", lines)
N["rob"] = {k: [{kk: float(vv) for kk, vv in x.items()} for x in v] for k, v in rob.items()}
N["asym"] = asym
N["kontrol"] = {k: {kk: (float(vv) if not isinstance(vv, dict) else {a: float(b) for a, b in vv.items()})
                    for kk, vv in v.items()} for k, v in kontrol.items()}

# ---------------------------------------------------------------------------
# 5. Figurer: rullende betaer og landebetaer
# ---------------------------------------------------------------------------
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
FARVE = {"A": "#1f4e9c", "B": "#c0504d", "D": "#4f8f6a"}

roll = {}
for k in ["A_USD_uafd", "B_EUR_uafd", "D_EUR_afd"]:
    d = agg[[k, "dUSD"]].dropna()
    out = {}
    for i in range(36, len(d) + 1):
        w = d.iloc[i - 36:i]
        out[w.index[-1]] = np.cov(w[k], w["dUSD"])[0, 1] / w["dUSD"].var()
    roll[k] = pd.Series(out)
fig, ax = plt.subplots(figsize=(6.2, 3.0))
ax.plot(roll["A_USD_uafd"], color=FARVE["A"], label="A: USD-investor, uafdækket")
ax.plot(roll["B_EUR_uafd"], color=FARVE["B"], label="B: EUR-investor, uafdækket")
ax.plot(roll["D_EUR_afd"], color=FARVE["D"], ls="--", label="D: EUR-investor, fuldt afdækket")
ax.axhline(0, color="grey", lw=0.6)
ax.set_ylabel("Dollarbeta (36 mdr. rullende)")
ax.set_title("Hvor meget falder EM-obligationer, når dollaren stiger 1 %?", fontsize=9)
ax.legend(frameon=False, fontsize=7.5, loc="lower left")
fig.tight_layout()
fig.savefig(RES / "fig_rullende.pdf")
fig.savefig(RES / "fig_rullende.png", dpi=150)
plt.close(fig)
N["rull_seneste"] = {k: float(v.iloc[-1]) for k, v in roll.items()}
N["rull_range"] = {k: [float(v.min()), float(v.max())] for k, v in roll.items()}

fig, ax = plt.subplots(figsize=(6.2, 3.6))
o = orden[::-1]
y = np.arange(len(o))
ax.barh(y + 0.2, [next(r for r in rows if r["valuta"] == c)["A_USD_uafd"]["b"] for c in o], 0.38,
        color=FARVE["A"], label="A: USD-investor")
ax.barh(y - 0.2, [next(r for r in rows if r["valuta"] == c)["B_EUR_uafd"]["b"] for c in o], 0.38,
        color=FARVE["B"], label="B: EUR-investor")
ax.set_yticks(y)
ax.set_yticklabels([NAVN[c] for c in o])
ax.axvline(0, color="grey", lw=0.6)
ax.set_xlabel("Dollarbeta, uafdækket afkast")
ax.legend(frameon=False, fontsize=7.5, loc="upper right")
fig.tight_layout()
fig.savefig(RES / "fig_lande.pdf")
fig.savefig(RES / "fig_lande.png", dpi=150)
plt.close(fig)

# ---------------------------------------------------------------------------
# 6. Prædiktorer
# ---------------------------------------------------------------------------
idx = agg.index
Wd = W.reindex(idx).fillna(0.0)


def vaegtet(df):
    """Vægtet gennemsnit over lande med data (vægte renormaliseres)."""
    df = df.reindex(idx)
    m = df.notna()
    w = Wd[df.columns].where(m, 0.0)
    return (df.fillna(0) * w).sum(axis=1) / w.sum(axis=1).replace(0, np.nan)


pol = pd.DataFrame({c: raa[f"POL_{c}"] for c in LANDE}).shift(1)   # 1 mdr. publiceringslag
lreer = pd.DataFrame({c: np.log(raa[f"REER_{c}"]) for c in LANDE})
val_c = -(lreer - lreer.expanding(36).mean()).shift(1) * 100      # billig valuta = positiv
fx_c = panel.pivot(index="dato", columns="valuta", values="fx_USD")
mom_c = fx_c.rolling(12).sum().shift(1)                             # 12-1 momentum

pred = pd.DataFrame(index=idx)
pred["carry_USD"] = vaegtet(pol.sub(raa["POL_US"].shift(1), axis=0))
pred["carry_EUR"] = vaegtet(pol.sub(raa["POL_EA"].shift(1), axis=0))
afe = raa["USD_AFE"]
pred["dmom"] = (100 * np.log(afe / afe.shift(12))).reindex(idx)
pred["fxmom_USD"] = agg["fx_USD"].rolling(12).sum()
pred["fxmom_EUR"] = agg["fx_EUR"].rolling(12).sum()
pred["value"] = vaegtet(val_c)
pred["vix"] = raa["VIX"].reindex(idx)

# mål: overskudsafkast næste måned
maal = pd.DataFrame(index=idx)
maal["USD"] = agg["A_USD_uafd"] - i_us.reindex(idx)
maal["EUR"] = agg["B_EUR_uafd"] - i_ea.reindex(idx)
maal["EMLC_USD"] = etf["EMLC_USD"] - i_us.reindex(idx)
maal["EMLC_EUR"] = etf["EMLC_EUR"] - i_ea.reindex(idx)
maal["FXX_EUR"] = agg["B_EUR_uafd"] - agg["D_EUR_afd"]        # valutaoverskudsafkast for EUR-investor
maal["FXX_USD"] = agg["A_USD_uafd"] - agg["H_USD_afd"]


def X_for(inv, navne):
    m = {"carry": f"carry_{'EUR' if inv.endswith('EUR') else 'USD'}", "dmom": "dmom",
         "fxmom": f"fxmom_{'EUR' if inv.endswith('EUR') else 'USD'}", "value": "value", "vix": "vix"}
    return pred[[m[n] for n in navne]].set_axis(navne, axis=1)


# ---------------------------------------------------------------------------
# 7. Walk-forward prognoser
# ---------------------------------------------------------------------------
def walk_forward(y, X, fortegn=None, min_n=MIN_TRAEN):
    """Prognose for y_{t+1} givet X_t, estimeret på data til og med t."""
    d = pd.concat([y.shift(-1).rename("y1"), X], axis=1)
    d = d[X.notna().all(axis=1)]
    fc, bm, real = {}, {}, {}
    datoer = d.index
    for i in range(min_n, len(datoer) - 1):
        traen = d.iloc[:i].dropna()       # y1 for sidste træningsobs er kendt på tidspunkt t
        if len(traen) < min_n:
            continue
        t = datoer[i]
        x_t = d.iloc[i][X.columns].values.astype(float)
        b, _, _, _ = ols(traen["y1"].values, traen[X.columns].values, lags=0)
        if fortegn is not None:
            for j, n in enumerate(X.columns):
                if np.sign(b[j + 1]) != fortegn[n]:
                    b[j + 1] = 0.0
                    # reestimér konstanten, så den svarer til det betingede gennemsnit
            if any(b[1:] == 0):
                b[0] = traen["y1"].mean() - (traen[X.columns].values.mean(axis=0) * b[1:]).sum()
        nxt = t + pd.offsets.MonthEnd(1)
        if pd.isna(d["y1"].iloc[i]):
            continue
        fc[nxt] = b[0] + x_t @ b[1:]
        bm[nxt] = traen["y1"].mean()
        real[nxt] = d["y1"].iloc[i]
    out = pd.DataFrame({"fc": fc, "bm": bm, "y": real}).dropna()
    return out


def evaluer(o, lags=0):
    from scipy import stats
    e_m = o["y"] - o["fc"]
    e_b = o["y"] - o["bm"]
    r2 = 1 - (e_m ** 2).sum() / (e_b ** 2).sum()
    fadj = e_b ** 2 - (e_m ** 2 - (o["bm"] - o["fc"]) ** 2)
    b, V, _, _ = ols(fadj.values, np.zeros((len(fadj), 0)), lags=lags)
    cw_t = b[0] / np.sqrt(V[0, 0]) if V[0, 0] > 1e-12 else np.nan
    p = 1 - stats.norm.cdf(cw_t)
    hit = float((np.sign(o["fc"]) == np.sign(o["y"])).mean())   # rammer fortegnet på overskudsafkastet
    return dict(r2=100 * r2, cw=cw_t, p=p, n=len(o), hit=hit)


def timing(o, y_hist):
    """Mean-variance investor (gamma=3) med vægt i [0, 1.5]; varians fra 60 mdr. rullende."""
    var = (y_hist / 100).rolling(60).var().shift(1).reindex(o.index)
    w_m = ((o["fc"] / 100) / (GAMMA * var)).clip(0, MAX_VAEGT)
    w_b = ((o["bm"] / 100) / (GAMMA * var)).clip(0, MAX_VAEGT)
    r_m, r_b = w_m * o["y"] / 100, w_b * o["y"] / 100
    cer = lambda r: 12 * (r.mean() - GAMMA / 2 * r.var())
    sr = lambda r: np.sqrt(12) * r.mean() / r.std()
    return dict(dcer=100 * (cer(r_m) - cer(r_b)), sr_m=sr(r_m), sr_b=sr(r_b),
                sr_bh=sr(o["y"] / 100), vaegt=float(w_m.mean()))


modeller = {f"U_{p}": [p] for p in PRAEDIKTORER}
modeller["Hovedmodel"] = HOVEDMODEL
progn = {}
for inv in ["USD", "EUR", "EMLC_USD", "EMLC_EUR"]:
    progn[inv] = {}
    for mn, navne in modeller.items():
        X = X_for(inv, navne)
        o = walk_forward(maal[inv], X)
        o_r = walk_forward(maal[inv], X, fortegn=FORTEGN)
        progn[inv][mn] = {"fri": o, "begr": o_r}
    # kombination: gennemsnit af univariate (begrænsede)
    us = [progn[inv][f"U_{p}"]["begr"]["fc"] for p in PRAEDIKTORER]
    base = progn[inv][f"U_{PRAEDIKTORER[0]}"]["begr"]
    comb = pd.concat(us, axis=1, sort=True).dropna().mean(axis=1)
    o = base.loc[comb.index].copy()
    o["fc"] = comb
    progn[inv]["Kombination"] = {"fri": o, "begr": o}


def periode(o, del_):
    if del_ == "alle":
        return o
    if del_ == "foer":
        return o.loc[:SPLIT]
    return o.loc[pd.Timestamp(SPLIT) + pd.Timedelta(days=1):]


res_p = {}
for inv in progn:
    res_p[inv] = {}
    for mn in progn[inv]:
        res_p[inv][mn] = {}
        for v in ["fri", "begr"]:
            o = progn[inv][mn][v]
            res_p[inv][mn][v] = {d: evaluer(periode(o, d)) for d in ["alle", "foer", "efter"]}
        res_p[inv][mn]["timing"] = timing(progn[inv][mn]["begr"], maal[inv])

N["oos_start"] = str(progn["USD"]["Hovedmodel"]["fri"].index.min().date())
N["oos_slut"] = str(progn["USD"]["Hovedmodel"]["fri"].index.max().date())
N["oos_start_emlc"] = str(progn["EMLC_USD"]["Hovedmodel"]["fri"].index.min().date())
N["prognoser"] = res_p


def prog_tabel(invs, navn_fil, overskrift):
    lines = [r"\begin{tabular}{l" + "rrrr" * len(invs) + "}", r"\toprule"]
    hdr = " & ".join(rf"\multicolumn{{4}}{{c}}{{{overskrift[i]}}}" for i in invs)
    lines.append(" & " + hdr + r" \\")
    cm = "".join(rf"\cmidrule(lr){{{2 + 4 * j}-{5 + 4 * j}}}" for j in range(len(invs)))
    lines.append(cm)
    lines.append("Model" + r" & $R^2_{OOS}$ & CW $p$ & Hit & $\Delta$CER" * len(invs) + r" \\")
    lines.append(r"\midrule")
    for mn in [f"U_{p}" for p in PRAEDIKTORER] + ["Hovedmodel", "Kombination"]:
        navn = NAVN_PRAED[mn[2:]] if mn.startswith("U_") else ("Hovedmodel (carry, dollar-mom., VIX)" if mn == "Hovedmodel" else "Kombination (gns. af univariate)")
        celler = []
        for inv in invs:
            e = res_p[inv][mn]["begr"]["alle"]
            celler += [f(e["r2"]), f(e["p"]), f(100 * e["hit"], 0), f(res_p[inv][mn]["timing"]["dcer"])]
        if mn == "Hovedmodel":
            lines.append(r"\midrule")
        lines.append(navn + " & " + " & ".join(celler) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    gem_tabel(navn_fil, lines)


prog_tabel(["USD", "EUR"], "prognose", {"USD": "A: USD-investor", "EUR": "B: EUR-investor"})
prog_tabel(["EMLC_USD", "EMLC_EUR"], "prognose_emlc", {"EMLC_USD": "EMLC, USD-investor", "EMLC_EUR": "EMLC, EUR-investor"})

# delperioder for hovedmodel og kombination (ubegrænset vs begrænset)
lines = [r"\begin{tabular}{llrrrrrr}", r"\toprule",
         r" & & \multicolumn{2}{c}{Hele OOS} & \multicolumn{2}{c}{Til og med 2021} & \multicolumn{2}{c}{2022--2026 (holdout)} \\",
         r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}\cmidrule(lr){7-8}",
         r"Investor & Model & $R^2_{OOS}$ & CW $p$ & $R^2_{OOS}$ & CW $p$ & $R^2_{OOS}$ & CW $p$ \\", r"\midrule"]
for inv, inavn in [("USD", "A: USD"), ("EUR", "B: EUR")]:
    for mn, v, mnavn in [("Hovedmodel", "fri", "Hovedmodel, fri"), ("Hovedmodel", "begr", "Hovedmodel, fortegnsbegr."),
                         ("Kombination", "begr", "Kombination")]:
        e = res_p[inv][mn][v]
        lines.append(f"{inavn} & {mnavn} & " + " & ".join(f"{f(e[d]['r2'])} & {f(e[d]['p'])}" for d in ["alle", "foer", "efter"]) + r" \\")
    if inv == "USD":
        lines.append(r"\midrule")
lines += [r"\bottomrule", r"\end{tabular}"]
gem_tabel("prognose_perioder", lines)

# figur: kumuleret forskel i kvadratfejl
fig, ax = plt.subplots(figsize=(6.2, 3.4))
for inv, farve, navn in [("USD", FARVE["A"], "A: USD-investor"), ("EUR", FARVE["B"], "B: EUR-investor")]:
    o = progn[inv]["Hovedmodel"]["begr"]
    ax.plot(((o["y"] - o["bm"]) ** 2 - (o["y"] - o["fc"]) ** 2).cumsum(), color=farve, label=navn + ", hovedmodel")
    o = progn[inv]["Kombination"]["begr"]
    ax.plot(((o["y"] - o["bm"]) ** 2 - (o["y"] - o["fc"]) ** 2).cumsum(), color=farve, ls="--", label=navn + ", kombination")
ax.axhline(0, color="grey", lw=0.6)
ax.axvline(pd.Timestamp(SPLIT), color="grey", lw=0.6, ls=":")
ax.set_ylabel("Kumuleret SSE-forskel")
ax.legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
fig.tight_layout()
fig.savefig(RES / "fig_oos.pdf")
fig.savefig(RES / "fig_oos.png", dpi=150)
plt.close(fig)

# ---------------------------------------------------------------------------
# 8. Tværsnit: landeallokering
# ---------------------------------------------------------------------------
ret_c = panel.pivot(index="dato", columns="valuta", values="A_USD_uafd")
ret_ce = panel.pivot(index="dato", columns="valuta", values="B_EUR_uafd")
carry_c = pol.sub(raa["POL_US"].shift(1), axis=0).reindex(ret_c.index)
sig = {"carry": carry_c, "mom": mom_c.reindex(ret_c.index), "value": val_c.reindex(ret_c.index)}
z = {}
for k, s in sig.items():
    s = s.where(ret_c.notna())
    z[k] = s.sub(s.mean(axis=1), axis=0).div(s.std(axis=1), axis=0)
z["komposit"] = pd.concat([z["carry"], z["mom"], z["value"]]).groupby(level=0).mean()

tv = {}
lines = [r"\begin{tabular}{lrrrrrr}", r"\toprule",
         r" & \multicolumn{3}{c}{Long--short (top 4 -- bund 4)} & \multicolumn{3}{c}{Top 4 -- ligevægtet (aktivt afkast)} \\",
         r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}",
         r"Signal & Afkast p.a. & $t$ & Sharpe & Afkast p.a. & $t$ & IR \\", r"\midrule"]
for k, navn in [("carry", "Carry"), ("mom", "Momentum (12--1)"), ("value", "Value (REER)"), ("komposit", "Komposit")]:
    ls, akt, akt_e = {}, {}, {}
    for t in ret_c.index[:-1]:
        s = z[k].loc[t].dropna()
        nxt = ret_c.index[ret_c.index.get_loc(t) + 1]
        r1 = ret_c.loc[nxt]
        s = s[r1.reindex(s.index).notna()]
        if len(s) < 8:
            continue
        rk = s.sort_values()
        top, bund = rk.index[-4:], rk.index[:4]
        ls[nxt] = r1[top].mean() - r1[bund].mean()
        akt[nxt] = r1[top].mean() - r1[s.index].mean()
        re1 = ret_ce.loc[nxt]
        akt_e[nxt] = re1[top].mean() - re1[s.index].mean()
    ls, akt = pd.Series(ls), pd.Series(akt)
    bl, Vl, _, _ = ols(ls.values, np.zeros((len(ls), 0)))
    ba, Va, _, _ = ols(akt.values, np.zeros((len(akt), 0)))
    tv[k] = dict(ls=12 * ls.mean(), ls_t=bl[0] / np.sqrt(Vl[0, 0]), ls_sr=np.sqrt(12) * ls.mean() / ls.std(),
                 akt=12 * akt.mean(), akt_t=ba[0] / np.sqrt(Va[0, 0]), ir=np.sqrt(12) * akt.mean() / akt.std(),
                 n=len(ls), start=str(ls.index.min().date()),
                 ls_foer=12 * ls.loc[:SPLIT].mean(), ls_efter=12 * ls.loc[SPLIT:].mean())
    lines.append(f"{navn} & {f(tv[k]['ls'])}\\,\\% & {ft(tv[k]['ls_t'])} & {f(tv[k]['ls_sr'])} & "
                 f"{f(tv[k]['akt'])}\\,\\% & {ft(tv[k]['akt_t'])} & {f(tv[k]['ir'])} \\\\")
    if k == "komposit":
        cum_ls = ls.cumsum()
lines += [r"\bottomrule", r"\end{tabular}"]
gem_tabel("tvaersnit", lines)
N["tvaersnit"] = tv

# 8b. Kontrafaktisk benchmark: hvad ville investoren have fået uden strategien?
#     Univers = lande med positiv EMLC-vægt på tidspunkt t (investerbart, ingen look-ahead).
bm_res = {}
bm_ser = {}
for k in ["carry", "komposit"]:
    rows_s = {}
    for t in ret_c.index[:-1]:
        nxt = ret_c.index[ret_c.index.get_loc(t) + 1]
        if t not in Wd.index:
            continue
        w_t = Wd.loc[t]
        univ = [c for c in LANDE if w_t.get(c, 0) > 0]
        s = z[k].loc[t].reindex(univ).dropna()
        r1, re1 = ret_c.loc[nxt], ret_ce.loc[nxt]
        s = s[r1.reindex(s.index).notna() & re1.reindex(s.index).notna()]
        if len(s) < 8:
            continue
        top = s.sort_values().index[-4:]
        ww = w_t[s.index] / w_t[s.index].sum()
        rows_s[nxt] = dict(strat_usd=r1[top].mean(), ew_usd=r1[s.index].mean(), emlc_usd=(r1[s.index] * ww).sum(),
                           strat_eur=re1[top].mean(), ew_eur=re1[s.index].mean(), emlc_eur=(re1[s.index] * ww).sum())
    d = pd.DataFrame(rows_s).T
    bm_ser[k] = d
    out = {"n": len(d), "start": str(d.index.min().date()), "slut": str(d.index.max().date())}
    for col in d.columns:
        out[col] = dict(mu=12 * d[col].mean(), vol=np.sqrt(12) * d[col].std(), sr=np.sqrt(12) * d[col].mean() / d[col].std())
    for inv in ["usd", "eur"]:
        for bm in ["ew", "emlc"]:
            diff = d[f"strat_{inv}"] - d[f"{bm}_{inv}"]
            b, V, _, _ = ols(diff.values, np.zeros((len(diff), 0)))
            out[f"akt_{inv}_{bm}"] = dict(mu=12 * diff.mean(), t=b[0] / np.sqrt(V[0, 0]),
                                          ir=np.sqrt(12) * diff.mean() / diff.std(), te=np.sqrt(12) * diff.std(),
                                          hit=float((diff > 0).mean()))
    bm_res[k] = out

lines = [r"\begin{tabular}{lrrrrrr}", r"\toprule",
         r" & \multicolumn{3}{c}{A: USD-investor} & \multicolumn{3}{c}{B: EUR-investor} \\",
         r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}",
         r" & Afkast p.a. & Vol. p.a. & Sharpe & Afkast p.a. & Vol. p.a. & Sharpe \\", r"\midrule"]
for k, navn in [("carry", "Carry"), ("komposit", "Komposit")]:
    o = bm_res[k]
    lines.append(rf"\multicolumn{{7}}{{l}}{{\textit{{{navn}-strategi}}}} \\")
    for col, cn in [("strat", "Strategi: top 4, ligevægtet"), ("emlc", "Benchmark: EMLC-vægtet"), ("ew", "Benchmark: ligevægtet")]:
        u, e = o[f"{col}_usd"], o[f"{col}_eur"]
        lines.append(f"\\quad {cn} & {f(u['mu'])}\\,\\% & {f(u['vol'])}\\,\\% & {f(u['sr'])} & "
                     f"{f(e['mu'])}\\,\\% & {f(e['vol'])}\\,\\% & {f(e['sr'])} \\\\")
    for bm, bn in [("emlc", "EMLC-vægtet"), ("ew", "ligevægtet")]:
        u, e = o[f"akt_usd_{bm}"], o[f"akt_eur_{bm}"]
        lines.append(f"\\quad Merafkast mod {bn} & {f(u['mu'], sig=u['t'])}\\,\\% & {ft(u['t'])} & IR {f(u['ir'])} & "
                     f"{f(e['mu'], sig=e['t'])}\\,\\% & {ft(e['t'])} & IR {f(e['ir'])} \\\\")
    if k == "carry":
        lines.append(r"\midrule")
lines += [r"\bottomrule", r"\end{tabular}"]
gem_tabel("benchmark", lines)
N["benchmark"] = bm_res

# ---------------------------------------------------------------------------
# 9. Afdækningsbeslutning
# ---------------------------------------------------------------------------
afd = {}
cum = {}
for inv, uafd, afdk, navn in [("EUR", "B_EUR_uafd", "D_EUR_afd", "EUR"), ("USD", "A_USD_uafd", "H_USD_afd", "USD")]:
    o = walk_forward(maal[f"FXX_{inv}"], X_for(inv, HOVEDMODEL), fortegn=FORTEGN)
    r_u = agg[uafd].shift(-1).reindex(o.index)
    r_u = agg[uafd].reindex(o.index)
    r_a = agg[afdk].reindex(o.index)
    dyn = np.where(o["fc"] > 0, r_u, r_a)
    dyn = pd.Series(dyn, index=o.index)
    sr = lambda r: np.sqrt(12) * r.mean() / r.std()
    afd[inv] = dict(sr_u=sr(r_u), sr_a=sr(r_a), sr_d=sr(dyn), mu_u=12 * r_u.mean(), mu_a=12 * r_a.mean(),
                    mu_d=12 * dyn.mean(), vol_u=np.sqrt(12) * r_u.std(), vol_a=np.sqrt(12) * r_a.std(),
                    vol_d=np.sqrt(12) * dyn.std(), andel_uafd=float((o["fc"] > 0).mean()),
                    hit=float((np.sign(o["fc"]) == np.sign(o["y"])).mean()),
                    beta_d=beta(pd.DataFrame({"r": dyn, "dUSD": agg["dUSD"].reindex(o.index)}), "r")["b"],
                    n=len(o), **{f"oos_{k}": v for k, v in evaluer(o).items()})
    cum[inv] = pd.DataFrame({"uafd": r_u.cumsum(), "afd": r_a.cumsum(), "dyn": dyn.cumsum()})
lines = [r"\begin{tabular}{lrrrrrr}", r"\toprule",
         r" & \multicolumn{3}{c}{EUR-investor} & \multicolumn{3}{c}{USD-investor} \\",
         r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}",
         r"Strategi & Afkast p.a. & Vol. p.a. & Sharpe & Afkast p.a. & Vol. p.a. & Sharpe \\", r"\midrule"]
for nk, navn in [("u", "Altid uafdækket"), ("a", "Altid afdækket"), ("d", "Dynamisk afdækning")]:
    e, u = afd["EUR"], afd["USD"]
    lines.append(f"{navn} & {f(e['mu_' + nk])}\\,\\% & {f(e['vol_' + nk])}\\,\\% & {f(e['sr_' + nk])} & "
                 f"{f(u['mu_' + nk])}\\,\\% & {f(u['vol_' + nk])}\\,\\% & {f(u['sr_' + nk])} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
gem_tabel("afdaekning", lines)
N["afdaekning"] = afd

fig, axs = plt.subplots(1, 2, figsize=(6.4, 2.8))
c = cum["EUR"]
axs[0].plot(c["uafd"], color=FARVE["B"], label="Altid uafdækket")
axs[0].plot(c["afd"], color=FARVE["D"], label="Altid afdækket")
axs[0].plot(c["dyn"], color="black", lw=1.2, label="Dynamisk")
axs[0].set_title("EUR-investor: afdækning", fontsize=8.5)
axs[0].set_ylabel("Kumuleret log-afkast, %")
axs[0].legend(frameon=False, fontsize=6.5)
axs[1].plot(cum_ls, color=FARVE["A"])
axs[1].axhline(0, color="grey", lw=0.6)
axs[1].set_title("Landeallokering: komposit long–short", fontsize=8.5)
for a in axs:
    a.tick_params(labelsize=7)
fig.tight_layout()
fig.savefig(RES / "fig_strategier.pdf")
fig.savefig(RES / "fig_strategier.png", dpi=150)
plt.close(fig)

# ---------------------------------------------------------------------------
# 10. Validering og deskriptivt
# ---------------------------------------------------------------------------
d = pd.concat([agg["A_USD_uafd"], etf["EMLC_USD"]], axis=1).dropna()
b, V, r2, n = ols(d["EMLC_USD"].values, d["A_USD_uafd"].values)
N["validering"] = dict(korr=float(d.corr().iloc[0, 1]), haeldning=float(b[1]),
                       te=float((d["EMLC_USD"] - d["A_USD_uafd"]).std() * np.sqrt(12)), n=int(n),
                       start=str(d.index.min().date()))
Wq = pd.read_csv(hg.MANUELT / "vaegte_historisk.csv")
N["vaegte"] = dict(n_tidspunkter=int(Wq["dato"].nunique()), start=Wq["dato"].min(), slut=Wq["dato"].max(),
                   n_nport=int(Wq[Wq["kilde"] == "SEC N-PORT"]["dato"].nunique()),
                   n_nq=int(Wq[Wq["kilde"] != "SEC N-PORT"]["dato"].nunique()))
Wp = Wq.pivot(index="dato", columns="valuta", values="vaegt")
N["vaegte"]["daekning_min"] = float(Wp.sum(axis=1).min())
N["vaegte"]["daekning_max"] = float(Wp.sum(axis=1).max())
N["vaegte"]["daekning_seneste"] = float(Wp.sum(axis=1).iloc[-1])

desk = agg[["A_USD_uafd", "B_EUR_uafd", "D_EUR_afd", "dUSD"]].dropna()
N["desk"] = {k: dict(mu=float(12 * desk[k].mean()), sd=float(np.sqrt(12) * desk[k].std())) for k in desk}


def til_json(x):
    if isinstance(x, dict):
        return {str(k): til_json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [til_json(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return float(x)
    return x


(RES / "noegletal.json").write_text(json.dumps(til_json(N), indent=1, ensure_ascii=False), encoding="utf-8")
print("Færdig. Resultater i", RES.resolve())
