"""
Stable ICP Scraper — Streamlit UI
=====================================
Run with:  streamlit run app_scraper.py

This is a thin UI layer over scraper.py. All the actual sourcing and scoring
logic lives there and is untouched — this app just calls run_pipeline(),
shows the results, and lets you tweak the score threshold and source mode
interactively.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path

import scraper

st.set_page_config(page_title="Stable ICP Scraper", layout="wide")

st.title("🔎 Stable ICP Scraper")

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
st.sidebar.header("Source")
mode = st.sidebar.radio(
    "Data mode",
    options=["mock", "live", "yc"],
    format_func=lambda m: {
        "mock": "🧪 Mock (local JSON demo data)",
        "live": "🌐 Live (SEC EDGAR Form D)",
        "yc": "🚀 Live (YC directory)",
    }[m],
)
days_back = 14
if mode == "live":
    days_back = st.sidebar.slider("Days of Form D filings to pull", 1, 60, 14)
    st.sidebar.caption(
        "Hits SEC's free EDGAR full-text search API — no key needed, but each "
        "filing requires a follow-up fetch for the offering amount, so larger "
        "windows take longer to load. Covers all private offerings, so non-startup "
        "filers (funds, real estate, etc.) are filtered out before scoring."
    )
elif mode == "yc":
    days_back = st.sidebar.slider("Days since YC launch date", 7, 180, 90)
    st.sidebar.caption(
        "Pulls YC's public company directory (via the free yc-oss/api mirror) — "
        "real team sizes, no key needed. Round size isn't published by YC, so "
        "amount is a standard-deal estimate, flagged for verification."
    )

st.sidebar.header("Filters")
min_score = st.sidebar.slider("Minimum fit score", 0, 100, 0, step=5)
st.sidebar.caption("Only qualified leads at or above this score are shown in the main table.")

if mode == "mock":
    st.warning(
        "**Mock data mode** — results below come from `data/raw_funding_signals.json`, "
        "not a live feed. Switch to **Live** in the sidebar to pull real, freshly-filed "
        "SEC Form D notices instead.",
        icon="🧪",
    )
    if not scraper.RAW_SIGNALS_PATH.exists():
        st.error(
            f"Couldn't find `{scraper.RAW_SIGNALS_PATH}`. Make sure "
            "`data/raw_funding_signals.json` exists next to `scraper.py`."
        )
        st.stop()
elif mode == "live":
    st.info(
        "**Live mode** — pulling real Form D filings from SEC EDGAR. Employee count and "
        "remote-work status aren't in Form D data, so those are conservatively defaulted "
        "and flagged for enrichment (⚠) until a Crunchbase/Apollo source is wired in.",
        icon="🌐",
    )
else:
    st.info(
        "**Live mode** — pulling real companies from YC's public directory. Team size is "
        "real; round size isn't published by YC, so it's a standard-deal estimate flagged (⚠) "
        "for verification before outreach.",
        icon="🚀",
    )

with st.spinner("Running pipeline..." if mode == "mock" else "Fetching live filings from SEC EDGAR..."):
    try:
        qualified, disqualified = scraper.run_pipeline(min_score=min_score, mode=mode, days_back=days_back)
    except Exception as e:
        st.error(f"Pipeline failed to run: {e}")
        st.stop()

qualified_df = pd.DataFrame(qualified)
disqualified_df = pd.DataFrame(disqualified)
all_df = pd.concat([qualified_df, disqualified_df], ignore_index=True) if not disqualified_df.empty else qualified_df

# ---------------------------------------------------------------------------
# Top-line metrics
# ---------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Qualified leads", len(qualified_df))
c2.metric("Disqualified", len(disqualified_df))
c3.metric(
    "Avg fit score (qualified)",
    f"{qualified_df['fit_score'].mean():.0f}" if not qualified_df.empty else "—",
)
c4.metric(
    "Top score",
    int(qualified_df["fit_score"].max()) if not qualified_df.empty else "—",
)

st.divider()

# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------
left, right = st.columns([2, 1])

with left:
    st.subheader("🎯 Qualified leads")
    if qualified_df.empty:
        st.info("No leads meet this score threshold. Try lowering the minimum fit score.")
    else:
        display_cols = ["company", "fit_score", "round", "amount_usd", "announced_date",
                         "employee_count_estimate", "suggested_contact", "source"]
        st.dataframe(
            qualified_df[display_cols].rename(columns={
                "fit_score": "Fit Score", "amount_usd": "Amount ($)",
                "employee_count_estimate": "Headcount", "suggested_contact": "Suggested Contact",
                "company": "Company", "round": "Round", "announced_date": "Announced",
                "source": "Source",
            }),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Fit Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
                "Amount ($)": st.column_config.NumberColumn(format="$%d"),
            },
        )

        st.subheader("Why each lead scored the way it did")
        for _, row in qualified_df.iterrows():
            with st.expander(f"[{row['fit_score']}] {row['company']}"):
                st.write(row["reasons"].replace(" | ", "\n\n"))

    if not disqualified_df.empty:
        st.subheader("🚫 Disqualified")
        st.dataframe(
            disqualified_df[["company", "dq_reason", "employee_count_estimate", "team_location"]].rename(columns={
                "company": "Company", "dq_reason": "Reason", "employee_count_estimate": "Headcount",
                "team_location": "Team Location",
            }),
            use_container_width=True,
            hide_index=True,
        )

with right:
    st.subheader("Score distribution")
    if not all_df.empty:
        fig = px.histogram(all_df, x="fit_score", nbins=10, title=None)
        fig.update_layout(xaxis_title="Fit score", yaxis_title="Count", margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True)

    if not qualified_df.empty:
        st.subheader("Suggested contact mix")
        persona_counts = qualified_df["suggested_contact"].value_counts().reset_index()
        persona_counts.columns = ["persona", "count"]
        fig2 = px.pie(persona_counts, names="persona", values="count")
        fig2.update_layout(margin=dict(t=10))
        st.plotly_chart(fig2, use_container_width=True)

    if not qualified_df.empty:
        st.subheader("Round size vs. score")
        fig3 = px.scatter(qualified_df, x="amount_usd", y="fit_score", hover_name="company",
                           labels={"amount_usd": "Round size ($)", "fit_score": "Fit score"})
        fig3.update_layout(margin=dict(t=10))
        st.plotly_chart(fig3, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
st.subheader("Export")
csv_bytes = all_df.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Download scored_leads.csv",
    data=csv_bytes,
    file_name="scored_leads.csv",
    mime="text/csv",
)
st.caption(f"Or find it on disk at `{scraper.OUTPUT_PATH}` after this app runs (saved automatically each load).")

# Save to disk too, matching scraper.py's own CLI behavior
try:
    scraper.save_csv(qualified, disqualified)
except Exception as e:
    st.caption(f"(Couldn't write to disk: {e})")