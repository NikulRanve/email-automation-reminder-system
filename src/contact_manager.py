"""Contact manager module for Email Automation & Reminder System.

Responsible for loading, validating, and managing contact records from data sources.
Provides contact validation and lookup utilities.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import re
import pandas as pd

from src.config import DATA_DIR

# Required columns in contacts.csv
REQUIRED_CONTACT_COLUMNS: List[str] = [
    "contact_id",
    "name",
    "email",
    "department",
]

# Reasonable email format pattern (practical syntax check, not full RFC 5322 compliance)
EMAIL_PATTERN: re.Pattern = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)


class ContactValidationError(ValueError):
    """Exception raised when contact data fails structural or semantic validation."""
    pass


class ContactNotFoundError(KeyError):
    """Exception raised when a requested contact_id does not exist."""
    pass


def validate_contacts_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize a contacts DataFrame.

    Checks:
    - Presence of required columns.
    - Non-empty records.
    - Strips leading/trailing whitespace on all string fields in memory.
    - Non-empty required fields across all rows.
    - Uniqueness of contact_id.
    - Reasonable email address format.

    Args:
        df: Input pandas DataFrame loaded from contacts CSV.

    Returns:
        A cleaned, normalized pandas DataFrame.

    Raises:
        ContactValidationError: If any validation rule is violated.
    """
    if df.empty:
        raise ContactValidationError("Contacts dataset is empty; no contact records found.")

    # Normalize column names (strip leading/trailing whitespace)
    df.columns = [str(col).strip() for col in df.columns]

    # 1. Verify required columns exist
    missing_columns = [col for col in REQUIRED_CONTACT_COLUMNS if col not in df.columns]
    if missing_columns:
        raise ContactValidationError(
            f"Missing required contact column(s): {missing_columns}. "
            f"Expected: {REQUIRED_CONTACT_COLUMNS}"
        )

    # Work on a copy to avoid mutating external references
    validated_df = df.copy()

    # 2. Normalize whitespace across all fields in memory
    for col in REQUIRED_CONTACT_COLUMNS:
        validated_df[col] = (
            validated_df[col]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # 3. Check for empty values in required fields per record
    for idx, row in validated_df.iterrows():
        # Display 1-based row number accounting for CSV header
        csv_row_num = idx + 2 if isinstance(idx, int) else idx
        for col in REQUIRED_CONTACT_COLUMNS:
            val = row[col]
            if not val:
                cid = row["contact_id"] if row["contact_id"] else f"row {csv_row_num}"
                raise ContactValidationError(
                    f"Row {csv_row_num} (contact: '{cid}'): Required field '{col}' is empty."
                )

    # 4. Validate unique contact IDs
    duplicated_mask = validated_df["contact_id"].duplicated(keep=False)
    if duplicated_mask.any():
        duplicate_ids = validated_df.loc[duplicated_mask, "contact_id"].unique().tolist()
        raise ContactValidationError(
            f"Duplicate contact_id values found: {duplicate_ids}. Contact IDs must be unique."
        )

    # 5. Validate email address format
    for idx, row in validated_df.iterrows():
        csv_row_num = idx + 2 if isinstance(idx, int) else idx
        email = row["email"]
        if not EMAIL_PATTERN.match(email):
            raise ContactValidationError(
                f"Row {csv_row_num} (contact_id: '{row['contact_id']}'): "
                f"Invalid email address '{email}'."
            )

    return validated_df


def load_contacts(csv_path: Optional[Path | str] = None) -> pd.DataFrame:
    """Load and validate contacts from a CSV file.

    Args:
        csv_path: Optional path to the contacts CSV file.
                  Defaults to DATA_DIR / 'contacts.csv'.

    Returns:
        pd.DataFrame: Validated and normalized contacts DataFrame.

    Raises:
        FileNotFoundError: If the specified CSV file does not exist.
        ContactValidationError: If the file is empty or fails validation.
    """
    target_path = Path(csv_path) if csv_path is not None else DATA_DIR / "contacts.csv"

    if not target_path.exists():
        raise FileNotFoundError(f"Contacts CSV file not found: {target_path}")

    # Check for empty file before loading
    if target_path.stat().st_size == 0:
        raise ContactValidationError(f"Contacts CSV file is empty: {target_path}")

    try:
        # Load CSV using pandas
        raw_df = pd.read_csv(target_path, dtype=str)
    except pd.errors.EmptyDataError as err:
        raise ContactValidationError(f"Contacts CSV file contains no data: {target_path}") from err
    except Exception as err:
        raise ContactValidationError(f"Failed to parse contacts CSV: {err}") from err

    return validate_contacts_dataframe(raw_df)


def get_contact_by_id(
    contact_id: str,
    contacts: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Retrieve a contact record by contact_id.

    Args:
        contact_id: Unique contact identifier to search for.
        contacts: Optional pre-loaded and validated DataFrame. If None,
                  contacts will be loaded using load_contacts().

    Returns:
        Dict[str, Any]: Matching contact record as a dictionary.

    Raises:
        ContactNotFoundError: If no contact matches the specified contact_id.
        ContactValidationError: If loading contacts fails validation.
    """
    norm_id = str(contact_id).strip()
    if not norm_id:
        raise ContactNotFoundError("A non-empty contact_id must be provided for lookup.")

    df = contacts if contacts is not None else load_contacts()

    match = df[df["contact_id"] == norm_id]
    if match.empty:
        raise ContactNotFoundError(f"Contact with ID '{norm_id}' not found.")

    return match.iloc[0].to_dict()
