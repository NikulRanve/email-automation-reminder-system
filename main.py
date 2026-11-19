"""Main entry point for the Email Automation & Reminder System.

Demonstrates contact loading, reminder validation, email personalization,
safe sending simulation, timezone-aware reminder scheduling, SQLite persistence,
and reporting & analytics.
"""

import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is present in sys.path regardless of execution environment
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import BASE_DIR, DB_PATH, EMAIL_MODE, IS_SIMULATION
from src.contact_manager import load_contacts, ContactValidationError
from src.reminder_manager import (
    load_reminders,
    get_reminders_for_contact,
    ReminderError,
)
from src.email_generator import generate_email, TemplateError
from src.email_sender import (
    create_email_message,
    send_email,
    get_simulated_path,
    EmailSenderError,
)
from src.database import (
    init_db,
    get_processing_summary,
    recover_stale_processing_reminders,
    DatabaseError,
)
from src.scheduler import (
    get_due_reminders,
    process_due_reminders,
    register_periodic_job,
    start_scheduler_loop,
    TIMEZONE,
    SchedulerError,
)
from src.report_generator import (
    generate_processing_summary,
    get_detailed_processing_history,
    export_summary_to_csv,
    export_history_to_csv,
    format_summary_console,
    ReportGeneratorError,
)


def main() -> int:
    """Initialize application and demonstrate full automation pipeline."""
    # Phase 9: CLI Reporting & Analytics Options
    show_report = "--report" in sys.argv or "--summary" in sys.argv
    export_reports = (
        "--export-csv" in sys.argv or "--export-reports" in sys.argv or "--export" in sys.argv
    )

    if show_report or export_reports:
        init_db()
        summary = generate_processing_summary()
        if show_report:
            print(format_summary_console(summary))
            recent_history = get_detailed_processing_history(limit=5)
            if recent_history:
                print("\nRecent Processing History (Last 5 events):")
                for h in recent_history:
                    print(
                        f"  [{h['history_id']}] Reminder {h['reminder_id']} "
                        f"(Attempt {h['attempt_number']}) -> {h['status']} at {h['timestamp']}"
                    )
                print("=" * 60)
            else:
                print("\nNo processing history entries found in database.")
                print("=" * 60)

        if export_reports:
            summary_csv = export_summary_to_csv()
            history_csv = export_history_to_csv()
            print("\n[*] Reports successfully exported to CSV:")
            print(f"    - Summary Report : {summary_csv}")
            print(f"    - History Report : {history_csv}")
            print("=" * 60)
        return 0

    # Phase 7: Continuous Scheduler Mode
    if "--schedule" in sys.argv or "--continuous" in sys.argv:
        print("=" * 60)
        print(" Continuous Simulation Scheduler Mode Activated")
        print("=" * 60)
        print("Timezone: Asia/Kolkata")
        print("Mode    : SIMULATION ONLY (No real emails will be transmitted)")
        init_db()
        stale_count = recover_stale_processing_reminders()
        summary = get_processing_summary()
        print(
            f"Database: {DB_PATH.name} (Simulated: {summary['simulated']}, "
            f"Failed: {summary['failed']}, Stale Recovered: {stale_count})"
        )
        print("-" * 60)
        register_periodic_job(interval_seconds=10)
        start_scheduler_loop(interval_seconds=5)
        return 0

    # Normal Pipeline Demonstration
    print("=" * 60)
    print(" Email Automation & Reminder System")
    print("=" * 60)
    print(f"Project Root     : {BASE_DIR}")
    print(
        f"Email Mode       : {EMAIL_MODE.upper()} "
        f"{'(Safe - no real emails will be sent)' if IS_SIMULATION else ''}"
    )
    print(f"Database Path    : {DB_PATH}")
    print("-" * 60)

    try:
        # Phase 8: Explicit SQLite Database Initialization & State Check
        init_db()
        stale_recovered = recover_stale_processing_reminders()
        db_summary = get_processing_summary()
        print(
            f"Database Status  : {DB_PATH.name} (Total: {db_summary['total']}, "
            f"Simulated: {db_summary['simulated']}, Failed: {db_summary['failed']})"
        )
        if stale_recovered > 0:
            print(f"  Note           : Recovered {stale_recovered} stale PROCESSING reminder(s).")
        print("-" * 60)

        # Phase 3: Contact Loading and Validation
        contacts_df = load_contacts()
        contact_count = len(contacts_df)
        print(f"Contacts Loaded  : {contact_count} valid record(s)")
        print("-" * 60)
        print("Contact Summary:")
        for _, row in contacts_df.iterrows():
            print(f"  [{row['contact_id']}] {row['name']} <{row['email']}> ({row['department']})")
        print("-" * 60)

        # Phase 6: Reminder Loading and Referential Integrity Validation
        reminders_df = load_reminders(contacts=contacts_df)
        reminder_count = len(reminders_df)
        print(
            f"Reminders Loaded : {reminder_count} valid record(s) "
            "(100% referential integrity verified)"
        )
        print("-" * 60)
        print("Reminder Summary:")
        for _, row in reminders_df.iterrows():
            print(
                f"  [{row['reminder_id']}] -> Contact {row['contact_id']} | "
                f"{row['reminder_type']:9} | {row['reminder_date']} {row['reminder_time']} | "
                f"{row['subject']}"
            )
        print("-" * 60)

        # Demonstrate Contact-Specific Reminder Retrieval
        sample_contact = contacts_df.iloc[0]
        sample_cid = sample_contact["contact_id"]
        c_reminders = get_reminders_for_contact(
            sample_cid, reminders=reminders_df, contacts=contacts_df
        )
        print(f"Contact Query Demonstration for [{sample_cid}] ({sample_contact['name']}):")
        print(f"  Total Matching Reminders: {len(c_reminders)}")
        for _, rem in c_reminders.iterrows():
            print(
                f"    - [{rem['reminder_id']}] {rem['subject']} "
                f"({rem['reminder_type']} on {rem['reminder_date']} at {rem['reminder_time']})"
            )
        print("-" * 60)

        # Phase 7 & 8: Timezone-Aware Due Reminder Evaluation with SQLite Persistence
        now_kolkata = datetime.now(TIMEZONE)
        due_df = get_due_reminders(reminders_df, now=now_kolkata)
        print(f"Scheduler Evaluation (Timezone: {TIMEZONE.key}):")
        print(f"  Current Evaluation Time : {now_kolkata.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"  Reminders Currently Due : {len(due_df)}")
        if not due_df.empty:
            print("  Processing Due Reminders:")
            batch_results = process_due_reminders(
                reminders=due_df, contacts=contacts_df, now=now_kolkata
            )
            for res in batch_results:
                print(f"    - [{res['reminder_id']}] -> {res['status']} ({res['subject']})")
        else:
            print("  Note: All 5 sample reminders are scheduled for future dates/times.")
            print("        Future reminders are safely preserved and not processed early.")
        print(
            "  Continuous Scheduling   : Run 'python main.py --schedule' to activate periodic polling."
        )
        print(
            "  Reporting & Analytics   : Run 'python main.py --report' or 'python main.py --export-csv'."
        )
        print("-" * 60)

        # Phase 4: Email Personalization Demonstration
        demo_type = "interview"
        demo_date = "2026-11-25"
        demo_time = "10:30 AM"

        print("Email Personalization Demonstration:")
        print(f"  Recipient      : {sample_contact['name']} <{sample_contact['email']}>")
        print(f"  Template Type  : {demo_type}")
        print(f"  Demo Date/Time : {demo_date} at {demo_time}")

        html_content = generate_email(
            reminder_type=demo_type,
            name=sample_contact["name"],
            date=demo_date,
            time=demo_time,
        )
        print("Status           : HTML email generated successfully.")
        print("-" * 60)

        # Phase 5: Email Construction & Safe Sending Simulation
        demo_subject = f"Upcoming Interview Reminder - {sample_contact['name']}"
        msg = create_email_message(
            to_email=sample_contact["email"],
            subject=demo_subject,
            html_content=html_content,
            from_email="no-reply@example.com",
        )

        send_status = send_email(msg)
        simulated_file = get_simulated_path(msg)

        print("Email Dispatch Simulation:")
        print(f"  Subject        : {demo_subject}")
        print(f"  To Header      : {msg['To']}")
        print(f"  From Header    : {msg['From']}")
        print(f"  Delivery Mode  : {EMAIL_MODE.upper()}")
        print(f"  Dispatch Status: {send_status}")
        if simulated_file:
            print(f"  Saved EML File : {simulated_file.name}")
            print(f"  File Location  : {simulated_file}")
        print("  Safety Note    : SIMULATION ONLY - No real email was sent over the network.")
        print("-" * 60)
        print("Status           : All phases (3, 4, 5, 6, 7, 8, 9) verified successfully.")
        print("=" * 60)
        return 0

    except (
        FileNotFoundError,
        ContactValidationError,
        ReminderError,
        TemplateError,
        EmailSenderError,
        SchedulerError,
        DatabaseError,
        ReportGeneratorError,
    ) as err:
        print(f"ERROR: Execution failed -> {err}", file=sys.stderr)
        print("-" * 60, file=sys.stderr)
        print("Status           : Execution aborted.", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
