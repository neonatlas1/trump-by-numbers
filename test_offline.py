#!/usr/bin/env python3
"""Offline logic tests — the gov APIs are egress-blocked in the build sandbox,
so we test everything that doesn't require the network: validation, series
merge (don't-overwrite + revision detection), freshness math, connector date
helpers, and a full build.py render against fixtures."""
import os
import sys
import json
import tempfile
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "connectors"))

import common
import validators
from validators import ValidationError

PASS, FAIL = 0, 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ FAIL: {msg}")


print("== validators ==")
try:
    validators.check("unemployment", 4.1, 4.0); ok(True, "normal value passes")
except ValidationError:
    ok(False, "normal value passes")


def raises(fn):
    try:
        fn(); return False
    except ValidationError:
        return True


ok(raises(lambda: validators.check("gas_price", 99, 3.1)), "gas $99 rejected (bounds)")
ok(raises(lambda: validators.check("trade_deficit", 80, 5)), "trade jump 5→80 rejected (max_jump)")
ok(raises(lambda: validators.check("inflation", float("nan"))), "NaN rejected")
try:
    validators.check("unknown_metric", 123); ok(True, "unknown metric passes through")
except ValidationError:
    ok(False, "unknown metric passes through")

print("== merge_series (don't overwrite + revisions) ==")
existing = {"series": [{"date": "2025-01", "value": 3.0}, {"date": "2025-02", "value": 3.1}]}
merged, revs = common.merge_series(existing, [{"date": "2025-03", "value": 3.2}])
ok([p["date"] for p in merged] == ["2025-01", "2025-02", "2025-03"], "new point appended, old kept")
ok(revs == [], "no revision when only adding")
merged2, revs2 = common.merge_series(existing, [{"date": "2025-02", "value": 3.5}])
ok(revs2 == [("2025-02", 3.1, 3.5)], "revision to an existing date is detected")
# merge preserves old history not present in the new fetch (self-healing store)
merged3, _ = common.merge_series(existing, [{"date": "2025-03", "value": 3.2}])
ok(any(p["date"] == "2025-01" for p in merged3), "history survives a shallow fetch (merge, don't overwrite)")

print("== freshness math ==")
ok(common._effective_date("2025-06") == datetime.date(2025, 6, 30), "monthly as_of -> month end")
ok(common._effective_date("2025-06-15") == datetime.date(2025, 6, 15), "daily as_of -> that date")
sa_daily = common._stale_after("2025-06-15", "Daily")
sa_month = common._stale_after("2025-06", "Monthly")
ok(sa_daily < sa_month, "daily goes stale sooner than monthly")

print("== publish end-to-end (temp data dir) ==")
with tempfile.TemporaryDirectory() as td:
    common.DATA_DIR = td
    out = {"id": "inflation", "name": "Inflation", "category": "Economy",
           "unit": "%", "direction": "up_is_bad", "cadence": "Monthly",
           "target": {"label": "Fed", "value": 2.0},
           "source": {"name": "BLS", "url": "x"}, "note": "n"}
    common.publish(dict(out), series=[{"date": "2025-01", "value": 3.0}, {"date": "2025-02", "value": 3.1}])
    saved = json.load(open(os.path.join(td, "inflation.json")))
    ok(saved["value"] == 3.1 and saved["as_of"] == "2025-02", "headline set from newest series point")
    ok("stale_after" in saved and "last_checked" in saved, "freshness stamps written")
    ok(len(saved["series"]) == 2, "series stored")
    # a bad value must NOT overwrite last-good
    try:
        common.publish(dict(out), series=[{"date": "2025-03", "value": 40.0}])
        ok(False, "bad value should raise and not write")
    except ValidationError:
        after = json.load(open(os.path.join(td, "inflation.json")))
        ok(after["value"] == 3.1, "last-good preserved after a rejected bad value")

print("== connector date helpers ==")
import cbp_border
ok(cbp_border.cal_month(2025, "OCT") == "2024-10", "CBP: FY2025 OCT -> 2024-10 (fiscal->calendar)")
ok(cbp_border.cal_month(2025, "Jan") == "2025-01", "CBP: FY2025 Jan -> 2025-01")
import ice_detention
ok(ice_detention.current_fy(datetime.date(2026, 7, 1)) == 2026, "ICE: Jul 2026 -> FY2026")
ok(ice_detention.current_fy(datetime.date(2025, 11, 1)) == 2026, "ICE: Nov 2025 -> FY2026 (post-Oct rollover)")

print("== v2 expansion: pure-logic tests (no network) ==")


def raises_runtime(fn):
    try:
        fn(); return False
    except RuntimeError:
        return True


ok(common.quarter_month("2026-01-01") == "2026-03", "FRED quarter start -> quarter-end month")
ok(common.quarter_month("2025-10-01") == "2025-12", "Q4 maps to December")

import fred_groceries
yoy = fred_groceries.yoy_from_index([
    ("2024-09-01", 300.0), ("2024-10-01", 300.0), ("2024-11-01", 300.0),
    ("2025-09-01", 309.0), ("2025-11-01", 306.0),   # Oct 2025 missing (shutdown hole)
    ("2026-10-01", 320.0),                            # year-ago base missing
])
ok({p["date"]: p["value"] for p in yoy} == {"2025-09": 3.0, "2025-11": 2.0},
   "groceries YoY: computed where base exists; missing months drop out both ends")

import fred_gdp
gdp_series = [{"date": "2025-03", "value": -0.6}, {"date": "2025-06", "value": 3.8},
              {"date": "2025-09", "value": 4.4}]
ok(fred_gdp.term_average(gdp_series, "2025-03") == 2.5, "GDP term average")
ok(fred_gdp.term_average(gdp_series, "2025-03", count=2) == 1.6, "GDP capped-quarters average")

import treasury_interest
tot = treasury_interest.sum_fytd([
    {"record_date": "2026-06-30", "fytd_expense_amt": "900000000000"},
    {"record_date": "2026-06-30", "fytd_expense_amt": "200000000000"},
    {"record_date": "2026-06-30", "fytd_expense_amt": "-15500000000"},  # negative line summed too
])
ok(tot == [{"date": "2026-06", "value": 1084.5}], "interest: sums ALL lines incl. negatives")

import tariff_rate
rate = tariff_rate.compute_rate(
    [{"record_date": "2026-05-31", "current_month_gross_rcpt_amt": "24000000000"},
     {"record_date": "2026-06-30", "current_month_gross_rcpt_amt": "23000000000"}],  # no import obs yet
    [("2026-05-01", 317045.0)])
ok(rate == [{"date": "2026-05", "value": 7.57}], "tariff rate: duties/imports %, months present in both only")

import cdc_overdoses
od = cdc_overdoses.rows_to_series([
    {"year": "2026", "month": "February", "data_value": "67531", "predicted_value": "68641"},
    {"year": "2026", "month": "January", "data_value": "68669", "predicted_value": "69402"},
    {"year": "2026", "month": "Smarch", "data_value": "1", "predicted_value": "1"},   # junk month
])
ok([p["value"] for p in od] == [69402, 68641], "overdoses: predicted_value used, junk dropped, sorted")

import cms_medicaid
agg = cms_medicaid.aggregate(
    [{"reporting_period": "202603", "state_name": f"State{i}",
      "total_medicaid_and_chip_enrollment": "1000000", "final_report": "N"} for i in range(46)]
    + [{"reporting_period": "202603", "state_name": "State0",
        "total_medicaid_and_chip_enrollment": "1100000", "final_report": "Y"},     # final beats preliminary
       {"reporting_period": "202604", "state_name": "OnlyOne",
        "total_medicaid_and_chip_enrollment": "999", "final_report": "Y"}])         # <45 states -> dropped
ok(agg == [{"date": "2026-03", "value": 46100000}],
   "medicaid: final row wins, states summed, sparse month dropped")

import fjc_judges
_pairs = [("Donald J. Trump", datetime.date(2025, 6, 1)),
          ("Donald J. Trump", datetime.date(2017, 5, 1)),
          ("Joseph R. Biden", datetime.date(2021, 5, 1)),
          ("Barack Obama", datetime.date(2009, 5, 1))]
ok(fjc_judges.count_window(_pairs, "Trump", datetime.date(2017, 1, 20), 200) == 1,
   "judges: first-term window counts only its own confirmations")
ok(fjc_judges.count_window(_pairs, "Biden", datetime.date(2021, 1, 20), 200) == 1,
   "judges: Biden window")
ok(fjc_judges._parse_date("11/20/2025") == datetime.date(2025, 11, 20), "judges: M/D/YYYY dates parse")

import cdc_measles
_as_of, _ytd, _yr = cdc_measles.parse_page(
    "<p>As of June 4, 2026, 2,030 confirmed* measles cases were reported in the United States in 2026.</p>")
ok((_as_of, _ytd, _yr) == ("2026-06-04", 2030, 2026), "measles: page sentence anchor parses")
ok(raises_runtime(lambda: cdc_measles.parse_page("<p>totally different page</p>")),
   "measles: restructured page raises (safe-fail)")

import votehub_approval
_today = datetime.date(2026, 7, 28)
app, dis, n, as_of = votehub_approval.average_polls([
    {"subject": "Donald Trump", "pollster": "A", "end_date": "2026-07-25",
     "answers": [{"choice": "Approve", "pct": 40.0}, {"choice": "Disapprove", "pct": 56.0}]},
    {"subject": "Donald Trump", "pollster": "A", "end_date": "2026-07-20",   # older poll, same pollster
     "answers": [{"choice": "Approve", "pct": 44.0}, {"choice": "Disapprove", "pct": 52.0}]},
    {"subject": "Donald Trump", "pollster": "B", "end_date": "2026-07-24",
     "answers": [{"choice": "Approve", "pct": 42.0}, {"choice": "Disapprove", "pct": 54.0}]},
    {"subject": "Donald Trump", "pollster": "C", "end_date": "2026-07-18",
     "answers": [{"choice": "Approve", "pct": 38.0}, {"choice": "Disapprove", "pct": 58.0}]},
    {"subject": "Congress", "pollster": "D", "end_date": "2026-07-25",
     "answers": [{"choice": "Approve", "pct": 20.0}, {"choice": "Disapprove", "pct": 70.0}]},
], _today)
ok((app, dis, n, as_of) == (40.0, 56.0, 3, "2026-07-25"),
   "approval: latest-per-pollster, Trump-only, simple mean, as_of = newest poll")

import ice_removals
_fyr, _tot, _famu = ice_removals.removals_from_rows([
    [None] * 13 + ["ICE Removals: FY2026"],
    [None] * 13 + ["Removals", None, "Total"],
    [None] * 13 + ["Total", None, 356389],
    [None] * 13 + ["Removals with a FAMU Identifier", None, 36548],
])
ok((_fyr, _tot, _famu) == (2026, 356389, 36548),
   "ICE removals: FYTD block parses (real FY26 layout)")

_adp_rows = ([["Name", "Addr", "City", "St", "Zip", "AOR", "Type", "M/F", "ALOS",
               "Level A", "Level B", "Level C", "Level D",
               "Male Crim", "Male Non-Crim", "Female Crim", "Female Non-Crim"]]
             + [[f"Fac{i}", "", "", "", "", "", "", "", 1.0,
                 10, 20, 30, 40, 25, 25, 25, 25] for i in range(25)]
             + [["Total", "", "", "", "", "", "", "", None,
                 999999, 0, 0, 0, 0, 0, 0, 0]])
_adp, _n = ice_detention.adp_from_rows(_adp_rows)
ok((_adp, _n) == (2500, 25), "ICE detention: Level A-D summed, Total row skipped, cross-check ok")


def _bad_adp():
    bad = [r[:] for r in _adp_rows]
    bad[1][13] = 500   # corrupt the criminality split
    ice_detention.adp_from_rows(bad)


ok(raises_runtime(_bad_adp), "ICE detention: split-mismatch raises (safe-fail)")

import va_backlog
_sats = va_backlog.recent_saturdays(datetime.date(2026, 7, 28))   # a Tuesday
ok(_sats[0] == datetime.date(2026, 7, 25) and all(s.weekday() == 5 for s in _sats),
   "VA: file dates are week-ending Saturdays (fix for the Monday guess)")
ok(va_backlog.recent_saturdays(datetime.date(2026, 7, 25))[0] == datetime.date(2026, 7, 25),
   "VA: a Saturday maps to itself")
_va = va_backlog.counts_from_rows([
    [None] * 6,
    [None, None, None, "SPECIAL MISSION SELECTOR", "#\nPending",
     "#\nPending\n> 125 Days", "%\nPending\n> 125 Days", "ADP"],
    [None] * 6,
    [394, 1, None, "Northeast District", 32097, 2923, 0.091, 57.5],
    [100, None, None, "Compensation Total", 591684, 68297, 0.115, 64.32],
])
ok(_va == (68297, 591684),
   "VA: '# Pending > 125' column + 'Compensation Total' row wins over districts (real 2026 layout)")
ok(va_backlog.counts_from_rows([["nothing", "here"]]) is None,
   "VA: sheet without the metric columns returns None (moves on)")

print("== phase 7: aligned-series math (build.py) ==")
sys.path.insert(0, HERE)
import build as B

_ms = [{"date": "2025-01", "value": 100.0}, {"date": "2025-02", "value": 102.0},
       {"date": "2025-04", "value": 90.0}]
_al = B.aligned_monthly(_ms, "trump2")
ok(_al == [[0, 100.0], [1, 102.0], [3, 90.0]], "aligned_monthly: months since inauguration, holes stay holes")
_alp = B.aligned_monthly(_ms, "trump2", pct=True)
ok(_alp == [[0, 0.0], [1, 2.0], [3, -10.0]], "aligned_monthly pct: rebased to month-0")
ok(B.aligned_monthly([{"date": "2025-03", "value": 5}], "trump2", pct=True) is None,
   "aligned_monthly pct: no month-0 base -> None (never fake a base)")
ok(B.carry_forward([[0, 46], [2, 100]]) == [[0, 46], [1, 46], [2, 100]],
   "carry_forward: cumulative counter carries between events")
_dd = [{"date": "2025-01-20", "value": 36e12}, {"date": "2025-01-22", "value": 36.1e12},
       {"date": "2025-02-20", "value": 36.72e12}]
_dp = B.aligned_daily_pct(_dd, "trump2")
ok(_dp[0] == [0.0, 0.0] and abs(_dp[-1][1] - 2.0) < 0.01,
   "aligned_daily_pct: 0% on inauguration day, growth vs that base")
_gq = [{"date": "2025-03", "value": 4.0}, {"date": "2025-06", "value": 4.0},
       {"date": "2025-09", "value": 4.0}, {"date": "2025-12", "value": 4.0}]
_gi = B.gdp_index(_gq, "trump2")
ok(_gi[0] == [0, 100.0] and abs(_gi[-1][1] - 104.0) < 0.05,
   "gdp_index: compounds annualized rates to +4% over four 4% quarters")

print("== phase 7: chart payloads ==")
_src = {"name": "S", "url": "u"}


def _m(mid, series, **kw):
    d = {"id": mid, "name": mid, "value": (series[-1]["value"] if series else 1),
         "as_of": "2026-06", "cadence": "Monthly", "source": _src, "series": series}
    d.update(kw)
    return d


_infl = B.payload(_m("inflation", _ms, target={"label": "Fed", "value": 2.0}), {})
ok(_infl["benchmark"] == 2.0 and _infl["gaps"] and _infl["series"][0]["pts"],
   "inflation payload: benchmark line + shutdown gap chip")
ok(_infl["channels"] and _infl["caveats"], "inflation payload: influence + caveats furniture present")

_debt_series = [{"date": (datetime.date(2017, 1, 20) + datetime.timedelta(days=i * 7)).isoformat(),
                 "value": 2e13 + i * 1e10} for i in range(500)]
_debt = B.payload(_m("national_debt", _debt_series), {})
_cols = {s["label"]: s["color"] for s in _debt["series"]}
ok(_cols.get("Trump ’25") == "#e66767" and _cols.get("Biden") == "#3987e5",
   "debt payload: locked president colors (Trump red, Biden blue)")
ok(len(_debt["series"]) == 3 and _debt["xType"] == "months", "debt payload: three aligned president lines")

_eo_series = [{"date": "2025-01", "value": 46}, {"date": "2025-02", "value": 76}]
_eo = B.payload(_m("executive_orders", _eo_series,
                   comparison={"label": "Biden", "value": 94}), {})
ok(len(_eo["series"]) == 1 and _eo["dots"] and _eo["dots"][0]["y"] == 94,
   "EO payload pre-backfill: Trump line + Biden same-point dot")
_eo2 = B.payload(_m("executive_orders", _eo_series,
                    comparison={"label": "Biden", "value": 94},
                    prev_terms={"biden": [{"month": 0, "value": 10}, {"month": 1, "value": 20}],
                                "obama": [{"month": 0, "value": 5}]}), {})
ok(len(_eo2["series"]) == 3 and not _eo2.get("dots"),
   "EO payload post-backfill: three full curves, dot retired")

_j = B.payload(_m("judges_confirmed", [],
                  aligned={"trump2": [{"month": 0, "value": 0}, {"month": 1, "value": 2}],
                           "trump1": [{"month": 0, "value": 0}],
                           "biden": [{"month": 0, "value": 1}]}), {})
ok(len(_j["series"]) == 3, "judges payload: aligned curves from the connector become three lines")

_ice = B.payload(_m("ice_removals", [{"date": "2026-07", "value": 356389}],
                    annual_history=[{"fy": 2023, "value": 142580}, {"fy": 2024, "value": 271484}]), {})
ok(_ice["template"] == "bars" and _ice["series"][0]["pts"][-1][2] == "’26*",
   "ICE removals payload: annual bars + current FY marked partial")
_hole = _ice["series"][0]["pts"][-2]
ok(_hole[1] is None and _hole[2] == "’25" and "pending" in _hole[3],
   "ICE removals payload: unpublished FY2025 is a labelled hole, never a zero bar")
_ice2 = B.payload(_m("ice_removals", [{"date": "2026-07", "value": 356389}]), {})
ok(not _ice2["series"] and _ice2["accrueBody"], "ICE removals payload without static: honest accrue state")

_tr = B.payload(_m("tariff_revenue", [{"date": "2026-05", "value": 220.7}, {"date": "2026-06", "value": 244.3}],
                   series_net=[{"date": "2026-06", "value": 163.0}]), {})
ok(len(_tr["series"]) == 2 and _tr["series"][1]["label"] == "Net of refunds",
   "tariff payload: gross + net lines once the net series exists")

_mz = B.payload(_m("measles_cases", [{"date": f"{y}-12", "value": v} for y, v in
                                     [(2019, 1274), (2020, 13), (2024, 285), (2025, 2288), (2026, 2318)]]), {})
ok(_mz["template"] == "bars" and sorted(_mz["labelIdx"]) == [0, 3, 4],
   "measles payload: top-3 bars labelled (incl. the partial year)")

_det = B.payload(_m("ice_detention", [{"date": "2026-07", "value": 62517}], currently_detained=65765), {})
ok(not _det["series"] and "62,517" in _det["accrueBody"], "sparse detention: accrue state carries the figures")

print("== phase 7: full build render ==")
B.build()
_ndata = len([f for f in os.listdir(os.path.join(HERE, "data"))
              if f.endswith(".json") and f[:-5] in B.ORDER])   # exclude support series (e.g. cpi_index deflator)
_html = open(os.path.join(HERE, "site", "index.html")).read()
ok(_html.count('data-id="') == _ndata and _ndata >= 23,
   f"index.html: one card per data file present ({_ndata})")
ok(_html.count("expand-btn") >= _ndata, "index.html: every card gets the expand affordance")
ok('class="callout"' in _html and "See what went dark" in _html,
   "transparency: homepage callout links to the /transparency page")
ok('data-tab="all"' not in _html, "tabs: section nav (scroll-to), no 'All' filter tab")
ok("tab-count" not in _html and '<span class="n">' not in _html, "tabs: no count indicators")
ok("sessionStorage" not in _html and "tbn-theme" in _html,
   "storage limited to the theme-persistence key (no cookies, no session storage)")
ok("Presentation layer" in _html or "chart.js" not in _html or "lineChart" in _html,
   "chart.js inlined into the page")
_dfiles = sorted(os.listdir(os.path.join(HERE, "site", "d")))
ok(len(_dfiles) == _ndata, "site/d/: one payload per metric (store deep, load shallow)")
_all_ok = True
for _df in _dfiles:
    _p = json.load(open(os.path.join(HERE, "site", "d", _df)))
    if not (_p.get("chartTitle") and _p.get("channels") and _p.get("caveats")
            and ("series" in _p) and _p.get("srcUrl")):
        _all_ok = False
        print(f"    ✗ {_df} missing furniture/spec fields")
ok(_all_ok, "every payload carries chart spec + influence note + caveats + source")

print("== phase 7: backfill logic (no network) ==")
import federal_register_eo as feo
_curve = feo.month_curve(["2021-01-25", "2021-01-30", "2021-03-02"], datetime.date(2021, 1, 20))
ok(_curve == [{"month": 0, "value": 2}, {"month": 1, "value": 2}, {"month": 2, "value": 3}],
   "EO month_curve: dense cumulative, empty months carry")
_have = {"biden": [{"month": 0, "value": 10}], "obama": [{"month": 0, "value": 5}]}
ok(feo.prev_term_curves({"prev_terms": _have}) == _have,
   "EO prev_term_curves: closed-term curves carried forward, never refetched")

_fpairs = [("Donald J. Trump", datetime.date(2017, 2, 10)),
           ("Donald J. Trump", datetime.date(2017, 5, 1)),
           ("Donald J. Trump", datetime.date(2025, 3, 1)),
           ("Joseph R. Biden", datetime.date(2021, 6, 1))]
_t1c = fjc_judges.term_curve(_fpairs, "Trump", datetime.date(2017, 1, 20))
ok(_t1c[0] == {"month": 0, "value": 0} and _t1c[1]["value"] == 1 and _t1c[-1]["value"] == 2,
   "judges term_curve: dense cumulative within the dated window")
_t2c = fjc_judges.term_curve(_fpairs, "Trump", datetime.date(2025, 1, 20),
                             today=datetime.date(2025, 4, 15))
ok(_t2c[-1] == {"month": 3, "value": 1} and len(_t2c) == 4,
   "judges term_curve: current term stops at the current month and excludes term-1 dates")

_sats = va_backlog.saturdays_between(datetime.date(2018, 1, 1), datetime.date(2018, 1, 31))
ok([s.isoformat() for s in _sats] == ["2018-01-06", "2018-01-13", "2018-01-20", "2018-01-27"],
   "VA saturdays_between: exactly the week-ending Saturdays")
_ex = {"series": [{"date": "2026-07-18", "value": 70000}],
       "archive_missing": ["2026-07-11"]}
_tg = va_backlog.backfill_targets(_ex, datetime.date(2026, 7, 28), chunk=5)
ok(len(_tg) == 5 and _tg[0] == datetime.date(2026, 7, 4)
   and datetime.date(2026, 7, 18) not in _tg and datetime.date(2026, 7, 11) not in _tg,
   "VA backfill_targets: newest-first, capped, skips stored + known-missing weeks")

_cbp_rows = "\n".join([
    "Fiscal Year,Month Grouping,Month (abbv),Encounter Count",
    "2023 (FYTD),FYTD,JUN,10000",
    "2023 (FYTD),Remaining,JUL,20000",     # closed FY: month happened -> keep
    "2026 (FYTD),FYTD,JUN,12901",
    "2026 (FYTD),Remaining,JUL,0",         # current FY: future month -> skip
    "2024 (FYTD),Remaining,AUG,",          # closed FY but blank count -> skip (never store fake zeros)
])
_cbp = cbp_border.parse_csv(_cbp_rows, current_fy=2026)
ok(_cbp.get("2023-07") == 20000 and "2026-07" not in _cbp and "2024-08" not in _cbp,
   "CBP: closed-FY 'Remaining' months kept (they happened); current-FY future + blanks skipped")
ok(cbp_border.current_fiscal_year(datetime.date(2026, 8, 4)) == 2026
   and cbp_border.current_fiscal_year(datetime.date(2026, 11, 1)) == 2027,
   "CBP: fiscal-year rollover at October")
ok(cbp_border.needs_archive({"2022-10", "2022-11"}), "CBP needs_archive: pre-2022 hole detected")
ok(cbp_border.needs_archive({"2021-01", "2023-06"}), "CBP needs_archive: closed-FY Jul–Sep holes detected")
_full = {f"{y}-{m:02d}" for y in range(2021, 2027) for m in range(1, 13)}
ok(not cbp_border.needs_archive(_full), "CBP needs_archive: complete series -> no refetch")

import ice_removals as icer
_hist = icer.annual_history()
ok(_hist and _hist[0]["fy"] == 2012 and _hist[-1]["fy"] == 2024 and _hist[-1]["value"] == 271484,
   "ICE annual_history: static file loads, sorted FY2012→FY2024")

print("== approval known-outage state (4 Aug 2026 incident) ==")
_ex = {"id": "approval_rating", "value": 42.2, "as_of": "2026-06-29", "n_polls": 2,
       "disapprove": 55.6, "net": -13.4, "cadence": "Weekly",
       "source": {"name": "VoteHub poll aggregate (CC-BY)", "url": "x"}, "note": "old"}
_st = votehub_approval.stalled_output(dict(_ex), datetime.date(2026, 8, 4), "0 usable polls")
ok(_st["source_stalled_since"] == "2026-06-29" and "no new national approval poll since Jun 29, 2026" in _st["note"],
   "stalled: last-good held with explicit on-card disclosure")
ok(_st["value"] == 42.2 and "series" not in _st, "stalled: value unchanged, stored series untouched")
ok(raises_runtime(lambda: votehub_approval.stalled_output(dict(_ex), datetime.date(2026, 9, 15), "x")),
   "stalled: acknowledgment window is time-boxed — hard-fails after 75 quiet days")
ok(raises_runtime(lambda: votehub_approval.stalled_output(None, datetime.date(2026, 8, 4), "x")),
   "stalled: no last-good to hold -> still fails loud")
_ap = B.payload(_m("approval_rating", [{"date": "2026-06-29", "value": 42.2}],
                   disapprove=55.6, source_stalled_since="2026-06-29"), {})
ok(any("no new national approval poll since" in c for c in _ap["caveats"]),
   "approval payload: outage disclosed in the expanded card's caveats")

print("== v3 register (locked 12 Aug 2026): static imports ==")
_gp = json.load(open(os.path.join(HERE, "connectors", "static", "gallup_terms.json")))
ok(_gp["quarterly"]["biden"]["7"] == 42.0 and _gp["quarterly"]["trump1"]["7"] == 41.1
   and _gp["quarterly"]["obama"]["7"] == 44.7,
   "gallup static: canonical 7th-quarter trio matches Gallup's own table")
ok("15" not in _gp["quarterly"]["biden"] and "16" not in _gp["quarterly"]["trump1"],
   "gallup static: unpublished quarters stay gaps, never estimated")
_adp = json.load(open(os.path.join(HERE, "connectors", "static", "ice_adp_annual.json")))
ok(all(sum(_adp["components_cbp_plus_ice"][fy]) == tot for fy, tot in _adp["adp_by_fy"].items()),
   "ADP static: every year passes ICE's own component-sum check")
_eoat = json.load(open(os.path.join(HERE, "connectors", "static", "eo_alltime.json")))
ok(next(p["total"] for p in _eoat["nara_modern"] if "1st term" in p["president"]) == 220
   and next(p["total"] for p in _eoat["nara_modern"] if p["president"] == "Barack Obama") == 276,
   "EO all-time static: Trump-1 consistency check (220) + the flagged Obama count (276)")
_fz = json.load(open(os.path.join(HERE, "connectors", "static", "frozen_sources.json")))
ok(len(_fz["sources"]) == 8 and all(e.get("url") and e.get("last_update") for e in _fz["sources"]),
   "frozen-sources static: 8 entries, each dated and cited")

print("== v3: connector logic (no network) ==")
import votehub_approval as vap
_g = vap.attach_gallup({}, datetime.date(2026, 8, 12))["gallup"]
ok(_g["term_quarter"] == 7 and _g["same_quarter"]["biden"] == 42.0,
   "approval: Aug 2026 maps to term quarter 7; Biden same-quarter attached")
ok(vap.attach_gallup({}, datetime.date(2025, 2, 1))["gallup"]["term_quarter"] == 1,
   "approval: Feb 2025 maps to quarter 1")

import dcas_military_deaths as dcm
_td = {"tableData": [{"army": "7", "navy": "1", "marines": "0", "airforce": "6",
                      "spaceforce": "0", "total": "14", "valid": True}],
       "extractionDate": "August 11, 2026"}
ok(dcm.table_total(_td) == 14 and dcm.parse_extraction_date(_td) == "2026-08-11",
   "DCAS: summary total + extraction date parse (real captured shape)")
_mm = dcm.monthly_points({"tableData": [
    {"month_Year": "FEBRUARY 2026", "tot_total": "0", "tot_kia": "0", "tot_acc": "0"},
    {"month_Year": "MARCH 2026", "tot_total": "13", "tot_kia": "7", "tot_acc": "6"},
    {"month_Year": "GRAND TOTAL", "tot_total": "14"}]})
ok(len(_mm) == 2 and _mm[1]["deaths"] == 13 and _mm[1]["hostile"] == 7,
   "DCAS: monthly rows parse; GRAND TOTAL row skipped")
ok(dcm.cumulative_series({"oefu": _mm, "oo": [{"date": "2026-03", "deaths": 4,
                                               "hostile": 4, "nonhostile": 0}]})[-1]["value"] == 17,
   "DCAS: cross-operation cumulative sums by month")

import eia_crude as ecr
_pts = ecr.parse_dnav_monthly('<tr><td>2026</td><td>13,570</td><td>13,580</td><td></td></tr>'
                              '<tr><td>notes</td><td>x</td></tr>')
ok(_pts == [{"date": "2026-01", "value": 13.57}, {"date": "2026-02", "value": 13.58}],
   "crude: dnav rows parse to million b/d; junk rows ignored")

import eia_renewables as ern
# real EIA Table 1.1 layout: 'Year YYYY' section headers + month rows ('Sept'
# abbreviation); 3 exact renewable columns; bare-year rows (Annual Totals / YTD)
# ignored; pumped storage + estimated small-scale solar excluded.
_ehdr = ["Period", "Coal", "Natural\nGas", "Nuclear", "Hydroelectric\nConventional",
         "Solar", "Renewable\nSources\nExcluding\nHydroelectric and Solar",
         "Hydroelectric\nPumped\nStorage", "Other",
         "Total Generation at Utility Scale Facilities", "Estimated Total Solar"]
_erows = [["Table 1.1. Net Generation by Energy Source"], ["(Thousand Megawatthours)"], [None],
          _ehdr,
          ["Annual Totals"], ["2024", "1", "1", "1", "1", "1", "1", "-1", "1", "10", "1"],
          ["Year 2025"],
          ["January", "100", "150", "60", "25", "30", "20", "-1", "5", "365.5", "8"],
          ["Sept", "90", "140", "60", "40", "50", "25", "-1", "5", "400", "9"],
          ["Year to Date"], ["2025", "9", "9", "9", "9", "9", "9", "-9", "9", "99", "9"]]
_er = ern.parse_table(_erows)
ok([p["date"] for p in _er] == ["2025-01", "2025-09"],
   "renewables: 'Year YYYY' sections + 'Sept' parsed; Annual-Totals/YTD bare years ignored")
ok(_er[0]["value"] == round((25 + 30 + 20) / 365.5 * 100, 1),
   "renewables: share = 3 renewable cols ÷ utility total; pumped storage + small-scale solar excluded")

import fr_emergencies as fre
_docs = [{"document_number": "1", "title": "Declaring a National Emergency at the Southern Border", "signing_date": "2025-01-20"},
         {"document_number": "2", "title": "Continuation of the National Emergency With Respect to Iran", "signing_date": "2025-03-05"},
         {"document_number": "3", "title": "Termination of Emergency With Respect to Cuba", "signing_date": "2025-04-01"},
         {"document_number": "4", "title": "Regulating Imports With a Reciprocal Tariff", "signing_date": "2025-04-02"}]
_dd = fre.declarations(_docs, datetime.date(2025, 1, 20))
ok([x["date"] for x in _dd] == ["2025-01-20", "2025-04-02"],
   "emergencies: continuations + terminations excluded by rule; declarations kept")

import ice_composition as icc
_crows = [["Currently Detained Criminality"], ["Criminality", "ICE", "CBP", "Total"],
          ["Convicted Criminal", 12000, 7329, 19329],
          ["Pending Criminal Charges", 9000, 6000, 15000],
          ["Other Immigration Violators", 20000, 11436, 31436]]
_cats = icc.reconcile(icc.criminality_block(_crows), 65765)
ok(_cats == {"convicted": 19329, "pending": 15000, "other": 31436}
   and round((15000 + 31436) / 65765 * 100, 1) == 70.6,
   "composition: label-anchored parse reconciles to Currently Detained (70.6% no conviction)")
try:
    icc.reconcile(icc.criminality_block(_crows), 90000)
    ok(False, "composition: irreconcilable totals must refuse to publish")
except RuntimeError:
    ok(True, "composition: irreconcilable totals refuse to publish (integrity check)")

import ice_custody_deaths as icd
_dates = icd.death_dates("".join(f"<tr><td>{d}</td><td>NAME</td></tr>" for d in
                                 ["04/12/2018", "10/05/2025", "January 5, 2026"]))
ok(len(_dates) == 3 and icd.fy_counts(_dates) == {2018: 1, 2026: 2},
   "custody deaths: row dates counted; Oct 2025 + Jan 2026 both land in FY2026")

import doj_clemency as djc
_chtml = ("<p><strong>May 28, 2025 - 16 Pardons and 6 Commutations</strong></p><table>"
          + "".join(f"<tr><td>Name {i}</td><td>D. Alaska</td><td>Five years (December 3, 2019)</td></tr>"
                    for i in range(22)) + "</table>"
          "<p><strong>October 1, 2025 - 1 Commutation (Amended)</strong></p>"
          "<p><strong>July 3, 2026 – 17 Pardons</strong></p>")
_b = djc.grant_batches(_chtml)
ok(_b == [("2025-05-28", 22, False), ("2025-10-01", 1, True), ("2026-07-03", 17, False)],
   "clemency: batch headings parsed (hyphen + en-dash), sentencing dates in rows ignored, amended flagged")

import nyu_warpowers as nwp
_urls = nwp.find_csv_urls('<a href="https://warpowers-data.herokuapp.com/download-48-hr-reports">CSV</a>'
                          '<a href="https://warpowers-data.herokuapp.com/download-periodic-reports">CSV</a>')
ok(len(_urls) == 2 and _urls[0].endswith("download-48-hr-reports"),
   "war powers: off-domain download endpoints discovered (first-live-run fix)")
import csv as _csv2, io as _io2
_wrows = [["Report", "Date Transmitted", "Link"]]
_d0 = datetime.date(1973, 11, 7)
for _i in range(120):
    _wrows.append([f"R{_i}", (_d0 + datetime.timedelta(days=_i * 160)).strftime("%m/%d/%Y"), "u"])
_buf = _io2.StringIO(); _csv2.writer(_buf).writerows(_wrows)
ok(len(nwp.report_dates(_buf.getvalue())) == 120,
   "war powers: date column auto-detected in the compilation CSV")

import rpc_refugees as rpr
_me = rpr.month_end_candidates(datetime.date(2026, 8, 12))
ok(_me[0] == datetime.date(2026, 7, 31) and _me[1] == datetime.date(2026, 6, 30),
   "refugees: month-end probing order (newest first)")
ok(rpr.fy_of(datetime.date(2025, 10, 1)) == 2026, "refugees: fiscal-year math")
# two real pypdf layouts (version-dependent grouping): 3.x one number per line,
# and 6.x the whole grand-total row on ONE line ('10,258 2,528 …' — the 13 Aug
# live-run bug). Both must extract the same total from the same file.
_rpdf_3x = ("Nationality\nJul\nGrand\nTotal\nAlabama\nTotal\nSouth Africa\n"
            "Kansas\nTotal\nSouth Africa\nTotal\n10,258\n2,528\n1,062\n801\n36\n4\n")
_rpdf_6x = ("Actual Destination\nState Name\nNationality\nNov\nJul\nGrand\nTotal\n"
            "Alabama\nTotal\nSouth Africa\nKansas\nTotal\nSouth Africa\nTotal\n"
            " 10,258 2,528 1,062 599 1,570 1,341 1,507 931 595 125\n36\n36\n4\n")
ok(rpr.grand_total_from_text(_rpdf_3x) == 10258 and rpr.grand_total_from_text(_rpdf_6x) == 10258,
   "refugees: grand total read from full text under both pypdf layouts (per-line and single-row)")
try:
    rpr.grand_total_from_text("Total\n500\n9,999\n")  # first != max
    ok(False, "refugees: mismatched first/max must refuse")
except RuntimeError:
    ok(True, "refugees: refuses when the grand-total cross-check fails (no guessing)")

import cms_medicaid as cmm
_tr = cmm.trim_leading_orphans([{"date": "2013-09", "value": 1}] +
                               [{"date": f"2016-{mm:02d}", "value": mm} for mm in range(1, 8)])
ok(_tr[0]["date"] == "2016-01" and len(_tr) == 7,
   "medicaid: leading orphan months trimmed at the first continuous run")

import fjc_judges as fjm
_at = fjm.all_time_totals([("Barack Obama", datetime.date(2009, 5, 1)),
                           ("George Washington", datetime.date(1789, 9, 26))])
ok(_at[0]["president"] == "George Washington", "judges: all-time totals ordered by first confirmation")

print("== v3: payloads & tiles ==")
_cd = B.payload(_m("ice_custody_deaths", [{"date": "2025-10", "value": 23}], value=23,
                   fy_counts={"2018": 12, "2024": 9, "2025": 32, "2026": 23}), {})
ok(_cd["template"] == "bars" and _cd["series"][0]["pts"][-1][2] == "’26*" and _cd["channels"],
   "custody-deaths payload: FY bars, current year marked to-date, furniture present")
_dt3 = B.payload(_m("ice_detention", [{"date": "2026-07", "value": 62517}], value=62517,
                    annual_adp={"values": {"2019": 50165, "2024": 37721}}), {})
ok(_dt3["template"] == "bars" and _dt3["series"][0]["pts"][0][1] == 50165
   and any(p[1] is None and p[2] == "’25" for p in _dt3["series"][0]["pts"]),
   "detention payload: verified annual bars + FY2025 labelled hole, never a zero")
_md = B.payload(_m("military_deaths", [{"date": "2026-02", "value": 0}, {"date": "2026-07", "value": 18}],
                   value=18, per_operation={}), {})
ok(_md["series"] and _md["markers"][0]["label"].startswith("Defense Casualty Analysis System") and _md["limits"],
   "military-deaths payload: cumulative line + recategorisation marker + influence note")
_ap3 = B.payload(_m("approval_rating", [{"date": "2025-02-01", "value": 51}, {"date": "2026-06-29", "value": 42}],
                    value=42, disapprove=56,
                    gallup={"quarterly": {"biden": {"1": 56.0, "7": 42.0},
                                          "trump1": {"7": 41.1}, "obama": {"7": 44.7}}}), {})
ok(len(_ap3["series"]) == 4 and [s["label"] for s in _ap3["series"]] == ["Trump ’25", "Biden", "Trump ’17", "Obama"]
   and [21, 42.0] in _ap3["series"][1]["pts"],
   "approval payload: VoteHub line + three Gallup quarterly lines (Q7 plotted at month 21), clean president labels")
_rf = B.payload(_m("refugee_admissions", [{"date": "2026-06", "value": 7730}], value=7730,
                   ceiling={"label": "FY2026 presidential ceiling", "value": 7500}), {})
ok(_rf["accrueBody"] and "7,730" in _rf["accrueBody"] and _rf["caveats"],
   "refugees payload: honest accrue state carries arrivals vs ceiling")
_mz3 = B.tile(_m("measles_cases", [{"date": f"{y}-12", "value": v} for y, v in
                                   [(2021, 49), (2022, 121), (2023, 59), (2024, 285), (2025, 2288), (2026, 2371)]],
                 value=2371, category="Health & Safety Net", unit="cases", direction="up_is_bad",
                 note="Confirmed US measles cases — x.", cadence="Weekly"))
ok("Worst Biden-term year (2024)" in _mz3 and "285" in _mz3,
   "measles tile: v3 comparison — vs the prior administration's years, from its own series")
_apt = B.tile(_m("approval_rating", [], value=42, category="Executive Power & Governance",
                 unit="% approve", disapprove=56, net=-14, note="x", cadence="Weekly",
                 gallup={"same_quarter": {"biden": 42.0, "trump1": 41.1, "obama": 44.7}}))
ok("vs Biden at the same point: 42%" in _apt and "Trump &#8217;25" in _apt and "Obama" in _apt
   and "VoteHub" not in _apt,
   "approval tile: v3 four-bar strip with clean president labels (survey basis moved to the caveat)")
_mdt = B.tile(_m("military_deaths", [], value=18, category="War & Defense", unit="deaths",
                 note="x. y.", cadence="Weekly", wounded_total=696,
                 per_operation={"Operation Epic Fury": {"deaths": 14},
                                "Overseas Operations": {"deaths": 4}}))
ok("military_deaths</h2>" in _mdt and "Op. Epic Fury" in _mdt,
   "military-deaths tile: card title is the metric, not a shadowed operation name (regression)")

print("== v3: border OHSS backfill (verified against the real workbook) ==")
_bf = json.load(open(os.path.join(HERE, "connectors", "static", "border_ohss_backfill.json")))
ok(len(_bf["series"]) == 108 and _bf["series"][0]["date"] == "2013-10"
   and _bf["series"][-1]["date"] == "2022-09",
   "border backfill static: 108 months, Oct 2013 – Sep 2022 exactly")
ok(all(p["date"] < "2022-10" for p in _bf["series"]),
   "border backfill static: never overlaps the live CBP series (boundary rule)")
ok(all(p["value"] % 10 == 0 for p in _bf["series"]) and "_verification" in _bf,
   "border backfill static: OHSS rounding intact + verification note embedded")
_bseries = _bf["series"] + [{"date": "2024-06", "value": 130415}, {"date": "2025-06", "value": 9300},
                            {"date": "2026-06", "value": 12901}]
_bt = B.tile(_m("border_encounters", _bseries, value=12901, as_of="2026-06",
                category="Immigration", unit="encounters", note="x.", cadence="Monthly",
                comparison={"label": "Same month, prior year", "value": 9300}))
ok("under Biden (2024: 130,415)" in _bt and "Same month last year" in _bt,
   "border tile: v3 comparison vs same month under Biden, YoY kept as secondary")
_bp = B.payload(_m("border_encounters", _bseries, value=12901, as_of="2026-06",
                   cadence="Monthly"), {})
ok(len(_bp["series"]) == 3 and not _bp.get("gaps"),
   "border payload: Trump-'17 line joins post-backfill; pre-backfill gap chip retired")
ok(any("Office of Homeland Security Statistics" in c for c in _bp["caveats"]),
   "border payload: backfill provenance + rounding stated in caveats")

print("== stale_days override ==")
with tempfile.TemporaryDirectory() as td:
    common.DATA_DIR = td
    slow = {"id": "overdose_deaths", "name": "x", "category": "Health & Safety Net",
            "unit": "deaths", "direction": "up_is_bad", "cadence": "Monthly",
            "stale_days": 240, "source": {"name": "CDC", "url": "x"}, "note": "n"}
    common.publish(dict(slow), series=[{"date": "2026-02", "value": 68641}])
    saved = json.load(open(os.path.join(td, "overdose_deaths.json")))
    ok(saved["stale_after"] == "2026-10-26", "stale_days=240 overrides the 70-day monthly clock")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
