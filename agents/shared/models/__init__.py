# Shared Models
"""
Pydantic models for events, DynamoDB items, and email threading.
"""

from agents.shared.models.events import (
    TraceContext,
    Attachment,
    Requirements,
    TemplateData,
    ExtractedFields,
    ConfidenceScores,
    ScreeningResults,
    NewCampaignRequestedEvent,
    SendMessageRequestedEvent,
    ProviderResponseReceivedEvent,
    DocumentProcessedEvent,
    ScreeningCompletedEvent,
    FollowUpTriggeredEvent,
)
from agents.shared.models.dynamo import ProviderState
from agents.shared.models.email_thread import (
    EmailDirection,
    EmailAttachment,
    EmailMessage,
    EmailThread,
)

__all__ = [
    # Common models
    "TraceContext",
    "Attachment",
    "Requirements",
    "TemplateData",
    "ExtractedFields",
    "ConfidenceScores",
    "ScreeningResults",
    # Events
    "NewCampaignRequestedEvent",
    "SendMessageRequestedEvent",
    "ProviderResponseReceivedEvent",
    "DocumentProcessedEvent",
    "ScreeningCompletedEvent",
    "FollowUpTriggeredEvent",
    # DynamoDB
    "ProviderState",
    # Email Thread
    "EmailDirection",
    "EmailAttachment",
    "EmailMessage",
    "EmailThread",
]
