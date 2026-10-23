"""Kør hele analysen:  python run.py            (bruger cache i data/raw hvis den findes)
                       python run.py --refresh  (henter alle data igen)
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from analysis import run_all  # noqa: E402
from data import build_monthly, load_raw  # noqa: E402
from latex import compile_pdf, write_latex  # noqa: E402
from report import fig_asym, fig_rolling, write_report  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true", help="hent alle data igen")
    args = p.parse_args()

    out = ROOT / "results"
    out.mkdir(exist_ok=True)

    print("1/5 Data")
    raw = load_raw(refresh=args.refresh)
    df = build_monthly(raw)
    df.to_csv(out / "maanedsdata.csv")

    print("2/5 Estimation")
    res = run_all(df)
    res["raw_last"] = min(s.index.max() for s in raw.values())
    for k in ["betas", "betas_ctrl", "asym", "oos"]:
        res[k].to_csv(out / f"{k}.csv")
    res["dekomp"].to_csv(out / "dekomp.csv")
    res["episode"].to_csv(out / "episode.csv", index=False)

    print("3/5 Figurer")
    fig_rolling(res["rolling"], out / "fig_rullende_beta.png")
    fig_asym(df, res["asym"], out / "fig_asymmetri.png")

    print("4/5 Rapport")
    path, verdicts = write_report(df, res, out)

    print("5/5 LaTeX-artikel")
    paper = ROOT / "paper"
    write_latex(df, res, verdicts, paper / "generated", out)
    pdf = compile_pdf(paper)
    print(f"\nFærdig: {path.relative_to(ROOT)}")
    if pdf:
        print(f"         {pdf.relative_to(ROOT)}")
    else:
        print("         paper/paper.tex (ingen LaTeX fundet eller fejl i kompilering, kompilér selv fx i Overleaf)")


if __name__ == "__main__":
    main()
