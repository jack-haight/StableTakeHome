"""
Stable Outbound Dashboard — input-driven version
====================================================
Run with:  streamlit run dash_app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
from datetime import date

st.set_page_config(page_title="Stable Outbound Dashboard", layout="wide")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
ACTIVITY_PATH = DATA_DIR / "activity_log.csv"
LEADS_PATH = DATA_DIR / "leads.csv"

ACTIVITY_COLS = ["date", "channel", "step", "company", "sent", "delivered",
                  "opened", "replied", "positive_reply", "meeting_booked", "notes"]
LEADS_COLS = ["date_added", "company", "segment", "contact_name", "contact_persona",
              "status", "fit_score", "source", "notes"]

CHANNELS = ["email", "call", "linkedin", "other"]
STATUSES = ["New", "Contacted", "Replied", "Meeting Booked", "Disqualified", "Closed - No Fit"]
SEGMENTS = ["Freshly-funded startup", "Multi-entity operator", "Other / manual add"]


def load_table(path, cols):
    if path.exists():
        df = pd.read_csv(path)
        for c in cols:
            if c not in df.columns:
                df[c] = None
        return df[cols]
    return pd.DataFrame(columns=cols)


def save_table(df, path):
    df.to_csv(path, index=False)


if "activity" not in st.session_state:
    st.session_state.activity = load_table(ACTIVITY_PATH, ACTIVITY_COLS)
if "leads" not in st.session_state:
    st.session_state.leads = load_table(LEADS_PATH, LEADS_COLS)


st.title("📬 Stable Outbound — Live Tracker")

tab_log, tab_leads, tab_dash = st.tabs(["✍️ Log activity", "🎯 Leads", "📊 Dashboard"])

with tab_log:
    st.subheader("Add a touch")
    with st.form("add_activity", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            a_date = st.date_input("Date", value=date.today())
            a_channel = st.selectbox("Channel", CHANNELS)
        with c2:
            a_step = st.text_input("Step / cadence stage")
            a_company = st.text_input("Company (optional)")
        with c3:
            a_sent = st.number_input("Sent", min_value=0, value=1, step=1)
            a_delivered = st.number_input("Delivered", min_value=0, value=1, step=1)
        c4, c5, c6 = st.columns(3)
        with c4:
            a_opened = st.number_input("Opened", min_value=0, value=0, step=1)
        with c5:
            a_replied = st.number_input("Replied", min_value=0, value=0, step=1)
        with c6:
            a_positive = st.number_input("Positive replies", min_value=0, value=0, step=1)
        a_booked = st.number_input("Meetings booked", min_value=0, value=0, step=1)
        a_notes = st.text_input("Notes (optional)")
        submitted = st.form_submit_button("Add entry", use_container_width=True)
        if submitted:
            new_row = pd.DataFrame([{
                "date": a_date, "channel": a_channel, "step": a_step, "company": a_company,
                "sent": a_sent, "delivered": a_delivered, "opened": a_opened, "replied": a_replied,
                "positive_reply": a_positive, "meeting_booked": a_booked, "notes": a_notes,
            }])
            st.session_state.activity = pd.concat([st.session_state.activity, new_row], ignore_index=True)
            save_table(st.session_state.activity, ACTIVITY_PATH)
            st.success(f"Logged {a_sent} {a_channel} touch(es) for {a_date}.")

    st.divider()
    st.subheader("Or import a batch from a CSV export")
    up = st.file_uploader("Upload activity CSV", type="csv", key="activity_upload")
    if up is not None:
        try:
            imported = pd.read_csv(up)
        except Exception as e:
            st.error(f"Couldn't read that CSV: {e}. Make sure it's not empty and is a valid comma-separated file.")
            imported = None
        if imported is not None:
            for c in ACTIVITY_COLS:
                if c not in imported.columns:
                    imported[c] = None
        if imported is not None and st.button("Append imported rows to the log"):
            st.session_state.activity = pd.concat([st.session_state.activity, imported[ACTIVITY_COLS]], ignore_index=True)
            save_table(st.session_state.activity, ACTIVITY_PATH)
            st.success(f"Imported {len(imported)} rows.")
            st.rerun()

    st.divider()
    st.subheader("All logged activity")
    edited = st.data_editor(st.session_state.activity, num_rows="dynamic", use_container_width=True, key="activity_editor")
    if st.button("💾 Save changes to activity log"):
        st.session_state.activity = edited
        save_table(edited, ACTIVITY_PATH)
        st.success("Saved.")

with tab_leads:
    st.subheader("Add a lead")
    with st.form("add_lead", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            l_company = st.text_input("Company / operator name")
            l_segment = st.selectbox("Segment", SEGMENTS)
        with c2:
            l_contact = st.text_input("Contact name (optional)")
            l_persona = st.text_input("Contact role")
        with c3:
            l_status = st.selectbox("Status", STATUSES)
            l_score = st.number_input("Fit score (0-100, optional)", min_value=0, max_value=100, value=0)
        l_source = st.text_input("Source")
        l_notes = st.text_input("Notes (optional)")
        submitted_lead = st.form_submit_button("Add lead", use_container_width=True)
        if submitted_lead and l_company:
            new_lead = pd.DataFrame([{
                "date_added": date.today(), "company": l_company, "segment": l_segment,
                "contact_name": l_contact, "contact_persona": l_persona, "status": l_status,
                "fit_score": l_score, "source": l_source, "notes": l_notes,
            }])
            st.session_state.leads = pd.concat([st.session_state.leads, new_lead], ignore_index=True)
            save_table(st.session_state.leads, LEADS_PATH)
            st.success(f"Added {l_company}.")

    st.divider()
    st.subheader("Import leads")
    lead_up = st.file_uploader("Upload leads CSV", type="csv", key="leads_upload")
    if lead_up is not None:
        try:
            imported_leads = pd.read_csv(lead_up)
        except Exception as e:
            st.error(f"Couldn't read that CSV: {e}. Make sure it's not empty and is a valid comma-separated file.")
            imported_leads = None
        name_col = None
        if imported_leads is not None:
            name_col = "company" if "company" in imported_leads.columns else (
                "operator" if "operator" in imported_leads.columns else None)
        if imported_leads is None:
            pass
        elif name_col is None:
            st.error("Couldn't find a 'company' or 'operator' column in this file.")
        else:
            mapped = pd.DataFrame({
                "date_added": date.today(),
                "company": imported_leads[name_col],
                "segment": "Multi-entity operator" if name_col == "operator" else "Freshly-funded startup",
                "contact_name": "",
                "contact_persona": imported_leads.get("suggested_contact", ""),
                "status": "New",
                "fit_score": imported_leads.get("fit_score", 0),
                "source": up.name if (up := lead_up) else "import",
                "notes": imported_leads.get("reasons", ""),
            })
            st.dataframe(mapped.head(), use_container_width=True)
            if st.button("Append these leads"):
                st.session_state.leads = pd.concat([st.session_state.leads, mapped], ignore_index=True)
                save_table(st.session_state.leads, LEADS_PATH)
                st.success(f"Imported {len(mapped)} leads.")
                st.rerun()

    st.divider()
    st.subheader("All leads")
    edited_leads = st.data_editor(
        st.session_state.leads, num_rows="dynamic", use_container_width=True, key="leads_editor",
        column_config={"status": st.column_config.SelectboxColumn(options=STATUSES),
                        "segment": st.column_config.SelectboxColumn(options=SEGMENTS)}
    )
    if st.button("💾 Save changes to leads"):
        st.session_state.leads = edited_leads
        save_table(edited_leads, LEADS_PATH)
        st.success("Saved.")

with tab_dash:
    act = st.session_state.activity.copy()
    leads_df = st.session_state.leads.copy()

    if act.empty and leads_df.empty:
        st.info("No data yet — log some activity or add leads in the other two tabs, and this fills in automatically.")
    else:
        if not act.empty:
            for c in ["sent", "delivered", "opened", "replied", "positive_reply", "meeting_booked"]:
                act[c] = pd.to_numeric(act[c], errors="coerce").fillna(0)

            totals = act[["sent", "delivered", "opened", "replied", "positive_reply", "meeting_booked"]].sum()
            delivered = max(totals["delivered"], 1)
            replied = max(totals["replied"], 1)

            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Sent", int(totals["sent"]))
            col2.metric("Open rate", f"{totals['opened'] / delivered * 100:.0f}%")
            col3.metric("Reply rate", f"{totals['replied'] / delivered * 100:.0f}%")
            col4.metric("Positive reply rate", f"{totals['positive_reply'] / replied * 100:.0f}%" if totals['replied'] else "—")
            col5.metric("Meetings booked", int(totals["meeting_booked"]))

            st.divider()
            left, right = st.columns([2, 1])

            with left:
                st.subheader("Funnel by channel")
                channel_summary = act.groupby("channel")[["sent", "opened", "replied", "meeting_booked"]].sum().reset_index()
                fig = px.bar(channel_summary, x="channel", y=["sent", "opened", "replied", "meeting_booked"],
                             barmode="group", title="Channel performance")
                st.plotly_chart(fig, use_container_width=True)

                if act["date"].notna().any():
                    st.subheader("Meetings booked over time")
                    act["date"] = pd.to_datetime(act["date"], errors="coerce")
                    daily = act.dropna(subset=["date"]).groupby("date")["meeting_booked"].sum().reset_index()
                    fig2 = px.line(daily, x="date", y="meeting_booked", markers=True)
                    st.plotly_chart(fig2, use_container_width=True)

            with right:
                st.subheader("Signals to watch")
                open_rate = totals['opened'] / delivered * 100
                reply_rate = totals['replied'] / delivered * 100
                positive_rate = (totals['positive_reply'] / replied * 100) if totals['replied'] else 0

                if open_rate < 40:
                    st.warning(f"Open rate is {open_rate:.0f}% — below the ~45-55% benchmark for cold B2B email. "
                               "Check subject lines and sender domain reputation before touching the body copy.")
                else:
                    st.success(f"Open rate is {open_rate:.0f}% — healthy.")

                if reply_rate < 8:
                    st.warning(f"Reply rate is {reply_rate:.0f}% — below the ~10-15% target. "
                               "Usually a messaging problem, not a list problem, if opens are fine.")
                else:
                    st.success(f"Reply rate is {reply_rate:.0f}% — the message is resonating.")

                if totals['replied'] > 0 and positive_rate < 40:
                    st.warning(f"Only {positive_rate:.0f}% of replies are positive — check for a targeting "
                               "mismatch vs. a messaging mismatch.")
                elif totals['replied'] > 0:
                    st.success(f"{positive_rate:.0f}% of replies are positive — targeting and message look aligned.")

                if act["step"].notna().any():
                    st.subheader("Drop-off by step")
                    step_summary = act.groupby("step")[["sent", "replied"]].sum()
                    step_summary["reply_rate_%"] = (step_summary["replied"] / step_summary["sent"].replace(0, 1) * 100).round(0)
                    st.dataframe(step_summary, use_container_width=True)
        else:
            st.info("No activity logged yet — add some in the 'Log activity' tab to see funnel metrics here.")

        st.divider()

        if not leads_df.empty:
            st.subheader("🎯 Pipeline")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Total leads", len(leads_df))
            p2.metric("Contacted", (leads_df["status"] == "Contacted").sum())
            p3.metric("Replied", (leads_df["status"] == "Replied").sum())
            p4.metric("Meetings booked", (leads_df["status"] == "Meeting Booked").sum())

            by_segment = leads_df.groupby("segment").size().reset_index(name="count")
            fig3 = px.pie(by_segment, names="segment", values="count", title="Leads by segment")
            st.plotly_chart(fig3, use_container_width=True)

            st.subheader("Lead status board")
            st.dataframe(leads_df.sort_values("fit_score", ascending=False), use_container_width=True, hide_index=True)