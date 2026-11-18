#!/usr/bin/env python3
"""Digest for the written reading of the exports and agro tab: the page's own read, worked out from agro_series.json
in the given folder. Prints one JSON line. Standard library only, no network.
Usage: python3 digest_agro.py <output-dir>"""
import json, os, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
by = {}
for r in json.load(open(os.path.join(OUT, "agro_series.json"), encoding="utf-8"))["rows"]:
    by.setdefault(r["id"], []).append((r["date"], r["value"]))
for k in by:
    by[k].sort()
year = lambda d, n: str(int(d[:4]) + n) + d[4:]
at = lambda k, d: ([v for x, v in by[k] if x <= d] or [None])[-1]
last = lambda k: by[k][-1]
pct = lambda a, b: round((a / b - 1) * 100, 1)
b, m, s, x, w = last("soy_brl"), last("rural_pf_mkt"), last("soy_cn_12m"), last("exp_12m"), last("enso_wk")
b1, c, c1 = at("soy_brl", year(b[0], -1)), at("soy_cbot", b[0]), at("soy_cbot", year(b[0], -1))
m3, m12 = by["rural_pf_mkt"][-4][1], at("rural_pf_mkt", year(m[0], -1))
p, p12 = last("rural_pf"), at("rural_pf", year(last("rural_pf")[0], -1))
price, credit = b[1] > b1, m[1] < m3
print(json.dumps({"ok": True, "digest": {
    "read": "enough" if price and credit else "short" if price else "neither",
    "soy_brl": [b[1], b[0]], "soy_brl_change_1y": pct(b[1], b1), "cbot_change_1y": pct(c, c1), "fx_change_1y": pct(b[1] / c, b1 / c1),
    "rural_default_market_rate": [m[1], m[0]], "three_months_before": m3, "a_year_before": m12, "rural_default_all": [p[1], p[0]], "all_a_year_before": p12,
    "el_nino_weekly": [w[1], w[0]], "el_nino_3m_avg": last("enso_oni"),
    "el_nino": "very strong" if w[1] >= 2 else "strong" if w[1] >= 1.5 else "under way" if w[1] >= 0.5 else "absent",
    "china_share_12m": [s[1], s[0]], "china_share_a_year_before": at("soy_cn_12m", year(s[0], -1)), "soy_exports_12m_mt": last("soy_exp_12m"),
    "exports_12m_usd_bn": [x[1], x[0]], "exports_a_year_before": at("exp_12m", year(x[0], -1))}}))
