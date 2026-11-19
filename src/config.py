"""Configuration module for Email Automation & Reminder System.

Handles application configuration, paths, environment variable loading,
and simulation mode settings.
"""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Allowed email execution modes
ALLOWED_EMAIL_MODES = ("simulation", "smtp")

# Mode Configuration (Simulation is default)
EMAIL_MODE = os.getenv("EMAIL_MODE", "simulation").strip().lower()

if EMAIL_MODE not in ALLOWED_EMAIL_MODES:
    raise ValueError(
        f"Invalid EMAIL_MODE: '{EMAIL_MODE}'. Allowed values are: {ALLOWED_EMAIL_MODES}"
    )

# Helper boolean flag for quick checks
IS_SIMULATION = (EMAIL_MODE == "simulation")

# Directory Paths
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUTS_DIR = BASE_DIR / "outputs"
SIMULATED_EMAILS_DIR = OUTPUTS_DIR / "simulated_emails"
REPORTS_DIR = OUTPUTS_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"

# Database Configuration
DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/reminders.db")

# SMTP Configuration (loaded via environment variables - placeholders only)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.example.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "reminders@example.com")
SENDER_NAME = os.getenv("SENDER_NAME", "Email Reminder System")
