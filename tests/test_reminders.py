"""Automated tests for reminder loading and validation module (Phase 6)."""

import hashlib
from pathlib import Path
import pytest
import pandas as pd

from src.config import DATA_DIR
from src.contact_manager import load_contacts
from src.reminder_manager import (
    load_reminders,
    validate_reminders_dataframe,
    get_reminders_for_contact,
    ReminderValidationError,
    ReminderNotFoundError,
    REQUIRED_REMINDER_COLUMNS,
)


def create_temp_csv(tmp_path: Path, filename: str, content: str) -> Path:
    """Helper to create temporary CSV files for isolated testing."""
    file_path = tmp_path / filename
    file_path.write_text(content, encoding="utf-8")
    return file_path


# 1. Successful reminder CSV loading
def test_load_reminders_success():
    """Verify that the official sample reminders.csv loads and validates cleanly."""
    df = load_reminders()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert list(df.columns) == REQUIRED_REMINDER_COLUMNS
    assert "R001" in df["reminder_id"].values
    assert "Sprint Planning Sync" in df["subject"].values


# 2. Missing CSV file
def test_load_reminders_missing_file(tmp_path):
    """Verify FileNotFoundError when target CSV file does not exist."""
    missing_file = tmp_path / "nonexistent_reminders.csv"
    with pytest.raises(FileNotFoundError) as exc_info:
        load_reminders(missing_file)
    assert "Reminders CSV file not found" in str(exc_info.value)


# 3. Empty CSV file (0-byte and header-only empty)
def test_load_reminders_empty_file(tmp_path):
    """Verify ReminderValidationError on zero-byte and data-empty CSVs."""
    empty_csv = create_temp_csv(tmp_path, "empty.csv", "")
    with pytest.raises(ReminderValidationError) as exc_info:
        load_reminders(empty_csv)
    assert "is empty" in str(exc_info.value) or "contains no data" in str(exc_info.value)

    header_csv = create_temp_csv(
        tmp_path,
        "header_only.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n",
    )
    with pytest.raises(ReminderValidationError) as exc_info:
        load_reminders(header_csv)
    assert "is empty" in str(exc_info.value) or "no reminder records found" in str(exc_info.value)


# 4. Missing required column
def test_load_reminders_missing_required_column(tmp_path):
    """Verify ReminderValidationError when a required column is missing."""
    csv_missing_subject = create_temp_csv(
        tmp_path,
        "missing_col.csv",
        "reminder_id,contact_id,reminder_type,reminder_date,reminder_time,status\n"
        "R001,C001,meeting,2026-11-20,10:00,pending\n",
    )
    with pytest.raises(ReminderValidationError) as exc_info:
        load_reminders(csv_missing_subject)
    assert "Missing required reminder column" in str(exc_info.value)
    assert "subject" in str(exc_info.value)


# 5. Empty required field
def test_load_reminders_empty_required_field(tmp_path):
    """Verify ReminderValidationError when any required field has empty/whitespace values."""
    csv_empty_subject = create_temp_csv(
        tmp_path,
        "empty_subject.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C001,meeting, ,2026-11-20,10:00,pending\n",
    )
    with pytest.raises(ReminderValidationError) as exc_info:
        load_reminders(csv_empty_subject)
    assert "Required field 'subject' is empty" in str(exc_info.value)


# 6. Duplicate reminder ID
def test_load_reminders_duplicate_reminder_id(tmp_path):
    """Verify ReminderValidationError when duplicate reminder_id values exist."""
    csv_dup = create_temp_csv(
        tmp_path,
        "dup_ids.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C001,meeting,First Sync,2026-11-20,10:00,pending\n"
        "R001,C002,interview,Second Sync,2026-11-21,11:00,pending\n",
    )
    with pytest.raises(ReminderValidationError) as exc_info:
        load_reminders(csv_dup)
    assert "Duplicate reminder_id values found" in str(exc_info.value)
    assert "R001" in str(exc_info.value)


# 7. Invalid reminder type
def test_load_reminders_invalid_reminder_type(tmp_path):
    """Verify ReminderValidationError when reminder_type is not one of the supported 4 types."""
    csv_bad_type = create_temp_csv(
        tmp_path,
        "bad_type.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C001,conference,Tech Conference,2026-11-20,10:00,pending\n",
    )
    with pytest.raises(ReminderValidationError) as exc_info:
        load_reminders(csv_bad_type)
    assert "Unsupported reminder_type 'conference'" in str(exc_info.value)


# 8. Valid reminder types
def test_load_reminders_valid_reminder_types(tmp_path):
    """Verify that all four supported types (interview, meeting, payment, webinar) pass."""
    csv_all_types = create_temp_csv(
        tmp_path,
        "all_types.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C001,interview,Dev Interview,2026-11-20,10:00,pending\n"
        "R002,C002,meeting,Team Sync,2026-11-21,11:00,pending\n"
        "R003,C003,payment,Invoice Due,2026-11-22,12:00,pending\n"
        "R004,C004,webinar,Cloud Webinar,2026-11-23,13:00,pending\n",
    )
    df = load_reminders(csv_all_types)
    assert len(df) == 4
    assert set(df["reminder_type"].unique()) == {"interview", "meeting", "payment", "webinar"}


# 9. Invalid date
def test_load_reminders_invalid_date(tmp_path):
    """Verify ReminderValidationError on invalid calendar dates or wrong date formats."""
    # Invalid date (Feb 30)
    csv_bad_date = create_temp_csv(
        tmp_path,
        "bad_date.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C001,meeting,Sprint,2026-02-30,10:00,pending\n",
    )
    with pytest.raises(ReminderValidationError) as exc_info:
        load_reminders(csv_bad_date)
    assert "Invalid date '2026-02-30'" in str(exc_info.value)

    # Wrong date format (MM/DD/YYYY)
    csv_slash_date = create_temp_csv(
        tmp_path,
        "slash_date.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C001,meeting,Sprint,11/20/2026,10:00,pending\n",
    )
    with pytest.raises(ReminderValidationError) as exc_slash:
        load_reminders(csv_slash_date)
    assert "Expected valid calendar date in YYYY-MM-DD format" in str(exc_slash.value)


# 10. Invalid time
def test_load_reminders_invalid_time(tmp_path):
    """Verify ReminderValidationError on invalid time formats or out-of-range times."""
    csv_bad_time = create_temp_csv(
        tmp_path,
        "bad_time.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C001,meeting,Sprint,2026-11-20,25:00,pending\n",
    )
    with pytest.raises(ReminderValidationError) as exc_info:
        load_reminders(csv_bad_time)
    assert "Invalid time '25:00'" in str(exc_info.value)

    csv_bad_min = create_temp_csv(
        tmp_path,
        "bad_min.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C001,meeting,Sprint,2026-11-20,10:99,pending\n",
    )
    with pytest.raises(ReminderValidationError) as exc_min:
        load_reminders(csv_bad_min)
    assert "Invalid time '10:99'" in str(exc_min.value)


# 11. Whitespace normalization
def test_load_reminders_whitespace_normalization(tmp_path):
    """Verify leading and trailing whitespace in all fields is stripped in memory."""
    csv_whitespace = create_temp_csv(
        tmp_path,
        "whitespace.csv",
        "  reminder_id , contact_id , reminder_type , subject , reminder_date , reminder_time , status  \n"
        "  R100  ,  C001  ,  meeting  ,  Quarterly Review  ,  2026-11-25  ,  14:00  ,  pending  \n",
    )
    df = load_reminders(csv_whitespace)
    rec = df.iloc[0]
    assert rec["reminder_id"] == "R100"
    assert rec["contact_id"] == "C001"
    assert rec["reminder_type"] == "meeting"
    assert rec["subject"] == "Quarterly Review"
    assert rec["reminder_date"] == "2026-11-25"
    assert rec["reminder_time"] == "14:00"
    assert rec["status"] == "pending"


# 12. Successful contact-reference validation
def test_validate_contact_references_success():
    """Verify that reminders referencing valid contacts pass referential integrity checks."""
    contacts_df = load_contacts()
    reminders_df = load_reminders(contacts=contacts_df)
    assert len(reminders_df) == 5
    # Every contact_id in reminders exists in contacts
    known_cids = set(contacts_df["contact_id"])
    assert all(cid in known_cids for cid in reminders_df["contact_id"])


# 13. Unknown contact-reference rejection
def test_validate_contact_references_unknown_contact(tmp_path):
    """Verify ReminderValidationError when a reminder references a nonexistent contact_id."""
    contacts_df = load_contacts()
    csv_orphan = create_temp_csv(
        tmp_path,
        "orphan.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C999,meeting,Sync,2026-11-20,10:00,pending\n",
    )
    with pytest.raises(ReminderValidationError) as exc_info:
        load_reminders(csv_orphan, contacts=contacts_df)
    assert "Referenced contact_id 'C999' does not exist in contacts dataset" in str(exc_info.value)


# 14. Successful retrieval of reminders for a contact
def test_get_reminders_for_contact_success():
    """Verify retrieving reminders matching a given contact_id."""
    contacts_df = load_contacts()
    reminders_df = load_reminders(contacts=contacts_df)

    # Contact C001 has reminder R001
    c001_rems = get_reminders_for_contact("C001", reminders=reminders_df, contacts=contacts_df)
    assert isinstance(c001_rems, pd.DataFrame)
    assert len(c001_rems) == 1
    assert c001_rems.iloc[0]["reminder_id"] == "R001"
    assert c001_rems.iloc[0]["subject"] == "Sprint Planning Sync"


# 15. Contact with no reminders returns an empty DataFrame
def test_get_reminders_for_contact_no_reminders(tmp_path):
    """Verify returning an empty DataFrame when a contact exists but has 0 associated reminders."""
    # Create reminders dataset without C002
    csv_no_c002 = create_temp_csv(
        tmp_path,
        "no_c002.csv",
        "reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status\n"
        "R001,C001,meeting,Sync,2026-11-20,10:00,pending\n",
    )
    contacts_df = load_contacts()
    reminders_df = load_reminders(csv_no_c002, contacts=contacts_df)

    res = get_reminders_for_contact("C002", reminders=reminders_df, contacts=contacts_df)
    assert isinstance(res, pd.DataFrame)
    assert len(res) == 0
    assert list(res.columns) == REQUIRED_REMINDER_COLUMNS


# 16. Empty contact ID rejection
def test_get_reminders_for_contact_empty_id():
    """Verify ReminderValidationError when empty or whitespace contact_id is provided."""
    with pytest.raises(ReminderValidationError) as exc_info:
        get_reminders_for_contact("")
    assert "non-empty contact_id must be provided" in str(exc_info.value)

    with pytest.raises(ReminderValidationError):
        get_reminders_for_contact("   ")


# 17. Unknown contact ID raises ReminderNotFoundError when contacts DataFrame is supplied
def test_get_reminders_for_contact_unknown_contact():
    """Verify ReminderNotFoundError when querying reminders for a contact not in contacts dataset."""
    contacts_df = load_contacts()
    with pytest.raises(ReminderNotFoundError) as exc_info:
        get_reminders_for_contact("C_DOES_NOT_EXIST", contacts=contacts_df)
    assert "Contact ID 'C_DOES_NOT_EXIST' not found in contacts dataset" in str(exc_info.value)


# 18. Original reminders.csv remains unchanged
def test_original_reminders_csv_remains_unchanged():
    """Verify that loading and querying reminders does not alter the physical CSV file."""
    reminders_file = DATA_DIR / "reminders.csv"
    hash_before = hashlib.sha256(reminders_file.read_bytes()).hexdigest()

    # Perform loads, validations, and lookups
    contacts_df = load_contacts()
    reminders_df = load_reminders(contacts=contacts_df)
    for cid in ["C001", "C002", "C003"]:
        _ = get_reminders_for_contact(cid, reminders=reminders_df, contacts=contacts_df)

    hash_after = hashlib.sha256(reminders_file.read_bytes()).hexdigest()
    assert hash_before == hash_after, "data/reminders.csv was modified!"
