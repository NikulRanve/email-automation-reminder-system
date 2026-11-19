"""Report generator and analytics module for Email Automation & Reminder System.

Provides SQLite-backed processing summaries, detailed audit history queries,
date-range filtering, and atomic, non-destructive CSV export capabilities.
"""

from contextlib import contextmanager
import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from src.config import DB_PATH, REPORTS_DIR
from src.database import get_db_connection

TIMEZONE: ZoneInfo = ZoneInfo("Asia/Kolkata")


class ReportGeneratorError(Exception):
    """Base exception for report generation errors."""
    pass


class InvalidDateRangeError(ReportGeneratorError):
    """Raised when an invalid date or date range is provided."""
    pass


def _resolve_db_path(db_path: Optional[Union[Path, str]] = None) -> Path:
    """Resolve database path from argument or default configuration."""
    if db_path is None:
        return Path(DB_PATH)
    return Path(db_path)


def _resolve_reports_dir(output_dir: Optional[Union[Path, str]] = None) -> Path:
    """Resolve and ensure existence of reports output directory."""
    if output_dir is None:
        path = Path(REPORTS_DIR)
    else:
        path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_date_bound(val: Union[str, datetime], is_end: bool = False) -> str:
    """Parse and normalize date boundary into ISO 8601 string for SQL comparison.

    Rules:
    - Pure YYYY-MM-DD:
      - Start boundary: set to 00:00:00 in Asia/Kolkata (inclusive).
      - End boundary: set to 23:59:59.999999 in Asia/Kolkata (inclusive).
    - Datetime objects:
      - If naive, tagged with Asia/Kolkata timezone.
      - If aware, converted to Asia/Kolkata via .astimezone(TIMEZONE).
    - ISO strings (including with 'Z' or UTC offsets):
      - Converted to Asia/Kolkata timezone.

    Args:
        val: Date string (YYYY-MM-DD, ISO format) or datetime object.
        is_end: If True and only YYYY-MM-DD was provided, sets time to end of day.

    Returns:
        str: ISO 8601 formatted datetime string localized to Asia/Kolkata.

    Raises:
        InvalidDateRangeError: If date format cannot be parsed.
    """
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=TIMEZONE)
        else:
            val = val.astimezone(TIMEZONE)
        return val.isoformat()

    clean = str(val).strip()

    # 1. Pure YYYY-MM-DD format
    try:
        dt = datetime.strptime(clean, "%Y-%m-%d")
        if is_end:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        dt = dt.replace(tzinfo=TIMEZONE)
        return dt.isoformat()
    except ValueError:
        pass

    # 2. Formats with time components (naive assumed Asia/Kolkata)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(clean, fmt)
            dt = dt.replace(tzinfo=TIMEZONE)
            return dt.isoformat()
        except ValueError:
            continue

    # 3. ISO strings (handles offsets such as +00:00 or 'Z')
    try:
        iso_str = clean.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TIMEZONE)
        else:
            dt = dt.astimezone(TIMEZONE)
        return dt.isoformat()
    except ValueError:
        raise InvalidDateRangeError(
            f"Invalid date format: '{val}'. Expected 'YYYY-MM-DD' or ISO 8601 format."
        )


@contextmanager
def _open_atomic_report_file(
    directory: Path,
    base_name: str,
) -> Generator[Tuple[Path, Any], None, None]:
    """Atomically create and open a unique report file using OS-level exclusive creation ('x' mode).

    Guarantees:
    - Atomicity: Uses OS-level exclusive file creation (O_CREAT | O_EXCL via mode 'x').
      Eliminates Time-of-Check to Time-of-Use (TOCTOU) race conditions between concurrent processes.
    - Suffix fallback: If filename collision occurs, increments counter (_1, _2, etc.).
    - Clean failure: If an exception occurs during writing, the partial file is safely deleted.

    Args:
        directory: Destination directory.
        base_name: Base filename prefix ('summary_report' or 'history_report').

    Yields:
        Tuple[Path, Any]: The resolved unique Path and the opened writable file handle.
    """
    timestamp_str = datetime.now(TIMEZONE).strftime("%Y%m%d_%H%M%S")
    counter = 0

    while True:
        if counter == 0:
            target_path = directory / f"{base_name}_{timestamp_str}.csv"
        else:
            target_path = directory / f"{base_name}_{timestamp_str}_{counter}.csv"

        try:
            # Mode 'x' issues atomic O_CREAT | O_EXCL syscall, failing with FileExistsError
            # if another process or thread created the file in the meantime.
            file_obj = open(target_path, mode="x", newline="", encoding="utf-8")
            break
        except FileExistsError:
            counter += 1
            continue

    try:
        yield target_path, file_obj
    except Exception:
        file_obj.close()
        target_path.unlink(missing_ok=True)
        raise
    else:
        file_obj.close()


def _get_unique_csv_path(directory: Path, base_name: str) -> Path:
    """Find a unique target path for reporting (kept for backward compatibility).

    Args:
        directory: Target directory.
        base_name: Base filename prefix.

    Returns:
        Path: Target file path.
    """
    timestamp_str = datetime.now(TIMEZONE).strftime("%Y%m%d_%H%M%S")
    target_path = directory / f"{base_name}_{timestamp_str}.csv"
    counter = 1
    while target_path.exists():
        target_path = directory / f"{base_name}_{timestamp_str}_{counter}.csv"
        counter += 1
    return target_path


def generate_processing_summary(
    db_path: Optional[Union[Path, str]] = None,
) -> Dict[str, Any]:
    """Generate aggregated processing metrics using SQLite as the single source of truth.

    Definitions:
    - total_reminders: Count of distinct reminders in reminder_records
    - simulated_reminders: Total reminders currently in SIMULATED status
    - failed_reminders: Total reminders currently in FAILED status
    - pending_reminders: Total reminders currently in PENDING status
    - processing_reminders: Total reminders currently in PROCESSING status
    - total_processing_attempts: Total processing attempts (rows where status = 'PROCESSING')
    - skipped_events: Total SKIPPED audit events (rows where status = 'SKIPPED')
    - total_history_events: Total audit log rows across all statuses in reminder_history
    - generated_at: ISO timestamp of report generation in Asia/Kolkata

    Args:
        db_path: Optional database path.

    Returns:
        Dict[str, Any]: Structured summary dictionary.
    """
    path = _resolve_db_path(db_path)
    if not path.exists():
        return {
            "total_reminders": 0,
            "simulated_reminders": 0,
            "failed_reminders": 0,
            "pending_reminders": 0,
            "processing_reminders": 0,
            "total_processing_attempts": 0,
            "skipped_events": 0,
            "total_history_events": 0,
            "generated_at": datetime.now(TIMEZONE).isoformat(),
        }

    with get_db_connection(path) as conn:
        cursor = conn.cursor()

        # 1. Metrics from reminder_records (Current state)
        cursor.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'SIMULATED' THEN 1 ELSE 0 END) as simulated,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END) as processing
            FROM reminder_records
            """
        )
        rec_row = cursor.fetchone()

        # 2. Metrics from reminder_history (Audit log)
        cursor.execute(
            """
            SELECT
                COUNT(*) as total_history_events,
                SUM(CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END) as total_processing_attempts,
                SUM(CASE WHEN status = 'SKIPPED' THEN 1 ELSE 0 END) as skipped_events
            FROM reminder_history
            """
        )
        hist_row = cursor.fetchone()

        total = rec_row["total"] if rec_row else 0
        simulated = rec_row["simulated"] if rec_row and rec_row["simulated"] else 0
        failed = rec_row["failed"] if rec_row and rec_row["failed"] else 0
        pending = rec_row["pending"] if rec_row and rec_row["pending"] else 0
        processing = rec_row["processing"] if rec_row and rec_row["processing"] else 0

        total_history_events = hist_row["total_history_events"] if hist_row else 0
        total_processing_attempts = (
            hist_row["total_processing_attempts"] if hist_row and hist_row["total_processing_attempts"] else 0
        )
        skipped_events = (
            hist_row["skipped_events"] if hist_row and hist_row["skipped_events"] else 0
        )

        return {
            "total_reminders": total,
            "simulated_reminders": simulated,
            "failed_reminders": failed,
            "pending_reminders": pending,
            "processing_reminders": processing,
            "total_processing_attempts": total_processing_attempts,
            "skipped_events": skipped_events,
            "total_history_events": total_history_events,
            "generated_at": datetime.now(TIMEZONE).isoformat(),
        }


def get_detailed_processing_history(
    reminder_id: Optional[str] = None,
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None,
    limit: Optional[int] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> List[Dict[str, Any]]:
    """Retrieve individual reminder processing history with optional ID and date-range filtering.

    Args:
        reminder_id: Optional reminder ID to filter by.
        start_date: Optional start date/datetime filter (inclusive).
        end_date: Optional end date/datetime filter (inclusive).
        limit: Optional maximum number of rows to return.
        db_path: Optional database path.

    Returns:
        List[Dict[str, Any]]: List of dictionary records from reminder_history.

    Raises:
        InvalidDateRangeError: If dates are malformed or start_date > end_date.
    """
    path = _resolve_db_path(db_path)
    if not path.exists():
        return []

    # Validate and normalize date bounds
    start_iso = None
    end_iso = None

    if start_date is not None:
        start_iso = _parse_date_bound(start_date, is_end=False)
    if end_date is not None:
        end_iso = _parse_date_bound(end_date, is_end=True)

    if start_iso is not None and end_iso is not None:
        if start_iso > end_iso:
            raise InvalidDateRangeError(
                f"Invalid date range: start_date '{start_date}' is after end_date '{end_date}'."
            )

    query = (
        "SELECT history_id, reminder_id, attempt_number, status, "
        "timestamp, simulated_output_path, error_message "
        "FROM reminder_history WHERE 1=1 "
    )
    params: List[Any] = []

    if reminder_id is not None:
        query += "AND reminder_id = ? "
        params.append(str(reminder_id).strip())

    if start_iso is not None:
        query += "AND timestamp >= ? "
        params.append(start_iso)

    if end_iso is not None:
        query += "AND timestamp <= ? "
        params.append(end_iso)

    query += "ORDER BY history_id ASC "

    if limit is not None:
        query += "LIMIT ? "
        params.append(int(limit))

    with get_db_connection(path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def export_summary_to_csv(
    output_dir: Optional[Union[Path, str]] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> Path:
    """Atomically export the current processing summary to a timestamped CSV report.

    Guarantees no overwrite across concurrent processes using OS-level exclusive creation ('x' mode).

    Args:
        output_dir: Optional target directory (defaults to outputs/reports/).
        db_path: Optional database path.

    Returns:
        Path: Path of the newly created CSV file.
    """
    summary = generate_processing_summary(db_path=db_path)
    target_dir = _resolve_reports_dir(output_dir)

    fields = [
        ("Metric", "Value"),
        ("Total Reminders Registered", summary["total_reminders"]),
        ("Total SIMULATED Reminders", summary["simulated_reminders"]),
        ("Total FAILED Reminders", summary["failed_reminders"]),
        ("Total PENDING Reminders", summary["pending_reminders"]),
        ("Total PROCESSING Reminders", summary["processing_reminders"]),
        ("Total Processing Attempts", summary["total_processing_attempts"]),
        ("Total SKIPPED Events", summary["skipped_events"]),
        ("Total History Events Logged", summary["total_history_events"]),
        ("Report Generated At (ISO)", summary["generated_at"]),
    ]

    with _open_atomic_report_file(target_dir, "summary_report") as (file_path, file_obj):
        writer = csv.writer(file_obj)
        for row in fields:
            writer.writerow(row)

    return file_path


def export_history_to_csv(
    reminder_id: Optional[str] = None,
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None,
    output_dir: Optional[Union[Path, str]] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> Path:
    """Atomically export detailed processing history to a timestamped CSV report.

    Guarantees no overwrite across concurrent processes using OS-level exclusive creation ('x' mode).

    Args:
        reminder_id: Optional reminder ID filter.
        start_date: Optional start date filter.
        end_date: Optional end date filter.
        output_dir: Optional target directory (defaults to outputs/reports/).
        db_path: Optional database path.

    Returns:
        Path: Path of the newly created CSV file.
    """
    history = get_detailed_processing_history(
        reminder_id=reminder_id,
        start_date=start_date,
        end_date=end_date,
        db_path=db_path,
    )
    target_dir = _resolve_reports_dir(output_dir)

    fieldnames = [
        "history_id",
        "reminder_id",
        "attempt_number",
        "status",
        "timestamp",
        "simulated_output_path",
        "error_message",
    ]

    with _open_atomic_report_file(target_dir, "history_report") as (file_path, file_obj):
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for row in history:
            writer.writerow(row)

    return file_path


def format_summary_console(summary: Dict[str, Any]) -> str:
    """Format processing summary dictionary into an aligned text table for console display.

    Args:
        summary: Dictionary returned by generate_processing_summary().

    Returns:
        str: Formatted string table.
    """
    lines = [
        "=" * 60,
        " SQLite Processing & Analytics Summary",
        "=" * 60,
        f"  Total Reminders Registered : {summary['total_reminders']}",
        f"  SIMULATED Reminders        : {summary['simulated_reminders']}",
        f"  FAILED Reminders           : {summary['failed_reminders']}",
        f"  PENDING Reminders          : {summary['pending_reminders']}",
        f"  PROCESSING Reminders       : {summary['processing_reminders']}",
        "-" * 60,
        f"  Total Processing Attempts  : {summary['total_processing_attempts']}",
        f"  SKIPPED Audit Events       : {summary['skipped_events']}",
        f"  Total History Events Logged: {summary['total_history_events']}",
        f"  Generated At               : {summary['generated_at']}",
        "=" * 60,
    ]
    return "\n".join(lines)
