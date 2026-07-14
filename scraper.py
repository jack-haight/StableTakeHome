"""
Stable ICP Scraper — freshly-funded, remote-first startups
=============================================================

WHAT THIS IS
Two source modes are supported now:
  --mode mock   (default) reads from a local JSON file, zero API keys, for demos.
  --mode live   pulls real, freshly-filed SEC Form D notices from EDGAR's free
                full-text search API, then hydrates each hit with the actual
                offering amount by fetching that filing's primary_doc.xml.
                No API key required for either EDGAR call.

Everything downstream of fetch_funding_signals() — enrich_contact(),
score_lead(), run_pipeline() — is completely unchanged between modes. That's
the point of the pluggable-source design: the scoring logic is the system,
the source functions are swappable.

REMAINING REAL SOURCES THIS COULD PLUG INTO (not wired up yet)
  - Crunchbase API (Organizations Search) — paid, but gives employee count
    and remote-flag directly instead of needing separate enrichment
  - YC's company directory (unofficial Algolia index, no key, but credentials
    can rotate/break — lower priority)
  - Clearbit / Apollo.io for contact enrichment (would replace the persona
    guess in enrich_contact() with a real name/email)
  - LinkedIn job postings (via Apollo/PhantomBuster) for the remote-mention
    signal — no public API, scraping-based, lowest priority / most fragile

USAGE
  python scraper.py                          # mock mode, full pipeline, print + save CSV
  python scraper.py --mode live               # real EDGAR Form D pull, last 14 days
  python scraper.py --mode live --days-back 30
  python scraper.py --min-score 60
"""

import json
import argparse
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
import csv
import xml.etree.ElementTree as ET

try:
    import requests
except ImportError:
    requests = None  # only required for --mode live

DATA_DIR = Path(__file__).parent / "data"
RAW_SIGNALS_PATH = DATA_DIR / "raw_funding_signals.json"
OUTPUT_PATH = DATA_DIR / "scored_leads.csv"

TODAY = datetime(2026, 7, 12)

# SEC asks that callers identify themselves — no key needed, just a real UA.
SEC_HEADERS = {"User-Agent": "Stable ICP Research contact@example.com"}

# Form D covers ANY private securities offering, not just startup equity
# rounds — real-estate funds, oil & gas partnerships, and pooled investment
# vehicles all file it too. These industryGroupType values (from Item 3 of
# the form itself) are essentially never operating startups, so we drop them
# before scoring rather than let them dilute the qualified list. This is a
# v1 exclude-list — tune it against real results as you see more filings.
EXCLUDED_INDUSTRIES = {
    "Pooled Investment Fund",
    "Real Estate",
    "Other Real Estate",
    "REITS and Finance",
    "Oil and Gas",
    "Mining",
    "Investing",
    "Commercial Banking",
    "Insurance",
    "Other Banking and Financial Services",
    "Hedge Fund",
}


# ---------------------------------------------------------------------------
# STEP 1 — SOURCE. Swap these for real API calls when ready.
# ---------------------------------------------------------------------------

def fetch_funding_signals_mock():
    """
    MOCK: reads local JSON.
    REAL: would hit Crunchbase API + YC Launch feed + SEC EDGAR Form D
    full-text search, normalize each into the same shape, and merge.
    """
    with open(RAW_SIGNALS_PATH) as f:
        return json.load(f)


def fetch_funding_signals_edgar(days_back=14, max_results=40):
    """
    REAL, LIVE, NO API KEY: pulls Form D notices from SEC EDGAR's official
    full-text search API. Form D is filed within 15 days of a company's
    first sale in a private offering, which makes it a near-real-time
    "just raised money" trigger — arguably fresher than press-release-based
    sources like Crunchbase, since it's a legal filing deadline, not PR timing.

    Two-stage fetch:
      1. Query the search index for Form D filings in the date window.
      2. For each hit, fetch that filing's primary_doc.xml to pull the
         actual offering amount and industry group — the search index
         only returns matched text + metadata, not the structured fields.
    """
    if requests is None:
        raise RuntimeError("`pip install requests` to use --mode live")

    end = TODAY
    start = end - timedelta(days=days_back)
    search_url = "https://efts.sec.gov/LATEST/search-index"
    params = {
        "forms": "D",
        "dateRange": "custom",
        "startdt": start.strftime("%Y-%m-%d"),
        "enddt": end.strftime("%Y-%m-%d"),
    }

    resp = requests.get(search_url, params=params, headers=SEC_HEADERS, timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("hits", {}).get("hits", [])[:max_results]

    signals = []
    seen_accessions = set()
    skipped_industry = 0

    for h in hits:
        src = h["_source"]
        cik = (src.get("ciks") or [None])[0]
        accession_no = h["_id"].split(":")[0] if ":" in h["_id"] else h["_id"]

        # A single filing can match on multiple exhibit documents and show up
        # as separate hits — only process it once.
        if accession_no in seen_accessions:
            continue
        seen_accessions.add(accession_no)

        amount_usd, industry = _fetch_form_d_detail(cik, accession_no)
        time.sleep(0.15)  # stay well under SEC's fair-access rate expectations

        if industry in EXCLUDED_INDUSTRIES:
            skipped_industry += 1
            continue

        signals.append({
            "company": (src.get("display_names") or ["Unknown"])[0].split(" (CIK")[0],
            "round": f"Form D{f' — {industry}' if industry else ''}",
            "amount_usd": amount_usd,  # None if the detail fetch failed/was skipped
            "announced_date": src.get("file_date"),
            "team_location": src.get("locationCodes", [""])[0] if src.get("locationCodes") else "",
            # Not present in Form D data — flagged for the enrichment step below.
            "employee_count_estimate": None,
            "linkedin_jobs_mention_remote": False,
            "hq_state_listed": src.get("locationCodes", [""])[0] if src.get("locationCodes") else "",
            "source": "SEC EDGAR Form D (live)",
            "needs_enrichment": True,
        })

    if skipped_industry:
        print(f"[fetch_funding_signals_edgar] filtered out {skipped_industry} "
              f"non-startup filings (funds/real-estate/etc.)")

    return signals


def _fetch_form_d_detail(cik, accession_no):
    """
    Fetches primary_doc.xml for a single Form D filing and pulls the total
    offering amount + industry group. Returns (amount_usd | None, industry | None).
    Best-effort: EDGAR's document layout varies enough across filers that a
    parse miss shouldn't take down the whole pipeline.
    """
    if not cik or not accession_no:
        return None, None
    try:
        acc_nodashes = accession_no.replace("-", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/"
               f"{int(cik)}/{acc_nodashes}/primary_doc.xml")
        resp = requests.get(url, headers=SEC_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None, None
        root = ET.fromstring(resp.text)
        ns = {"n": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

        def find_text(tag):
            el = root.find(f".//{{{ns.get('n','')}}}{tag}") if ns else root.find(f".//{tag}")
            return el.text if el is not None else None

        amount_raw = find_text("totalOfferingAmount")
        amount_usd = int(re.sub(r"[^\d]", "", amount_raw)) if amount_raw and amount_raw.isdigit() else None
        industry = find_text("industryGroupType")
        return amount_usd, industry
    except Exception:
        return None, None


def _apply_conservative_defaults(signal):
    """
    Form D alone doesn't include headcount or remote-work signal — those
    would come from a Crunchbase/Apollo enrichment pass we haven't wired up
    yet. Rather than crash score_lead() on None fields, default to
    conservative values (assume small team, assume remote-status unknown)
    and leave a visible flag so these rows can be prioritized for manual
    enrichment before outreach.
    """
    if signal.get("employee_count_estimate") is None:
        signal["employee_count_estimate"] = 8  # early Form D filers skew tiny; conservative guess
    if signal.get("amount_usd") is None:
        signal["amount_usd"] = 0
    if not signal.get("hq_state_listed"):
        signal["hq_state_listed"] = ""
    if not signal.get("team_location"):
        signal["team_location"] = ""
    return signal


def enrich_contact(company_name, employee_count):
    """
    MOCK: infers the right persona to contact from headcount, since we don't
    have real contact data.
    REAL: would call Clearbit/Apollo to pull the actual founder/ops contact
    (name, title, email, LinkedIn URL) for the company.
    """
    if employee_count <= 8:
        return "Founder / Co-founder (CEO)"
    elif employee_count <= 25:
        return "Head of Operations / Finance"
    else:
        return "Office Manager / Workplace Lead"


# ---------------------------------------------------------------------------
# STEP 2 — SCORE. This is the part that stays constant regardless of source.
# ---------------------------------------------------------------------------

def score_lead(signal):
    """
    Returns (score 0-100, reasons[], disqualified: bool, dq_reason)
    Weights reflect the targeting thesis: recency, remote-native, small team,
    DE/WY incorporation without a listed physical office.
    """
    score = 0
    reasons = []

    # --- Disqualifiers first (hard filters) ---
    if signal["employee_count_estimate"] > 40:
        return 0, [], True, "Team size >40 — likely already has an ops/facilities function and a physical office"

    if "physical" in signal["team_location"].lower() or "facility" in signal["team_location"].lower():
        return 0, [], True, "Physical office/facility explicitly mentioned — not a fit for a virtual address"

    # --- Recency of funding (bigger buying-trigger window = higher score) ---
    announced = datetime.strptime(signal["announced_date"], "%Y-%m-%d")
    days_since = (TODAY - announced).days
    if days_since <= 14:
        score += 35
        reasons.append(f"Funding announced {days_since}d ago — hot buying window (address/entity setup is top of mind)")
    elif days_since <= 45:
        score += 20
        reasons.append(f"Funding announced {days_since}d ago — still within a reasonable outreach window")
    else:
        score += 5
        reasons.append(f"Funding announced {days_since}d ago — colder, but round size/profile still fits")

    # --- Remote-first signal ---
    if signal.get("linkedin_jobs_mention_remote"):
        score += 25
        reasons.append("Job postings/description explicitly reference remote/distributed team")

    # --- Small team (self-serve buyer, fast decision) ---
    if signal["employee_count_estimate"] <= 10:
        score += 20
        reasons.append(f"Team of {signal['employee_count_estimate']} — founder is likely the buyer, short sales cycle")
    elif signal["employee_count_estimate"] <= 25:
        score += 10
        reasons.append(f"Team of {signal['employee_count_estimate']} — small enough that ops decisions move fast")

    # --- Incorporation state (DE/WY = paperwork-savvy, no physical presence implied) ---
    if "delaware" in signal["hq_state_listed"].lower() or "wyoming" in signal["hq_state_listed"].lower():
        score += 15
        reasons.append(f"Incorporated in {signal['hq_state_listed']} — common for remote-first startups with no home-state office")

    # --- Round size sanity check (too big = probably already solved this) ---
    if signal["amount_usd"] <= 10_000_000:
        score += 5
        reasons.append("Round size fits early-stage profile (pre-seed/seed) — hasn't yet built out back-office infra")

    return min(score, 100), reasons, False, None


# ---------------------------------------------------------------------------
# STEP 3 — RUN PIPELINE
# ---------------------------------------------------------------------------

def run_pipeline(min_score=0, mode="mock", days_back=14):
    if mode == "live":
        raw_signals = fetch_funding_signals_edgar(days_back=days_back)
        signals = [_apply_conservative_defaults(s) for s in raw_signals]
    else:
        signals = fetch_funding_signals_mock()

    results = []
    for s in signals:
        score, reasons, dq, dq_reason = score_lead(s)
        contact_persona = enrich_contact(s["company"], s["employee_count_estimate"])
        if s.get("needs_enrichment"):
            reasons.append("⚠ headcount/remote-status assumed — needs Apollo/Clearbit enrichment before outreach")
        results.append({
            "company": s["company"],
            "round": s["round"],
            "amount_usd": s["amount_usd"],
            "announced_date": s["announced_date"],
            "team_location": s["team_location"],
            "employee_count_estimate": s["employee_count_estimate"],
            "fit_score": score,
            "disqualified": dq,
            "dq_reason": dq_reason or "",
            "reasons": " | ".join(reasons),
            "suggested_contact": contact_persona,
            "source": s["source"],
        })

    qualified = sorted([r for r in results if not r["disqualified"] and r["fit_score"] >= min_score],
                        key=lambda r: r["fit_score"], reverse=True)
    disqualified = [r for r in results if r["disqualified"]]

    return qualified, disqualified


def save_csv(qualified, disqualified, path=OUTPUT_PATH):
    fieldnames = ["company", "round", "amount_usd", "announced_date", "team_location",
                  "employee_count_estimate", "fit_score", "suggested_contact", "reasons",
                  "disqualified", "dq_reason", "source"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in qualified + disqualified:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=int, default=0)
    parser.add_argument("--mode", choices=["mock", "live"], default="mock",
                         help="mock = local JSON demo data; live = real SEC EDGAR Form D pull")
    parser.add_argument("--days-back", type=int, default=14,
                         help="live mode only: how many days of Form D filings to pull")
    args = parser.parse_args()

    qualified, disqualified = run_pipeline(min_score=args.min_score, mode=args.mode, days_back=args.days_back)
    save_csv(qualified, disqualified)

    print(f"\n{'='*70}\nQUALIFIED LEADS ({len(qualified)})  [mode={args.mode}]\n{'='*70}")
    for r in qualified:
        print(f"\n[{r['fit_score']}] {r['company']}  —  {r['round']}, ${r['amount_usd']:,}  ({r['announced_date']})")
        print(f"    Contact: {r['suggested_contact']}")
        print(f"    Why: {r['reasons']}")

    print(f"\n{'='*70}\nDISQUALIFIED ({len(disqualified)})\n{'='*70}")
    for r in disqualified:
        print(f"  {r['company']}: {r['dq_reason']}")

    print(f"\nSaved full results to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()