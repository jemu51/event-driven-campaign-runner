"""
Event Models

Pydantic models for all events in the recruitment automation system.
These models are derived from contracts/events.json and provide
validation and serialization for EventBridge communication.
"""

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TraceContext(BaseModel):
    """OpenTelemetry trace context for distributed tracing."""
    
    model_config = ConfigDict(frozen=True)
    
    trace_id: str = Field(
        ...,
        pattern=r"^[a-f0-9]{32}$",
        description="32-character hex trace ID",
    )
    span_id: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{16}$",
        description="16-character hex span ID",
    )
    parent_span_id: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{16}$",
        description="16-character hex parent span ID",
    )


class Attachment(BaseModel):
    """Email attachment metadata."""
    
    model_config = ConfigDict(frozen=True)
    
    filename: str = Field(..., description="Original filename of the attachment")
    s3_path: str = Field(
        ...,
        pattern=r"^s3://",
        description="S3 URI where attachment is stored",
    )
    content_type: str = Field(..., description="MIME type of the attachment")
    size_bytes: int = Field(..., ge=0, description="File size in bytes")


class MessageType(str, Enum):
    """Type of message being sent to provider."""
    
    INITIAL_OUTREACH = "initial_outreach"
    FOLLOW_UP = "follow_up"
    MISSING_DOCUMENT = "missing_document"
    CLARIFICATION = "clarification"
    QUALIFIED_CONFIRMATION = "qualified_confirmation"
    REJECTION = "rejection"


class DocumentType(str, Enum):
    """Classified document type."""
    
    INSURANCE_CERTIFICATE = "insurance_certificate"
    LICENSE = "license"
    CERTIFICATION = "certification"
    W9 = "w9"
    OTHER = "other"


class ScreeningDecision(str, Enum):
    """Final screening decision for a provider."""
    
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    UNDER_REVIEW = "UNDER_REVIEW"


class FollowUpReason(str, Enum):
    """Reason for follow-up."""
    
    NO_RESPONSE = "no_response"
    MISSING_DOCUMENT = "missing_document"
    INCOMPLETE_INFO = "incomplete_info"


class ReplyType(str, Enum):
    """Type of reply being requested to provider."""
    
    MISSING_DOCUMENT = "missing_document"
    INVALID_DOCUMENT = "invalid_document"
    CLARIFICATION_NEEDED = "clarification_needed"
    ADDITIONAL_INFO = "additional_info"


# --- Nested Models ---


class EquipmentRequirements(BaseModel):
    """Equipment requirements for a campaign."""
    
    model_config = ConfigDict(frozen=True)
    
    required: list[str] = Field(default_factory=list, description="Required equipment keywords")
    optional: list[str] = Field(default_factory=list, description="Nice-to-have equipment")


class DocumentRequirements(BaseModel):
    """Document requirements for a campaign."""
    
    model_config = ConfigDict(frozen=True)
    
    required: list[str] = Field(default_factory=list, description="Required document types")
    insurance_min_coverage: int | None = Field(
        default=None, 
        description="Minimum insurance coverage in dollars",
    )


class CertificationRequirements(BaseModel):
    """Certification requirements for a campaign."""
    
    model_config = ConfigDict(frozen=True)
    
    required: list[str] = Field(default_factory=list, description="Required certifications")
    preferred: list[str] = Field(default_factory=list, description="Preferred certifications")


class Requirements(BaseModel):
    """Campaign requirements specification."""
    
    model_config = ConfigDict(frozen=True)
    
    type: str = Field(..., description="Campaign type (e.g., satellite_upgrade)")
    markets: list[str] = Field(default_factory=list, description="Target geographic markets")
    providers_per_market: int = Field(default=5, ge=1, description="Providers needed per market")
    equipment: EquipmentRequirements = Field(default_factory=EquipmentRequirements)
    documents: DocumentRequirements = Field(default_factory=DocumentRequirements)
    certifications: CertificationRequirements = Field(default_factory=CertificationRequirements)
    travel_required: bool = Field(default=False, description="Whether travel is required")


class TemplateData(BaseModel):
    """Data for email template rendering."""
    
    model_config = ConfigDict(frozen=True, extra="allow")
    
    campaign_type: str | None = None
    market: str | None = None
    equipment_list: str | None = None
    insurance_requirement: str | None = None
    missing_documents: list[str] | None = None
    question: str | None = None
    reason: str | None = None
    next_steps: str | None = None
    days_since_contact: int | None = None


class ExtractedFields(BaseModel):
    """Structured data extracted from document via OCR."""
    
    model_config = ConfigDict(frozen=True)
    
    expiry_date: date | None = Field(default=None, description="Document expiry date")
    coverage_amount: int | None = Field(default=None, ge=0, description="Insurance coverage in dollars")
    policy_holder: str | None = Field(default=None, description="Name on policy/document")
    policy_number: str | None = Field(default=None, description="Policy or document number")
    insurance_company: str | None = Field(default=None, description="Insurance carrier name")


class ConfidenceScores(BaseModel):
    """OCR confidence scores per field."""
    
    model_config = ConfigDict(frozen=True, extra="allow")
    
    # Field name to confidence score (0-1)
    # Using extra="allow" for dynamic field names


class ScreeningResults(BaseModel):
    """Detailed screening analysis results."""
    
    model_config = ConfigDict(frozen=True)
    
    equipment_confirmed: list[str] = Field(default_factory=list)
    equipment_missing: list[str] = Field(default_factory=list)
    travel_confirmed: bool | None = None
    documents_valid: bool | None = None
    insurance_coverage: int | None = None
    insurance_expiry: date | None = None
    certifications_found: list[str] = Field(default_factory=list)


# --- Event Models ---


class BaseEvent(BaseModel):
    """Base class for all events."""
    
    model_config = ConfigDict(frozen=True)
    
    campaign_id: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9-]+$",
        description="Campaign identifier",
    )
    trace_context: TraceContext | None = Field(
        default=None,
        description="OpenTelemetry trace context",
    )
    
    def to_eventbridge_detail(self) -> dict:
        """Convert to EventBridge detail payload."""
        return self.model_dump(mode="json", exclude_none=True)


class NewCampaignRequestedEvent(BaseEvent):
    """
    Buyer creates new recruitment campaign.
    
    Source: recruitment.api
    Triggers: CampaignPlannerAgent
    Produces: SendMessageRequested
    """
    
    buyer_id: str = Field(..., description="Buyer/client identifier")
    requirements: Requirements = Field(..., description="Campaign requirements")
    
    @classmethod
    def detail_type(cls) -> str:
        return "NewCampaignRequested"


class SendMessageRequestedEvent(BaseEvent):
    """
    Request to send email to provider.
    
    Source: recruitment.agents.campaign_planner
    Triggers: CommunicationAgent
    """
    
    provider_id: str = Field(..., description="Provider identifier")
    provider_email: str | None = Field(default=None, description="Provider's email address")
    provider_name: str | None = Field(default=None, description="Provider's display name")
    provider_market: str | None = Field(default=None, description="Target market")
    message_type: MessageType = Field(..., description="Type of message being sent")
    template_data: TemplateData | None = Field(default=None, description="Template variables")
    custom_message: str | None = Field(default=None, description="Custom message content")
    
    @classmethod
    def detail_type(cls) -> str:
        return "SendMessageRequested"


class ProviderResponseReceivedEvent(BaseEvent):
    """
    Provider replied to outreach email.
    
    Source: recruitment.lambdas.process_inbound_email
    Triggers: ScreeningAgent
    Produces: SendMessageRequested, DocumentProcessed, ScreeningCompleted
    """
    
    provider_id: str = Field(..., description="Provider identifier")
    body: str = Field(..., min_length=1, max_length=10000, description="Email body text")
    attachments: list[Attachment] = Field(default_factory=list, description="Email attachments")
    received_at: int = Field(..., ge=0, description="Unix epoch timestamp")
    email_thread_id: str = Field(..., description="SES message/thread identifier")
    from_address: str | None = Field(default=None, description="Sender's email address")
    subject: str | None = Field(default=None, description="Email subject line")
    
    @classmethod
    def detail_type(cls) -> str:
        return "ProviderResponseReceived"


class DocumentProcessedEvent(BaseEvent):
    """
    Document OCR completed via Textract.
    
    Source: recruitment.lambdas.textract_completion
    Triggers: ScreeningAgent
    Produces: ScreeningCompleted, SendMessageRequested
    """
    
    provider_id: str = Field(..., description="Provider identifier")
    document_s3_path: str = Field(
        ...,
        pattern=r"^s3://",
        description="S3 URI of the processed document",
    )
    document_type: DocumentType = Field(..., description="Classified document type")
    job_id: str = Field(..., description="Textract job identifier")
    ocr_text: str | None = Field(default=None, description="Raw OCR text")
    extracted_fields: ExtractedFields | None = Field(default=None, description="Structured data")
    confidence_scores: dict[str, float] | None = Field(
        default=None,
        description="OCR confidence scores per field",
    )
    
    @classmethod
    def detail_type(cls) -> str:
        return "DocumentProcessed"
    
    @field_validator("confidence_scores")
    @classmethod
    def validate_confidence_scores(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is not None:
            for key, score in v.items():
                if not 0 <= score <= 1:
                    raise ValueError(f"Confidence score for '{key}' must be between 0 and 1")
        return v


class ScreeningCompletedEvent(BaseEvent):
    """
    Provider screening finished with decision.
    
    Source: recruitment.agents.screening
    Triggers: NotificationAgent
    """
    
    provider_id: str = Field(..., description="Provider identifier")
    decision: ScreeningDecision = Field(..., description="Final screening decision")
    reasoning: str | None = Field(default=None, description="Human-readable explanation")
    confidence_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Confidence in the decision (0-1)",
    )
    screening_results: ScreeningResults | None = Field(default=None, description="Detailed analysis")
    artifacts_reviewed: list[str] = Field(default_factory=list, description="S3 paths of documents reviewed")
    
    @classmethod
    def detail_type(cls) -> str:
        return "ScreeningCompleted"


class FollowUpTriggeredEvent(BaseEvent):
    """
    Scheduled follow-up reminder triggered for dormant session.
    
    Source: recruitment.lambdas.send_follow_ups
    Triggers: CommunicationAgent
    Produces: SendMessageRequested
    """
    
    provider_id: str = Field(..., description="Provider identifier")
    reason: FollowUpReason | None = Field(default=None, description="Reason for follow-up")
    follow_up_number: int = Field(..., ge=1, le=3, description="Which follow-up attempt (1-3)")
    days_since_last_contact: int = Field(..., ge=0, description="Days elapsed since last contact")
    current_status: str | None = Field(default=None, description="Provider's current status")
    
    @classmethod
    def detail_type(cls) -> str:
        return "FollowUpTriggered"


class ReplyContext(BaseModel):
    """Context for generating a reply to provider."""
    
    model_config = ConfigDict(frozen=True)
    
    missing_items: list[str] = Field(
        default_factory=list,
        description="List of missing documents or information",
    )
    validation_errors: list[str] = Field(
        default_factory=list,
        description="List of validation errors found",
    )
    questions: list[str] = Field(
        default_factory=list,
        description="Questions to ask the provider",
    )
    original_response_summary: str | None = Field(
        default=None,
        description="Summary of the provider's original response",
    )


class ReplyToProviderRequestedEvent(BaseEvent):
    """
    Request to send a reply to provider for missing/invalid content.
    
    Source: recruitment.agents.screening
    Triggers: CommunicationAgent
    """
    
    provider_id: str = Field(..., description="Provider identifier")
    provider_email: str | None = Field(default=None, description="Provider's email address")
    provider_name: str | None = Field(default=None, description="Provider's display name")
    provider_market: str | None = Field(default=None, description="Target market")
    reply_type: ReplyType = Field(..., description="Type of reply being requested")
    context: ReplyContext = Field(..., description="Context for generating the reply")
    in_reply_to_message_id: str | None = Field(
        default=None,
        description="Message ID of the email being replied to",
    )
    
    @classmethod
    def detail_type(cls) -> str:
        return "ReplyToProviderRequested"


# Event type mapping for deserialization
EVENT_TYPE_MAP: dict[str, type[BaseEvent]] = {
    "NewCampaignRequested": NewCampaignRequestedEvent,
    "SendMessageRequested": SendMessageRequestedEvent,
    "ProviderResponseReceived": ProviderResponseReceivedEvent,
    "DocumentProcessed": DocumentProcessedEvent,
    "ScreeningCompleted": ScreeningCompletedEvent,
    "FollowUpTriggered": FollowUpTriggeredEvent,
    "ReplyToProviderRequested": ReplyToProviderRequestedEvent,
}


def parse_event(detail_type: str, detail: dict) -> BaseEvent:
    """
    Parse an EventBridge event detail into the appropriate model.
    
    Args:
        detail_type: The EventBridge detail-type
        detail: The event detail payload
        
    Returns:
        Parsed event model
        
    Raises:
        ValueError: If detail_type is unknown
        ValidationError: If detail doesn't match schema
    """
    event_class = EVENT_TYPE_MAP.get(detail_type)
    if event_class is None:
        raise ValueError(f"Unknown event type: {detail_type}")
    return event_class.model_validate(detail)
