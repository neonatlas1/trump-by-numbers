#!/usr/bin/env python3
"""Frozen-source resume watch (powers the /transparency page's honesty).

Enhancement-only and fail-SAFE: this never blocks the site, and it never reddens a
run on its own errors (network, parse, a server being down) — it returns non-zero
ONLY when it is confident a frozen government source has started publishing again,
so the owner gets the usual GitHub failure email to review it. Everything else exits 0.

Signal: the HTTP Last-Modified date on each government source URL. If the server
reports a modification date clearly newer than the recorded last_update, that source
may have resumed. To kill noise from servers that return a rolling "now" as
Last-Modified, a candidate must appear on TWO consecutive daily runs before it flags,
and each distinct modification date flags at most once. State lives in
data/frozen_state.json (committed by the workflow), so the flag fires exactly once.

VoteHub (gov:false) is skipped here — its status is driven live by the approval
connector's source_stalled_since, and the page reads that directly.
"""
import os
import sys
import json
import datetime
import email.utils
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCES = os.path.join(HERE, "static", "frozen_sources.json")
STATE = os.path.join(ROOT, "data", "frozen_state.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; TrumpByNumbers/1.0; +https://trumpbynumbers.pages.dev)"}
MARGIN_DAYS = 3


def _date(s):
    for f in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _last_modified(url):
    """(last_modified_date | None, etag | None); never raises."""
    for method in ("head", "get"):
        try:
            r = getattr(requests, method)(url, headers=UA, timeout=20, allow_redirects=True)
            lm, etag = r.headers.get("Last-Modified"), r.headers.get("ETag")
            d = None
            if lm:
                try:
                    d = email.utils.parsedate_to_datetime(lm).date()
                except Exception:
                    d = None
            if d or etag:
                return d, etag
        except Exception:
            continue
    return None, None


def main():
    try:
        doc = json.load(open(SOURCES))
    except Exception as e:  # noqa: BLE001
        print(f"  frozen_check: cannot read sources ({e}); skipping")
        return 0
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}

    today = datetime.date.today()
    flags = []
    for e in doc.get("sources", []):
        if not e.get("gov", True):
            continue
        url = e["url"]
        recorded = _date(e["last_update"])
        lm, etag = _last_modified(url)
        st = state.get(url, {})
        lm_s = lm.isoformat() if lm else None
        # A publication clearly newer than the recorded last release, and not a
        # future/"now" rolling stamp. Must persist across two runs before flagging.
        candidate = bool(lm and recorded and lm > recorded + datetime.timedelta(days=MARGIN_DAYS)
                         and lm <= today)
        if candidate:
            if st.get("pending_lm") == lm_s and st.get("flagged_lm") != lm_s:
                flags.append(f"{e['name']}: server reports Last-Modified {lm_s}, newer than the "
                             f"recorded {e['last_update']} — it may have resumed. Review {url}")
                st["flagged_lm"] = lm_s
            else:
                st["pending_lm"] = lm_s
        else:
            st["pending_lm"] = None
        st["last_modified"] = lm_s
        st["etag"] = etag
        st["checked"] = today.isoformat()
        state[url] = st

    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(state, open(STATE, "w"), indent=2, sort_keys=True)
    except Exception as e:  # noqa: BLE001
        print(f"  frozen_check: could not write state ({e})")

    if flags:
        print("  ✗ frozen_check: possible source resumption(s) detected:")
        for f in flags:
            print("    -", f)
        print("  Update or remove the entry in connectors/static/frozen_sources.json.")
        return 1
    print("  ✓ frozen_check: no government-source resumption detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
