#!/usr/bin/env python3
"""Build the static dashboard from data/*.json. No network needed.

Cards are grouped under category headers. Each card shows its own data date
('as of …') prominently and carries a client-side freshness check: a small
"⚠ data may be stale" flag appears whenever the visitor's clock is past the
metric's `stale_after` date. That check runs in the browser, so it keeps
escalating honestly even if the pipeline dies and the page freezes, unlike the
build timestamp, which is always fresh and therefore misleading (it is kept, but
de-emphasised, in the footer)."""
import json
import glob
import os
import re
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "site", "index.html")

TOTAL_PLANNED = 35   # v3 register (project doc 03), locked 12 Aug 2026
CATEGORY_ORDER = [
    "Cost of Living", "Economy & Jobs", "Trade & Tariffs", "Public Finances",
    "Energy", "Immigration", "Health & Safety Net",
    "Executive Power & Governance", "War & Defense",
]
# Display name for each category — used for BOTH the tab button AND the section
# heading, so the two always match. The internal category names above (and in
# CATEGORIES) and the slugs derived from them are UNCHANGED — so grouping, deep
# links (#t/<slug>) and the connectors' category stamps are all unaffected.
# This map only renames what the reader sees.
TAB_LABEL = {
    "Cost of Living": "Prices",
    "Economy & Jobs": "Economy",
    "Trade & Tariffs": "Trade",
    "Public Finances": "Debt",
    "Energy": "Energy",
    "Immigration": "Immigration",
    "Health & Safety Net": "Health",
    "Executive Power & Governance": "Governance",
    "War & Defense": "Defense",
}
ORDER = [
    "inflation", "grocery_prices", "gas_price",
    "real_gdp", "unemployment", "real_wages", "federal_workforce",
    "tariff_revenue", "effective_tariff_rate", "trade_deficit",
    "national_debt", "budget_deficit", "interest_on_debt",
    "electricity_price", "crude_oil", "renewable_share",
    "border_encounters", "ice_removals", "ice_detention",
    "ice_composition", "ice_custody_deaths", "refugee_admissions",
    "overdose_deaths", "measles_cases", "medicaid_enrollment", "va_claims_backlog",
    "executive_orders", "judges_confirmed", "approval_rating",
    "clemency", "national_emergencies",
    "defense_outlays", "foreign_aid", "war_powers", "military_deaths",
]
# Canonical id -> v2 category. Applied at load so the board groups correctly
# even from data files written before the category migration (the connectors
# also stamp the new names; this makes the grouping deterministic either way).
CATEGORIES = {
    "inflation": "Cost of Living", "grocery_prices": "Cost of Living", "gas_price": "Cost of Living",
    "real_gdp": "Economy & Jobs", "unemployment": "Economy & Jobs",
    "real_wages": "Economy & Jobs", "federal_workforce": "Economy & Jobs",
    "tariff_revenue": "Trade & Tariffs", "effective_tariff_rate": "Trade & Tariffs",
    "trade_deficit": "Trade & Tariffs",
    "national_debt": "Public Finances", "budget_deficit": "Public Finances",
    "interest_on_debt": "Public Finances",
    "border_encounters": "Immigration", "ice_removals": "Immigration", "ice_detention": "Immigration",
    "overdose_deaths": "Health & Safety Net", "measles_cases": "Health & Safety Net",
    "medicaid_enrollment": "Health & Safety Net", "va_claims_backlog": "Health & Safety Net",
    "executive_orders": "Executive Power & Governance",
    "judges_confirmed": "Executive Power & Governance",
    "approval_rating": "Executive Power & Governance",
    # --- v3 additions (register locked 12 Aug 2026) ---
    "electricity_price": "Energy", "crude_oil": "Energy", "renewable_share": "Energy",
    "ice_composition": "Immigration", "ice_custody_deaths": "Immigration",
    "refugee_admissions": "Immigration",
    "clemency": "Executive Power & Governance",
    "national_emergencies": "Executive Power & Governance",
    "defense_outlays": "War & Defense", "foreign_aid": "War & Defense",
    "war_powers": "War & Defense", "military_deaths": "War & Defense",
}
STALE_DAYS = {"biweek": 30, "as signed": 12, "as-signed": 12, "as confirmed": 14,
              "dai": 5, "week": 14, "month": 70, "quarter": 130}
DEFAULT_STALE_DAYS = 45


# ---- formatting helpers -----------------------------------------------------
def money_compact(v):
    a = abs(v)
    if a >= 1e12: return f"${v/1e12:.2f}T"
    if a >= 1e9:  return f"${v/1e9:.1f}B"
    if a >= 1e6:  return f"${v/1e6:.1f}M"
    return f"${v:,.0f}"


def num(v):
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,}"


def pretty_date(s):
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            d = datetime.datetime.strptime(s, fmt)
            return d.strftime("%b %Y") if fmt == "%Y-%m" else d.strftime("%b %-d, %Y")
        except ValueError:
            continue
    return s


def effective_date(as_of):
    try:
        if len(as_of) == 7:
            y, m = int(as_of[:4]), int(as_of[5:7])
            nm = datetime.date(y + (m == 12), (m % 12) + 1, 1)
            return nm - datetime.timedelta(days=1)
        return datetime.date.fromisoformat(as_of)
    except Exception:
        return datetime.date.today()


def stale_after(m):
    if m.get("stale_after"):
        return m["stale_after"]
    cad = (m.get("cadence") or "").lower()
    days, best = DEFAULT_STALE_DAYS, -1
    for key, d in STALE_DAYS.items():
        if key in cad and len(key) > best:
            days, best = d, len(key)
    return (effective_date(m["as_of"]) + datetime.timedelta(days=days)).isoformat()


# ---- per-metric render ------------------------------------------------------
def render_bars(rows, accent):
    mx = max(r[1] for r in rows) or 1
    out = []
    for label, val, disp, tone in rows:
        w = max(2, round(abs(val) / mx * 100))
        color = {"accent": accent, "muted": "var(--muted)",
                 "critical": "var(--critical)", "good": "var(--good)",
                 "t25": "var(--pres-t25)", "biden": "var(--pres-biden)",
                 "t17": "var(--pres-t17)", "obama": "var(--pres-obama)"}.get(tone, tone)
        out.append(f"""
        <div class="bar-row">
          <div class="bar-label">{label}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{w}%;background:{color}"></div></div>
          <div class="bar-val">{disp}</div>
        </div>""")
    return "".join(out)


# Clean collapsed-card descriptions: what the metric is and how it is measured, in plain
# language with acronyms expanded. Flags / caveats live in the expanded "Read this number
# carefully" block, not here. (Card-design review pass.)
DESC = {
    "inflation": "How fast consumer prices are rising: the change in the Consumer Price Index (all items) over the past 12 months.",
    "grocery_prices": "Grocery (food-at-home) prices compared with a year earlier, seasonally adjusted.",
    "gas_price": "The US average retail price of regular gasoline, per gallon.",
    "real_gdp": "Growth of the economy: the quarter-on-quarter change in inflation-adjusted gross domestic product (GDP), annualized.",
    "unemployment": "The share of people who want a job and are actively looking but cannot find one (the standard U-3 rate), seasonally adjusted.",
    "real_wages": "Typical pay for full-time workers after inflation: median usual weekly earnings in constant (1982-84) dollars.",
    "federal_workforce": "The number of federal civilian employees, including the Postal Service, from the monthly jobs report.",
    "tariff_revenue": "Customs duties (tariffs) collected so far this fiscal year, which resets each October. Shown both gross and net of refunds.",
    "effective_tariff_rate": "The average tariff actually paid at the border: gross customs duties as a share of the value of goods imported that month.",
    "trade_deficit": "How much more the US imports than it exports each month, across goods and services.",
    "national_debt": "The total amount the federal government owes: total public debt outstanding.",
    "budget_deficit": "How much more the government has spent than it has collected so far this fiscal year (resets each October).",
    "interest_on_debt": "Interest the government has paid on the national debt so far this fiscal year (resets each October).",
    "electricity_price": "The average residential price of electricity, in cents per kilowatt-hour (US city average).",
    "crude_oil": "US crude oil pumped from wells, in millions of barrels per day.",
    "renewable_share": "The share of US utility-scale electricity generated from renewable sources: hydro, wind, solar, geothermal and biomass.",
    "border_encounters": "The number of times US authorities encountered someone at the southwest land border each month.",
    "ice_removals": "People removed (deported) from the US this fiscal year, as recorded in ICE's published statistics workbook.",
    "ice_detention": "The average number of people held in ICE detention at any given time this fiscal year.",
    "ice_composition": "The share of people in ICE detention who have no criminal conviction, using ICE's own categories.",
    "ice_custody_deaths": "The number of people who have died while in ICE detention, from ICE's own death-reporting page.",
    "refugee_admissions": "The number of refugees formally admitted to the US this fiscal year, from the State Department's monthly report.",
    "overdose_deaths": "Estimated US drug overdose deaths over the most recent 12 months, from provisional Centers for Disease Control and Prevention data.",
    "measles_cases": "Confirmed measles cases reported to the Centers for Disease Control and Prevention this year.",
    "medicaid_enrollment": "The number of people enrolled in Medicaid and the Children's Health Insurance Program (CHIP), from state reports.",
    "va_claims_backlog": "Veterans' disability-compensation claims that have waited more than 125 days for a decision (the VA's backlog definition).",
    "executive_orders": "The number of executive orders the president has signed since taking office, from the Federal Register.",
    "judges_confirmed": "Lifetime federal judges (Article III) confirmed by the Senate this term, from the Federal Judicial Center.",
    "approval_rating": "The share of the public that approves of the president's job performance, averaged from recent national polls. Opinion data, not an official government statistic.",
    "clemency": "Pardons and commutations the president has granted this term, from the Department of Justice's grants page.",
    "national_emergencies": "New national emergencies the president has declared under the National Emergencies Act this term.",
    "defense_outlays": "Money spent by the Department of Defense on military programs so far this fiscal year (pay, operations, procurement and research).",
    "foreign_aid": "Federal money committed to international affairs (budget function 150): development and humanitarian aid, security assistance, diplomacy and contributions to international organizations.",
    "war_powers": "Reports the president has sent to Congress this term under the War Powers Resolution, the official record of US military action abroad.",
    "military_deaths": "US military deaths in the current named operations, both hostile and non-hostile, from the Defense Casualty Analysis System.",
}


# ---- share hook text (brief 09, MVP) ----------------------------------------
# Part 1 of a shared message: the typed text, different per card. Four lines,
# no em dashes: a question (same template, metric noun slotted in), the current
# value, the board's comparison line, then the link. Value + comparison come
# straight from the collapsed card, so nothing travels that isn't on the board.
import html as _htmllib

SHARE_NOUN = {
    "inflation": "inflation", "grocery_prices": "grocery prices",
    "gas_price": "gas prices", "real_gdp": "GDP growth",
    "unemployment": "unemployment", "real_wages": "real wages",
    "federal_workforce": "the federal workforce", "tariff_revenue": "tariff revenue",
    "effective_tariff_rate": "tariffs", "trade_deficit": "the trade deficit",
    "national_debt": "the national debt", "budget_deficit": "the budget deficit",
    "interest_on_debt": "interest on the debt", "electricity_price": "electricity prices",
    "crude_oil": "US oil production", "renewable_share": "renewable electricity",
    "border_encounters": "border encounters", "ice_removals": "ICE removals",
    "ice_detention": "the ICE detention population",
    "ice_composition": "ICE detention", "ice_custody_deaths": "deaths in ICE custody",
    "refugee_admissions": "refugee admissions", "overdose_deaths": "drug overdose deaths",
    "measles_cases": "measles", "medicaid_enrollment": "Medicaid enrollment",
    "va_claims_backlog": "the VA claims backlog", "executive_orders": "executive orders",
    "judges_confirmed": "federal judge confirmations", "approval_rating": "presidential approval",
    "clemency": "clemency", "national_emergencies": "national emergencies",
    "defense_outlays": "defense spending", "foreign_aid": "foreign aid",
    "war_powers": "war-powers reports to Congress", "military_deaths": "US military deaths",
}
# A few metrics don't fit the template cleanly, so they carry a full question.
SHARE_Q = {
    "ice_composition": "How many people in ICE detention have no criminal conviction?",
}
# Cumulative counts read better as "So far" than "Now".
SHARE_COUNT = {
    "executive_orders", "judges_confirmed", "national_emergencies",
    "war_powers", "clemency", "military_deaths", "ice_removals",
    "national_emergencies",
}


def _plain(s):
    """HTML/entity string -> clean one-line plain text for a share message:
    drop tags, decode entities, strip direction arrows, remove dashes."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = _htmllib.unescape(s)
    # keep the direction the board's arrow carried, as a word
    for ch in ("▲", "△", "↑"):
        s = s.replace(ch, " up ")
    for ch in ("▼", "▽", "↓"):
        s = s.replace(ch, " down ")
    for ch in ("→", "←", "➔"):
        s = s.replace(ch, "")
    s = s.replace("—", ", ").replace("–", "-")   # em / en dash
    s = re.sub(r"\s+", " ", s).strip()
    return s.replace(" ,", ",").replace(" .", ".")


def share_text(m, hero, delta):
    """Assemble the per-card typed hook (Part 1). Returns plain text with real
    newlines; caller escapes it into a data attribute."""
    mid = m["id"]
    q = SHARE_Q.get(mid)
    if not q:
        noun = SHARE_NOUN.get(mid, m["name"].split("(")[0].strip().lower())
        q = f"What's actually happened to {noun} under Trump?"
    stat = []
    val = _plain(hero)
    if val:
        stat.append(("So far " if mid in SHARE_COUNT else "Now ") + val)
    cmp = _plain(delta)
    if cmp:
        stat.append(cmp)
    # blank line between the hook question and the numbers, so the message
    # reads as two breathing blocks rather than one dense stack. The link is
    # appended by the messaging app below this.
    return q + ("\n\n" + "\n".join(stat) if stat else "")


def _share_attrs(m, hero, delta):
    """data-* attributes that carry Part 1 text + the ?c= link to chart.js."""
    text = _htmllib.escape(share_text(m, hero, delta), quote=True).replace("\n", "&#10;")
    url = f"{SITE_URL}/?c={m['id']}"
    return f'data-share-text="{text}" data-share-url="{url}"'


def tile(m):
    cat, name, src = m["category"], m["name"], m["source"]
    accent = "var(--series-1)"
    delta, bars, sub = "", "", m.get("note", "")

    if m["id"] == "executive_orders":
        hero = num(m["value"]); comp = m["comparison"]
        delta = f'<span class="delta neutral">{num(m["value"]-comp["value"])} more than Biden ({num(comp["value"])}) at the same point</span>'
        bars = render_bars([("Trump", m["value"], num(m["value"]), "accent"),
                            ("Biden", comp["value"], num(comp["value"]), "muted")], accent)
        sub = "Since inauguration · " + pretty_date(m["since"])

    elif m["id"] == "national_debt":
        hero = money_compact(m["value"]); base = m["baseline"]
        inc = m["value"] - base["value"]; pct = inc / base["value"] * 100
        delta = f'<span class="delta bad">&#9650; {money_compact(inc)} (+{pct:.1f}%) since inauguration</span>'
        bars = render_bars([("Now", m["value"], money_compact(m["value"]), "critical"),
                            ("Inauguration", base["value"], money_compact(base["value"]), "muted")], accent)
        sub = "Total public debt outstanding"

    elif m["id"] == "budget_deficit":
        hero = f'${m["value"]:,.0f}B'
        sub = m["note"]
        if m.get("comparison"):
            comp = m["comparison"]; diff = m["value"] - comp["value"]
            tone = "bad" if diff > 0 else "good"; arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = f'<span class="delta {tone}">{arrow} ${abs(diff):,.0f}B vs the same point last fiscal year (${comp["value"]:,.0f}B)</span>'
            bars = render_bars([("This FY", m["value"], f'${m["value"]:,.0f}B', "critical"),
                                ("Prior FY", comp["value"], f'${comp["value"]:,.0f}B', "muted")], accent)

    elif m["id"] == "inflation":
        hero = f'{m["value"]}%'; tgt = m["target"]; gap = m["value"] - tgt["value"]
        tone = "bad" if gap > 0 else "good"; arrow = "&#9650;" if gap > 0 else "&#9660;"
        delta = f'<span class="delta {tone}">{arrow} {abs(gap):.1f} pts {"above" if gap>0 else "below"} the Fed&#39;s {tgt["value"]}% target</span>'
        bars = render_bars([("CPI (YoY)", m["value"], f'{m["value"]}%', "critical" if gap > 0 else "good"),
                            ("Fed target", tgt["value"], f'{tgt["value"]}%', "muted")], accent)
        sub = m["note"]

    elif m["id"] == "unemployment":
        hero = f'{m["value"]}%'; base = m["baseline"]; diff = m["value"] - (base["value"] or m["value"])
        tone = "bad" if diff > 0 else "good"; arrow = "&#9650;" if diff > 0 else "&#9660;"
        delta = f'<span class="delta {tone}">{arrow} {abs(diff):.1f} pts since inauguration ({base["value"]}%)</span>'
        bars = render_bars([("Now", m["value"], f'{m["value"]}%', "critical" if diff > 0 else "good"),
                            ("Inauguration", base["value"] or 0, f'{base["value"]}%', "muted")], accent)
        sub = m["note"]

    elif m["id"] == "gas_price":
        hero = f'${m["value"]:.2f}'; base = m["baseline"]; diff = m["value"] - base["value"]; pct = diff / base["value"] * 100
        tone = "bad" if diff > 0 else "good"; arrow = "&#9650;" if diff > 0 else "&#9660;"
        delta = f'<span class="delta {tone}">{arrow} ${abs(diff):.2f} ({pct:+.0f}%) since inauguration</span>'
        bars = render_bars([("Now", m["value"], f'${m["value"]:.2f}', "critical" if diff > 0 else "good"),
                            ("Inauguration", base["value"], f'${base["value"]:.2f}', "muted")], accent)
        sub = m["note"].split(".")[0]

    elif m["id"] == "trade_deficit":
        hero = f'${m["value"]:.1f}B'; base = m["baseline"]; diff = m["value"] - base["value"]
        tone = "bad" if diff > 0 else "good"; arrow = "&#9650;" if diff > 0 else "&#9660;"
        pct = (diff / base["value"] * 100) if base["value"] else 0
        delta = f'<span class="delta {tone}">{arrow} ${abs(diff):.1f}B ({pct:+.0f}%) vs {base["label"].lower()}</span>'
        bars = render_bars([("Latest", m["value"], f'${m["value"]:.1f}B', "critical" if diff > 0 else "good"),
                            (base["label"].split("(")[0].strip()[:12] or "Baseline", base["value"], f'${base["value"]:.1f}B', "muted")], accent)
        sub = m["note"]

    elif m["id"] == "border_encounters":
        hero = num(m["value"])
        sub = m["note"]
        # v3 comparison change (locked 12 Aug 2026): the headline compares to
        # the SAME CALENDAR MONTH in 2024, the last full Biden year, because
        # "vs last year" now compares this administration to itself. Computed
        # from the stored series (backfill-independent for 2024 months);
        # year-over-year stays as the secondary line.
        biden_val = None
        if m.get("as_of") and m.get("series"):
            want = f"2024-{str(m['as_of'])[5:7]}"
            biden_val = next((p["value"] for p in m["series"] if p["date"] == want), None)
        if biden_val:
            diff = m["value"] - biden_val
            pct = diff / biden_val * 100
            arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = (f'<span class="delta neutral">{arrow} {pct:+.0f}% vs the same month '
                     f'under Biden (2024: {num(biden_val)})</span>')
            rows = [("This year", m["value"], num(m["value"]), "accent"),
                    ("Same month 2024 (Biden)", biden_val, num(biden_val), "muted")]
            if m.get("comparison"):
                rows.insert(1, ("Same month last year", m["comparison"]["value"],
                                num(m["comparison"]["value"]), "muted"))
            bars = render_bars(rows, accent)
        elif m.get("comparison"):
            comp = m["comparison"]; diff = m["value"] - comp["value"]
            pct = (diff / comp["value"] * 100) if comp["value"] else 0
            arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = f'<span class="delta neutral">{arrow} {pct:+.0f}% vs the same month last year ({num(comp["value"])})</span>'
            bars = render_bars([("Latest", m["value"], num(m["value"]), "accent"),
                                ("Yr earlier", comp["value"], num(comp["value"]), "muted")], accent)

    elif m["id"] == "ice_detention":
        hero = num(m["value"])
        sub = m["note"]
        if m.get("currently_detained"):
            delta = f'<span class="delta neutral">Currently detained (point-in-time): {num(m["currently_detained"])}</span>'
        else:
            delta = '<span class="delta neutral">Average daily population in ICE detention</span>'

    # ---- v2 expansion cards (28 Jul 2026) ----
    elif m["id"] == "grocery_prices":
        hero = f'{m["value"]}%'
        sub = m["note"]
        if m.get("baseline"):
            base = m["baseline"]; gap = m["value"] - base["value"]
            tone = "bad" if gap > 0 else "good"; arrow = "&#9650;" if gap > 0 else "&#9660;"
            delta = f'<span class="delta {tone}">{arrow} {abs(gap):.1f} pts vs {base["value"]}% at inauguration</span>'
            bars = render_bars([("Now (YoY)", m["value"], f'{m["value"]}%', "critical" if gap > 0 else "good"),
                                ("Inauguration", base["value"], f'{base["value"]}%', "muted")], accent)

    elif m["id"] == "real_gdp":
        hero = f'{m["value"]:+.1f}%'
        sub = m["note"]
        if m.get("comparison") and m.get("term_avg") is not None:
            comp = m["comparison"]
            delta = (f'<span class="delta neutral">Term average {m["term_avg"]:+.1f}% · '
                     f'{comp["label"]}: {comp["value"]:+.1f}%</span>')
            bars = render_bars([("This term", m["term_avg"], f'{m["term_avg"]:+.1f}%', "accent"),
                                ("Biden", comp["value"], f'{comp["value"]:+.1f}%', "muted")], accent)

    elif m["id"] == "real_wages":
        hero = f'${m["value"]:,.0f}'
        sub = m["note"]
        if m.get("baseline"):
            base = m["baseline"]; diff = m["value"] - base["value"]
            pct = diff / base["value"] * 100 if base["value"] else 0
            tone = "good" if diff > 0 else ("bad" if diff < 0 else "neutral")
            arrow = "&#9650;" if diff > 0 else ("&#9660;" if diff < 0 else "")
            delta = f'<span class="delta {tone}">{arrow} {pct:+.1f}% since the inauguration quarter (${base["value"]:,.0f})</span>'
            bars = render_bars([("Now", m["value"], f'${m["value"]:,.0f}', "accent"),
                                ("Q1 2025", base["value"], f'${base["value"]:,.0f}', "muted")], accent)

    elif m["id"] == "federal_workforce":
        hero = f'{m["value"]:,.0f}k'
        sub = m["note"]
        if m.get("baseline"):
            base = m["baseline"]; diff = m["value"] - base["value"]
            pct = diff / base["value"] * 100 if base["value"] else 0
            arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = f'<span class="delta neutral">{arrow} {abs(diff):,.0f}k ({pct:+.1f}%) since inauguration ({base["value"]:,.0f}k)</span>'
            bars = render_bars([("Now", m["value"], f'{m["value"]:,.0f}k', "accent"),
                                ("Inauguration", base["value"], f'{base["value"]:,.0f}k', "muted")], accent)

    elif m["id"] == "tariff_revenue":
        hero = f'${m["value"]:,.0f}B'
        sub = m["note"]
        rows = [("This FY, gross", m["value"], f'${m["value"]:,.0f}B', "accent")]
        if m.get("net_fytd") is not None:
            rows.append(("This FY, net", m["net_fytd"], f'${m["net_fytd"]:,.0f}B', "muted"))
        if m.get("comparison"):
            comp = m["comparison"]
            rows.append(("Prior FY, gross", comp["value"], f'${comp["value"]:,.0f}B', "muted"))
            pieces = [f'prior FY gross ${comp["value"]:,.0f}B']
            if m.get("net_fytd") is not None:
                pieces.insert(0, f'net after refunds ${m["net_fytd"]:,.0f}B')
            delta = f'<span class="delta neutral">Gross fiscal-YTD · {" · ".join(pieces)}</span>'
        bars = render_bars(rows, accent)

    elif m["id"] == "effective_tariff_rate":
        hero = f'{m["value"]:.1f}%'
        sub = m["note"]
        if m.get("baseline"):
            base = m["baseline"]
            delta = f'<span class="delta neutral">vs {base["value"]:.1f}% at inauguration</span>'
            bars = render_bars([("Now", m["value"], f'{m["value"]:.1f}%', "accent"),
                                ("Inauguration", base["value"], f'{base["value"]:.1f}%', "muted")], accent)

    elif m["id"] == "interest_on_debt":
        hero = f'${m["value"]:,.0f}B'
        sub = m["note"]
        if m.get("comparison"):
            comp = m["comparison"]; diff = m["value"] - comp["value"]
            tone = "bad" if diff > 0 else "good"; arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = f'<span class="delta {tone}">{arrow} ${abs(diff):,.0f}B vs the same point last fiscal year (${comp["value"]:,.0f}B)</span>'
            bars = render_bars([("This FY", m["value"], f'${m["value"]:,.0f}B', "critical"),
                                ("Prior FY", comp["value"], f'${comp["value"]:,.0f}B', "muted")], accent)

    elif m["id"] == "ice_removals":
        hero = num(m["value"])
        sub = m["note"]
        if m.get("comparison"):
            comp = m["comparison"]
            delta = f'<span class="delta neutral">FY2024 full year (prior administration): {num(comp["value"])}</span>'
            bars = render_bars([("This FY so far", m["value"], num(m["value"]), "accent"),
                                ("FY2024 total", comp["value"], num(comp["value"]), "muted")], accent)

    elif m["id"] == "overdose_deaths":
        hero = num(m["value"])
        sub = m["note"]
        if m.get("baseline"):
            base = m["baseline"]; diff = m["value"] - base["value"]
            pct = diff / base["value"] * 100 if base["value"] else 0
            tone = "bad" if diff > 0 else "good"; arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = f'<span class="delta {tone}">{arrow} {num(abs(diff))} ({pct:+.0f}%) vs the 12 months ending at inauguration</span>'
            bars = render_bars([("Latest 12 mo", m["value"], num(m["value"]), "critical" if diff > 0 else "good"),
                                ("To Jan 2025", base["value"], num(base["value"]), "muted")], accent)

    elif m["id"] == "measles_cases":
        hero = num(m["value"])
        sub = m["note"].split(", ")[0] + "."
        # v3 comparison change (locked 12 Aug 2026): compare to the PRIOR
        # ADMINISTRATION'S years (the board's own compare-administrations
        # principle), computed from the stored series, plus last year.
        by_year = {int(p["date"][:4]): p["value"] for p in (m.get("series") or [])}
        biden_years = {y: v for y, v in by_year.items() if 2021 <= y <= 2024}
        if biden_years:
            worst_y = max(biden_years, key=biden_years.get)
            rows = [("This year so far", m["value"], num(m["value"]), "critical"),
                    (f"Worst Biden-term year ({worst_y})", biden_years[worst_y],
                     num(biden_years[worst_y]), "muted")]
            if by_year.get(2025) is not None:
                rows.insert(1, ("2025 full year", by_year[2025], num(by_year[2025]), "muted"))
            bars = render_bars(rows, accent)
            mult = m["value"] / biden_years[worst_y] if biden_years[worst_y] else 0
            delta = (f'<span class="delta bad">&#9650; {mult:.0f}&#215; the worst Biden-term year '
                     f'({worst_y}: {num(biden_years[worst_y])})</span>')
        elif m.get("comparison"):
            comp = m["comparison"]; diff = m["value"] - comp["value"]
            if diff > 0:
                delta = f'<span class="delta bad">&#9650; already above {comp["label"].lower()} ({num(comp["value"])})</span>'
            else:
                delta = f'<span class="delta neutral">{comp["label"]}: {num(comp["value"])}</span>'
            bars = render_bars([("This year so far", m["value"], num(m["value"]), "critical" if diff > 0 else "accent"),
                                (comp["label"], comp["value"], num(comp["value"]), "muted")], accent)

    elif m["id"] == "medicaid_enrollment":
        hero = f'{m["value"] / 1e6:.1f}M'
        sub = m["note"]
        if m.get("baseline"):
            base = m["baseline"]; diff = m["value"] - base["value"]
            arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = f'<span class="delta neutral">{arrow} {abs(diff) / 1e6:.1f}M since Dec 2024 ({base["value"] / 1e6:.1f}M)</span>'
            bars = render_bars([("Now", m["value"], f'{m["value"] / 1e6:.1f}M', "accent"),
                                ("Dec 2024", base["value"], f'{base["value"] / 1e6:.1f}M', "muted")], accent)

    elif m["id"] == "va_claims_backlog":
        hero = num(m["value"])
        sub = m["note"]
        if m.get("total_pending"):
            sub += f' Total pending now: {num(m["total_pending"])}.'
        if m.get("baseline"):
            base = m["baseline"]; diff = m["value"] - base["value"]
            pct = diff / base["value"] * 100 if base["value"] else 0
            tone = "bad" if diff > 0 else "good"; arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = f'<span class="delta {tone}">{arrow} {num(abs(diff))} ({pct:+.0f}%) since inauguration</span>'
            bars = render_bars([("Now", m["value"], num(m["value"]), "critical" if diff > 0 else "good"),
                                ("Inauguration", base["value"], num(base["value"]), "muted")], accent)

    elif m["id"] == "judges_confirmed":
        hero = num(m["value"])
        sub = m["note"]
        if m.get("comparison"):
            comp = m["comparison"]; diff = m["value"] - comp["value"]
            delta = f'<span class="delta neutral">{diff:+,.0f} vs his first term at the same point ({num(comp["value"])})</span>'
            rows = [("This term", m["value"], num(m["value"]), "accent"),
                    ("Term 1", comp["value"], num(comp["value"]), "muted")]
            if m.get("biden_same_point") is not None:
                rows.append(("Biden", m["biden_same_point"], num(m["biden_same_point"]), "muted"))
            bars = render_bars(rows, accent)

    elif m["id"] == "approval_rating":
        hero = f'{m["value"]:.0f}%'
        sub = m["note"]
        net_txt = ""
        if m.get("disapprove") is not None:
            net = m.get("net", m["value"] - m["disapprove"])
            net_txt = f'Disapprove {m["disapprove"]:.0f}% · net {net:+.0f}'
        # v3 comparison change (locked 12 Aug 2026): vs Biden at the same point
        # in term, via the sourced Gallup import, the four-bar strip. Basis is
        # mixed (current term: VoteHub aggregate; prior: Gallup quarterly
        # averages) and labelled as such on every bar.
        sq = (m.get("gallup") or {}).get("same_quarter") or {}
        if sq.get("biden") is not None:
            delta = (f'<span class="delta neutral">{net_txt} &#183; vs Biden at the same point: '
                     f'{sq["biden"]:.0f}%</span>')
            rows = [("Trump &#8217;25", m["value"], f'{m["value"]:.0f}%', "t25"),
                    ("Biden", sq["biden"], f'{sq["biden"]:.0f}%', "biden")]
            if sq.get("trump1") is not None:
                rows.append(("Trump &#8217;17", sq["trump1"], f'{sq["trump1"]:.0f}%', "t17"))
            if sq.get("obama") is not None:
                rows.append(("Obama", sq["obama"], f'{sq["obama"]:.0f}%', "obama"))
            bars = render_bars(rows, accent)
        elif m.get("disapprove") is not None:
            delta = f'<span class="delta neutral">{net_txt}</span>'
            bars = render_bars([("Approve", m["value"], f'{m["value"]:.0f}%', "accent"),
                                ("Disapprove", m["disapprove"], f'{m["disapprove"]:.0f}%', "muted")], accent)

    # ---- v3 register cards (locked 12 Aug 2026) ----
    elif m["id"] == "electricity_price":
        cents = m["value"] * 100
        hero = f'{cents:.1f}&#162;/kWh'
        sub = m["note"].split(".")[0] + "."
        if m.get("baseline"):
            base = m["baseline"]["value"] * 100
            diff = cents - base; pct = diff / base * 100
            tone = "bad" if diff > 0 else "good"; arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = f'<span class="delta {tone}">{arrow} {abs(diff):.1f}&#162; ({pct:+.0f}%) since inauguration</span>'
            bars = render_bars([("Now", cents, f'{cents:.1f}&#162;', "critical" if diff > 0 else "good"),
                                ("Inauguration", base, f'{base:.1f}&#162;', "muted")], accent)

    elif m["id"] == "crude_oil":
        hero = f'{m["value"]:.1f}M b/d'
        sub = m["note"].split(".")[0] + "."
        if m.get("baseline"):
            base = m["baseline"]["value"]; diff = m["value"] - base; pct = diff / base * 100
            arrow = "&#9650;" if diff > 0 else "&#9660;"
            rec = m.get("record") or {}
            rec_txt = f' &#183; record {rec["value"]:.1f} ({pretty_date(rec["date"])})' if rec.get("value") else ""
            delta = f'<span class="delta neutral">{arrow} {pct:+.1f}% since inauguration{rec_txt}</span>'
            bars = render_bars([("Now", m["value"], f'{m["value"]:.1f}', "accent"),
                                ("Inauguration", base, f'{base:.1f}', "muted")], accent)

    elif m["id"] == "renewable_share":
        hero = f'{m["value"]:.1f}%'
        sub = m["note"].split(".")[0] + "."
        if m.get("baseline"):
            base = m["baseline"]["value"]; diff = m["value"] - base
            arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = (f'<span class="delta neutral">{arrow} {abs(diff):.1f} pts vs Jan 2025 ({base}%) '
                     "&#8212; the mix is seasonal; compare same months</span>")
            bars = render_bars([("Now", m["value"], f'{m["value"]:.1f}%', "accent"),
                                ("Jan 2025", base, f'{base:.1f}%', "muted")], accent)

    elif m["id"] == "ice_composition":
        hero = f'{m["value"]:.1f}%'
        sub = m["note"]
        d = m.get("detail") or {}
        if d:
            noconv = d["pending_criminal_charges"] + d["other_immigration_violators"]
            delta = (f'<span class="delta neutral">{num(noconv)} of {num(d["total_detained"])} '
                     "detained have no criminal conviction</span>")
            bars = render_bars([("No conviction", noconv, num(noconv), "accent"),
                                ("Convicted", d["convicted_criminal"],
                                 num(d["convicted_criminal"]), "muted")], accent)

    elif m["id"] == "ice_custody_deaths":
        hero = num(m["value"])
        sub = m["note"].split(". ")[0] + "."
        fc = {int(k): v for k, v in (m.get("fy_counts") or {}).items()}
        if fc:
            latest = max(fc)
            rows = [(f"FY{fy}" + (" (to date)" if fy == latest else ""), n, num(n),
                     "accent" if fy == latest else "muted")
                    for fy, n in sorted(fc.items(), reverse=True)[:3]]
            bars = render_bars(rows, accent)
            if latest - 1 in fc:
                delta = f'<span class="delta neutral">FY{latest - 1} full year: {num(fc[latest - 1])}</span>'

    elif m["id"] == "refugee_admissions":
        hero = num(m["value"])
        sub = m["note"].split(". ")[0] + "."
        if m.get("ceiling"):
            c = m["ceiling"]
            delta = (f'<span class="delta neutral">Above the {num(c["value"])} {c["label"]}; '
                     "court-ordered cases sit outside it</span>")
            bars = render_bars([("Arrivals FYTD", m["value"], num(m["value"]), "accent"),
                                ("Ceiling", c["value"], num(c["value"]), "muted")], accent)

    elif m["id"] == "clemency":
        hero = num(m["value"])
        sub = m["note"].split(". ")[0] + "."
        ind = m.get("individuals_covered_approx")
        if ind:
            delta = (f'<span class="delta neutral">~{num(ind)} individuals covered incl. the '
                     "Jan 6 proclamation (one action, ~1,500 people)</span>")
        pp = m.get("per_president_individuals") or {}
        if pp and ind:
            bars = render_bars([("Trump &#8217;25 (~)", ind, f"~{num(ind)}", "t25"),
                                ("Biden", pp.get("biden", 0), num(pp.get("biden", 0)), "biden"),
                                ("Obama", pp.get("obama", 0), num(pp.get("obama", 0)), "obama"),
                                ("Trump &#8217;17", pp.get("trump1", 0), num(pp.get("trump1", 0)), "t17")], accent)

    elif m["id"] in ("national_emergencies", "war_powers"):
        hero = num(m["value"])
        sub = m["note"].split(". ")[0] + "."
        pt = m.get("prev_terms") or {}
        rows = [("Trump &#8217;25", m["value"], num(m["value"]), "t25")]
        for pid, lbl, tone in (("biden", "Biden", "biden"), ("trump1", "Trump &#8217;17", "t17"),
                               ("obama", "Obama", "obama")):
            v = pt.get(pid)
            if isinstance(v, dict) and v.get("same_point") is not None:
                rows.append((lbl, v["same_point"], num(v["same_point"]), tone))
        if len(rows) > 1:
            bars = render_bars(rows, accent)
            what = "New declarations" if m["id"] == "national_emergencies" else "Reports"
            delta = f'<span class="delta neutral">{what} at the same point in term</span>'

    elif m["id"] in ("defense_outlays", "foreign_aid"):
        hero = f'${m["value"]:,.0f}B'
        sub = m["note"].split(". ")[0] + "."
        if m.get("comparison"):
            comp = m["comparison"]; diff = m["value"] - comp["value"]
            arrow = "&#9650;" if diff > 0 else "&#9660;"
            delta = (f'<span class="delta neutral">{arrow} ${abs(diff):,.0f}B vs {comp["label"].lower()} '
                     f'(${comp["value"]:,.0f}B)</span>')
            bars = render_bars([("This FY", m["value"], f'${m["value"]:,.0f}B', "accent"),
                                ("Prior FY", comp["value"], f'${comp["value"]:,.0f}B', "muted")], accent)

    elif m["id"] == "military_deaths":
        hero = num(m["value"])
        sub = m["note"].split(". ")[0] + "."
        po = m.get("per_operation") or {}
        rows, first = [], True
        for op_name, v in po.items():   # NB: do not shadow tile()'s `name`
            if v.get("deaths") is None:
                continue
            rows.append((op_name.replace("Operation ", "Op. "), v["deaths"], num(v["deaths"]),
                         "accent" if first else "muted"))
            first = False
        if rows:
            bars = render_bars(rows, accent)
        if m.get("wounded_total"):
            delta = f'<span class="delta neutral">Wounded in action: {num(m["wounded_total"])}</span>'

    else:
        hero = str(m.get("value", ""))

    # card-design pass: generalise the four-bar same-point strip to term-comparable
    # metrics (headline delta stays; the strip gains the four-president context)
    if m["id"] in FOUR_BAR_FMT:
        fb = same_point_rows(m, FOUR_BAR_FMT[m["id"]])
        if fb:
            bars = render_bars(fb, accent)

    sub = DESC.get(m["id"], sub)   # clean, flag-free description (flags live in the caveats)

    sa = stale_after(m)
    # split a trailing "(qualifier)" out of the title so it can sit, quieter, below the name
    import re as _re
    _qm = _re.match(r'^(.*?)\s*\(([^)]*)\)\s*$', name)
    name_main, name_qual = (_qm.group(1), _qm.group(2)) if _qm else (name, "")
    qual_html = f'\n      <div class="tile-qual">{name_qual}</div>' if name_qual else ""
    return f"""
    <article class="tile" data-as-of="{m['as_of']}" data-stale-after="{sa}" data-cadence="{m['cadence'].lower()}" {_share_attrs(m, hero, delta)}>
      <button class="tile-share" type="button" aria-label="Share this metric">{_ICON_SHARE}</button>
      <h2 class="tile-name">{name_main}</h2>{qual_html}
      <div class="hero">{hero}</div>
      {delta}
      <div class="freshness">
        <span class="asof">as of {pretty_date(m['as_of'])}</span>
        <span class="stale-flag" hidden>&#9888; data may be stale</span>
      </div>
      <div class="tile-sub">{sub}</div>
      <div class="bars">{bars}</div>
      <div class="tile-foot">
        <a href="{src['url']}" target="_blank" rel="noopener">{src['name']} &#8594;</a>
        <span>updates {m['cadence'].lower()}</span>
      </div>
    </article>"""


# ---- presentation layer (phase 7): chart payloads ---------------------------
# Expanded views use three reusable templates (own-history / term-aligned /
# vs-benchmark; project doc 03 fixes each metric's pick). build.py pre-computes
# everything chart-ready here in Python and emits one small site/d/<id>.json per
# metric, fetched by the browser on first expand, "store deep, load shallow"
# all the way to the visitor. Browser JS (assets/chart.js, inlined) stays dumb.
#
# President colors (locked with the creator, 29 Jul 2026): the current term is
# red and Biden is blue (party-conventional). The reds/greens the collapsed
# cards use for good/bad deltas are DIFFERENT steps (#d03b3b/#0ca30c) from the
# series red (#e66767) so a direction cue can never impersonate a president
# line. Palette validated (colorblind separation + contrast, dark surface):
# worst adjacent pair ΔE 8.4, all lines also carry legend + direct labels.
ASSETS = os.path.join(HERE, "assets")
SITE_D = os.path.join(HERE, "site", "d")

PRES = {
    "trump2": {"label": "Trump ’25", "color": "#e66767", "inaug": datetime.date(2025, 1, 20)},
    "biden":  {"label": "Biden",     "color": "#3987e5", "inaug": datetime.date(2021, 1, 20)},
    "trump1": {"label": "Trump ’17", "color": "#199e70", "inaug": datetime.date(2017, 1, 20)},
    "obama":  {"label": "Obama",     "color": "#c98500", "inaug": datetime.date(2009, 1, 20)},
}
ACCENT = "#3987e5"      # single-series lines: the metric, not a president
SECOND = "#d95926"      # second non-president series (e.g. net vs gross)
TERM_MONTHS = 48        # aligned charts compare first terms, month 0–48
T2_START = PRES["trump2"]["inaug"]


def _pdate(s):
    return datetime.date(int(s[:4]), int(s[5:7]), 1) if len(s) == 7 else datetime.date.fromisoformat(s)


def _ems(d):
    return int(datetime.datetime(d.year, d.month, d.day,
                                 tzinfo=datetime.timezone.utc).timestamp() * 1000)


def _mon_idx(d, inaug):
    return (d.year - inaug.year) * 12 + (d.month - inaug.month)


def date_points(series):
    return [[_ems(_pdate(p["date"])), p["value"]] for p in series]


def aligned_monthly(series, pres, pct=False, months=TERM_MONTHS, base_by=0):
    """Series -> [[months_in_office, value]] for one president's first term.
    pct=True rebases to % change vs the earliest point at month <= base_by.
    base_by=0 (default) demands the inauguration month itself; QUARTERLY series
    never store month 0 (quarters are stamped with their END month, so the
    inauguration quarter lands at month 2), pass base_by=3 for those, which is
    what 'percent of the inauguration-quarter level' actually means. This was
    the real-wages empty-chart bug (creator-found, Aug 2026)."""
    inaug = PRES[pres]["inaug"]
    pts = []
    for p in series:
        mi = _mon_idx(_pdate(p["date"]), inaug)
        if 0 <= mi <= months:
            pts.append([mi, p["value"]])
    if not pts:
        return None
    if pct:
        base = next((v for m, v in pts if m <= base_by), None)
        if base is None:
            return None
        pts = [[m, round((v / base - 1) * 100, 2)] for m, v in pts]
    return pts


def carry_forward(pts, months=TERM_MONTHS):
    """Densify a cumulative counter: months with no events carry the running
    value (that IS the count's meaning, not interpolation of missing data)."""
    if not pts:
        return pts
    out, have = [], dict(pts)
    last = None
    for m in range(0, min(months, max(have)) + 1):
        if m in have:
            last = have[m]
        if last is not None:
            out.append([m, last])
    return out


def aligned_daily_pct(series, pres, months=TERM_MONTHS, thin_days=7):
    """Daily series -> weekly-thinned [[months_in_office, %growth since
    inauguration day]] (exact stored values, sampled, never smoothed)."""
    inaug = PRES[pres]["inaug"]
    rows = sorted((_pdate(p["date"]), p["value"]) for p in series)
    rows = [(d, v) for d, v in rows if 0 <= (d - inaug).days <= months * 30.44 + 15]
    if not rows:
        return None
    base = rows[0][1]
    pts, last = [], None
    for i, (d, v) in enumerate(rows):
        if last is None or (d - last).days >= thin_days or i == len(rows) - 1:
            pts.append([round((d - inaug).days / 30.4375, 2), round((v / base - 1) * 100, 2)])
            last = d
    return pts


def gdp_index(series, pres, quarters=16):
    """Quarterly annualized rates -> compounded index, 100 at the inauguration
    quarter's start (transparent formula: ×(1+r/100)^(1/4) per quarter)."""
    inaug = PRES[pres]["inaug"]
    pts, idx = [[0, 100.0]], 100.0
    n = 0
    for p in series:
        d = _pdate(p["date"])                      # stored as quarter-END month
        mi = _mon_idx(d, inaug) + 1                # months elapsed at quarter end
        if mi <= 0 or n >= quarters:
            continue
        if mi > TERM_MONTHS:
            break
        idx *= (1 + p["value"] / 100) ** 0.25
        pts.append([mi, round(idx, 2)])
        n += 1
    return pts if len(pts) > 1 else None


def _pseries(ids, series, **kw):
    """Aligned series list for the given presidents, newest-term first (fixed
    entity colors; presidents with no reachable data simply drop out)."""
    out = []
    for pid in ids:
        fn = kw.get("fn") or (lambda s, p: aligned_monthly(
            s, p, pct=kw.get("pct", False), base_by=kw.get("base_by", 0)))
        pts = fn(series, pid)
        if pts:
            out.append({"label": PRES[pid]["label"], "color": PRES[pid]["color"], "pts": pts})
    return out


# ---- card-design pass: generalised four-bar "same point in term" strip -------
# For a term-comparable metric with long stored history, read each president's
# value at the SAME months-in-office as the current term (from the metric's own
# series, sourced, not invented) and render Obama·Trump'17·Biden·Trump'25 as a
# four-bar strip in the president-identity palette. Presidents whose data doesn't
# reach that point in their term simply drop out (never faked).
FOUR_BAR_FMT = {
    "unemployment":          lambda v: f"{v:.1f}%",
    "gas_price":             lambda v: f"${v:.2f}",
    "electricity_price":     lambda v: f"{v*100:.1f}&#162;",
    "crude_oil":             lambda v: f"{v:.1f}",
    "trade_deficit":         lambda v: f"${v:.0f}B",
    "federal_workforce":     lambda v: num(v),
    "effective_tariff_rate": lambda v: f"{v:.1f}%",
    "overdose_deaths":       lambda v: num(v),
    "real_wages":            lambda v: f"${v:.0f}",
    "medicaid_enrollment":   lambda v: f"{v/1e6:.1f}M" if v > 1000 else f"{v:.1f}M",
}
FOUR_BAR_TONE = [("trump2", "t25"), ("biden", "biden"), ("trump1", "t17"), ("obama", "obama")]

# card-design pass: which own-history cards also carry a "months in office" president-
# aligned view (levels for rates/counts/prices; % change for wages/workforce).
ALIGNED_LEVELS = {"unemployment", "gas_price", "crude_oil", "electricity_price",
                  "effective_tariff_rate", "overdose_deaths", "medicaid_enrollment",
                  "trade_deficit", "inflation", "grocery_prices", "va_claims_backlog"}
ALIGNED_PCT = {"real_wages", "federal_workforce"}
# fiscal-YTD cumulative cards: the "months in office" slot becomes an FY overlay
FY_OVERLAY = {"budget_deficit", "interest_on_debt", "defense_outlays"}


def fy_overlay(series, n_years=4):
    """Split a fiscal-YTD cumulative series (resets each Oct) into one line per fiscal
    year, x = fiscal-month index (Oct=0 … Sep=11). Current FY red, priors grey."""
    from collections import defaultdict
    by_fy = defaultdict(list)
    for p in series:
        d = _pdate(p["date"])
        fy = d.year + 1 if d.month >= 10 else d.year
        by_fy[fy].append([(d.month - 10) % 12, p["value"]])
    fys = sorted(by_fy)[-n_years:]
    greys = ["#8b9198", "#6c7280", "#4a4d53"]
    out = []
    for i, fy in enumerate(fys):
        back = len(fys) - 1 - i           # 0 = current
        color = "#e66767" if back == 0 else greys[min(back - 1, len(greys) - 1)]
        out.append({"label": f"FY{fy}", "color": color, "pts": sorted(by_fy[fy])})
    return out

def same_point_rows(m, fmt):
    series = m.get("series")
    if not series:
        return None
    try:
        N = _mon_idx(_pdate(str(m["as_of"])), PRES["trump2"]["inaug"])
    except Exception:
        return None
    rows = []
    for pid, tone in FOUR_BAR_TONE:
        pts = aligned_monthly(series, pid)          # [[months_in_office, value]]
        if not pts:
            continue
        d = {mi: v for mi, v in pts}
        if N in d:
            val = d[N]
        else:
            near = min(pts, key=lambda mv: abs(mv[0] - N))
            if abs(near[0] - N) > 2 and pid != "trump2":
                continue                            # too far from the same point → honest drop
            val = near[1]
        rows.append((PRES[pid]["label"], val, fmt(val), tone))
    # order the strip Obama → Trump'17 → Biden → Trump'25 (oldest → current)
    order = {"Obama": 0, "Trump ’17": 1, "Biden": 2, "Trump ’25": 3}
    rows.sort(key=lambda r: order.get(r[0], 9))
    return rows if len(rows) >= 2 else None


GAP_SHUTDOWN = "Oct ’25 not published (shutdown)"


REAL_PRICE = {"gas_price", "electricity_price"}


def real_series(S, cpi):
    """Deflate a nominal $ series to real (latest-year) dollars using the CPI-U index.
    real(t) = nominal(t) * CPI(latest) / CPI(t). Matches by month, falls back to the
    year's value (the committed deflator is annual; the connector supplies monthly)."""
    by_month, by_year = {}, {}
    for p in cpi.get("series", []):
        by_month[p["date"]] = p["value"]
        by_year[p["date"][:4]] = p["value"]
    if not cpi.get("series"):
        return None, None
    base = cpi["series"][-1]["value"]
    base_year = cpi["series"][-1]["date"][:4]
    out = []
    for p in S:
        c = by_month.get(p["date"]) or by_year.get(p["date"][:4])
        if not c and p["date"][:4] >= base_year:
            c = base   # months past the deflator's latest year: treat as base-year dollars (real ~ nominal)
        if c:
            out.append({"date": p["date"], "value": round(p["value"] * base / c, 4)})
    return (out, base_year) if out else (None, None)


def _pres_color(name):
    n = name.lower()
    if "obama" in n:
        return PRES["obama"]["color"]
    if "biden" in n:
        return PRES["biden"]["color"]
    if "trump" in n:
        return PRES["trump1"]["color"]   # the earlier Trump; current term appended separately
    return "#6c7280"


def alltime_bars(entries, name_field, span_field, current_total, take=8):
    # per-president lifetime totals as context bars: recent presidents, 4 palette
    # presidents coloured + earlier grey, current term appended in progress (red).
    def yr(e):
        mt = re.search(r'(19|20)\d\d', str(e.get(span_field, "")))
        return mt.group(0) if mt else ""
    rows = [e for e in entries if yr(e) and int(yr(e)) < 2025][-take:]
    bars = []
    for i, e in enumerate(rows):
        nm = e[name_field]
        sur = ("Trump ’17" if yr(e)[2:] == "17" else "Trump ’" + yr(e)[2:]) if "Trump" in nm else nm.split()[-1]
        bars.append([i, e["total"], sur, f"{nm} ({yr(e)})", _pres_color(nm)])
    bars.append([len(bars), current_total, "Trump ’25", "Trump ’25 (in progress)", PRES["trump2"]["color"]])
    return bars


def payload(m, loaded):
    """The chart payload for one metric, everything assets/chart.js needs.
    Falls back to an honest 'history accrues from here' state when the stored
    series is still too short to chart."""
    mid = m["id"]
    S = m.get("series") or []
    fx = {"id": mid, "asOf": pretty_date(m["as_of"]), "cadence": m["cadence"].lower(),
          "srcName": m["source"]["name"], "srcUrl": m["source"]["url"],
          "template": "line", "xType": "date", "series": []}

    def own(title, fmt, area=True, rng=None, gaps=None, unit=None, label=None):
        fx.update(chartTitle=title, fmt=fmt, zeroBase=True, area=area,
                  series=[{"label": label or m["name"], "color": ACCENT, "pts": date_points(S)}],
                  markers=[{"x": _ems(T2_START), "label": "Inauguration", "kind": "inaug"}])
        if unit:
            fx["unitLabel"] = unit
        if gaps:
            fx["gaps"] = gaps
        first = _pdate(S[0]["date"]) if S else T2_START
        if first < T2_START:            # spans prior presidents → colour the line by era (4 + grey)
            fx["presEras"] = True
        if rng is None:
            rng = (T2_START - first).days > 3 * 365
        if rng:
            fx.update(rangeToggle=True, termStart=_ems(T2_START))

    def aligned(title, fmt, sers, unit=None, markers=None, gaps=None, dots=None,
                zero=True, baseline=None, fmt_axis=None):
        fx.update(chartTitle=title, fmt=fmt, xType="months", xMax=TERM_MONTHS,
                  zeroBase=zero, direct=True, series=sers)
        if unit:
            fx["unitLabel"] = unit
        if markers:
            fx["markers"] = markers
        if gaps:
            fx["gaps"] = gaps
        if dots:
            fx["dots"] = dots
        if baseline is not None:
            fx["baseline"] = baseline
        if fmt_axis:
            fx["fmtAxis"] = fmt_axis

    def accrue(title, body):
        fx.update(chartTitle=title, series=[], accrueTitle="History accrues from here",
                  accrueBody=body)

    def snapshot(title, spec):
        # A point-in-time metric with too little history to plot a line yet: show an
        # honest current-snapshot visual (composition bar / value-vs-target) instead of
        # empty space. Auto-upgrades to the real line chart once enough points accrue.
        fx.update(chartTitle=title, series=[], snapshot=spec)

    def _own_hist():
        first = _pdate(S[0]["date"])
        own = {"series": [{"label": m["name"], "color": ACCENT, "pts": date_points(S)}],
               "xType": "date", "presEras": first < T2_START, "termStart": _ems(T2_START),
               "fmt": fx.get("fmt", "num"), "zeroBase": True,
               "chartTitle": m["name"] + ", full history",
               "markers": [{"x": _ems(T2_START), "label": "Inauguration", "kind": "inaug"}]}
        if fx.get("benchmark") is not None:
            own["benchmark"] = fx["benchmark"]; own["benchmarkLabel"] = fx.get("benchmarkLabel")
        if fx.get("gaps"):
            own["gaps"] = fx["gaps"]
        return own

    def attach_views(pct_moi=False, base_by=0):
        # Three-view kit: attach BOTH an own-history dataset (This term / Full history)
        # and a president-aligned dataset (Months in office), computed from this metric's
        # own series, sourced, never invented. Presidents without data simply drop out.
        if not S:
            return
        al_sers = _pseries(["trump2", "biden", "trump1", "obama"], S, pct=pct_moi, base_by=base_by)
        if len(al_sers) < 2:
            return
        fx["ownHist"] = _own_hist()
        fx["aligned"] = {"series": al_sers, "xType": "months", "xMax": TERM_MONTHS,
                         "fmt": "pct" if pct_moi else fx.get("fmt", "num"), "zeroBase": not pct_moi,
                         "chartTitle": m["name"] + ", months in office (aligned at inauguration)"}
        if not pct_moi and fx.get("benchmark") is not None:
            fx["aligned"]["benchmark"] = fx["benchmark"]
            fx["aligned"]["benchmarkLabel"] = fx.get("benchmarkLabel")

    def attach_fy():
        # Fiscal-year overlay: for fiscal-YTD cumulative series (reset each October),
        # the honest cross-term view is each FY as its own Oct→Sep line, not months-in-office.
        if not S:
            return
        sers = fy_overlay(S)
        if len(sers) < 2:
            return
        fx["ownHist"] = _own_hist()
        fx["aligned"] = {"series": sers, "xType": "months", "xMax": 11,
                         "fmt": fx.get("fmt", "num"), "zeroBase": True,
                         "xLabels": [{"x": 0, "lab": "Oct"}, {"x": 3, "lab": "Jan"},
                                     {"x": 6, "lab": "Apr"}, {"x": 9, "lab": "Jul"}, {"x": 11, "lab": "Sep"}],
                         "xCaption": "Fiscal year (Oct → Sep)",
                         "chartTitle": m["name"] + ", fiscal-year overlay (each FY, Oct → Sep)"}
        fx["moiLabel"] = "FY overlay"

    # ---------------- Cost of Living ----------------
    if mid == "inflation":
        own("CPI-U inflation, year over year, 2018 to now", "pct", unit="CPI-U YoY")
        fx.update(benchmark=(m.get("target") or {}).get("value", 2.0), benchmarkLabel="Fed target 2%",
                  gaps=[{"x": _ems(datetime.date(2025, 10, 15)), "label": GAP_SHUTDOWN}],
                  channels="tariffs feed into import prices; fiscal policy shapes demand; energy policy moves fuel costs.",
                  limits="the Federal Reserve independently sets interest-rate policy, and global supply and demand drive most short-run movement.",
                  caveats=["October 2025 CPI was never published (federal shutdown), the line breaks rather than estimating a value.",
                           "Bureau of Labor Statistics sample reductions in 2025 widen the error bars on recent readings."])

    elif mid == "grocery_prices":
        own("Grocery inflation (food at home), year over year, 1953 to now", "pct", unit="Food-at-home YoY")
        fx.update(gaps=[{"x": _ems(datetime.date(2025, 10, 15)), "label": GAP_SHUTDOWN}],
                  channels="tariffs on imported food, energy and transport costs, farm-labor supply via immigration policy.",
                  limits="weather, animal disease (e.g. avian flu in eggs) and global commodity markets set most short-run food prices.",
                  caveats=["October 2025 CPI was never published (federal shutdown), the gap is shown, not interpolated.",
                           "Year-over-year change in the Bureau of Labor Statistics food-at-home index, the grocery-store basket."])

    elif mid == "gas_price":
        own("US average pump price, regular, weekly since 1990", "usd2", unit="$/gal")
        fx.update(channels="drilling and permitting policy, strategic-reserve releases, sanctions on producer states.",
                  limits="global crude markets set most of the pump price; OPEC+ supply decisions and demand swings dominate.",
                  caveats=["Energy Information Administration weekly survey, national average for regular grade; state prices vary widely around it."])

    # ---------------- Economy & Jobs ----------------
    elif mid == "real_gdp":
        sers = _pseries(["trump2", "biden", "trump1", "obama"], S, fn=gdp_index)
        aligned("Real GDP growth", "idx",
                sers, unit="Index (=100 at inauguration)", zero=False, baseline=100)
        fx.update(channels="fiscal policy, tariffs, regulation, immigration (labor supply).",
                  limits="business cycles, Federal Reserve policy and global conditions dominate quarterly moves; tariff-driven import swings whipsawed 2025 readings in both directions.",
                  caveats=["Index compounds the official quarterly annualized rates: ×(1+r/100)^¼ per quarter, from 100 at the start of each president’s inauguration quarter.",
                           "GDP estimates are revised repeatedly (advance → second → third); recent quarters will move. Q4-2025 estimates were built on shutdown-impaired inputs."])

    elif mid == "unemployment":
        sers = _pseries(["trump2", "biden", "trump1"], S)
        aligned("Unemployment rate", "pct", sers, unit="U-3 rate",
                gaps=[{"x": _mon_idx(datetime.date(2025, 10, 1), T2_START), "label": GAP_SHUTDOWN}])
        fx.update(channels="fiscal policy, federal hiring and firing, trade policy, immigration enforcement (labor supply).",
                  limits="the business cycle and Fed policy drive most changes; presidents inherit trends.",
                  caveats=["Oct 2025’s household survey was lost to the shutdown, the line breaks, nothing is estimated. The Aug 2025 dismissal of the Bureau of Labor Statistics commissioner is a data-independence caveat, stated factually: methodology is unchanged and the series remains the official count.",
                           "Obama-era months predate the stored series (which starts 2017), a candidate one-time backfill."])

    elif mid == "real_wages":
        # quarterly series: quarter-END stamps mean month 0 never exists;
        # base_by=3 rebases on the inauguration QUARTER (stored at month 2)
        sers = _pseries(["trump2", "biden", "trump1", "obama"], S, pct=True, base_by=3)
        aligned("Real median weekly earnings, % change since inauguration quarter", "pctsign", sers,
                unit="% vs inauguration qtr",
                gaps=[{"x": _mon_idx(datetime.date(2025, 12, 1), T2_START), "label": "Q4 ’25 not collected (shutdown)"}])
        fx.update(channels="tax policy, labor regulation, tariffs (consumer prices), immigration policy (labor supply).",
                  limits="productivity and labor-market tightness set the trend; the series is quarterly and noisy.",
                  caveats=["Q4 2025 is a permanent hole, the shutdown killed that quarter’s survey collection; the break is shown, never filled.",
                           "Constant-dollar (inflation-adjusted) median usual weekly earnings, full-time workers; % of each president’s inauguration-quarter level."])

    elif mid == "federal_workforce":
        sers = _pseries(["trump2", "biden", "trump1", "obama"], S, pct=True)
        aligned("Federal civilian employment, % change since inauguration", "pctsign", sers,
                unit="% vs inauguration")
        fx.update(channels="direct, hiring freezes, reductions in force, deferred-resignation programs, reorganisations.",
                  limits="includes the self-funded ~600k Postal Service; courts have reversed some separations; deferred-resignation staff counted as employed while still paid, which delayed the visible drop until Oct 2025.",
                  caveats=["Percent of each president’s inauguration-month workforce (Bureau of Labor Statistics monthly count, incl. Postal Service).",
                           "Staff on paid 'deferred resignation' are counted as employed until they actually leave the payroll, visible as the Oct 2025 step-down.",
                           "Obama’s month-14 spike is the temporary 2010 Census hiring, a reminder that single months mislead."])

    # ---------------- Trade & Tariffs ----------------
    elif mid == "tariff_revenue":
        sers = [{"label": "Gross, fiscal-YTD", "color": ACCENT, "pts": date_points(S)}]
        net = m.get("series_net")
        if net:
            sers.append({"label": "Net of refunds", "color": SECOND, "pts": date_points(net)})
        fx.update(chartTitle="Customs duties, fiscal-YTD by month, resets each October", fmt="usdB",
                  zeroBase=True, series=sers, unitLabel="FYTD ($B)",
                  markers=[{"x": _ems(T2_START), "label": "Inauguration", "kind": "inaug"}],
                  channels="direct, the president sets tariff rates by proclamation under trade statutes and International Emergency Economic Powers Act.",
                  limits="duties are remitted by importers; revenue depends on import volumes, which tariffs suppress; courts can order refunds, visible in 2026 as negative net months.",
                  caveats=["Fiscal-year-to-date, so lines saw-tooth back toward zero every October.",
                           "Gross and net shown together (once the net line lands, from the same Treasury table): June 2026 alone saw $49B of court-ordered refunds, either figure without the other misleads."
                           if not net else
                           "Gross and net of refunds shown together: June 2026 alone saw $49B of court-ordered refunds, either figure without the other misleads."])

    elif mid == "effective_tariff_rate":
        own("Effective tariff rate: duties ÷ goods imports, monthly", "pct2", unit="Duties ÷ imports")
        fx.update(channels="as tariff revenue, rates are set by proclamation.",
                  limits="the measured rate reflects the import mix as well as policy: imports shifting toward exempt goods lowers it with no policy change; refund months distort it.",
                  caveats=["A transparent computed ratio of two official series (Treasury customs duties ÷ Census/BEA goods imports), not an academic ‘average tariff rate’.",
                           "Gross-duties numerator, labelled as such; heavy-refund months overstate or understate the true rate."])

    elif mid == "trade_deficit":
        own("Goods & services trade balance, monthly since 1992", "usdB", unit="Balance ($B)")
        fx.update(channels="tariffs, trade agreements, export controls.",
                  limits="the balance is driven by macro saving-investment flows, exchange rates and growth differentials; tariff front-running whipsawed 2025 monthly readings.",
                  caveats=["Negative = deficit. The 2025 spikes are importers front-running announced tariffs, then the snap-back, single months mislead here more than usual."])

    # ---------------- Public Finances ----------------
    elif mid == "national_debt":
        sers = _pseries(["trump2", "biden", "trump1"], S, fn=aligned_daily_pct)
        aligned("Total public debt", "pctsign", sers,
                unit="% growth", fmt_axis="pctsign")
        fx.update(channels="signed tax and spending legislation (incl. the 2025 reconciliation law), tariff receipts.",
                  limits="most spending is mandatory programs enacted decades ago; interest compounds automatically; Congress holds the purse.",
                  caveats=["Each line starts at 0% on that president’s inauguration day (Treasury daily series, weekly-sampled); Obama’s line needs a one-time backfill, the stored series begins 2017.",
                           "Growth is in percent so different starting debt levels compare honestly; dollar levels are on the collapsed card."])

    elif mid == "budget_deficit":
        own("Federal deficit, fiscal-YTD by month, resets each October", "usdB",
            area=False, unit="FYTD ($B)")
        fx.update(channels="proposed budgets, signed legislation, tariff receipts, workforce cuts.",
                  limits="mandatory spending and interest dominate outlays; fiscal years straddle administrations (FY2025 began under Biden).",
                  caveats=["Fiscal-year-to-date, so the line saw-tooths each October; compare same months across teeth, not adjacent points."])

    elif mid == "interest_on_debt":
        own("Interest on the public debt, fiscal-YTD by month", "usdB", area=False, unit="FYTD ($B)")
        fx.update(channels="deficits add to the stock of debt to be financed.",
                  limits="interest rates, set by markets and the Fed, drive the cost of rolling the existing $36T+; much of today’s bill was locked in by past borrowing.",
                  caveats=["Sums all ~38 Treasury expense categories, including negative amortization lines; single months are lumpy from premium timing, the FYTD line is the honest read."])

    # ---------------- Immigration ----------------
    elif mid == "border_encounters":
        # v3: the verified Office of Homeland Security Statistics backfill extends the series to Oct 2013, so the
        # months-in-office view gains Trump-'17's full term and Biden's first
        # 21 months; the pre-backfill gap chip renders only while it's needed.
        sers = _pseries(["trump2", "biden", "trump1"], S)
        has_backfill = S and S[0]["date"] < "2022-01"
        gaps = None if has_backfill else [{"x": 21, "label": "Biden data begins Oct ’22 (current Customs and Border Protection file)"}]
        aligned("Southwest border encounters per month", "count", sers,
                unit="Encounters / mo",
                markers=[{"x": _mon_idx(datetime.date(2023, 5, 1), PRES["biden"]["inaug"]),
                          "label": "Title 42 ends, definition change", "kind": "break"}],
                gaps=gaps)
        border_caveats = ["Counts encounters (events), not unique people: one person crossing more than once is counted each time.",
                          "The dashed marker is a definition break: pandemic-era Title 42 expulsions ended May 2023, counts either side aren’t directly comparable. Marked, never smoothed."]
        if has_backfill:
            border_caveats.append("Months before Oct 2022 come from DHS Office of Homeland Security Statistics’s official historical tables (discontinued Jan 2025), the same encounters definition, verified against Customs and Border Protection’s live series on their 24-month overlap; Office of Homeland Security Statistics publishes values rounded to the nearest 10. No official monthly encounters series exists before Oct 2013.")
        else:
            border_caveats.append("Line breaks are real holes (Customs and Border Protection’s current file omits Jul–Sep of closed fiscal years); the archive backfill fills them and Biden’s first 21 months.")
        fx.update(channels="direct, border policy, asylum rules, processing regimes, military deployment.",
                  limits="push factors abroad and smuggling economics also move flows; counts are events, not unique people; Title 42→Title 8 changes comparability across eras.",
                  caveats=border_caveats)

    elif mid == "ice_removals":
        annual = m.get("annual_history") or []
        if annual:
            bars, label_idx = [], []
            for i, p in enumerate(annual):
                bars.append([i, p["value"], "’" + str(p["fy"])[2:], "FY" + str(p["fy"])])
            last_fy = annual[-1]["fy"]
            for fy in range(last_fy + 1, 2026):   # unpublished closed years: labelled holes
                bars.append([len(bars), None, "’" + str(fy)[2:], f"FY{fy}, annual report pending"])
            bars.append([len(bars), m["value"], "’26*", f"FY2026 to date ({pretty_date(m['as_of'])})"])
            vals = [(b[1] or 0) for b in bars]
            label_idx = sorted(range(len(vals)), key=lambda i: vals[i], reverse=True)[:2] + [len(bars) - 1]
            fx.update(template="bars", xType="bars",
                      chartTitle="ICE removals by fiscal year, ’26 is year-to-date", fmt="count",
                      series=[{"label": "Removals", "color": ACCENT, "pts": bars}],
                      labelIdx=sorted(set(label_idx)), unitLabel="Removals")
        else:
            accrue("ICE removals, fiscal-YTD",
                   "The workbook series starts FY2025 and accrues with each ICE snapshot "
                   "(roughly biweekly). Annual history FY2012–FY2024 from ICE’s ERO annual "
                   "reports is a one-time static import that lands with the next data run.")
        fx.update(channels="direct, enforcement priorities, funding (the 2025 reconciliation law tripled ICE’s budget), agreements with receiving countries.",
                  limits="court injunctions, detention capacity and receiving-country cooperation constrain removals; official counts exclude some Border Patrol actions and lag events.",
                  caveats=["ICE’s published workbook figure, never reconciled to press-release ‘deportation’ totals, which mix in Customs and Border Protection actions counted differently.",
                           "Annual bars are ICE ERO annual-report totals (static, sourced); FY2025’s full-year total joins when ICE publishes its annual report. ICE paused publication for 56 days in early 2026, gaps show as gaps."])

    elif mid == "ice_detention":
        adp_hist = ((m.get("annual_adp") or {}).get("values") or {})
        if adp_hist:
            # v3: verified annual backfill (ICE's own reports; citations in
            # connectors/static/ice_adp_annual.json) + the accruing current FY
            bars = []
            for fy in sorted(int(k) for k in adp_hist):
                bars.append([len(bars), adp_hist[str(fy)], "’" + str(fy)[2:], f"FY{fy} average"])
            bars.append([len(bars), None, "’25", "FY2025, no comparable annual figure published"])
            bars.append([len(bars), m["value"], "’26*", f"FY2026 to date ({pretty_date(m['as_of'])})"])
            fx.update(template="bars", xType="bars", fmt="count",
                      chartTitle="ICE detention, average daily population by fiscal year, ’26 is to-date",
                      series=[{"label": "average daily population", "color": ACCENT, "pts": bars}],
                      labelIdx=list(range(len(bars))), unitLabel="average daily population")
        elif len(S) >= 4:
            own("Average daily population in ICE detention (FY-to-date)", "count",
                rng=False, unit="average daily population")
        else:
            accrue("Average daily population in ICE detention",
                   f"First dated snapshot: FY2026-to-date average of {m['value']:,.0f} "
                   f"(data through {pretty_date(m['as_of'])})"
                   + (f", with {m['currently_detained']:,.0f} currently detained as context. "
                      if m.get("currently_detained") else ". ")
                   + "ICE publishes dated workbook snapshots roughly every two weeks, each "
                     "release adds a point and this chart draws itself as the record builds.")
        fx.update(channels="direct, detention funding, facility contracts, arrest priorities.",
                  limits="capacity is set by congressional appropriations; average daily population is a FY-to-date average that smooths spikes (not a point-in-time headcount, labelled as such).",
                  caveats=["The workbook’s two independent average daily population splits are cross-checked every run and must agree within 1% before a value publishes."])

    # ---------------- Health & Safety Net ----------------
    elif mid == "overdose_deaths":
        own("Drug overdose deaths, trailing-12-month total, 2015 to now", "count",
            unit="Deaths (12-mo)")
        fx.update(channels="fentanyl interdiction at the border, precursor-focused trade pressure, treatment and naloxone funding.",
                  limits="the decline began mid-2023; street-supply changes, state programs and naloxone availability drive much of it; provisional data revises for months.",
                  caveats=["Centers for Disease Control and Prevention provisional estimates (predicted counts); the most recent ~6 months revise as reports complete."])

    elif mid == "measles_cases":
        bars = []
        for i, p in enumerate(S):
            y = p["date"][:4]
            last = i == len(S) - 1
            bars.append([i, p["value"], "’" + y[2:] + ("*" if last else ""),
                         y + (f" (to {pretty_date(m['as_of'])})" if last else "")])
        vals = [b[1] for b in bars]
        top = sorted(range(len(vals)), key=lambda i: vals[i], reverse=True)[:3]
        fx.update(template="bars", xType="bars", fmt="count",
                  chartTitle="Confirmed measles cases by year, the last bar is year-to-date",
                  series=[{"label": "Confirmed cases", "color": ACCENT, "pts": bars}],
                  labelIdx=sorted(set(top)), unitLabel="Cases",
                  channels="federal vaccine policy, Centers for Disease Control and Prevention/ACIP recommendations and messaging, outbreak-response funding.",
                  limits="outbreaks are local, driven by community vaccination rates and exposure events; counts are confirmed-only and revised retroactively.",
                  caveats=["The final bar is a partial year and already exceeds 2025, the worst full year since 1992. Measles was declared eliminated in the US in 2000.",
                           "Centers for Disease Control and Prevention merged its ‘unvaccinated’ and ‘unknown-status’ categories in 2025; history revises as cases are re-bucketed."])

    elif mid == "medicaid_enrollment":
        own("Medicaid & Children's Health Insurance Program enrollment, monthly, 2014 to now", "count", unit="Enrolled")
        fx.update(channels="eligibility and work-requirement rules (2025 reconciliation law), verification requirements, funding formulas.",
                  limits="the post-pandemic unwinding decline began in 2023 under Biden; most 2025-law provisions phase in through 2027–28; states administer enrollment.",
                  caveats=["~4-month reporting lag; states restate preliminary months, revisions are logged, not hidden.",
                           "The full arc matters: ACA expansion, pandemic continuous-enrollment surge, the 2023 unwinding, and the current decline are all policy eras."])

    elif mid == "va_claims_backlog":
        if len(S) >= 5:
            own("VA claims backlog, weekly, claims pending >125 days", "count",
                rng=None, unit="Claims >125 days")
        else:
            accrue("VA claims backlog, weekly",
                   f"Live tracking starts now: {m['value']:,.0f} claims pending >125 days "
                   f"(week ending {pretty_date(m['as_of'])}), vs ~{(m.get('baseline') or {}).get('value', 257253):,.0f} "
                   "at inauguration. The weekly archive back to 2018 is being backfilled a batch "
                   "per day from VA’s own report files, the full curve (including the 418k peak "
                   "of Jan 2024) draws itself in as it lands.")
        fx.update(channels="direct, VA staffing, overtime, claims automation.",
                  limits="the backlog also falls when intake slows; the official definition (rating claims >125 days) excludes other queues, total pending is shown for context.",
                  caveats=["VA’s own backlog definition (rating claims pending >125 days), from the Monday Morning Workload Report; total pending shown alongside as the definition-gaming guard.",
                           "Education-claims data was absent from the reports Oct 2025–Jul 2026 (annotated, not estimated)."])

    # ---------------- Executive Power & Governance ----------------
    elif mid == "executive_orders":
        t2 = carry_forward(aligned_monthly(S, "trump2") or [])
        sers = [{"label": PRES["trump2"]["label"], "color": PRES["trump2"]["color"], "pts": t2}] if t2 else []
        prev = m.get("prev_terms") or {}
        for pid in ("biden", "obama"):
            pts = prev.get(pid)
            if pts:
                mm = carry_forward([[p["month"], p["value"]] for p in pts])
                sers.append({"label": PRES[pid]["label"], "color": PRES[pid]["color"], "pts": mm})
        dots = []
        if "biden" not in prev and m.get("comparison"):
            months_in = round((datetime.date.today() - T2_START).days / 30.4375, 1)
            dots = [{"x": min(months_in, TERM_MONTHS), "y": m["comparison"]["value"],
                     "label": f"Biden, same point ({num(m['comparison']['value'])})",
                     "color": PRES["biden"]["color"]}]
        aligned("Cumulative executive orders signed", "count", sers,
                unit="Orders (cumulative)", dots=dots)
        fx.update(channels="entirely the president’s instrument.",
                  limits="orders direct the executive branch only; courts block or narrow many; a count measures activity, not effect.",
                  caveats=["Cumulative count of signed orders (Federal Register)."
                           + ("" if "biden" in prev else " Biden’s and Obama’s full monthly curves land with the next data run, until then the dot marks Biden’s total at the same point in term.")])

    elif mid == "judges_confirmed":
        al = m.get("aligned") or {}
        sers, dots = [], []
        for pid in ("trump2", "trump1", "biden"):
            pts = al.get(pid)
            if pts:
                sers.append({"label": PRES[pid]["label"], "color": PRES[pid]["color"],
                             "pts": carry_forward([[p["month"], p["value"]] for p in pts])})
        if not sers:
            t2 = carry_forward(aligned_monthly(S, "trump2") or [])
            if t2:
                sers = [{"label": PRES["trump2"]["label"], "color": PRES["trump2"]["color"], "pts": t2}]
            months_in = round((datetime.date.today() - T2_START).days / 30.4375, 1)
            if m.get("comparison"):
                dots.append({"x": min(months_in, TERM_MONTHS), "y": m["comparison"]["value"],
                             "label": f"Term 1 ({num(m['comparison']['value'])})",
                             "color": PRES["trump1"]["color"]})
            if m.get("biden_same_point") is not None:
                dots.append({"x": min(months_in, TERM_MONTHS), "y": m["biden_same_point"],
                             "label": f"Biden ({num(m['biden_same_point'])})",
                             "color": PRES["biden"]["color"]})
        aligned("Cumulative Article III judges confirmed", "count", sers,
                unit="Judges (cumulative)", dots=dots)
        fx.update(channels="direct, the president nominates.",
                  limits="the Senate confirms on its own calendar; available vacancies set the ceiling; the count records confirmations, which commissions trail by days.",
                  caveats=["Counted by Senate confirmation date from the Federal Judicial Center’s directory of every federal judge since 1789, the cleanest cross-president dataset on the board."])

    elif mid == "approval_rating":
        t2 = aligned_monthly([{"date": p["date"][:7], "value": p["value"]} for p in S], "trump2")
        # v3: the sourced Gallup import draws prior presidents as quarterly-
        # average lines (quarter N plotted at month 3N); the current term stays
        # the VoteHub aggregate. Mixed survey bases, labelled on every line and
        # in the caveats. Gallup's unpublished quarters stay gaps.
        gq = (m.get("gallup") or {}).get("quarterly") or {}
        sers = []
        if t2:
            sers.append({"label": PRES["trump2"]["label"],
                         "color": PRES["trump2"]["color"], "pts": t2})
        for pid in ("biden", "trump1", "obama"):
            qq = gq.get(pid)
            if qq:
                pts = [[int(k) * 3, v] for k, v in sorted(qq.items(), key=lambda kv: int(kv[0]))]
                sers.append({"label": PRES[pid]["label"],
                             "color": PRES[pid]["color"], "pts": pts})
        if len(sers) >= 2:
            aligned("Presidential approval",
                    "pct", sers, unit="% approve", zero=False)
        elif t2 and len(t2) >= 4:
            aligned("Presidential approval", "pct",
                    [{"label": PRES["trump2"]["label"], "color": PRES["trump2"]["color"], "pts": t2}],
                    unit="% approve")
        else:
            accrue("Presidential approval, weekly aggregate",
                   f"The weekly aggregate starts accruing now ({m['value']:.0f}% approve / "
                   f"{m.get('disapprove', 0):.0f}% disapprove as of {pretty_date(m['as_of'])}).")
        appr_caveats = ["Simple average of recent national polls, one per pollster (VoteHub, CC-BY); the poll list is linked from the source. Opinion data, not a government statistic.",
                        "Survey bases differ: the current term is the VoteHub poll aggregate; prior presidents are Gallup quarterly averages. Gallup never published a few late quarters (Biden Q15-16, Trump-’17 Q16), and those stay gaps."]
        if m.get("source_stalled_since"):
            stalled_pretty = pretty_date(m["source_stalled_since"])
            appr_caveats.insert(0, f"VoteHub’s public feed has carried no new national approval poll since {stalled_pretty}, the figure shown is the last aggregate. The pipeline checks daily; this card revives automatically when polls resume.")
        fx.update(channels="public opinion responds to everything on this board, it is the electorate’s own scoreboard, not a government statistic.",
                  limits="poll aggregates smooth single-poll noise but inherit house effects and modelling choices; this is the board’s one survey-derived metric, labelled as such.",
                  caveats=appr_caveats)

    # ---------------- v3 register cards (locked 12 Aug 2026) ----------------
    elif mid == "electricity_price":
        own("Residential electricity price, monthly since 1978", "usd2", unit="$/kWh")
        fx.update(channels="permitting for generation and transmission, tariffs on grid equipment (transformers, panels), federal power marketing.",
                  limits="rates are set by state regulators and utilities; fuel costs and grid-investment cycles dominate; data-center demand growth is a private-sector force.",
                  caveats=["Bureau of Labor Statistics average-price series, US city average, not seasonally adjusted, the price on a bill, not a policy index.",
                           "The nominal long view embeds general inflation; cross-president views use % change since inauguration."])

    elif mid == "crude_oil":
        own("US crude oil production, monthly since 1920", "idx", unit="Million barrels/day")
        fx.update(channels="leasing, permitting, regulatory posture.",
                  limits="production responds to global prices and shale economics with multi-year lags; records were also being set under the prior administration.",
                  caveats=["Energy Information Administration monthly field production, millions of barrels per day.",
                           "The shale era (2010→) dwarfs everything before it, the century of context is the point of this chart."])

    elif mid == "renewable_share":
        own("Renewable share of US electricity generation, monthly since 2001", "pct",
            unit="% of utility-scale generation")
        fx.update(channels="tax-credit changes (2025 law phase-outs), federal permitting and leasing (esp. offshore wind), tariffs on imported equipment.",
                  limits="the generation mix follows multi-year investment cycles and weather (hydro, wind); most 2025–26 capacity additions were contracted years earlier.",
                  caveats=["A computed ratio of Energy Information Administration's own generation-by-source figures: (conventional hydro + wind + solar + geothermal + biomass) ÷ total, utility-scale only; excludes rooftop solar and pumped storage.",
                           "The mix is strongly seasonal (hydro peaks in spring, solar in summer), compare same months, not adjacent ones."])

    elif mid == "ice_composition":
        d = m.get("detail") or {}
        if len(S) >= 4:
            own("Share of ICE detainees with no criminal conviction", "pct", rng=False,
                unit="% no conviction")
        elif d.get("total_detained"):
            tot = d["total_detained"]
            pend = d.get("pending_criminal_charges") or 0
            other = d.get("other_immigration_violators") or 0
            conv = d.get("convicted_criminal")
            if conv is None:
                conv = max(0, tot - pend - other)
            pc = lambda n: round(n / tot * 100, 1)
            snapshot("Detention composition, ICE's own categories", {
                "kind": "proportion",
                "highlight": f"{m['value']:.1f}% have no criminal conviction",
                "parts": [
                    {"label": "No criminal charges", "value": other, "pct": pc(other), "tone": "accent"},
                    {"label": "Charges pending, not convicted", "value": pend, "pct": pc(pend), "tone": "mid"},
                    {"label": "Convicted of a crime", "value": conv, "pct": pc(conv), "tone": "muted"},
                ],
                "caption": (f"Of {tot:,} people in ICE detention, as of {pretty_date(m['as_of'])}. "
                            "Captured biweekly; a trend line appears as more snapshots accrue."),
            })
        else:
            accrue("Detention composition, ICE's own categories",
                   "Composition accrues from here. Each biweekly ICE snapshot adds a point; "
                   "the share draws itself as the record builds.")
        fx.update(channels="direct, arrest priorities, detention decisions, quota pressure.",
                  limits="'no conviction' includes people with pending charges (broken out separately); composition shifts with the enforcement mix (interior arrests vs border book-ins).",
                  caveats=["ICE's own categories, 'Convicted Criminal', 'Pending Criminal Charges', 'Other Immigration Violators', reconciled against the workbook's Currently Detained total before publishing.",
                           "Detention composition only: ICE stopped publishing arrest-side criminality when its dashboard was frozen (Jan 2025)."])

    elif mid == "ice_custody_deaths":
        fc = {int(k): v for k, v in (m.get("fy_counts") or {}).items()}
        if fc:
            bars = []
            for fy in range(min(fc), max(fc) + 1):
                star = fy == max(fc)
                bars.append([len(bars), fc.get(fy), "’" + str(fy)[2:] + ("*" if star else ""),
                             f"FY{fy}" + (" to date" if star else "")])
            fx.update(template="bars", xType="bars", fmt="count",
                      chartTitle="Deaths in ICE custody by fiscal year, current year is to-date",
                      series=[{"label": "Deaths", "color": ACCENT, "pts": bars}],
                      labelIdx=list(range(len(bars))), unitLabel="Deaths")
        else:
            accrue("Deaths in ICE custody", "Counts accrue from ICE's death-reporting page.")
        fx.update(channels="direct, detention capacity and crowding, medical-care contracts, oversight intensity.",
                  limits="population size drives exposure (the detention card carries the average daily population context); ICE posts deaths with documented delays, so recent counts revise upward.",
                  caveats=["Counted from ICE's own per-death reporting page; names are never republished here.",
                           "Definition narrowed in June 2026: deaths within 30 days of release are no longer reported, later years undercount relative to earlier ones by that rule change."])

    elif mid == "refugee_admissions":
        if len(S) >= 4:
            own("Refugee arrivals, fiscal-YTD by month", "count", rng=False, unit="Arrivals FYTD")
            if m.get("ceiling"):
                fx.update(benchmark=m["ceiling"]["value"], benchmarkLabel=m["ceiling"]["label"])
        else:
            c = m.get("ceiling") or {}
            snapshot("Refugee admissions, fiscal year to date", {
                "kind": "vsTarget",
                "value": m["value"], "valueLabel": "Arrivals this fiscal year",
                "target": c.get("value"), "targetLabel": c.get("label", "Presidential ceiling"),
                "caption": (f"As of {pretty_date(m['as_of'])}. Court-ordered and follow-to-join cases "
                            "sit outside the cap; monthly history accrues from here."),
            })
        fx.update(channels="direct, the president sets the annual ceiling and program priorities; suspension and resumption by executive order.",
                  limits="courts have ordered admissions the program suspended; processing pipelines lag policy decisions by months.",
                  caveats=["Arrivals can exceed the ceiling: court-ordered and follow-to-join cases sit outside it.",
                           "The State Department skips some monthly reports (Nov 2025 was never posted), gaps show as gaps.",
                           "Composition is part of the record: current arrivals are dominated by the reprioritised program (see the card's context line)."])

    elif mid == "clemency":
        own("Named clemency grants this term, cumulative", "count", rng=False,
            unit="Named grants (cumulative)")
        fx.update(channels="entirely the president's, the pardon power is plenary.",
                  limits="counts measure use of the power, not merits; blanket proclamations cover unnamed individuals, counted separately from named grants.",
                  caveats=["Two numbers, defined on the card: named grants (counted row-by-row from Department of Justice's grants pages) and individuals covered (adds the ~1,500 Jan 6 defendants pardoned or commuted in one day-one proclamation, one action, many people; the proclamation text itself names no count).",
                           "Historical per-president totals are Department of Justice's own clemency statistics, frozen by Department of Justice in Jan 2025, individual acts, categorical proclamations excluded."])

    elif mid == "national_emergencies":
        own("New national emergencies declared this term, cumulative", "count", rng=False,
            unit="Declarations (cumulative)")
        fx.update(channels="entirely the president's instrument.",
                  limits="a count measures invocation, not scope; some declarations are routine (sanctions programs); continuations of pre-existing emergencies are excluded by rule.",
                  caveats=["A derived count, no official list exists. Rules: Federal Register presidential documents containing the declaring phrase; annual 'Continuation of…' notices and terminations excluded; reconciled against the Brennan Center's tracker (a labelled cross-check, never the source).",
                           "Each counted declaration's date and title is stored with the data, the receipts behind the number."])

    elif mid == "defense_outlays":
        own("Defense outlays, fiscal-YTD by month, resets each October", "usdB",
            area=False, unit="FYTD ($B)")
        fx.update(channels="budget requests, signed appropriations, supplementals.",
                  limits="Congress appropriates; outlays lag obligations; much spending is multi-year programs locked in earlier.",
                  caveats=["Department of Defense, Military Programs (military pay, operations, procurement, R&D; excludes VA and civil programs). Fiscal-year-to-date, so the line saw-tooths each October.",
                           "The department is being renamed (Defense → War); the connector matches both labels so the series survives the rebrand."])

    elif mid == "foreign_aid":
        own("International-affairs obligations by fiscal year", "usdB", rng=False,
            unit="Obligations ($B)")
        fx.update(channels="direct, program terminations, agency reorganisation, withheld funds (litigated).",
                  limits="obligations are commitments, not cash delivered; the USAID→State transition muddies 2025 reporting.",
                  caveats=["A constructed metric, definition printed: federal obligations under budget function 150 (International Affairs), development and humanitarian aid, security assistance, State operations, multilateral contributions, from USAspending.",
                           "Cross-checked against foreignassistance.gov, whose own FY2024–25 reporting is partial since the USAID merger."])

    elif mid == "war_powers":
        own("War-powers reports to Congress this term, cumulative", "count", rng=False,
            unit="Reports (cumulative)")
        fx.update(channels="direct, reports follow presidential military action.",
                  limits="classified annexes and disputed reporting obligations make counts a floor, not a ceiling; the 2026 dispute over the 60-day clock is itself part of the record.",
                  caveats=["The officially defined record of US military action abroad: 48-hour and periodic War Powers Resolution reports, each linking its underlying official document.",
                           "Compiled by NYU's War Powers Resolution Reporting project, named here because no official machine-readable list exists (the board's second non-government source; the other is the approval poll aggregate)."])

    elif mid == "military_deaths":
        own("US military deaths in current named operations, cumulative", "count",
            rng=False, unit="Deaths (cumulative)")
        fx.update(markers=[{"x": _ems(datetime.date(2026, 7, 15)),
                            "label": "Defense Casualty Analysis System splits Iran-war casualties, definition change"}],
                  channels="direct, decisions to initiate and continue operations.",
                  limits="covers service members, not civilians or contractors; Defense Casualty Analysis System recategorised Iran-war casualties mid-conflict (July 2026), so per-operation splits changed while totals carried over.",
                  caveats=["Hostile and non-hostile deaths across the current named operations (per-operation split on the card), as extracted by Defense Casualty Analysis System on its own stated date.",
                           "The Pentagon's legacy public casualty report froze on Jan 30, 2025, this database is the only current official channel."])

    else:
        accrue(m.get("name", mid), "History for this metric accrues with each data run.")

    if mid in ALIGNED_LEVELS:
        attach_views(pct_moi=False)
    elif mid == "real_wages":
        attach_views(pct_moi=True, base_by=3)
        # This-term / Full-history show the dollar level, not the %-change of the moi view.
        if fx.get("ownHist"):
            fx["ownHist"]["fmt"] = "usd"
    elif mid in ALIGNED_PCT:
        attach_views(pct_moi=True)
        # Months-in-office compares presidents as % change (correct). But This-term and
        # Full-history show the underlying LEVEL, so they must use the level's own unit —
        # not the %-change formatter the primary view carries. Workforce is stored in
        # thousands of employees; wages are constant dollars.
        if fx.get("ownHist"):
            fx["ownHist"]["fmt"] = "thou" if mid == "federal_workforce" else "usd"
    elif mid in FY_OVERLAY:
        attach_fy()
    elif mid == "real_gdp" and S and fx.get("series"):
        # GDP is aligned-primary (compounded index = Months in office); add an own-history
        # quarterly-rate view so it gets the full This term / Months in office / Full history kit.
        fx["aligned"] = {"series": fx["series"], "xType": "months", "xMax": TERM_MONTHS,
                         "fmt": fx.get("fmt", "idx"), "zeroBase": fx.get("zeroBase", False),
                         "baseline": fx.get("baseline"),
                         "chartTitle": m["name"] + ", months in office (compounded index, 100 at inauguration)"}
        fx["ownHist"] = {"series": [{"label": m["name"], "color": ACCENT, "pts": date_points(S)}],
                         "xType": "date", "presEras": _pdate(S[0]["date"]) < T2_START,
                         "termStart": _ems(T2_START), "fmt": "pct", "zeroBase": False,
                         "chartTitle": m["name"] + ", full history (quarterly growth rate)",
                         "markers": [{"x": _ems(T2_START), "label": "Inauguration", "kind": "inaug"}]}
    elif mid == "national_debt" and S and fx.get("series"):
        # aligned-primary (% growth since inauguration = Months in office); add own-history $ level
        fx["aligned"] = {"series": fx["series"], "xType": "months", "xMax": TERM_MONTHS,
                         "fmt": fx.get("fmt", "pctsign"), "zeroBase": fx.get("zeroBase", False),
                         "baseline": fx.get("baseline"),
                         "chartTitle": m["name"] + ", months in office (% growth since inauguration)"}
        if fx.get("fmtAxis"):
            fx["aligned"]["fmtAxis"] = fx["fmtAxis"]
        fx["ownHist"] = {"series": [{"label": m["name"], "color": ACCENT, "pts": date_points(S)}],
                         "xType": "date", "presEras": _pdate(S[0]["date"]) < T2_START,
                         "termStart": _ems(T2_START), "fmt": "usd", "zeroBase": True,
                         "chartTitle": m["name"] + ", full history (total public debt)",
                         "markers": [{"x": _ems(T2_START), "label": "Inauguration", "kind": "inaug"}]}
    elif mid in ("executive_orders", "judges_confirmed") and fx.get("series"):
        curves = fx["series"]
        t2 = [s for s in curves if s["label"] == PRES["trump2"]["label"]]
        entries = m.get("all_time")
        if mid == "executive_orders":
            entries = (entries or {}).get("nara_modern", [])
        bars = alltime_bars(entries, "president", "years" if mid == "executive_orders" else "from",
                            m["value"]) if entries else None
        if bars:
            title = "Executive orders signed" if mid == "executive_orders" else "Federal judges confirmed"
            fx["chartTitle"] = title
            fx["views"] = [
                {"key": "term", "label": "This term", "series": t2 or curves[:1],
                 "xType": "months", "xMax": TERM_MONTHS, "fmt": "count", "xCaption": "Months in office"},
                {"key": "moi", "label": "Months in office", "def": True, "series": curves,
                 "xType": "months", "xMax": TERM_MONTHS, "fmt": "count", "dots": fx.get("dots"),
                 "xCaption": "Months in office"},
                {"key": "all", "label": "All-time totals", "template": "bars", "xType": "bars",
                 "fmt": "count", "labelIdx": list(range(len(bars))),
                 "series": [{"label": title, "color": "#6c7280", "pts": bars}]},
            ]

    # Real-price toggle (gas, electricity): deflate the nominal history to today's dollars
    # so the full-history / this-term chart can switch Nominal <-> Real. Nominal stays default.
    if mid in REAL_PRICE and fx.get("ownHist") and loaded.get("cpi_index"):
        real, base_year = real_series(S, loaded["cpi_index"])
        if real:
            fx["ownHist"]["seriesReal"] = [{"label": m["name"], "color": ACCENT, "pts": date_points(real)}]
            fx["realToggle"] = True
            fx["realBase"] = base_year
    return fx


# ---- page -------------------------------------------------------------------
def _slug(cat):
    return cat.lower().replace(" & ", "-").replace(" ", "-")


def _frozen_rows(today=None):
    """Load the frozen-source list, compute days-silent, and drive the VoteHub
    (non-government) row live from the approval connector's stall state. Returns
    (rows, gov_count, verified_date) or ([], 0, None) if the file can't be read."""
    path = os.path.join(HERE, "connectors", "static", "frozen_sources.json")
    try:
        doc = json.load(open(path))
        entries = doc["sources"]
    except Exception as e:  # noqa: BLE001
        print(f"  ! frozen data skipped ({e})")
        return [], 0, None
    today = today or datetime.date.today()
    appr = {}
    try:
        appr = json.load(open(os.path.join(DATA, "approval_rating.json")))
    except Exception:
        pass
    rows, gov = [], 0
    for e in entries:
        is_gov = e.get("gov", True)
        last = e["last_update"]
        if not is_gov and "votehub" in e["url"]:
            stalled = appr.get("source_stalled_since")
            if not stalled:
                continue          # approval feed resumed → no longer a frozen source
            last = stalled
        rows.append({"name": e["name"], "last": last,
                     "days": (today - effective_date(last)).days,
                     "note": e["note"], "instead": e.get("instead", ""),
                     "url": e["url"], "gov": is_gov})
        if is_gov:
            gov += 1
    return rows, gov, doc.get("verified")


def frozen_callout(today=None):
    """Compact homepage callout: states the pattern factually and links to the full
    page. The table itself lives on /transparency, so the board isn't cluttered and
    readers don't mistake this for the board's own data being stale (it isn't —
    each source that went dark was replaced by a live one)."""
    _, gov, _ = _frozen_rows(today)
    if not gov:
        return ""
    return f"""
    <section class="callout" id="frozen">
      <h2>Government data that stopped updating</h2>
      <p>Since January 2025, <b>{gov} official data sources</b> this board draws on have been frozen, deleted, or narrowed. Where one went dark, the board switched to a still-current source, so the numbers here stay live.</p>
      <a class="callout-link" href="/transparency">See what went dark <span aria-hidden="true">&rarr;</span></a>
    </section>"""


def frozen_page_content(today=None):
    """Full detail for the dedicated /transparency page: the government table
    (source · last release · silent for · what happened · what the board uses
    instead), then any non-government source in a separate, labelled block."""
    rows, gov, verified = _frozen_rows(today)
    if not rows:
        return '<section class="block"><p>Every tracked source is currently publishing.</p></section>'
    gov_rows = [r for r in rows if r["gov"]]
    ng_rows = [r for r in rows if not r["gov"]]

    def table(rs):
        body = ""
        for r in rs:
            body += (f'<tr><td><a href="{r["url"]}" target="_blank" rel="noopener">{r["name"]}</a></td>'
                     f'<td class="fz-date">{pretty_date(r["last"])}</td>'
                     f'<td class="fz-days">{r["days"]:,} days</td>'
                     f'<td class="fz-note">{r["note"]}</td>'
                     f'<td class="fz-instead">{r["instead"]}</td></tr>')
        return ('<div class="fz-scroll"><table class="fz-table">'
                '<thead><tr><th>Source</th><th>Last&nbsp;release</th><th>Silent&nbsp;for</th>'
                '<th>What happened</th><th>What the board uses instead</th></tr></thead>'
                f'<tbody>{body}</tbody></table></div>')

    html = f'<section class="block">{table(gov_rows)}</section>'
    if ng_rows:
        html += (f'<section class="block"><p class="eyebrow">Non-government source</p>'
                 f'{table(ng_rows)}</section>')
    return html


# ---------------------------------------------------------------------------
# Phase 4: meta pages (About/methodology, Support, Contact), footer nav,
# security headers and the cookieless analytics beacon. These reuse the same
# theme tokens as the board so light/dark and the serif hero match exactly.
# ---------------------------------------------------------------------------
REPO_URL        = "https://github.com/neonatlas1/trump-by-numbers"
DISCUSSIONS_URL = "https://github.com/neonatlas1/trump-by-numbers/discussions"

# Canonical public address (Cloudflare Pages). Single source of truth for the
# absolute URLs that link previews (OpenGraph) and share links need. When a
# custom domain lands, change this one line.
SITE_URL = "https://trumpbynumbers.pages.dev"

# One link-preview card for the whole site (brief 09, MVP). The per-metric
# difference lives in the typed share text; this card is identical on every
# share. Image is a single file in site/ (swap assets/og.png to change it).
SOCIAL_TITLE = "Trump Administration, Tracked in Data"
SOCIAL_DESC  = "See what's actually happening under Trump, according to the numbers"
SOCIAL_IMAGE = SITE_URL + "/og.png"


def _social_meta(path="/"):
    """OpenGraph + Twitter tags so a pasted link shows the brand card (image +
    title + description) in WhatsApp, iMessage, X, etc. Same card site-wide;
    only og:url changes per page. Absolute URLs required for previews."""
    url = SITE_URL + path
    t = SOCIAL_TITLE
    d = SOCIAL_DESC
    return (
        f'<meta property="og:type" content="website">\n'
        f'<meta property="og:site_name" content="Trump by Numbers">\n'
        f'<meta property="og:title" content="{t}">\n'
        f'<meta property="og:description" content="{d}">\n'
        f'<meta property="og:image" content="{SOCIAL_IMAGE}">\n'
        f'<meta property="og:url" content="{url}">\n'
        f'<link rel="canonical" href="{url}">\n'
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{t}">\n'
        f'<meta name="twitter:description" content="{d}">\n'
        f'<meta name="twitter:image" content="{SOCIAL_IMAGE}">'
    )
KOFI_URL        = "https://ko-fi.com/trumpbynumbers"
SPONSORS_URL    = "https://github.com/sponsors/neonatlas1"
TALLY_EMBED     = "https://tally.so/embed/J9EW5Y?alignLeft=1&hideTitle=1"

# The site's single external script: cookieless Cloudflare Web Analytics. Baked
# before </body> on every page so each path (/, /methodology, /support, /contact)
# is counted. Snippet is exactly the one from brief 12.
BEACON = ("""<!-- Cloudflare Web Analytics --><script type="module" """
          """src="https://static.cloudflareinsights.com/beacon.min.js" """
          """data-cf-beacon='{"token": "d38cfd52e6ef4782a773d0e7b1f2e212"}'>"""
          """</script><!-- End Cloudflare Web Analytics -->""")

# Applies a saved theme in <head> before first paint, so a chosen theme carries
# across page navigation with no flash of the default. The ONLY thing the site
# stores: one "tbn-theme" value in localStorage — no cookie, never sent anywhere.
# Wrapped in try/catch (private mode can throw). System-follow still applies when
# nothing is saved.
_THEME_INIT = ("<script>try{var t=localStorage.getItem('tbn-theme');"
               "if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}"
               "catch(e){}</script>")

_ICON_SUN = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle>'
    '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path></svg>')
_ICON_MOON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"></path></svg>')
# Static "info" glyph for the button that jumps to the footer page-links.
_ICON_INFO = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9.5"></circle>'
    '<path d="M12 11v5"></path><path d="M12 7.6h.01"></path></svg>')
# Share glyph (connected nodes), used on the card icon, the drawer button, and
# the board-level control.
_ICON_SHARE = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"></circle>'
    '<circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle>'
    '<path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"></path></svg>')

# Standalone theme toggle for the meta pages (the board's copy lives inside
# chart.js, which these pages don't load). System-follow by default via CSS; the
# on-page toggle forces a theme and saves it to localStorage, so the choice carries
# across pages and visits (applied pre-paint by _THEME_INIT in the head).
_META_TOGGLE_JS = ("""<script>
(function () {
  var ROOT = document.documentElement;
  ROOT.classList.remove('no-js');
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;
  function eff() {
    var t = ROOT.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return (mq && mq.matches) ? 'light' : 'dark';
  }
  var SUN = '""" + _ICON_SUN + """';
  var MOON = '""" + _ICON_MOON + """';
  var btn = document.getElementById('themeToggle');
  function upd() {
    if (!btn) return;
    var light = eff() === 'light';
    btn.innerHTML = light ? MOON : SUN;
    btn.setAttribute('aria-label', light ? 'Switch to dark theme' : 'Switch to light theme');
    btn.setAttribute('aria-pressed', light ? 'true' : 'false');
  }
  if (btn) btn.addEventListener('click', function () {
    var next = eff() === 'dark' ? 'light' : 'dark';
    ROOT.setAttribute('data-theme', next);
    try { localStorage.setItem('tbn-theme', next); } catch (e) {}
    upd();
  });
  if (mq) {
    var onSys = function () { if (!ROOT.getAttribute('data-theme')) upd(); };
    if (mq.addEventListener) mq.addEventListener('change', onSys);
    else if (mq.addListener) mq.addListener(onSys);
  }
  var info = document.getElementById('infoScroll');
  if (info) info.addEventListener('click', function () {
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  });
  upd();
})();
</script>""")

_META_CSS = """
  :root { %%DARK%% }
  @media (prefers-color-scheme: light) { :root:not([data-theme]) { %%LIGHT%% } }
  :root[data-theme="light"] { %%LIGHT%% }
  :root[data-theme="dark"] { %%DARK%% }
  html { background:var(--plane); }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--plane); color:var(--primary);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.5;
    -webkit-font-smoothing:antialiased; }
  .wrap { max-width:720px; margin:0 auto; padding:56px 24px 80px; }
  header { margin-bottom:28px; }
  .theme-toggle { float:right; margin:2px 0 8px 18px; width:38px; height:38px; padding:0;
                  display:inline-flex; align-items:center; justify-content:center;
                  background:var(--panel); border:1px solid var(--hair); border-radius:10px;
                  color:var(--secondary); cursor:pointer; transition:color .15s ease, border-color .15s ease; }
  .theme-toggle:hover { color:var(--primary); border-color:var(--hair-strong); }
  .theme-toggle:focus-visible { outline:none; box-shadow:0 0 0 2px var(--focus); }
  .theme-toggle svg { width:18px; height:18px; display:block; }
  .no-js .theme-toggle { display:none; }
  .head-ctrls { float:right; display:flex; gap:8px; margin:2px 0 8px 18px; }
  .head-ctrls .theme-toggle { float:none; margin:0; }
  .brand { display:inline-block; font-size:13px; font-weight:600; letter-spacing:.01em;
           color:var(--muted); text-decoration:none; margin-bottom:14px; }
  .brand:hover { color:var(--series-1); }
  h1 { font-family:Georgia,"Iowan Old Style","Palatino Linotype","Book Antiqua",serif;
       font-size:clamp(38px,6vw,58px); font-weight:700; margin:0 0 12px;
       letter-spacing:-0.015em; line-height:1.04; }
  .lede { color:var(--secondary); margin:0; font-size:15.5px; max-width:56ch; }
  .page { margin-top:6px; }
  .block { padding:22px 0; border-top:1px solid var(--hair); }
  .block:first-child { border-top:0; padding-top:12px; }
  .eyebrow { font-size:12px; letter-spacing:.12em; text-transform:uppercase; font-weight:600;
             color:var(--muted); margin:0 0 9px; }
  .block p { margin:0 0 11px; color:var(--secondary); font-size:15.5px; line-height:1.62; }
  .block p:last-child { margin-bottom:0; }
  .block a { color:var(--series-1); text-decoration:none; }
  .block a:hover { text-decoration:underline; }
  .btn-row { display:flex; gap:12px; flex-wrap:wrap; margin:4px 0 2px; }
  .btn { display:inline-flex; align-items:center; gap:8px; padding:11px 18px; border-radius:12px;
         font-size:14px; font-weight:600; text-decoration:none; border:1px solid var(--hair-strong);
         color:var(--primary); background:var(--panel); transition:border-color .15s ease, color .15s ease; }
  .btn:hover { border-color:var(--series-1); color:var(--series-1); text-decoration:none; }
  .btn.primary { background:var(--series-1); border-color:var(--series-1); color:#fff; }
  .btn.primary:hover { color:#fff; opacity:.92; }
  ul.help { list-style:none; padding:0; margin:4px 0 0; }
  ul.help li { padding:10px 0; border-top:1px solid var(--hair-faint); color:var(--secondary);
               font-size:15.5px; line-height:1.55; }
  ul.help li:first-child { border-top:0; }
  ul.help b { color:var(--primary); font-weight:600; }
  ul.help a { color:var(--series-1); text-decoration:none; }
  ul.help a:hover { text-decoration:underline; }
  .form-embed { margin-top:2px; border:1px solid var(--hair); border-radius:14px; overflow:hidden;
                background:#fff; padding:0 22px; }
  .form-embed iframe { display:block; width:100%; border:0; }
  footer { margin-top:52px; border-top:1px solid var(--hair); padding-top:24px;
           color:var(--muted); font-size:12px; text-align:center; line-height:1.7; }
  footer a { color:var(--secondary); text-decoration:none; }
  footer a:hover { color:var(--series-1); }
  .footer-nav { margin-bottom:8px; }
  .footer-nav a, .footer-nav span { margin:0 5px; }
  .footer-nav [aria-current] { color:var(--muted); }
  .built { opacity:.6; font-size:11px; }
  .fz-meta { font-size:13px !important; color:var(--muted) !important; }
  .fz-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; margin:0 -4px; }
  .fz-table { border-collapse:collapse; font-size:13.5px; min-width:640px; width:100%; }
  .fz-table th { text-align:left; color:var(--muted); font-weight:600; padding:0 16px 10px 0;
                 border-bottom:1px solid var(--hair); vertical-align:bottom; }
  .fz-table td { padding:13px 16px 13px 0; border-bottom:1px solid var(--hair-faint);
                 vertical-align:top; color:var(--secondary); line-height:1.5; }
  .fz-table tbody tr:last-child td { border-bottom:0; }
  .fz-table a { color:var(--primary); font-weight:600; text-decoration:none; }
  .fz-table a:hover { color:var(--series-1); }
  .fz-date, .fz-days { white-space:nowrap; }
  .fz-days { font-variant-numeric:tabular-nums; }
  .fz-note { color:var(--muted); min-width:22ch; }
  .fz-instead { min-width:22ch; }
"""


def _footer_nav(current):
    """Footer meta-nav for the sub-pages: Home + the three pages, current one flat."""
    items = [("/", "Home"), ("/methodology", "About"), ("/transparency", "Transparency"),
             ("/support", "Support"), ("/contact", "Contact")]
    parts = []
    for href, label in items:
        if href == current:
            parts.append(f'<span aria-current="page">{label}</span>')
        else:
            parts.append(f'<a href="{href}">{label}</a>')
    return '<div class="footer-nav">' + ' · '.join(parts) + '</div>'


def render_meta_page(current, title, hero, lede, desc, content, dark_tokens, light_tokens):
    """A standalone page that matches the board's visual system (serif hero,
    light/dark tokens, theme toggle) but carries no charts/tabs/drawers."""
    css = _META_CSS.replace("%%DARK%%", dark_tokens).replace("%%LIGHT%%", light_tokens)
    return f"""<!doctype html>
<html lang="en" class="no-js">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Trump by Numbers</title>
<meta name="description" content="{desc}">
{_social_meta(current)}
{_THEME_INIT}
<style>{css}</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="head-ctrls">
        <button class="theme-toggle" id="infoScroll" type="button" aria-label="Jump to page links">{_ICON_INFO}</button>
        <button class="theme-toggle" id="themeToggle" type="button" aria-label="Switch to light theme" aria-pressed="false"></button>
      </div>
      <a class="brand" href="/"><span aria-hidden="true">&larr;</span> Trump by Numbers</a>
      <h1>{hero}</h1>
      <p class="lede">{lede}</p>
    </header>
    <main class="page">
      {content}
    </main>
    <footer>
      {_footer_nav(current)}
    </footer>
  </div>
  {_META_TOGGLE_JS}
  {BEACON}
</body>
</html>"""


def _about_content():
    return f"""
      <section class="block">
        <p class="eyebrow">What this is</p>
        <p>Trump by Numbers tracks the record of the Trump administration using official statistics. Every number comes from a primary government source, it's dated, and it's shown with its history, so you can see how it's changed over time and not just where it stands today.</p>
      </section>
      <section class="block">
        <p class="eyebrow">How we pick metrics</p>
        <p>We decide which metrics to show based on what we think matters, not on the direction they happen to point in. If there isn't a reliable official source for a number, we don't include it.</p>
      </section>
      <section class="block">
        <p class="eyebrow">How we handle the numbers</p>
        <p>The numbers themselves are shown as they are. Each one is sourced, dated, and plotted over time, usually next to previous administrations at the same point. Figures that look good and figures that look bad are both there. We don't take a metric down because it's started to look better, and when the official data has gaps, we leave them visible rather than fill them in with estimates.</p>
      </section>
      <section class="block">
        <p class="eyebrow">What this isn't</p>
        <p>This isn't a neutral utility, and it isn't an attack site. We have a clear view on which measures of a presidency are worth paying attention to, but not on the numbers themselves, and we don't add any commentary or narrative on top of them.</p>
      </section>
      <section class="block">
        <p class="eyebrow">How it runs</p>
        <p>The board updates itself from official sources every day, and it's <a href="{REPO_URL}" target="_blank" rel="noopener">open source</a>, so you can look at the code and the data behind any number yourself. If you notice a mistake or something that looks wrong, <a href="/contact">let us know</a>.</p>
      </section>"""


def _support_content():
    return f"""
      <section class="block">
        <p>If you find the site useful and want to support it, you can leave a one-off tip. Thanks for considering it.</p>
        <div class="btn-row">
          <a class="btn primary" href="{KOFI_URL}" target="_blank" rel="noopener"><svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>Tip on Ko-fi</a>
          <a class="btn" href="{SPONSORS_URL}" target="_blank" rel="noopener">Sponsor on GitHub</a>
        </div>
      </section>
      <section class="block">
        <p class="eyebrow">Free ways to help</p>
        <ul class="help">
          <li><b>Share a card.</b> It's mostly word of mouth that brings people here.</li>
          <li><b>Star the <a href="{REPO_URL}" target="_blank" rel="noopener">repo on GitHub</a>.</b> It helps more people find it.</li>
          <li><b>Suggest a metric.</b> If there's something official and important we're missing, <a href="/contact">let us know</a>.</li>
          <li><b>Check the numbers.</b> If a source looks wrong or out of date, <a href="/contact">tell us</a>.</li>
        </ul>
      </section>"""


def _contact_content():
    return f"""
      <section class="block">
        <div class="form-embed">
          <iframe src="{TALLY_EMBED}" title="Contact form" height="640" loading="lazy"></iframe>
        </div>
        <p style="margin-top:18px;">You can also post publicly or start a discussion on <a href="{DISCUSSIONS_URL}" target="_blank" rel="noopener">GitHub Discussions</a>.</p>
      </section>"""


def _headers_text():
    """Cloudflare Pages security headers. One CSP for all paths; it permits the
    analytics beacon (script + connect) and the Tally form frame on /contact,
    and otherwise keeps the site locked to itself. chart.js is inlined into the
    page, so script-src carries 'unsafe-inline'."""
    csp = ("default-src 'self'; "
           "script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com; "
           "style-src 'self' 'unsafe-inline'; "
           "img-src 'self' data:; "
           "font-src 'self'; "
           "connect-src 'self' https://cloudflareinsights.com; "
           "frame-src https://tally.so; "
           "frame-ancestors 'none'; "
           "base-uri 'self'; "
           "form-action 'self'; "
           "object-src 'none'")
    return (
        "/*\n"
        "  X-Frame-Options: DENY\n"
        "  X-Content-Type-Options: nosniff\n"
        "  Referrer-Policy: strict-origin-when-cross-origin\n"
        "  Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=(), usb=()\n"
        f"  Content-Security-Policy: {csp}\n"
    )


def build():
    loaded = {}
    for f in glob.glob(os.path.join(DATA, "*.json")):
        try:
            d = json.load(open(f))
            # canonical v2 category (deterministic grouping even from data
            # files written before the Jul-2026 category migration)
            d["category"] = CATEGORIES.get(d["id"], d.get("category", ""))
            loaded[d["id"]] = d
        except Exception as e:
            print(f"  ! skipping {f}: {e}")

    metrics = [loaded[k] for k in ORDER if k in loaded]
    # ---- per-metric chart payloads -> site/d/<id>.json (fetched on expand) ----
    os.makedirs(SITE_D, exist_ok=True)
    payload_fail = []
    for m in metrics:
        try:
            fx = payload(m, loaded)
            # chart title mirrors the card exactly: "<name> · <qualifier>" (no date-range clutter,
            # the x-axis already shows the range). Same split as the tile so they never drift.
            _tm = re.match(r'^(.*?)\s*\(([^)]*)\)\s*$', m["name"])
            _tmain, _tqual = (_tm.group(1), _tm.group(2)) if _tm else (m["name"], "")
            fx["chartTitle"] = _tmain + (" · " + _tqual if _tqual else "")
            with open(os.path.join(SITE_D, f"{m['id']}.json"), "w") as f:
                json.dump(fx, f, separators=(",", ":"))
        except Exception as e:
            payload_fail.append((m["id"], e))
            print(f"  ! payload failed for {m['id']}: {e} (card ships collapsed-only)")

    expandable = {m["id"] for m in metrics} - {mid for mid, _ in payload_fail}
    expand_btn = (
        '<button class="expand-btn" type="button" aria-expanded="false">'
        '<span>See more</span>'
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<polyline points="6 9 12 15 18 9"></polyline></svg></button>'
        '<div class="detail" hidden></div>')

    # Group by category, preserving ORDER within each. The tab bar is a SECTION NAV,
    # not a filter: every category is always rendered, a tab click scrolls to it, and
    # its heading is the scroll anchor (same display name as the tab). No "All" tab.
    sections, tab_btns = [], []
    for cat in CATEGORY_ORDER:
        cat_metrics = [m for m in metrics if m["category"] == cat]
        if not cat_metrics:
            continue
        slug = _slug(cat)
        name = TAB_LABEL.get(cat, cat)
        tiles = []
        for m in cat_metrics:
            h = tile(m)
            h = h.replace('<article class="tile" ',
                          f'<article class="tile" id="card-{m["id"]}" data-id="{m["id"]}" ', 1)
            if m["id"] in expandable:
                h = h.replace('<div class="tile-foot">', expand_btn + '\n      <div class="tile-foot">', 1)
            tiles.append(h)
        tab_btns.append(f'<button class="tab" type="button" data-tab="{slug}">{name}</button>')
        sections.append(f"""
      <section class="category" data-tab="{slug}" id="{slug}">
        <h2 class="cat-head">{name}</h2>
        <div class="grid">{"".join(tiles)}</div>
      </section>""")
    body = "".join(sections)
    tabs_html = "".join(tab_btns)

    # Board-level share (brief 09): whole-board hook, side-neutral wit.
    _board_share_text = _htmllib.escape(
        "For your next dinner-table argument about Trump\nSettle it with numbers",
        quote=True).replace("\n", "&#10;")
    board_share_btn = (
        f'<button class="theme-toggle" id="boardShare" type="button" '
        f'aria-label="Share the board" '
        f'data-share-text="{_board_share_text}" data-share-url="{SITE_URL}/">'
        f'{_ICON_SHARE}</button>'
    )

    chart_js = ""
    js_path = os.path.join(ASSETS, "chart.js")
    if os.path.exists(js_path):
        chart_js = open(js_path).read()
    else:
        print("  ! assets/chart.js missing, shipping collapsed-only board")

    live = len(metrics)
    built = datetime.datetime.utcnow().strftime("%b %-d, %Y %H:%M UTC")

    # ---- theme tokens ----------------------------------------------------------
    # Every colour on the page resolves from one of these variables, so a full
    # light palette is a straight swap. Dark is the default (and the no-preference
    # fallback); light auto-applies for visitors whose system is light and can be
    # forced either way by the on-page toggle. No storage: the toggle resets on reload.
    # The four president colours and the chart chrome are re-tuned for legibility on
    # a light background (each cleared its WCAG contrast target before shipping).
    dark_tokens = (
        "color-scheme:dark;"
        "--plane:#0d0d0d;--surface:#1a1a19;--drawer:#242422;--tile-hover:#1f1f1e;"
        "--tile-hover-border:rgba(255,255,255,0.20);--tile-hover-shadow:none;"
        "--primary:#ffffff;--secondary:#c3c2b7;--muted:#898781;"
        "--hair:rgba(255,255,255,0.10);--hair-strong:rgba(255,255,255,0.28);"
        "--hair-faint:rgba(255,255,255,0.05);--tile-open:rgba(255,255,255,0.32);--grid:#2c2c2a;"
        "--panel:rgba(255,255,255,0.03);--tab-track:rgba(255,255,255,0.045);"
        "--tab-active:rgba(255,255,255,0.10);--seg-shadow:none;"
        "--rswitch:#141414;--rknob:#2a2c31;--tooltip:#232322;--shadow:rgba(0,0,0,0.5);"
        "--drawer-shadow:none;--focus:rgba(57,135,229,0.5);"
        "--series-1:#3987e5;--series-2:#d95926;--critical:#d03b3b;--good:#2bb35c;--warn:#e0a83b;"
        "--accent-tint:rgba(57,135,229,0.12);--warn-line:rgba(224,168,59,0.4);--warn-tile:rgba(224,168,59,0.45);"
        "--pres-t25:#e66767;--pres-biden:#3987e5;--pres-t17:#199e70;--pres-obama:#c98500;"
        "--era-grey:#6c7280;--bar-g1:#8b9198;--bar-g3:#4a4d53;"
        "--chart-ink:#ffffff;--chart-sec:#c3c2b7;--chart-mut:#898781;--chart-grid:#2c2c2a;"
        "--chart-axis:#4a4a47;--chart-surface:#1a1a19;--chart-dash:#6b6965;"
    )
    light_tokens = (
        "color-scheme:light;"
        "--plane:#f7f6f2;--surface:#ffffff;--drawer:#fdfcfb;--tile-hover:#fdfdfc;"
        "--tile-hover-border:rgba(0,0,0,0.14);--tile-hover-shadow:0 2px 10px rgba(0,0,0,0.06);"
        "--primary:#2a2723;--secondary:#55534b;--muted:#73716a;"
        "--hair:rgba(0,0,0,0.12);--hair-strong:rgba(0,0,0,0.28);"
        "--hair-faint:rgba(0,0,0,0.06);--tile-open:rgba(0,0,0,0.32);--grid:#e6e4dd;"
        "--panel:rgba(0,0,0,0.028);--tab-track:rgba(0,0,0,0.06);"
        "--tab-active:#ffffff;--seg-shadow:0 1px 2px rgba(0,0,0,0.12);"
        "--rswitch:#eceae4;--rknob:#ffffff;--tooltip:#ffffff;--shadow:rgba(0,0,0,0.16);"
        "--drawer-shadow:0 1px 2px rgba(0,0,0,0.05),0 10px 28px rgba(0,0,0,0.06);--focus:rgba(31,111,208,0.55);"
        "--series-1:#1f6fd0;--series-2:#d35a24;--critical:#d83a34;--good:#1a9a44;--warn:#b3830c;"
        "--accent-tint:rgba(31,111,208,0.12);--warn-line:rgba(179,131,12,0.4);--warn-tile:rgba(179,131,12,0.5);"
        "--pres-t25:#db4444;--pres-biden:#2f7fe0;--pres-t17:#14a06e;--pres-obama:#e3a11d;"
        "--era-grey:#6b7078;--bar-g1:#7c828c;--bar-g3:#3f444c;"
        "--chart-ink:#2a2723;--chart-sec:#55534b;--chart-mut:#73716a;--chart-grid:#e6e4dd;"
        "--chart-axis:#b7b4ab;--chart-surface:#fdfcfb;--chart-dash:#a9a69d;"
    )

    html = f"""<!doctype html>
<html lang="en" class="no-js">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trump Administration, Tracked in Data</title>
<meta name="description" content="{SOCIAL_DESC}">
{_social_meta("/")}
{_THEME_INIT}
<style>
  /* Dark is the default and the no-preference fallback. Light auto-applies via the
     media query for system-light visitors (works even with JS off); the on-page
     toggle sets data-theme to force either way and resets on reload (no storage). */
  :root {{ {dark_tokens} }}
  @media (prefers-color-scheme: light) {{ :root:not([data-theme]) {{ {light_tokens} }} }}
  :root[data-theme="light"] {{ {light_tokens} }}
  :root[data-theme="dark"] {{ {dark_tokens} }}
  html {{ background:var(--plane); -webkit-tap-highlight-color:transparent; }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--plane); color:var(--primary);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.5;
    -webkit-font-smoothing:antialiased;
  }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:0 24px; }}
  .wrap-hero {{ padding-top:56px; padding-bottom:10px; }}
  .sb-inner {{ padding-top:0; padding-bottom:0; }}
  .wrap-main {{ padding-bottom:80px; }}
  #sbSentinel {{ height:0; }}
  header {{ margin-bottom:36px; }}
  .theme-toggle {{ float:right; margin:2px 0 8px 18px; width:38px; height:38px; padding:0;
                  display:inline-flex; align-items:center; justify-content:center;
                  background:var(--panel); border:1px solid var(--hair); border-radius:10px;
                  color:var(--secondary); cursor:pointer; transition:color .15s ease, border-color .15s ease; }}
  .theme-toggle:hover {{ color:var(--primary); border-color:var(--hair-strong); }}
  .theme-toggle:focus-visible {{ outline:none; box-shadow:0 0 0 2px var(--focus); }}
  .theme-toggle svg {{ width:18px; height:18px; display:block; }}
  .no-js .theme-toggle {{ display:none; }}
  .head-ctrls {{ display:flex; gap:8px; flex:0 0 auto; }}
  .head-ctrls .theme-toggle {{ float:none; margin:0; }}
  /* ---- sticky condensing header: hero scrolls away, this bar pins ---- */
  #hero {{ position:relative; margin-bottom:0; }}
  #hero .head-ctrls {{ float:right; margin-left:18px; }}
  .stickybar {{ position:sticky; top:0; z-index:30; background:transparent; padding:8px 0;
    transition:background .2s ease, box-shadow .2s ease; }}
  .stickybar.stuck {{ background:var(--surface); border-bottom:1px solid var(--hair); box-shadow:0 4px 14px var(--shadow); }}
  .sb-top {{ display:flex; align-items:center; justify-content:space-between; gap:12px; min-height:38px; }}
  .stickybar:not(.stuck) .sb-top {{ display:none; }}   /* nothing to show here until pinned */
  .stickybar .tabs-wrap {{ margin:9px 0 0; }}
  .mini-title {{ font-family:Georgia,"Iowan Old Style","Palatino Linotype","Book Antiqua",serif;
    font-weight:700; font-size:20px; letter-spacing:-0.01em; line-height:1; color:var(--primary);
    background:none; border:0; padding:0; cursor:pointer; white-space:nowrap; max-width:0; overflow:hidden;
    opacity:0; transition:max-width .28s ease, opacity .2s ease; }}
  .stickybar.stuck .mini-title {{ max-width:320px; opacity:1; }}
  .no-js .stickybar {{ display:none; }}
  .kicker {{ color:var(--series-1); font-size:12px; letter-spacing:.14em; text-transform:uppercase; font-weight:600; }}
  h1 {{ font-family:Georgia,"Iowan Old Style","Palatino Linotype","Book Antiqua",serif;
       font-size:clamp(42px,7.5vw,68px); font-weight:700; margin:0 0 14px;
       letter-spacing:-0.015em; line-height:1.03; }}
  .h1-accent {{ color:var(--pres-t25); }}
  .lede {{ color:var(--secondary); max-width:none; margin:0; font-size:15px; }}
  .pilot {{ display:inline-block; margin-top:16px; font-size:12px; color:var(--muted);
           border:1px solid var(--hair); border-radius:100px; padding:5px 12px; }}
  .category {{ margin-top:40px; scroll-margin-top:118px; }}
  .cat-head {{ font-size:13px; font-weight:600; letter-spacing:.12em; text-transform:uppercase;
              color:var(--secondary); margin:0 0 16px; padding-bottom:10px;
              border-bottom:1px solid var(--hair); display:flex; align-items:center; gap:10px; }}
  .cat-count {{ color:var(--muted); font-weight:500; font-size:12px;
               border:1px solid var(--hair); border-radius:100px; padding:1px 8px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:18px; }}
  .tile {{ position:relative; background:var(--surface); border:1px solid var(--hair); border-radius:16px; padding:24px 24px 18px; }}
  /* share icon, top-right of the collapsed card (brief 09) */
  .tile-share {{ position:absolute; top:15px; right:15px; width:30px; height:30px; padding:0;
    display:inline-flex; align-items:center; justify-content:center; background:none;
    border:1px solid transparent; border-radius:8px; color:var(--muted); cursor:pointer;
    transition:color .15s ease, border-color .15s ease, background .15s ease; }}
  .tile-share:hover {{ color:var(--primary); border-color:var(--hair); background:var(--panel); }}
  .tile-share:focus-visible {{ outline:none; box-shadow:0 0 0 2px var(--focus); }}
  .tile-share svg {{ width:16px; height:16px; display:block; }}
  .no-js .tile-share {{ display:none; }}
  .tile.is-stale {{ border-color:var(--warn-tile); }}
  .tile-cat {{ color:var(--muted); font-size:11px; letter-spacing:.12em; text-transform:uppercase; font-weight:600; }}
  .tile-name {{ font-size:15px; font-weight:550; color:var(--secondary); margin:6px 0 2px; padding-right:34px; }}
  .tile-qual {{ color:var(--muted); font-size:12px; font-weight:500; margin:0 0 14px; }}
  .hero {{ font-size:52px; font-weight:660; letter-spacing:-0.02em; line-height:1; }}
  .delta {{ display:block; font-size:13px; font-weight:550; margin-top:12px; }}
  .delta.bad {{ color:var(--critical); }}
  .delta.good {{ color:var(--good); }}
  .delta.neutral {{ color:var(--secondary); }}
  .freshness {{ display:flex; align-items:center; gap:10px; margin-top:10px; flex-wrap:wrap; }}
  .asof {{ font-size:12px; color:var(--secondary); font-weight:550; }}
  .stale-flag {{ font-size:11px; font-weight:600; color:var(--warn);
                border:1px solid var(--warn-line); border-radius:100px; padding:2px 8px; }}
  .tile-sub {{ color:var(--muted); font-size:12.5px; margin-top:8px; min-height:1.4em; }}
  .bars {{ margin:18px 0 6px; display:flex; flex-direction:column; gap:9px; }}
  .bar-row {{ display:grid; grid-template-columns:88px 1fr auto; align-items:center; gap:10px; }}
  .bar-label {{ color:var(--secondary); font-size:12px; }}
  .bar-track {{ background:var(--grid); border-radius:4px; height:10px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:4px; }}
  .bar-val {{ color:var(--primary); font-size:12px; font-variant-numeric:tabular-nums; }}
  .tile-foot {{ display:flex; justify-content:space-between; align-items:center; gap:10px;
               margin-top:14px; padding-top:14px; border-top:1px solid var(--hair);
               font-size:11.5px; color:var(--muted); flex-wrap:wrap; }}
  .tile-foot a {{ color:var(--secondary); text-decoration:none; font-weight:550; }}
  .tile-foot a:hover {{ color:var(--series-1); }}
  /* ---- category tabs = section nav (scroll-to; JS-off shows the whole board) ---- */
  .tabs-wrap {{ position:relative; margin:28px 0 4px; }}
  .tabs-wrap::before, .tabs-wrap::after {{ content:""; position:absolute; top:0; bottom:0; width:72px;
          pointer-events:none; opacity:0; transition:opacity .18s ease; z-index:1; border-radius:12px; }}
  .tabs-wrap::after {{ right:0; background:linear-gradient(to right, transparent, var(--plane)); }}
  .tabs-wrap::before {{ left:0; background:linear-gradient(to left, transparent, var(--plane)); }}
  .stickybar.stuck .tabs-wrap::after {{ background:linear-gradient(to right, transparent, var(--surface)); }}
  .stickybar.stuck .tabs-wrap::before {{ background:linear-gradient(to left, transparent, var(--surface)); }}
  .tabs-wrap.more-right::after {{ opacity:1; }}
  .tabs-wrap.more-left::before {{ opacity:1; }}
  .tabs {{ display:flex; gap:3px; margin:0; padding:4px; background:var(--tab-track);
          border:1px solid var(--hair); border-radius:12px; overflow-x:auto; scrollbar-width:none; }}
  .tabs::-webkit-scrollbar {{ display:none; }}
  .tab {{ flex:1 0 auto; white-space:nowrap; text-align:center; font-size:13px; font-weight:600;
         color:var(--secondary); background:none; border:0; border-radius:8px; padding:8px 14px;
         cursor:pointer; font-family:inherit; transition:background .15s ease, color .15s ease; }}
  .tab:hover {{ color:var(--primary); }}
  .tab.active {{ color:var(--primary); background:var(--tab-active); box-shadow:var(--seg-shadow); }}
  .no-js .tabs {{ display:none; }}
  .category[hidden] {{ display:none; }}

  /* ---- expandable cards ---- */
  .expand-btn {{ width:100%; margin-top:14px; background:none; font-family:inherit;
                border:1px solid var(--hair); border-radius:10px; color:var(--secondary);
                font-size:12px; font-weight:600; padding:8px 10px; cursor:pointer;
                display:flex; align-items:center; justify-content:center; gap:8px; }}
  .expand-btn:hover {{ color:var(--primary); border-color:var(--hair-strong); }}
  .expand-btn svg {{ transition:transform .25s ease; }}
  .tile.open .expand-btn svg {{ transform:rotate(180deg); }}
  .no-js .expand-btn {{ display:none; }}
  .tile.open {{ border-color:var(--tile-open); }}
  .detail {{ margin-top:18px; border-top:1px solid var(--hair); padding-top:18px; animation:reveal .28s ease; }}
  /* expanded detail opens in a full-width drawer beneath the card's row; drawer surface is a
     step lighter than the cards so the expanded panel reads as distinct (esp. stacked on mobile) */
  .detail-drawer {{ grid-column:1 / -1; background:var(--drawer); border:1px solid var(--hair);
    border-radius:16px; overflow:hidden; max-height:0; transition:max-height .34s ease; box-shadow:var(--drawer-shadow); }}
  .detail-drawer > .detail {{ margin-top:0; border-top:0; padding:24px 26px 20px; }}
  /* ---- mobile (single-column): fuse the open card + its drawer into ONE panel ----
     On a phone there are no side-by-side cards to compare the highlight against, and a
     rounded, gapped drawer just reads as the next card. So we butt them together: drop
     the gap, square the join, share one continuous outline, and run an accent spine down
     the left of the whole unit — it reads as the card expanding, not a second card. */
  @media (max-width:665px) {{
    .tile.open {{ border-bottom-left-radius:0; border-bottom-right-radius:0; border-bottom:0;
                 border-left:3px solid var(--tile-open); }}
    .detail-drawer {{ margin-top:-18px; border-top-left-radius:0; border-top-right-radius:0;
                 border-top:0; border-color:var(--tile-open); border-left:3px solid var(--tile-open); }}
  }}
  /* ---- desktop: caret under the open card points down at the full-width drawer ----
     The drawer opens below the whole row, so on desktop the title + highlight alone
     don't show which card it came from. A small pointer at the open card's bottom edge
     draws the eye from the card to the panel below it. */
  @media (min-width:666px) {{
    .tile.open {{ position:relative; }}
    .tile.open::after {{ content:""; position:absolute; left:50%; bottom:-9px;
      transform:translateX(-50%); width:0; height:0;
      border-left:10px solid transparent; border-right:10px solid transparent;
      border-top:10px solid var(--drawer); filter:drop-shadow(0 1.5px 0 var(--tile-open));
      pointer-events:none; z-index:2; }}
  }}
  /* whole collapsed card is clickable */
  .tile[data-id] {{ cursor:pointer; }}
  .tile[data-id]:not(.open):hover {{ border-color:var(--tile-hover-border); background:var(--tile-hover); box-shadow:var(--tile-hover-shadow); }}
  .detail[hidden] {{ display:none; }}
  @keyframes reveal {{ from {{ opacity:0; transform:translateY(-4px); }} to {{ opacity:1; transform:none; }} }}
  .chart-head {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; flex-wrap:wrap; margin-bottom:10px; }}
  .chart-title {{ font-size:13px; font-weight:600; color:var(--secondary); }}
  .chart-ctrl {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .ctrl-btn {{ font-size:11.5px; font-weight:600; color:var(--muted); background:none; font-family:inherit;
              border:1px solid var(--hair); border-radius:8px; padding:4px 10px; cursor:pointer; }}
  .ctrl-btn:hover {{ color:var(--primary); }}
  .ctrl-btn.active {{ color:var(--primary); border-color:var(--series-1); background:var(--accent-tint); }}
  /* real-price slider: a sub-control that sits below the view filters */
  .realbar {{ display:flex; align-items:center; gap:10px; margin:2px 0 8px; }}
  .realbar .rlbl {{ font-size:12px; color:var(--muted); }}
  .rswitch {{ position:relative; display:inline-flex; background:var(--rswitch); border:1px solid var(--hair);
             border-radius:999px; padding:3px; }}
  .rswitch button {{ all:unset; position:relative; z-index:1; flex:1; cursor:pointer; text-align:center; min-width:92px;
             white-space:nowrap; box-sizing:border-box; font-family:inherit; font-size:12px; font-weight:600;
             color:var(--muted); padding:5px 14px; border-radius:999px; }}
  .rswitch button[aria-pressed="true"] {{ color:var(--primary); }}
  .rknob {{ position:absolute; top:3px; bottom:3px; left:3px; width:calc(50% - 3px); background:var(--rknob);
           border-radius:999px; transition:left .18s ease; z-index:0; }}
  .rswitch.on .rknob {{ left:50%; }}
  .legend {{ display:flex; gap:14px; flex-wrap:wrap; margin:0 0 8px; }}
  .lg {{ display:flex; align-items:center; gap:7px; font-size:12px; color:var(--secondary); font-weight:550; }}
  .lg .key {{ width:14px; height:0; border-top:2.5px solid; border-radius:2px; }}
  /* ---- snapshot (point-in-time metrics: composition / value-vs-target) ---- */
  .snap {{ padding:6px 2px 2px; }}
  .snap-hl {{ font-size:15.5px; font-weight:600; color:var(--primary); margin-bottom:16px; }}
  .snap-bar {{ display:flex; height:16px; border-radius:6px; overflow:hidden; background:var(--grid); }}
  .snap-seg {{ height:100%; }}
  .snap-seg + .snap-seg {{ box-shadow:inset 1.5px 0 0 var(--surface); }}
  .snap-legend {{ margin-top:16px; display:flex; flex-direction:column; gap:10px; }}
  .snap-row {{ display:grid; grid-template-columns:12px 1fr auto; align-items:center; gap:11px; }}
  .snap-key {{ width:12px; height:12px; border-radius:3px; }}
  .snap-lab {{ color:var(--secondary); font-size:13px; }}
  .snap-val {{ color:var(--primary); font-size:13px; font-variant-numeric:tabular-nums; text-align:right; }}
  .snap-track {{ position:relative; height:16px; border-radius:6px; background:var(--grid); margin-top:34px; }}
  .snap-fill {{ height:100%; border-radius:6px; }}
  .snap-mark {{ position:absolute; top:-5px; bottom:-5px; width:2px; background:var(--chart-dash); }}
  .snap-mark-lab {{ position:absolute; top:-24px; transform:translateX(-50%); white-space:nowrap;
                   font-size:11px; font-weight:600; color:var(--muted); }}
  .snap-over {{ margin-top:14px; font-size:12.5px; font-weight:600; color:var(--secondary); }}
  .snap-cap {{ margin-top:16px; font-size:12.5px; color:var(--muted); line-height:1.55; }}
  .chart-box {{ position:relative; outline:none; border-radius:8px;
    -webkit-user-select:none; user-select:none; -webkit-touch-callout:none; touch-action:none; }}
  .chart-box:focus-visible {{ box-shadow:0 0 0 2px var(--focus); }}
  .chart-box svg {{ display:block; touch-action:none; }}
  .chart-box svg text {{ font-family:inherit; }}
  .tooltip {{ position:absolute; pointer-events:none; background:var(--tooltip); border:1px solid var(--hair);
             border-radius:10px; padding:8px 11px; font-size:12px; display:none; z-index:5;
             box-shadow:0 6px 20px var(--shadow); min-width:120px; }}
  .tt-x {{ color:var(--muted); font-size:11px; margin-bottom:2px; font-weight:600; }}
  .tt-row {{ display:flex; align-items:center; gap:7px; margin-top:4px; }}
  .tt-key {{ width:11px; border-top:2.5px solid; border-radius:2px; flex:none; }}
  .tt-val {{ font-weight:650; color:var(--primary); font-variant-numeric:tabular-nums; }}
  .tt-lab {{ color:var(--secondary); font-size:11.5px; }}
  .dtable {{ max-height:280px; overflow:auto; border:1px solid var(--hair); border-radius:10px; }}
  .dtable table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  .dtable th {{ position:sticky; top:0; background:var(--surface); text-align:right; padding:7px 12px;
               color:var(--muted); font-weight:600; border-bottom:1px solid var(--hair); }}
  .dtable th:first-child, .dtable td:first-child {{ text-align:left; }}
  .dtable td {{ padding:5px 12px; text-align:right; color:var(--secondary);
               font-variant-numeric:tabular-nums; border-bottom:1px solid var(--hair-faint); }}
  .accrue {{ border:1px dashed var(--hair-strong); border-radius:12px; padding:28px 22px;
            text-align:center; color:var(--muted); font-size:12.5px; }}
  .accrue b {{ display:block; color:var(--secondary); font-size:13px; margin-bottom:6px; font-weight:600; }}
  .furniture {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:16px; }}
  @media (max-width:720px) {{ .furniture {{ grid-template-columns:1fr; }} }}
  .fbox {{ background:var(--panel); border:1px solid var(--hair); border-radius:12px; padding:14px 16px; }}
  .fbox h4 {{ margin:0 0 8px; font-size:11px; letter-spacing:.1em; text-transform:uppercase;
             color:var(--muted); font-weight:650; }}
  .fbox p {{ margin:0; font-size:12.5px; color:var(--secondary); line-height:1.55; }}
  .fbox p + p {{ margin-top:7px; }}
  .fbox .flabel {{ font-weight:650; color:var(--primary); }}
  .detail-meta {{ display:flex; gap:6px 18px; flex-wrap:wrap; margin-top:14px; font-size:11.5px;
                 color:var(--muted); align-items:center; }}
  .detail-meta a {{ color:var(--secondary); font-weight:550; text-decoration:none; }}
  .detail-meta .vtoggle {{ color:var(--muted); border:1px solid var(--hair); border-radius:6px; padding:2px 9px; cursor:pointer; }}
  .detail-meta .vtoggle:hover {{ color:var(--primary); border-color:var(--hair-strong); }}
  .detail-meta .exp-group {{ display:inline-flex; align-items:center; gap:9px; }}
  .detail-meta .exp-lbl {{ color:var(--muted); display:inline-flex; align-items:center; gap:4px; }}
  .detail-meta .exp-link {{ color:var(--secondary); cursor:pointer; }}
  .detail-meta .exp-link:hover {{ color:var(--series-1); }}
  .detail-meta a:hover {{ color:var(--series-1); }}
  /* share button, bottom-right of the open drawer (brief 09) */
  .detail-share {{ margin-left:auto; display:inline-flex; align-items:center; gap:6px;
    background:none; font-family:inherit; font-size:11.5px; font-weight:600; color:var(--secondary);
    border:1px solid var(--hair); border-radius:6px; padding:3px 11px; cursor:pointer;
    transition:color .15s ease, border-color .15s ease; }}
  .detail-share:hover {{ color:var(--primary); border-color:var(--hair-strong); }}
  .detail-share:focus-visible {{ outline:none; box-shadow:0 0 0 2px var(--focus); }}
  .detail-share svg {{ width:14px; height:14px; }}
  /* desktop fallback popover (mobile uses the native share sheet instead) */
  .share-panel {{ position:absolute; z-index:60; min-width:168px; background:var(--surface);
    border:1px solid var(--hair-strong); border-radius:12px; padding:6px;
    box-shadow:0 10px 30px var(--shadow); display:flex; flex-direction:column; gap:2px; }}
  .share-opt {{ display:block; width:100%; text-align:left; background:none; border:0;
    font-family:inherit; font-size:13px; color:var(--primary); padding:8px 11px; border-radius:8px;
    cursor:pointer; text-decoration:none; }}
  .share-opt:hover {{ background:var(--panel); }}
  .share-opt:focus-visible {{ outline:none; box-shadow:0 0 0 2px var(--focus); }}

  footer {{ margin-top:52px; border-top:1px solid var(--hair); padding-top:24px;
           color:var(--muted); font-size:12px; text-align:center; line-height:1.6; }}
  footer a {{ color:var(--secondary); }}
  .footer-nav {{ margin-top:12px; }}
  .footer-nav a {{ margin:0 5px; text-decoration:none; }}
  .footer-nav a:hover {{ color:var(--series-1); }}
  .built {{ opacity:.6; font-size:11px; margin-top:14px; }}
  /* homepage callout → links to the full /transparency page (table lives there).
     Stacked and narrower than the board so it reads as a distinct note. */
  .callout {{ margin:48px auto 0; max-width:640px; background:var(--panel);
             border:1px solid var(--hair); border-radius:14px; padding:24px 26px; }}
  .callout h2 {{ font-size:15px; margin:0 0 8px; color:var(--primary); }}
  .callout p {{ color:var(--secondary); font-size:13.5px; line-height:1.62; margin:0 0 14px; }}
  .callout p b {{ color:var(--primary); font-weight:650; }}
  .callout-link {{ font-size:13.5px; font-weight:600; color:var(--series-1); text-decoration:none; }}
  .callout-link:hover {{ text-decoration:underline; }}
  @media (max-width:560px) {{ .callout {{ padding:20px; }} }}
</style>
</head>
<body>
  <div class="wrap wrap-hero">
    <header id="hero">
      <h1><span class="h1-accent">Trump</span> by Numbers</h1>
      <p class="lede">The administration's record, in data.</p>
    </header>
  </div>
  <div id="sbSentinel"></div>
  <div class="stickybar" id="stickybar">
    <div class="wrap sb-inner">
      <div class="sb-top">
        <button class="mini-title" id="miniTitle" type="button" aria-label="Back to top"><span class="h1-accent">Trump</span> by Numbers</button>
        <div class="head-ctrls" id="headCtrls">
          <button class="theme-toggle" id="infoScroll" type="button" aria-label="Jump to page links">{_ICON_INFO}</button>
          {board_share_btn}
          <button class="theme-toggle" id="themeToggle" type="button" aria-label="Switch to light theme" aria-pressed="false"></button>
        </div>
      </div>
      <div class="tabs-wrap"><nav class="tabs" id="tabs" aria-label="Categories">{tabs_html}</nav></div>
    </div>
  </div>
  <div class="wrap wrap-main">
    <main>
      {body}
      {frozen_callout()}
    </main>
    <footer>
      <div class="footer-nav"><a href="/methodology">About</a> · <a href="/transparency">Transparency</a> · <a href="/support">Support</a> · <a href="/contact">Contact</a></div>
    </footer>
  </div>
  <script>
%%CHARTJS%%
  </script>
  {BEACON}
</body>
</html>"""
    html = html.replace("%%CHARTJS%%", chart_js)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write(html)
    print("wrote", OUT, f"({len(html)} bytes, {live} metrics, "
          f"{len(expandable)} expandable, {len(os.listdir(SITE_D))} series payloads)")
    if payload_fail:
        print(f"  ! {len(payload_fail)} payload(s) failed, board still shipped")

    # ---- phase 4: meta pages + security headers (into the build output dir) ----
    site_dir = os.path.dirname(OUT)
    meta_pages = [
        ("methodology.html", "/methodology",
         "About", "About",
         "What this site is, and how it works.",
         "How Trump by Numbers is built, sourced, and kept factual: official primary sources, shown with history, chosen for importance not direction.",
         _about_content()),
        ("support.html", "/support",
         "Support", "Support",
         "The site is free to use. If you'd like to help keep it going, here's how.",
         "Support Trump by Numbers: a one-off tip on Ko-fi or GitHub Sponsors, or free ways to help like sharing a card or suggesting a metric.",
         _support_content()),
        ("contact.html", "/contact",
         "Contact", "Say hello",
         "Ask a question. Suggest a metric. Share feedback.",
         "Contact Trump by Numbers: suggest a metric, send feedback, or discuss the numbers in public on GitHub Discussions.",
         _contact_content()),
        ("transparency.html", "/transparency",
         "Government data that stopped updating", "Data that went dark",
         "Official data sources that stopped publishing since January 2025. Where one went dark, the board switched to a still-current source, so the numbers here stay live. Updated daily.",
         "Official US data series frozen, deleted, or narrowed since January 2025, each with its last release, what happened, and the still-current source the board uses instead.",
         frozen_page_content()),
    ]
    for fname, current, title, hero, lede, desc, content in meta_pages:
        page = render_meta_page(current, title, hero, lede, desc, content,
                                dark_tokens, light_tokens)
        with open(os.path.join(site_dir, fname), "w") as f:
            f.write(page)
        print("wrote", os.path.join(site_dir, fname), f"({len(page)} bytes)")

    with open(os.path.join(site_dir, "_headers"), "w") as f:
        f.write(_headers_text())
    print("wrote", os.path.join(site_dir, "_headers"))

    # Brand link-preview image (one card for the whole site, brief 09). Copied
    # from assets/ each build so the daily run reproduces it; swap assets/og.png
    # to change every share preview at once.
    import shutil
    og_src = os.path.join(ASSETS, "og.png")
    if os.path.exists(og_src):
        shutil.copyfile(og_src, os.path.join(site_dir, "og.png"))
        print("wrote", os.path.join(site_dir, "og.png"))
    else:
        print("  ! assets/og.png missing, link-preview image not emitted")


if __name__ == "__main__":
    build()
