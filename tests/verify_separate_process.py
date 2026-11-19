"""Demonstration of persistent duplicate prevention across two separate OS processes.

This script launches two separate OS-level Python processes (Process A and Process B)
pointing to the same temporary SQLite database file to verify that:
1. Process A claims and simulates a reminder, persisting it as 'SIMULATED'.
2. Process A terminates (clearing any process memory).
3. Process B starts as an independent OS process with clean memory.
4. Process B attempts to claim the same reminder and is rejected.
5. Zero additional .eml simulation artifacts are generated.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    python = sys.executable
    project_root = Path(__file__).resolve().parent.parent

    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "separate_process_test.db")
    output_dir = os.path.join(temp_dir, "eml_output")
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 70)
    print("SEPARATE-PROCESS PERSISTENT DUPLICATE PREVENTION TEST")
    print("=" * 70)
    print(f"Shared SQLite Database: {db_file}")
    print(f"Shared EML Output Dir : {output_dir}")
    print("-" * 70)

    # Code executed inside Process A
    code_proc_a = f"""
import sys, os
sys.path.insert(0, r"{project_root}")
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from src.database import init_db
from src.scheduler import process_due_reminders

db_path = r"{db_file}"
out_dir = r"{output_dir}"

init_db(db_path)

contacts_df = pd.DataFrame([{{
    "contact_id": "C001",
    "name": "Alice Johnson",
    "email": "alice.johnson@example.com",
    "department": "Engineering"
}}])

reminders_df = pd.DataFrame([{{
    "reminder_id": "R001",
    "contact_id": "C001",
    "reminder_type": "meeting",
    "subject": "Sprint Planning Sync",
    "reminder_date": "2026-11-20",
    "reminder_time": "10:00",
    "status": "pending"
}}])

eval_time = datetime(2026, 11, 20, 10, 5, tzinfo=ZoneInfo("Asia/Kolkata"))

print("[Process A] Starting with PID:", os.getpid())
results = process_due_reminders(
    reminders=reminders_df,
    contacts=contacts_df,
    now=eval_time,
    output_dir=out_dir,
    db_path=db_path,
    use_db=True
)
print("[Process A] Result Status:", results[0]["status"])
eml_files = [f for f in os.listdir(out_dir) if f.endswith('.eml')]
print("[Process A] Generated EML Files:", len(eml_files))
print("[Process A] Exiting cleanly.")
"""

    # Code executed inside Process B
    code_proc_b = f"""
import sys, os
sys.path.insert(0, r"{project_root}")
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from src.database import get_reminder_status, claim_reminder_for_processing
from src.scheduler import process_due_reminders

db_path = r"{db_file}"
out_dir = r"{output_dir}"

print("[Process B] Starting with PID:", os.getpid())

contacts_df = pd.DataFrame([{{
    "contact_id": "C001",
    "name": "Alice Johnson",
    "email": "alice.johnson@example.com",
    "department": "Engineering"
}}])

reminders_df = pd.DataFrame([{{
    "reminder_id": "R001",
    "contact_id": "C001",
    "reminder_type": "meeting",
    "subject": "Sprint Planning Sync",
    "reminder_date": "2026-11-20",
    "reminder_time": "10:00",
    "status": "pending"
}}])

eval_time = datetime(2026, 11, 20, 10, 5, tzinfo=ZoneInfo("Asia/Kolkata"))

# Check status in SQLite
status = get_reminder_status("R001", db_path=db_path)
print("[Process B] Persistent Status in SQLite:", status["status"])

# Attempt claim directly
claim = claim_reminder_for_processing(reminders_df.iloc[0], db_path=db_path)
print("[Process B] Direct Claim Result:", claim.success, "| Reason:", claim.reason)

# Run full scheduler batch pipeline
results = process_due_reminders(
    reminders=reminders_df,
    contacts=contacts_df,
    now=eval_time,
    output_dir=out_dir,
    db_path=db_path,
    use_db=True
)
print("[Process B] Scheduler Pipeline Status:", results[0]["status"])
eml_files = [f for f in os.listdir(out_dir) if f.endswith('.eml')]
print("[Process B] Total EML Files on Disk (must be 1):", len(eml_files))
print("[Process B] Exiting cleanly.")
"""

    # 1. Execute Process A
    res_a = subprocess.run(
        [python, "-c", code_proc_a],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    print(res_a.stdout)
    if res_a.stderr:
        print("[Process A STDERR]:", res_a.stderr)
    assert res_a.returncode == 0, f"Process A failed with code {res_a.returncode}"

    # 2. Execute Process B
    res_b = subprocess.run(
        [python, "-c", code_proc_b],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    print(res_b.stdout)
    if res_b.stderr:
        print("[Process B STDERR]:", res_b.stderr)
    assert res_b.returncode == 0, f"Process B failed with code {res_b.returncode}"

    # Final verification on disk
    final_eml_files = [f for f in os.listdir(output_dir) if f.endswith(".eml")]
    print("-" * 70)
    print(f"VERIFICATION RESULT: Final EML Count = {len(final_eml_files)} (Exactly 1 expected)")
    assert len(final_eml_files) == 1, "Duplicate EML file was created!"
    print("SUCCESS: Persistent duplicate prevention across separate OS processes confirmed.")
    print("=" * 70)


if __name__ == "__main__":
    main()
