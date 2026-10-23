"""Skriver LaTeX-tabeller og tal-makroer til paper/generated/, som paper/paper.tex inkluderer.

Alle tal i artiklen kommer herfra. Teksten i paper.tex skal derfor ikke rettes,
når data opdateres: kør run.py igen og kompilér.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pandas as pd
from scipy.stats import norm

from analysis import ols_hac

EM, CEW, LOK, EMB = (
    "EM lokalvaluta-obl. (EMLC)",
    "EM-valutakurv (CEW)",
    "Lokal rentekomponent (EMLC - CEW)",
    "EM hård valuta (EMB)",
)
SHORT = {EM: "EMLC", CEW: "CEW", LOK: "Lokal rente", EMB: "EMB"}
DA_MONTH = ["januar", "februar", "marts", "april", "maj", "juni", "juli",
            "august", "september", "oktober", "november", "december"]


def num(x: float, d: int = 2) -> str:
    """Dansk decimaltegn, virker i både tekst- og matematiktilstand."""
    s = f"{x:.{d}f}".replace(".", "{,}")
    return f"\\ensuremath{{{s}}}"


def stars(p: float) -> str:
    return "^{***}" if p < 0.01 else "^{**}" if p < 0.05 else "^{*}" if p < 0.10 else ""


def cell(beta: float, p: float, d: int = 2) -> str:
    s = f"{beta:.{d}f}".replace(".", "{,}")
    return f"${s}{stars(p)}$"


def tcell(t: float) -> str:
    return "$(" + f"{t:.2f}".replace(".", "{,}") + ")$"


def month_da(ts: pd.Timestamp) -> str:
    return f"{DA_MONTH[ts.month - 1]} {ts.year}"


def _table(path: Path, colspec: str, header: str, body: list[str]) -> None:
    lines = [f"\\begin{{tabular}}{{{colspec}}}", "\\toprule", header + " \\\\", "\\midrule", *body, "\\bottomrule", "\\end{tabular}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_latex(df: pd.DataFrame, res: dict, verdicts: dict, out: Path, results_dir: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    b, bc, dk, asym, oos, ep = (res[k] for k in ["betas", "betas_ctrl", "dekomp", "asym", "oos", "episode"])
    start, end, n = res["sample"]

    # --- Tabel 1: dollarbetaer uden og med kontroller -------------------------------
    order = [EM, CEW, LOK, EMB]
    rows = []
    for spec_name, tab in [("Uden kontroller", b), ("Med kontroller", bc)]:
        rows.append(f"\\multicolumn{{5}}{{l}}{{\\textit{{{spec_name}}}}} \\\\")
        rows.append("$\\Delta \\mathrm{USD}_t$ & " + " & ".join(cell(tab.at[a, "beta"], tab.at[a, "p"]) for a in order) + " \\\\")
        rows.append(" & " + " & ".join(tcell(tab.at[a, "t"]) for a in order) + " \\\\")
        if spec_name == "Med kontroller":
            for c, lab in [("d_oil", "$\\Delta \\mathrm{Olie}_t$"), ("d_us10y", "$\\Delta y^{US}_{10,t}$")]:
                rows.append(lab + " & " + " & ".join(
                    cell(tab.at[a, f"beta_{c}"], 2 * (1 - norm.cdf(abs(tab.at[a, f't_{c}']))), 3)
                    for a in order) + " \\\\")
                rows.append(" & " + " & ".join(tcell(tab.at[a, f"t_{c}"]) for a in order) + " \\\\")
        rows.append("$R^2$ & " + " & ".join(num(tab.at[a, "R2"]) for a in order) + " \\\\")
        if spec_name == "Uden kontroller":
            rows.append("\\addlinespace")
    rows.append("\\midrule")
    rows.append("Observationer & " + " & ".join(str(int(b.at[a, "N"])) for a in order) + " \\\\")
    _table(out / "tab_betas.tex", "lcccc", " & " + " & ".join(SHORT[a] for a in order), rows)

    # --- Tabel 2: asymmetri ------------------------------------------------------
    rows = [
        "$\\beta^{op}$ & " + " & ".join(cell(asym.at[a, "beta_op"], 2 * (1 - norm.cdf(abs(asym.at[a, 't_op'])))) for a in order) + " \\\\",
        " & " + " & ".join(tcell(asym.at[a, "t_op"]) for a in order) + " \\\\",
        "$\\beta^{ned}$ & " + " & ".join(cell(asym.at[a, "beta_ned"], 2 * (1 - norm.cdf(abs(asym.at[a, 't_ned'])))) for a in order) + " \\\\",
        " & " + " & ".join(tcell(asym.at[a, "t_ned"]) for a in order) + " \\\\",
        "\\midrule",
        "$p$-værdi, $\\beta^{op}=\\beta^{ned}$ & " + " & ".join(num(asym.at[a, "p_ens"]) for a in order) + " \\\\",
        "Måneder med stigende dollar & " + " & ".join(str(int(asym.at[a, "mdr_op"])) for a in order) + " \\\\",
        "Måneder med faldende dollar & " + " & ".join(str(int(asym.at[a, "mdr_ned"])) for a in order) + " \\\\",
    ]
    _table(out / "tab_asym.tex", "lcccc", " & " + " & ".join(SHORT[a] for a in order), rows)

    # --- Tabel 3: out-of-sample ---------------------------------------------------
    rows = [
        f"{SHORT[a]} & {num(oos.at[a, 'R2_OOS_pct'])} & {num(oos.at[a, 'CW_t'])} & {num(oos.at[a, 'CW_p'])} & {int(oos.at[a, 'N_oos'])} \\\\"
        for a in order
    ]
    _table(out / "tab_oos.tex", "lcccc", "Aktiv & $R^2_{OOS}$ (\\%) & Clark-West $t$ & $p$ (ensidet) & $N_{OOS}$", rows)

    # --- Tabel 4: seneste episode -------------------------------------------------
    rows = []
    for m, g in ep.groupby("måned", sort=True):
        ts = pd.Timestamp(m + "-01")
        for i, (_, r) in enumerate(g.iterrows()):
            first = f"{DA_MONTH[ts.month - 1].capitalize()} {ts.year}" if i == 0 else ""
            usd = num(r["d_dollar"]) if i == 0 else ""
            rows.append(f"{first} & {usd} & {SHORT.get(r['aktiv'], r['aktiv'])} & {num(r['faktisk'])} & {num(r['model'])} & {num(r['afvigelse'])} \\\\")
        rows.append("\\addlinespace")
    rows = rows[:-1]
    _table(out / "tab_episode.tex", "llcccc", "Måned & $\\Delta\\mathrm{USD}$ & Aktiv & Faktisk & Model & Afvigelse", rows)

    # --- Makroer ------------------------------------------------------------------
    diff = ols_hac(df["r_emlc"] - df["r_emb"], df[["d_dollar"]])
    raw_last = res.get("raw_last")
    partial = raw_last is not None and raw_last < end
    sep = df.loc[df.index.month == 9].iloc[-1:] if (df.index.month == 9).any() else df.iloc[-2:-1]
    mac = {
        "SampleStart": month_da(start),
        "SampleEnd": month_da(end),
        "NObs": str(n),
        "DataTil": raw_last.strftime("%d.\\,%m.\\,%Y") if raw_last is not None else month_da(end),
        "PartialNote": (f"Den sidste måned er ufuldstændig og løber til {raw_last.day}.\\ {DA_MONTH[raw_last.month-1]}." if partial else ""),
        "BetaEMLC": num(b.at[EM, "beta"]), "TEMLC": num(b.at[EM, "t"]), "RtoEMLC": num(b.at[EM, "R2"]),
        "BetaCEW": num(b.at[CEW, "beta"]), "BetaLok": num(b.at[LOK, "beta"]), "BetaEMB": num(b.at[EMB, "beta"]),
        "BetaEMLCctrl": num(bc.at[EM, "beta"]), "OilEMLC": num(bc.at[EM, "beta_d_oil"], 3), "TOilEMLC": num(bc.at[EM, "t_d_oil"]),
        "DiffBeta": num(diff.params["d_dollar"]), "DiffT": num(diff.tvalues["d_dollar"]),
        "ValutaAndel": num(100 * dk["valutaandel"], 0),
        "AsymOp": num(asym.at[EM, "beta_op"]), "AsymNed": num(asym.at[EM, "beta_ned"]), "AsymP": num(asym.at[EM, "p_ens"]),
        "OosRto": num(oos.at[EM, "R2_OOS_pct"]), "OosP": num(oos.at[EM, "CW_p"]),
        "RollMin": num(res["rolling"]["r_emlc"].min()), "RollMax": num(res["rolling"]["r_emlc"].max()),
        "RollLast": num(res["rolling"]["r_emlc"].iloc[-1]),
        "SepMonth": month_da(sep.index[0]), "SepUSD": num(sep["d_dollar"].iloc[0]), "SepEMLC": num(sep["r_emlc"].iloc[0]),
    }
    for k, ok in verdicts.items():
        mac[f"Dom{k}"] = "understøttes" if ok else "understøttes ikke"

    # Ekstra tal brugt i teksten
    mac["RateLok"] = num(bc.at[LOK, "beta_d_us10y"])
    mac["TRateLok"] = num(bc.at[LOK, "t_d_us10y"])
    mac["RateEMB"] = num(bc.at[EMB, "beta_d_us10y"])
    mac["TRateEMB"] = num(bc.at[EMB, "t_d_us10y"])
    mac["AsymOpCEW"] = num(asym.at[CEW, "beta_op"])
    mac["AsymNedCEW"] = num(asym.at[CEW, "beta_ned"])
    mac["AsymPCEW"] = num(asym.at[CEW, "p_ens"])
    sep_key = sep.index[0].strftime("%Y-%m")
    e = ep[ep["måned"] == sep_key].set_index("aktiv")
    if len(e):
        mac["SepEMLCmodel"] = num(e.at[EM, "model"])
        mac["SepEMB"] = num(e.at[EMB, "faktisk"])
        mac["SepEMBmodel"] = num(e.at[EMB, "model"])
        mac["SepTekst"] = (
            "EM-lokalvaluta klarede sig altså bedre end den historiske sammenhæng tilsiger, mens hård valuta klarede sig dårligere. "
            "Det er konsistent med, at Fed-forhøjelsen især ramte gennem de amerikanske renter, som hård valuta er mest følsom over for."
            if e.at[EM, "afvigelse"] > 0 and e.at[EMB, "afvigelse"] < 0 else
            ""
        )
    else:
        mac["SepEMLCmodel"] = mac["SepEMB"] = mac["SepEMBmodel"] = "--"
        mac["SepTekst"] = ""

    # Konklusionens sætninger afhænger af dommene, så teksten altid passer til tallene
    mac["KonklKanal"] = (
        "og med begge valutaproxyer kommer hovedparten gennem valutaen" if verdicts["III"]
        else "men under halvdelen kommer gennem valutaen"
    )
    mac["KonklSignal"] = (
        "Der er tegn på, at dollaren har en vis forudsigelseskraft med en måneds forsinkelse, hvilket bør undersøges nærmere på en længere stikprøve."
        if verdicts["V"] else
        "Jeg finder ingen evidens for, at dollaren kan bruges som signal med en måneds forsinkelse; eksponeringen viser sig samtidig."
    )
    mac["KonklAsym"] = (
        "Effekten er asymmetrisk: en stigende dollar gør mere skade, end en faldende dollar gavner."
        if verdicts["IV"] else
        "Den forhåndsfastlagte test finder ikke signifikant asymmetri, men testen har begrænset styrke."
    )
    lines = ["% Genereret af src/latex.py. Rediger ikke manuelt."]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in mac.items()]
    (out / "numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- Robusthed: dollarindeks ------------------------------------------------
    rd, rk, ra = res["rob_dollar"], res["rob_dekomp"], res["rob_asym"]
    rows = []
    for a in rd.index:
        rows.append(f"{a} & {cell(rd.at[a, 'beta_bred'], 2 * (1 - norm.cdf(abs(rd.at[a, 't_bred']))))} & {tcell(rd.at[a, 't_bred'])} & {num(rd.at[a, 'R2_bred'])}"
                    f" & {cell(rd.at[a, 'beta_afe'], 2 * (1 - norm.cdf(abs(rd.at[a, 't_afe']))))} & {tcell(rd.at[a, 't_afe'])} & {num(rd.at[a, 'R2_afe'])} \\\\")
    _table(out / "tab_rob_dollar.tex", "lcccccc",
           " & \\multicolumn{3}{c}{Bredt indeks (inkl.\\ EM)} & \\multicolumn{3}{c}{Avancerede økonomier} \\\\ \\cmidrule(lr){2-4}\\cmidrule(lr){5-7}\n"
           "Aktiv & $\\beta$ & $t$ & $R^2$ & $\\beta$ & $t$ & $R^2$", rows)

    # --- Robusthed: valutaproxy ---------------------------------------------------
    rows = [f"{a} & {num(rk.at[a, 'beta_valuta'])} & {num(rk.at[a, 'beta_rest'])} & {tcell(rk.at[a, 't_rest'])} & "
            f"{num(100 * rk.at[a, 'valutaandel'], 0)}\\,\\% & {num(rk.at[a, 'korr_med_EMLC'])} \\\\" for a in rk.index]
    _table(out / "tab_rob_dekomp.tex", "lccccc",
           "Valutaproxy & $\\beta^{valuta}$ & $\\beta^{rest}$ & $t^{rest}$ & Valutaandel & Korr.\\ med EMLC", rows)

    # --- Eksplorativ: asymmetri med VIX ----------------------------------------------
    rows = []
    for (a, c), r in ra.iterrows():
        rows.append(f"{a if c == 'nej' else ''} & {c} & {num(r['beta_op'])} & {num(r['beta_ned'])} & {num(r['forskel'])} & {num(r['p_ens'])} \\\\")
    _table(out / "tab_rob_asym.tex", "llcccc",
           "Aktiv & VIX-kontrol & $\\beta^{op}$ & $\\beta^{ned}$ & Forskel & $p$", rows)

    mac2 = {
        "AfeEMLC": num(rd.at["EMLC", "beta_afe"]), "TAfeEMLC": num(rd.at["EMLC", "t_afe"]),
        "AfeCEW": num(rd.at["CEW", "beta_afe"]), "AfeRtoCEW": num(rd.at["CEW", "R2_afe"]),
        "BredRtoCEW": num(rd.at["CEW", "R2_bred"]),
        "AfeLok": num(rd.at["EMLC - CEW", "beta_afe"]), "TAfeLok": num(rd.at["EMLC - CEW", "t_afe"]),
        "SpotBeta": num(rk.iloc[1]["beta_valuta"]), "SpotAndel": num(100 * rk.iloc[1]["valutaandel"], 0),
        "SpotRest": num(rk.iloc[1]["beta_rest"]), "TSpotRest": num(rk.iloc[1]["t_rest"]),
        "CewAndel": num(100 * rk.iloc[0]["valutaandel"], 0),
        "AndelMin": num(100 * rk["valutaandel"].min(), 0),
        "AndelMax": num(100 * rk["valutaandel"].max(), 0),
        "AfeRtoEMLC": num(rd.at["EMLC", "R2_afe"]),
        "AfeLokSpot": num(rd.at["EMLC - spotkurv", "beta_afe"]),
        "AfeEMB": num(rd.at["EMB", "beta_afe"]),
        "VixPEMLC": num(ra.loc[("EMLC", "ja"), "p_ens"]),
        "NoVixPCEW": num(ra.loc[("CEW", "nej"), "p_ens"]),
        "SpotOp": num(ra.loc[("Spotkurv (7 GBI-EM)", "nej"), "beta_op"]),
        "SpotNed": num(ra.loc[("Spotkurv (7 GBI-EM)", "nej"), "beta_ned"]),
        "VixPCEW": num(ra.loc[("CEW", "ja"), "p_ens"]), "VixDiffCEW": num(ra.loc[("CEW", "ja"), "forskel"]),
        "VixPSpot": num(ra.loc[("Spotkurv (7 GBI-EM)", "ja"), "p_ens"]),
        "NoVixPSpot": num(ra.loc[("Spotkurv (7 GBI-EM)", "nej"), "p_ens"]),
    }
    with open(out / "numbers.tex", "a", encoding="utf-8") as fh:
        fh.write("\n".join(f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in mac2.items()) + "\n")
    if not (out / "mc.tex").exists():
        (out / "mc.tex").write_text("% Kør tests/monte_carlo.py for at udfylde\n", encoding="utf-8")

    for f in ["fig_rullende_beta.png", "fig_asymmetri.png"]:
        shutil.copy(results_dir / f, out / f)


def compile_pdf(paper_dir: Path) -> Path | None:
    """Kompilerer paper.tex hvis latexmk eller pdflatex findes. Ellers springes det over."""
    tex = paper_dir / "paper.tex"
    for cmd in (["latexmk", "-pdf", "-interaction=nonstopmode", "-quiet", tex.name],
                ["pdflatex", "-interaction=nonstopmode", tex.name]):
        if shutil.which(cmd[0]):
            runs = 1 if cmd[0] == "latexmk" else 3
            for _ in range(runs):
                if cmd[0] == "pdflatex":
                    subprocess.run(["bibtex", "paper"], cwd=paper_dir, capture_output=True)
                r = subprocess.run(cmd, cwd=paper_dir, capture_output=True, text=True)
            pdf = paper_dir / "paper.pdf"
            return pdf if pdf.exists() and r.returncode == 0 else None
    return None
