"""
Attachment Handler Module

Stores email attachments to S3 for document processing.
Returns metadata in the format expected by ProviderResponseReceived event.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

import boto3
import structlog
from botocore.exceptions import ClientError

from lambdas.process_inbound_email.email_parser import AttachmentData

log = structlog.get_logger()

# Default configuration - can be overridden via environment
DEFAULT_BUCKET = "recruitment-documents"
DEFAULT_PREFIX = "attachments/"
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB from contracts/email_config.json


@dataclass(frozen=True)
class AttachmentInfo:
    """
    Attachment metadata for ProviderResponseReceived event.

    Matches the "attachment" definition in contracts/events.json.
    
    Note on filenames:
        - `filename`: Original filename (may contain spaces, special chars)
        - `original_filename`: Alias for clarity (same as filename)
        - S3 key in `s3_path` contains a sanitized, timestamped version
        
    When looking up files in S3 or matching against Textract results,
    parse the filename from the s3_path rather than using the original.
    """

    filename: str  # Original filename (for display/logging)
    s3_path: str   # S3 URI with sanitized, timestamped filename
    content_type: str
    size_bytes: int

    @property
    def original_filename(self) -> str:
        """Alias for filename - the original, unsanitized name."""
        return self.filename
    
    @property
    def s3_key(self) -> str:
        """Extract the S3 key from the s3_path URI."""
        # s3_path format: s3://bucket/key
        if self.s3_path.startswith("s3://"):
            parts = self.s3_path[5:].split("/", 1)
            return parts[1] if len(parts) > 1 else ""
        return ""

    def to_dict(self) -> dict:
        """Convert to dictionary for event payload."""
        return {
            "filename": self.filename,
            "s3_path": self.s3_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
        }


def _get_s3_client():
    """Get S3 client with optional endpoint override for local dev."""
    import os

    endpoint_url = os.environ.get("RECRUITMENT_S3_ENDPOINT_URL")
    region = os.environ.get("AWS_REGION", "us-west-2")

    if endpoint_url:
        return boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
    return boto3.client("s3", region_name=region)


def _get_bucket_name() -> str:
    """Get S3 bucket name from environment or default."""
    import os

    return os.environ.get("RECRUITMENT_S3_BUCKET_NAME", DEFAULT_BUCKET)


def _get_prefix() -> str:
    """Get S3 key prefix from environment or default."""
    import os

    return os.environ.get("RECRUITMENT_S3_ATTACHMENTS_PREFIX", DEFAULT_PREFIX)


def _sanitize_filename(filename: str) -> str:
    """
    Sanitize filename for S3 storage.

    - Removes path components (Unix and Windows)
    - Replaces problematic characters
    - Limits length
    """
    import os

    # Normalize Windows backslashes to forward slashes for cross-platform support
    normalized = filename.replace("\\", "/")
    # Get just the filename, no path
    safe_name = os.path.basename(normalized)

    # Replace spaces and special chars
    safe_name = safe_name.replace(" ", "_")

    # Limit to 200 chars
    if len(safe_name) > 200:
        name_part = safe_name[:150]
        suffix = os.path.splitext(safe_name)[1]
        safe_name = f"{name_part}{suffix}"

    return safe_name


def _build_s3_key(
    campaign_id: str,
    provider_id: str,
    filename: str,
    prefix: str | None = None,
) -> str:
    """
    Build S3 key for attachment storage.

    Format: {prefix}{campaign_id}/{provider_id}/{timestamp}_{filename}

    This ensures unique keys even if the same filename is uploaded multiple times.
    """
    key_prefix = prefix or _get_prefix()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    safe_filename = _sanitize_filename(filename)

    return f"{key_prefix}{campaign_id}/{provider_id}/{timestamp}_{safe_filename}"


def store_attachment(
    attachment: AttachmentData,
    campaign_id: str,
    provider_id: str,
    *,
    bucket: str | None = None,
    prefix: str | None = None,
) -> AttachmentInfo:
    """
    Store a single attachment to S3.

    Args:
        attachment: Raw attachment data from email parse
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        bucket: Override S3 bucket name
        prefix: Override S3 key prefix

    Returns:
        AttachmentInfo with S3 path for event payload

    Raises:
        ValueError: If attachment exceeds size limit
        ClientError: If S3 upload fails
    """
    # Validate size
    if attachment.size_bytes > MAX_ATTACHMENT_SIZE:
        raise ValueError(
            f"Attachment '{attachment.filename}' exceeds max size "
            f"({attachment.size_bytes} > {MAX_ATTACHMENT_SIZE})"
        )

    s3_bucket = bucket or _get_bucket_name()
    s3_key = _build_s3_key(campaign_id, provider_id, attachment.filename, prefix)

    log.info(
        "storing_attachment",
        filename=attachment.filename,
        bucket=s3_bucket,
        key=s3_key,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
    )

    client = _get_s3_client()

    try:
        client.put_object(
            Bucket=s3_bucket,
            Key=s3_key,
            Body=attachment.content,
            ContentType=attachment.content_type,
            Metadata={
                "campaign_id": campaign_id,
                "provider_id": provider_id,
                "original_filename": attachment.filename,
            },
        )
    except ClientError as e:
        log.error(
            "s3_upload_failed",
            bucket=s3_bucket,
            key=s3_key,
            error=str(e),
        )
        raise

    s3_path = f"s3://{s3_bucket}/{s3_key}"

    log.info(
        "attachment_stored",
        s3_path=s3_path,
        size_bytes=attachment.size_bytes,
    )

    return AttachmentInfo(
        filename=attachment.filename,
        s3_path=s3_path,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
    )


def process_attachments(
    attachments: list[AttachmentData],
    campaign_id: str,
    provider_id: str,
    *,
    bucket: str | None = None,
    prefix: str | None = None,
    continue_on_error: bool = True,
) -> tuple[list[AttachmentInfo], list[tuple[str, Exception]]]:
    """
    Process and store all attachments from an email.

    Args:
        attachments: List of raw attachment data from email parse
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        bucket: Override S3 bucket name
        prefix: Override S3 key prefix
        continue_on_error: If True, continue processing other attachments on failure

    Returns:
        Tuple of (successful AttachmentInfo list, failed (filename, exception) list)
    """
    stored: list[AttachmentInfo] = []
    failed: list[tuple[str, Exception]] = []

    for attachment in attachments:
        try:
            info = store_attachment(
                attachment,
                campaign_id,
                provider_id,
                bucket=bucket,
                prefix=prefix,
            )
            stored.append(info)
        except Exception as e:
            log.error(
                "attachment_processing_failed",
                filename=attachment.filename,
                error=str(e),
            )
            if continue_on_error:
                failed.append((attachment.filename, e))
            else:
                raise

    log.info(
        "attachments_processed",
        stored_count=len(stored),
        failed_count=len(failed),
    )

    return stored, failed


def fetch_email_from_s3(bucket: str, key: str) -> bytes:
    """
    Fetch raw email content from S3.

    Used when SES stores emails in S3 rather than embedding in SNS.

    Args:
        bucket: S3 bucket name
        key: S3 object key

    Returns:
        Raw email content as bytes

    Raises:
        ClientError: If S3 get fails
    """
    log.info("fetching_email_from_s3", bucket=bucket, key=key)

    client = _get_s3_client()

    try:
        response = client.get_object(Bucket=bucket, Key=key)
        content = response["Body"].read()

        log.debug(
            "email_fetched_from_s3",
            bucket=bucket,
            key=key,
            size_bytes=len(content),
        )

        return content
    except ClientError as e:
        log.error(
            "s3_fetch_failed",
            bucket=bucket,
            key=key,
            error=str(e),
        )
        raise
