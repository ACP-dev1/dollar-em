"""Monte Carlo-validering af pipelinen på syntetiske data med kendte parametre.

Kør:  python3 tests/monte_carlo.py [antal]   (standard 1000; tager nogle minutter)

Skriver results/monte_carlo.csv og paper/generated/mc.tex (tal til artiklens valideringsafsnit).
Monte Carlo-standardfejlen på en forkastelsesrate p er sqrt(p(1-p)/R).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from analysis import asymmetry, oos_predictive, static_betas  # noqa: E402
from data import build_monthly  # noqa: E402
from make_synthetic import TRUE, simulate  # noqa: E402

EM, CEW, EMB = "EM lokalvaluta-obl. (EMLC)", "EM-valutakurv (CEW)", "EM hård valuta (EMB)"


def one(seed: int) -> dict:
    df = build_monthly(simulate(seed))
    b = static_betas(df)
    a = asymmetry(df)
    o = oos_predictive(df)
    return {
        "beta_emb": b.at[EMB, "beta"],
        "beta_op_cew": a.at[CEW, "beta_op"], "beta_ned_cew": a.at[CEW, "beta_ned"],
        "asym_rej_cew": a.at[CEW, "p_ens"] < 0.05,   # sand forskel -0,4: styrke
        "asym_rej_emlc": a.at[EM, "p_ens"] < 0.05,   # sand forskel -0,4: styrke
        "asym_rej_emb": a.at[EMB, "p_ens"] < 0.05,   # symmetrisk: størrelse (bør være 5 %)
        "cw_rej_emlc": o.at[EM, "CW_p"] < 0.05,      # ingen forudsigelse: størrelse
        "cw_rej_all": float((o["CW_p"] < 0.05).mean()),
    }


def fmt(x: float, d: int = 1) -> str:
    return "\\ensuremath{" + f"{x:.{d}f}".replace(".", "{,}") + "}"


def main(R: int) -> None:
    rows = []
    for i in range(R):
        rows.append(one(1000 + i))
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{R}")
    res = pd.DataFrame(rows)
    (ROOT / "results").mkdir(exist_ok=True)
    res.to_csv(ROOT / "results" / "monte_carlo.csv", index=False)

    def rate(c):
        p = res[c].mean()
        return 100 * p, 100 * np.sqrt(p * (1 - p) / R)

    out = {"R": R}
    for k, c in [("CWsize", "cw_rej_emlc"), ("CWsizeAll", "cw_rej_all"), ("PowCEW", "asym_rej_cew"),
                 ("PowEMLC", "asym_rej_emlc"), ("SizeAsym", "asym_rej_emb")]:
        out[k], out[k + "SE"] = rate(c)
    out["BetaOp"] = res["beta_op_cew"].mean()
    out["BetaNed"] = res["beta_ned_cew"].mean()
    out["BetaEMB"] = res["beta_emb"].mean()

    print("\nResultater (procent, MC-standardfejl i parentes):")
    for k in ["CWsize", "CWsizeAll", "SizeAsym", "PowCEW", "PowEMLC"]:
        print(f"  {k:10s} {out[k]:5.1f} ({out[k + 'SE']:.1f})")
    print(f"  Gns. beta_op CEW {out['BetaOp']:.3f} (sand {TRUE['cew_op']}), beta_ned {out['BetaNed']:.3f} "
          f"(sand {TRUE['cew_ned']}), beta EMB {out['BetaEMB']:.3f} (sand {TRUE['emb']})")

    lines = ["% Genereret af tests/monte_carlo.py. Rediger ikke manuelt.", f"\\newcommand{{\\MCR}}{{{R:,}}}".replace(",", ".")]
    for k, v in out.items():
        if k == "R":
            continue
        d = 3 if k.startswith("Beta") else 1
        lines.append(f"\\newcommand{{\\MC{k}}}{{{fmt(v, d)}}}")
    gen = ROOT / "paper" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "mc.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSkrev {gen / 'mc.tex'}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
