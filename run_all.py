#!/usr/bin/env python3
"""Run every connector, then rebuild the static site.

Reliability contract (see project doc 00 — Reliability hardening):
  • UPTIME: a failing connector never blocks the others and never blocks the
    rebuild — the site always redeploys with last-good data.
  • VISIBILITY: if ANY connector fails (network error, bad data rejected by the
    validators, etc.) we exit non-zero AFTER building, so the GitHub Actions run
    goes red and GitHub emails the repo owner. A green run means everything
    refreshed cleanly; a red run means "look at me" while the site stays up.

Order note: ice_removals reuses ice_detention's workbook-fetch helper but each
runs standalone; tariff_rate reuses treasury_tariffs' fetch. The SEMI scrapers
run last so the cheap API connectors always land first in the log.
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONNECTORS = [
    # --- v1 nine (live since Jul 2026) ---
    "federal_register_eo.py",
    "treasury_debt.py",
    "treasury_deficit.py",
    "bls_inflation.py",
    "bls_unemployment.py",
    "eia_gas.py",
    "census_trade.py",
    "cbp_border.py",   # verified against the real June-2026 file (Jul 2026)
    "ice_detention.py",
    # --- v2 expansion: keyless-API set ---
    "fred_groceries.py",
    "fred_gdp.py",
    "fred_real_wages.py",
    "fred_federal_workforce.py",
    "treasury_tariffs.py",
    "treasury_interest.py",
    "tariff_rate.py",          # computed: MTS duties ÷ FRED goods imports
    "cdc_overdoses.py",
    "cms_medicaid.py",
    "fjc_judges.py",
    # --- v3 additions: keyless-API set (register locked 12 Aug 2026) ---
    "fred_cpi.py",             # CPI-U deflator (support series) for real-price views
    "fred_electricity.py",
    "treasury_defense.py",
    "usaspending_aid.py",
    "fr_emergencies.py",       # derived count, rules printed on the card
    "dcas_military_deaths.py", # keyless JSON API (endpoints pinned via creator capture)
    # --- v2 expansion: SEMI set (scrapes/workbooks; safe-fail) ---
    "ice_removals.py",         # same ICE workbook as ice_detention
    "va_backlog.py",
    "cdc_measles.py",
    "votehub_approval.py",
    # --- v3 additions: SEMI set (scrapes/workbooks/PDF; safe-fail) ---
    "ice_composition.py",      # same ICE workbook fetch, third metric
    "ice_custody_deaths.py",
    "eia_crude.py",
    "eia_renewables.py",
    "doj_clemency.py",
    "nyu_warpowers.py",
    "rpc_refugees.py",         # first PDF parser — workflow must install pypdf
    # --- transparency watch: flags a frozen source that may have resumed (fail-safe) ---
    "frozen_check.py",
]


def run(path):
    print(f"→ {path}", flush=True)
    subprocess.run([sys.executable, os.path.join(HERE, path)], check=True)


failures = []
for c in CONNECTORS:
    try:
        run(os.path.join("connectors", c))
    except subprocess.CalledProcessError as e:
        failures.append(c)
        print(f"  ! {c} FAILED ({e}) — keeping last-good data for this metric", flush=True)

# Always rebuild so the site redeploys with whatever data we have (last-good
# for any connector that failed).
run("build.py")

if failures:
    print(f"\n✗ {len(failures)} connector(s) failed: {', '.join(failures)}", flush=True)
    print("  Site rebuilt with last-good data; failing this run so it is visible.", flush=True)
    sys.exit(1)

print("\n✓ all connectors succeeded.")
