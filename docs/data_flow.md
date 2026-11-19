# Data Flow Architecture

This document describes how data enters, transitions through, and leaves the **Email Automation & Reminder System**.

---

## 1. End-to-End Reminder Scheduling & Persistence Pipeline (Phase 8)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. DATA INGESTION & REFERENTIAL INTEGRITY                   │
│    • Load validated contacts (data/contacts.csv)            │
│    • Load validated reminders (data/reminders.csv)          │
│    • Verify foreign key relations (contact_id)              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. TIMEZONE-AWARE DUE-ITEM FILTERING                        │
│    • Pinned to Asia/Kolkata (IST, UTC+05:30)                │
│    • Filter: status == 'pending' in CSV                     │
│    • Filter: (reminder_date + reminder_time) <= now_kolkata │
│    • Future reminders strictly excluded                     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. PERSISTENT SQLITE ATOMIC CLAIM (Phase 8)                 │
│    • Open BEGIN IMMEDIATE transaction (exclusive lock)      │
│    • Check reminder_records:                                │
│      - If SIMULATED -> Reject (persistent duplicate skip)   │
│      - If PROCESSING -> Reject (concurrent worker active)   │
│      - If FAILED -> Reject unless explicit retry requested   │
│      - If NEW or PENDING -> Claim with status 'PROCESSING'  │
│    • Record 'PROCESSING' entry in reminder_history          │
│    • Commit claim transaction                               │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. TEMPLATE PERSONALIZATION & SANITIZATION                  │
│    • Map reminder_type to template file                     │
│    • Resolve contact name, date, time                       │
│    • Apply html.escape(val, quote=True)                     │
│    • Substitute placeholders ({{name}}, {{date}}, {{time}}) │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. MESSAGE CONSTRUCTION & SAFE SIMULATION DISPATCH          │
│    • Build standard MIME EmailMessage                       │
│    • Set headers (To, From, Subject)                        │
│    • Attach text/html alternative part                      │
│    • Serialize to outputs/simulated_emails/*.eml (UTF-8)    │
│    • Return result status: SIMULATED                        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. PERSISTENT OUTCOME & AUDIT LOGGING                       │
│    • If Success:                                            │
│      - UPDATE reminder_records SET status = 'SIMULATED',    │
│        simulated_output_path = ..., updated_at = ...        │
│      - INSERT into reminder_history ('SIMULATED', attempt)  │
│      - Add reminder_id to in-memory _PROCESSED_REMINDER_IDS │
│    • If Failure:                                            │
│      - UPDATE reminder_records SET status = 'FAILED',       │
│        error_message = ..., updated_at = ...                │
│      - INSERT into reminder_history ('FAILED', attempt)     │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Core Data Schemas

### 2.1 Contact DTO
```json
{
  "contact_id": "C001",
  "name": "Alice Johnson",
  "email": "alice.johnson@example.com",
  "department": "Engineering"
}
```

### 2.2 Reminder DTO
```json
{
  "reminder_id": "R001",
  "contact_id": "C001",
  "reminder_type": "meeting",
  "subject": "Sprint Planning Sync",
  "reminder_date": "2026-11-20",
  "reminder_time": "10:00",
  "status": "pending"
}
```

### 2.3 Processing Result Schema
```json
{
  "reminder_id": "R001",
  "contact_id": "C001",
  "status": "SIMULATED",
  "subject": "Sprint Planning Sync",
  "output_path": "outputs/simulated_emails/simulated_20261118_224440_560388_alice.johnson_example.com.eml",
  "error": null,
  "timestamp": "2026-11-18T22:44:40+05:30"
}
```

---

## 3. Duplicate Suppression & State Transitions

* `DRAFT` / `PENDING`: Stored in CSV, awaiting scheduled execution time.
* `SIMULATED`: Formatted, sanitized, and stored as `.eml` simulation file. Added to session-level `_PROCESSED_REMINDER_IDS`.
* `SKIPPED`: Detected as already processed in the current running session.
* `FAILED`: Gracefully captured on data or template error without halting the batch.

---

## 4. Reporting & Analytics Data Flow (Phase 9)

```
┌───────────────────────────────────────────────┐
│ SQLite Database (data/reminders.db)           │
│   • reminder_records (Current status counts)  │
│   • reminder_history (Chronological attempts) │
└───────────────────────┬───────────────────────┘
                        │ Read-only Parameterized Queries
                        ▼
┌───────────────────────────────────────────────┐
│ Report Generator (src/report_generator.py)    │
│   • Aggregates summary statistics             │
│   • Filters history by reminder_id/date range │
│   • Validates date boundaries                 │
└───────────────────────┬───────────────────────┘
                        │
         ┌──────────────┴──────────────┐
         ▼                             ▼
┌──────────────────┐          ┌───────────────────────────────────┐
│ Console Display  │          │ CSV Export (outputs/reports/)     │
│ (--report)       │          │   • summary_report_*.csv          │
│ Aligned text     │          │   • history_report_*.csv          │
└──────────────────┘          └───────────────────────────────────┘
```

---

## 5. Streamlit Dashboard Data Flow (Phase 10)

```
┌────────────────────────────────────────────────────────┐
│ SQLite Database (data/reminders.db)                    │
│   • reminder_records (Current states)                  │
│   • reminder_history (Audit log events)                │
└──────────────────────────┬─────────────────────────────┘
                           │ (Read-Only Connection)
                           ▼
┌────────────────────────────────────────────────────────┐
│ Backend Services (src/report_generator.py)             │
│   • generate_processing_summary()                      │
│   • get_detailed_processing_history()                  │
│   • export_summary_to_csv() / export_history_to_csv()   │
└──────────────────────────┬─────────────────────────────┘
                           │ DataFrames & Dictionaries
                           ▼
┌────────────────────────────────────────────────────────┐
│ Streamlit Application Layer (app.py)                   │
│   ├── Safety Disclosure (Simulation Notice)            │
│   ├── Overview: 7 KPI Cards (st.metric)                │
│   ├── Analytics: Bar & Timeline Charts                 │
│   ├── History: Searchable / Filterable Audit Table     │
│   └── Reports: Atomic CSV Triggers & Direct Downloads  │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ User Browser UI (Localhost Web Interface)              │
│   • Interactive metrics, visualizations, and downloads │
│   • Zero SMTP transmissions, 100% sandboxed & safe     │
└────────────────────────────────────────────────────────┘
```
