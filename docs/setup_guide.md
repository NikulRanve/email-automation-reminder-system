# Setup Guide

This guide walks you through setting up the local environment and running the **Email Automation & Reminder System**.

---

## 1. Prerequisites

* **Python 3.10+** installed on your system.
* Standard package manager: `pip`.

---

## 2. Environment Setup

### 2.1 Clone or Open Repository
Navigate to the root directory of the project:
```bash
cd "Email-Automation-Reminder-System"
```

### 2.2 Create and Activate a Virtual Environment
* **Windows (PowerShell)**:
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```
* **Linux / macOS**:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

### 2.3 Install Dependencies
Install the required packages:
```bash
pip install -r requirements.txt
```

---

## 3. Configuration

1. Copy the sample environment file to create your local `.env`:
   * **Windows (PowerShell)**:
     ```powershell
     Copy-Item .env.example .env
     ```
   * **Linux / macOS**:
     ```bash
     cp .env.example .env
     ```
2. Verify settings in `.env`:
   - By default, `EMAIL_MODE=simulation` is enabled. In this mode, no real emails are transmitted; generated messages are written to `outputs/simulated_emails/`.
   - Ensure `DB_PATH=data/reminders.db` is configured.

---

## 4. Running the Application

### 4.1 CLI Execution Modes
Execute the application from the project root:
```bash
# Normal demonstration pipeline
python main.py

# Continuous simulation scheduler mode
python main.py --schedule

# View processing summary and recent audit events
python main.py --report

# Export summary and history CSV reports to outputs/reports/
python main.py --export-csv
```

### 4.2 Streamlit Analytics Dashboard
Launch the visual web dashboard:
```bash
streamlit run app.py
```

Expected behavior:
* Streamlit launches a local web server (defaults to `http://localhost:8501`).
* The browser automatically opens to display the 5 dashboard sections (Overview KPIs, Analytics Charts, Filterable History, CSV Downloads, and System Status).
* Safety disclosures prominently indicate `EMAIL_MODE=simulation`. No emails or SMTP connections will ever be initiated by the dashboard.
