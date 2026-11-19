# 📧 Email Automation & Reminder System

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Test Suite](https://img.shields.io/badge/tests-137%20passed-brightgreen.svg)](tests/)
[![Architecture](https://img.shields.io/badge/architecture-layered%20%26%20modular-informational.svg)](docs/architecture.md)
[![Safety Mode](https://img.shields.io/badge/mode-simulation%20only-success.svg)](src/config.py)

A production-grade, modular Python automation engine designed for reliable reminder scheduling, personalized HTML notification generation, persistent audit tracking, and real-time visual analytics.

Engineered with **offline-first simulation safety**, the system provides comprehensive end-to-end automation without risking unintended live email dispatches to real recipients.

---

## 📌 Problem Statement & Objectives

Managing operational notifications—such as interview invitations, sprint planning meetings, invoice payment reminders, and webinar links—manually is time-consuming and error-prone. In real-world business environments:
1. **Accidental Duplicate Emails** erode client trust and clutter inboxes.
2. **Timezone Miscalculations** lead to missed appointments and scheduling conflicts.
3. **Live Testing Hazards** can trigger catastrophic email storms to real customer addresses if SMTP connections are accidentally activated during development or demonstrations.

### Project Objectives
- **100% Referential Integrity**: Ingest tabular CSV data (`contacts.csv`, `reminders.csv`) with strict schema validation and foreign key verification.
- **Timezone-Aware Scheduling**: Pinned explicitly to `Asia/Kolkata` (IST, UTC+05:30) with deterministic due-time filtering.
- **Persistent Duplicate Protection**: Backed by SQLite (`data/reminders.db`) as the single source of truth; reminders simulated once are permanently skipped across restarts.
- **Atomic Concurrency Locks**: Implements `BEGIN IMMEDIATE` transactions to prevent race conditions across parallel worker processes.
- **Offline Simulation Safety**: Generates fully-formed MIME `.eml` files saved locally for inspection, keeping external SMTP disabled.
- **Interactive Analytics Dashboard**: Modern Streamlit web interface with 7 KPI cards, status charts, activity timelines, filterable audit tables, and in-browser CSV downloads.

---

## 🛡️ Safe Simulation Architecture

The system operates strictly in **Simulation Mode** (`EMAIL_MODE=simulation`) by default:
- **No External SMTP Transmissions**: The application makes zero outbound SMTP network connections.
- **MIME Serialization**: Emails are constructed using Python's standard `email.message.EmailMessage`, rendered with HTML alternatives, and written to disk as `.eml` files under `outputs/simulated_emails/`.
- **Inspection Ready**: Preview files can be opened and verified in standard email clients (Outlook, Apple Mail, Thunderbird) without sending a single network packet.

```
┌─────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                          │
│   • Data Sources: data/contacts.csv, data/reminders.csv     │
│   • HTML Templates: templates/*.html                        │
│   • Environment & Config: .env.example / src/config.py      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      PROCESSING LAYER                       │
│   • Validation & Referential Integrity: contact & reminder  │
│   • Sanitized Template Engine: email_generator (XSS-safe)   │
│   • Timezone Scheduling: scheduler (Asia/Kolkata)           │
│   • Atomic Persistence: database (SQLite BEGIN IMMEDIATE)   │
│   • Analytics & Reporting Engine: report_generator          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                        OUTPUT LAYER                         │
│   • Offline Previews: outputs/simulated_emails/*.eml        │
│   • Atomic Reports: outputs/reports/*.csv                   │
│   • Visual Analytics Dashboard: app.py (Streamlit)          │
│   • Terminal CLI: main.py (--report, --export-csv)          │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Key Features

- **Robust CSV Ingestion & Validation**: Trims whitespace in memory, verifies email formatting, enforces calendar dates and 24-hour times, and ensures 100% referential integrity without modifying source CSV files.
- **XSS-Safe HTML Personalization**: Dynamic placeholders (`{{name}}`, `{{date}}`, `{{time}}`) are sanitized via `html.escape()` before template insertion.
- **Timezone Precision (`Asia/Kolkata`)**: Resolves naive and aware datetimes against Indian Standard Time (`UTC+05:30`), avoiding host OS clock discrepancies.
- **Atomic Concurrency Protection**: Multiple OS processes can safely target the same database; `BEGIN IMMEDIATE` transaction locking guarantees only one worker claims a given reminder.
- **Persistent State Across Restarts**: System state transitions (`PENDING` $\rightarrow$ `PROCESSING` $\rightarrow$ `SIMULATED` / `FAILED`) are permanently recorded in SQLite.
- **Collision-Proof CSV Reporting**: Generates summary and detailed history CSV reports using atomic OS-level exclusive file creation (`O_CREAT | O_EXCL`), eliminating TOCTOU race conditions.
- **Streamlit Analytics Dashboard**: Real-time KPI metric cards, status distribution charts, activity timelines, searchable audit tables, and instant CSV download buttons.

---

## 🛠️ Technology Stack

| Layer | Technologies & Libraries |
|---|---|
| **Language** | Python 3.10+ (Tested on Python 3.13) |
| **Data Processing** | Pandas (tabular ingestion, DataFrame operations) |
| **Persistence** | SQLite3 (ACID transactions, foreign keys, indexing) |
| **Scheduling** | Schedule (periodic job registration, polling loops) |
| **Web Dashboard** | Streamlit (reactive web interface, KPI metrics, AppTest) |
| **Data Visualization** | Matplotlib (cross-platform fallback plotting) |
| **Configuration** | Python-Dotenv (environment variable isolation) |
| **Quality Assurance** | Pytest (137 automated unit and integration tests) |

---

## 📂 Project Directory Structure

```text
Email-Automation-Reminder-System/
├── data/
│   ├── contacts.csv           # Recipient contact records (ID, name, email, department)
│   ├── reminders.csv          # Scheduled reminders (ID, contact_id, type, date, time)
│   └── reminders.db           # SQLite persistent database (git-ignored)
├── templates/                 # Semantic HTML email templates
│   ├── interview_reminder.html
│   ├── meeting_reminder.html
│   ├── payment_reminder.html
│   └── webinar_reminder.html
├── src/                       # Modular application source code
│   ├── __init__.py
│   ├── config.py              # Configuration constants and environment loading
│   ├── contact_manager.py     # CSV loading, validation, and contact lookup
│   ├── reminder_manager.py    # Reminder loading and referential integrity check
│   ├── email_generator.py     # HTML template loading, escaping, and substitution
│   ├── email_sender.py        # MIME construction and safe .eml simulation storage
│   ├── scheduler.py           # Timezone scheduling and batch processing loop
│   ├── database.py            # SQLite schema, atomic claims, and state tracking
│   ├── report_generator.py    # Processing summary, SQL history query, and CSV exports
│   └── logger.py              # Logging configuration
├── outputs/                   # Generated output artifacts (git-ignored)
│   ├── simulated_emails/      # Generated MIME .eml preview files
│   └── reports/               # Timestamped CSV summary and history reports
├── docs/                      # Architectural and technical documentation
│   ├── architecture.md        # System architecture and layer breakdown
│   ├── data_flow.md           # End-to-end data flow and state transitions
│   ├── modules.md             # Detailed module and class specifications
│   ├── setup_guide.md         # Environment setup and execution walkthrough
│   ├── dataset.md             # Data dictionary and schema specifications
│   └── validation_and_testing.md # Testing protocols and verification benchmarks
├── tests/                     # Comprehensive automated test suite
│   ├── test_contacts.py       # Contact validation tests (14 tests)
│   ├── test_reminders.py      # Reminder validation and referential tests (18 tests)
│   ├── test_email_generator.py # Template rendering and escaping tests (16 tests)
│   ├── test_email_sender.py   # Safe simulation dispatch tests (17 tests)
│   ├── test_scheduler.py      # Timezone scheduling and due filtering tests (18 tests)
│   ├── test_database.py       # Atomic claim, concurrency, and persistence tests (19 tests)
│   ├── test_report_generator.py # Reporting, metrics, and CSV safety tests (17 tests)
│   ├── test_dashboard.py      # Streamlit dashboard and AppTest tests (18 tests)
│   └── verify_separate_process.py # Standalone dual-process restart test
├── images/                    # Visual tour assets and documentation screenshots
├── main.py                    # CLI application entry point
├── app.py                     # Streamlit analytics dashboard entry point
├── requirements.txt           # Declared third-party dependencies
├── .env.example               # Template environment configuration (safe placeholders)
├── .gitignore                 # Version control exclusions
└── LICENSE                    # MIT open-source license
```

---

## ⚙️ Installation & Setup

### 1. Prerequisites
- **Python 3.10** or higher installed.
- Standard package installer: `pip`.

### 2. Environment Setup
Clone or download the project folder, then navigate to the root directory:

```bash
# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy the sample environment file:

```bash
# Windows (PowerShell):
Copy-Item .env.example .env

# Linux / macOS:
cp .env.example .env
```

Verify that `.env` contains:
```ini
EMAIL_MODE=simulation
DB_PATH=data/reminders.db
```

---

## 💻 Usage & CLI Guide

The system supports multiple operational modes through `main.py` and `app.py`:

### 1. Standard Single-Run Pipeline
Loads contacts, validates reminders, claims due items, and generates `.eml` previews:
```bash
python main.py
```

### 2. Continuous Background Scheduler
Runs periodic polling cycles checking for due reminders against `Asia/Kolkata` time:
```bash
python main.py --schedule
```
*(Press `Ctrl+C` to cleanly exit the loop).*

### 3. Display Processing Summary & Audit History
Queries SQLite and outputs an aligned text report of current states and recent audit events:
```bash
python main.py --report
```

### 4. Export Timestamped CSV Reports
Atomically exports summary metrics and detailed audit logs into `outputs/reports/`:
```bash
python main.py --export-csv
```

### 5. Combined Report & Export
Displays console summary and generates CSV files in one step:
```bash
python main.py --report --export-csv
```

### 6. Launch Interactive Streamlit Dashboard
Starts the local analytics web dashboard:
```bash
streamlit run app.py
```
Open your browser to `http://localhost:8501` to view real-time metrics, interactive status charts, filterable audit tables, and download reports with one click.

---

## 🧪 Testing & Quality Assurance

The project enforces rigorous verification with **137 automated tests** across all subsystems:

```bash
# Run the complete test suite
python -m pytest -v tests/
```

### Multi-Process Concurrency Test
To verify persistent duplicate prevention across two independent OS-level Python processes:
```bash
python tests/verify_separate_process.py
```
*Process A claims and simulates a reminder; Process B starts fresh with empty memory and is strictly rejected by SQLite, guaranteeing zero duplicate `.eml` files.*

---

## 📸 Screenshots & Visual Tour

The `images/` directory is prepared for documentation visuals:

| Target Visual | File Reference | Description |
|---|---|---|
| **Dashboard Overview** | `images/dashboard_overview.png` | 7 KPI cards showing registered, simulated, failed, and pending counts. |
| **Analytics Visualizations** | `images/analytics_charts.png` | Reminder status distribution bar charts and throughput timeline. |
| **Audit History Table** | `images/processing_history.png` | Filterable table showing reminder ID, attempt sequence, and timestamps. |
| **CSV Report Export** | `images/reports_download.png` | On-demand CSV report generation and direct browser download buttons. |
| **Terminal CLI Execution** | `images/cli_summary.png` | Clean aligned ASCII output from `python main.py --report`. |

---

## ⚠️ Known Limitations & Design Boundaries

1. **Decoupled Background Polling**: The Streamlit dashboard is intentionally read-only and does not launch the scheduler loop. Background reminder processing should run independently via `python main.py --schedule`.
2. **Local Storage**: Designed for departmental automation using file-based SQLite and local `.eml` output directories rather than distributed cloud databases.
3. **Simulation Boundary**: Real SMTP delivery is disabled by design. Converting the system to live delivery requires switching `EMAIL_MODE=smtp` in `.env` and configuring a valid SMTP host.

---

## 📜 License

This project is licensed under the terms of the [MIT License](LICENSE).
