"""Database module for Email Automation & Reminder System.

Provides SQLite persistence for reminder processing state, execution history,
atomic claims, and duplicate prevention across application restarts.
"""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo
import pandas as pd

from src.config import DB_PATH

# Standard project timezone for consistent timestamping
TIMEZONE: ZoneInfo = ZoneInfo("Asia/Kolkata")


class DatabaseError(Exception):
    """Base exception for all database-related operations."""
    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when connecting to SQLite fails."""
    pass


class DatabaseTransactionError(DatabaseError):
    """Raised when a database transaction fails and is rolled back."""
    pass


class ClaimResult:
    """Represents the outcome of an atomic reminder claim operation.

    Can be evaluated directly as a boolean (True if successfully claimed,
    False otherwise), unpacked as a tuple (success, reason), or accessed
    via attributes.
    """

    def __init__(
        self,
        success: bool,
        reason: str,
        status: Optional[str] = None,
        attempt_number: int = 0,
    ) -> None:
        self.success = success
        self.reason = reason
        self.status = status
        self.attempt_number = attempt_number

    def __bool__(self) -> bool:
        return self.success

    def __iter__(self):
        return iter((self.success, self.reason))

    def __repr__(self) -> str:
        return (
            f"ClaimResult(success={self.success}, reason='{self.reason}', "
            f"status={self.status!r}, attempt_number={self.attempt_number})"
        )


def _resolve_db_path(db_path: Optional[Union[Path, str]] = None) -> Path:
    """Resolve and return database file path.

    Args:
        db_path: Optional path to SQLite file. If None, uses configured DB_PATH.

    Returns:
        Path: Resolved Path object.
    """
    if db_path is None:
        return Path(DB_PATH)
    return Path(db_path)


def get_connection(db_path: Optional[Union[Path, str]] = None) -> sqlite3.Connection:
    """Open and return a configured SQLite connection.

    Enforces foreign key constraints (PRAGMA foreign_keys = ON) and sets
    row_factory to sqlite3.Row for dictionary-like column access.

    Args:
        db_path: Optional path to SQLite file. If None, uses configured DB_PATH.

    Returns:
        sqlite3.Connection: Connected database instance.

    Raises:
        DatabaseConnectionError: If connection cannot be established.
    """
    path = _resolve_db_path(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn
    except Exception as err:
        raise DatabaseConnectionError(f"Failed to connect to database at {path}: {err}") from err


@contextmanager
def get_db_connection(
    db_path: Optional[Union[Path, str]] = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for safely acquiring and releasing database connections.

    Args:
        db_path: Optional path to SQLite file.

    Yields:
        sqlite3.Connection: Database connection.
    """
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Optional[Union[Path, str]] = None) -> None:
    """Explicitly initialize SQLite database tables, constraints, and indexes.

    Creates:
    1. reminder_records: Current state and lifecycle tracking per reminder.
    2. reminder_history: Immutable audit log of all attempts, state changes, and skips.

    Safe to execute repeatedly (idempotent). Does not run automatically on import.

    Args:
        db_path: Optional path to SQLite file.
    """
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with get_db_connection(path) as conn:
        cursor = conn.cursor()

        # 1. Current state table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reminder_records (
                reminder_id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                reminder_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                simulated_output_path TEXT,
                error_message TEXT,
                last_processed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CONSTRAINT chk_status CHECK (
                    status IN ('PENDING', 'PROCESSING', 'SIMULATED', 'FAILED')
                )
            );
            """
        )

        # 2. Attempt history audit table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reminder_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reminder_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                status TEXT NOT NULL,
                simulated_output_path TEXT,
                error_message TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (reminder_id) REFERENCES reminder_records(reminder_id)
                    ON DELETE CASCADE
            );
            """
        )

        # 3. Performance and lookup indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminder_records_status ON reminder_records(status);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminder_records_contact ON reminder_records(contact_id);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminder_history_reminder ON reminder_history(reminder_id);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminder_history_timestamp ON reminder_history(timestamp);"
        )

        conn.commit()


def get_reminder_status(
    reminder_id: str,
    db_path: Optional[Union[Path, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve the current persistent state of a reminder.

    Args:
        reminder_id: The reminder ID to query.
        db_path: Optional database path.

    Returns:
        Optional[Dict[str, Any]]: Record dictionary if found, else None.
    """
    rid = str(reminder_id).strip()
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT reminder_id, contact_id, reminder_type, subject, status,
                   attempt_count, simulated_output_path, error_message,
                   last_processed_at, created_at, updated_at
            FROM reminder_records
            WHERE reminder_id = ?
            """,
            (rid,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)


def claim_reminder_for_processing(
    reminder: Union[pd.Series, Dict[str, Any]],
    db_path: Optional[Union[Path, str]] = None,
    allow_retry: bool = False,
) -> ClaimResult:
    """Atomically claim a due reminder for processing using a BEGIN IMMEDIATE transaction.

    Concurrency Rules:
    - If reminder does not exist in database: inserts record in 'PROCESSING' state (attempt 1).
    - If status == 'SIMULATED': rejected (already processed, persistent duplicate protection).
    - If status == 'PROCESSING': rejected (currently claimed by an active process).
    - If status == 'FAILED': rejected unless allow_retry=True. When allow_retry=True,
      promotes status to 'PROCESSING' and increments attempt_count.
    - If status == 'PENDING': promotes status to 'PROCESSING' and increments attempt_count.

    Args:
        reminder: Reminder row/dict containing reminder_id, contact_id, reminder_type, subject.
        db_path: Optional database path.
        allow_retry: If True, permits retrying previously 'FAILED' reminders.

    Returns:
        ClaimResult: Claim evaluation result (truthy if claimed, falsy if skipped/rejected).
    """
    rid = str(reminder.get("reminder_id", "")).strip()
    cid = str(reminder.get("contact_id", "")).strip()
    rtype = str(reminder.get("reminder_type", "")).strip().lower()
    subject = str(reminder.get("subject", "")).strip()

    now_iso = datetime.now(TIMEZONE).isoformat()
    conn = get_connection(db_path)

    try:
        # Disable automatic transaction handling to take explicit immediate exclusive lock
        conn.isolation_level = None
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            "SELECT status, attempt_count FROM reminder_records WHERE reminder_id = ?",
            (rid,),
        )
        row = cursor.fetchone()

        if row is None:
            # 1. New reminder from CSV: register and claim
            cursor.execute(
                """
                INSERT INTO reminder_records (
                    reminder_id, contact_id, reminder_type, subject,
                    status, attempt_count, last_processed_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'PROCESSING', 1, ?, ?, ?)
                """,
                (rid, cid, rtype, subject, now_iso, now_iso, now_iso),
            )
            cursor.execute(
                """
                INSERT INTO reminder_history (
                    reminder_id, attempt_number, status, timestamp
                ) VALUES (?, 1, 'PROCESSING', ?)
                """,
                (rid, now_iso),
            )
            cursor.execute("COMMIT")
            return ClaimResult(True, "Claimed for processing", status="PROCESSING", attempt_number=1)

        current_status = row["status"]
        current_attempts = row["attempt_count"]

        # 2. Already successfully simulated -> Skip permanently
        if current_status == "SIMULATED":
            cursor.execute("COMMIT")
            return ClaimResult(
                False,
                "Already successfully simulated in database (persistent duplicate protection)",
                status="SIMULATED",
                attempt_number=current_attempts,
            )

        # 3. Currently in processing by another task/worker -> Skip
        if current_status == "PROCESSING":
            cursor.execute("COMMIT")
            return ClaimResult(
                False,
                "Reminder is currently being processed by another worker",
                status="PROCESSING",
                attempt_number=current_attempts,
            )

        # 4. Previously failed -> Skip unless explicitly authorized for retry
        if current_status == "FAILED":
            if not allow_retry:
                cursor.execute("COMMIT")
                return ClaimResult(
                    False,
                    "Reminder previously failed; retry not requested",
                    status="FAILED",
                    attempt_number=current_attempts,
                )
            # Authorized retry
            new_attempt = current_attempts + 1
            cursor.execute(
                """
                UPDATE reminder_records
                SET status = 'PROCESSING',
                    attempt_count = ?,
                    last_processed_at = ?,
                    updated_at = ?,
                    error_message = NULL
                WHERE reminder_id = ?
                """,
                (new_attempt, now_iso, now_iso, rid),
            )
            cursor.execute(
                """
                INSERT INTO reminder_history (
                    reminder_id, attempt_number, status, timestamp
                ) VALUES (?, ?, 'PROCESSING', ?)
                """,
                (rid, new_attempt, now_iso),
            )
            cursor.execute("COMMIT")
            return ClaimResult(
                True,
                f"Claimed for retry attempt {new_attempt}",
                status="PROCESSING",
                attempt_number=new_attempt,
            )

        # 5. PENDING (e.g. after manual retry reset) -> Claim
        if current_status == "PENDING":
            new_attempt = current_attempts + 1
            cursor.execute(
                """
                UPDATE reminder_records
                SET status = 'PROCESSING',
                    attempt_count = ?,
                    last_processed_at = ?,
                    updated_at = ?
                WHERE reminder_id = ?
                """,
                (new_attempt, now_iso, now_iso, rid),
            )
            cursor.execute(
                """
                INSERT INTO reminder_history (
                    reminder_id, attempt_number, status, timestamp
                ) VALUES (?, ?, 'PROCESSING', ?)
                """,
                (rid, new_attempt, now_iso),
            )
            cursor.execute("COMMIT")
            return ClaimResult(
                True,
                "Claimed for processing from pending",
                status="PROCESSING",
                attempt_number=new_attempt,
            )

        cursor.execute("COMMIT")
        return ClaimResult(
            False,
            f"Unrecognized status: {current_status}",
            status=current_status,
            attempt_number=current_attempts,
        )

    except Exception as err:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        raise DatabaseTransactionError(f"Atomic claim transaction failed for {rid}: {err}") from err
    finally:
        conn.close()


def record_simulation_success(
    reminder_id: str,
    output_path: str,
    db_path: Optional[Union[Path, str]] = None,
) -> None:
    """Persist successful simulation outcome in reminder_records and reminder_history.

    Args:
        reminder_id: The reminder ID that was simulated.
        output_path: File system path of the generated .eml simulation file.
        db_path: Optional database path.
    """
    rid = str(reminder_id).strip()
    now_iso = datetime.now(TIMEZONE).isoformat()

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE reminder_records
            SET status = 'SIMULATED',
                simulated_output_path = ?,
                error_message = NULL,
                last_processed_at = ?,
                updated_at = ?
            WHERE reminder_id = ?
            """,
            (str(output_path), now_iso, now_iso, rid),
        )

        cursor.execute(
            "SELECT attempt_count FROM reminder_records WHERE reminder_id = ?",
            (rid,),
        )
        row = cursor.fetchone()
        attempt_number = row["attempt_count"] if row else 1

        cursor.execute(
            """
            INSERT INTO reminder_history (
                reminder_id, attempt_number, status, simulated_output_path, timestamp
            ) VALUES (?, ?, 'SIMULATED', ?, ?)
            """,
            (rid, attempt_number, str(output_path), now_iso),
        )
        conn.commit()


def record_simulation_failure(
    reminder_id: str,
    error_message: str,
    db_path: Optional[Union[Path, str]] = None,
) -> None:
    """Persist failed simulation attempt in reminder_records and reminder_history.

    Args:
        reminder_id: The reminder ID that failed.
        error_message: Diagnostic failure message.
        db_path: Optional database path.
    """
    rid = str(reminder_id).strip()
    now_iso = datetime.now(TIMEZONE).isoformat()

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE reminder_records
            SET status = 'FAILED',
                error_message = ?,
                last_processed_at = ?,
                updated_at = ?
            WHERE reminder_id = ?
            """,
            (str(error_message), now_iso, now_iso, rid),
        )

        cursor.execute(
            "SELECT attempt_count FROM reminder_records WHERE reminder_id = ?",
            (rid,),
        )
        row = cursor.fetchone()
        attempt_number = row["attempt_count"] if row else 1

        cursor.execute(
            """
            INSERT INTO reminder_history (
                reminder_id, attempt_number, status, error_message, timestamp
            ) VALUES (?, ?, 'FAILED', ?, ?)
            """,
            (rid, attempt_number, str(error_message), now_iso),
        )
        conn.commit()


def record_skipped_attempt(
    reminder_id: str,
    reason: str,
    db_path: Optional[Union[Path, str]] = None,
) -> None:
    """Record an audit trail entry for a skipped reminder in reminder_history.

    Args:
        reminder_id: The reminder ID that was skipped.
        reason: Explanation of why processing was skipped.
        db_path: Optional database path.
    """
    rid = str(reminder_id).strip()
    now_iso = datetime.now(TIMEZONE).isoformat()

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT attempt_count FROM reminder_records WHERE reminder_id = ?",
            (rid,),
        )
        row = cursor.fetchone()
        attempt_number = row["attempt_count"] if row else 0

        cursor.execute(
            """
            INSERT INTO reminder_history (
                reminder_id, attempt_number, status, error_message, timestamp
            ) VALUES (?, ?, 'SKIPPED', ?, ?)
            """,
            (rid, attempt_number, str(reason), now_iso),
        )
        conn.commit()


def reset_failed_reminder_for_retry(
    reminder_id: str,
    db_path: Optional[Union[Path, str]] = None,
) -> bool:
    """Explicitly reset a FAILED reminder to PENDING status to allow re-processing.

    This implements the explicit retry policy: failed reminders do not retry
    automatically on polling cycles, but can be reset by calling this function.

    Args:
        reminder_id: Reminder ID to reset.
        db_path: Optional database path.

    Returns:
        bool: True if reminder was in FAILED status and reset to PENDING, False otherwise.
    """
    rid = str(reminder_id).strip()
    now_iso = datetime.now(TIMEZONE).isoformat()

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, attempt_count FROM reminder_records WHERE reminder_id = ?",
            (rid,),
        )
        row = cursor.fetchone()

        if row is None or row["status"] != "FAILED":
            return False

        cursor.execute(
            """
            UPDATE reminder_records
            SET status = 'PENDING',
                updated_at = ?
            WHERE reminder_id = ?
            """,
            (now_iso, rid),
        )
        cursor.execute(
            """
            INSERT INTO reminder_history (
                reminder_id, attempt_number, status, error_message, timestamp
            ) VALUES (?, ?, 'PENDING', 'Explicitly reset for retry', ?)
            """,
            (rid, row["attempt_count"], now_iso),
        )
        conn.commit()
        return True


def recover_stale_processing_reminders(
    target_status: str = "FAILED",
    db_path: Optional[Union[Path, str]] = None,
) -> int:
    """Recover reminders left in 'PROCESSING' state after unexpected application termination.

    If the application stops while a reminder is in 'PROCESSING', this function
    recovers those records so they are not left permanently locked.

    Args:
        target_status: Status to assign recovered records ('FAILED' by default, or 'PENDING').
        db_path: Optional database path.

    Returns:
        int: Number of recovered records.
    """
    if target_status not in ("FAILED", "PENDING"):
        raise ValueError(f"Invalid target_status '{target_status}'. Must be 'FAILED' or 'PENDING'.")

    now_iso = datetime.now(TIMEZONE).isoformat()
    msg = f"Recovered from stale PROCESSING status to {target_status}"

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT reminder_id, attempt_count FROM reminder_records WHERE status = 'PROCESSING'"
        )
        stale_rows = cursor.fetchall()

        if not stale_rows:
            return 0

        for row in stale_rows:
            rid = row["reminder_id"]
            attempt_count = row["attempt_count"]

            cursor.execute(
                """
                UPDATE reminder_records
                SET status = ?,
                    error_message = ?,
                    updated_at = ?
                WHERE reminder_id = ?
                """,
                (target_status, msg, now_iso, rid),
            )
            cursor.execute(
                """
                INSERT INTO reminder_history (
                    reminder_id, attempt_number, status, error_message, timestamp
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (rid, attempt_count, target_status, msg, now_iso),
            )

        conn.commit()
        return len(stale_rows)


def get_processing_history(
    reminder_id: Optional[str] = None,
    limit: Optional[int] = None,
    db_path: Optional[Union[Path, str]] = None,
) -> List[Dict[str, Any]]:
    """Retrieve history entries for audit analysis.

    Args:
        reminder_id: Optional reminder ID to filter by.
        limit: Optional maximum number of records to return.
        db_path: Optional database path.

    Returns:
        List[Dict[str, Any]]: List of history record dictionaries.
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        query = (
            "SELECT history_id, reminder_id, attempt_number, status, "
            "simulated_output_path, error_message, timestamp "
            "FROM reminder_history "
        )
        params: List[Any] = []

        if reminder_id is not None:
            query += "WHERE reminder_id = ? "
            params.append(str(reminder_id).strip())

        query += "ORDER BY history_id ASC "

        if limit is not None:
            query += "LIMIT ? "
            params.append(int(limit))

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_processing_summary(
    db_path: Optional[Union[Path, str]] = None,
) -> Dict[str, Any]:
    """Retrieve aggregated counts of reminder statuses in the database.

    Args:
        db_path: Optional database path.

    Returns:
        Dict[str, Any]: Dictionary with counts for total, simulated, failed,
                        processing, and pending.
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'SIMULATED' THEN 1 ELSE 0 END) as simulated,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END) as processing,
                SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending
            FROM reminder_records
            """
        )
        row = cursor.fetchone()
        if row is None:
            return {"total": 0, "simulated": 0, "failed": 0, "processing": 0, "pending": 0}

        return {
            "total": row["total"] or 0,
            "simulated": row["simulated"] or 0,
            "failed": row["failed"] or 0,
            "processing": row["processing"] or 0,
            "pending": row["pending"] or 0,
        }


def clear_all_reminders(db_path: Optional[Union[Path, str]] = None) -> None:
    """Clear all records from reminder_records and reminder_history.

    Primarily used for test isolation.

    Args:
        db_path: Optional database path.
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reminder_history;")
        cursor.execute("DELETE FROM reminder_records;")
        conn.commit()
