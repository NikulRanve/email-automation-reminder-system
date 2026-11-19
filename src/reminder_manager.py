"""Reminder manager module for Email Automation & Reminder System.

Responsible for loading, validating, and filtering scheduled reminder records from CSV sources,
verifying referential integrity against contacts, and ensuring date/time validity.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set
import pandas as pd

from src.config import DATA_DIR
from src.contact_manager import load_contacts

# Exact required columns matching data/reminders.csv schema
REQUIRED_REMINDER_COLUMNS: List[str] = [
    "reminder_id",
    "contact_id",
    "reminder_type",
    "subject",
    "reminder_date",
    "reminder_time",
    "status",
]

# Supported reminder types corresponding to template system
SUPPORTED_REMINDER_TYPES: Set[str] = {
    "interview",
    "meeting",
    "payment",
    "webinar",
}

# Recognized lifecycle statuses
ALLOWED_REMINDER_STATUSES: Set[str] = {
    "pending",
    "sent",
    "dispatched",
    "failed",
    "cancelled",
}


class ReminderError(Exception):
    """Base exception for reminder management errors."""
    pass


class ReminderValidationError(ReminderError, ValueError):
    """Raised when reminder data fails structural, schema, or value validation."""
    pass


class ReminderNotFoundError(ReminderError, KeyError):
    """Raised when a queried reminder or associated contact cannot be found."""
    pass


def _validate_date_string(date_str: str) -> str:
    """Validate that date_str conforms to ISO YYYY-MM-DD calendar date format.

    Args:
        date_str: Date string to validate.

    Returns:
        str: Validated date in YYYY-MM-DD format.

    Raises:
        ValueError: If string cannot be parsed as a valid calendar date.
    """
    clean_date = date_str.strip()
    try:
        parsed_dt = datetime.strptime(clean_date, "%Y-%m-%d")
        return parsed_dt.strftime("%Y-%m-%d")
    except ValueError as err:
        raise ValueError(
            f"Invalid date '{date_str}'. Expected valid calendar date in YYYY-MM-DD format (e.g. 2026-11-20)."
        ) from err


def _validate_time_string(time_str: str) -> str:
    """Validate that time_str conforms to 24-hour time format (HH:MM or HH:MM:SS).

    Args:
        time_str: Time string to validate.

    Returns:
        str: Validated time string.

    Raises:
        ValueError: If string cannot be parsed as a valid 24-hour time.
    """
    clean_time = time_str.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed_tm = datetime.strptime(clean_time, fmt)
            return parsed_tm.strftime("%H:%M")
        except ValueError:
            continue
    raise ValueError(
        f"Invalid time '{time_str}'. Expected 24-hour time format HH:MM or HH:MM:SS (e.g. 14:30)."
    )


def validate_reminders_dataframe(
    df: pd.DataFrame,
    contacts: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Validate and normalize a reminders DataFrame.

    Checks:
    - Presence of required schema columns.
    - Non-empty dataset.
    - Trims leading/trailing whitespace across all string columns in memory.
    - Non-empty values for required fields in each row.
    - Uniqueness of reminder_id.
    - Validity of reminder_type against supported types.
    - Correct calendar date format (YYYY-MM-DD).
    - Correct 24-hour time format (HH:MM or HH:MM:SS).
    - Allowed status values.
    - Referential integrity of contact_id against contacts DataFrame, if supplied.

    Args:
        df: Input pandas DataFrame loaded from reminders CSV.
        contacts: Optional validated contacts DataFrame to verify foreign keys.

    Returns:
        pd.DataFrame: Cleaned, validated reminders DataFrame.

    Raises:
        ReminderValidationError: If any structural or value check fails.
    """
    if df.empty:
        raise ReminderValidationError("Reminders dataset is empty; no reminder records found.")

    # Normalize column names
    df.columns = [str(col).strip() for col in df.columns]

    # 1. Verify required columns exist
    missing_columns = [col for col in REQUIRED_REMINDER_COLUMNS if col not in df.columns]
    if missing_columns:
        raise ReminderValidationError(
            f"Missing required reminder column(s): {missing_columns}. "
            f"Expected schema: {REQUIRED_REMINDER_COLUMNS}"
        )

    # Work on a copy to avoid mutating external references
    validated_df = df.copy()

    # 2. Normalize whitespace across all fields in memory
    for col in REQUIRED_REMINDER_COLUMNS:
        validated_df[col] = (
            validated_df[col]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # 3. Check for empty values in required fields per record
    for idx, row in validated_df.iterrows():
        csv_row_num = idx + 2 if isinstance(idx, int) else idx
        for col in REQUIRED_REMINDER_COLUMNS:
            val = row[col]
            if not val:
                rid = row["reminder_id"] if row["reminder_id"] else f"row {csv_row_num}"
                raise ReminderValidationError(
                    f"Row {csv_row_num} (reminder: '{rid}'): Required field '{col}' is empty."
                )

    # 4. Validate unique reminder_id values
    duplicated_mask = validated_df["reminder_id"].duplicated(keep=False)
    if duplicated_mask.any():
        duplicate_ids = validated_df.loc[duplicated_mask, "reminder_id"].unique().tolist()
        raise ReminderValidationError(
            f"Duplicate reminder_id values found: {duplicate_ids}. Reminder IDs must be unique."
        )

    # 5. Validate reminder_type, date, time, and status per record
    for idx, row in validated_df.iterrows():
        csv_row_num = idx + 2 if isinstance(idx, int) else idx
        rid = row["reminder_id"]

        # Validate reminder_type
        rtype = row["reminder_type"].lower()
        if rtype not in SUPPORTED_REMINDER_TYPES:
            raise ReminderValidationError(
                f"Row {csv_row_num} (reminder: '{rid}'): Unsupported reminder_type '{row['reminder_type']}'. "
                f"Supported types are: {sorted(list(SUPPORTED_REMINDER_TYPES))}"
            )
        validated_df.at[idx, "reminder_type"] = rtype

        # Validate date format
        try:
            validated_df.at[idx, "reminder_date"] = _validate_date_string(row["reminder_date"])
        except ValueError as err:
            raise ReminderValidationError(
                f"Row {csv_row_num} (reminder: '{rid}'): {err}"
            ) from err

        # Validate time format
        try:
            validated_df.at[idx, "reminder_time"] = _validate_time_string(row["reminder_time"])
        except ValueError as err:
            raise ReminderValidationError(
                f"Row {csv_row_num} (reminder: '{rid}'): {err}"
            ) from err

        # Validate status value
        status_val = row["status"].lower()
        if status_val not in ALLOWED_REMINDER_STATUSES:
            raise ReminderValidationError(
                f"Row {csv_row_num} (reminder: '{rid}'): Invalid status '{row['status']}'. "
                f"Allowed statuses: {sorted(list(ALLOWED_REMINDER_STATUSES))}"
            )
        validated_df.at[idx, "status"] = status_val

    # 6. Contact reference validation (if contacts DataFrame is provided)
    if contacts is not None:
        if "contact_id" not in contacts.columns:
            raise ReminderValidationError(
                "Supplied contacts DataFrame is missing required 'contact_id' column."
            )
        known_contact_ids = set(contacts["contact_id"].astype(str).str.strip().unique())
        for idx, row in validated_df.iterrows():
            csv_row_num = idx + 2 if isinstance(idx, int) else idx
            cid = row["contact_id"]
            if cid not in known_contact_ids:
                raise ReminderValidationError(
                    f"Row {csv_row_num} (reminder: '{row['reminder_id']}'): "
                    f"Referenced contact_id '{cid}' does not exist in contacts dataset."
                )

    return validated_df


def load_reminders(
    csv_path: Optional[Path | str] = None,
    contacts: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Load and validate reminders from CSV file.

    Args:
        csv_path: Optional path to reminders CSV file. Defaults to DATA_DIR / 'reminders.csv'.
        contacts: Optional validated contacts DataFrame to verify foreign key relationships.

    Returns:
        pd.DataFrame: Cleaned, validated reminders DataFrame.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        ReminderValidationError: If the file is empty or fails validation checks.
    """
    target_path = Path(csv_path) if csv_path is not None else DATA_DIR / "reminders.csv"

    if not target_path.exists():
        raise FileNotFoundError(f"Reminders CSV file not found: {target_path}")

    # Check for empty file before loading
    if target_path.stat().st_size == 0:
        raise ReminderValidationError(f"Reminders CSV file is empty: {target_path}")

    try:
        raw_df = pd.read_csv(target_path, dtype=str)
    except pd.errors.EmptyDataError as err:
        raise ReminderValidationError(f"Reminders CSV file contains no data: {target_path}") from err
    except Exception as err:
        raise ReminderValidationError(f"Failed to parse reminders CSV: {err}") from err

    return validate_reminders_dataframe(raw_df, contacts=contacts)


def get_reminders_for_contact(
    contact_id: str,
    reminders: Optional[pd.DataFrame] = None,
    contacts: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Retrieve all reminders associated with a specific contact ID.

    Args:
        contact_id: Contact identifier to query.
        reminders: Optional pre-loaded reminders DataFrame. If None, reminders will be loaded.
        contacts: Optional contacts DataFrame. If supplied, validates that contact_id exists.

    Returns:
        pd.DataFrame: DataFrame containing matching reminders (may be empty if contact has 0 reminders).

    Raises:
        ReminderValidationError: If contact_id is empty or whitespace-only.
        ReminderNotFoundError: If contacts DataFrame is supplied and contact_id does not exist.
    """
    norm_id = str(contact_id).strip() if contact_id is not None else ""
    if not norm_id:
        raise ReminderValidationError("A non-empty contact_id must be provided for reminder lookup.")

    # If contacts DataFrame is provided, verify contact exists
    if contacts is not None:
        if "contact_id" in contacts.columns:
            valid_cids = set(contacts["contact_id"].astype(str).str.strip().unique())
            if norm_id not in valid_cids:
                raise ReminderNotFoundError(
                    f"Contact ID '{norm_id}' not found in contacts dataset."
                )

    # Load reminders if not provided
    df = reminders if reminders is not None else load_reminders()

    # Filter matching reminders
    matching = df[df["contact_id"] == norm_id].copy()
    return matching
