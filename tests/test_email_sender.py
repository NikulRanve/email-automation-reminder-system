"""Automated tests for email construction and sending simulation module (Phase 5)."""

from email.message import EmailMessage
from pathlib import Path
import pytest

from src.email_sender import (
    create_email_message,
    send_email,
    get_simulated_path,
    EmailMessageError,
    EmailDeliveryError,
    SmtpNotImplementedError,
    DEFAULT_SENDER_EMAIL,
)


# 1. Successful email message construction
def test_create_email_message_success():
    """Verify that a valid EmailMessage is constructed with proper types."""
    msg = create_email_message(
        to_email="recipient@example.com",
        subject="Interview Reminder",
        html_content="<p>Please attend your interview.</p>",
    )
    assert isinstance(msg, EmailMessage)


# 2. Correct To header
def test_create_email_message_to_header():
    """Verify the To header is set accurately."""
    msg = create_email_message(
        to_email="candidate@example.com",
        subject="Test",
        html_content="<p>Content</p>",
    )
    assert msg["To"] == "candidate@example.com"


# 3. Correct From header (default and custom)
def test_create_email_message_from_header():
    """Verify default fallback sender and custom sender header."""
    # Default sender
    msg_default = create_email_message(
        to_email="test@example.com",
        subject="Test",
        html_content="<p>Body</p>",
    )
    assert msg_default["From"] == DEFAULT_SENDER_EMAIL

    # Custom sender
    msg_custom = create_email_message(
        to_email="test@example.com",
        subject="Test",
        html_content="<p>Body</p>",
        from_email="custom-hr@example.com",
    )
    assert msg_custom["From"] == "custom-hr@example.com"


# 4. Correct subject
def test_create_email_message_subject_header():
    """Verify Subject header is correctly trimmed and assigned."""
    msg = create_email_message(
        to_email="test@example.com",
        subject="  Upcoming Quarterly Sync  ",
        html_content="<p>Content</p>",
    )
    assert msg["Subject"] == "Upcoming Quarterly Sync"


# 5. HTML MIME part exists
def test_create_email_message_html_part_exists():
    """Verify the message contains a text/html MIME payload."""
    raw_html = "<div class='container'><h1>Meeting Notice</h1></div>"
    msg = create_email_message(
        to_email="test@example.com",
        subject="Meeting",
        html_content=raw_html,
    )
    html_body = msg.get_body(preferencelist=("html",))
    assert html_body is not None
    assert html_body.get_content_type() == "text/html"
    assert "Meeting Notice" in html_body.get_content()


# 6. Empty recipient rejected
def test_create_email_message_empty_recipient():
    """Verify EmailMessageError when recipient email is empty or whitespace."""
    with pytest.raises(EmailMessageError) as exc_info:
        create_email_message(to_email="", subject="Sub", html_content="<p>H</p>")
    assert "cannot be empty" in str(exc_info.value)

    with pytest.raises(EmailMessageError) as exc_info:
        create_email_message(to_email="   ", subject="Sub", html_content="<p>H</p>")
    assert "cannot be empty" in str(exc_info.value)


# 7. Empty subject rejected
def test_create_email_message_empty_subject():
    """Verify EmailMessageError when subject is empty or whitespace."""
    with pytest.raises(EmailMessageError) as exc_info:
        create_email_message(to_email="user@example.com", subject="", html_content="<p>H</p>")
    assert "cannot be empty" in str(exc_info.value)

    with pytest.raises(EmailMessageError):
        create_email_message(to_email="user@example.com", subject="   ", html_content="<p>H</p>")


# 8. Empty HTML content rejected
def test_create_email_message_empty_html():
    """Verify EmailMessageError when HTML content is empty or whitespace."""
    with pytest.raises(EmailMessageError) as exc_info:
        create_email_message(to_email="user@example.com", subject="Sub", html_content="")
    assert "HTML content cannot be empty" in str(exc_info.value)

    with pytest.raises(EmailMessageError):
        create_email_message(to_email="user@example.com", subject="Sub", html_content="   ")


# 9. Invalid recipient rejected
def test_create_email_message_invalid_recipient():
    """Verify EmailMessageError when recipient email syntax is malformed."""
    bad_emails = ["not-an-email", "missing-domain@", "@no-user.com", "user@domain"]
    for bad_email in bad_emails:
        with pytest.raises(EmailMessageError) as exc_info:
            create_email_message(to_email=bad_email, subject="Sub", html_content="<p>Hi</p>")
        assert "Invalid email address syntax" in str(exc_info.value)


# 10. Newline/header injection rejected
def test_create_email_message_header_injection_rejected():
    """Verify EmailMessageError when CRLF characters are passed in headers."""
    # Injection in To
    with pytest.raises(EmailMessageError) as exc_to:
        create_email_message(
            to_email="user@example.com\nBcc: spy@example.com",
            subject="Sub",
            html_content="<p>Body</p>",
        )
    assert "Header injection detected" in str(exc_to.value)

    # Injection in Subject
    with pytest.raises(EmailMessageError) as exc_sub:
        create_email_message(
            to_email="user@example.com",
            subject="Valid Subject\r\nCc: attacker@example.com",
            html_content="<p>Body</p>",
        )
    assert "Header injection detected" in str(exc_sub.value)

    # Injection in From
    with pytest.raises(EmailMessageError) as exc_from:
        create_email_message(
            to_email="user@example.com",
            subject="Subject",
            html_content="<p>Body</p>",
            from_email="admin@example.com\nBcc: leak@example.com",
        )
    assert "Header injection detected" in str(exc_from.value)


# 11. Simulation mode saves an .eml file
def test_send_email_saves_eml_file(tmp_path):
    """Verify that send_email creates a .eml file in the output directory."""
    msg = create_email_message(
        to_email="alice@example.com",
        subject="Interview Reminder",
        html_content="<p>Your interview is scheduled.</p>",
    )
    status = send_email(msg, output_dir=tmp_path)
    assert status == "SIMULATED"

    eml_files = list(tmp_path.glob("*.eml"))
    assert len(eml_files) == 1
    assert eml_files[0].suffix == ".eml"
    assert get_simulated_path(msg) == eml_files[0]


# 12. Saved file contains the expected headers and HTML content
def test_send_email_file_contents(tmp_path):
    """Verify the saved .eml file preserves headers and body content in UTF-8."""
    raw_html = "<p>Meeting scheduled for 2026-11-20 at 10:00.</p>"
    msg = create_email_message(
        to_email="bob@example.com",
        subject="Sprint Planning",
        html_content=raw_html,
        from_email="pm@example.com",
    )
    send_email(msg, output_dir=tmp_path)

    saved_file = get_simulated_path(msg)
    assert saved_file is not None
    content = saved_file.read_text(encoding="utf-8")

    assert "To: bob@example.com" in content
    assert "From: pm@example.com" in content
    assert "Subject: Sprint Planning" in content
    assert "Meeting scheduled for 2026-11-20 at 10:00" in content


# 13. Simulation returns SIMULATED
def test_send_email_returns_simulated_status(tmp_path):
    """Verify send_email strictly returns 'SIMULATED' upon completion."""
    msg = create_email_message(
        to_email="user@example.com",
        subject="Sub",
        html_content="<p>Body</p>",
    )
    result = send_email(msg, output_dir=tmp_path)
    assert result == "SIMULATED"


# 14. Output directory is created when missing
def test_send_email_creates_missing_output_dir(tmp_path):
    """Verify send_email automatically creates nested directories if nonexistent."""
    nested_dir = tmp_path / "deep" / "nested" / "simulated"
    assert not nested_dir.exists()

    msg = create_email_message(
        to_email="test@example.com",
        subject="Sub",
        html_content="<p>Body</p>",
    )
    send_email(msg, output_dir=nested_dir)
    assert nested_dir.is_dir()
    assert len(list(nested_dir.glob("*.eml"))) == 1


# 15. Existing files are not overwritten
def test_send_email_avoids_overwriting_existing_files(tmp_path, monkeypatch):
    """Verify that multiple simulated emails to the same recipient do not overwrite files."""
    msg1 = create_email_message(
        to_email="alice@example.com",
        subject="First Notification",
        html_content="<p>First email body</p>",
    )
    msg2 = create_email_message(
        to_email="alice@example.com",
        subject="Second Notification",
        html_content="<p>Second email body</p>",
    )

    send_email(msg1, output_dir=tmp_path)
    file1 = get_simulated_path(msg1)

    send_email(msg2, output_dir=tmp_path)
    file2 = get_simulated_path(msg2)

    assert file1 != file2
    assert file1.exists()
    assert file2.exists()
    assert len(list(tmp_path.glob("*.eml"))) == 2
    assert "First email body" in file1.read_text(encoding="utf-8")
    assert "Second email body" in file2.read_text(encoding="utf-8")


# 16. SMTP mode fails safely without network activity
def test_send_email_fails_safely_in_smtp_mode(tmp_path, monkeypatch):
    """Verify that setting EMAIL_MODE='smtp' raises SmtpNotImplementedError without network calls."""
    monkeypatch.setattr("src.email_sender.EMAIL_MODE", "smtp")

    msg = create_email_message(
        to_email="test@example.com",
        subject="Test",
        html_content="<p>Body</p>",
    )

    with pytest.raises(SmtpNotImplementedError) as exc_info:
        send_email(msg, output_dir=tmp_path)

    assert "SMTP email delivery is disabled and not implemented in Phase 5" in str(exc_info.value)
    # Ensure no file was written
    assert len(list(tmp_path.glob("*.eml"))) == 0


# 17. File-writing failure is handled correctly
def test_send_email_handles_file_write_failure(tmp_path, monkeypatch):
    """Verify EmailDeliveryError is raised on simulated file persistence errors."""
    msg = create_email_message(
        to_email="test@example.com",
        subject="Test",
        html_content="<p>Body</p>",
    )

    # Force an open() failure by mocking builtins.open
    def mock_open_failure(*args, **kwargs):
        raise OSError("Disk quota exceeded or write permission denied")

    monkeypatch.setattr("builtins.open", mock_open_failure)

    with pytest.raises(EmailDeliveryError) as exc_info:
        send_email(msg, output_dir=tmp_path)

    assert "Failed to save simulated email" in str(exc_info.value)
