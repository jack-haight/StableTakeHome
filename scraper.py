"""
Stable ICP Scraper — freshly-funded, remote-first startups
=============================================================

WHAT THIS IS
Sources are read from a local JSON file so the demo runs with zero API keys.
Each `fetch_*` function below is a stand-in for a real data pull — swap the
body for a live API/scrape call and everything downstream (scoring,
disqualification, output) keeps working unchanged. That's the "repeatable
engine" the exercise asks for: the scoring logic is the system, the source
functions are pluggable.

REAL SOURCES THIS WOULD PLUG INTO
  - Crunchbase API (Organizations Search, filter: funding_type, announced_on)
  - YC's public "Launch" / company API (batch + description)
  - SEC EDGAR full-text search API for Form D filings (free, no key needed:
    https://efts.sec.gov/LATEST/search-index?q=%22Form D%22&forms=D)
  - Clearbit / Apollo.io for contact enrichment (find the founder/ops contact)
  - LinkedIn job postings (via a tool like Apollo or PhantomBuster) to check
    for "remote" language in open roles, used as a corroborating signal

USAGE
  python scraper.py                  # run full pipeline, print + save CSV
  python scraper.py --min-score 60   # only show leads above a fit threshold
"""

import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import csv

DATA_DIR = Path(__file__).parent / "data"
RAW_SIGNALS_PATH = DATA_DIR / "raw_funding_signals.json"
OUTPUT_PATH = DATA_DIR / "scored_leads.csv"

TODAY = datetime(2026, 7, 12)


# ---------------------------------------------------------------------------
# STEP 1 — SOURCE. Swap these for real API calls when ready.
# ---------------------------------------------------------------------------

def fetch_funding_signals():
    """
    MOCK: reads local JSON.
    REAL: would hit Crunchbase API + YC Launch feed + SEC EDGAR Form D
    full-text search, normalize each into the same shape, and merge.
    """
    with open(RAW_SIGNALS_PATH) as f:
        return json.load(f)


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

def run_pipeline(min_score=0):
    signals = fetch_funding_signals()
    results = []

    for s in signals:
        score, reasons, dq, dq_reason = score_lead(s)
        contact_persona = enrich_contact(s["company"], s["employee_count_estimate"])
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

    # Sort qualified leads by score desc, disqualified leads at the bottom
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
    args = parser.parse_args()

    qualified, disqualified = run_pipeline(min_score=args.min_score)
    save_csv(qualified, disqualified)

    print(f"\n{'='*70}\nQUALIFIED LEADS ({len(qualified)})\n{'='*70}")
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