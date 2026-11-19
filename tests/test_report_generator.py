"""Automated tests for SQLite reporting & analytics module (Phase 9)."""

import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo
import sqlite3
import pytest

from src.database import (
    init_db,
    claim_reminder_for_processing,
    record_simulation_success,
    record_simulation_failure,
    record_skipped_attempt,
    get_db_connection,
)
from src.report_generator import (
    generate_processing_summary,
    get_detailed_processing_history,
    export_summary_to_csv,
    export_history_to_csv,
    format_summary_console,
    _open_atomic_report_file,
    InvalidDateRangeError,
    TIMEZONE,
)


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """Fixture providing an initialized SQLite database with known sample records."""
    db_file = tmp_path / "reporting_test.db"
    init_db(db_file)

    # Reminder 1: SIMULATED (2 history entries: PROCESSING, SIMULATED)
    r1 = {
        "reminder_id": "R001",
        "contact_id": "C001",
        "reminder_type": "meeting",
        "subject": "Sprint Planning Sync",
    }
    claim_reminder_for_processing(r1, db_path=db_file)
    record_simulation_success("R001", output_path="outputs/r001.eml", db_path=db_file)

    # Reminder 2: FAILED (2 history entries: PROCESSING, FAILED)
    r2 = {
        "reminder_id": "R002",
        "contact_id": "C002",
        "reminder_type": "interview",
        "subject": "Technical Interview",
    }
    claim_reminder_for_processing(r2, db_path=db_file)
    record_simulation_failure("R002", error_message="Template not found", db_path=db_file)

    # Reminder 3: PROCESSING (1 history entry: PROCESSING)
    r3 = {
        "reminder_id": "R003",
        "contact_id": "C003",
        "reminder_type": "payment",
        "subject": "Invoice Reminder",
    }
    claim_reminder_for_processing(r3, db_path=db_file)

    # Record 1 SKIPPED event for R001 (1 history entry: SKIPPED)
    record_skipped_attempt("R001", reason="Duplicate poll cycle skip", db_path=db_file)

    # Total history entries in DB = 2 + 2 + 1 + 1 = 6 entries.
    # Total actual processing attempts (status == 'PROCESSING') = 3 (R1 attempt 1, R2 attempt 1, R3 attempt 1).
    return db_file


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Fixture providing an empty initialized SQLite database."""
    db_file = tmp_path / "empty_test.db"
    init_db(db_file)
    return db_file


# 1. Processing summary count verification with explicit metric definitions
def test_generate_processing_summary_counts(populated_db: Path):
    """Verify aggregated metrics reflect exact database state with distinct definitions."""
    summary = generate_processing_summary(db_path=populated_db)

    assert summary["total_reminders"] == 3
    assert summary["simulated_reminders"] == 1
    assert summary["failed_reminders"] == 1
    assert summary["processing_reminders"] == 1
    assert summary["pending_reminders"] == 0

    # Distinct metrics:
    # 3 actual processing attempts initiated (R001, R002, R003 each claimed once)
    assert summary["total_processing_attempts"] == 3
    # 1 SKIPPED audit event recorded
    assert summary["skipped_events"] == 1
    # 6 total audit log entries across all statuses (PROCESSING x3, SIMULATED x1, FAILED x1, SKIPPED x1)
    assert summary["total_history_events"] == 6
    assert "generated_at" in summary


# 2. Empty database behavior
def test_generate_processing_summary_empty_db(empty_db: Path):
    """Verify summary returns zeros for all counts when database has no records."""
    summary = generate_processing_summary(db_path=empty_db)

    assert summary["total_reminders"] == 0
    assert summary["simulated_reminders"] == 0
    assert summary["failed_reminders"] == 0
    assert summary["pending_reminders"] == 0
    assert summary["processing_reminders"] == 0
    assert summary["total_processing_attempts"] == 0
    assert summary["skipped_events"] == 0
    assert summary["total_history_events"] == 0


# 3. Non-existent database path behavior
def test_generate_processing_summary_nonexistent_db(tmp_path: Path):
    """Verify missing database path is handled gracefully without crashing."""
    missing_db = tmp_path / "does_not_exist.db"
    summary = generate_processing_summary(db_path=missing_db)
    assert summary["total_reminders"] == 0
    assert summary["total_processing_attempts"] == 0


# 4. Detailed history retrieval
def test_get_detailed_processing_history_retrieval(populated_db: Path):
    """Verify retrieval of detailed history audit entries."""
    history = get_detailed_processing_history(db_path=populated_db)
    assert len(history) == 6

    # Verify column presence
    first = history[0]
    assert "history_id" in first
    assert "reminder_id" in first
    assert "attempt_number" in first
    assert "status" in first
    assert "timestamp" in first
    assert "simulated_output_path" in first
    assert "error_message" in first


# 5. Reminder ID filtering in history
def test_get_detailed_processing_history_filter_by_id(populated_db: Path):
    """Verify filtering history by a specific reminder ID."""
    r1_history = get_detailed_processing_history(reminder_id="R001", db_path=populated_db)
    assert len(r1_history) == 3  # PROCESSING, SIMULATED, SKIPPED
    assert all(h["reminder_id"] == "R001" for h in r1_history)

    r2_history = get_detailed_processing_history(reminder_id="R002", db_path=populated_db)
    assert len(r2_history) == 2  # PROCESSING, FAILED
    assert all(h["reminder_id"] == "R002" for h in r2_history)

    unknown_history = get_detailed_processing_history(reminder_id="R999", db_path=populated_db)
    assert len(unknown_history) == 0


# 6. Date-range filtering in history (pure YYYY-MM-DD strings)
def test_get_detailed_processing_history_date_range(tmp_path: Path):
    """Verify filtering history by start_date and end_date."""
    db_file = tmp_path / "date_test.db"
    init_db(db_file)

    with get_db_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO reminder_records (reminder_id, contact_id, reminder_type, subject, status, created_at, updated_at)
            VALUES ('R1', 'C1', 'meeting', 'Subj', 'SIMULATED', '2026-11-01T10:00:00', '2026-11-01T10:00:00')
            """
        )
        cursor.execute(
            """
            INSERT INTO reminder_history (reminder_id, attempt_number, status, timestamp)
            VALUES
                ('R1', 1, 'SIMULATED', '2026-11-10T09:00:00+05:30'),
                ('R1', 2, 'SIMULATED', '2026-11-15T12:00:00+05:30'),
                ('R1', 3, 'SIMULATED', '2026-11-20T18:00:00+05:30')
            """
        )
        conn.commit()

    # Filter Nov 12 to Nov 18 -> matches only Nov 15
    filtered = get_detailed_processing_history(
        start_date="2026-11-12",
        end_date="2026-11-18",
        db_path=db_file,
    )
    assert len(filtered) == 1
    assert "2026-11-15" in filtered[0]["timestamp"]

    # Filter Nov 01 to Nov 25 -> matches all 3
    all_dates = get_detailed_processing_history(
        start_date="2026-11-01",
        end_date="2026-11-25",
        db_path=db_file,
    )
    assert len(all_dates) == 3


# 7. Timezone-aware datetime inputs in date-range filtering
def test_get_detailed_processing_history_timezone_aware_datetime(tmp_path: Path):
    """Verify that timezone-aware UTC datetime inputs are normalized to Asia/Kolkata correctly."""
    db_file = tmp_path / "tz_test.db"
    init_db(db_file)

    # 2026-11-20 10:00:00 IST (+05:30) is 2026-11-20 04:30:00 UTC
    with get_db_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO reminder_records (reminder_id, contact_id, reminder_type, subject, status, created_at, updated_at)
            VALUES ('R1', 'C1', 'meeting', 'Subj', 'SIMULATED', '2026-11-20T10:00:00+05:30', '2026-11-20T10:00:00+05:30')
            """
        )
        cursor.execute(
            """
            INSERT INTO reminder_history (reminder_id, attempt_number, status, timestamp)
            VALUES ('R1', 1, 'SIMULATED', '2026-11-20T10:00:00+05:30')
            """
        )
        conn.commit()

    # Pass UTC datetime boundaries: 04:00 UTC to 05:00 UTC (bounds 09:30 IST to 10:30 IST)
    utc_start = datetime(2026, 11, 20, 4, 0, tzinfo=timezone.utc)
    utc_end = datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc)

    results = get_detailed_processing_history(start_date=utc_start, end_date=utc_end, db_path=db_file)
    assert len(results) == 1
    assert results[0]["reminder_id"] == "R1"


# 8. Invalid date range detection
def test_get_detailed_processing_history_invalid_date_range(populated_db: Path):
    """Verify InvalidDateRangeError is raised when start_date is chronologically after end_date."""
    with pytest.raises(InvalidDateRangeError, match="is after end_date"):
        get_detailed_processing_history(
            start_date="2026-11-25",
            end_date="2026-11-20",
            db_path=populated_db,
        )


# 9. Malformed date string handling
def test_get_detailed_processing_history_malformed_date(populated_db: Path):
    """Verify InvalidDateRangeError is raised on malformed date string."""
    with pytest.raises(InvalidDateRangeError, match="Invalid date format"):
        get_detailed_processing_history(start_date="not-a-date", db_path=populated_db)


# 10. CSV summary report export contents
def test_export_summary_to_csv(populated_db: Path, tmp_path: Path):
    """Verify export_summary_to_csv creates a valid CSV file with expected metrics."""
    reports_out = tmp_path / "reports_out"
    csv_file = export_summary_to_csv(output_dir=reports_out, db_path=populated_db)

    assert csv_file.exists()
    assert csv_file.name.startswith("summary_report_")
    assert csv_file.name.endswith(".csv")

    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        headers = reader[0]
        assert headers == ["Metric", "Value"]

        metrics_dict = {row[0]: row[1] for row in reader[1:]}
        assert metrics_dict["Total Reminders Registered"] == "3"
        assert metrics_dict["Total SIMULATED Reminders"] == "1"
        assert metrics_dict["Total FAILED Reminders"] == "1"
        assert metrics_dict["Total PROCESSING Reminders"] == "1"
        assert metrics_dict["Total Processing Attempts"] == "3"
        assert metrics_dict["Total SKIPPED Events"] == "1"
        assert metrics_dict["Total History Events Logged"] == "6"


# 11. CSV history report export contents
def test_export_history_to_csv(populated_db: Path, tmp_path: Path):
    """Verify export_history_to_csv exports full audit records with headers."""
    reports_out = tmp_path / "reports_out"
    csv_file = export_history_to_csv(output_dir=reports_out, db_path=populated_db)

    assert csv_file.exists()
    assert csv_file.name.startswith("history_report_")
    assert csv_file.name.endswith(".csv")

    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        # Exact match: all 6 history rows exported
        assert len(reader) == 6
        statuses = [r["status"] for r in reader]
        assert statuses == ["PROCESSING", "SIMULATED", "PROCESSING", "FAILED", "PROCESSING", "SKIPPED"]


# 12. Automatic directory creation on CSV export
def test_export_creates_missing_directory(populated_db: Path, tmp_path: Path):
    """Verify reports directory is created automatically if it does not exist."""
    nested_dir = tmp_path / "level1" / "level2" / "reports"
    assert not nested_dir.exists()

    csv_file = export_summary_to_csv(output_dir=nested_dir, db_path=populated_db)
    assert nested_dir.exists()
    assert csv_file.exists()


# 13. Unique filenames and no overwriting — rapid sequential exports
def test_export_unique_filenames_rapid_same_second(populated_db: Path, tmp_path: Path):
    """Verify that multiple rapid exports within the same second never overwrite existing reports."""
    reports_out = tmp_path / "rapid_reports"

    # Export 5 times in rapid succession
    exported_paths = []
    for _ in range(5):
        exported_paths.append(export_summary_to_csv(output_dir=reports_out, db_path=populated_db))

    # All 5 paths must be unique
    assert len(set(exported_paths)) == 5
    # All 5 files must exist on disk simultaneously
    for p in exported_paths:
        assert p.exists()
    assert len(list(reports_out.glob("summary_report_*.csv"))) == 5


# 14. Atomic no-overwrite across concurrent separate processes
def test_export_atomic_concurrent_processes(populated_db: Path, tmp_path: Path):
    """Verify concurrent separate OS processes exporting to the same directory cannot collide or overwrite."""
    shared_out = tmp_path / "concurrent_reports"
    shared_out.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    project_root = Path(__file__).resolve().parent.parent

    # Worker script that exports 1 summary and 1 history report
    worker_code = f"""
import sys
sys.path.insert(0, r"{project_root}")
from src.report_generator import export_summary_to_csv, export_history_to_csv

db = r"{populated_db}"
out = r"{shared_out}"

s = export_summary_to_csv(output_dir=out, db_path=db)
h = export_history_to_csv(output_dir=out, db_path=db)
print("SUCCESS", s.name, h.name)
"""

    # Spawn 4 concurrent worker processes simultaneously
    procs = []
    for _ in range(4):
        p = subprocess.Popen(
            [python, "-c", worker_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(project_root),
        )
        procs.append(p)

    # Wait for all processes to finish
    for p in procs:
        stdout, stderr = p.communicate(timeout=10)
        assert p.returncode == 0, f"Concurrent worker failed: {stderr}"
        assert "SUCCESS" in stdout

    # Verify: 4 workers * 1 summary = exactly 4 distinct summary files
    summary_files = list(shared_out.glob("summary_report_*.csv"))
    assert len(summary_files) == 4

    # Verify: 4 workers * 1 history = exactly 4 distinct history files
    history_files = list(shared_out.glob("history_report_*.csv"))
    assert len(history_files) == 4

    # Verify all files are valid and non-empty
    for sf in summary_files:
        assert sf.stat().st_size > 50
    for hf in history_files:
        assert hf.stat().st_size > 50


# 15. Atomic cleanup on failure: No partial/corrupted files left behind
def test_export_atomic_cleanup_on_failure(tmp_path: Path):
    """Verify that an exception during export cleans up the target file, leaving no partial report."""
    target_dir = tmp_path / "fail_dir"
    target_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(RuntimeError, match="Simulated write crash"):
        with _open_atomic_report_file(target_dir, "test_fail_report") as (file_path, file_obj):
            file_obj.write("Partial data that should be deleted")
            file_obj.flush()
            raise RuntimeError("Simulated write crash")

    # File must not exist on disk after exception
    assert not file_path.exists()
    assert len(list(target_dir.glob("test_fail_report_*.csv"))) == 0


# 16. Read-only guarantee: Database remains unchanged after report generation
def test_database_remains_unchanged_after_reporting(populated_db: Path, tmp_path: Path):
    """Verify that generating summaries and exporting CSVs does not mutate database records."""
    # Read initial state
    with get_db_connection(populated_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT reminder_id, status, updated_at FROM reminder_records ORDER BY reminder_id")
        initial_records = [tuple(row) for row in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) FROM reminder_history")
        initial_history_count = cursor.fetchone()[0]

    # Run all reporting functions
    _ = generate_processing_summary(db_path=populated_db)
    _ = get_detailed_processing_history(db_path=populated_db)
    _ = export_summary_to_csv(output_dir=tmp_path, db_path=populated_db)
    _ = export_history_to_csv(output_dir=tmp_path, db_path=populated_db)

    # Read state after reporting
    with get_db_connection(populated_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT reminder_id, status, updated_at FROM reminder_records ORDER BY reminder_id")
        after_records = [tuple(row) for row in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) FROM reminder_history")
        after_history_count = cursor.fetchone()[0]

    assert initial_records == after_records
    assert initial_history_count == after_history_count


# 17. Console summary formatter output
def test_format_summary_console():
    """Verify text formatting of summary dictionary."""
    sample_summary = {
        "total_reminders": 10,
        "simulated_reminders": 8,
        "failed_reminders": 1,
        "pending_reminders": 1,
        "processing_reminders": 0,
        "total_processing_attempts": 9,
        "skipped_events": 2,
        "total_history_events": 18,
        "generated_at": "2026-11-19T13:00:00+05:30",
    }
    output = format_summary_console(sample_summary)
    assert "SQLite Processing & Analytics Summary" in output
    assert "Total Reminders Registered : 10" in output
    assert "SIMULATED Reminders        : 8" in output
    assert "Total Processing Attempts  : 9" in output
    assert "SKIPPED Audit Events       : 2" in output
    assert "Total History Events Logged: 18" in output
