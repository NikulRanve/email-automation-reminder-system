"""Scheduler and reminder-processing module for Email Automation & Reminder System.

Responsible for identifying due reminders based on Asia/Kolkata timezone,
generating personalized emails, dispatching safe simulation messages, and managing
persistent duplicate suppression via SQLite and periodic job scheduling.
"""

from datetime import datetime
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Union
from zoneinfo import ZoneInfo
import pandas as pd
import schedule

from src.config import DB_PATH, SIMULATED_EMAILS_DIR
from src.contact_manager import load_contacts, get_contact_by_id, ContactNotFoundError
from src.reminder_manager import load_reminders
from src.email_generator import generate_email, TemplateError
from src.email_sender import (
    create_email_message,
    send_email,
    get_simulated_path,
    EmailSenderError,
)
from src.database import (
    init_db,
    claim_reminder_for_processing,
    record_simulation_success,
    record_simulation_failure,
    record_skipped_attempt,
    recover_stale_processing_reminders,
    clear_all_reminders,
    get_reminder_status,
)

# Standard project timezone
TIMEZONE: ZoneInfo = ZoneInfo("Asia/Kolkata")

# In-memory tracking set to suppress duplicate processing during a single application session.
_PROCESSED_REMINDER_IDS: Set[str] = set()


class SchedulerError(Exception):
    """Base exception for scheduler and processing errors."""
    pass


class SchedulerExecutionError(SchedulerError):
    """Raised when an unrecoverable scheduler failure occurs."""
    pass


def get_processed_reminder_ids() -> Set[str]:
    """Retrieve a copy of all reminder IDs processed in the current session.

    Returns:
        Set[str]: In-memory set of processed reminder IDs.
    """
    return set(_PROCESSED_REMINDER_IDS)


def reset_processed_reminders(
    db_path: Optional[Union[Path, str]] = None,
    reset_db: bool = True,
) -> None:
    """Clear the in-memory duplicate tracking set and optionally clear database state.

    Primarily used between test runs or upon system re-initialization.

    Args:
        db_path: Optional database path to clear.
        reset_db: If True, also clears tables in the specified or default database.
    """
    global _PROCESSED_REMINDER_IDS
    _PROCESSED_REMINDER_IDS.clear()

    if reset_db:
        target_db = Path(db_path) if db_path is not None else DB_PATH
        if target_db.exists():
            try:
                clear_all_reminders(db_path=target_db)
            except Exception:
                pass


def mark_reminder_processed(reminder_id: str) -> None:
    """Record a reminder ID as processed in memory."""
    _PROCESSED_REMINDER_IDS.add(str(reminder_id).strip())


def is_reminder_processed(reminder_id: str) -> bool:
    """Check if a reminder ID has already been simulated during the active session."""
    return str(reminder_id).strip() in _PROCESSED_REMINDER_IDS


def _normalize_comparison_time(now: Optional[datetime] = None) -> datetime:
    """Normalize input reference time to timezone-aware Asia/Kolkata datetime.

    Args:
        now: Reference datetime. If None, uses current Asia/Kolkata time.
             If naive (now.tzinfo is None), interprets it as Asia/Kolkata local time.
             If timezone-aware in another zone, converts it to Asia/Kolkata.

    Returns:
        datetime: Timezone-aware datetime localized to Asia/Kolkata.
    """
    if now is None:
        return datetime.now(TIMEZONE)
    if now.tzinfo is None:
        return now.replace(tzinfo=TIMEZONE)
    return now.astimezone(TIMEZONE)


def _parse_reminder_datetime(date_str: str, time_str: str) -> datetime:
    """Parse reminder date and time strings into an Asia/Kolkata timezone-aware datetime.

    Args:
        date_str: Date string in YYYY-MM-DD format.
        time_str: Time string in HH:MM or HH:MM:SS format.

    Returns:
        datetime: Timezone-aware datetime localized to Asia/Kolkata.

    Raises:
        ValueError: If date/time strings cannot be parsed.
    """
    clean_date = str(date_str).strip()
    clean_time = str(time_str).strip()

    dt = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(f"{clean_date} {clean_time}", fmt)
            break
        except ValueError:
            continue

    if dt is None:
        raise ValueError(
            f"Cannot parse reminder datetime from date='{date_str}', time='{time_str}'"
        )

    return dt.replace(tzinfo=TIMEZONE)


def get_due_reminders(
    reminders: pd.DataFrame,
    now: Optional[datetime] = None,
) -> pd.DataFrame:
    """Filter and return reminders that are due at the specified time.

    Rules:
    - Compares against Asia/Kolkata timezone.
    - Reminder is due if scheduled datetime <= now.
    - Only reminders with status == 'pending' are considered.
    - Returns a new DataFrame without mutating the input DataFrame.

    Args:
        reminders: Validated reminders DataFrame.
        now: Optional evaluation timestamp (defaults to current Asia/Kolkata time).

    Returns:
        pd.DataFrame: Subset DataFrame containing due pending reminders.
    """
    if reminders is None or reminders.empty:
        return pd.DataFrame(columns=reminders.columns if reminders is not None else [])

    ref_time = _normalize_comparison_time(now)
    due_indices = []

    for idx, row in reminders.iterrows():
        status = str(row.get("status", "")).strip().lower()
        if status != "pending":
            continue

        try:
            rem_dt = _parse_reminder_datetime(row["reminder_date"], row["reminder_time"])
            if rem_dt <= ref_time:
                due_indices.append(idx)
        except Exception:
            continue

    return reminders.loc[due_indices].copy()


def process_reminder(
    reminder: Union[pd.Series, Dict[str, Any]],
    contacts: pd.DataFrame,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Process a single reminder: lookup contact, render personalized template, and simulate sending.

    Args:
        reminder: Reminder record containing reminder_id, contact_id, reminder_type, etc.
        contacts: Validated contacts DataFrame.
        output_dir: Optional override directory for .eml simulation output.

    Returns:
        Dict[str, Any]: Structured processing result containing reminder_id, contact_id,
                        status ('SIMULATED', 'FAILED', or 'SKIPPED'), output_path, and error.
    """
    rid = str(reminder.get("reminder_id", "")).strip()
    cid = str(reminder.get("contact_id", "")).strip()
    rtype = str(reminder.get("reminder_type", "")).strip().lower()
    subject = str(reminder.get("subject", "")).strip()
    rdate = str(reminder.get("reminder_date", "")).strip()
    rtime = str(reminder.get("reminder_time", "")).strip()

    result: Dict[str, Any] = {
        "reminder_id": rid,
        "contact_id": cid,
        "status": "FAILED",
        "subject": subject,
        "output_path": None,
        "error": None,
        "timestamp": datetime.now(TIMEZONE).isoformat(),
    }

    try:
        # 1. Retrieve recipient contact
        contact = get_contact_by_id(cid, contacts=contacts)
        recipient_name = contact["name"]
        recipient_email = contact["email"]

        # 2. Personalize email template
        html_content = generate_email(
            reminder_type=rtype,
            name=recipient_name,
            date=rdate,
            time=rtime,
        )

        # 3. Construct MIME message
        msg = create_email_message(
            to_email=recipient_email,
            subject=subject,
            html_content=html_content,
            from_email="no-reply@example.com",
        )

        # 4. Safe simulation dispatch
        send_status = send_email(msg, output_dir=output_dir)
        sim_path = get_simulated_path(msg)

        result["status"] = send_status  # "SIMULATED"
        result["output_path"] = str(sim_path) if sim_path else None
        return result

    except (ContactNotFoundError, TemplateError, EmailSenderError, Exception) as err:
        result["status"] = "FAILED"
        result["error"] = str(err)
        return result


def process_due_reminders(
    reminders: Optional[pd.DataFrame] = None,
    contacts: Optional[pd.DataFrame] = None,
    now: Optional[datetime] = None,
    output_dir: Optional[Path] = None,
    processed_ids: Optional[Set[str]] = None,
    db_path: Optional[Union[Path, str]] = None,
    use_db: bool = True,
    allow_retry: bool = False,
) -> List[Dict[str, Any]]:
    """Identify due reminders and execute safe simulation for all eligible records.

    Enforces persistent SQLite duplicate protection and in-memory duplicate protection
    so reminders are never duplicated across restarts or during an active run.

    Args:
        reminders: Optional pre-loaded reminders DataFrame.
        contacts: Optional pre-loaded contacts DataFrame.
        now: Optional evaluation timestamp (defaults to current Asia/Kolkata time).
        output_dir: Optional override directory for .eml simulation output.
        processed_ids: Optional set tracking processed IDs (defaults to internal session set).
        db_path: Optional database path for persistent tracking.
        use_db: Whether to enforce SQLite persistence and atomic claims (default: True).
        allow_retry: Whether to retry previously 'FAILED' reminders (default: False).

    Returns:
        List[Dict[str, Any]]: List of structured processing results.
    """
    contacts_df = contacts if contacts is not None else load_contacts()
    reminders_df = reminders if reminders is not None else load_reminders(contacts=contacts_df)

    due_df = get_due_reminders(reminders_df, now=now)
    results: List[Dict[str, Any]] = []

    active_processed = processed_ids if processed_ids is not None else _PROCESSED_REMINDER_IDS

    target_db = Path(db_path) if db_path is not None else DB_PATH
    if use_db and not target_db.exists():
        init_db(target_db)

    for _, row in due_df.iterrows():
        rid = str(row["reminder_id"]).strip()
        cid = str(row.get("contact_id", "")).strip()
        subject = str(row.get("subject", "")).strip()

        # 1. In-memory duplicate check (session-level)
        if rid in active_processed:
            results.append({
                "reminder_id": rid,
                "contact_id": cid,
                "status": "SKIPPED",
                "subject": subject,
                "output_path": None,
                "error": "Already processed in current session (in-memory protection)",
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            })
            continue

        # 2. Persistent SQLite duplicate check and atomic claim
        if use_db:
            claim_result = claim_reminder_for_processing(
                row,
                db_path=target_db,
                allow_retry=allow_retry,
            )
            if not claim_result.success:
                if claim_result.status == "SIMULATED":
                    record_skipped_attempt(
                        rid,
                        reason="Already simulated in database",
                        db_path=target_db,
                    )
                results.append({
                    "reminder_id": rid,
                    "contact_id": cid,
                    "status": "SKIPPED",
                    "subject": subject,
                    "output_path": None,
                    "error": claim_result.reason,
                    "timestamp": datetime.now(TIMEZONE).isoformat(),
                })
                continue

        # 3. Execute single reminder simulation
        res = process_reminder(row, contacts=contacts_df, output_dir=output_dir)
        results.append(res)

        # 4. Record simulation result to persistent database
        if use_db:
            if res["status"] == "SIMULATED":
                record_simulation_success(
                    rid,
                    output_path=res["output_path"] or "",
                    db_path=target_db,
                )
                active_processed.add(rid)
            elif res["status"] == "FAILED":
                record_simulation_failure(
                    rid,
                    error_message=res["error"] or "Unknown error",
                    db_path=target_db,
                )
        else:
            if res["status"] == "SIMULATED":
                active_processed.add(rid)

    return results


def register_periodic_job(
    interval_seconds: int = 60,
    output_dir: Optional[Path] = None,
    db_path: Optional[Union[Path, str]] = None,
    use_db: bool = True,
    allow_retry: bool = False,
) -> schedule.Job:
    """Register a periodic reminder check job using the schedule library.

    The periodic job reloads and revalidates contacts and reminders before each run.

    Args:
        interval_seconds: Polling frequency in seconds (default: 60).
        output_dir: Optional override directory for simulation output.
        db_path: Optional database path.
        use_db: Whether to use database persistence (default: True).
        allow_retry: Whether to retry previously failed reminders.

    Returns:
        schedule.Job: Registered job instance.
    """
    def _scheduled_worker():
        contacts = load_contacts()
        reminders = load_reminders(contacts=contacts)
        return process_due_reminders(
            reminders=reminders,
            contacts=contacts,
            output_dir=output_dir,
            db_path=db_path,
            use_db=use_db,
            allow_retry=allow_retry,
        )

    job = schedule.every(interval_seconds).seconds.do(_scheduled_worker)
    return job


def run_pending_jobs() -> int:
    """Run all currently pending scheduled jobs once.

    Returns:
        int: Number of active jobs registered in schedule.
    """
    schedule.run_pending()
    return len(schedule.get_jobs())


def clear_scheduled_jobs() -> None:
    """Clear all registered jobs from the schedule library."""
    schedule.clear()


def start_scheduler_loop(
    interval_seconds: int = 5,
    max_iterations: Optional[int] = None,
    db_path: Optional[Union[Path, str]] = None,
    recover_stale: bool = True,
) -> None:
    """Run the continuous simulation scheduler loop.

    Can be terminated gracefully via Ctrl+C (KeyboardInterrupt) or max_iterations limit.

    Args:
        interval_seconds: Heartbeat polling interval in seconds.
        max_iterations: Optional loop limit (primarily for testing).
        db_path: Optional database path.
        recover_stale: Whether to recover any leftover PROCESSING records at startup.
    """
    iteration = 0
    print(f"[*] Starting Email Reminder Simulation Scheduler (Polling every {interval_seconds}s)...")
    print("[*] Press Ctrl+C to stop cleanly.")

    if recover_stale:
        target_db = Path(db_path) if db_path is not None else DB_PATH
        if target_db.exists():
            recovered = recover_stale_processing_reminders(db_path=target_db)
            if recovered > 0:
                print(f"[*] Recovered {recovered} reminder(s) from stale PROCESSING state to FAILED.")

    try:
        while True:
            schedule.run_pending()
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                print(f"[*] Max iterations ({max_iterations}) reached. Exiting scheduler loop.")
                break
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\n[*] Scheduler loop stopped cleanly by user.")
