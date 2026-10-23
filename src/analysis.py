"""Estimationer. Alle standardfejl er Newey-West (HAC) med 3 lags.

Hypoteserne er fastlagt på forhånd i README.md (H1-H6) og testes her.
Regressionerne er samtidige (contemporaneous): de måler eksponering,
ikke forudsigelseskraft. Forudsigelse testes særskilt i oos_predictive().
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

HAC_LAGS = 3
ASSETS = {
    "r_emlc": "EM lokalvaluta-obl. (EMLC)",
    "r_cew": "EM-valutakurv (CEW)",
    "r_lokal": "Lokal rentekomponent (EMLC - CEW)",
    "r_emb": "EM hård valuta (EMB)",
}


def ols_hac(y: pd.Series, X: pd.DataFrame):
    X = sm.add_constant(X)
    return sm.OLS(y, X, missing="drop").fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})


def _row(res, var: str) -> dict:
    return {
        "beta": res.params[var],
        "se": res.bse[var],
        "t": res.tvalues[var],
        "p": res.pvalues[var],
    }


def static_betas(df: pd.DataFrame, controls: list[str] | None = None) -> pd.DataFrame:
    """H1, H2, H6: r_i = a + b*d_dollar (+ kontroller) + e."""
    regs = ["d_dollar"] + (controls or [])
    rows = []
    for col, label in ASSETS.items():
        res = ols_hac(df[col], df[regs])
        row = {"aktiv": label, **_row(res, "d_dollar"), "R2": res.rsquared, "N": int(res.nobs)}
        for c in controls or []:
            row[f"beta_{c}"] = res.params[c]
            row[f"t_{c}"] = res.tvalues[c]
        rows.append(row)
    return pd.DataFrame(rows).set_index("aktiv")


def decomposition(df: pd.DataFrame) -> pd.Series:
    """H3: Da r_emlc = r_cew + r_lokal per konstruktion, er beta_emlc = beta_cew + beta_lokal
    eksakt i OLS med samme regressorer. Andelen fra valuta = beta_cew / beta_emlc."""
    b = {c: ols_hac(df[c], df[["d_dollar"]]).params["d_dollar"] for c in ["r_emlc", "r_cew", "r_lokal"]}
    return pd.Series(
        {
            "beta_EMLC": b["r_emlc"],
            "beta_valuta (CEW)": b["r_cew"],
            "beta_lokal rente": b["r_lokal"],
            "valutaandel": b["r_cew"] / b["r_emlc"],
            "kontrol: sum - total": b["r_cew"] + b["r_lokal"] - b["r_emlc"],
        }
    )


def asymmetry(df: pd.DataFrame) -> pd.DataFrame:
    """H4: r = a + b_op*max(dD,0) + b_ned*min(dD,0) + e. Wald-test af b_op = b_ned."""
    X = pd.DataFrame(
        {"dollar_op": df["d_dollar"].clip(lower=0), "dollar_ned": df["d_dollar"].clip(upper=0)},
        index=df.index,
    )
    rows = []
    for col, label in ASSETS.items():
        res = ols_hac(df[col], X)
        w = res.wald_test("dollar_op = dollar_ned", scalar=True)
        rows.append(
            {
                "aktiv": label,
                "beta_op": res.params["dollar_op"],
                "t_op": res.tvalues["dollar_op"],
                "beta_ned": res.params["dollar_ned"],
                "t_ned": res.tvalues["dollar_ned"],
                "p_ens": float(w.pvalue),
                "mdr_op": int((df["d_dollar"] > 0).sum()),
                "mdr_ned": int((df["d_dollar"] <= 0).sum()),
            }
        )
    return pd.DataFrame(rows).set_index("aktiv")


def rolling_beta(df: pd.DataFrame, window: int = 36) -> pd.DataFrame:
    out = {}
    for col in ["r_emlc", "r_cew", "r_lokal"]:
        cov = df[col].rolling(window).cov(df["d_dollar"])
        var = df["d_dollar"].rolling(window).var()
        out[col] = cov / var
    return pd.DataFrame(out).dropna()


def clark_west(y: np.ndarray, f_bench: np.ndarray, f_model: np.ndarray) -> tuple[float, float]:
    """Clark-West (2007) for indlejrede modeller. Ensidet test af H0: modellen er ikke bedre."""
    adj = (y - f_bench) ** 2 - ((y - f_model) ** 2 - (f_bench - f_model) ** 2)
    res = sm.OLS(adj, np.ones_like(adj)).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    t = float(res.tvalues[0])
    return t, float(1 - stats.norm.cdf(t))


def oos_predictive(df: pd.DataFrame, min_train: int = 60) -> pd.DataFrame:
    """H5: Forudsiger sidste måneds dollarændring næste måneds afkast?
    Udvidende vindue. Benchmark: historisk gennemsnit fra samme vindue (ingen lookahead).
    R2_OOS = 1 - SSE(model)/SSE(gennemsnit)."""
    rows = []
    x_lag = df["d_dollar"].shift(1)
    for col, label in ASSETS.items():
        data = pd.DataFrame({"y": df[col], "x": x_lag}).dropna()
        y_all, x_all = data["y"].to_numpy(), data["x"].to_numpy()
        f_mean, f_mod = [], []
        for t in range(min_train, len(data)):
            y, x = y_all[:t], x_all[:t]  # kun information til og med t-1
            X = np.column_stack([np.ones(t), x])
            a, b = np.linalg.lstsq(X, y, rcond=None)[0]
            f_mod.append(a + b * x_all[t])
            f_mean.append(y.mean())
        yt, fb, fm = y_all[min_train:], np.asarray(f_mean), np.asarray(f_mod)
        r2 = 1 - np.sum((yt - fm) ** 2) / np.sum((yt - fb) ** 2)
        cw_t, cw_p = clark_west(yt, fb, fm)
        rows.append({"aktiv": label, "R2_OOS_pct": 100 * r2, "CW_t": cw_t, "CW_p": cw_p, "N_oos": len(yt)})
    return pd.DataFrame(rows).set_index("aktiv")


def recent_episode(df: pd.DataFrame, n_months: int = 3, controls: list[str] | None = None) -> pd.DataFrame:
    """Faktisk vs. modelforventet afkast i de seneste måneder. Modellen estimeres KUN
    på data før episoden, så det er en ægte out-of-sample sammenligning."""
    regs = ["d_dollar"] + (controls or [])
    train, test = df.iloc[:-n_months], df.iloc[-n_months:]
    rows = []
    for col in ["r_emlc", "r_cew", "r_emb"]:
        res = ols_hac(train[col], train[regs])
        pred = res.predict(sm.add_constant(test[regs], has_constant="add"))
        for d in test.index:
            rows.append(
                {
                    "måned": d.strftime("%Y-%m"),
                    "aktiv": ASSETS[col],
                    "d_dollar": test.at[d, "d_dollar"],
                    "faktisk": test.at[d, col],
                    "model": pred[d],
                    "afvigelse": test.at[d, col] - pred[d],
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------
# Robusthed og eksplorative analyser (IKKE en del af de forhåndsfastlagte hypoteser)
# ---------------------------------------------------------------------------------------
ROB_ASSETS = {
    "r_emlc": "EMLC",
    "r_cew": "CEW",
    "r_spot": "Spotkurv (7 GBI-EM)",
    "r_lokal": "EMLC - CEW",
    "r_lokal_spot": "EMLC - spotkurv",
    "r_emb": "EMB",
}


def robustness_dollar(df: pd.DataFrame) -> pd.DataFrame:
    """Dollarbetaer med Feds brede indeks (inkl. EM-valutaer) og med indekset mod
    avancerede økonomier (uden EM-valutaer). Hvis betaerne holder med det sidste,
    er sammenhængen ikke blot mekanisk."""
    rows = []
    for col, label in ROB_ASSETS.items():
        r_b = ols_hac(df[col], df[["d_dollar"]])
        r_a = ols_hac(df[col], df[["d_dollar_afe"]])
        rows.append({
            "aktiv": label,
            "beta_bred": r_b.params["d_dollar"], "t_bred": r_b.tvalues["d_dollar"], "R2_bred": r_b.rsquared,
            "beta_afe": r_a.params["d_dollar_afe"], "t_afe": r_a.tvalues["d_dollar_afe"], "R2_afe": r_a.rsquared,
        })
    return pd.DataFrame(rows).set_index("aktiv")


def decomposition_compare(df: pd.DataFrame) -> pd.DataFrame:
    """Valutaandelen af EMLC's dollarbeta med to valutaproxyer. Restposten er per
    definition EMLC minus proxyen, så at betaerne summerer er en regneidentitet,
    ikke en validering. Det, der er informativt, er hvor meget andelen flytter sig."""
    b_emlc = ols_hac(df["r_emlc"], df[["d_dollar"]]).params["d_dollar"]
    rows = []
    for proxy, rest, label in [("r_cew", "r_lokal", "CEW (ligevægtet, inkl. carry)"),
                               ("r_spot", "r_lokal_spot", "Spotkurv (7 GBI-EM, uden carry)")]:
        b_fx = ols_hac(df[proxy], df[["d_dollar"]]).params["d_dollar"]
        b_rest = ols_hac(df[rest], df[["d_dollar"]])
        corr = df[proxy].corr(df["r_emlc"])
        rows.append({
            "valutaproxy": label, "beta_valuta": b_fx, "beta_rest": b_rest.params["d_dollar"],
            "t_rest": b_rest.tvalues["d_dollar"], "valutaandel": b_fx / b_emlc, "korr_med_EMLC": corr,
        })
    return pd.DataFrame(rows).set_index("valutaproxy")


def asymmetry_vix(df: pd.DataFrame) -> pd.DataFrame:
    """Eksplorativ: holder asymmetrien, når der kontrolleres for ændringen i VIX?
    Hvis den forsvinder, handler den snarere om kriser end om dollarens retning."""
    rows = []
    for col in ["r_emlc", "r_cew", "r_spot"]:
        for ctrl in [False, True]:
            X = pd.DataFrame({"op": df["d_dollar"].clip(lower=0), "ned": df["d_dollar"].clip(upper=0)})
            if ctrl:
                X["d_vix"] = df["d_vix"]
            res = ols_hac(df[col], X)
            w = res.wald_test("op = ned", scalar=True)
            rows.append({
                "aktiv": ROB_ASSETS[col], "VIX-kontrol": "ja" if ctrl else "nej",
                "beta_op": res.params["op"], "beta_ned": res.params["ned"],
                "forskel": res.params["op"] - res.params["ned"], "p_ens": float(w.pvalue),
            })
    return pd.DataFrame(rows).set_index(["aktiv", "VIX-kontrol"])


def run_all(df: pd.DataFrame) -> dict:
    return {
        "betas": static_betas(df),
        "betas_ctrl": static_betas(df, controls=["d_oil", "d_us10y"]),
        "dekomp": decomposition(df),
        "asym": asymmetry(df),
        "rolling": rolling_beta(df),
        "oos": oos_predictive(df),
        "episode": recent_episode(df, controls=["d_oil", "d_us10y"]),
        "rob_dollar": robustness_dollar(df),
        "rob_dekomp": decomposition_compare(df),
        "rob_asym": asymmetry_vix(df),
        "sample": (df.index.min(), df.index.max(), len(df)),
    }
