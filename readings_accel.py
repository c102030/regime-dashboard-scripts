#!/usr/bin/env python3
"""Vals RSI Index and the digest for the written reading of the acceleration block.
Writes rsi_series.json as {rows, meta} from the Vals AI leaderboard, then prints one JSON line with what the page's
outside measurements show, read from accel_series.json in the same folder. Standard library only; network via curl.
Usage: python3 readings_accel.py <output-dir>"""
import json, os, re, subprocess, sys, datetime as dt
from zoneinfo import ZoneInfo

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
TODAY = dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
VALS = "https://www.vals.ai"
problems, digest = [], {}

def get(url, timeout=120):
    r = subprocess.run(["curl", "-sS", "-L", "--http1.1", "-m", str(timeout), "--retry", "2", "--retry-all-errors",
                        "-A", "regime-dashboard/1.0", url], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode()[:160] or "empty answer")
    return r.stdout.decode("utf-8", "replace")

def chunk(text, name): # the address of a script the page loads, which changes with every release of the site
    m = re.search(r"(/_astro/" + name + r"\.[\w-]+\.js(?:\?dpl=[\w-]+)?)", text) or re.search(r"\./(" + name + r"\.[\w-]+\.js(?:\?dpl=[\w-]+)?)", text)
    if not m:
        raise RuntimeError("Vals page changed: no " + name)
    path = m.group(1)
    return VALS + (path if path.startswith("/") else "/_astro/" + path)

def rsi(): # every model's score on each task and overall, with the date each model was released
    page = get(VALS + "/benchmarks/rsi_index")
    view = get(chunk(page, "RsiBenchmarkView"))
    data, consts = get(chunk(view, "benchmark_view_rsi_index")), get(chunk(view, "constants"))
    tasks = json.loads(re.search(r"JSON\.parse\(`(.*?)`\)", data, re.S).group(1))
    updated = re.search(r"updated:`(\d{4}-\d{2}-\d{2})`", data).group(1)
    names = {"compression": "Compression of Wikipedia text", "lm_training": "Training a small language model",
             "harness_engineering": "Engineering a grading harness", "post_training": "Post-training for a finance agent"}
    info = {m.group(1): m.groups()[1:] for m in re.finditer(
        r'"([\w.-]+/[\w.-]+)":\{company:`([^`]*)`,country:`[^`]*`,label:`([^`]*)`,release_date:(?:`(\d{4}-\d{2}-\d{2})`|null),open_source:(!0|!1)', consts)}
    models = []
    for key, r in tasks["overall"].items():
        lab, label, released, open_src = info.get(key, (None, None, None, None))
        if released and r.get("accuracy") is not None:
            models.append((dt.date.fromisoformat(released), float(r["accuracy"]), label, lab, open_src == "!0"))
    if len(models) < 10:
        raise RuntimeError("Vals RSI Index: too few models with a release date")
    rows = []
    def frontier(sid, pick):
        best = None
        for d, v, label, lab, op in sorted(models):
            if pick(op) and (best is None or v > best):
                best = v
                rows.append({"id": sid, "date": d.isoformat(), "value": round(v, 2), "model": label, "lab": lab})
        if best is not None:
            rows.append({"id": sid, "date": TODAY.isoformat(), "value": round(best, 2), "model": rows[-1]["model"], "lab": rows[-1]["lab"]})
    frontier("rsi_front", lambda op: True)
    frontier("rsi_open", lambda op: op)
    first = min(m[0] for m in models)
    rows += [{"id": "rsi_ref", "date": first.isoformat(), "value": 50.0}, {"id": "rsi_ref", "date": TODAY.isoformat(), "value": 50.0}]
    for d, v, label, lab, op in sorted(models):
        rows.append({"id": "rsi_model", "date": d.isoformat(), "value": round(v, 2), "model": label, "lab": lab, "open": op})
    for task, name in names.items():
        scores = [(float(r["accuracy"]), key) for key, r in tasks.get(task, {}).items() if r.get("accuracy") is not None and key in info]
        if scores:
            v, key = max(scores)
            rows.append({"id": "rsi_task", "date": updated, "value": round(v, 2), "task": name, "model": info[key][1], "lab": info[key][0]})
    meta = [{"label": "readings_accel.py", "value": open(os.path.abspath(__file__), encoding="utf-8").read(), "type": "code", "lang": "python"},
            {"label": "Inputs", "value": "Vals AI, Vals RSI Index (built with CoreWeave), leaderboard version of " + updated + ": each model's score on four autonomous AI-research tasks, and its release date"},
            {"label": "Run", "value": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}]
    with open(os.path.join(OUT, "rsi_series.json"), "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "meta": meta}, f, ensure_ascii=False, separators=(",", ":"))
    front = [r for r in rows if r["id"] == "rsi_front"]
    half = [r for r in front if r["date"] <= (TODAY - dt.timedelta(days=182)).isoformat()]
    opens = [r for r in rows if r["id"] == "rsi_open"]
    return {"updated": updated, "models": len(models), "front": front[-1]["value"], "front_model": front[-2]["model"] if len(front) > 1 else front[-1]["model"],
            "front_6m_ago": half[-1]["value"] if half else None, "open_front": opens[-1]["value"] if opens else None, "reference": 50,
            "tasks": {r["task"]: [r["value"], r["model"]] for r in rows if r["id"] == "rsi_task"}}

def accel(): # the page's outside measurements, from the weekly file
    series = json.load(open(os.path.join(OUT, "accel_series.json"), encoding="utf-8"))["rows"]
    by = {}
    for r in series:
        by.setdefault(r["id"], []).append((r["date"], r["value"]))
    for k in by:
        by[k].sort()
    year = lambda d, n: str(int(d[:4]) + n) + d[4:]
    at = lambda k, d: ([v for x, v in by[k] if x <= d] or [None])[-1]
    eci, mult, yoy = by["eci_front"], by["chips_mult"], by["build_yoy"]
    pace_now = eci[-1][1] - at("eci_front", year(eci[-1][0], -1))
    pace_then = at("eci_front", year(eci[-1][0], -1)) - at("eci_front", year(eci[-1][0], -2))
    tests = [pace_now > pace_then, mult[-1][1] >= 3, yoy[-1][1] > at("build_yoy", year(yoy[-1][0], -1))]
    gw, plan = by["sites_gw"], by["sites_gw_plan"]
    return {"read": ["against", "partial", "partial", "supports"][tests.count(True)], "capabilities": tests[0], "chip_stock": tests[1], "construction": tests[2],
            "eci_now": eci[-1][1], "pace_now": round(pace_now, 1), "pace_then": round(pace_then, 1), "eci_open": by["eci_open"][-1][1],
            "chips_mult": [mult[-1][1], mult[-1][0]], "chips_mult_year_before": at("chips_mult", year(mult[-1][0], -1)),
            "build_yoy": [yoy[-1][1], yoy[-1][0]], "build_yoy_year_before": at("build_yoy", year(yoy[-1][0], -1)),
            "sites_gw_now": gw[-1][1], "sites_gw_in_12_months": at("sites_gw_plan", year(gw[-1][0], 1)), "sites_gw_end_2028": plan[-1][1],
            "metr_minutes": by["metr_h50"][-1] if "metr_h50" in by else None,
            "best_posttrain": by["rd_posttrain"][-1] if "rd_posttrain" in by else None, "best_frontierswe": by["rd_swe"][-1] if "rd_swe" in by else None,
            "best_remote_labor": by["rd_rli"][-1] if "rd_rli" in by else None,
            "revenue_anthropic": by["rev_anthropic"][-1] if "rev_anthropic" in by else None, "revenue_openai": by["rev_openai"][-1] if "rev_openai" in by else None}

for name, fn in (("rsi", rsi), ("accel", accel)):
    try:
        digest[name] = fn()
    except Exception as e:
        problems.append(f"{name}: {e}")
print(json.dumps({"ok": "accel" in digest, "problems": problems, "digest": digest}))
