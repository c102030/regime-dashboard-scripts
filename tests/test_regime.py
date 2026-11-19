"""Tests of the daily script's rules, without the network: python3 -m unittest discover tests"""
import datetime as dt, json, math, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fetch_regime as R
import check_readings as C

D = dt.date
REAL = {k: getattr(R, k) for k in ("fred", "sgs_long", "rec_br", "rec_us")}


class Case(unittest.TestCase):   # every test starts from the script's own functions and empty state, and leaves them so
    def setUp(self):
        self.saved = dict(R.S), dict(R.LIVE)
        R.S.clear(); R.LIVE.clear(); del R.REC[:]; del R.problems[:]

    def tearDown(self):
        for k, v in REAL.items():
            setattr(R, k, v)
        R.S.clear(); R.S.update(self.saved[0]); R.LIVE.clear(); R.LIVE.update(self.saved[1]); del R.REC[:]; del R.problems[:]

months = lambda a, b: [R.back(b, k) for k in range((b.year - a.year) * 12 + b.month - a.month, -1, -1)]


def us_data(last=D(2026, 10, 1)):
    ms = months(D(1998, 1, 1), last)
    wave = lambda i, k: math.sin(i / k)
    return {"GS10": {m: 4 + wave(i, 9) for i, m in enumerate(ms)}, "TB3MS": {m: 3 + wave(i, 13) for i, m in enumerate(ms)},
            "NFCI": {m: 0.2 * wave(i, 5) for i, m in enumerate(ms)}, "PERMIT": {m: 1400 + 150 * wave(i, 7) for i, m in enumerate(ms)},
            "USREC": {m: 0.0 for m in ms}}


def run_us(data):
    R.fred = lambda code, start=None, extra="": sorted(data[code].items())
    del R.REC[:]
    out = R.rec_us()
    return out, {dt.date.fromisoformat(r["date"]): r["value"] for r in R.REC if r["id"] == "rec_us"}


def run_br(selic_last, ibc_last):
    selic = {m: 12 + math.sin(i / 11) for i, m in enumerate(months(D(2001, 1, 1), selic_last))}
    ibc = {m: 100 + 0.1 * i + math.sin(i / 6) for i, m in enumerate(months(D(2003, 1, 1), ibc_last))}
    R.sgs_long = lambda code, first: sorted((selic if code == 4189 else ibc).items())
    del R.REC[:]
    return R.rec_br(), {dt.date.fromisoformat(r["date"]): r["value"] for r in R.REC if r["id"] == "rec_br"}


class NoLookAhead(Case):
    def test_fill_repeats_the_month_before_and_never_reads_a_later_one(self):
        a = R.fill({D(2025, 9, 1): 10.0, D(2025, 11, 1): 30.0})
        b = R.fill({D(2025, 9, 1): 10.0, D(2025, 11, 1): 99.0})
        self.assertEqual(a[D(2025, 10, 1)], 10.0)
        self.assertEqual(b[D(2025, 10, 1)], 10.0)

    def test_fill_leaves_a_gap_of_two_months(self):
        self.assertNotIn(D(2025, 10, 1), R.fill({D(2025, 9, 1): 10.0, D(2025, 12, 1): 30.0}))

    def test_us_reading_of_a_month_does_not_change_when_later_months_do(self):
        t, nxt = D(2026, 6, 1), D(2026, 7, 1)
        base = us_data()
        del base["PERMIT"][t]                      # month t was not published
        _, before = run_us(base)
        later = {k: dict(v) for k, v in base.items()}
        for k in ("GS10", "TB3MS", "NFCI", "PERMIT"):
            later[k][nxt] = later[k][nxt] * 1.5 + 1  # everything published afterwards changes
        _, after = run_us(later)
        self.assertEqual(before[t], after[t])
        self.assertNotEqual(before[nxt], after[nxt])
        x = {"spread": base["GS10"][t] - base["TB3MS"][t], "permits": 100 * math.log(base["PERMIT"][R.back(t, 1)] / base["PERMIT"][R.back(t, 12)]), "nfci": base["NFCI"][t]}
        self.assertAlmostEqual(before[t], round(R.score(R.US_MODEL, R.US_MEAN, x)[0], 1))

    def test_us_reading_is_dated_by_the_newest_month_with_every_input(self):
        data = us_data()
        data["GS10"][D(2026, 11, 1)] = 5.0         # one input alone is not a reading
        out, probs = run_us(data)
        self.assertEqual(out["as_of"], "2026-10-01")
        self.assertEqual(max(probs), D(2026, 10, 1))

    def test_brazil_reading_is_dated_by_the_newest_month_with_both_inputs(self):
        out, probs = run_br(D(2026, 11, 1), D(2026, 9, 1))
        self.assertEqual(out["as_of"], "2026-09-01")
        self.assertEqual(out["ibc_as_of"], "2026-09-01")
        self.assertEqual(max(probs), D(2026, 9, 1))

    def test_brazil_reading_of_a_month_ignores_a_later_policy_rate(self):
        a, pa = run_br(D(2026, 9, 1), D(2026, 9, 1))
        b, pb = run_br(D(2026, 11, 1), D(2026, 9, 1))
        self.assertEqual(a["p"], b["p"])
        self.assertEqual(pa[D(2026, 9, 1)], pb[D(2026, 9, 1)])


class BothModelsOrNeither(Case):
    meta = [{"label": "fetch_regime.py", "value": ""}, {"label": "Inputs", "value": ""}, {"label": "Run", "value": "now"}]

    def run_with(self, br, us):
        boom = lambda: (_ for _ in ()).throw(RuntimeError("source down"))
        R.rec_br = (lambda: (R.rec_put("rec_br", [(D(2026, 9, 1), 38.3)], 1), {"p": 38.3, "as_of": "2026-09-01"})[1]) if br else boom
        R.rec_us = (lambda: (R.rec_put("rec_us", [(D(2026, 10, 1), 13.7)], 1), {"p": 13.7, "as_of": "2026-10-01"})[1]) if us else boom
        del R.problems[:]
        with tempfile.TemporaryDirectory() as tmp:
            recession, written = R.recession_models(tmp, self.meta)
            rows = json.load(open(os.path.join(tmp, "recession.json")))["rows"] if os.path.exists(os.path.join(tmp, "recession.json")) else None
        return recession, written, rows, list(R.problems)

    def test_brazil_fails(self):
        recession, written, rows, problems = self.run_with(False, True)
        self.assertFalse(written)
        self.assertIsNone(rows)
        self.assertEqual(list(recession), ["us"])
        self.assertTrue(any(p.startswith("recession_br") for p in problems))

    def test_united_states_fails(self):
        recession, written, rows, problems = self.run_with(True, False)
        self.assertFalse(written)
        self.assertIsNone(rows)
        self.assertTrue(any(p.startswith("recession_us") for p in problems))

    def test_both_work(self):
        recession, written, rows, problems = self.run_with(True, True)
        self.assertTrue(written)
        self.assertEqual({r["id"] for r in rows}, {"rec_br", "rec_us", "run"})
        self.assertEqual([r["date"] for r in rows if r["id"] == "run"], [R.TODAY.isoformat()])
        self.assertEqual(problems, [])


def weekly(last_move, n=60, start=D(2025, 9, 1)):   # every four-week move is 1, except the newest
    pts = [(start + dt.timedelta(days=7 * i), 0.25 * i) for i in range(n)]
    pts[-1] = (pts[-1][0], pts[-5][1] + last_move)
    return pts


class Signals(Case):
    def test_band_of_half_a_typical_move(self):
        self.assertEqual(R.signal(weekly(0.6), "diff", 1)[0], "worsening")
        self.assertEqual(R.signal(weekly(0.4), "diff", 1)[0], "neutral")
        self.assertEqual(R.signal(weekly(-0.4), "diff", 1)[0], "neutral")
        self.assertEqual(R.signal(weekly(-0.6), "diff", 1)[0], "improving")

    def test_direction_follows_the_stress_sign(self):
        self.assertEqual(R.signal(weekly(0.6), "diff", -1)[0], "improving")
        self.assertEqual(R.signal(weekly(-0.6), "diff", -1)[0], "worsening")

    def test_unscored_series_and_short_histories(self):
        self.assertEqual(R.signal(weekly(3.0), "diff", 0)[0], "unscored")
        self.assertEqual(R.signal(weekly(3.0, n=6), "diff", 1)[0], "unscored")
        self.assertEqual(R.signal([], "diff", 1)[0], "unscored")

    def test_curve_slopes_and_policy_rates_are_not_scored_in_either_country(self):
        unscored = {k for k, v in R.IND.items() if v[6] == 0}
        self.assertEqual(unscored, {"br_slope", "us_slope_2s10s", "us_slope_3m10y", "selic", "fed_funds", "us2y"})

    def test_every_scored_series_belongs_to_a_group(self):
        self.assertEqual({k for k, v in R.IND.items() if v[6] != 0} - set(R.GROUP_OF), set())


class Digest(Case):
    def setUp(self):
        super().setUp()
        day = lambda k: R.TODAY - dt.timedelta(days=k)
        series = lambda last, move: [(last - dt.timedelta(days=7 * (59 - i)), v) for i, (_, v) in enumerate(weekly(move))]
        R.S.update(spx=series(day(0), -0.6), us_real10=series(day(1), 0.0), us10y=series(day(1), 0.6), us_slope_2s10s=series(day(1), 3.0), vix=series(day(0), 0.6))
        R.LIVE.update(spx="14:22", vix="14:07")
        self.latest = [{"id": k, "region": "United States", "kind": "diff", "stress": R.IND[k][6], "value": R.S[k][-1][1], "as_of": R.S[k][-1][0].isoformat(),
                        "chg_1w": None, "chg_1m": None, "chg_3m": None, "chg_runoff": None, **({"as_of_time": R.LIVE[k]} if k in R.LIVE else {})} for k in R.S]

    def test_only_series_dated_today_are_listed_as_observed_today(self):
        d = R.build_digest(self.latest, {})
        self.assertEqual(sorted(d["us"]["observed_today"]), ["spx", "vix"])
        self.assertEqual(d["today"], R.TODAY.isoformat())
        self.assertEqual(d["us"]["series"]["us_real10"][1], (R.TODAY - dt.timedelta(days=1)).isoformat())
        self.assertTrue(d["us"]["series"]["spx"][1].endswith(" 14:22"))

    def test_counts_leave_out_unscored_series_and_group_the_rest(self):
        d = R.build_digest(self.latest, {})["us"]
        self.assertEqual(d["signals"], {"worsening": 3, "improving": 0, "neutral": 1})
        self.assertEqual(d["series"]["us_slope_2s10s"][6], "unscored")
        self.assertEqual(d["groups"], {"stocks": {"worsening": 2}, "rates": {"worsening": 1, "neutral": 1}})

    def test_no_recession_part_without_both_models(self):
        self.assertNotIn("recession", R.build_digest(self.latest, {}))
        self.assertIn("recession", R.build_digest(self.latest, {"br": {}, "us": {}}))


class Calculations(Case):
    def test_ibovespa_in_dollars_divides_by_the_fixing_of_the_same_day(self):
        d1, d2 = R.TODAY - dt.timedelta(days=2), R.TODAY - dt.timedelta(days=1)
        R.S.update(ibov=[(d1, 160000.0), (d2, 167138.0)], usdbrl=[(d2, 5.8102)])
        R.derived()
        self.assertEqual(len(R.S["ibov_usd"]), 1)                       # no fixing, no dollar value
        self.assertAlmostEqual(R.S["ibov_usd"][0][1], 28766.31, places=1)

    def test_a_stock_fall_and_a_dollar_rise_compound(self):
        self.assertAlmostEqual(((1 - 0.185) / (1 + 0.153) - 1) * 100, -29.3, places=1)

    def test_soybean_price_in_reais_compounds_dollars_and_the_exchange_rate(self):
        self.assertAlmostEqual(((1 + 0.104) * (1 + 0.083) - 1) * 100, 19.6, places=1)

    def test_a_missing_reference_leaves_the_change_empty(self):
        self.assertIsNone(R.at([(D(2026, 11, 10), 1.0)], D(2026, 11, 1)))


YESTERDAY = ("us|en|Stocks extend their fall; real yields steady, volatility up|The discount-rate reading still fits, but today's leg comes without a further "
             "rise in real yields, which are unchanged since the earlier reading. At 14:22 the S&P 500 is 4.7% below a month ago and the VIX has risen to 24.5, "
             "consistent with a pull-back in risk appetite rather than a rates move. Jobs still hold; permits remain the weak spot.")
FIXED = ("us|en|Stocks extend their fall; no rates reading for today yet|At 14:22 the S&P 500 is 4.7% below a month ago and the VIX has risen to 24.5. "
         "The newest real-yield reading, 2.89%, is the 17 Nov close, so today's move in rates is not known yet. Jobs still hold; permits remain the weak spot.")


class Readings(unittest.TestCase):
    def test_the_reading_of_18_november_is_caught(self):
        problems = C.check([YESTERDAY, YESTERDAY.replace("us|en|", "us|pt|")])
        self.assertTrue(any('"steady"' in p for p in problems))
        self.assertTrue(any('"without a further rise"' in p for p in problems))
        self.assertTrue(any('"rather than"' in p for p in problems))

    def test_a_dated_reading_passes(self):
        self.assertEqual(C.check([FIXED, FIXED.replace("us|en|", "us|pt|")]), [])

    def test_portuguese_wording_is_caught_too(self):
        pt = "us|pt|Bolsa cai|O juro real segue inalterado, o que é compatível com um recuo do apetite a risco, e não com um movimento de juros."
        problems = C.check([pt, pt.replace("|pt|", "|en|")])
        self.assertTrue(any('"inalterado"' in p for p in problems))
        self.assertTrue(any('"e não com"' in p for p in problems))

    def test_an_unchanged_figure_may_be_stated_with_its_date(self):
        ok = "recession|en|Odds unchanged since October|No new monthly data arrived, so Brazil's 38% for September is unchanged."
        self.assertEqual(C.check([ok, ok.replace("|en|", "|pt|")]), [])

    def test_the_recession_section_may_say_what_drives_a_model(self):
        ok = "recession|en|Brazil 38%, United States 14%|Brazil's 38% for September is driven by activity that shrank in the six months to September."
        self.assertEqual(C.check([ok, ok.replace("|en|", "|pt|")]), [])

    def test_lengths_languages_and_forecasts(self):
        long_head = "us|en|" + " ".join(["word"] * 13) + ".|Text."
        problems = C.check([long_head, "br|en|Head|Yields will rise."])
        self.assertTrue(any("13 words" in p for p in problems))
        self.assertTrue(any("ends with a period" in p for p in problems))
        self.assertTrue(any("us: needs both" in p for p in problems))
        self.assertTrue(any('"will"' in p for p in problems))
        self.assertTrue(any("70" in p for p in C.check(["us|en|Head|" + " ".join(["w"] * 71), "us|pt|Head|ok"])))


if __name__ == "__main__":
    unittest.main()
