"""Automated tests for reminder scheduling and processing module (Phase 7)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
import pandas as pd
import schedule

from src.contact_manager import load_contacts
from src.reminder_manager import load_reminders
from src.scheduler import (
    get_due_reminders,
    process_reminder,
    process_due_reminders,
    register_periodic_job,
    clear_scheduled_jobs,
    reset_processed_reminders,
    get_processed_reminder_ids,
    TIMEZONE,
)


@pytest.fixture(autouse=True)
def clean_scheduler_state():
    """Ensure in-memory tracking and schedule jobs are cleared before each test."""
    clear_scheduled_jobs()
    reset_processed_reminders()
    yield
    clear_scheduled_jobs()
    reset_processed_reminders()


# 1. No reminders are due
def test_get_due_reminders_none_due():
    """Verify that no reminders are returned when current time precedes all scheduled times."""
    reminders_df = load_reminders()
    past_eval_time = datetime(2026, 11, 1, 9, 0, tzinfo=TIMEZONE)
    due_df = get_due_reminders(reminders_df, now=past_eval_time)
    assert len(due_df) == 0


# 2. One reminder is due
def test_get_due_reminders_one_due():
    """Verify exactly one reminder is identified when evaluated right after R001."""
    reminders_df = load_reminders()
    eval_time = datetime(2026, 11, 20, 10, 5, tzinfo=TIMEZONE)
    due_df = get_due_reminders(reminders_df, now=eval_time)
    assert len(due_df) == 1
    assert due_df.iloc[0]["reminder_id"] == "R001"


# 3. Multiple reminders are due
def test_get_due_reminders_multiple_due():
    """Verify multiple reminders are returned when evaluation time is past their schedule."""
    reminders_df = load_reminders()
    # At 2026-11-22 10:00: R001 (Nov 20), R002 (Nov 21), R003 (Nov 22 09:00) are due
    eval_time = datetime(2026, 11, 22, 10, 0, tzinfo=TIMEZONE)
    due_df = get_due_reminders(reminders_df, now=eval_time)
    assert len(due_df) == 3
    assert set(due_df["reminder_id"]) == {"R001", "R002", "R003"}


# 4. Future reminders are excluded
def test_get_due_reminders_future_excluded():
    """Verify that reminders scheduled in the future are strictly excluded."""
    reminders_df = load_reminders()
    # Nov 21 at 12:00: R001 (Nov 20 10:00) is due, but R002 (Nov 21 14:30) is future
    eval_time = datetime(2026, 11, 21, 12, 0, tzinfo=TIMEZONE)
    due_df = get_due_reminders(reminders_df, now=eval_time)
    assert len(due_df) == 1
    assert "R002" not in due_df["reminder_id"].values


# 5. Non-pending reminders are excluded
def test_get_due_reminders_non_pending_excluded():
    """Verify reminders with status other than 'pending' are ignored."""
    data = [
        {"reminder_id": "R101", "contact_id": "C001", "reminder_type": "meeting", "subject": "Due Pending", "reminder_date": "2026-11-20", "reminder_time": "10:00", "status": "pending"},
        {"reminder_id": "R102", "contact_id": "C001", "reminder_type": "meeting", "subject": "Already Sent", "reminder_date": "2026-11-20", "reminder_time": "10:00", "status": "sent"},
        {"reminder_id": "R103", "contact_id": "C001", "reminder_type": "meeting", "subject": "Cancelled", "reminder_date": "2026-11-20", "reminder_time": "10:00", "status": "cancelled"},
    ]
    df = pd.DataFrame(data)
    eval_time = datetime(2026, 11, 20, 11, 0, tzinfo=TIMEZONE)
    due_df = get_due_reminders(df, now=eval_time)
    assert len(due_df) == 1
    assert due_df.iloc[0]["reminder_id"] == "R101"


# 6. Exact scheduled time is considered due
def test_get_due_reminders_exact_time():
    """Verify that evaluating at the exact scheduled timestamp considers the reminder due."""
    reminders_df = load_reminders()
    exact_time = datetime(2026, 11, 20, 10, 0, 0, tzinfo=TIMEZONE)
    due_df = get_due_reminders(reminders_df, now=exact_time)
    assert "R001" in due_df["reminder_id"].values


# 7. Timezone-aware comparisons
def test_get_due_reminders_timezone_aware():
    """Verify that an injected UTC datetime is converted properly to Asia/Kolkata."""
    reminders_df = load_reminders()
    # 2026-11-20 04:30 UTC is exactly 2026-11-20 10:00 Asia/Kolkata (+05:30)
    utc_time = datetime(2026, 11, 20, 4, 30, tzinfo=ZoneInfo("UTC"))
    due_df = get_due_reminders(reminders_df, now=utc_time)
    assert "R001" in due_df["reminder_id"].values


# 8. Naive injected datetime behavior
def test_get_due_reminders_naive_datetime():
    """Verify that an injected naive datetime is interpreted as Asia/Kolkata local time."""
    reminders_df = load_reminders()
    naive_time = datetime(2026, 11, 20, 10, 0)  # Naive
    due_df = get_due_reminders(reminders_df, now=naive_time)
    assert "R001" in due_df["reminder_id"].values


# 9. Successful processing of a reminder
def test_process_reminder_success(tmp_path):
    """Verify processing a single reminder yields status SIMULATED with an output path."""
    contacts_df = load_contacts()
    reminders_df = load_reminders(contacts=contacts_df)
    r001 = reminders_df.iloc[0]

    result = process_reminder(r001, contacts=contacts_df, output_dir=tmp_path)
    assert result["status"] == "SIMULATED"
    assert result["reminder_id"] == "R001"
    assert result["contact_id"] == "C001"
    assert result["output_path"] is not None
    assert Path(result["output_path"]).exists()


# 10. Correct contact is selected
def test_process_reminder_correct_contact(tmp_path):
    """Verify the generated email is addressed to the contact matching the reminder."""
    contacts_df = load_contacts()
    reminders_df = load_reminders(contacts=contacts_df)
    r002 = reminders_df[reminders_df["reminder_id"] == "R002"].iloc[0]  # C002 = Bob Smith

    res = process_reminder(r002, contacts=contacts_df, output_dir=tmp_path)
    eml_file = Path(res["output_path"])
    content = eml_file.read_text(encoding="utf-8")
    assert "To: bob.smith@example.com" in content
    assert "Bob Smith" in content


# 11. Correct reminder template type is used
def test_process_reminder_correct_template(tmp_path):
    """Verify template matching the reminder_type is rendered."""
    contacts_df = load_contacts()
    reminders_df = load_reminders(contacts=contacts_df)
    r_payment = reminders_df[reminders_df["reminder_type"] == "payment"].iloc[0]

    res = process_reminder(r_payment, contacts=contacts_df, output_dir=tmp_path)
    eml_file = Path(res["output_path"])
    content = eml_file.read_text(encoding="utf-8")
    assert "Payment Due Reminder" in content


# 12. Reminder subject is used in the email
def test_process_reminder_subject_used(tmp_path):
    """Verify the subject header in the email matches the reminder subject."""
    contacts_df = load_contacts()
    reminders_df = load_reminders(contacts=contacts_df)
    r001 = reminders_df.iloc[0]

    res = process_reminder(r001, contacts=contacts_df, output_dir=tmp_path)
    eml_file = Path(res["output_path"])
    content = eml_file.read_text(encoding="utf-8")
    assert "Subject: Sprint Planning Sync" in content


# 13. Simulated output is recorded
def test_process_reminder_simulated_output_recorded(tmp_path):
    """Verify .eml file is saved into the specified output directory."""
    contacts_df = load_contacts()
    reminders_df = load_reminders(contacts=contacts_df)
    r001 = reminders_df.iloc[0]

    res = process_reminder(r001, contacts=contacts_df, output_dir=tmp_path)
    saved_files = list(tmp_path.glob("*.eml"))
    assert len(saved_files) == 1
    assert saved_files[0] == Path(res["output_path"])


# 14. Individual processing failures are handled
def test_process_due_reminders_handles_individual_failure(tmp_path):
    """Verify that an invalid reminder does not crash batch processing of valid reminders."""
    contacts_df = load_contacts()
    # Batch containing 1 valid reminder and 1 pointing to a broken type
    data = [
        {"reminder_id": "R1", "contact_id": "C001", "reminder_type": "meeting", "subject": "Valid", "reminder_date": "2026-11-20", "reminder_time": "10:00", "status": "pending"},
        {"reminder_id": "R2", "contact_id": "C001", "reminder_type": "invalid_type", "subject": "Bad Type", "reminder_date": "2026-11-20", "reminder_time": "10:00", "status": "pending"},
    ]
    df = pd.DataFrame(data)
    eval_time = datetime(2026, 11, 20, 11, 0, tzinfo=TIMEZONE)

    results = process_due_reminders(reminders=df, contacts=contacts_df, now=eval_time, output_dir=tmp_path)
    assert len(results) == 2
    assert results[0]["status"] == "SIMULATED"
    assert results[1]["status"] == "FAILED"
    assert "Unsupported reminder type" in results[1]["error"]


# 15. Same reminder is not processed twice during one run
def test_process_due_reminders_duplicate_prevention(tmp_path):
    """Verify that in-memory duplicate tracking skips already-processed reminders on subsequent passes."""
    contacts_df = load_contacts()
    reminders_df = load_reminders(contacts=contacts_df)
    eval_time = datetime(2026, 11, 20, 10, 5, tzinfo=TIMEZONE)

    # First run processes R001
    results_run1 = process_due_reminders(reminders=reminders_df, contacts=contacts_df, now=eval_time, output_dir=tmp_path)
    assert len(results_run1) == 1
    assert results_run1[0]["status"] == "SIMULATED"
    assert "R001" in get_processed_reminder_ids()

    # Second run with same time skips R001
    results_run2 = process_due_reminders(reminders=reminders_df, contacts=contacts_df, now=eval_time, output_dir=tmp_path)
    assert len(results_run2) == 1
    assert results_run2[0]["status"] == "SKIPPED"
    assert "Already processed in current session" in results_run2[0]["error"]


# 16. Original DataFrame remains unchanged
def test_get_due_reminders_leaves_dataframe_unchanged():
    """Verify that filtering due reminders does not alter the source DataFrame."""
    reminders_df = load_reminders()
    original_shape = reminders_df.shape
    eval_time = datetime(2026, 11, 20, 10, 5, tzinfo=TIMEZONE)

    _ = get_due_reminders(reminders_df, now=eval_time)
    assert reminders_df.shape == original_shape


# 17. Invalid or unknown contact references are handled safely
def test_process_reminder_unknown_contact_handled(tmp_path):
    """Verify process_reminder fails gracefully with status FAILED when contact is missing."""
    contacts_df = load_contacts()
    bad_reminder = {
        "reminder_id": "R999",
        "contact_id": "C_NONEXISTENT",
        "reminder_type": "meeting",
        "subject": "Missing Contact Test",
        "reminder_date": "2026-11-20",
        "reminder_time": "10:00",
        "status": "pending",
    }
    res = process_reminder(bad_reminder, contacts=contacts_df, output_dir=tmp_path)
    assert res["status"] == "FAILED"
    assert "Contact with ID 'C_NONEXISTENT' not found" in res["error"]


# 18. Scheduler registration does not execute jobs immediately
def test_register_periodic_job_does_not_execute_immediately():
    """Verify registering a scheduled job does not execute it prematurely."""
    job = register_periodic_job(interval_seconds=60)
    assert job in schedule.get_jobs()
    # No reminders should be recorded in processed set merely by registering
    assert len(get_processed_reminder_ids()) == 0
