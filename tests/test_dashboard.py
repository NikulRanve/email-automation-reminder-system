"""Automated test suite for Streamlit Analytics Dashboard (Phase 10).

Validates dashboard component imports, empty and populated database handling,
history filtering logic, visualization data transformations, atomic CSV export
preparation, and full in-memory AppTest simulation without opening external ports.
"""

from datetime import datetime
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import Generator
from zoneinfo import ZoneInfo
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import app
from src.database import (
    claim_reminder_for_processing,
    init_db,
    record_simulation_failure,
    record_simulation_success,
    record_skipped_attempt,
)
from src.report_generator import InvalidDateRangeError

TIMEZONE = ZoneInfo("Asia/Kolkata")
APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Fixture providing an initialized temporary SQLite database path."""
    db_file = tmp_path / "test_dashboard.db"
    init_db(db_file)
    return db_file


@pytest.fixture
def populated_db(temp_db: Path) -> Path:
    """Fixture providing a temporary SQLite database with known reminder & history rows."""
    # Insert 3 reminders
    r1 = {
        "reminder_id": "R001",
        "contact_id": "C001",
        "reminder_type": "meeting",
        "subject": "Sprint Planning Sync",
    }
    r2 = {
        "reminder_id": "R002",
        "contact_id": "C002",
        "reminder_type": "interview",
        "subject": "Technical Interview",
    }
    r3 = {
        "reminder_id": "R003",
        "contact_id": "C003",
        "reminder_type": "payment",
        "subject": "Invoice Reminder",
    }

    # R001: Claim -> Success (SIMULATED)
    claim_reminder_for_processing(r1, db_path=temp_db)
    record_simulation_success(
        "R001",
        output_path="outputs/simulated_emails/R001.eml",
        db_path=temp_db,
    )

    # R002: Claim -> Failure (FAILED)
    claim_reminder_for_processing(r2, db_path=temp_db)
    record_simulation_failure(
        "R002",
        error_message="Simulated rendering failure",
        db_path=temp_db,
    )

    # R003: Insert directly in PENDING state
    now_iso = datetime.now(TIMEZONE).isoformat()
    with sqlite3.connect(str(temp_db)) as conn:
        conn.execute(
            """
            INSERT INTO reminder_records (
                reminder_id, contact_id, reminder_type, subject,
                status, attempt_count, created_at, updated_at
            ) VALUES ('R003', 'C003', 'payment', 'Invoice Reminder',
                      'PENDING', 0, ?, ?)
            """,
            (now_iso, now_iso),
        )

    # Add a SKIPPED event for R001
    record_skipped_attempt(
        "R001",
        reason="Already successfully simulated (duplicate)",
        db_path=temp_db,
    )

    return temp_db


# ============================================================================
# 1. Module Structure and Import Tests
# ============================================================================

def test_dashboard_imports_and_exports() -> None:
    """Verify that app.py exports all required functions and canonical columns."""
    assert hasattr(app, "HISTORY_COLUMNS")
    assert isinstance(app.HISTORY_COLUMNS, list)
    assert "reminder_id" in app.HISTORY_COLUMNS
    assert "status" in app.HISTORY_COLUMNS

    assert callable(app.load_summary_metrics)
    assert callable(app.load_history_data)
    assert callable(app.build_status_distribution_df)
    assert callable(app.build_history_status_df)
    assert callable(app.build_timeline_df)
    assert callable(app.prepare_csv_export)
    assert callable(app.main)


# ============================================================================
# 2. Empty Database Behavior
# ============================================================================

def test_empty_database_summary_metrics(temp_db: Path) -> None:
    """Verify summary metrics on an empty database return zeros without errors."""
    summary = app.load_summary_metrics(db_path=temp_db)
    assert summary["total_reminders"] == 0
    assert summary["simulated_reminders"] == 0
    assert summary["failed_reminders"] == 0
    assert summary["pending_reminders"] == 0
    assert summary["processing_reminders"] == 0
    assert summary["total_processing_attempts"] == 0
    assert summary["skipped_events"] == 0
    assert summary["total_history_events"] == 0
    assert "generated_at" in summary


def test_empty_database_history_dataframe(temp_db: Path) -> None:
    """Verify history loading on an empty database yields an empty DataFrame with schema."""
    df = app.load_history_data(db_path=temp_db)
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert list(df.columns) == app.HISTORY_COLUMNS


# ============================================================================
# 3. Populated Database and Metric Loading
# ============================================================================

def test_populated_database_summary_metrics(populated_db: Path) -> None:
    """Verify summary metrics aggregate properly from populated database."""
    summary = app.load_summary_metrics(db_path=populated_db)
    assert summary["total_reminders"] == 3
    assert summary["simulated_reminders"] == 1
    assert summary["failed_reminders"] == 1
    assert summary["pending_reminders"] == 1
    assert summary["processing_reminders"] == 0
    assert summary["total_processing_attempts"] == 2  # R001 and R002 both had 1 PROCESSING attempt
    assert summary["skipped_events"] == 1             # 1 SKIPPED event for R001
    assert summary["total_history_events"] == 5        # 2 PROCESSING + 1 SIMULATED + 1 FAILED + 1 SKIPPED


def test_populated_database_history_dataframe(populated_db: Path) -> None:
    """Verify full history dataframe loads all history records."""
    df = app.load_history_data(db_path=populated_db)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert set(df["reminder_id"].unique()) == {"R001", "R002"}


# ============================================================================
# 4. History Filtering Logic
# ============================================================================

def test_history_filtering_by_reminder_id(populated_db: Path) -> None:
    """Verify history filtering restricts records to a specific reminder ID."""
    df_r1 = app.load_history_data(reminder_id="R001", db_path=populated_db)
    assert len(df_r1) == 3
    assert (df_r1["reminder_id"] == "R001").all()

    df_r2 = app.load_history_data(reminder_id="R002", db_path=populated_db)
    assert len(df_r2) == 2
    assert (df_r2["reminder_id"] == "R002").all()

    # 'All' or empty string loads all
    df_all = app.load_history_data(reminder_id="All", db_path=populated_db)
    assert len(df_all) == 5


def test_history_filtering_by_date_range(populated_db: Path) -> None:
    """Verify date range filtering works with date objects and date strings."""
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    df = app.load_history_data(start_date=today, end_date=today, db_path=populated_db)
    assert len(df) == 5

    # Past date with no records
    df_past = app.load_history_data(start_date="2020-01-01", end_date="2020-01-02", db_path=populated_db)
    assert df_past.empty


def test_history_filtering_invalid_date_range(populated_db: Path) -> None:
    """Verify invalid date range (start > end) raises InvalidDateRangeError."""
    with pytest.raises(InvalidDateRangeError):
        app.load_history_data(start_date="2026-12-31", end_date="2026-01-01", db_path=populated_db)


# ============================================================================
# 5. Visualization Transformations
# ============================================================================

def test_build_status_distribution_df(populated_db: Path) -> None:
    """Verify status distribution dataframe format."""
    summary = app.load_summary_metrics(db_path=populated_db)
    df = app.build_status_distribution_df(summary)
    assert list(df.columns) == ["Status", "Count"]
    assert len(df) == 4
    counts = dict(zip(df["Status"], df["Count"]))
    assert counts["SIMULATED"] == 1
    assert counts["FAILED"] == 1
    assert counts["PENDING"] == 1
    assert counts["PROCESSING"] == 0


def test_build_history_status_df(populated_db: Path) -> None:
    """Verify history status distribution aggregation."""
    history_df = app.load_history_data(db_path=populated_db)
    df = app.build_history_status_df(history_df)
    assert list(df.columns) == ["Status", "Count"]
    status_counts = dict(zip(df["Status"], df["Count"]))
    assert status_counts.get("PROCESSING") == 2
    assert status_counts.get("SIMULATED") == 1
    assert status_counts.get("FAILED") == 1
    assert status_counts.get("SKIPPED") == 1


def test_build_timeline_df(populated_db: Path) -> None:
    """Verify event activity timeline generation."""
    history_df = app.load_history_data(db_path=populated_db)
    df = app.build_timeline_df(history_df)
    assert "Events" in df.columns
    assert df.index.name == "Date"
    assert df["Events"].sum() == 5

    # Empty history handles gracefully
    empty_timeline = app.build_timeline_df(pd.DataFrame(columns=app.HISTORY_COLUMNS))
    assert empty_timeline.empty


# ============================================================================
# 6. CSV Report Preparation & Download Data
# ============================================================================

def test_prepare_csv_export_summary(populated_db: Path, tmp_path: Path) -> None:
    """Verify summary CSV export generation and byte payload retrieval."""
    csv_path, csv_bytes = app.prepare_csv_export("summary", db_path=populated_db)
    assert csv_path.exists()
    assert csv_path.suffix == ".csv"
    assert len(csv_bytes) > 0
    content = csv_bytes.decode("utf-8")
    assert "Total Reminders Registered,3" in content
    assert "Total SIMULATED Reminders,1" in content


def test_prepare_csv_export_history(populated_db: Path) -> None:
    """Verify history CSV export generation and byte payload retrieval."""
    csv_path, csv_bytes = app.prepare_csv_export("history", db_path=populated_db)
    assert csv_path.exists()
    assert csv_path.suffix == ".csv"
    assert len(csv_bytes) > 0
    content = csv_bytes.decode("utf-8")
    assert "history_id,reminder_id,attempt_number,status,timestamp" in content
    assert "R001" in content
    assert "R002" in content


def test_prepare_csv_export_invalid_type(populated_db: Path) -> None:
    """Verify unknown export type raises ValueError."""
    with pytest.raises(ValueError, match="Unknown export_type"):
        app.prepare_csv_export("unknown_type", db_path=populated_db)


# ============================================================================
# 7. End-to-End Streamlit AppTest Execution (In-Memory, No Port Binding)
# ============================================================================

def test_apptest_renders_dashboard_sections(monkeypatch: pytest.MonkeyPatch, populated_db: Path) -> None:
    """Test full Streamlit app lifecycle using native AppTest without launching a web server."""
    monkeypatch.setenv("DB_PATH", str(populated_db))

    at = AppTest.from_file(APP_PATH)
    at.run()

    # 1. Main Title
    assert len(at.title) >= 1
    assert "Email Automation & Reminder System" in at.title[0].value

    # 2. Safety Warning Banner
    assert len(at.warning) >= 1
    assert "Simulation Mode Active" in at.warning[0].value

    # 3. Subheaders
    subheaders = [s.value for s in at.subheader]
    assert any("Overview" in s for s in subheaders)
    assert any("Analytics" in s for s in subheaders)
    assert any("History" in s for s in subheaders)
    assert any("Report" in s for s in subheaders)

    # 4. KPI Metrics
    metrics_dict = {m.label: m.value for m in at.metric}
    assert "Total Reminders Registered" in metrics_dict
    assert metrics_dict["Total Reminders Registered"] == "3"
    assert metrics_dict["SIMULATED Emails"] == "1"
    assert metrics_dict["FAILED Reminders"] == "1"
    assert metrics_dict["PENDING Reminders"] == "1"
    assert metrics_dict["PROCESSING Reminders"] == "0"
    assert metrics_dict["Total Processing Attempts"] == "2"
    assert metrics_dict["Total SKIPPED Events"] == "1"


def test_apptest_button_triggers(monkeypatch: pytest.MonkeyPatch, populated_db: Path) -> None:
    """Verify clicking export buttons reveals download buttons in AppTest."""
    monkeypatch.setenv("DB_PATH", str(populated_db))

    at = AppTest.from_file(APP_PATH)
    at.run()

    # Find and click summary generation button
    summary_btn = at.button(key="btn_gen_summary")
    summary_btn.click().run()

    # Verify download button rendered
    download_buttons = [b.label for b in at.download_button]
    assert any("Download Summary CSV" in label for label in download_buttons)


# ============================================================================
# 8. CLI Compatibility Regression Check
# ============================================================================

def test_cli_compatibility_with_app_file_present() -> None:
    """Confirm main.py CLI functions identically when app.py exists."""
    python_exe = sys.executable

    # Test main.py --report
    res_report = subprocess.run(
        [python_exe, "main.py", "--report"],
        capture_output=True,
        text=True,
    )
    assert res_report.returncode == 0
    assert "SQLite Processing & Analytics Summary" in res_report.stdout

    # Test main.py --export-csv
    res_export = subprocess.run(
        [python_exe, "main.py", "--export-csv"],
        capture_output=True,
        text=True,
    )
    assert res_export.returncode == 0
    assert "Reports successfully exported to CSV" in res_export.stdout


# ============================================================================
# 9. HTML Escaping & Injection Defense Test
# ============================================================================

def test_history_html_rendering_escapes_malicious_content(monkeypatch: pytest.MonkeyPatch, temp_db: Path) -> None:
    """Verify dynamic values in history records are strictly escaped against HTML/XSS injection."""
    malicious_id = "<script>alert('xss')</script>"
    malicious_error = "<img src=x onerror=alert(1)>"

    now_iso = datetime.now(TIMEZONE).isoformat()
    with sqlite3.connect(str(temp_db)) as conn:
        conn.execute(
            """
            INSERT INTO reminder_records (
                reminder_id, contact_id, reminder_type, subject,
                status, attempt_count, created_at, updated_at
            ) VALUES (?, 'C001', 'meeting', 'Malicious Payload Test', 'FAILED', 1, ?, ?)
            """,
            (malicious_id, now_iso, now_iso),
        )
        conn.execute(
            """
            INSERT INTO reminder_history (
                reminder_id, attempt_number, status, error_message, timestamp
            ) VALUES (?, 1, 'FAILED', ?, ?)
            """,
            (malicious_id, malicious_error, now_iso),
        )

    monkeypatch.setenv("DB_PATH", str(temp_db))
    at = AppTest.from_file(APP_PATH)
    at.run()

    # Verify no raw unescaped HTML tags were rendered in any markdown elements
    all_markdown = " ".join(m.value for m in at.markdown)
    assert "<script>" not in all_markdown
    assert "<img src=x onerror=alert(1)>" not in all_markdown

    # If rendered via HTML table fallback, verify the escaped entities appear
    if not app.HAS_PYARROW:
        assert "&lt;script&gt;" in all_markdown
        assert "&lt;img" in all_markdown
