"""Email generator module for Email Automation & Reminder System.

Responsible for populating HTML templates with dynamic contact and reminder details,
enforcing placeholder validation and sanitizing values via HTML escaping.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set
import html
import re

from src.config import TEMPLATES_DIR

# Controlled mapping between reminder types and template filenames
TEMPLATE_MAPPING: Dict[str, str] = {
    "interview": "interview_reminder.html",
    "meeting": "meeting_reminder.html",
    "payment": "payment_reminder.html",
    "webinar": "webinar_reminder.html",
}

# Approved template filenames
APPROVED_TEMPLATE_FILES: Set[str] = set(TEMPLATE_MAPPING.values())

# Required placeholders expected in all reminder templates
REQUIRED_PLACEHOLDERS: Set[str] = {"name", "date", "time"}

# Regex pattern to match placeholders of the form {{variable_name}}
PLACEHOLDER_REGEX: re.Pattern = re.compile(r"\{\{([^}]+)\}\}")


class TemplateError(Exception):
    """Base exception for email template errors."""
    pass


class TemplateNotFoundError(TemplateError, FileNotFoundError):
    """Raised when an approved template file cannot be found on disk."""
    pass


class TemplateValidationError(TemplateError, ValueError):
    """Raised when a template or its values fail validation."""
    pass


def load_template(
    template_name: str,
    templates_dir: Optional[Path] = None,
) -> str:
    """Load an approved HTML template from the templates directory.

    Args:
        template_name: The reminder type (e.g. 'interview') or template filename
                       (e.g. 'interview_reminder.html').
        templates_dir: Optional override directory for templates. Defaults to TEMPLATES_DIR.

    Returns:
        str: Raw HTML template content.

    Raises:
        TemplateValidationError: If template_name is not in the approved whitelist.
        TemplateNotFoundError: If the template file does not exist on disk.
    """
    clean_name = str(template_name).strip().lower()

    if clean_name in TEMPLATE_MAPPING:
        filename = TEMPLATE_MAPPING[clean_name]
    elif clean_name in APPROVED_TEMPLATE_FILES:
        filename = clean_name
    else:
        raise TemplateValidationError(
            f"Unsupported template name: '{template_name}'. "
            f"Allowed types: {list(TEMPLATE_MAPPING.keys())}, "
            f"Allowed files: {list(APPROVED_TEMPLATE_FILES)}"
        )

    base_dir = Path(templates_dir) if templates_dir is not None else TEMPLATES_DIR
    target_path = base_dir / filename

    if not target_path.exists():
        raise TemplateNotFoundError(f"Template file not found at: {target_path}")

    return target_path.read_text(encoding="utf-8")


def validate_template_placeholders(template_content: str) -> Set[str]:
    """Validate placeholder structure within a template.

    Checks:
    - All required placeholders ({name}, {date}, {time}) are present.
    - No unsupported placeholders exist.

    Args:
        template_content: Raw template HTML string.

    Returns:
        Set[str]: Set of discovered placeholder names.

    Raises:
        TemplateValidationError: If required placeholders are missing or unsupported
                                placeholders are present.
    """
    found_placeholders = set(
        p.strip() for p in PLACEHOLDER_REGEX.findall(template_content)
    )

    # 1. Check for missing required placeholders
    missing = REQUIRED_PLACEHOLDERS - found_placeholders
    if missing:
        raise TemplateValidationError(
            f"Template is missing required placeholder(s): {sorted(list(missing))}. "
            f"Expected: {sorted(list(REQUIRED_PLACEHOLDERS))}"
        )

    # 2. Check for unknown/unsupported placeholders
    unknown = found_placeholders - REQUIRED_PLACEHOLDERS
    if unknown:
        raise TemplateValidationError(
            f"Template contains unsupported placeholder(s): {sorted(list(unknown))}. "
            f"Allowed placeholders: {sorted(list(REQUIRED_PLACEHOLDERS))}"
        )

    return found_placeholders


def generate_email(
    reminder_type: str,
    name: str,
    date: str,
    time: str,
    templates_dir: Optional[Path] = None,
) -> str:
    """Generate a personalized HTML email from an approved template.

    Args:
        reminder_type: Type of reminder ('interview', 'meeting', 'payment', 'webinar').
        name: Recipient full name (cannot be empty).
        date: Scheduled date string (cannot be empty).
        time: Scheduled time string (cannot be empty).
        templates_dir: Optional override for template directory.

    Returns:
        str: Fully rendered, HTML-escaped email content.

    Raises:
        TemplateValidationError: If reminder_type is invalid, personalization fields are
                                empty, or placeholders fail validation.
        TemplateNotFoundError: If the mapped template file does not exist.
    """
    clean_type = str(reminder_type).strip().lower()
    if clean_type not in TEMPLATE_MAPPING:
        raise TemplateValidationError(
            f"Unsupported reminder type '{reminder_type}'. "
            f"Allowed types: {list(TEMPLATE_MAPPING.keys())}"
        )

    # 1. Validate personalization inputs (reject empty or whitespace-only)
    field_values = {
        "name": str(name).strip() if name is not None else "",
        "date": str(date).strip() if date is not None else "",
        "time": str(time).strip() if time is not None else "",
    }

    for field, val in field_values.items():
        if not val:
            raise TemplateValidationError(
                f"Personalization field '{field}' cannot be empty."
            )

    # 2. Load the template
    template_content = load_template(clean_type, templates_dir=templates_dir)

    # 3. Validate template placeholders
    validate_template_placeholders(template_content)

    # 4. Escape inputs to prevent HTML injection and substitute placeholders
    rendered = template_content
    for field, val in field_values.items():
        escaped_val = html.escape(val, quote=True)
        placeholder = f"{{{{{field}}}}}"
        rendered = rendered.replace(placeholder, escaped_val)

    # 5. Confirm no unresolved placeholders remain
    remaining = PLACEHOLDER_REGEX.findall(rendered)
    if remaining:
        raise TemplateValidationError(
            f"Unresolved placeholder(s) remain in generated email: {remaining}"
        )

    return rendered
