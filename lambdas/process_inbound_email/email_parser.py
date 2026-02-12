"""
Email Parser Module

Parses SES/SNS notifications to extract email content, sender info,
and decode campaign/provider IDs from Reply-To address.

Follows the inbound email specification from contracts/email_config.json.
"""

import base64
import email
import json
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import default as default_policy
from typing import Any

import structlog

log = structlog.get_logger()

# Pattern from contracts/email_config.json for Reply-To parsing
REPLY_TO_PATTERN = re.compile(
    r"^campaign\+([a-zA-Z0-9-]+)_provider\+([a-zA-Z0-9-]+)@(.+)$"
)


@dataclass(frozen=True)
class EmailIdentifiers:
    """Decoded identifiers from email addressing."""

    campaign_id: str
    provider_id: str
    domain: str


@dataclass
class AttachmentData:
    """Raw attachment data from email parse."""

    filename: str
    content: bytes
    content_type: str
    size_bytes: int


@dataclass
class EmailParseResult:
    """Result of parsing an inbound email."""

    # Required fields
    from_address: str
    subject: str
    body: str
    message_id: str

    # Decoded identifiers (from Reply-To encoding)
    campaign_id: str | None = None
    provider_id: str | None = None

    # Optional metadata
    received_at: str | None = None
    to_addresses: list[str] = field(default_factory=list)
    cc_addresses: list[str] = field(default_factory=list)
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)

    # Attachments (raw data, not yet stored)
    attachments: list[AttachmentData] = field(default_factory=list)

    # Parsing metadata
    parse_errors: list[str] = field(default_factory=list)


def _extract_address(header_value: str) -> str:
    """
    Extract email address from a header value.

    Handles formats like:
    - "John Doe <john@example.com>"
    - "<john@example.com>"
    - "john@example.com"
    """
    if not header_value:
        return ""

    # Try to extract from angle brackets
    match = re.search(r"<([^>]+)>", header_value)
    if match:
        return match.group(1).strip()

    # Just clean up whitespace
    return header_value.strip()


def _extract_addresses(header_value: str | None) -> list[str]:
    """Extract multiple email addresses from a header (e.g., To, Cc)."""
    if not header_value:
        return []

    addresses = []
    # Split on comma and extract each address
    for part in header_value.split(","):
        addr = _extract_address(part)
        if addr:
            addresses.append(addr)
    return addresses


def decode_reply_to(address: str) -> EmailIdentifiers | None:
    """
    Decode campaign_id and provider_id from a Reply-To address.

    Format: campaign+{campaign_id}_provider+{provider_id}@{domain}
    Pattern: ^campaign\\+([a-zA-Z0-9-]+)_provider\\+([a-zA-Z0-9-]+)@(.+)$

    Args:
        address: Email address to decode

    Returns:
        EmailIdentifiers if pattern matches, None otherwise
    """
    match = REPLY_TO_PATTERN.match(address)
    if not match:
        return None

    return EmailIdentifiers(
        campaign_id=match.group(1),
        provider_id=match.group(2),
        domain=match.group(3),
    )


def _find_identifiers(
    to_addresses: list[str],
    cc_addresses: list[str],
) -> EmailIdentifiers | None:
    """
    Search To and Cc headers for encoded Reply-To address.

    When a provider replies, the encoded Reply-To becomes the To address.
    """
    # Check To addresses first (most likely)
    for addr in to_addresses:
        identifiers = decode_reply_to(addr)
        if identifiers:
            log.debug("found_identifiers_in_to", address=addr)
            return identifiers

    # Check Cc addresses as fallback
    for addr in cc_addresses:
        identifiers = decode_reply_to(addr)
        if identifiers:
            log.debug("found_identifiers_in_cc", address=addr)
            return identifiers

    return None


def _extract_body_text(msg: EmailMessage) -> str:
    """
    Extract plaintext body from email message.

    Prefers text/plain, falls back to text/html with tag stripping.
    """
    body = ""

    if msg.is_multipart():
        # Walk through parts looking for text
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        body = payload.decode("utf-8", errors="replace")
                    break  # Prefer plaintext

            elif content_type == "text/html" and not body:
                # Fallback to HTML if no plaintext found yet
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        html = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        html = payload.decode("utf-8", errors="replace")
                    # Strip HTML tags (basic)
                    body = re.sub(r"<[^>]+>", " ", html)
                    body = re.sub(r"\s+", " ", body).strip()
    else:
        # Simple non-multipart message
        payload = msg.get_payload(decode=True)
        if payload:
            content_type = msg.get_content_type()
            charset = msg.get_content_charset() or "utf-8"
            try:
                body = payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                body = payload.decode("utf-8", errors="replace")

            # If HTML, strip tags
            if content_type == "text/html":
                body = re.sub(r"<[^>]+>", " ", body)
                body = re.sub(r"\s+", " ", body).strip()

    return body.strip()


def _extract_attachments(msg: EmailMessage) -> list[AttachmentData]:
    """
    Extract attachments from email message.

    Filters to allowed MIME types per contracts/email_config.json.
    """
    # Allowed MIME types from contracts/email_config.json
    allowed_types = {
        "text/plain",
        "text/html",
        "application/pdf",
        "image/jpeg",
        "image/png",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    # Max attachment size: 10MB
    max_size = 10 * 1024 * 1024  # 10MB

    attachments = []

    if not msg.is_multipart():
        return attachments

    for part in msg.walk():
        content_disposition = str(part.get("Content-Disposition", ""))

        # Check if this is an attachment
        if (
            "attachment" not in content_disposition
            and "inline" not in content_disposition
        ):
            # Also check if it has a filename
            filename = part.get_filename()
            if not filename:
                continue

        filename = part.get_filename()
        if not filename:
            # Generate a filename
            content_type = part.get_content_type()
            ext = content_type.split("/")[-1]
            filename = f"attachment.{ext}"

        content_type = part.get_content_type()

        # Check allowed types
        if content_type not in allowed_types:
            log.warning(
                "skipping_unsupported_attachment",
                filename=filename,
                content_type=content_type,
            )
            continue

        # Get content
        payload = part.get_payload(decode=True)
        if not payload:
            continue

        size_bytes = len(payload)

        # Check size limit
        if size_bytes > max_size:
            log.warning(
                "skipping_oversized_attachment",
                filename=filename,
                size_bytes=size_bytes,
                max_size=max_size,
            )
            continue

        attachments.append(
            AttachmentData(
                filename=filename,
                content=payload,
                content_type=content_type,
                size_bytes=size_bytes,
            )
        )

        log.debug(
            "extracted_attachment",
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    return attachments


def extract_email_body(raw_email: str | bytes) -> EmailParseResult:
    """
    Parse raw email content (MIME format) into structured result.

    Args:
        raw_email: Raw email content as string or bytes

    Returns:
        EmailParseResult with parsed fields
    """
    parse_errors: list[str] = []

    # Parse the MIME message
    raw_bytes = raw_email.encode("utf-8") if isinstance(raw_email, str) else raw_email

    try:
        msg = email.message_from_bytes(raw_bytes, policy=default_policy)
    except Exception as e:
        log.error("email_parse_failed", error=str(e))
        return EmailParseResult(
            from_address="",
            subject="",
            body="",
            message_id="",
            parse_errors=[f"Failed to parse email: {e}"],
        )

    # Extract headers
    from_address = _extract_address(msg.get("From", ""))
    subject = msg.get("Subject", "") or ""
    message_id = msg.get("Message-ID", "") or ""
    received_at = msg.get("Date", "")
    in_reply_to = msg.get("In-Reply-To", "")

    # Extract references (can be multi-line)
    references_raw = msg.get("References", "") or ""
    references = references_raw.split() if references_raw else []

    # Extract To and Cc addresses
    to_addresses = _extract_addresses(msg.get("To", ""))
    cc_addresses = _extract_addresses(msg.get("Cc", ""))

    # Find campaign/provider identifiers from To addresses
    identifiers = _find_identifiers(to_addresses, cc_addresses)

    if not identifiers:
        parse_errors.append(
            "Could not decode campaign/provider IDs from email addressing"
        )
        log.warning(
            "missing_identifiers",
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
        )

    # Extract body
    body = _extract_body_text(msg)
    if not body:
        parse_errors.append("Could not extract email body text")

    # Extract attachments
    attachments = _extract_attachments(msg)

    return EmailParseResult(
        from_address=from_address,
        subject=subject,
        body=body,
        message_id=message_id,
        campaign_id=identifiers.campaign_id if identifiers else None,
        provider_id=identifiers.provider_id if identifiers else None,
        received_at=received_at,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        in_reply_to=in_reply_to,
        references=references,
        attachments=attachments,
        parse_errors=parse_errors,
    )


def parse_ses_notification(sns_event: dict[str, Any]) -> EmailParseResult:
    """
    Parse an SNS notification containing SES email data.

    SES sends emails to SNS in one of two modes:
    1. Full email content (MIME) in the SNS message
    2. Reference to S3 where the email is stored

    For S3 reference mode, the caller must fetch from S3 first.

    Args:
        sns_event: SNS notification payload

    Returns:
        EmailParseResult if email content is embedded, raises if S3 reference

    Raises:
        ValueError: If email is stored in S3 (must be fetched separately)
    """
    # Parse SNS Message (which contains SES notification)
    if "Records" in sns_event:
        # Lambda event format with SNS records
        record = sns_event["Records"][0]
        sns_message = json.loads(record["Sns"]["Message"])
    elif "Message" in sns_event:
        # Direct SNS message
        sns_message = json.loads(sns_event["Message"])
    else:
        # Assume it's already the SES notification
        sns_message = sns_event

    log.debug(
        "parsing_ses_notification",
        notification_type=sns_message.get("notificationType"),
    )

    # Check for bounce/complaint notifications (pass through for now)
    notification_type = sns_message.get("notificationType")
    if notification_type in ("Bounce", "Complaint"):
        log.info("received_notification", type=notification_type)
        return EmailParseResult(
            from_address="",
            subject="",
            body="",
            message_id=sns_message.get("mail", {}).get("messageId", ""),
            parse_errors=[
                f"Received {notification_type} notification, not provider response"
            ],
        )

    # For inbound email, look for the content
    mail_data = sns_message.get("mail", {})
    receipt_data = sns_message.get("receipt", {})

    # Check if email is in S3 (action.type = "S3" instead of embedded)
    for action in (
        receipt_data.get("action", {}).values()
        if isinstance(receipt_data.get("action"), dict)
        else [receipt_data.get("action", {})]
    ):
        if isinstance(action, dict) and action.get("type") == "S3":
            bucket = action.get("bucketName")
            key = action.get("objectKey")
            raise ValueError(
                f"Email stored in S3: s3://{bucket}/{key}. "
                "Use fetch_email_from_s3() to retrieve content first."
            )

    # Check for embedded content
    content = sns_message.get("content")
    if content:
        # Content is typically base64 encoded in some configurations
        try:
            if not content.startswith("From:") and not content.startswith("MIME"):
                # Try base64 decode
                raw_email = base64.b64decode(content)
            else:
                raw_email = content
        except Exception:
            raw_email = content

        result = extract_email_body(raw_email)

        # Supplement with SES metadata
        if not result.message_id and mail_data.get("messageId"):
            # Create a new result with the SES message ID
            result = EmailParseResult(
                from_address=result.from_address or mail_data.get("source", ""),
                subject=result.subject,
                body=result.body,
                message_id=mail_data.get("messageId", ""),
                campaign_id=result.campaign_id,
                provider_id=result.provider_id,
                received_at=result.received_at or mail_data.get("timestamp", ""),
                to_addresses=result.to_addresses or mail_data.get("destination", []),
                cc_addresses=result.cc_addresses,
                in_reply_to=result.in_reply_to,
                references=result.references,
                attachments=result.attachments,
                parse_errors=result.parse_errors,
            )

        return result

    # Try to extract from SES headers directly (simpler SNS format)
    common_headers = mail_data.get("commonHeaders", {})

    # Extract identifiers from destination
    to_addresses = mail_data.get("destination", [])
    identifiers = _find_identifiers(to_addresses, [])

    return EmailParseResult(
        from_address=mail_data.get("source", ""),
        subject=common_headers.get("subject", ""),
        body="[Email content not embedded - check S3]",
        message_id=mail_data.get("messageId", ""),
        campaign_id=identifiers.campaign_id if identifiers else None,
        provider_id=identifiers.provider_id if identifiers else None,
        received_at=mail_data.get("timestamp", ""),
        to_addresses=to_addresses,
        parse_errors=["Email content not embedded in SNS message"],
    )
