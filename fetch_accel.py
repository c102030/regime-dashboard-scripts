#!/usr/bin/env python3
"""AI acceleration, measured from outside the labs: capability benchmarks, lab revenue, AI chips delivered,
AI data centers energized and US data center construction. Writes accel_series.json and accel_sites.json as {rows, meta}.
Standard library only; network via curl.
Usage: python3 fetch_accel.py <output-dir> [base] (with "base" it also writes accel_base.json, the schedule as it stands today)"""
import csv, io, json, os, re, subprocess, sys, zipfile, datetime as dt
from zoneinfo import ZoneInfo

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
BASE = len(sys.argv) > 2 and sys.argv[2] == "base"
TODAY = dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
EPOCH = "https://epoch.ai/data/"
rows, sites, problems, ids = [], [], [], []

def get(url, timeout=180):
    r = subprocess.run(["curl", "-sS", "-L", "--http1.1", "-m", str(timeout), "--retry", "2", "--retry-all-errors",
                        "-A", "regime-dashboard/1.0", url], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode()[:160] or "empty answer")
    return r.stdout

def table(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def day(v):
    try:
        return dt.date.fromisoformat((v or "")[:10])
    except ValueError:
        return None

def put(sid, pairs, dec=2):
    pairs = sorted((d, v) for d, v in pairs if d is not None and v is not None)
    if not pairs:
        raise RuntimeError(sid + ": no observations")
    ids.append(sid)
    rows.extend({"id": sid, "date": d.isoformat(), "value": round(v, dec) + 0.0} for d, v in pairs)

def frontier(pairs, carry=True): # best value so far, one point for each new record, carried to today
    best, out = None, []
    for d, v in sorted(p for p in pairs if p[0] is not None and p[1] is not None and p[0] <= TODAY):
        if best is None or v > best:
            best = v
            if out and out[-1][0] == d: # two records on one day: keep the higher
                out.pop()
            out.append((d, v))
    if out and carry and out[-1][0] < TODAY:
        out.append((TODAY, best))
    return out

def month_ends(first, last):
    d, out = dt.date(first.year, first.month, 1), []
    while True:
        d = (d + dt.timedelta(days=32)).replace(day=1)
        end = d - dt.timedelta(days=1)
        if end > last:
            return out
        out.append(end)

def capabilities(): # Epoch AI benchmarking hub: one zip with every benchmark it tracks
    z = zipfile.ZipFile(io.BytesIO(get(EPOCH + "benchmark_data.zip")))
    read = lambda name: table(z.read(name))
    eci = [(day(r["date"]), num(r["eci"]), r["Accessibility group"]) for r in read("epoch_capabilities_index/eci_scores.csv")]
    eci = [r for r in eci if r[0] and r[0] >= dt.date(2023, 1, 1)]
    put("eci_front", frontier((d, v) for d, v, g in eci), 1)
    put("eci_open", frontier((d, v) for d, v, g in eci if g == "Open weights"), 1)
    metr = [(day(r["Release date"]), num(r["Time horizon"])) for r in read("metr_time_horizons_external.csv")]
    put("metr_h50", frontier((p for p in metr if p[0] and p[0] >= dt.date(2023, 1, 1)), carry=False), 2)
    for sid, name, col in (("rd_posttrain", "posttrainbench_external.csv", "Average (%)"), ("rd_swe", "frontierswe_external.csv", "Score"),
                           ("rd_rli", "rli_external.csv", "Score")):
        try:
            put(sid, frontier((day(r["Release date"]), num(r[col]) * 100) for r in read(name) if num(r[col]) is not None), 1)
        except Exception as e:
            problems.append(f"{sid}: {e}")

def revenue(): # Epoch AI companies hub: every public report of annualized revenue
    reports = table(get(EPOCH + "ai_companies_revenue_reports.csv"))
    for sid, company in (("rev_openai", "OpenAI"), ("rev_anthropic", "Anthropic")):
        seen = {}
        for r in reports:
            d, v = day(r["Date"]), num(r["Annualized revenue (USD)"])
            if r["Company"] == company and r["Scope"] == "Full company" and d and v and dt.date(2023, 1, 1) <= d <= TODAY:
                seen[d] = max(v / 1e9, seen.get(d, 0))
        put(sid, seen.items(), 1)

def chips(): # Epoch AI chip sales hub: cumulative deliveries by chip designer, in H100-equivalents and in megawatts
    z = zipfile.ZipFile(io.BytesIO(get(EPOCH + "ai_chip_sales.zip")))
    h, mw = {}, {}
    for r in table(z.read("cumulative_timelines_by_designer.csv")):
        d, who = day(r["End date"]), r["Chip manufacturer"]
        if d and num(r["Compute estimate in H100e (median)"]) is not None:
            h.setdefault(d, {})[who] = num(r["Compute estimate in H100e (median)"])
            mw.setdefault(d, {})[who] = num(r["Power in MW (median)"]) or 0.0
    kept, most = [], 0
    for d in sorted(h): # a quarter still missing a designer would understate the stock: leave it out
        if len(h[d]) >= most and d <= TODAY:
            most = len(h[d])
            kept.append(d)
    stock = {d: sum(h[d].values()) / 1e6 for d in kept}
    put("chips_h", stock.items(), 2)
    put("chips_gw", [(d, sum(mw[d].values()) / 1000) for d in kept], 2)
    put("chips_add", [(d, stock[d] - stock[kept[i - 1]]) for i, d in enumerate(kept) if i], 2)
    ago = lambda d: next((p for p in kept if abs((d - p).days - 365) <= 3), None)
    put("chips_mult", [(d, stock[d] / stock[ago(d)]) for d in kept if ago(d)], 2)

def centers(): # Epoch AI data centers hub: each site's timeline of power and compute, observed and scheduled
    info = {r["Name"]: r for r in table(get(EPOCH + "data_centers/data_centers.csv"))}
    tag = lambda v: re.sub(r" #(\w+)", r" (\1)", v or "")
    plain = lambda v: re.sub(r"\s+", " ", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", v or "")).strip()
    by = {}
    for r in table(get(EPOCH + "data_centers/data_center_timelines.csv")):
        d = day(r["Date"])
        if d and r["Data center"]:
            by.setdefault(r["Data center"], []).append((d, num(r["IT power (MW)"]), num(r["H100 equivalents"]), r["Construction status"]))
    def stock(when, k):
        total = 0.0
        for line in by.values():
            last = [p[k] for p in line if p[0] <= when and p[k] is not None]
            total += last[-1] if last else 0.0
        return total
    past = month_ends(dt.date(2023, 12, 1), TODAY) + [TODAY]
    plan = [TODAY] + month_ends(TODAY.replace(day=1), dt.date(2028, 12, 31))
    put("sites_gw", [(d, stock(d, 1) / 1000) for d in past], 2)
    put("sites_gw_plan", [(d, stock(d, 1) / 1000) for d in plan], 2)
    put("sites_h", [(d, stock(d, 2) / 1e6) for d in past], 2)
    put("sites_h_plan", [(d, stock(d, 2) / 1e6) for d in plan], 2)
    for name in sorted(by):
        r = info.get(name, {})
        for d, it, h, note in sorted(by[name], key=lambda p: p[0]):
            sites.append({"site": name, "date": d.isoformat(), "it_mw": None if it is None else round(it, 1), "h100e": None if h is None else round(h),
                          "user": tag(r.get("Users")), "owner": tag(r.get("Owner")), "country": r.get("Country") or "",
                          "note": plain(note)[:160]})

def building(): # US Census Bureau: value of private construction put in place, data centers, seasonally adjusted annual rate
    z = zipfile.ZipFile(io.BytesIO(get("https://www.census.gov/construction/c30/xlsx/privsatime.xlsx")))
    text = lambda s: re.sub(r"<[^>]+>", "", "".join(re.findall(r"<t[^>]*>(.*?)</t>", s, flags=re.S)))
    shared = [text(s) for s in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode("utf-8"), flags=re.S)]
    grid = []
    for row in re.findall(r"<row [^>]*>(.*?)</row>", z.read("xl/worksheets/sheet1.xml").decode("utf-8"), flags=re.S):
        cells = {}
        for ref, attrs, body in re.findall(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', row, flags=re.S):
            v = re.search(r"<v>(.*?)</v>", body or "")
            cells[ref] = (shared[int(v.group(1))] if 't="s"' in attrs else v.group(1)) if v else ""
        grid.append(cells)
    head = next(c for c in grid if "Data center" in c.values())
    col = next(k for k, v in head.items() if v == "Data center")
    series = {}
    for c in grid:
        m = re.match(r"^([A-Z][a-z]{2}-\d{2})", c.get("A", ""))
        if m and num(c.get(col)) is not None:
            series[dt.datetime.strptime(m.group(1), "%b-%y").date()] = num(c[col]) / 1000
    put("build_us", [(d, v) for d, v in series.items() if d >= dt.date(2020, 1, 1)], 1)
    put("build_yoy", [(d, (v / series[d.replace(year=d.year - 1)] - 1) * 100) for d, v in series.items()
                      if d >= dt.date(2020, 1, 1) and d.replace(year=d.year - 1) in series], 1)

for name, fn in (("capabilities", capabilities), ("revenue", revenue), ("chips", chips), ("centers", centers), ("building", building)):
    try:
        fn()
    except Exception as e:
        problems.append(f"{name}: {e}")

if len(ids) < 14 or not sites:
    print(json.dumps({"ok": False, "series": len(ids), "sites": len(sites), "problems": problems}))
    sys.exit(2)
meta = [{"label": "fetch_accel.py", "value": open(os.path.abspath(__file__), encoding="utf-8").read(), "type": "code", "lang": "python"},
        {"label": "Inputs", "value": "Epoch AI (benchmarking hub, AI companies, AI chip sales, AI data centers; CC BY 4.0), METR time horizons as republished by Epoch AI, US Census Bureau (construction spending)"},
        {"label": "Run", "value": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
        {"label": "Skipped", "value": "; ".join(problems) or "none"}]
files = [("accel_series.json", rows), ("accel_sites.json", sites)]
if BASE:
    files.append(("accel_base.json", [{"site": r["site"], "date": r["date"], "it_mw": r["it_mw"], "h100e": r["h100e"], "snap": TODAY.isoformat()} for r in sites]))
for name, data in files:
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump({"rows": data, "meta": meta}, f, ensure_ascii=False, separators=(",", ":"))
newest, value = {}, {}
for r in rows: # rows of one series are in date order, so the last one seen is its latest
    newest[r["id"]], value[r["id"]] = r["date"], r["value"]
headline = {k: value.get(k) for k in ("eci_front", "eci_open", "chips_h", "chips_mult", "build_us", "build_yoy", "sites_gw", "sites_gw_plan")}
print(json.dumps({"ok": True, "series": len(ids), "rows": len(rows), "site_rows": len(sites), "sites": len({r["site"] for r in sites}),
                  "problems": problems, "newest": {k: v for k, v in newest.items() if not k.endswith("_plan")}, "headline": headline}))
