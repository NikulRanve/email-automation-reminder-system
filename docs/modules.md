# System Modules & Component Specifications

This document outlines the software modules, their class responsibilities, interfaces, and expected interactions within the **Email Automation & Reminder System**.

---

## 1. Module Inventory

```text
src/
├── __init__.py           # Package initialization
├── config.py             # System paths, environment variables, email mode configuration
├── contact_manager.py    # Contact CSV loading, validation, and ID lookup
├── reminder_manager.py   # Reminder CSV loading, referential validation, and contact filtering
├── email_generator.py    # Template loading, placeholder validation, and personalization
├── email_sender.py       # Email message construction and safe sending simulation
├── scheduler.py          # Timezone-aware scheduling, due-item evaluation, and simulation runner
├── database.py           # SQLite connection and delivery state tracking
├── logger.py             # Application and audit logging
└── report_generator.py   # Run summary and statistics generator
```

---

## 2. Contact Management Module (`src/contact_manager.py`)

### 2.1 Purpose
The `contact_manager.py` module loads recipient contacts from `data/contacts.csv`, verifies schema and values, trims whitespace in memory, and provides lookups by contact ID.

### 2.2 Contact CSV Schema
Columns: `contact_id`, `name`, `email`, `department`.

### 2.3 Running Contact Tests
```bash
pytest -v tests/test_contacts.py
```

---

## 3. Reminder Management Module (`src/reminder_manager.py`)

### 3.1 Purpose
The `reminder_manager.py` module loads reminder records from `data/reminders.csv`, enforces calendar date and 24-hour time compliance, verifies referential integrity against contacts, and provides contact-filtered lookups.

### 3.2 Reminder CSV Schema
Columns: `reminder_id`, `contact_id`, `reminder_type`, `subject`, `reminder_date`, `reminder_time`, `status`.

### 3.3 Running Reminder Tests
```bash
pytest -v tests/test_reminders.py
```

---

## 4. Email Generation Module (`src/email_generator.py`)

### 4.1 Purpose
Loads approved HTML templates (`interview`, `meeting`, `payment`, `webinar`), validates `{{name}}`, `{{date}}`, and `{{time}}` placeholders, and injects HTML-escaped dynamic values to prevent injection.

### 4.2 Running Email Generator Tests
```bash
pytest -v tests/test_email_generator.py
```

---

## 5. Email Sender & Simulation Module (`src/email_sender.py`)

### 5.1 Purpose & Responsibility
Constructs MIME `EmailMessage` instances and simulates safe sending by persisting `.eml` files into `outputs/simulated_emails/`. Real SMTP is disabled via `SmtpNotImplementedError`.

### 5.2 Running Email Sender Tests
```bash
pytest -v tests/test_email_sender.py
```

---

## 6. Reminder Scheduling & Processing Module (`src/scheduler.py`)

### 6.1 Purpose
The `scheduler.py` module orchestrates the end-to-end reminder processing cycle. It detects due pending reminders against the `Asia/Kolkata` timezone, resolves contacts, builds personalized HTML, triggers safe simulation dispatches, and tracks in-memory processed IDs.

### 6.2 Key Functions & Signatures
* `get_due_reminders(reminders: pd.DataFrame, now: Optional[datetime] = None) -> pd.DataFrame`:
  Filters reminders where `status == 'pending'` and scheduled datetime $\le$ `now` (localized to `Asia/Kolkata`). Leaves source DataFrame unaltered.
* `process_reminder(reminder: pd.Series | Dict[str, Any], contacts: pd.DataFrame, output_dir: Optional[Path] = None) -> Dict[str, Any]`:
  Processes a single reminder through contact resolution, personalization, message construction, and simulation. Returns a result dict with statuses:
  - `SIMULATED`: Email generated and saved to a `.eml` file.
  - `FAILED`: Error encountered (does not halt batch).
  - `SKIPPED`: Ineligible or previously processed.
* `process_due_reminders(reminders: Optional[pd.DataFrame] = None, contacts: Optional[pd.DataFrame] = None, now: Optional[datetime] = None, output_dir: Optional[Path] = None) -> List[Dict[str, Any]]`:
  Batches due reminder processing and suppresses duplicate processing during the active run.
* `register_periodic_job(interval_seconds: int = 60, output_dir: Optional[Path] = None) -> schedule.Job`:
  Registers a recurring polling worker with the `schedule` library.
* `start_scheduler_loop(interval_seconds: int = 5, max_iterations: Optional[int] = None)`:
  Initiates a continuous polling loop with graceful `KeyboardInterrupt` (Ctrl+C) shutdown.

### 6.3 Timezone Handling (`Asia/Kolkata`)
All date and time calculations are explicitly pinned to `zoneinfo.ZoneInfo("Asia/Kolkata")`:
* Injected naive datetimes are interpreted directly as `Asia/Kolkata` local time.
* Injected aware datetimes in other zones are converted using `.astimezone(TIMEZONE)`.
* System avoids depending on the host OS local timezone.

### 6.4 Persistent Duplicate Prevention & Database Integration
In Phase 8, `scheduler.py` coordinates with `src/database.py` for persistent duplicate protection:
- **Pre-check & Atomic Claim**: Calls `claim_reminder_for_processing` using `BEGIN IMMEDIATE` to prevent race conditions.
- **Persistent State**: Reminders marked `SIMULATED` in the database are permanently skipped across restarts.
- **Active Claim State (`PROCESSING`)**: Prevents concurrent processes from claiming the same reminder.
- **Session Layer**: Secondary in-memory set (`_PROCESSED_REMINDER_IDS`) remains active for session-level caching.

### 6.5 Running Scheduler Tests
```bash
pytest -v tests/test_scheduler.py
```

---

## 7. Database Module (`src/database.py`)

### 7.1 Purpose & Architecture
The `database.py` module manages SQLite persistence for reminder lifecycle states, execution history, and atomic claim transactions. It acts as the single source of truth for reminder processing, ensuring that a reminder successfully simulated is never duplicated even after application restarts.

### 7.2 Database Location & Configuration
- Path: `DB_PATH` from `src/config.py` (defaults to `data/reminders.db`).
- Does not create database files on module import. Explicit initialization via `init_db()` is required.

### 7.3 Schema & Constraints
#### `reminder_records` Table (Current State)
- `reminder_id` (TEXT PRIMARY KEY): Unique identifier of reminder.
- `contact_id` (TEXT NOT NULL): Recipient foreign reference.
- `reminder_type` (TEXT NOT NULL): `interview`, `meeting`, `payment`, `webinar`.
- `subject` (TEXT NOT NULL): Email subject line.
- `status` (TEXT NOT NULL): Constraint: `CHECK (status IN ('PENDING', 'PROCESSING', 'SIMULATED', 'FAILED'))`.
- `attempt_count` (INTEGER NOT NULL DEFAULT 0): Total processing attempts.
- `simulated_output_path` (TEXT): File system path to the saved `.eml` file.
- `error_message` (TEXT): Failure diagnostics, if applicable.
- `last_processed_at` (TEXT): ISO 8601 timestamp of last state transition.
- `created_at` (TEXT NOT NULL): Initial insertion timestamp.
- `updated_at` (TEXT NOT NULL): Record modification timestamp.

#### `reminder_history` Table (Immutable Audit Log)
- `history_id` (INTEGER PRIMARY KEY AUTOINCREMENT): Auto-incrementing log entry ID.
- `reminder_id` (TEXT NOT NULL): Foreign key referencing `reminder_records(reminder_id) ON DELETE CASCADE`.
- `attempt_number` (INTEGER NOT NULL): Sequence number of the attempt.
- `status` (TEXT NOT NULL): Status recorded during this transition (`PROCESSING`, `SIMULATED`, `FAILED`, `SKIPPED`, `PENDING`).
- `simulated_output_path` (TEXT): Path to `.eml` if applicable.
- `error_message` (TEXT): Diagnostic or skip reason.
- `timestamp` (TEXT NOT NULL): ISO 8601 timestamp.

### 7.4 Key Functions
- `init_db(db_path=None)`: Idempotently creates tables and performance indexes.
- `get_connection(db_path=None)`: Opens connection with `PRAGMA foreign_keys = ON;` and `sqlite3.Row`.
- `get_db_connection(db_path=None)`: Context manager safely closing connections.
- `claim_reminder_for_processing(reminder, db_path=None, allow_retry=False) -> ClaimResult`: Atomically claims a reminder with `BEGIN IMMEDIATE`.
- `record_simulation_success(reminder_id, output_path, db_path=None)`: Persists `SIMULATED` state and history.
- `record_simulation_failure(reminder_id, error_message, db_path=None)`: Persists `FAILED` state and history.
- `record_skipped_attempt(reminder_id, reason, db_path=None)`: Logs skipped attempts in history.
- `reset_failed_reminder_for_retry(reminder_id, db_path=None) -> bool`: Explicit retry function promoting `FAILED` to `PENDING`.
- `recover_stale_processing_reminders(target_status='FAILED', db_path=None) -> int`: Resets stuck `PROCESSING` records on recovery.
- `get_processing_history(reminder_id=None, limit=None, db_path=None) -> List[Dict]`: Queries audit trail.
- `get_processing_summary(db_path=None) -> Dict`: Aggregates status counts.

### 7.5 Running Database Tests
```bash
pytest -v tests/test_database.py
```

---

## 8. Reporting & Analytics Module (`src/report_generator.py`)

### 8.1 Purpose & Architecture
The `report_generator.py` module queries SQLite database state and audit logs to generate processing summaries, query historical events, and export non-destructive CSV reports into `outputs/reports/`. It acts purely as a read-only analytics consumer and never modifies reminder data or triggers email sending.

### 8.2 Key Functions & Signatures
* `generate_processing_summary(db_path: Optional[Path | str] = None) -> Dict[str, Any]`:
  Aggregates total reminders, status breakdowns (`SIMULATED`, `FAILED`, `PENDING`, `PROCESSING`), total attempt logs, and `SKIPPED` audit events.
* `get_detailed_processing_history(reminder_id=None, start_date=None, end_date=None, limit=None, db_path=None) -> List[Dict[str, Any]]`:
  Queries `reminder_history` with parameterized SQL filters. Supports `YYYY-MM-DD` and ISO 8601 strings and validates that `start_date <= end_date`.
* `export_summary_to_csv(output_dir=None, db_path=None) -> Path`:
  Exports processing metrics into a timestamped file `summary_report_YYYYMMDD_HHMMSS.csv` under `outputs/reports/`.
* `export_history_to_csv(reminder_id=None, start_date=None, end_date=None, output_dir=None, db_path=None) -> Path`:
  Exports history records into a timestamped file `history_report_YYYYMMDD_HHMMSS.csv` under `outputs/reports/`.
* `format_summary_console(summary: Dict[str, Any]) -> str`:
  Renders an aligned plain-text table for CLI presentation.

### 8.3 CLI Usage
```bash
# View processing summary and recent events on console
python main.py --report

# Export timestamped summary and history CSV files to outputs/reports/
python main.py --export-csv

# Combine summary display and CSV export
python main.py --report --export-csv
```

### 8.4 Running Report Generator Tests
```bash
pytest -v tests/test_report_generator.py
```

---

## 9. Streamlit Analytics Dashboard (`app.py`)

### 9.1 Purpose & Architecture
The `app.py` module delivers a browser-based visual dashboard for real-time monitoring, metrics analysis, audit log inspection, and on-demand report downloading. It integrates with `src/report_generator.py` and `src/database.py` without duplicating SQL queries or business logic. It operates strictly in a read-only reporting mode—it does not initialize the scheduler loop, claim reminders, or attempt live email dispatches. If the SQLite database file does not exist, `init_db()` is called idempotently to establish required tables and indexes.

### 9.2 Dashboard Components & Structure
The dashboard is structured into five cohesive sections:

1. **System Disclosures & Safety Header**:
   - Displays a prominent simulation warning banner: `EMAIL_MODE=simulation`.
   - Confirms that no real external emails are sent and SMTP connections are disabled.
2. **Section A: Overview (KPI Cards)**:
   - 7 key metrics powered by `generate_processing_summary()`:
     - `Total Reminders Registered`
     - `SIMULATED Emails`
     - `FAILED Reminders`
     - `PENDING Reminders`
     - `PROCESSING Reminders`
     - `Total Processing Attempts`
     - `Total SKIPPED Events`
3. **Section B: Analytics & Visualizations**:
   - Current Reminder State Distribution chart.
   - Processing History Events by Status chart.
   - Processing Activity Timeline over calendar dates.
   - Cross-platform architecture: Uses native Streamlit charts when `pyarrow` is available, with automatic fallback to `matplotlib` on environments without prebuilt pyarrow wheels (e.g. Windows ARM64).
4. **Section C: Processing History Table**:
   - Filterable by `reminder_id`, date range (`start_date`, `end_date`), and maximum rows.
   - Displays `history_id`, `reminder_id`, `attempt_number`, `status`, `timestamp`, `simulated_output_path`, and `error_message`.
   - Renders interactive dataframes or styled HTML tables gracefully.
5. **Section D: Reports & Direct CSV Download**:
   - Provides on-demand triggers for generating atomic `summary_report_*.csv` and `history_report_*.csv` files in `outputs/reports/`.
   - Integrates `st.download_button` so users can download reports directly in their browser without shell access.
6. **Section E: Sidebar Infrastructure Status**:
   - Displays active `EMAIL_MODE`, SQLite database file availability and path, reports directory status, simulated emails directory status, and system timezone (`Asia/Kolkata`).

### 9.3 Launch Command
```bash
streamlit run app.py
```

### 9.4 Running Dashboard Tests
```bash
pytest -v tests/test_dashboard.py
```

---

## 10. Future Modules (Phases 11+)

### 10.1 Logger Module (`src/logger.py`)
* Application logging and structured file rotation.
