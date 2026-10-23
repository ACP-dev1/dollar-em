"""Figurer og en markdown-rapport med resultater og hypotesedomme."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis import ols_hac

INK, MUTED, GRID = "#1f2937", "#6b7280", "#e5e7eb"
C1, C2, C3 = "#1d4ed8", "#c2410c", "#0f766e"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
    }
)


def fig_rolling(roll: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(roll.index, roll["r_emlc"], color=C1, lw=1.8, label="EM lokalvaluta-obl. (EMLC)")
    ax.plot(roll.index, roll["r_cew"], color=C2, lw=1.4, label="Valutakomponent (CEW)")
    ax.plot(roll.index, roll["r_lokal"], color=C3, lw=1.4, ls="--", label="Lokal rentekomponent")
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_ylabel("Dollarbeta (36 mdr. rullende)")
    ax.set_title("Hvor meget falder EM-aktiver, når dollaren stiger 1 %?", loc="left", color=INK, pad=28)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, fontsize=9)
    fig.savefig(path)
    plt.close(fig)


def fig_asym(df: pd.DataFrame, asym: pd.DataFrame, path: Path) -> None:
    x, y = df["d_dollar"], df["r_emlc"]
    a = asym.loc["EM lokalvaluta-obl. (EMLC)"]
    alpha = ols_hac(
        y,
        pd.DataFrame({"op": x.clip(lower=0), "ned": x.clip(upper=0)}),
    ).params["const"]
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    ax.scatter(x, y, s=14, color=C1, alpha=0.45, edgecolor="none")
    xs_up = np.linspace(0, x.max(), 50)
    xs_dn = np.linspace(x.min(), 0, 50)
    ax.plot(xs_up, alpha + a["beta_op"] * xs_up, color=C2, lw=2, label=f"Dollar op: β = {a['beta_op']:.2f}")
    ax.plot(xs_dn, alpha + a["beta_ned"] * xs_dn, color=C3, lw=2, label=f"Dollar ned: β = {a['beta_ned']:.2f}")
    last = df.index[-1]
    ax.annotate(
        last.strftime("%Y-%m"),
        (x.iloc[-1], y.iloc[-1]),
        xytext=(8, 8),
        textcoords="offset points",
        color=INK,
        fontsize=9,
        arrowprops={"arrowstyle": "-", "color": MUTED},
    )
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.set_xlabel("Ændring i dollarindeks, % (måned)")
    ax.set_ylabel("Afkast EMLC, % (måned)")
    ax.set_title("Asymmetri: dollarstyrke vs. dollarsvaghed", loc="left", color=INK)
    ax.legend(frameon=False, loc="upper right")
    fig.savefig(path)
    plt.close(fig)


def _md(df: pd.DataFrame, fmt: str = "{:.2f}") -> str:
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: fmt.format(v))
    return d.to_markdown()


def _verdict(ok: bool) -> str:
    return "**Understøttes**" if ok else "**Understøttes ikke**"


def write_report(df: pd.DataFrame, res: dict, out: Path) -> Path:
    b, bc, dk, asym, oos, ep = (res[k] for k in ["betas", "betas_ctrl", "dekomp", "asym", "oos", "episode"])
    start, end, n = res["sample"]
    em = "EM lokalvaluta-obl. (EMLC)"

    # H2: test af forskellen direkte
    diff = ols_hac(df["r_emlc"] - df["r_emb"], df[["d_dollar"]])
    h1_rows = b.loc[[em, "EM-valutakurv (CEW)", "EM hård valuta (EMB)"]]
    h1 = bool(((h1_rows["beta"] < 0) & (h1_rows["p"] < 0.05)).all())
    h2 = bool(diff.params["d_dollar"] < 0 and diff.pvalues["d_dollar"] < 0.05)
    h3 = bool(dk["valutaandel"] > 0.5)
    a = asym.loc[em]
    h4 = bool(abs(a["beta_op"]) > abs(a["beta_ned"]) and a["p_ens"] < 0.05)
    o = oos.loc[em]
    h5 = bool(o["R2_OOS_pct"] > 0 and o["CW_p"] < 0.05)
    c = bc.loc[em]
    h6 = bool(c["beta_d_oil"] > 0 and c["t_d_oil"] > 1.96 and c["beta"] < 0 and c["p"] < 0.05)

    last_month = df.index[-1]
    raw_last = res.get("raw_last")
    partial = ""
    if raw_last is not None and raw_last < last_month:
        partial = f" Sidste måned ({last_month:%Y-%m}) er ufuldstændig og løber til {raw_last:%d-%m-%Y}."

    txt = f"""# Dollaren og EM-obligationer i lokalvaluta

*Genereret automatisk af `run.py`. Månedlige data {start:%Y-%m} til {end:%Y-%m}, N = {n}.{partial}
Newey-West standardfejl (3 lags). Alle afkast og ændringer i procent.*

## Hypoteser og domme

| | Hypotese (fastlagt før estimation på de rigtige data) | Dom |
|---|---|---|
| H1 | Dollarbetaen er negativ og signifikant for EMLC, CEW og EMB | {_verdict(h1)} |
| H2 | Lokalvaluta (EMLC) er mere dollarfølsom end hård valuta (EMB) | {_verdict(h2)} (forskel β = {diff.params['d_dollar']:.2f}, t = {diff.tvalues['d_dollar']:.2f}) |
| H3 | Over halvdelen af EMLC's dollarbeta kommer fra valutaen | {_verdict(h3)} (valutaandel {100*dk['valutaandel']:.0f} %) |
| H4 | Dollarstyrke gør mere ondt end dollarsvaghed gavner | {_verdict(h4)} (β op {a['beta_op']:.2f} vs. ned {a['beta_ned']:.2f}, p = {a['p_ens']:.2f}) |
| H5 | Sidste måneds dollarændring forudsiger næste måneds EMLC-afkast out-of-sample | {_verdict(h5)} (R²_OOS = {o['R2_OOS_pct']:.2f} %, CW p = {o['CW_p']:.2f}) |
| H6 | Olie har en positiv effekt, og dollarbetaen overlever kontrol for olie og US-renter | {_verdict(h6)} |

## 1. Dollarbetaer

$r_{{i,t}} = \\alpha_i + \\beta_i \\, \\Delta \\text{{USD}}_t + \\varepsilon_{{i,t}}$

{_md(b)}

### Med kontrol for olie og amerikansk 10-årig rente

$r_{{i,t}} = \\alpha_i + \\beta_i \\, \\Delta \\text{{USD}}_t + \\gamma_i \\, \\Delta \\text{{Olie}}_t + \\delta_i \\, \\Delta y^{{US}}_{{10,t}} + \\varepsilon_{{i,t}}$

{_md(bc)}

## 2. Dekomponering: valuta eller rente?

Restposten er defineret som $r^{{EMLC}} - r^{{CEW}}$, så betaerne summerer per konstruktion. Det er en regneidentitet og ikke en validering. Det informative er, hvor følsom valutaandelen er over for valget af valutaproxy (se afsnit 7).

{_md(dk.drop("kontrol: sum - total").to_frame('værdi'), '{:.3f}')}

## 3. Asymmetri

$r_t = \\alpha + \\beta^{{op}} \\max(\\Delta \\text{{USD}}_t, 0) + \\beta^{{ned}} \\min(\\Delta \\text{{USD}}_t, 0) + \\varepsilon_t$

{_md(asym)}

![Asymmetri](fig_asymmetri.png)

## 4. Rullende dollarbeta

![Rullende beta](fig_rullende_beta.png)

## 5. Forudsigelse out-of-sample

Udvidende vindue, mindst 60 måneders træning. Benchmark er det historiske gennemsnit. Clark-West-test (ensidet).

{_md(oos)}

## 6. Den seneste episode: modellen estimeret uden de sidste 3 måneder

{_md(ep.set_index(['måned', 'aktiv']))}

## 7. Robusthed og eksplorative analyser (ikke forhåndsfastlagt)

### Dollarindeks uden EM-valutaer

Feds brede indeks indeholder bl.a. yuan og peso. Indekset mod avancerede økonomier (`DTWEXAFEGS`) gør ikke.

{_md(res["rob_dollar"])}

### Valutaproxy: CEW mod spotkurv

Spotkurven er ligevægtet over de syv GBI-EM-valutaer, Fed offentliggør (BRL, MXN, ZAR, INR, CNY, MYR, THB), og indeholder ingen carry.

{_md(res["rob_dekomp"])}

### Asymmetri med kontrol for VIX

{_md(res["rob_asym"])}

## Begrænsninger

- Hverken CEW eller spotkurven matcher EMLC's landevægte. Restposten opsamler derfor både lokal rente, vægtforskel og (for CEW) carry. En ren opdeling kræver J.P. Morgan GBI-EM i både hedget og uhedget version.
- CEW handles sjældent og har uændrede slutkurser i nogle måneder, hvilket trækker dens beta mod nul.
- ETF'er har gebyrer og tracking error i forhold til de underliggende J.P. Morgan-indeks.
- Asymmetri-resultatet for CEW og VIX-kontrollen er eksplorative og var ikke fastlagt på forhånd.
- Hypoteserne blev skrevet, før analysen blev kørt på de rigtige data, men det er ikke dokumenteret med tidsstempler.
- Samtidige regressioner viser eksponering, ikke kausalitet. Dollaren og EM-aktiver reagerer begge på global risikovillighed.
"""
    path = out / "rapport.md"
    path.write_text(txt, encoding="utf-8")
    verdicts = {"I": h1, "II": h2, "III": h3, "IV": h4, "V": h5, "VI": h6}
    return path, verdicts
