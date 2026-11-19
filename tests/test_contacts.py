"""Automated tests for contact loading and validation module (Phase 3)."""

from pathlib import Path
import pytest
import pandas as pd

from src.contact_manager import (
    load_contacts,
    get_contact_by_id,
    ContactValidationError,
    ContactNotFoundError,
)


def create_csv(tmp_path: Path, filename: str, content: str) -> Path:
    """Helper to create temporary CSV files for test isolation."""
    file_path = tmp_path / filename
    file_path.write_text(content, encoding="utf-8")
    return file_path


# 1. Successful loading of valid contacts
def test_load_contacts_success():
    """Verify that the official sample contacts.csv loads and validates cleanly."""
    df = load_contacts()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert list(df.columns) == ["contact_id", "name", "email", "department"]
    assert "C001" in df["contact_id"].values
    assert "Alice Johnson" in df["name"].values


# 2. Missing CSV file
def test_load_contacts_missing_file(tmp_path):
    """Verify FileNotFoundError is raised when target CSV file does not exist."""
    nonexistent = tmp_path / "does_not_exist.csv"
    with pytest.raises(FileNotFoundError) as exc_info:
        load_contacts(nonexistent)
    assert "Contacts CSV file not found" in str(exc_info.value)


# 3. Empty CSV file (0 bytes and header-only empty)
def test_load_contacts_empty_file(tmp_path):
    """Verify ContactValidationError is raised for zero-byte or data-empty CSVs."""
    empty_csv = create_csv(tmp_path, "empty.csv", "")
    with pytest.raises(ContactValidationError) as exc_info:
        load_contacts(empty_csv)
    assert "is empty" in str(exc_info.value) or "contains no data" in str(exc_info.value)

    header_only_csv = create_csv(
        tmp_path, "header_only.csv", "contact_id,name,email,department\n"
    )
    with pytest.raises(ContactValidationError) as exc_info:
        load_contacts(header_only_csv)
    assert "is empty" in str(exc_info.value) or "no contact records found" in str(exc_info.value)


# 4. Missing required column
def test_load_contacts_missing_required_column(tmp_path):
    """Verify ContactValidationError is raised when a required column is missing."""
    csv_missing_dept = create_csv(
        tmp_path,
        "missing_dept.csv",
        "contact_id,name,email\nC001,Test User,test@example.com\n",
    )
    with pytest.raises(ContactValidationError) as exc_info:
        load_contacts(csv_missing_dept)
    assert "Missing required contact column" in str(exc_info.value)
    assert "department" in str(exc_info.value)


# 5. Empty contact ID
def test_load_contacts_empty_contact_id(tmp_path):
    """Verify ContactValidationError is raised when contact_id is empty or whitespace."""
    csv_empty_id = create_csv(
        tmp_path,
        "empty_id.csv",
        "contact_id,name,email,department\n,Alice,alice@example.com,Eng\n",
    )
    with pytest.raises(ContactValidationError) as exc_info:
        load_contacts(csv_empty_id)
    assert "Required field 'contact_id' is empty" in str(exc_info.value)


# 6. Empty name
def test_load_contacts_empty_name(tmp_path):
    """Verify ContactValidationError is raised when name is blank."""
    csv_empty_name = create_csv(
        tmp_path,
        "empty_name.csv",
        "contact_id,name,email,department\nC001, ,alice@example.com,Eng\n",
    )
    with pytest.raises(ContactValidationError) as exc_info:
        load_contacts(csv_empty_name)
    assert "Required field 'name' is empty" in str(exc_info.value)


# 7. Empty email
def test_load_contacts_empty_email(tmp_path):
    """Verify ContactValidationError is raised when email is missing."""
    csv_empty_email = create_csv(
        tmp_path,
        "empty_email.csv",
        "contact_id,name,email,department\nC001,Alice Johnson,,Eng\n",
    )
    with pytest.raises(ContactValidationError) as exc_info:
        load_contacts(csv_empty_email)
    assert "Required field 'email' is empty" in str(exc_info.value)


# 8. Empty department
def test_load_contacts_empty_department(tmp_path):
    """Verify ContactValidationError is raised when department is blank."""
    csv_empty_dept = create_csv(
        tmp_path,
        "empty_dept.csv",
        "contact_id,name,email,department\nC001,Alice Johnson,alice@example.com,\n",
    )
    with pytest.raises(ContactValidationError) as exc_info:
        load_contacts(csv_empty_dept)
    assert "Required field 'department' is empty" in str(exc_info.value)


# 9. Duplicate contact IDs
def test_load_contacts_duplicate_contact_ids(tmp_path):
    """Verify ContactValidationError is raised when duplicate contact_id values exist."""
    csv_dup = create_csv(
        tmp_path,
        "dup_ids.csv",
        "contact_id,name,email,department\n"
        "C001,Alice,alice@example.com,Eng\n"
        "C001,Bob,bob@example.com,HR\n",
    )
    with pytest.raises(ContactValidationError) as exc_info:
        load_contacts(csv_dup)
    assert "Duplicate contact_id values found" in str(exc_info.value)
    assert "C001" in str(exc_info.value)


# 10. Invalid email format
def test_load_contacts_invalid_email_format(tmp_path):
    """Verify ContactValidationError is raised when email does not follow standard format."""
    csv_bad_email = create_csv(
        tmp_path,
        "bad_email.csv",
        "contact_id,name,email,department\n"
        "C001,Alice,not_an_email_at_all,Eng\n",
    )
    with pytest.raises(ContactValidationError) as exc_info:
        load_contacts(csv_bad_email)
    assert "Invalid email address 'not_an_email_at_all'" in str(exc_info.value)


# 11. Leading/trailing whitespace handling
def test_load_contacts_whitespace_handling(tmp_path):
    """Verify whitespace is normalized in memory without altering the data integrity."""
    csv_whitespace = create_csv(
        tmp_path,
        "whitespace.csv",
        "contact_id,name,email,department\n"
        "  C100  ,  John Doe  ,  john.doe@example.com  ,  Support  \n",
    )
    df = load_contacts(csv_whitespace)
    record = df.iloc[0]
    assert record["contact_id"] == "C100"
    assert record["name"] == "John Doe"
    assert record["email"] == "john.doe@example.com"
    assert record["department"] == "Support"


# 12. Successful lookup by contact ID
def test_get_contact_by_id_success():
    """Verify contact lookup returns the expected record with and without pre-loaded DataFrame."""
    # Lookup without preloaded DataFrame
    contact = get_contact_by_id("C001")
    assert isinstance(contact, dict)
    assert contact["contact_id"] == "C001"
    assert contact["name"] == "Alice Johnson"
    assert contact["email"] == "alice.johnson@example.com"
    assert contact["department"] == "Engineering"

    # Lookup with preloaded DataFrame
    df = load_contacts()
    contact_c002 = get_contact_by_id("C002", contacts=df)
    assert contact_c002["contact_id"] == "C002"
    assert contact_c002["name"] == "Bob Smith"


# 13. Lookup of a nonexistent contact ID
def test_get_contact_by_id_nonexistent():
    """Verify ContactNotFoundError is raised when searching for a missing contact ID."""
    with pytest.raises(ContactNotFoundError) as exc_info:
        get_contact_by_id("NONEXISTENT_999")
    assert "Contact with ID 'NONEXISTENT_999' not found" in str(exc_info.value)


# 14. Lookup with empty or whitespace contact ID
def test_get_contact_by_id_empty_id():
    """Verify ContactNotFoundError is raised if empty string is supplied as ID."""
    with pytest.raises(ContactNotFoundError) as exc_info:
        get_contact_by_id("   ")
    assert "non-empty contact_id must be provided" in str(exc_info.value)
