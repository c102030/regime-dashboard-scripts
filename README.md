# regime-dashboard-scripts

Scripts behind the dashboard "Leading indicators vs markets — Brazil & US". Scheduled tasks download them at a pinned
commit, check each file's SHA-256 and run them; a change here does nothing until a task's instructions name the new
commit and hashes. Standard library only, network via curl. Nothing here is investment advice.

| File | What it does | Run by |
|---|---|---|
| `fetch_regime.py` | Daily series, the two recession models, and a digest for the written readings | daily task |
| `fetch_news.py` | Candidate news for each section, and the merge of the task's picks | all three tasks |
| `check_readings.py` | Rule checks on the written readings before they are saved | all three tasks |
| `fetch_agro.py`, `digest_agro.py` | Exports and agro series, and their digest | weekly agro task |
| `fetch_accel.py`, `readings_accel.py` | AI acceleration series, the Vals RSI Index, and their digest | weekly acceleration task |
| `model/validate.py` | Refits the recession models from `model/data` and writes `model/REPORT.md` | by hand |

## What the daily script guarantees

- A value read while its market is trading carries its clock time (São Paulo). Every other value is the last close or
  official figure before today, with its own date; the digest lists which series were observed today.
- `recession.json` is written only when both models were computed. If an essential series is missing the run fails.
- A recession reading is dated by the newest month that has every input. A missing month repeats the month before it;
  nothing published later is ever used for an earlier month.
- Curve slopes, policy rates and the two-year Treasury yield are not scored.

## Tests

    python3 -m unittest discover tests        # rules of the daily script and of the readings check, no network

End to end, with one source blocked (needs the network; `tests/curl_stub.sh` stands in for curl):

    mkdir -p /tmp/stub out && cp tests/curl_stub.sh /tmp/stub/curl && chmod +x /tmp/stub/curl
    BLOCK=stlouisfed PATH=/tmp/stub:$PATH python3 -I fetch_regime.py out   # FRED down: no recession.json, "recession_file": false
    BLOCK=bcb.gov.br PATH=/tmp/stub:$PATH python3 -I fetch_regime.py out   # central bank down: "ok": false, exit code 2

## The recession models

`model/REPORT.md` says what they estimate, how they were checked and where they fail. In short: the United States
model ranks months well but is overconfident at high readings; the Brazil model showed no skill when tested on months outside its fit and is
labelled experimental. Both charts on the dashboard are retrospective fits on revised data.
