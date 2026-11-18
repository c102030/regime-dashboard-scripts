#!/usr/bin/env python3
"""Brazil's exports and agro: El Nino, rural loan delinquency, soybeans in Chicago and in reais, soybean exports by destination.
Writes agro_series.json as {rows, meta}. Standard library only; network via curl.
Usage: python3 fetch_agro.py <output-dir>"""
import json, os, re, subprocess, sys, time, datetime as dt
from zoneinfo import ZoneInfo

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
TODAY = dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
rows, problems, ids = [], [], []

def get(url, body=None, timeout=120):
    post = ["-X", "POST", "-H", "Content-Type: application/json", "-d", body] if body else []
    r = subprocess.run(["curl", "-sS", "-L", "--http1.1", "-m", str(timeout), "--retry", "2", "--retry-all-errors",
                        "-A", "regime-dashboard/1.0"] + post + [url], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode()[:160] or "empty answer")
    return r.stdout

def put(sid, pairs, dec=2):
    pairs = sorted((d, v) for d, v in pairs if d <= TODAY)
    if not pairs:
        raise RuntimeError(sid + ": no observations")
    ids.append(sid)
    rows.extend({"id": sid, "date": d.isoformat(), "value": round(v, dec) + 0.0} for d, v in pairs)

def sgs(code, first):
    u = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json"
         f"&dataInicial={first:%d/%m/%Y}&dataFinal={TODAY:%d/%m/%Y}")
    return [(dt.datetime.strptime(r["data"], "%d/%m/%Y").date(), float(r["valor"])) for r in json.loads(get(u))]

def el_nino(): # NOAA Climate Prediction Center: sea-surface temperature in the Nino 3.4 region against normal
    weekly = []
    for line in get("https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for").decode().splitlines():
        m = re.match(r"\s*(\d{2}[A-Z]{3}\d{4})", line)
        nums = re.findall(r"-?\d+\.\d", line[m.end():]) if m else []
        if len(nums) == 8: # four regions, temperature then anomaly; Nino 3.4 is the third
            weekly.append((dt.datetime.strptime(m.group(1), "%d%b%Y").date(), float(nums[5])))
    put("enso_wk", [p for p in weekly if p[0] >= dt.date(2023, 1, 1)], 1)
    mid = {s: i + 1 for i, s in enumerate("DJF JFM FMA MAM AMJ MJJ JJA JAS ASO SON OND NDJ".split())}
    oni = []
    for line in get("https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt").decode().splitlines():
        p = line.split()
        if len(p) == 4 and p[0] in mid and p[1].isdigit():
            oni.append((dt.date(int(p[1]), mid[p[0]], 1), float(p[3])))
    put("enso_oni", [p for p in oni if p[0] >= dt.date(1996, 1, 1)], 2)

def credit(): # Banco Central: rural loans more than 90 days overdue, percent of the balance
    for sid, code in (("rural_pf", 21148), ("rural_pf_mkt", 21146), ("rural_pj", 21136)):
        put(sid, sgs(code, dt.date(2019, 1, 1)), 2)

def soy(): # Chicago soybean futures (US cents per bushel) and the official dollar rate; 2.2046 bushels to a 60-kg sack
    u, r = "https://query1.finance.yahoo.com/v8/finance/chart/ZS%3DF?range=2y&interval=1d", None
    for wait in (1, 6, 15): # unofficial endpoint: go slowly, back off when it is busy
        time.sleep(wait)
        try:
            r = json.loads(get(u))["chart"]["result"][0]
            break
        except (ValueError, KeyError, TypeError):
            r = None
    if not r:
        raise RuntimeError("no answer from Yahoo Finance")
    off, close = r["meta"].get("gmtoffset", 0), {}
    for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]):
        if c is not None:
            close[dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date()] = c / 100
    close = {d: v for d, v in close.items() if d < TODAY} # closes only
    put("soy_cbot", close.items(), 2)
    ptax = sgs(1, TODAY - dt.timedelta(days=760))
    def rate(day):
        seen = [v for d, v in ptax if d <= day]
        return seen[-1] if seen else None
    put("soy_brl", [(d, v * 2.2046 * rate(d)) for d, v in close.items() if rate(d)], 1)

def exports(): # Comex Stat, Brazil's trade ministry: monthly exports, all goods and soybeans by destination
    def ask(filters, details): # the month range applies inside every year, so it has to run from January to December
        body = json.dumps({"flow": "export", "monthDetail": True, "period": {"from": f"{TODAY.year - 5}-01", "to": f"{TODAY.year}-12"},
                           "filters": filters, "details": details, "metrics": ["metricFOB", "metricKG"]})
        answer = json.loads(get("https://api-comexstat.mdic.gov.br/general?language=en", body, 180))
        return [(dt.date(int(r["year"]), int(r["monthNumber"]), 1), r) for r in answer["data"]["list"]]
    def rolling(month): # sum of the twelve months ending at each month, only where all twelve are present
        days = sorted(month)
        return {d: sum(month[x] for x in days[i - 11:i + 1]) for i, d in enumerate(days)
                if i >= 11 and (d.year - days[i - 11].year) * 12 + d.month - days[i - 11].month == 11}
    total = {d: float(r["metricFOB"]) / 1e9 for d, r in ask([], [])}
    put("exp_m", total.items(), 2)
    put("exp_12m", rolling(total).items(), 1)
    time.sleep(3)
    world, china = {}, {}
    for d, r in ask([{"filter": "heading", "values": ["1201"]}], ["country"]):
        world[d] = world.get(d, 0.0) + float(r["metricKG"]) / 1e9
        if r["country"] == "China":
            china[d] = china.get(d, 0.0) + float(r["metricKG"]) / 1e9
    put("soy_exp_m", world.items(), 2)
    put("soy_cn_m", [(d, china.get(d, 0.0) / v * 100) for d, v in world.items() if v], 1)
    w12, c12 = rolling(world), rolling({d: china.get(d, 0.0) for d in world})
    put("soy_exp_12m", w12.items(), 1)
    put("soy_cn_12m", [(d, c12[d] / v * 100) for d, v in w12.items() if v], 1)

for name, fn in (("el_nino", el_nino), ("credit", credit), ("soy", soy), ("exports", exports)):
    try:
        fn()
    except Exception as e:
        problems.append(f"{name}: {e}")

if len(ids) < 9:
    print(json.dumps({"ok": False, "series": len(ids), "problems": problems}))
    sys.exit(2)
meta = [{"label": "fetch_agro.py", "value": open(os.path.abspath(__file__), encoding="utf-8").read(), "type": "code", "lang": "python"},
        {"label": "Inputs", "value": "NOAA Climate Prediction Center (El Nino indices), Banco Central do Brasil (SGS), Yahoo Finance (Chicago soybean futures), Comex Stat (Brazil's trade ministry)"},
        {"label": "Run", "value": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
        {"label": "Skipped", "value": "; ".join(problems) or "none"}]
with open(os.path.join(OUT, "agro_series.json"), "w", encoding="utf-8") as f:
    json.dump({"rows": rows, "meta": meta}, f, ensure_ascii=False, separators=(",", ":"))
newest, value = {}, {}
for r in rows: # rows of one series are in date order, so the last one seen is its latest
    newest[r["id"]], value[r["id"]] = r["date"], r["value"]
keys = ("enso_wk", "enso_oni", "rural_pf", "rural_pf_mkt", "soy_cbot", "soy_brl", "soy_exp_12m", "soy_cn_12m", "exp_12m")
print(json.dumps({"ok": True, "series": len(ids), "rows": len(rows), "problems": problems,
                  "headline": {k: [value.get(k), newest.get(k)] for k in keys}}))
