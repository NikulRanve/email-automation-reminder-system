"""Automated tests for SQLite database integration module (Phase 8)."""

from datetime import datetime
from pathlib import Path
import sqlite3
import pytest
import pandas as pd

from src.database import (
    init_db,
    get_connection,
    get_db_connection,
    get_reminder_status,
    claim_reminder_for_processing,
    record_simulation_success,
    record_simulation_failure,
    record_skipped_attempt,
    reset_failed_reminder_for_retry,
    recover_stale_processing_reminders,
    get_processing_history,
    get_processing_summary,
    clear_all_reminders,
    ClaimResult,
    DatabaseConnectionError,
    TIMEZONE,
)
from src.contact_manager import load_contacts
from src.scheduler import (
    process_due_reminders,
    reset_processed_reminders,
    get_processed_reminder_ids,
)


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Fixture providing an initialized temporary SQLite database path."""
    db_file = tmp_path / "test_reminders.db"
    init_db(db_file)
    return db_file


@pytest.fixture
def sample_reminder_dict() -> dict:
    """Fixture providing sample reminder dict for testing."""
    return {
        "reminder_id": "R001",
        "contact_id": "C001",
        "reminder_type": "meeting",
        "subject": "Sprint Planning Sync",
        "reminder_date": "2026-11-20",
        "reminder_time": "10:00",
        "status": "pending",
    }


# 1. Database initialization and table creation
def test_init_db_creates_tables_and_indexes(test_db: Path):
    """Verify that init_db creates reminder_records and reminder_history tables with indexes."""
    with get_db_connection(test_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cursor.fetchall()}
        assert "reminder_records" in tables
        assert "reminder_history" in tables

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_reminder_records_status" in indexes
        assert "idx_reminder_history_reminder" in indexes


# 2. Database initialization is idempotent
def test_init_db_idempotent_safe_to_run_repeatedly(test_db: Path, sample_reminder_dict: dict):
    """Verify that running init_db repeatedly does not raise errors or clear existing data."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)

    # Re-run init_db
    init_db(test_db)
    init_db(test_db)

    # Data must be preserved
    status = get_reminder_status("R001", db_path=test_db)
    assert status is not None
    assert status["reminder_id"] == "R001"


# 3. Foreign key enforcement
def test_get_connection_enforces_foreign_keys(test_db: Path):
    """Verify that foreign keys are enforced and inserting orphan history records fails."""
    with pytest.raises(sqlite3.IntegrityError):
        with get_db_connection(test_db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO reminder_history (reminder_id, attempt_number, status, timestamp)
                VALUES ('NON_EXISTENT_R', 1, 'PROCESSING', '2026-11-20T10:00:00')
                """
            )
            conn.commit()


# 4. Context manager connection safety
def test_get_db_connection_context_manager_closes_connection(test_db: Path):
    """Verify context manager automatically closes SQLite connection upon exit."""
    captured_conn = None
    with get_db_connection(test_db) as conn:
        captured_conn = conn
        assert conn.total_changes >= 0

    # Connection should be closed now
    with pytest.raises(sqlite3.ProgrammingError):
        captured_conn.execute("SELECT 1")


# 5. Atomic claim: new reminder
def test_claim_reminder_new_record_success(test_db: Path, sample_reminder_dict: dict):
    """Verify a newly encountered reminder is claimed in 'PROCESSING' state with attempt 1."""
    claim = claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    assert claim.success is True
    assert claim.status == "PROCESSING"
    assert claim.attempt_number == 1

    status = get_reminder_status("R001", db_path=test_db)
    assert status is not None
    assert status["status"] == "PROCESSING"
    assert status["attempt_count"] == 1

    history = get_processing_history(reminder_id="R001", db_path=test_db)
    assert len(history) == 1
    assert history[0]["status"] == "PROCESSING"


# 6. Atomic claim: reject already simulated reminder
def test_claim_reminder_already_simulated_rejected(test_db: Path, sample_reminder_dict: dict):
    """Verify a reminder already in 'SIMULATED' status cannot be claimed (persistent duplicate protection)."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    record_simulation_success("R001", output_path="outputs/sim.eml", db_path=test_db)

    # Second claim attempt
    second_claim = claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    assert second_claim.success is False
    assert second_claim.status == "SIMULATED"
    assert "Already successfully simulated" in second_claim.reason


# 7. Atomic claim: reject active processing reminder
def test_claim_reminder_already_processing_rejected(test_db: Path, sample_reminder_dict: dict):
    """Verify a reminder currently in 'PROCESSING' cannot be claimed concurrently."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)

    competing_claim = claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    assert competing_claim.success is False
    assert competing_claim.status == "PROCESSING"
    assert "currently being processed" in competing_claim.reason


# 8. Atomic claim: reject failed reminder without explicit retry
def test_claim_reminder_failed_rejected_without_retry(test_db: Path, sample_reminder_dict: dict):
    """Verify a FAILED reminder is skipped unless allow_retry is explicitly True."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    record_simulation_failure("R001", error_message="Template error", db_path=test_db)

    # Polling cycle tries to claim without retry flag
    cycle_claim = claim_reminder_for_processing(sample_reminder_dict, db_path=test_db, allow_retry=False)
    assert cycle_claim.success is False
    assert cycle_claim.status == "FAILED"
    assert "retry not requested" in cycle_claim.reason


# 9. Atomic claim: allow failed reminder with explicit retry
def test_claim_reminder_failed_accepted_with_allow_retry(test_db: Path, sample_reminder_dict: dict):
    """Verify a FAILED reminder is claimed when allow_retry=True, incrementing attempt count."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    record_simulation_failure("R001", error_message="Network glitch", db_path=test_db)

    retry_claim = claim_reminder_for_processing(sample_reminder_dict, db_path=test_db, allow_retry=True)
    assert retry_claim.success is True
    assert retry_claim.status == "PROCESSING"
    assert retry_claim.attempt_number == 2

    status = get_reminder_status("R001", db_path=test_db)
    assert status["attempt_count"] == 2
    assert status["status"] == "PROCESSING"


# 10. Record simulation success
def test_record_simulation_success_updates_record_and_history(test_db: Path, sample_reminder_dict: dict):
    """Verify record_simulation_success updates status, path, and writes audit history."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    sim_path = "outputs/simulated_emails/test.eml"
    record_simulation_success("R001", output_path=sim_path, db_path=test_db)

    status = get_reminder_status("R001", db_path=test_db)
    assert status["status"] == "SIMULATED"
    assert status["simulated_output_path"] == sim_path
    assert status["error_message"] is None

    history = get_processing_history("R001", db_path=test_db)
    assert len(history) == 2  # PROCESSING + SIMULATED
    assert history[1]["status"] == "SIMULATED"
    assert history[1]["simulated_output_path"] == sim_path


# 11. Record simulation failure
def test_record_simulation_failure_updates_record_and_history(test_db: Path, sample_reminder_dict: dict):
    """Verify record_simulation_failure persists failure diagnostics and history."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    record_simulation_failure("R001", error_message="Contact C999 not found", db_path=test_db)

    status = get_reminder_status("R001", db_path=test_db)
    assert status["status"] == "FAILED"
    assert "Contact C999 not found" in status["error_message"]

    history = get_processing_history("R001", db_path=test_db)
    assert len(history) == 2  # PROCESSING + FAILED
    assert history[1]["status"] == "FAILED"
    assert "Contact C999 not found" in history[1]["error_message"]


# 12. Record skipped attempt in history
def test_record_skipped_attempt_records_in_history(test_db: Path, sample_reminder_dict: dict):
    """Verify record_skipped_attempt appends SKIPPED audit entry in history."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    record_simulation_success("R001", output_path="outputs/sim.eml", db_path=test_db)

    record_skipped_attempt("R001", reason="Duplicate poll cycle skip", db_path=test_db)

    history = get_processing_history("R001", db_path=test_db)
    assert len(history) == 3  # PROCESSING + SIMULATED + SKIPPED
    assert history[2]["status"] == "SKIPPED"
    assert history[2]["error_message"] == "Duplicate poll cycle skip"


# 13. Processing history retrieval and filtering
def test_get_processing_history_ordering_and_filtering(test_db: Path):
    """Verify get_processing_history filters by reminder_id and respects limit."""
    r1 = {"reminder_id": "R1", "contact_id": "C1", "reminder_type": "meeting", "subject": "S1"}
    r2 = {"reminder_id": "R2", "contact_id": "C2", "reminder_type": "meeting", "subject": "S2"}

    claim_reminder_for_processing(r1, db_path=test_db)
    record_simulation_success("R1", "out1.eml", db_path=test_db)

    claim_reminder_for_processing(r2, db_path=test_db)
    record_simulation_failure("R2", "err", db_path=test_db)

    all_history = get_processing_history(db_path=test_db)
    assert len(all_history) == 4

    r1_history = get_processing_history(reminder_id="R1", db_path=test_db)
    assert len(r1_history) == 2
    assert all(h["reminder_id"] == "R1" for h in r1_history)

    limited = get_processing_history(limit=2, db_path=test_db)
    assert len(limited) == 2


# 14. Processing summary counts
def test_get_processing_summary_counts(test_db: Path):
    """Verify get_processing_summary aggregates counts accurately."""
    r1 = {"reminder_id": "R1", "contact_id": "C1", "reminder_type": "meeting", "subject": "S1"}
    r2 = {"reminder_id": "R2", "contact_id": "C2", "reminder_type": "meeting", "subject": "S2"}
    r3 = {"reminder_id": "R3", "contact_id": "C3", "reminder_type": "meeting", "subject": "S3"}

    claim_reminder_for_processing(r1, db_path=test_db)
    record_simulation_success("R1", "out.eml", db_path=test_db)

    claim_reminder_for_processing(r2, db_path=test_db)
    record_simulation_failure("R2", "err", db_path=test_db)

    claim_reminder_for_processing(r3, db_path=test_db)  # Stays PROCESSING

    summary = get_processing_summary(db_path=test_db)
    assert summary["total"] == 3
    assert summary["simulated"] == 1
    assert summary["failed"] == 1
    assert summary["processing"] == 1
    assert summary["pending"] == 0


# 15. Explicit retry reset for FAILED reminders
def test_reset_failed_reminder_for_retry(test_db: Path, sample_reminder_dict: dict):
    """Verify reset_failed_reminder_for_retry promotes FAILED to PENDING and rejects SIMULATED."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    record_simulation_failure("R001", error_message="Transient error", db_path=test_db)

    # Successfully reset
    reset_ok = reset_failed_reminder_for_retry("R001", db_path=test_db)
    assert reset_ok is True
    status = get_reminder_status("R001", db_path=test_db)
    assert status["status"] == "PENDING"

    # Cannot reset non-existent or simulated reminder
    assert reset_failed_reminder_for_retry("R_UNKNOWN", db_path=test_db) is False


# 16. Recovery of stale PROCESSING reminders
def test_recover_stale_processing_reminders(test_db: Path, sample_reminder_dict: dict):
    """Verify recover_stale_processing_reminders marks leftover PROCESSING as FAILED."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    # Simulate application crash while in PROCESSING

    recovered = recover_stale_processing_reminders(target_status="FAILED", db_path=test_db)
    assert recovered == 1

    status = get_reminder_status("R001", db_path=test_db)
    assert status["status"] == "FAILED"
    assert "Recovered from stale PROCESSING" in status["error_message"]

    # Running again should recover 0
    assert recover_stale_processing_reminders(db_path=test_db) == 0


# 17. Persistent duplicate prevention across application restarts (Core Phase 8 Guarantee)
def test_persistent_duplicate_prevention_across_restarts(test_db: Path, tmp_path: Path):
    """Verify that after in-memory state is wiped (simulating restart), DB prevents re-simulation."""
    contacts_df = load_contacts()
    eval_time = datetime(2026, 11, 20, 10, 5, tzinfo=TIMEZONE)

    data = [{
        "reminder_id": "R001",
        "contact_id": "C001",
        "reminder_type": "meeting",
        "subject": "Sprint Planning Sync",
        "reminder_date": "2026-11-20",
        "reminder_time": "10:00",
        "status": "pending",
    }]
    reminders_df = pd.DataFrame(data)

    # First run (session 1)
    run1 = process_due_reminders(
        reminders=reminders_df,
        contacts=contacts_df,
        now=eval_time,
        output_dir=tmp_path,
        db_path=test_db,
        use_db=True,
    )
    assert len(run1) == 1
    assert run1[0]["status"] == "SIMULATED"
    eml_files_run1 = list(tmp_path.glob("*.eml"))
    assert len(eml_files_run1) == 1

    # SIMULATE APPLICATION RESTART:
    # Clear in-memory duplicate set without touching test_db
    reset_processed_reminders(reset_db=False)
    assert len(get_processed_reminder_ids()) == 0

    # Second run (session 2 after restart) with identical due reminder
    run2 = process_due_reminders(
        reminders=reminders_df,
        contacts=contacts_df,
        now=eval_time,
        output_dir=tmp_path,
        db_path=test_db,
        use_db=True,
    )
    assert len(run2) == 1
    assert run2[0]["status"] == "SKIPPED"
    assert "Already successfully simulated in database" in run2[0]["error"]

    # Verify no new .eml file was created
    eml_files_run2 = list(tmp_path.glob("*.eml"))
    assert len(eml_files_run2) == 1


# 18. ClaimResult interface helper
def test_claim_result_boolean_and_unpacking():
    """Verify ClaimResult behaves as a boolean, supports tuple unpacking, and reports attributes."""
    success_claim = ClaimResult(True, "Claimed", status="PROCESSING", attempt_number=1)
    failed_claim = ClaimResult(False, "Already simulated", status="SIMULATED", attempt_number=1)

    assert bool(success_claim) is True
    assert bool(failed_claim) is False

    is_ok, reason = success_claim
    assert is_ok is True
    assert reason == "Claimed"

    assert "PROCESSING" in repr(success_claim)


# 19. Clear all reminders test helper
def test_clear_all_reminders(test_db: Path, sample_reminder_dict: dict):
    """Verify clear_all_reminders deletes all records from reminder_records and reminder_history."""
    claim_reminder_for_processing(sample_reminder_dict, db_path=test_db)
    record_simulation_success("R001", "out.eml", db_path=test_db)

    clear_all_reminders(test_db)
    summary = get_processing_summary(test_db)
    assert summary["total"] == 0
    assert len(get_processing_history(db_path=test_db)) == 0
