# Dataset Documentation

This document describes the datasets, data schemas, validation constraints, and referential relationships utilized within the **Email Automation & Reminder System**.

---

## 1. Production Tabular Datasets (`data/`)

The application processes two primary relational CSV datasets located in the [`data/`](file:///c:/Users/nikul/OneDrive/Desktop/Diploma%20program/python/Email%20Automation%20&%20Reminder%20System/data) directory.

### 1.1 Contacts Dataset (`data/contacts.csv`)
Stores recipient metadata used to address and personalize notifications.

| Column Name | Data Type | Required | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `contact_id` | String | Yes | Primary key uniquely identifying the recipient | `C001` |
| `name` | String | Yes | Full recipient name | `Alice Johnson` |
| `email` | String | Yes | Valid recipient email address | `alice.johnson@example.com` |
| `department` | String | Yes | Organizational department | `Engineering` |

#### Sample Records:
```csv
contact_id,name,email,department
C001,Alice Johnson,alice.johnson@example.com,Engineering
C002,Bob Smith,bob.smith@example.com,Human Resources
C003,Charlie Davis,charlie.davis@example.com,Finance
C004,Diana Prince,diana.prince@example.com,Marketing
C005,Evan Wright,evan.wright@example.com,Operations
```

---

### 1.2 Reminders Dataset (`data/reminders.csv`)
Stores scheduled notifications, event details, and initial delivery lifecycle states.

| Column Name | Data Type | Required | Validation & Formatting Rules | Example |
| :--- | :--- | :--- | :--- | :--- |
| `reminder_id` | String | Yes | Unique reminder identifier (Primary Key) | `R001` |
| `contact_id` | String | Yes | Foreign key mapping to a valid `contact_id` in `contacts.csv` | `C001` |
| `reminder_type` | String | Yes | Must be one of: `interview`, `meeting`, `payment`, `webinar` | `meeting` |
| `subject` | String | Yes | Descriptive subject line (non-empty string) | `Sprint Planning Sync` |
| `reminder_date` | String | Yes | Calendar date in ISO format `YYYY-MM-DD` | `2026-11-20` |
| `reminder_time` | String | Yes | 24-hour time in format `HH:MM` or `HH:MM:SS` | `10:00` |
| `status` | String | Yes | Lifecycle status (`pending`, `sent`, `dispatched`, `failed`, `cancelled`) | `pending` |

#### Sample Records:
```csv
reminder_id,contact_id,reminder_type,subject,reminder_date,reminder_time,status
R001,C001,meeting,Sprint Planning Sync,2026-11-20,10:00,pending
R002,C002,interview,Senior Python Developer Interview,2026-11-21,14:30,pending
R003,C003,payment,Invoice #INV-2026-089 Due Reminder,2026-11-22,09:00,pending
R004,C004,webinar,AI in Workflow Automation Webinar,2026-11-23,16:00,pending
R005,C005,meeting,Quarterly Operations Review,2026-11-24,11:00,pending
```

---

## 2. Referential Integrity & Validation Constraints

1. **Foreign Key Integrity**: Every `contact_id` appearing in `data/reminders.csv` must resolve to an existing record in `data/contacts.csv`. Orphan records raise `ReminderValidationError`.
2. **Date Realism**: Dates are parsed strictly against real calendar dates using `%Y-%m-%d` (e.g., February 30th is rejected).
3. **Time Compliance**: Times must be 24-hour compliant (`00:00` to `23:59`).
4. **Whitelisting**: `reminder_type` is restricted strictly to supported template types (`interview`, `meeting`, `payment`, `webinar`).
5. **Whitespace Invariance**: Leading and trailing whitespaces are normalized in memory during ingestion without mutating the original CSV files.
