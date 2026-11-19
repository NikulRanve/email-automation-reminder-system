# System Architecture

## 1. Architectural Overview

The **Email Automation & Reminder System** is structured into three clean, decoupled layers: **Input Layer**, **Processing Layer**, and **Output Layer**. This separation guarantees modularity, testability, and safe simulation without sending unintended emails.

```
┌─────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                          │
│   • Data Sources: data/contacts.csv, data/reminders.csv     │
│   • HTML Templates: templates/*.html                        │
│   • Environment & Configurations: .env / src/config.py      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      PROCESSING LAYER                       │
│   • Data Ingestion & Validation: contact_manager,           │
│     reminder_manager                                        │
│   • Template Engine & Content Assembly: email_generator     │
│   • Scheduling & Timing Logic: scheduler                    │
│   • State Persistence & Audit: database (SQLite)            │
│   • Application Logging: logger                             │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                        OUTPUT LAYER                         │
│   • Simulation Previews: outputs/simulated_emails/          │
│   • Execution & Audit Reports: outputs/reports/             │
│   • Interactive UI Dashboard: app.py (Streamlit)            │
│   • File Logs: logs/                                        │
│   • Delivery Gateway: email_sender (SMTP / Simulation)      │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Layer Breakdown

### 2.1 Input Layer
* **Contacts & Reminders Data (`data/`)**: Tabular CSV datasets storing recipient contacts (`contacts.csv`) and schedule items (`reminders.csv`) with contact IDs, reminder types, dates, times, and initial statuses.
* **HTML Templates (`templates/`)**: Semantic email templates (`interview_reminder.html`, `meeting_reminder.html`, `payment_reminder.html`, `webinar_reminder.html`) with consistent placeholders (`{{name}}`, `{{date}}`, `{{time}}`).
* **Environment Configuration (`.env.example` / `src/config.py`)**: Centralized application parameters, directory paths, and default operational modes (`EMAIL_MODE=simulation`).

### 2.2 Processing Layer
* **Contact & Reminder Managers (`contact_manager.py`, `reminder_manager.py`)**: Ingest and validate data, ensuring referential integrity (e.g. every reminder points to a valid contact).
* **Email Generator (`email_generator.py`)**: Merges contact records and reminder details into the corresponding HTML templates.
* **Scheduler (`scheduler.py`)**: Evaluates scheduled dates/times against `Asia/Kolkata` timezone to filter due pending items. Manages session-level duplicate suppression in memory and orchestrates batch email simulations.
* **Database & Persistence (`database.py`)**: SQLite-based persistent store for reminder states, attempt counters, audit logs, and atomic claim locks (`BEGIN IMMEDIATE`), ensuring zero duplicate dispatches across restarts.
* **Logger (`logger.py`)**: Centralizes structured logging across console and persistent file logs.

### 2.3 Output Layer
* **Simulated Previews (`outputs/simulated_emails/`)**: In simulation mode (the default), generated emails are saved as HTML/text files for inspection without contacting external servers.
* **Reporting & Analytics (`report_generator.py` / `outputs/reports/`)**: Queries SQLite states to export timestamped summary and detailed history CSV reports without mutating database state.
* **Streamlit Visual Dashboard (`app.py`)**: Browser-based interactive user interface displaying live KPI cards, reminder status distributions, activity timelines, audit search/filtering, and in-browser CSV download buttons.
* **Log Files (`logs/`)**: Persistent audit logs for debugging and monitoring.
* **Delivery Gateway (`email_sender.py`)**: Dispatches emails via SMTP when simulation mode is explicitly disabled.

---

## 3. Core Design Principles
* **Default Simulation**: The system defaults to simulation mode to prevent accidental live email dispatches.
* **Single Source of Truth**: SQLite maintains processing state and prevents duplicate reminders.
* **Zero Hardcoded Secrets**: Credentials are strictly loaded through environment variables.
