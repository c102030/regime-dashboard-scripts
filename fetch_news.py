#!/usr/bin/env python3
"""Candidate news for the written readings of the dashboard "Leading indicators vs markets", from Google News searches
(RSS), with Bing News as the fallback. Standard library only; network via curl. The scheduled task picks at most
three items per section and writes its own one-line summary of each; the page shows that line with the source, the
date and the link, never the headline.

Fetch:  python3 fetch_news.py <output-dir> <section> [<section> ...]     sections: br us ai agro accel
  Writes <output-dir>/news.json ({section: [{"id", "t" headline, "s" source, "d" São Paulo time, "u" link}]}) and
  <output-dir>/news.txt (one line per item, without the links, for the task to read), and prints one JSON line
  {"ok", "counts", "problems"}. A section whose searches all fail is left out and listed in problems.
Merge:  python3 fetch_news.py <output-dir> --merge <picks-file>
  The picks file has one line per chosen item, "<section>|<id>|<English line>|<Portuguese line>", or "<section>|none"
  for a section with nothing worth showing. Sections: those fetched, plus recession, which picks among the br and us
  items. Prints one JSON line {"ok", "fields": {"<section>_news": [{"en", "pt", "src", "url", "d"}]}, "problems"}."""
import json, os, subprocess, sys, datetime as dt, urllib.parse as up, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

SP = ZoneInfo("America/Sao_Paulo")
PT, EN = ("pt-BR", "BR", "hl=pt-BR&gl=BR&ceid=BR:pt-419"), ("en-US", "US", "hl=en-US&gl=US&ceid=US:en")
# Two searches per section, in the language its sources write in, over the task's cadence in days.
SECTIONS = {
    "br": (PT, 1, ['Selic OR Copom OR IPCA OR "juros futuros" OR "Banco Central"',
                   '"dívida pública" OR "arcabouço fiscal" OR "Tesouro Nacional" OR dólar OR Ibovespa']),
    "us": (EN, 1, ['"Treasury yields" OR "Federal Reserve" OR "jobless claims" OR "credit spreads"',
                   '"S&P 500" OR "stock market" OR recession OR "high-yield bonds"']),
    "ai": (EN, 1, ['Nvidia OR hyperscalers OR "AI capex" OR "AI spending" OR "data center financing"',
                   '"AI bubble" OR "AI stocks" OR OpenAI OR "AI chips" OR "AI debt"']),
    "agro": (PT, 7, ['soja OR safra OR Conab OR "exportações do agronegócio" OR "preço da soja"',
                     '"El Niño" OR "La Niña" OR "crédito rural" OR "Plano Safra"']),
    "accel": (EN, 7, ['"AI data center" OR "AI data centers" OR "data center construction" OR "AI chip shipments" OR Stargate',
                      '"frontier AI" OR "AI capabilities" OR "AI benchmark" OR "automated AI research" OR "self-improving AI"']),
}
POOLS = {"recession": ("br", "us")}  # sections that pick among other sections' items
KEEP, PICKS, LONGEST = 10, 3, 120  # candidates per section, items shown per section, characters per line


def get(url):
    r = subprocess.run(["curl", "-sS", "-L", "-m", "40", "--retry", "2", "--retry-all-errors",
                        "-A", "Mozilla/5.0 (regime-dashboard)", url], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode()[:160] or "empty answer")
    return r.stdout


def item_list(xml, days):
    oldest = dt.datetime.now(SP) - dt.timedelta(days=days, hours=12)
    out = []
    for item in ET.fromstring(xml).iter("item"):
        title = (item.findtext("title") or "").strip()
        source = next(((c.text or "").strip() for c in item if c.tag == "source" or c.tag.endswith("}Source")), "")
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3].strip()
        link = (item.findtext("link") or "").strip()
        if "bing.com/news/apiclick" in link:  # Bing wraps the publisher's link
            link = (up.parse_qs(up.urlparse(link).query).get("url") or [""])[0]
        elif "news.google.com" in link:
            link = link.split("?")[0]
        if link.startswith("https://") and "?" in link and "news.google.com" not in link:  # drop tracking tags only
            base, query = link.split("?", 1)
            kept = [kv for kv in query.split("&") if kv and not kv.lower().startswith(("utm_", "ocid=", "cmpid="))]
            link = base + ("?" + "&".join(kept) if kept else "")
        source = source or up.urlparse(link).netloc.removeprefix("www.")
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(SP)
        except (TypeError, ValueError):
            continue
        if title and link.startswith("https://") and when >= oldest:
            out.append({"t": title, "s": source, "d": when.strftime("%Y-%m-%d %H:%M"), "u": link})
    return out


def search(lang, days, query):
    setlang, cc, google = lang
    bing = (f"https://www.bing.com/news/search?q={up.quote(query)}&format=rss&setlang={setlang}&cc={cc}"
            f"&qft=interval%3d%22{7 if days <= 1 else 8}%22")
    try:
        found = item_list(get("https://news.google.com/rss/search?q=" + up.quote(f"{query} when:{days}d") + "&" + google), days)
        if found:
            return found
    except Exception:
        pass
    return item_list(get(bing), days)


def fetch(out_dir, sections):
    news, problems = {}, []
    for sec in dict.fromkeys(sections):
        lang, days, queries = SECTIONS[sec]
        found = []
        for q in queries:
            try:
                found.append(search(lang, days, q))
            except Exception as e:  # one failed search leaves the other
                problems.append(f"{sec}: {str(e)[:120]}")
        if not found:
            continue
        seen, picked = set(), []
        for rank in range(max(len(f) for f in found)):  # alternate the two searches, keeping each one's own order
            for f in found:
                if rank < len(f):
                    key = " ".join(f[rank]["t"].lower().split())[:70]
                    if key not in seen:
                        seen.add(key)
                        picked.append(f[rank])
        news[sec] = [dict(id=f"{sec}{i + 1}", **x) for i, x in enumerate(picked[:KEEP])]
        if not news[sec]:
            problems.append(f"{sec}: no news in the window")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "news.json"), "w", encoding="utf-8") as fh:
        json.dump(news, fh, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out_dir, "news.txt"), "w", encoding="utf-8") as fh:
        for sec, items in news.items():
            for x in items:
                fh.write(f"{x['id']} · {x['s']} · {x['d'][8:10]}/{x['d'][5:7]} {x['d'][11:]} · {x['t']}\n")
    print(json.dumps({"ok": any(news.values()), "counts": {s: len(v) for s, v in news.items()}, "problems": problems}))


def merge(out_dir, picks_file):
    with open(os.path.join(out_dir, "news.json"), encoding="utf-8") as fh:
        news = json.load(fh)
    flat = lambda s: " ".join(s.lower().split())
    fields, problems = {}, []
    with open(picks_file, encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    for ln in lines:
        parts = [p.strip() for p in ln.split("|", 3)]
        sec = parts[0]
        if sec not in SECTIONS and sec not in POOLS:
            problems.append(f"unknown section in: {ln[:60]}")
            continue
        out = fields.setdefault(f"{sec}_news", [])
        if len(parts) == 2 and parts[1].lower() == "none":
            continue
        if len(parts) != 4 or not parts[2] or not parts[3]:
            problems.append(f"{sec}: a line needs section|id|English|Portuguese: {ln[:60]}")
            continue
        _, pid, en, pt = parts
        item = next((x for s in POOLS.get(sec, (sec,)) for x in news.get(s, []) if x["id"] == pid), None)
        if item is None:
            problems.append(f"{sec}: no candidate {pid}")
        elif len(out) >= PICKS:
            problems.append(f"{sec}: more than {PICKS} picks, {pid} left out")
        elif any(x["url"] == item["u"] for x in out):
            problems.append(f"{sec}: {pid} picked twice")
        elif max(len(en), len(pt)) > LONGEST:
            problems.append(f"{sec}: the lines for {pid} are longer than {LONGEST} characters")
        elif flat(item["t"]) in (flat(en), flat(pt)):
            problems.append(f"{sec}: the line for {pid} copies the headline; write it in your own words")
        else:
            out.append({"en": en, "pt": pt, "src": item["s"], "url": item["u"], "d": item["d"][:10]})
    print(json.dumps({"ok": not problems, "fields": fields, "problems": problems}, ensure_ascii=False, separators=(",", ":")))


def main():
    args = sys.argv[1:]
    if len(args) == 3 and args[1] == "--merge":
        merge(args[0], args[2])
    elif len(args) >= 2 and all(s in SECTIONS for s in args[1:]):
        fetch(args[0], args[1:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
