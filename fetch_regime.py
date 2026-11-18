#!/usr/bin/env python3
"""Leading indicators vs markets (Brazil + US). Pulls free public series and writes latest.json and series.json,
recession.json (the dashboard's own recession models) and digest.json (a short summary for the written readings),
each as {rows, meta} except the digest. Standard library only; network via curl. A value read while its market is
trading keeps the clock time of the reading.
Usage: python3 fetch_regime.py <output-dir>. FRED series come from FRED's public CSV download, which needs no key;
with FRED_API_KEY set, they come from FRED's API instead (the same observations)."""
import csv, io, json, math, os, subprocess, sys, time, datetime as dt, urllib.parse as up
from zoneinfo import ZoneInfo

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
TODAY = dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date() # closes before today, plus today's value where a source has one
START = TODAY - dt.timedelta(days=800) # fetch window (year-on-year needs two years)
SHOW = TODAY - dt.timedelta(days=372) # history kept for the charts
ANCHOR = dt.date(2026, 10, 23) # last close before the presidential runoff
S, problems = {}, [] # S[id] = sorted [(date, value)]
LIVE = {} # id -> clock time (Sao Paulo) of a value read while its market was trading
FRED_DOWN = [] # set when FRED's keyless download fails, so the run does not wait on it again

def get(url, timeout=120):
    r = subprocess.run(["curl", "-sS", "-L", "--http1.1", "-m", str(timeout), "--retry", "2", "--retry-all-errors",
                        "-A", "regime-dashboard/1.0", url], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode()[:160] or "empty answer")
    return r.stdout

def put(sid, pairs, today=False):
    pairs = sorted((d, v) for d, v in pairs if START <= d < TODAY or (today and d == TODAY))
    if not pairs:
        raise RuntimeError("no observations")
    S[sid] = pairs

def fred(code, start=None, extra=""):
    key = os.environ.get("FRED_API_KEY")
    if key:
        u = f"https://api.stlouisfed.org/fred/series/observations?series_id={code}&api_key={key}&file_type=json&observation_start={start or START}{extra}"
        return [(dt.date.fromisoformat(o["date"]), float(o["value"])) for o in json.loads(get(u))["observations"] if o["value"] not in ("", ".")]
    # Without a key: the CSV behind FRED's own graphs, with the API's options under their graph names. It answers
    # curl's own client name and refuses others, so no -A here; after one failure the rest of FRED is skipped at once.
    if FRED_DOWN:
        raise RuntimeError("FRED's CSV download did not answer earlier in this run")
    graph = extra.replace("&frequency=m", "&fq=Monthly").replace("&aggregation_method=", "&fam=").replace("&units=", "&transformation=")
    r = subprocess.run(["curl", "-sS", "-L", "--http1.1", "-m", "45", f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}&cosd={start or START}{graph}"],
                       capture_output=True)
    rows = list(csv.reader(io.StringIO(r.stdout.decode(errors="replace")))) if r.returncode == 0 else []
    if not rows or rows[0][0].strip().lower() not in ("observation_date", "date"):
        FRED_DOWN.append(code)
        raise RuntimeError("FRED's CSV download did not answer: " + (r.stderr.decode()[:120] or "unexpected answer"))
    time.sleep(0.4)  # spaced out, as a person clicking through FRED would be
    return [(dt.date.fromisoformat(r[0]), float(r[1])) for r in rows[1:] if len(r) > 1 and r[1] not in ("", ".")]

def treasury_us():
    def curve(kind):
        out = {}
        for year in range((TODAY - dt.timedelta(days=470)).year, TODAY.year + 1):
            u = (f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
                 f"?type=daily_treasury_{kind}&field_tdr_date_value={year}&page&_format=csv")
            for r in csv.DictReader(io.StringIO(get(u).decode())):
                out[dt.datetime.strptime(r["Date"], "%m/%d/%Y").date()] = r
        return out
    def col(table, name):
        return {d: float(r[name]) for d, r in table.items() if r.get(name) not in (None, "", "N/A")}
    nom, real = curve("yield_curve"), curve("real_yield_curve")
    m3, y2, y10, r10 = col(nom, "3 Mo"), col(nom, "2 Yr"), col(nom, "10 Yr"), col(real, "10 YR")
    put("us2y", y2.items()); put("us10y", y10.items()); put("us_real10", r10.items())
    put("us_slope_2s10s", [(d, v - y2[d]) for d, v in y10.items() if d in y2])
    put("us_slope_3m10y", [(d, v - m3[d]) for d, v in y10.items() if d in m3])
    put("us_be10", [(d, v - r10[d]) for d, v in y10.items() if d in r10])

def sgs(code):
    u = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json"
         f"&dataInicial={START:%d/%m/%Y}&dataFinal={TODAY:%d/%m/%Y}")
    return [(dt.datetime.strptime(r["data"], "%d/%m/%Y").date(), float(r["valor"])) for r in json.loads(get(u))]

def sgs_long(code, first): # the Banco Central answers at most ten years per request
    out, a = [], first
    while a <= TODAY:
        b = min(dt.date(a.year + 9, 12, 31), TODAY)
        u = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json"
             f"&dataInicial={a:%d/%m/%Y}&dataFinal={b:%d/%m/%Y}")
        out += [(dt.datetime.strptime(r["data"], "%d/%m/%Y").date(), float(r["valor"])) for r in json.loads(get(u))]
        a = dt.date(b.year + 1, 1, 1)
    return sorted(set(out))

def ptax(code): # the official dollar fixing: the Banco Central series plus today's fixing once published, about 13:00
    pairs = sgs(code)
    q = f"@dataCotacao='{TODAY:%m-%d-%Y}'&$format=json&$select=cotacaoVenda"
    try:
        v = json.loads(get("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarDia(dataCotacao=@dataCotacao)?"
                           + up.quote(q, safe="=&$,'@")))["value"]
        if v and all(d != TODAY for d, _ in pairs):
            pairs.append((TODAY, float(v[-1]["cotacaoVenda"])))
    except Exception:
        pass
    return pairs

def focus(indicator):
    q = (f"$top=500&$filter=Indicador eq '{indicator}' and DataReferencia eq '{TODAY.year + 1}' and baseCalculo eq 0"
         "&$orderby=Data desc&$format=json&$select=Data,Mediana")
    u = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais?" + up.quote(q, safe="=&$,'")
    return [(dt.date.fromisoformat(r["Data"]), float(r["Mediana"])) for r in json.loads(get(u))["value"]]

def yahoo(symbol):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{up.quote(symbol)}?range=2y&interval=1d"
    for wait in (1, 6, 15): # unofficial endpoint: go slowly, back off when it is busy
        time.sleep(wait)
        try:
            r = json.loads(get(u))["chart"]["result"][0]
            break
        except (ValueError, KeyError, TypeError):
            r = None
    if not r:
        raise RuntimeError("no answer from Yahoo Finance")
    off, out = r["meta"].get("gmtoffset", 0), {}
    for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]):
        if c is not None:
            out[dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date()] = float(c)
    t, p = r["meta"].get("regularMarketTime"), r["meta"].get("regularMarketPrice")
    when = dt.datetime.fromtimestamp(t, ZoneInfo("America/Sao_Paulo")) if t else None
    out.pop(TODAY, None)
    if when and p and when.date() == TODAY: # traded today: the price at the time of this run
        out[TODAY] = float(p)
        LIVE[symbol] = when.strftime("%H:%M")
    return list(out.items())

def tesouro():
    pkg = json.loads(get("https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=taxas-dos-titulos-ofertados-pelo-tesouro-direto"))
    url = next(r["url"] for r in pkg["result"]["resources"] if r["format"].upper() == "CSV")
    rows = csv.reader(io.StringIO(get(url, 300).decode("latin-1")), delimiter=";")
    next(rows)
    bonds = {} # (type, maturity) -> {date: buy yield}
    for r in rows:
        if len(r) > 3 and r[0] in ("Tesouro Prefixado", "Tesouro IPCA+") and r[3]:
            d = dt.datetime.strptime(r[2], "%d/%m/%Y").date()
            if START <= d < TODAY:
                bonds.setdefault((r[0], dt.datetime.strptime(r[1], "%d/%m/%Y").date()), {})[d] = float(r[3].replace(",", "."))
    last = max(max(v) for v in bonds.values())
    live = {k: v for k, v in bonds.items() if max(v) >= last - dt.timedelta(days=10) and k[1] > last + dt.timedelta(days=365)}
    nom = sorted(k for k in live if k[0] == "Tesouro Prefixado")
    real = sorted(k for k in live if k[0] == "Tesouro IPCA+")
    put("br_nom_short", live[nom[0]].items())
    put("br_nom_long", live[nom[-1]].items())
    put("br_real_long", live[real[-1]].items())
    put("br_slope", [(d, v - live[nom[0]][d]) for d, v in live[nom[-1]].items() if d in live[nom[0]]])
    n, r = min(((a, b) for a in nom for b in real), key=lambda p: abs((p[0][1] - p[1][1]).days))
    put("br_breakeven", [(d, ((1 + v / 100) / (1 + live[r][d] / 100) - 1) * 100) for d, v in live[n].items() if d in live[r]])
    return {"br_nom_short": nom[0][1].year, "br_nom_long": nom[-1][1].year, "br_real_long": real[-1][1].year,
            "br_breakeven": f"{n[1].year} fixed vs {r[1].year} inflation-linked"}

def at(pairs, day): # last observation on or before a day
    best = None
    for d, v in pairs:
        if d > day:
            break
        best = (d, v)
    return best

def ecb_fx(): # same-clock fixings (14:15 CET) for the real and its peers
    u = (f"https://data-api.ecb.europa.eu/service/data/EXR/D.USD+BRL+MXN+ZAR+IDR+INR+KRW+PLN.EUR.SP00.A"
         f"?startPeriod={TODAY - dt.timedelta(days=470)}&format=csvdata")
    day = {}
    for r in csv.DictReader(io.StringIO(get(u).decode())):
        day.setdefault(dt.date.fromisoformat(r["TIME_PERIOD"]), {})[r["CURRENCY"]] = float(r["OBS_VALUE"])
    days = sorted(d for d, v in day.items() if len(v) == 8 and d <= TODAY)
    usd = {d: {c: v / day[d]["USD"] for c, v in day[d].items() if c != "USD"} for d in days} # units per US dollar
    base = usd[max(d for d in days if d <= ANCHOR)]
    basket = [(d, sum(usd[d][c] / base[c] for c in base if c != "BRL") / 6 * 100) for d in days]
    put("peers", basket, True)
    put("brl_resid", [(d, usd[d]["BRL"] / base["BRL"] * 100 - b) for d, b in basket], True)

def derived():
    if "ibov" in S and "usdbrl" in S:
        brl = dict(S["usdbrl"])
        put("ibov_usd", [(d, v / brl[d]) for d, v in S["ibov"] if d in brl], True)
        if "ibov" in LIVE and S["ibov_usd"][-1][0] == TODAY:
            LIVE["ibov_usd"] = LIVE["ibov"]
    if "us_cpi" in S:
        idx = dict(S["us_cpi"])
        put("us_cpi_yoy", [(d, (v / idx[d.replace(year=d.year - 1)] - 1) * 100) for d, v in S["us_cpi"] if d.replace(year=d.year - 1) in idx])
        del S["us_cpi"]

# id: (name, region, role, unit, decimals, change kind, stress direction, source)
IND = {
 "usdbrl": ("US dollar in reais, official fixing (PTAX)", "Brazil", "market", "R$", 4, "pct", 1, "Banco Central SGS 1"),
 "peers": ("Emerging-market peer currencies vs the dollar (Mexico, South Africa, Indonesia, India, Korea, Poland), runoff eve = 100", "Brazil", "market", "index", 1, "pct", 1, "European Central Bank reference rates, own calculation"),
 "brl_resid": ("Real versus the peer basket since the runoff eve", "Brazil", "leading", "pp", 1, "diff", 1, "European Central Bank reference rates, own calculation"),
 "ibov": ("Ibovespa", "Brazil", "market", "points", 0, "pct", -1, "Yahoo Finance ^BVSP"),
 "ibov_usd": ("Ibovespa in US dollars", "Brazil", "market", "US$", 0, "pct", -1, "Yahoo Finance and Banco Central, own calculation"),
 "br_nom_long": ("Long fixed-rate government bond yield", "Brazil", "market", "%", 2, "diff", 1, "Tesouro Transparente"),
 "br_nom_short": ("Short fixed-rate government bond yield", "Brazil", "market", "%", 2, "diff", 1, "Tesouro Transparente"),
 "br_slope": ("Fixed-rate curve slope, long minus short", "Brazil", "leading", "pp", 2, "diff", 1, "Tesouro Transparente, own calculation"),
 "br_real_long": ("Long inflation-linked bond real yield", "Brazil", "market", "%", 2, "diff", 1, "Tesouro Transparente"),
 "br_breakeven": ("Implied inflation, fixed versus inflation-linked", "Brazil", "leading", "%", 2, "diff", 1, "Tesouro Transparente, own calculation"),
 "focus_ipca": ("Focus survey: inflation expected for next year", "Brazil", "leading", "%", 2, "diff", 1, "Banco Central Focus"),
 "focus_selic": ("Focus survey: policy rate expected for end of next year", "Brazil", "leading", "%", 2, "diff", 1, "Banco Central Focus"),
 "selic": ("Policy rate target (Selic)", "Brazil", "lagging", "%", 2, "diff", 0, "Banco Central SGS 432"),
 "br_ipca12": ("Consumer inflation, 12 months", "Brazil", "lagging", "%", 2, "diff", 1, "Banco Central SGS 13522"),
 "br_unemp": ("Unemployment rate", "Brazil", "lagging", "%", 1, "diff", 1, "Banco Central SGS 24369"),
 "br_delinq": ("Loan delinquency rate, all credit", "Brazil", "lagging", "%", 2, "diff", 1, "Banco Central SGS 21082"),
 "us_slope_2s10s": ("Treasury curve slope, 10-year minus 2-year", "United States", "leading", "pp", 2, "diff", 0, "US Treasury, own calculation"),
 "us_slope_3m10y": ("Treasury curve slope, 10-year minus 3-month", "United States", "leading", "pp", 2, "diff", 0, "US Treasury, own calculation"),
 "us_hy": ("High-yield credit spread", "United States", "leading", "pp", 2, "diff", 1, "FRED BAMLH0A0HYM2"),
 "us_claims": ("Initial jobless claims, weekly", "United States", "leading", "thousand", 0, "pct", 1, "FRED ICSA"),
 "us_permits": ("Building permits, annual rate", "United States", "leading", "thousand", 0, "pct", -1, "FRED PERMIT"),
 "us_lending": ("Banks tightening business loan standards, net share", "United States", "leading", "%", 1, "diff", 1, "FRED DRTSCILM"),
 "us_nfci": ("Chicago Fed financial conditions index", "United States", "leading", "index", 2, "diff", 1, "FRED NFCI"),
 "us2y": ("Treasury 2-year yield", "United States", "market", "%", 2, "diff", 0, "US Treasury"),
 "us10y": ("Treasury 10-year yield", "United States", "market", "%", 2, "diff", 1, "US Treasury"),
 "us_real10": ("Treasury 10-year real yield", "United States", "market", "%", 2, "diff", 1, "US Treasury"),
 "us_be10": ("Implied inflation, 10-year", "United States", "market", "%", 2, "diff", 1, "US Treasury, own calculation"),
 "spx": ("S&P 500", "United States", "market", "points", 0, "pct", -1, "Yahoo Finance ^GSPC"),
 "vix": ("Implied volatility index (VIX)", "United States", "market", "points", 1, "diff", 1, "Yahoo Finance ^VIX"),
 "dxy": ("US dollar index", "United States", "market", "index", 1, "pct", 1, "Yahoo Finance DX-Y.NYB"),
 "fed_funds": ("Policy rate target, upper bound", "United States", "lagging", "%", 2, "diff", 0, "FRED DFEDTARU"),
 "us_unemp": ("Unemployment rate", "United States", "lagging", "%", 1, "diff", 1, "FRED UNRATE"),
 "us_cpi_yoy": ("Consumer inflation, 12 months", "United States", "lagging", "%", 1, "diff", 1, "FRED CPIAUCSL, own calculation"),
}
JOBS = [("usdbrl", ptax, 1), ("selic", sgs, 432), ("br_ipca12", sgs, 13522), ("br_unemp", sgs, 24369), ("br_delinq", sgs, 21082),
        ("focus_ipca", focus, "IPCA"), ("focus_selic", focus, "Selic"),
        ("ibov", yahoo, "^BVSP"), ("spx", yahoo, "^GSPC"), ("vix", yahoo, "^VIX"), ("dxy", yahoo, "DX-Y.NYB"),
        ("us_hy", fred, "BAMLH0A0HYM2"), ("us_claims", fred, "ICSA"), ("us_permits", fred, "PERMIT"), ("us_lending", fred, "DRTSCILM"),
        ("us_nfci", fred, "NFCI"), ("fed_funds", fred, "DFEDTARU"), ("us_unemp", fred, "UNRATE"), ("us_cpi", fred, "CPIAUCSL")]

notes = {}
for sid, fn, arg in JOBS:
    try:
        put(sid, fn(arg), fn in (ptax, yahoo))
        if arg in LIVE:
            LIVE[sid] = LIVE.pop(arg)
    except Exception as e:
        problems.append(f"{sid}: {e}")
for name, fn in (("tesouro", tesouro), ("treasury_us", treasury_us), ("ecb_fx", ecb_fx)):
    try:
        notes = fn() or notes
    except Exception as e:
        problems.append(f"{name}: {e}")
try:
    derived()
except Exception as e:
    problems.append(f"derived: {e}")
if "us_claims" in S:
    S["us_claims"] = [(d, v / 1000) for d, v in S["us_claims"]]

latest, series = [], []
for sid, (name, region, role, unit, dec, kind, stress, source) in IND.items():
    if sid not in S:
        continue
    pairs = S[sid]
    day, val = pairs[-1]
    def change(ref_day, slack):
        ref = at(pairs, ref_day)
        if not ref or ref[0] == day or (ref_day - ref[0]).days > slack: # no observation near enough: leave empty
            return None
        return (round((val / ref[1] - 1) * 100, 1) if kind == "pct" else round(val - ref[1], max(dec, 2))) + 0.0
    latest.append({"id": sid, "name": name + (f" ({notes[sid]})" if sid in notes else ""), "region": region, "role": role,
                   "unit": unit, "value": round(val, dec) + 0.0, "dec": dec, "as_of": day.isoformat(), "kind": kind, "stress": stress,
                   "chg_1w": change(day - dt.timedelta(days=7), 6), "chg_1m": change(day - dt.timedelta(days=30), 15),
                   "chg_3m": change(day - dt.timedelta(days=91), 45), "chg_runoff": change(ANCHOR, 6) if day > ANCHOR else None,
                   "source": source})
    if day == TODAY and sid in LIVE:
        latest[-1]["as_of_time"] = LIVE[sid]
    series += [{"id": sid, "date": d.isoformat(), "value": round(v, 4)} for d, v in pairs if d >= SHOW]

if len(latest) < 20: # 25 series come from sources other than FRED; fewer than 20 means a source-wide failure
    print(json.dumps({"ok": False, "series": len(latest), "problems": problems}))
    sys.exit(2)
meta = [{"label": "fetch_regime.py", "value": open(os.path.abspath(__file__), encoding="utf-8").read(), "type": "code", "lang": "python"},
        {"label": "Inputs", "value": "Banco Central do Brasil (SGS, Focus), Tesouro Transparente, European Central Bank, US Treasury, FRED, Yahoo Finance"},
        {"label": "Run", "value": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
        {"label": "Skipped", "value": "; ".join(problems) or "none"}]
for name, rows in (("latest.json", latest), ("series.json", series)):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "meta": meta}, f, ensure_ascii=False, separators=(",", ":"))
def read_at(k): # the same rule the dashboard page applies to the newest day
    gap, yld = S.get("brl_resid"), S.get("br_nom_long")
    if not gap or not yld or len(gap) < abs(k):
        return None
    week = lambda rows: [v for d, v in rows if ANCHOR < d <= ANCHOR + dt.timedelta(days=7)]
    day, now = gap[k]
    y = at(yld, day)
    if not week(gap) or not week(yld) or not y:
        return None
    return "repricing" if now > max(week(gap)) else "overshoot" if now < max(week(gap)) / 2 and y[1] < max(week(yld)) else "mixed"
# Recession models: probit of a recession at some point in the next twelve months, fitted on 18 November 2026.
# United States: NBER dates, January 1972 to October 2024 (634 months). Brazil: CODACE dates, July 2003 to December 2024 (258 months).
US_MODEL, US_MEAN = {"const": -0.3058, "spread": -0.4781, "permits": -0.0222, "nfci": 0.9837}, {"spread": 1.5549, "permits": -0.4791, "nfci": -0.0057}
BR_MODEL, BR_MEAN = {"const": -0.3817, "dselic": 0.0618, "ibc": -0.1015}, {"dselic": -0.5561, "ibc": 1.9677}
CODACE = (("2001-04", "2001-12"), ("2003-01", "2003-06"), ("2008-10", "2009-03"), ("2014-04", "2016-12"), ("2020-01", "2020-06"))
REC = []

def back(m, k): # first day of the month k months before m
    y, mo = divmod(m.year * 12 + m.month - 1 - k, 12)
    return dt.date(y, mo + 1, 1)

def monthly(pairs): # average by calendar month
    acc = {}
    for d, v in pairs:
        acc.setdefault(d.replace(day=1), []).append(v)
    return {m: sum(v) / len(v) for m, v in acc.items()}

def fill(series): # one missing month, such as October 2025 in the US shutdown, takes the average of its neighbours
    for m in list(series):
        if back(m, -2) in series and back(m, -1) not in series:
            series[back(m, -1)] = (series[m] + series[back(m, -2)]) / 2
    return series

def score(model, mean, x): # probability in percent, and each input's pull on it against its own average in the sample
    z = model["const"] + sum(model[k] * x[k] for k in x)
    return 50 * (1 + math.erf(z / math.sqrt(2))), {k: round(model[k] * (x[k] - mean[k]), 2) for k in x}

def rec_put(sid, items, dec=2):
    REC.extend({"id": sid, "date": m.isoformat(), "value": round(v, dec) + 0.0} for m, v in sorted(items) if m >= dt.date(2000, 1, 1))

def recent(sid, probs, rows, k, last=None): # the inputs and their pull, for the latest five years; an input stops at its own latest reading
    first = back(max(rows), 59)
    rec_put("in_" + sid + "_" + k, [(m, x[k]) for m, x in rows.items() if m >= first and (last is None or m <= last)])
    rec_put("ctb_" + sid + "_" + k, [(m, probs[m][1][k]) for m in rows if m >= first])

def summary(probs, rows):
    m = max(probs)
    ago = lambda k: round(probs[back(m, k)][0], 1) if back(m, k) in probs else None
    return {"as_of": m.isoformat(), "p": round(probs[m][0], 1), "p_1m": ago(1), "p_3m": ago(3), "p_12m": ago(12),
            "inputs": {k: round(v, 2) for k, v in rows[m].items()}, "drivers": probs[m][1]}

def rec_us(): # curve slope (10-year minus 3-month), building permits against a year earlier, Chicago Fed financial conditions
    first = "1998-01-01"
    gs10, tb3, nfci = monthly(fred("GS10", first)), monthly(fred("TB3MS", first)), monthly(fred("NFCI", first, "&frequency=m&aggregation_method=avg"))
    permit, usrec = fill(monthly(fred("PERMIT", first))), monthly(fred("USREC", first))
    rows = {m: {"spread": gs10[m] - tb3[m], "permits": 100 * math.log(permit[m] / permit[back(m, 12)]), "nfci": nfci[m]}
            for m in gs10 if m in tb3 and m in nfci and m in permit and back(m, 12) in permit}
    probs = {m: score(US_MODEL, US_MEAN, x) for m, x in rows.items()}
    rec_put("rec_us", [(m, p[0]) for m, p in probs.items()], 1)
    rec_put("nber", [(m, 1.0) for m, v in usrec.items() if v >= 1], 0)
    for k in ("spread", "permits", "nfci"):
        recent("us", probs, rows, k)
    REC.append({"id": "base_us", "date": "2024-10-01", "value": 23.8}) # share of months, January 1972 to October 2024, with a recession in the next twelve
    return summary(probs, rows)

def rec_br(): # change in the policy rate over twelve months, and six-month annualised growth of the central bank's activity index
    first = dt.date(2001, 1, 1)
    selic, ibc = monthly(sgs_long(4189, first)), monthly(sgs_long(24364, first))
    rows = {m: {"dselic": selic[m] - selic[back(m, 12)], "ibc": 200 * math.log(ibc[m] / ibc[back(m, 6)])}
            for m in selic if back(m, 12) in selic and m in ibc and back(m, 6) in ibc}
    seen = max(rows) # the activity index arrives about two months late: its latest reading stands in for the months after it
    for m in selic:
        if m > seen and back(m, 12) in selic:
            rows[m] = {"dselic": selic[m] - selic[back(m, 12)], "ibc": rows[seen]["ibc"]}
    probs = {m: score(BR_MODEL, BR_MEAN, x) for m, x in rows.items()}
    rec_put("rec_br", [(m, p[0]) for m, p in probs.items()], 1)
    codace = set()
    for a, b in CODACE:
        m = dt.date.fromisoformat(a + "-01")
        while m <= dt.date.fromisoformat(b + "-01"):
            codace.add(m)
            m = back(m, -1)
    rec_put("codace", [(m, 1.0) for m in codace], 0)
    recent("br", probs, rows, "dselic")
    recent("br", probs, rows, "ibc", seen)
    REC.append({"id": "base_br", "date": "2024-12-01", "value": 30.2}) # the same share for Brazil, July 2003 to December 2024
    out = summary(probs, rows)
    out["ibc_as_of"] = seen.isoformat()
    return out

recession = {}
for key, fn in (("br", rec_br), ("us", rec_us)):
    try:
        recession[key] = fn()
    except Exception as e:
        problems.append(f"recession_{key}: {e}")
if REC:
    rmeta = [meta[0], {"label": "Inputs", "value": "FRED: GS10, TB3MS, PERMIT, NFCI, USREC. Banco Central do Brasil SGS 4189 (policy rate, monthly) and 24364 (IBC-Br, seasonally adjusted). CODACE recession dates."},
             {"label": "Model", "value": "Probit of a recession at some point in the next twelve months. United States, fitted on NBER dates from January 1972 to October 2024: area under the ROC curve 0.93 in sample and 0.88 when each recession is left out of the fit in turn. Brazil, fitted on CODACE dates from July 2003 to December 2024, three recessions: 0.76 and 0.71."},
             {"label": "Run", "value": meta[2]["value"]}, {"label": "Skipped", "value": "; ".join(problems) or "none"}]
    with open(os.path.join(OUT, "recession.json"), "w", encoding="utf-8") as f:
        json.dump({"rows": REC, "meta": rmeta}, f, ensure_ascii=False, separators=(",", ":"))

# Digest for the written readings: the same rules the page applies, worked out here so the reader of the digest sees what the page shows.
def signal(pts, kind, stress): # four-week move against its own typical four-week move over the year, signed so that positive is stress
    moves, k = [], -1
    for i in range(1, len(pts)):
        while k + 1 < i and pts[k + 1][0] <= pts[i][0] - dt.timedelta(days=28):
            k += 1
        if k >= 0:
            moves.append((pts[i][1] / pts[k][1] - 1) * 100 if kind == "pct" else pts[i][1] - pts[k][1])
    typical = math.sqrt(sum(m * m for m in moves) / (len(moves) or 1))
    move = moves[-1] if moves else 0
    sc = stress * move / typical if typical else 0
    state = "unscored" if not stress or len(moves) < 3 or not typical else "worsening" if sc > 0.5 else "improving" if sc < -0.5 else "neutral"
    return state, round(move, 2), round(typical, 2), round(sc, 2)

digest = {"run_sao_paulo": dt.datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d %H:%M"), "intraday": LIVE, "recession": recession}
for key, region in (("br", "Brazil"), ("us", "United States")):
    part, counts = {}, {"worsening": 0, "improving": 0, "neutral": 0}
    for r in latest:
        if r["region"] != region:
            continue
        state = signal([p for p in S[r["id"]] if p[0] >= SHOW], r["kind"], r["stress"])[0]
        counts[state] = counts.get(state, 0) + 1
        part[r["id"]] = [r["value"], r["as_of"] + (" " + r["as_of_time"] if r.get("as_of_time") else ""), r["chg_1w"], r["chg_1m"], r["chg_3m"], r["chg_runoff"], state]
    counts.pop("unscored", None)
    digest[key] = {"signals": counts, "series": part}
gap, yld = S.get("brl_resid"), S.get("br_nom_long")
if gap and yld:
    week = lambda rows: [v for d, v in rows if ANCHOR < d <= ANCHOR + dt.timedelta(days=7)]
    digest["br"].update(read=read_at(-1), read_before=read_at(-2), gap_now=round(gap[-1][1], 1), gap_peak=round(max(week(gap)), 1),
                        yield_now=round(yld[-1][1], 2), yield_peak=round(max(week(yld)), 2))

def ai_digest(): # the AI-trade read and the footprint of acceleration, as the page works them out from FRED
    first = (TODAY - dt.timedelta(days=800)).isoformat()
    ndx, spx = sorted(fred("NASDAQ100", first)), dict(fred("SP500", first))
    bbb, real = sorted(fred("BAMLC0A4CBBB", first)), sorted(fred("DFII30", first))
    spend, chips = sorted(fred("A679RC1Q027SBEA", "2019-01-01", "&units=pc1")), sorted(fred("IPG3344S", "2019-01-01", "&units=pc1"))
    end = ndx[-1][0]
    year = end.replace(year=end.year - 1)
    avg = lambda rows: {rows[i][0]: sum(v for _, v in rows[i - 199:i + 1]) / 200 for i in range(199, len(rows))}
    ratio = [(d, v / spx[d]) for d, v in ndx if d in spx]
    base = next(v for d, v in ratio if d >= year)
    lead = [(d, v / base * 100) for d, v in ratio]
    lead_avg, ndx_avg, real_avg = avg(lead), avg(ndx), avg(real)
    lead_gap = round((lead[-1][1] / lead_avg[lead[-1][0]] - 1) * 100, 1)
    trend = round((ndx[-1][1] / ndx_avg[end] - 1) * 100, 1)
    state, move, typical, sc = signal([p for p in bbb if p[0] >= year], "diff", 1)
    tests = [lead_gap >= 0, trend >= 0, sc <= 1]
    near = lambda rows, k: min(rows, key=lambda p: abs((p[0] - (rows[len(rows) - 1 - k][0] - dt.timedelta(days=365))).days))[1]
    spend_now, spend_then = spend[-1][1], near(spend, 0)
    chips_now, chips_then = sum(chips[-1 - k][1] for k in range(3)) / 3, sum(near(chips, k) for k in range(3)) / 3
    foot = [spend_now > spend_then, chips_now > chips_then, real[-1][1] >= real_avg[real[-1][0]], tests[0]]
    return {"read": ["continuation", "strain", "unwinding", "unwinding"][tests.count(False)], "lead": tests[0], "trend": tests[1], "credit": tests[2],
            "lead_gap": lead_gap, "trend_gap": trend, "bbb_now": bbb[-1][1], "bbb_move": move, "bbb_typical": typical, "ndx_now": ndx[-1][1], "as_of": end.isoformat(),
            "footprint": ["absent", "absent", "mixed", "visible", "visible"][foot.count(True)], "spend_now": round(spend_now, 1), "spend_then": round(spend_then, 1),
            "chips_now": round(chips_now, 1), "chips_then": round(chips_then, 1), "real30_now": real[-1][1], "real30_avg": round(real_avg[real[-1][0]], 2)}

try:
    digest["ai"] = ai_digest()
except Exception as e:
    problems.append(f"ai_digest: {e}")
digest["problems"] = problems
with open(os.path.join(OUT, "digest.json"), "w", encoding="utf-8") as f:
    json.dump(digest, f, ensure_ascii=False, separators=(",", ":"))
print(json.dumps({"ok": True, "series": len(latest), "rows": len(series), "problems": problems, "intraday": LIVE,
                  "newest": max(r["as_of"] for r in latest), "brazil_read": read_at(-1), "brazil_read_before": read_at(-2),
                  "recession": {k: [v["p"], v["as_of"]] for k, v in recession.items()}}))
