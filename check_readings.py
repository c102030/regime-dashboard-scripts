#!/usr/bin/env python3
"""Checks the written readings of the dashboard "Leading indicators vs markets" before they are saved.
Standard library only, no network. It cannot judge whether a reading is right; it catches the mistakes a rule can see.

Usage: python3 check_readings.py <readings-file>
The file has one line per section and language: <section>|<en or pt>|<headline>|<text>
Prints one JSON line {"ok", "problems"}. Each problem names its section and language.

What it checks:
- every section has both languages; the headline has at most 12 words and no final period; the text at most 70 words;
- a sentence that calls something unchanged, stable, steady or flat names the date or month of the observation it
  rests on. A figure that simply has no newer observation has not been shown to be stable: say which date it is from;
- no sentence states or rules out a cause (because, due to, rather than...): say what moved and when, and use
  "consistent with" or "suggests" at most. The recession section may say what drives a model, which is arithmetic;
- no "will": the readings describe, they do not forecast."""
import json, re, sys

MONTHS = ("jan|feb|fev|mar|apr|abr|may|mai|jun|jul|aug|ago|sep|set|oct|out|nov|dec|dez|january|february|march|april|june|july|august|september|"
          "october|november|december|janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro")
DATED = re.compile(r"\b(" + MONTHS + r")\b|\b\d{1,2}/\d{1,2}\b", re.I)
STABLE = re.compile(r"\b(unchanged|steady|stable|flat|did not move|has not moved|have not moved|without a further (rise|fall|increase|drop)|"
                    r"inalterad[oa]s?|estável|estáveis|estagnad[oa]s?|não se move[u]?|não se moveram|sem nova (alta|queda))\b", re.I)
CAUSE = re.compile(r"\b(because|due to|caused by|as a result of|rather than|thanks to|driven by|porque|por causa d[eoa]s?|devido|causad[oa]s?|em vez de|"
                   r"e não (com|de|por)|graças|puxad[oa]s? p)\b", re.I)
DRIVER = re.compile(r"\b(driven by|puxad[oa]s? p)", re.I)
WILL = re.compile(r"\bwill\b", re.I)
words = lambda s: len(s.split())
sentences = lambda s: [x for x in re.split(r"(?<=[.!?;:])\s+", s.strip()) if x]


def check(lines):
    problems, seen = [], {}
    for n, ln in enumerate(lines, 1):
        parts = [p.strip() for p in ln.split("|", 3)]
        if len(parts) != 4 or parts[1] not in ("en", "pt") or not parts[2] or not parts[3]:
            problems.append(f"line {n}: needs section|en or pt|headline|text")
            continue
        sec, lang, head, text = parts
        tag = f"{sec} {lang}"
        seen.setdefault(sec, set()).add(lang)
        if words(head) > 12:
            problems.append(f"{tag}: the headline has {words(head)} words, at most 12")
        if head.endswith("."):
            problems.append(f"{tag}: the headline ends with a period")
        if words(text) > 70:
            problems.append(f"{tag}: the text has {words(text)} words, at most 70")
        for s in sentences(head) + sentences(text):
            if STABLE.search(s) and not DATED.search(s):
                problems.append(f"{tag}: \"{STABLE.search(s).group(0)}\" without the date of the observation; a figure with no newer "
                                f"observation has not been shown to be stable. Name the date or month it is from, or drop the claim")
            cause = CAUSE.search(s)
            if cause and not (sec == "recession" and DRIVER.match(cause.group(0))):
                problems.append(f"{tag}: \"{cause.group(0)}\" states or rules out a cause; say what moved and when, and use "
                                f"\"consistent with\" or \"suggests\" at most")
            if lang == "en" and WILL.search(s):
                problems.append(f"{tag}: \"will\" forecasts; describe what the data show")
    for sec, langs in seen.items():
        if langs != {"en", "pt"}:
            problems.append(f"{sec}: needs both an en and a pt line")
    return problems


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as fh:
        problems = check([ln.strip() for ln in fh if ln.strip()])
    print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False))


if __name__ == "__main__":
    main()
