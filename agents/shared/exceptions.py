"""
Custom Exceptions for Recruitment Automation System

All exceptions follow the pattern of specific, actionable errors
with context needed for debugging and logging.
"""

from dataclasses import dataclass
from typing import Any


class RecruitmentError(Exception):
    """Base exception for recruitment automation system."""
    
    def __init__(self, message: str, **context: Any) -> None:
        self.message = message
        self.context = context
        super().__init__(message)
    
    def __str__(self) -> str:
        if self.context:
            context_str = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{self.message} ({context_str})"
        return self.message


@dataclass
class ProviderNotFoundError(RecruitmentError):
    """Provider record not found in DynamoDB."""
    
    provider_id: str
    campaign_id: str
    
    def __init__(self, provider_id: str, campaign_id: str) -> None:
        self.provider_id = provider_id
        self.campaign_id = campaign_id
        super().__init__(
            f"Provider '{provider_id}' not found in campaign '{campaign_id}'",
            provider_id=provider_id,
            campaign_id=campaign_id,
        )


@dataclass
class InvalidStateTransitionError(RecruitmentError):
    """Attempted invalid state transition."""
    
    current_status: str
    new_status: str
    allowed_transitions: list[str]
    
    def __init__(
        self,
        current_status: str,
        new_status: str,
        allowed_transitions: list[str],
    ) -> None:
        self.current_status = current_status
        self.new_status = new_status
        self.allowed_transitions = allowed_transitions
        super().__init__(
            f"Cannot transition from '{current_status}' to '{new_status}'. "
            f"Allowed transitions: {allowed_transitions}",
            current_status=current_status,
            new_status=new_status,
            allowed_transitions=allowed_transitions,
        )


@dataclass
class EventPublishError(RecruitmentError):
    """Failed to publish event to EventBridge."""
    
    event_type: str
    error_code: str | None = None
    error_message: str | None = None
    
    def __init__(
        self,
        event_type: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.event_type = event_type
        self.error_code = error_code
        self.error_message = error_message
        super().__init__(
            f"Failed to publish event '{event_type}': {error_message or 'Unknown error'}",
            event_type=event_type,
            error_code=error_code,
            error_message=error_message,
        )


@dataclass
class InvalidEmailFormatError(RecruitmentError):
    """Email address or Reply-To format is invalid."""
    
    email_address: str
    expected_pattern: str | None = None
    
    def __init__(
        self,
        email_address: str,
        expected_pattern: str | None = None,
    ) -> None:
        self.email_address = email_address
        self.expected_pattern = expected_pattern
        pattern_hint = f" Expected pattern: {expected_pattern}" if expected_pattern else ""
        super().__init__(
            f"Invalid email format: '{email_address}'.{pattern_hint}",
            email_address=email_address,
            expected_pattern=expected_pattern,
        )


@dataclass
class DocumentProcessingError(RecruitmentError):
    """Error during document processing (upload, download, OCR)."""
    
    document_path: str
    operation: str  # "upload", "download", "ocr"
    
    def __init__(
        self,
        document_path: str,
        operation: str,
        error_message: str | None = None,
    ) -> None:
        self.document_path = document_path
        self.operation = operation
        super().__init__(
            f"Document {operation} failed for '{document_path}': {error_message or 'Unknown error'}",
            document_path=document_path,
            operation=operation,
            error_message=error_message,
        )


@dataclass
class DynamoDBError(RecruitmentError):
    """DynamoDB operation failed."""
    
    operation: str  # "get", "put", "update", "query"
    table_name: str
    
    def __init__(
        self,
        operation: str,
        table_name: str,
        error_message: str | None = None,
    ) -> None:
        self.operation = operation
        self.table_name = table_name
        super().__init__(
            f"DynamoDB {operation} failed on table '{table_name}': {error_message or 'Unknown error'}",
            operation=operation,
            table_name=table_name,
            error_message=error_message,
        )


@dataclass
class ConditionalWriteError(DynamoDBError):
    """DynamoDB conditional write failed (optimistic lock conflict)."""
    
    expected_version: int | None = None
    actual_version: int | None = None
    
    def __init__(
        self,
        table_name: str,
        expected_version: int | None = None,
        actual_version: int | None = None,
    ) -> None:
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            operation="conditional_write",
            table_name=table_name,
            error_message=f"Version mismatch: expected {expected_version}, got {actual_version}",
        )


@dataclass
class SESError(RecruitmentError):
    """SES email operation failed."""
    
    operation: str  # "send", "verify"
    recipient: str | None = None
    
    def __init__(
        self,
        operation: str,
        recipient: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.operation = operation
        self.recipient = recipient
        super().__init__(
            f"SES {operation} failed{f' for {recipient}' if recipient else ''}: "
            f"{error_message or 'Unknown error'}",
            operation=operation,
            recipient=recipient,
            error_message=error_message,
        )


@dataclass
class S3Error(RecruitmentError):
    """S3 operation failed."""
    
    operation: str  # "upload", "download", "list", "delete"
    bucket: str
    key: str | None = None
    
    def __init__(
        self,
        operation: str,
        bucket: str,
        key: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.operation = operation
        self.bucket = bucket
        self.key = key
        super().__init__(
            f"S3 {operation} failed for s3://{bucket}/{key or '*'}: "
            f"{error_message or 'Unknown error'}",
            operation=operation,
            bucket=bucket,
            key=key,
            error_message=error_message,
        )
