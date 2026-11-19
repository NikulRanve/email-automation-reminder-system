"""Streamlit Analytics Dashboard for Email Automation & Reminder System.

Provides an interactive visual interface for real-time monitoring,
KPI metric cards, reminder status distribution, audit history inspection,
and non-destructive CSV report generation & downloading.

Database & Concurrency Policy:
- Reporting and history retrieval are strictly read-only SELECT operations.
- If the SQLite database file does not exist, schema tables and indexes are
  idempotently initialized using init_db().
- The dashboard never claims reminders, never updates processing statuses,
  never dispatches emails, and never runs background scheduling loops.
"""

from datetime import date, datetime
import html
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd
import streamlit as st

# Check for pyarrow availability (native to x86_64; gracefully falls back to matplotlib on ARM64)
try:
    import pyarrow as _pa  # type: ignore # noqa: F401
    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False

if not HAS_PYARROW:
    import matplotlib.pyplot as plt

from src.config import (
    BASE_DIR,
    DB_PATH,
    EMAIL_MODE,
    IS_SIMULATION,
    OUTPUTS_DIR,
    REPORTS_DIR,
    SIMULATED_EMAILS_DIR,
)
from src.database import init_db
from src.report_generator import (
    TIMEZONE,
    export_history_to_csv,
    export_summary_to_csv,
    generate_processing_summary,
    get_detailed_processing_history,
)

# Canonical columns for history table representation
HISTORY_COLUMNS = [
    "history_id",
    "reminder_id",
    "attempt_number",
    "status",
    "timestamp",
    "simulated_output_path",
    "error_message",
]


# ============================================================================
# Modular Data Loading & Transformation Functions (Unit-Testable)
# ============================================================================

def load_summary_metrics(db_path: Optional[Union[Path, str]] = None) -> Dict[str, Any]:
    """Retrieve aggregate processing metrics from SQLite.

    Args:
        db_path: Optional path to SQLite database.

    Returns:
        Dict[str, Any]: Processing summary dictionary.
    """
    return generate_processing_summary(db_path=db_path)


def load_history_data(
    reminder_id: Optional[str] = None,
    start_date: Optional[Union[str, date, datetime]] = None,
    end_date: Optional[Union[str, date, datetime]] = None,
    limit: Optional[int] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> pd.DataFrame:
    """Retrieve audit history and return as a structured pandas DataFrame.

    Args:
        reminder_id: Optional reminder ID filter.
        start_date: Optional start date/datetime filter.
        end_date: Optional end date/datetime filter.
        limit: Optional maximum rows to return.
        db_path: Optional database path.

    Returns:
        pd.DataFrame: Formatted DataFrame with canonical history columns.
    """
    # Clean up empty or "All" reminder_id values
    clean_rid = str(reminder_id).strip() if reminder_id else None
    if clean_rid in ("", "All", "ALL"):
        clean_rid = None

    # Format date objects to strings if needed
    s_date = start_date.isoformat() if isinstance(start_date, (date, datetime)) else start_date
    e_date = end_date.isoformat() if isinstance(end_date, (date, datetime)) else end_date

    records = get_detailed_processing_history(
        reminder_id=clean_rid,
        start_date=s_date,
        end_date=e_date,
        limit=limit,
        db_path=db_path,
    )

    if not records:
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    df = pd.DataFrame(records)
    for col in HISTORY_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[HISTORY_COLUMNS]


def build_status_distribution_df(summary: Dict[str, Any]) -> pd.DataFrame:
    """Construct a DataFrame for current reminder status distribution visualization.

    Args:
        summary: Dictionary returned by generate_processing_summary().

    Returns:
        pd.DataFrame: DataFrame with 'Status' and 'Count' columns.
    """
    statuses = [
        ("SIMULATED", int(summary.get("simulated_reminders", 0))),
        ("FAILED", int(summary.get("failed_reminders", 0))),
        ("PENDING", int(summary.get("pending_reminders", 0))),
        ("PROCESSING", int(summary.get("processing_reminders", 0))),
    ]
    return pd.DataFrame(statuses, columns=["Status", "Count"])


def build_history_status_df(history_df: pd.DataFrame) -> pd.DataFrame:
    """Construct a DataFrame summarizing events in history by status.

    Args:
        history_df: History DataFrame.

    Returns:
        pd.DataFrame: DataFrame with 'Status' and 'Count' columns.
    """
    if history_df.empty or "status" not in history_df.columns:
        return pd.DataFrame(columns=["Status", "Count"])

    counts = history_df["status"].value_counts().reset_index()
    counts.columns = ["Status", "Count"]
    return counts


def build_timeline_df(history_df: pd.DataFrame) -> pd.DataFrame:
    """Construct a DataFrame aggregating event activity over calendar dates.

    Args:
        history_df: History DataFrame with 'timestamp' column.

    Returns:
        pd.DataFrame: DataFrame indexed by Date with an 'Events' count column.
    """
    if history_df.empty or "timestamp" not in history_df.columns:
        return pd.DataFrame(columns=["Date", "Events"]).set_index("Date")

    # Extract date part from ISO timestamps (YYYY-MM-DD)
    dates = history_df["timestamp"].dropna().astype(str).str.slice(0, 10)
    timeline = dates.value_counts().sort_index().reset_index()
    timeline.columns = ["Date", "Events"]
    return timeline.set_index("Date")


def prepare_csv_export(
    export_type: str,
    db_path: Optional[Union[Path, str]] = None,
    reminder_id: Optional[str] = None,
    start_date: Optional[Union[str, date, datetime]] = None,
    end_date: Optional[Union[str, date, datetime]] = None,
) -> Tuple[Path, bytes]:
    """Execute CSV report export and return both the file Path and bytes for downloading.

    Args:
        export_type: 'summary' or 'history'.
        db_path: Optional database path.
        reminder_id: Optional reminder ID for history export.
        start_date: Optional start date for history export.
        end_date: Optional end date for history export.

    Returns:
        Tuple[Path, bytes]: Path to written file and file content bytes.
    """
    if export_type == "summary":
        csv_path = export_summary_to_csv(db_path=db_path)
    elif export_type == "history":
        clean_rid = str(reminder_id).strip() if reminder_id and reminder_id not in ("All", "ALL") else None
        s_date = start_date.isoformat() if isinstance(start_date, (date, datetime)) else start_date
        e_date = end_date.isoformat() if isinstance(end_date, (date, datetime)) else end_date
        csv_path = export_history_to_csv(
            reminder_id=clean_rid,
            start_date=s_date,
            end_date=e_date,
            db_path=db_path,
        )
    else:
        raise ValueError(f"Unknown export_type: '{export_type}'. Expected 'summary' or 'history'.")

    data = csv_path.read_bytes()
    return csv_path, data


# ============================================================================
# Streamlit UI Rendering Functions
# ============================================================================

def render_safety_banner() -> None:
    """Render prominent simulation mode and safety disclosures."""
    st.warning(
        "🛡️ **Simulation Mode Active**: The system is running in **SIMULATION** mode "
        f"(`EMAIL_MODE={EMAIL_MODE}`). Real external email transmission and SMTP connections "
        "are strictly disabled. Generated preview messages are safely written to "
        f"`outputs/simulated_emails/`."
    )


def render_sidebar(db_path: Path) -> None:
    """Render the sidebar with system configuration and operational statuses.

    Args:
        db_path: SQLite database path.
    """
    with st.sidebar:
        st.header("⚙️ System Status")

        # Mode Badge
        if IS_SIMULATION:
            st.success(f"Mode: **{EMAIL_MODE.upper()}** (Safe Preview)")
        else:
            st.error(f"Mode: **{EMAIL_MODE.upper()}**")

        st.markdown("---")
        st.subheader("📂 Infrastructure")

        db_exists = db_path.exists()
        st.markdown(
            f"**SQLite Database:**\n`{db_path.name}` "
            f"({'✅ Found' if db_exists else '⚠️ Not Initialized'})"
        )
        st.caption(f"Path: `{db_path}`")

        reports_exists = REPORTS_DIR.exists()
        st.markdown(
            f"**Reports Directory:** "
            f"({'✅ Ready' if reports_exists else '📁 Will create on export'})"
        )
        st.caption(f"Path: `{REPORTS_DIR}`")

        sim_exists = SIMULATED_EMAILS_DIR.exists()
        st.markdown(
            f"**Simulation Directory:** "
            f"({'✅ Ready' if sim_exists else '📁 Ready'})"
        )
        st.caption(f"Path: `{SIMULATED_EMAILS_DIR}`")

        st.markdown("---")
        st.subheader("🌐 Timezone")
        st.info("System Timezone: **Asia/Kolkata** (IST, UTC+05:30)")

        st.markdown("---")
        st.caption(
            "ℹ️ *Note: The analytics dashboard is read-only. "
            "To run continuous polling, launch `python main.py --schedule` in a separate terminal.*"
        )


def render_overview_section(summary: Dict[str, Any]) -> None:
    """Render Section A: Key Performance Indicator (KPI) metrics cards.

    Args:
        summary: Aggregated metrics dictionary.
    """
    st.subheader("📊 System Overview & Key Metrics")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            label="Total Reminders Registered",
            value=summary.get("total_reminders", 0),
            help="Total distinct reminders registered in SQLite.",
        )
    with col2:
        st.metric(
            label="SIMULATED Emails",
            value=summary.get("simulated_reminders", 0),
            help="Reminders successfully simulated and stored locally as .eml preview files.",
        )
    with col3:
        st.metric(
            label="FAILED Reminders",
            value=summary.get("failed_reminders", 0),
            help="Reminders that encountered errors during simulation.",
        )
    with col4:
        st.metric(
            label="PENDING Reminders",
            value=summary.get("pending_reminders", 0),
            help="Reminders awaiting their scheduled processing time.",
        )

    col5, col6, col7 = st.columns(3)
    with col5:
        st.metric(
            label="PROCESSING Reminders",
            value=summary.get("processing_reminders", 0),
            help="Reminders actively claimed by a worker process.",
        )
    with col6:
        st.metric(
            label="Total Processing Attempts",
            value=summary.get("total_processing_attempts", 0),
            help="Total attempts dispatched across all reminders.",
        )
    with col7:
        st.metric(
            label="Total SKIPPED Events",
            value=summary.get("skipped_events", 0),
            help="Duplicate or ineligible evaluation events skipped safely.",
        )


def render_analytics_section(summary: Dict[str, Any], history_df: pd.DataFrame) -> None:
    """Render Section B: Visual analytics and distribution charts.

    Supports native Streamlit charts when pyarrow is present, with automatic
    matplotlib fallback on platforms where pyarrow is unavailable (such as Windows ARM64).

    Args:
        summary: Summary metrics dictionary.
        history_df: Full or filtered history DataFrame.
    """
    st.subheader("📈 Execution Analytics & Status Distribution")

    if summary.get("total_reminders", 0) == 0 and history_df.empty:
        st.info(
            "ℹ️ No reminder or history records found in database. "
            "Run `python main.py` or `python main.py --schedule` to ingest and process reminders."
        )
        return

    status_df = build_status_distribution_df(summary)
    hist_status_df = build_history_status_df(history_df)
    timeline_df = build_timeline_df(history_df)

    if HAS_PYARROW:
        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown("**Current Reminder State Distribution**")
            st.bar_chart(status_df.set_index("Status"))

        with col_right:
            st.markdown("**Processing History Events by Status**")
            if not hist_status_df.empty:
                st.bar_chart(hist_status_df.set_index("Status"))
            else:
                st.caption("No history events logged yet.")

        st.markdown("**Processing Activity Over Time**")
        if not timeline_df.empty:
            st.line_chart(timeline_df)
        else:
            st.caption("No timeline activity recorded yet.")
    else:
        # Fallback to matplotlib for platforms without pyarrow
        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown("**Current Reminder State Distribution**")
            fig1, ax1 = plt.subplots(figsize=(6, 3.5))
            colors = ["#2e7d32", "#c62828", "#f57f17", "#0277bd"]
            ax1.bar(status_df["Status"], status_df["Count"], color=colors)
            ax1.set_ylabel("Count")
            ax1.set_title("Reminder Current States")
            plt.tight_layout()
            st.pyplot(fig1)
            plt.close(fig1)

        with col_right:
            st.markdown("**Processing History Events by Status**")
            if not hist_status_df.empty:
                fig2, ax2 = plt.subplots(figsize=(6, 3.5))
                ax2.bar(hist_status_df["Status"], hist_status_df["Count"], color="#5c6bc0")
                ax2.set_ylabel("Occurrences")
                ax2.set_title("Audit Events Logged")
                plt.tight_layout()
                st.pyplot(fig2)
                plt.close(fig2)
            else:
                st.caption("No history events logged yet.")

        st.markdown("**Processing Activity Over Time**")
        if not timeline_df.empty:
            fig3, ax3 = plt.subplots(figsize=(10, 3.2))
            ax3.plot(timeline_df.index, timeline_df["Events"], marker="o", color="#00897b", linewidth=2)
            ax3.set_ylabel("Events")
            ax3.set_xlabel("Date")
            ax3.set_title("Timeline Activity")
            plt.xticks(rotation=45)
            plt.tight_layout()
            st.pyplot(fig3)
            plt.close(fig3)
        else:
            st.caption("No timeline activity recorded yet.")


def render_history_section(
    db_path: Path,
    history_df: pd.DataFrame,
) -> None:
    """Render Section C: Searchable and filterable processing history table.

    Uses native st.dataframe when pyarrow is available, or an interactive
    HTML table with styled CSS on platforms where pyarrow is absent.

    Args:
        db_path: SQLite database path.
        history_df: Processed history DataFrame.
    """
    st.subheader("📜 Detailed Processing History & Audit Log")

    total_rows = len(history_df)
    st.caption(f"Showing **{total_rows}** record(s) matching current criteria.")

    if history_df.empty:
        st.info("No processing history entries found matching the specified filters.")
        return

    if HAS_PYARROW:
        st.dataframe(
            history_df,
            use_container_width=True,
            column_config={
                "history_id": st.column_config.NumberColumn("Log ID", width="small"),
                "reminder_id": st.column_config.TextColumn("Reminder ID", width="small"),
                "attempt_number": st.column_config.NumberColumn("Attempt #", width="small"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "timestamp": st.column_config.TextColumn("Timestamp (IST)", width="medium"),
                "simulated_output_path": st.column_config.TextColumn("Simulated Output Path", width="large"),
                "error_message": st.column_config.TextColumn("Diagnostic / Error", width="medium"),
            },
            hide_index=True,
        )
    else:
        # Fallback to HTML table when pyarrow is not installed (e.g. Windows ARM64)
        # Defense-in-depth: explicitly escape all dynamic values against HTML/XSS injection
        sanitized_df = history_df.copy()
        for col in sanitized_df.columns:
            sanitized_df[col] = sanitized_df[col].apply(
                lambda val: html.escape(str(val), quote=True)
                if val is not None and not (isinstance(val, float) and pd.isna(val))
                else "-"
            )
        html_table = sanitized_df.to_html(
            index=False,
            classes="table table-striped table-hover",
            escape=False,
        )
        styled_html = (
            "<style>"
            ".st-history-table table { width: 100%; border-collapse: collapse; font-family: sans-serif; font-size: 0.9em; }"
            ".st-history-table th { background-color: #2b2b36; color: #fff; padding: 8px 12px; text-align: left; }"
            ".st-history-table td { padding: 6px 12px; border-bottom: 1px solid #444; }"
            ".st-history-table tr:hover { background-color: #383848; }"
            "</style>"
            f"<div class='st-history-table'>{html_table}</div>"
        )
        st.markdown(styled_html, unsafe_allow_html=True)


def render_reports_section(
    db_path: Path,
    reminder_id: Optional[str] = None,
    start_date: Optional[Union[str, date]] = None,
    end_date: Optional[Union[str, date]] = None,
) -> None:
    """Render Section D: Report generation and in-browser CSV download triggers.

    Args:
        db_path: SQLite database path.
        reminder_id: Current reminder filter.
        start_date: Current start date filter.
        end_date: Current end date filter.
    """
    st.subheader("📥 Report Generation & CSV Exports")
    st.write(
        "Generate atomic, non-destructive CSV reports into `outputs/reports/` "
        "and download copies directly to your browser."
    )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📊 Processing Summary Report")
        st.caption("Aggregated counts, current states, attempts, and skipped events.")
        if st.button("Generate Summary CSV", key="btn_gen_summary"):
            try:
                target_path, data_bytes = prepare_csv_export("summary", db_path=db_path)
                st.success(f"Report created: `{target_path.name}`")
                st.download_button(
                    label="⬇️ Download Summary CSV",
                    data=data_bytes,
                    file_name=target_path.name,
                    mime="text/csv",
                    key="download_summary_csv",
                )
            except Exception as err:
                st.error(f"Failed to generate summary report: {err}")

    with col2:
        st.markdown("### 📜 Detailed History Audit Report")
        st.caption("Complete chronological record of all processing attempts and events.")
        if st.button("Generate History CSV", key="btn_gen_history"):
            try:
                target_path, data_bytes = prepare_csv_export(
                    "history",
                    db_path=db_path,
                    reminder_id=reminder_id,
                    start_date=start_date,
                    end_date=end_date,
                )
                st.success(f"Report created: `{target_path.name}`")
                st.download_button(
                    label="⬇️ Download History CSV",
                    data=data_bytes,
                    file_name=target_path.name,
                    mime="text/csv",
                    key="download_history_csv",
                )
            except Exception as err:
                st.error(f"Failed to generate history report: {err}")


# ============================================================================
# Main Application Flow
# ============================================================================

def main(db_path: Optional[Union[Path, str]] = None) -> None:
    """Main application routine for Streamlit execution.

    Database & Execution Guarantees:
    - If the SQLite database file does not exist, init_db() is called to ensure
      schema tables and indexes exist.
    - All data loading operations (metrics, history) are strictly read-only SELECT
      queries that never mutate database records.
    - The dashboard does not process reminders, claim records, or start the scheduler.
    """
    st.set_page_config(
        page_title="Email Automation & Reminder System — Analytics",
        page_icon="📧",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    import os
    env_db = os.getenv("DB_PATH")
    if db_path is not None:
        resolved_db = Path(db_path)
    elif env_db:
        resolved_db = Path(env_db)
    else:
        resolved_db = DB_PATH

    # Initialize database if missing (safe idempotent check)
    if not resolved_db.exists():
        init_db(resolved_db)

    # 1. Title & Header
    st.title("📧 Email Automation & Reminder System")
    st.caption(
        "Interactive analytics dashboard, processing summaries, and audit trail viewer. "
        "Built with Streamlit & SQLite."
    )

    # 2. Safety Disclosure Banner
    render_safety_banner()

    # 3. Sidebar Infrastructure Status
    render_sidebar(resolved_db)

    # 4. Global Filters (placed in an expander or container)
    with st.expander("🔍 Filter History & Analytics", expanded=False):
        fcol1, fcol2, fcol3, fcol4 = st.columns(4)
        with fcol1:
            filter_rid = st.text_input(
                "Filter by Reminder ID",
                value="",
                placeholder="e.g. R001, R002",
                help="Leave empty to view all reminders.",
            ).strip()
        with fcol2:
            filter_start = st.date_input("Start Date", value=None)
        with fcol3:
            filter_end = st.date_input("End Date", value=None)
        with fcol4:
            limit_val = st.number_input(
                "Max Records",
                min_value=1,
                max_value=1000,
                value=200,
                step=50,
            )

    # 5. Load Data
    summary = load_summary_metrics(db_path=resolved_db)
    history_df = load_history_data(
        reminder_id=filter_rid if filter_rid else None,
        start_date=filter_start,
        end_date=filter_end,
        limit=int(limit_val) if limit_val else None,
        db_path=resolved_db,
    )

    # 6. Render Dashboard Sections
    render_overview_section(summary)
    st.markdown("---")

    render_analytics_section(summary, history_df)
    st.markdown("---")

    render_history_section(resolved_db, history_df)
    st.markdown("---")

    render_reports_section(
        db_path=resolved_db,
        reminder_id=filter_rid if filter_rid else None,
        start_date=filter_start,
        end_date=filter_end,
    )


if __name__ == "__main__":
    main()
