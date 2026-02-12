"""
Communication Agent Models

Pydantic models for email drafting and sending operations.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmailStatus(str, Enum):
    """Email delivery status."""
    
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    BOUNCED = "bounced"


class TemplateContext(BaseModel):
    """
    Context data for template rendering.
    
    This model aggregates all data available for email templates.
    """
    
    model_config = ConfigDict(frozen=True, extra="allow")
    
    # Provider information
    provider_name: str = Field(..., description="Provider's display name")
    provider_email: str = Field(..., description="Provider's email address")
    provider_market: str = Field(..., description="Target market")
    provider_id: str = Field(..., description="Provider identifier")
    
    # Campaign information
    campaign_id: str = Field(..., description="Campaign identifier")
    campaign_type: str | None = Field(default=None, description="Type of campaign")
    
    # Content variables
    equipment_list: str | None = Field(default=None, description="Required equipment as string")
    insurance_requirement: str | None = Field(default=None, description="Insurance requirement text")
    missing_documents: list[str] | None = Field(default=None, description="Missing document types")
    question: str | None = Field(default=None, description="Clarification question")
    reason: str | None = Field(default=None, description="Rejection reason")
    next_steps: str | None = Field(default=None, description="Next steps instructions")
    days_since_contact: int | None = Field(default=None, description="Days since last contact")
    deadline: str | None = Field(default=None, description="Response deadline")
    original_requirements: str | None = Field(default=None, description="Original requirements summary")
    
    def to_template_vars(self) -> dict[str, Any]:
        """
        Convert to dictionary for template rendering.
        
        Returns all non-None fields as template variables.
        """
        return {
            k: v for k, v in self.model_dump().items()
            if v is not None
        }


class EmailDraft(BaseModel):
    """
    A drafted email ready for sending.
    
    Contains subject, body, and metadata for sending via SES.
    """
    
    model_config = ConfigDict(frozen=True)
    
    # Content
    subject: str = Field(..., max_length=998, description="Email subject line")
    body_text: str = Field(..., description="Plain text email body")
    body_html: str | None = Field(default=None, description="HTML email body")
    
    # Recipients
    to_address: str = Field(..., description="Recipient email address")
    reply_to: str = Field(..., description="Reply-To address (encoded)")
    
    # Metadata
    campaign_id: str = Field(..., description="Campaign identifier")
    provider_id: str = Field(..., description="Provider identifier")
    message_type: str = Field(..., description="Type of message")
    template_name: str | None = Field(default=None, description="Template used")
    
    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        """Ensure subject is not empty and strip whitespace."""
        v = v.strip()
        if not v:
            raise ValueError("Subject cannot be empty")
        return v
    
    @field_validator("body_text")
    @classmethod
    def validate_body(cls, v: str) -> str:
        """Ensure body is not empty."""
        v = v.strip()
        if not v:
            raise ValueError("Body cannot be empty")
        return v


class EmailResult(BaseModel):
    """
    Result of an email send operation.
    
    Contains success/failure status and SES metadata.
    """
    
    model_config = ConfigDict(frozen=True)
    
    # Status
    success: bool = Field(..., description="Whether email was sent successfully")
    status: EmailStatus = Field(..., description="Email delivery status")
    
    # Identifiers
    message_id: str | None = Field(default=None, description="SES message ID")
    campaign_id: str = Field(..., description="Campaign identifier")
    provider_id: str = Field(..., description="Provider identifier")
    
    # Metadata
    sent_at: int | None = Field(default=None, description="Unix timestamp when sent")
    error_message: str | None = Field(default=None, description="Error message if failed")
    error_code: str | None = Field(default=None, description="Error code if failed")
    
    # Context
    message_type: str = Field(..., description="Type of message sent")
    recipient: str = Field(..., description="Recipient email address")
    
    @classmethod
    def success_result(
        cls,
        message_id: str,
        campaign_id: str,
        provider_id: str,
        message_type: str,
        recipient: str,
    ) -> "EmailResult":
        """Create a successful email result."""
        return cls(
            success=True,
            status=EmailStatus.SENT,
            message_id=message_id,
            campaign_id=campaign_id,
            provider_id=provider_id,
            sent_at=int(datetime.now(timezone.utc).timestamp()),
            message_type=message_type,
            recipient=recipient,
        )
    
    @classmethod
    def failure_result(
        cls,
        campaign_id: str,
        provider_id: str,
        message_type: str,
        recipient: str,
        error_message: str,
        error_code: str | None = None,
    ) -> "EmailResult":
        """Create a failed email result."""
        return cls(
            success=False,
            status=EmailStatus.FAILED,
            campaign_id=campaign_id,
            provider_id=provider_id,
            message_type=message_type,
            recipient=recipient,
            error_message=error_message,
            error_code=error_code,
        )


class CommunicationResult(BaseModel):
    """
    Result of the communication agent's execution.
    
    Summary of email operations performed.
    """
    
    model_config = ConfigDict(frozen=True)
    
    # Summary
    campaign_id: str = Field(..., description="Campaign identifier")
    provider_id: str = Field(..., description="Provider identifier")
    message_type: str = Field(..., description="Type of message")
    
    # Result
    email_sent: bool = Field(..., description="Whether email was sent")
    message_id: str | None = Field(default=None, description="SES message ID")
    state_updated: bool = Field(..., description="Whether DynamoDB state was updated")
    new_status: str | None = Field(default=None, description="New provider status")
    
    # Errors
    errors: list[str] = Field(default_factory=list, description="Any errors encountered")
