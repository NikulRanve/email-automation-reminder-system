"""Automated tests for email template loading and personalization module (Phase 4)."""

import hashlib
from pathlib import Path
import pytest

from src.config import TEMPLATES_DIR
from src.email_generator import (
    load_template,
    generate_email,
    validate_template_placeholders,
    TEMPLATE_MAPPING,
    TemplateValidationError,
    TemplateNotFoundError,
)


def create_temp_template(dir_path: Path, filename: str, content: str) -> Path:
    """Helper to create a temporary template file for isolated testing."""
    file_path = dir_path / filename
    file_path.write_text(content, encoding="utf-8")
    return file_path


# 1. Successful interview template loading
def test_load_interview_template_success():
    """Verify loading interview template via type name and exact filename."""
    content_by_type = load_template("interview")
    content_by_file = load_template("interview_reminder.html")
    assert content_by_type == content_by_file
    assert "Upcoming Interview Reminder" in content_by_type
    assert "{{name}}" in content_by_type


# 2. Successful meeting template loading
def test_load_meeting_template_success():
    """Verify loading meeting template."""
    content = load_template("meeting")
    assert "Meeting Reminder" in content
    assert "{{date}}" in content


# 3. Successful payment template loading
def test_load_payment_template_success():
    """Verify loading payment template."""
    content = load_template("payment")
    assert "Payment Due Reminder" in content
    assert "{{time}}" in content


# 4. Successful webinar template loading
def test_load_webinar_template_success():
    """Verify loading webinar template."""
    content = load_template("webinar")
    assert "Webinar Session Reminder" in content
    assert "{{name}}" in content


# 5. Correct name replacement
def test_generate_email_name_replacement():
    """Verify that {{name}} is replaced with the supplied recipient name."""
    html_output = generate_email("interview", "Alice Johnson", "2026-11-25", "14:00")
    assert "Dear Alice Johnson," in html_output
    assert "{{name}}" not in html_output


# 6. Correct date replacement
def test_generate_email_date_replacement():
    """Verify that {{date}} is replaced with the supplied date string."""
    html_output = generate_email("meeting", "Bob Smith", "2026-11-26", "11:30")
    assert "2026-11-26" in html_output
    assert "{{date}}" not in html_output


# 7. Correct time replacement
def test_generate_email_time_replacement():
    """Verify that {{time}} is replaced with the supplied time string."""
    html_output = generate_email("payment", "Charlie Davis", "2026-11-27", "16:45")
    assert "16:45" in html_output
    assert "{{time}}" not in html_output


# 8. Missing template handling
def test_missing_template_handling(tmp_path):
    """Verify TemplateNotFoundError when an approved template file is missing from disk."""
    # tmp_path has no template files inside it
    with pytest.raises(TemplateNotFoundError) as exc_info:
        load_template("interview", templates_dir=tmp_path)
    assert "Template file not found at" in str(exc_info.value)

    with pytest.raises(TemplateNotFoundError):
        generate_email("interview", "Alice", "2026-11-25", "14:00", templates_dir=tmp_path)


# 9. Unsupported reminder type handling
def test_unsupported_reminder_type_handling():
    """Verify TemplateValidationError when passing an unknown reminder type."""
    with pytest.raises(TemplateValidationError) as exc_info:
        generate_email("unsupported_type", "Alice", "2026-11-25", "14:00")
    assert "Unsupported reminder type" in str(exc_info.value)

    with pytest.raises(TemplateValidationError) as exc_info:
        load_template("nonexistent_template.html")
    assert "Unsupported template name" in str(exc_info.value)


# 10. Empty name rejection
def test_empty_name_rejection():
    """Verify TemplateValidationError when name is empty or whitespace-only."""
    with pytest.raises(TemplateValidationError) as exc_info:
        generate_email("interview", "", "2026-11-25", "14:00")
    assert "field 'name' cannot be empty" in str(exc_info.value)

    with pytest.raises(TemplateValidationError) as exc_info:
        generate_email("interview", "   ", "2026-11-25", "14:00")
    assert "field 'name' cannot be empty" in str(exc_info.value)


# 11. Empty date rejection
def test_empty_date_rejection():
    """Verify TemplateValidationError when date is empty or whitespace-only."""
    with pytest.raises(TemplateValidationError) as exc_info:
        generate_email("interview", "Alice", "", "14:00")
    assert "field 'date' cannot be empty" in str(exc_info.value)

    with pytest.raises(TemplateValidationError) as exc_info:
        generate_email("interview", "Alice", "   ", "14:00")
    assert "field 'date' cannot be empty" in str(exc_info.value)


# 12. Empty time rejection
def test_empty_time_rejection():
    """Verify TemplateValidationError when time is empty or whitespace-only."""
    with pytest.raises(TemplateValidationError) as exc_info:
        generate_email("interview", "Alice", "2026-11-25", "")
    assert "field 'time' cannot be empty" in str(exc_info.value)

    with pytest.raises(TemplateValidationError) as exc_info:
        generate_email("interview", "Alice", "2026-11-25", "   ")
    assert "field 'time' cannot be empty" in str(exc_info.value)


# 13. Missing placeholder detection
def test_missing_placeholder_detection(tmp_path):
    """Verify TemplateValidationError when a template is missing a required placeholder."""
    # Create an invalid template missing {{time}}
    bad_template = (
        "<html><body>Hello {{name}}, you have a meeting on {{date}}.</body></html>"
    )
    create_temp_template(tmp_path, "interview_reminder.html", bad_template)

    with pytest.raises(TemplateValidationError) as exc_info:
        generate_email("interview", "Alice", "2026-11-25", "14:00", templates_dir=tmp_path)
    assert "missing required placeholder" in str(exc_info.value)
    assert "time" in str(exc_info.value)


# 14. Unknown placeholder detection
def test_unknown_placeholder_detection(tmp_path):
    """Verify TemplateValidationError when a template contains an unrecognized placeholder."""
    # Create a template with an unexpected {{extra_custom_field}}
    bad_template = (
        "<html><body>Hello {{name}}, meeting on {{date}} at {{time}} with {{extra_var}}.</body></html>"
    )
    create_temp_template(tmp_path, "interview_reminder.html", bad_template)

    with pytest.raises(TemplateValidationError) as exc_info:
        generate_email("interview", "Alice", "2026-11-25", "14:00", templates_dir=tmp_path)
    assert "unsupported placeholder" in str(exc_info.value)
    assert "extra_var" in str(exc_info.value)


# 15. HTML escaping of personalized values
def test_html_escaping_of_personalized_values():
    """Verify that dangerous HTML/script characters are properly escaped to prevent injection."""
    malicious_name = "<script>alert('XSS')</script> & \"Tester\""
    malicious_date = "2026-11-20 <img src=x onerror=alert(1)>"
    malicious_time = "10:00 > 09:00"

    html_output = generate_email(
        "webinar", malicious_name, malicious_date, malicious_time
    )

    # Malicious raw tags must NOT be present
    assert "<script>" not in html_output
    assert "<img src=x" not in html_output

    # Escaped versions MUST be present
    assert "&lt;script&gt;alert(&#x27;XSS&#x27;)&lt;/script&gt;" in html_output or "&lt;script&gt;alert('XSS')&lt;/script&gt;" in html_output
    assert "&amp;" in html_output
    assert "&quot;Tester&quot;" in html_output
    assert "&gt; 09:00" in html_output


# 16. Original template file remains unchanged
def test_original_template_files_remain_unchanged():
    """Verify that generating emails does not modify on-disk template files."""
    hashes_before = {}
    for filename in TEMPLATE_MAPPING.values():
        path = TEMPLATES_DIR / filename
        hashes_before[filename] = hashlib.sha256(path.read_bytes()).hexdigest()

    # Run generation across all template types
    for r_type in TEMPLATE_MAPPING.keys():
        _ = generate_email(r_type, "Sample User", "2026-11-30", "12:00")

    # Check hashes after generation
    for filename in TEMPLATE_MAPPING.values():
        path = TEMPLATES_DIR / filename
        hash_after = hashlib.sha256(path.read_bytes()).hexdigest()
        assert hash_after == hashes_before[filename], f"Template {filename} was modified!"
