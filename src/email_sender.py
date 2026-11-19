"""Email sender module for Email Automation & Reminder System.

Responsible for constructing MIME email messages and executing safe sending simulations.
For Phase 5, all email delivery is simulated by saving messages as .eml files.
Direct SMTP delivery is strictly disabled.
"""

from email.message import EmailMessage
from pathlib import Path
from typing import Optional
from datetime import datetime
import re

from src.config import EMAIL_MODE, SIMULATED_EMAILS_DIR

# Default safe fallback sender address
DEFAULT_SENDER_EMAIL = "no-reply@example.com"

# Syntax validation regex for email addresses
EMAIL_REGEX: re.Pattern = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)


class EmailSenderError(Exception):
    """Base exception for email construction and sending errors."""
    pass


class EmailMessageError(EmailSenderError, ValueError):
    """Exception raised when an email message header or body fails validation."""
    pass


class EmailDeliveryError(EmailSenderError, RuntimeError):
    """Exception raised when an email delivery or simulation storage fails."""
    pass


class SmtpNotImplementedError(EmailDeliveryError, NotImplementedError):
    """Exception raised when SMTP delivery is attempted while in Phase 5 simulation scope."""
    pass


def _validate_header_value(header_name: str, value: str) -> str:
    """Validate a header value, ensuring it is non-empty and contains no newlines.

    Args:
        header_name: Name of header (for error reporting).
        value: String value of the header.

    Returns:
        str: Cleaned, whitespace-stripped string.

    Raises:
        EmailMessageError: If value is empty or contains CR/LF characters.
    """
    if value is None or not str(value).strip():
        raise EmailMessageError(f"Email header '{header_name}' cannot be empty or whitespace-only.")

    val_str = str(value).strip()
    if "\r" in val_str or "\n" in val_str:
        raise EmailMessageError(
            f"Header injection detected in '{header_name}': Newline characters are not permitted."
        )

    return val_str


def _validate_email_address(field_name: str, email_address: str) -> str:
    """Validate an email address syntax and header safety.

    Args:
        field_name: Header name (e.g., 'To' or 'From').
        email_address: The email address to check.

    Returns:
        str: Validated email address.

    Raises:
        EmailMessageError: If email address is empty, malformed, or contains newlines.
    """
    clean_addr = _validate_header_value(field_name, email_address)
    if not EMAIL_REGEX.match(clean_addr):
        raise EmailMessageError(
            f"Invalid email address syntax for '{field_name}': '{email_address}'"
        )
    return clean_addr


def create_email_message(
    to_email: str,
    subject: str,
    html_content: str,
    from_email: Optional[str] = None,
) -> EmailMessage:
    """Construct an EmailMessage with valid headers and an HTML body.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        html_content: Raw or rendered HTML content for the message body.
        from_email: Optional sender address. Defaults to 'no-reply@example.com'.

    Returns:
        EmailMessage: Properly structured MIME email message.

    Raises:
        EmailMessageError: If any header or content fails validation or contains injection attacks.
    """
    # 1. Validate headers
    valid_to = _validate_email_address("To", to_email)
    valid_subject = _validate_header_value("Subject", subject)

    if from_email is not None and str(from_email).strip():
        valid_from = _validate_email_address("From", from_email)
    else:
        valid_from = DEFAULT_SENDER_EMAIL

    # 2. Validate HTML content
    if html_content is None or not str(html_content).strip():
        raise EmailMessageError("HTML content cannot be empty or whitespace-only.")

    # 3. Build EmailMessage
    msg = EmailMessage()
    msg["To"] = valid_to
    msg["From"] = valid_from
    msg["Subject"] = valid_subject
    msg.add_alternative(str(html_content), subtype="html")

    return msg


def send_email(
    message: EmailMessage,
    output_dir: Optional[Path] = None,
) -> str:
    """Dispatch an email message via the configured execution mode.

    In Phase 5, only simulation mode is active. In this mode, messages are serialized
    to .eml files under the designated output directory. SMTP dispatch is strictly disabled.

    Args:
        message: EmailMessage instance to dispatch.
        output_dir: Optional directory override where simulation files should be saved.
                    Defaults to SIMULATED_EMAILS_DIR from config.

    Returns:
        str: Status string 'SIMULATED' upon successful file persistence.

    Raises:
        SmtpNotImplementedError: If EMAIL_MODE is configured as 'smtp'.
        EmailDeliveryError: If writing the simulation file fails.
        EmailMessageError: If message is invalid or missing required headers.
    """
    if not isinstance(message, EmailMessage):
        raise EmailMessageError("The 'message' argument must be an instance of email.message.EmailMessage.")

    # Check for required headers
    for req_header in ("To", "From", "Subject"):
        if req_header not in message:
            raise EmailMessageError(f"Email message is missing required header: '{req_header}'.")

    # Safety Check: Enforce simulation mode restriction
    active_mode = str(EMAIL_MODE).strip().lower()
    if active_mode == "smtp":
        raise SmtpNotImplementedError(
            "SMTP email delivery is disabled and not implemented in Phase 5. "
            "Only 'simulation' mode is supported."
        )

    # Resolve target directory
    target_dir = Path(output_dir) if output_dir is not None else SIMULATED_EMAILS_DIR

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as err:
        raise EmailDeliveryError(
            f"Failed to create output directory '{target_dir}': {err}"
        ) from err

    # Create safe unique filename
    to_clean = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(message["To"]).strip().lower())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    base_filename = f"simulated_{timestamp}_{to_clean}.eml"
    file_path = target_dir / base_filename

    # Prevent collision / overwrite
    counter = 1
    while file_path.exists():
        file_path = target_dir / f"simulated_{timestamp}_{to_clean}_{counter}.eml"
        counter += 1

    # Write .eml file in UTF-8
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(message.as_string())
    except Exception as err:
        raise EmailDeliveryError(
            f"Failed to save simulated email to '{file_path}': {err}"
        ) from err

    # Attach saved path to message object for inspection
    setattr(message, "simulated_path", file_path)

    return "SIMULATED"


def get_simulated_path(message: EmailMessage) -> Optional[Path]:
    """Retrieve the path of the saved simulated .eml file from an EmailMessage.

    Args:
        message: EmailMessage instance processed by send_email().

    Returns:
        Optional[Path]: Path to the generated .eml file, or None if not set.
    """
    return getattr(message, "simulated_path", None)
