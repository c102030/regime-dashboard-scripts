#!/usr/bin/env python3
"""Fits and checks the dashboard's two recession models from the data snapshot in model/data.

What each model estimates: the chance that at least one of the next twelve months (t+1 to t+12) is a recession month,
by NBER dates for the United States and CODACE dates for Brazil. A probit on monthly data.

What this script reports, and what it cannot:
- "in sample": the model scored on the months it was fitted on. The chart on the dashboard is this kind of
  retrospective fit: today's coefficients applied to today's (revised) data. It is not a record of real-time forecasts.
- "leave one recession out": refitted without each recession and the 24 months before and 12 after it, then scored there.
- "walk forward": at each month the model is refitted only on months at least EMBARGO months older (twelve for the
  horizon, twelve more because recessions are dated late), then scores that month. This removes look-ahead in the
  coefficients, not in the data: the snapshot holds today's revised figures, because real-time vintages are not in it.
- The input choice itself was made with the whole sample in view (several specifications were compared), so every
  score here flatters the model somewhat. Brazil has three recessions in the sample: its scores are fragile.
AUC measures ranking (discrimination), not accuracy and not calibration; Brier score and log loss measure the
probabilities themselves and are shown against a model that always answers the historical share of such months.

Usage: python3 model/validate.py [--write]   (--write saves model/report.json and model/REPORT.md)
Needs numpy, pandas and statsmodels. The data snapshot was downloaded on 18 November 2026."""
import json, os, sys, warnings
import numpy as np, pandas as pd, statsmodels.api as sm

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
HORIZON, EMBARGO = 12, 24
PRODUCTION = {"us": {"const": -0.3058, "spread": -0.4781, "permits": -0.0222, "nfci": 0.9837},
              "br": {"const": -0.3817, "dselic": 0.0618, "ibc": -0.1015}}
CODACE = (("2001Q2", "2001Q4"), ("2003Q1", "2003Q2"), ("2008Q4", "2009Q1"), ("2014Q2", "2016Q4"), ("2020Q1", "2020Q2"))


def fred(sid):
    return pd.read_csv(os.path.join(HERE, "data", sid + ".csv"), na_values=".", parse_dates=["date"]).set_index("date")[sid].astype(float)


def ahead(rec, h=HORIZON):  # 1 when any of the next h months is a recession month; undefined for the last h months
    return pd.concat([rec.shift(-k) for k in range(1, h + 1)], axis=1).max(axis=1, skipna=False)


def episodes(rec):
    out, start, prev = [], None, None
    for d, v in rec.items():
        if v == 1 and start is None:
            start = d
        if v == 0 and start is not None:
            out.append((start, prev))
            start = None
        prev = d
    return out


def probit(df, cols):
    return sm.Probit(df["y"], sm.add_constant(df[cols], has_constant="add")).fit(disp=0)


def predict(model, df, cols):
    return pd.Series(np.asarray(model.predict(sm.add_constant(df[cols], has_constant="add"))), index=df.index)


def auc(y, p):
    y, p = np.asarray(y), np.asarray(p)
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    return float((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())


def brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def logloss(y, p):
    y, p = np.asarray(y), np.clip(np.asarray(p), 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def loeo(df, cols, eps):  # leave one recession out, with its run-up and aftermath
    p = pd.Series(np.nan, index=df.index)
    for a, b in eps:
        lo, hi = a - pd.DateOffset(months=24), b + pd.DateOffset(months=12)
        inside = (df.index >= lo) & (df.index <= hi)
        p[inside] = predict(probit(df[~inside], cols), df[inside], cols)
    return p


def walk(df, cols, first):  # expanding window; the fit never sees a month newer than t minus EMBARGO
    p, base, last = pd.Series(np.nan, index=df.index), pd.Series(np.nan, index=df.index), None
    for t in df.index[df.index >= first]:
        train = df[df.index <= t - pd.DateOffset(months=EMBARGO)]
        if train.y.nunique() < 2:
            continue
        try:
            last = probit(train, cols)
        except Exception:  # a short window can be perfectly separated: keep the previous fit
            pass
        if last is None:
            continue
        p[t] = float(predict(last, df.loc[[t]], cols).iloc[0])
        base[t] = train.y.mean()
    return p, base


def boot(y, p, q, fn, reps=1000, block=24, seed=7):  # moving blocks, because neighbouring months are not independent
    rng, n, out = np.random.default_rng(seed), len(y), []
    y, p, q = np.asarray(y), np.asarray(p), np.asarray(q)
    for _ in range(reps):
        idx = np.concatenate([np.arange(s, s + block) % n for s in rng.integers(0, n, int(np.ceil(n / block)))])[:n]
        v = fn(y[idx], p[idx], q[idx])
        if not np.isnan(v):
            out.append(v)
    return [round(float(np.percentile(out, 5)), 3), round(float(np.percentile(out, 95)), 3)]


def scores(y, p, base, rec):
    ok = p.notna() & y.notna()
    y, p, base, rec = y[ok], p[ok], base[ok], rec[ok]
    calm = rec == 0  # months not already in recession: the harder and more useful question
    bins, table = [0, .1, .25, .5, .75, 1.0001], []
    for lo, hi in zip(bins, bins[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum():
            table.append({"range": f"{int(lo * 100)}-{int(min(hi, 1) * 100)}%", "months": int(m.sum()), "mean_forecast": round(float(p[m].mean()) * 100, 1),
                          "share_followed_by_recession": round(float(y[m].mean()) * 100, 1)})
    skill = lambda yy, pp, qq: 1 - brier(yy, pp) / brier(yy, qq) if brier(yy, qq) else float("nan")
    return {"months": int(len(y)), "from": str(y.index[0].date()), "to": str(y.index[-1].date()), "share_positive": round(float(y.mean()), 3),
            "auc": round(auc(y, p), 3), "auc_90pct_interval": boot(y, p, base, lambda a, b, c: auc(a, b)),
            "auc_months_not_in_recession": round(auc(y[calm], p[calm]), 3),
            "brier": round(brier(y, p), 4), "brier_base_rate": round(brier(y, base), 4), "brier_skill": round(skill(y, p, base), 3),
            "brier_skill_90pct_interval": boot(y, p, base, skill),
            "logloss": round(logloss(y, p), 4), "logloss_base_rate": round(logloss(y, base), 4), "calibration": table}


def study(df, cols, eps, first_oos, rec):
    m = probit(df, cols)
    fitted = predict(m, df, cols)
    flat = pd.Series(df.y.mean(), index=df.index)
    wf, wf_base = walk(df, cols, pd.Timestamp(first_oos))
    return {"inputs": cols, "coefficients": {k: round(float(v), 4) for k, v in m.params.items()}, "p_values": {k: round(float(v), 3) for k, v in m.pvalues.items()},
            "means": {k: round(float(df[k].mean()), 4) for k in cols}, "fit_window": [str(df.index[0].date()), str(df.index[-1].date())],
            "recessions_in_window": len(eps), "in_sample": scores(df.y, fitted, flat, rec.reindex(df.index)),
            "leave_one_recession_out": scores(df.y, loeo(df, cols, eps), flat, rec.reindex(df.index)),
            "walk_forward": scores(df.y, wf, wf_base, rec.reindex(df.index))}


def united_states():
    us = pd.DataFrame({k: fred(k) for k in ("GS10", "TB3MS", "PERMIT", "NFCI", "USREC")})
    us["spread"], us["permits"], us["nfci"] = us.GS10 - us.TB3MS, 100 * np.log(us.PERMIT / us.PERMIT.shift(12)), us.NFCI
    us["y"] = ahead(us.USREC)
    df = us.loc["1972-01-01":"2024-10-01"].dropna(subset=["y", "spread", "permits", "nfci"])  # the last two years are left out: NBER dates recessions late
    eps = [e for e in episodes(us.USREC.dropna()) if e[0] >= pd.Timestamp("1973-01-01")]
    return {"production": study(df, ["spread", "permits", "nfci"], eps, "1990-01-01", us.USREC),
            "curve_only": study(df, ["spread"], eps, "1990-01-01", us.USREC)}


def brazil():
    raw = json.load(open(os.path.join(HERE, "data", "br.json")))
    b = pd.DataFrame({k: pd.Series({pd.Timestamp(d): v for d, v in raw[k]}) for k in raw}).sort_index()
    rec = pd.Series(0.0, index=pd.date_range("1996-01-01", "2026-11-01", freq="MS"))
    eps = []
    for a, z in CODACE:
        s, e = pd.Period(a, "Q").start_time, pd.Period(z, "Q").end_time.normalize().replace(day=1)
        rec[(rec.index >= s) & (rec.index <= e)] = 1
        eps.append((s, e))
    b = b.reindex(rec.index)
    b["dselic"] = b.selic_m - b.selic_m.shift(12)
    b["ibc"] = 200 * np.log(b.ibc_sa / b.ibc_sa.shift(6))      # same month: only known about two months later
    b["ibc_known"] = b["ibc"].shift(2)                          # the reading that was already published in month t
    b["y"] = ahead(rec)
    eps = [e for e in eps if e[0] >= pd.Timestamp("2004-01-01")]
    out = {}
    for name, cols in (("production", ["dselic", "ibc"]), ("activity_as_published", ["dselic", "ibc_known"]), ("policy_rate_only", ["dselic"])):
        df = b.loc["2003-09-01":"2024-12-01"].dropna(subset=["y"] + cols) if "ibc_known" in cols else b.loc["2003-07-01":"2024-12-01"].dropna(subset=["y"] + cols)
        out[name] = study(df, cols, eps, "2012-01-01", rec)
    return out


def markdown(report):
    names = {"in_sample": "In sample", "leave_one_recession_out": "Leave one recession out", "walk_forward": "Walk forward"}
    out = ["# Recession models: what the checks show", "",
           "Written by `model/validate.py` from the data snapshot of " + report["data_snapshot"] + ". Rerun it to reproduce every figure.", "",
           "Each model estimates the chance that at least one of the next twelve months is a recession month (NBER dates for the United States, "
           "CODACE dates for Brazil). The scores below use today's revised data, not the figures available at each date, and the inputs were chosen "
           "with the whole sample in view, so they flatter the models. AUC measures ranking, not accuracy or calibration. Brier skill is the share of "
           "the base-rate forecast's squared error that the model removes: zero or less means no better than always answering the historical share.", ""]
    for country, title in (("united_states", "United States"), ("brazil", "Brazil")):
        for spec, s in report[country].items():
            out += [f"## {title}: {spec.replace('_', ' ')}", "",
                    "Inputs: " + ", ".join(s["inputs"]) + f". Fitted on {s['fit_window'][0][:7]} to {s['fit_window'][1][:7]}, {s['recessions_in_window']} recessions. "
                    "Coefficients: " + ", ".join(f"{k} {v:+.4f}" for k, v in s["coefficients"].items()) + ".", "",
                    "| Check | Months | AUC (90% interval) | AUC, months not in recession | Brier, model vs base rate | Brier skill (90% interval) | Log loss, model vs base rate |",
                    "|---|---|---|---|---|---|---|"]
            for part, label in names.items():
                r = s[part]
                out.append(f"| {label}, {r['from'][:7]} to {r['to'][:7]} | {r['months']} | {r['auc']:.2f} ({r['auc_90pct_interval'][0]:.2f} to {r['auc_90pct_interval'][1]:.2f}) | "
                           f"{r['auc_months_not_in_recession']:.2f} | {r['brier']:.3f} vs {r['brier_base_rate']:.3f} | {r['brier_skill']:+.2f} "
                           f"({r['brier_skill_90pct_interval'][0]:+.2f} to {r['brier_skill_90pct_interval'][1]:+.2f}) | {r['logloss']:.3f} vs {r['logloss_base_rate']:.3f} |")
            out += ["", "Calibration, walk forward: " + "; ".join(f"forecast {c['range']} ({c['months']} months, mean {c['mean_forecast']}%) was followed by a recession "
                                                                 f"{c['share_followed_by_recession']}% of the time" for c in s["walk_forward"]["calibration"]) + ".", ""]
    out += ["## Limits", "",
            "- No real-time vintages: building permits, the Chicago Fed index and Brazil's activity index are all revised after first publication.",
            "- Brazil's activity index is published about two months late. The dashboard therefore dates Brazil's reading by the newest month with both inputs.",
            "- The last two years (United States) are outside the fit because recessions are dated with a delay.",
            "- Intervals come from a moving-block bootstrap (24-month blocks, 1,000 draws): with so few recessions they are wide and themselves uncertain.", ""]
    return "\n".join(out)


def main():
    report = {"horizon_months": HORIZON, "embargo_months": EMBARGO, "data_snapshot": "2026-11-18", "united_states": united_states(), "brazil": brazil()}
    for key, where in (("us", report["united_states"]["production"]), ("br", report["brazil"]["production"])):
        gap = max(abs(where["coefficients"][k] - v) for k, v in PRODUCTION[key].items())
        report[key + "_matches_production"] = bool(gap < 5e-4)
    if "--write" in sys.argv:
        with open(os.path.join(HERE, "report.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
        with open(os.path.join(HERE, "REPORT.md"), "w", encoding="utf-8") as f:
            f.write(markdown(report))
    row = lambda name, s: (f"{name:44s} n={s['months']:3d} AUC {s['auc']:.3f} {s['auc_90pct_interval']} calm {s['auc_months_not_in_recession']:.3f} "
                           f"Brier {s['brier']:.3f} vs {s['brier_base_rate']:.3f} skill {s['brier_skill']:+.2f} {s['brier_skill_90pct_interval']} "
                           f"logloss {s['logloss']:.3f} vs {s['logloss_base_rate']:.3f}")
    for country in ("united_states", "brazil"):
        for spec, s in report[country].items():
            print(country, spec, s["coefficients"], s["fit_window"])
            for part in ("in_sample", "leave_one_recession_out", "walk_forward"):
                print("  " + row(part + " " + s[part]["from"][:7] + ".." + s[part]["to"][:7], s[part]))
    print("matches production:", report["us_matches_production"], report["br_matches_production"])
    return report


if __name__ == "__main__":
    main()
