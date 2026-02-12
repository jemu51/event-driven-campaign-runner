"""
Test Models

Unit tests for Pydantic event models and DynamoDB state models.
Covers validation, serialization, and deserialization.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from agents.shared.models.dynamo import ProviderKey, ProviderState
from agents.shared.models.events import (
    Attachment,
    DocumentProcessedEvent,
    DocumentType,
    FollowUpReason,
    FollowUpTriggeredEvent,
    MessageType,
    NewCampaignRequestedEvent,
    ProviderResponseReceivedEvent,
    Requirements,
    ScreeningCompletedEvent,
    ScreeningDecision,
    SendMessageRequestedEvent,
    TraceContext,
    parse_event,
)
from agents.shared.state_machine import ProviderStatus


class TestTraceContext:
    """Tests for TraceContext model."""

    def test_valid_trace_context(self, trace_id: str, span_id: str):
        """Valid trace context with all fields."""
        ctx = TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=span_id,
        )
        assert ctx.trace_id == trace_id
        assert ctx.span_id == span_id

    def test_trace_context_optional_spans(self, trace_id: str):
        """Span IDs are optional."""
        ctx = TraceContext(trace_id=trace_id)
        assert ctx.trace_id == trace_id
        assert ctx.span_id is None
        assert ctx.parent_span_id is None

    def test_invalid_trace_id_pattern(self):
        """Trace ID must be 32 hex chars."""
        with pytest.raises(ValidationError, match="trace_id"):
            TraceContext(trace_id="invalid")

        with pytest.raises(ValidationError, match="trace_id"):
            TraceContext(trace_id="abc")  # Too short

    def test_invalid_span_id_pattern(self, trace_id: str):
        """Span ID must be 16 hex chars."""
        with pytest.raises(ValidationError, match="span_id"):
            TraceContext(trace_id=trace_id, span_id="invalid")


class TestAttachment:
    """Tests for Attachment model."""

    def test_valid_attachment(self):
        """Valid attachment with all fields."""
        attachment = Attachment(
            filename="insurance.pdf",
            s3_path="s3://bucket/path/to/file.pdf",
            content_type="application/pdf",
            size_bytes=125000,
        )
        assert attachment.filename == "insurance.pdf"
        assert attachment.s3_path == "s3://bucket/path/to/file.pdf"
        assert attachment.content_type == "application/pdf"
        assert attachment.size_bytes == 125000

    def test_invalid_s3_path(self):
        """S3 path must start with s3://."""
        with pytest.raises(ValidationError, match="s3_path"):
            Attachment(
                filename="test.pdf",
                s3_path="invalid/path",
                content_type="application/pdf",
                size_bytes=100,
            )

    def test_negative_size(self):
        """Size must be non-negative."""
        with pytest.raises(ValidationError, match="size_bytes"):
            Attachment(
                filename="test.pdf",
                s3_path="s3://bucket/test.pdf",
                content_type="application/pdf",
                size_bytes=-1,
            )


class TestRequirements:
    """Tests for Requirements model."""

    def test_valid_requirements(self, sample_requirements: dict):
        """Valid requirements object."""
        req = Requirements.model_validate(sample_requirements)
        assert req.type == "satellite_upgrade"
        assert "atlanta" in req.markets
        assert "bucket_truck" in req.equipment.required

    def test_requirements_defaults(self):
        """Requirements has sensible defaults."""
        req = Requirements(type="test_campaign")
        assert req.markets == []
        assert req.providers_per_market == 5
        assert req.equipment.required == []
        assert req.travel_required is False


class TestNewCampaignRequestedEvent:
    """Tests for NewCampaignRequested event."""

    def test_valid_event(self, new_campaign_event: dict):
        """Valid NewCampaignRequested event."""
        event = NewCampaignRequestedEvent.model_validate(new_campaign_event)
        assert event.campaign_id == new_campaign_event["campaign_id"]
        assert event.buyer_id == new_campaign_event["buyer_id"]
        assert event.requirements.type == "satellite_upgrade"

    def test_detail_type(self, new_campaign_event: dict):
        """Verify detail_type class method."""
        assert NewCampaignRequestedEvent.detail_type() == "NewCampaignRequested"

    def test_to_eventbridge_detail(self, new_campaign_event: dict):
        """Event serializes to EventBridge format."""
        event = NewCampaignRequestedEvent.model_validate(new_campaign_event)
        detail = event.to_eventbridge_detail()
        assert detail["campaign_id"] == new_campaign_event["campaign_id"]
        assert "requirements" in detail

    def test_missing_campaign_id(self, new_campaign_event: dict):
        """campaign_id is required."""
        del new_campaign_event["campaign_id"]
        with pytest.raises(ValidationError, match="campaign_id"):
            NewCampaignRequestedEvent.model_validate(new_campaign_event)

    def test_invalid_campaign_id_pattern(self, new_campaign_event: dict):
        """campaign_id must match pattern."""
        new_campaign_event["campaign_id"] = "invalid@id"
        with pytest.raises(ValidationError, match="campaign_id"):
            NewCampaignRequestedEvent.model_validate(new_campaign_event)


class TestSendMessageRequestedEvent:
    """Tests for SendMessageRequested event."""

    def test_valid_event(self, send_message_event: dict):
        """Valid SendMessageRequested event."""
        event = SendMessageRequestedEvent.model_validate(send_message_event)
        assert event.campaign_id == send_message_event["campaign_id"]
        assert event.provider_id == send_message_event["provider_id"]
        assert event.message_type == MessageType.INITIAL_OUTREACH

    def test_detail_type(self):
        """Verify detail_type class method."""
        assert SendMessageRequestedEvent.detail_type() == "SendMessageRequested"

    def test_all_message_types(self, send_message_event: dict):
        """All message types are valid."""
        for msg_type in MessageType:
            send_message_event["message_type"] = msg_type.value
            event = SendMessageRequestedEvent.model_validate(send_message_event)
            assert event.message_type == msg_type


class TestProviderResponseReceivedEvent:
    """Tests for ProviderResponseReceived event."""

    def test_valid_event(self, provider_response_event: dict):
        """Valid ProviderResponseReceived event."""
        event = ProviderResponseReceivedEvent.model_validate(provider_response_event)
        assert event.campaign_id == provider_response_event["campaign_id"]
        assert event.provider_id == provider_response_event["provider_id"]
        assert len(event.body) > 0

    def test_event_with_attachments(self, provider_response_with_attachment: dict):
        """Event with attachment list."""
        event = ProviderResponseReceivedEvent.model_validate(
            provider_response_with_attachment
        )
        assert len(event.attachments) == 1
        assert event.attachments[0].filename == "insurance_certificate.pdf"

    def test_detail_type(self):
        """Verify detail_type class method."""
        assert ProviderResponseReceivedEvent.detail_type() == "ProviderResponseReceived"

    def test_body_too_long(self, provider_response_event: dict):
        """Body must not exceed 10000 chars."""
        provider_response_event["body"] = "x" * 10001
        with pytest.raises(ValidationError, match="body"):
            ProviderResponseReceivedEvent.model_validate(provider_response_event)


class TestDocumentProcessedEvent:
    """Tests for DocumentProcessed event."""

    def test_valid_event(self, document_processed_event: dict):
        """Valid DocumentProcessed event."""
        # Adjust to match actual model fields
        event_data = {
            "campaign_id": document_processed_event["campaign_id"],
            "provider_id": document_processed_event["provider_id"],
            "document_s3_path": document_processed_event["s3_path"],
            "document_type": document_processed_event["document_type"],
            "job_id": "textract-job-123",
            "trace_context": document_processed_event["trace_context"],
        }
        event = DocumentProcessedEvent.model_validate(event_data)
        assert event.document_type == DocumentType.INSURANCE_CERTIFICATE

    def test_detail_type(self):
        """Verify detail_type class method."""
        assert DocumentProcessedEvent.detail_type() == "DocumentProcessed"

    def test_all_document_types(self, trace_context: dict, campaign_id: str, provider_id: str):
        """All document types are valid."""
        for doc_type in DocumentType:
            event_data = {
                "campaign_id": campaign_id,
                "provider_id": provider_id,
                "document_s3_path": "s3://bucket/doc.pdf",
                "document_type": doc_type.value,
                "job_id": "job-123",
                "trace_context": trace_context,
            }
            event = DocumentProcessedEvent.model_validate(event_data)
            assert event.document_type == doc_type

    def test_confidence_score_validation(
        self, trace_context: dict, campaign_id: str, provider_id: str
    ):
        """Confidence scores must be between 0 and 1."""
        event_data = {
            "campaign_id": campaign_id,
            "provider_id": provider_id,
            "document_s3_path": "s3://bucket/doc.pdf",
            "document_type": "insurance_certificate",
            "job_id": "job-123",
            "confidence_scores": {"field1": 1.5},  # Invalid
            "trace_context": trace_context,
        }
        with pytest.raises(ValidationError, match="Confidence score"):
            DocumentProcessedEvent.model_validate(event_data)


class TestScreeningCompletedEvent:
    """Tests for ScreeningCompleted event."""

    def test_valid_event(self, trace_context: dict, campaign_id: str, provider_id: str):
        """Valid ScreeningCompleted event."""
        event = ScreeningCompletedEvent(
            campaign_id=campaign_id,
            provider_id=provider_id,
            decision=ScreeningDecision.QUALIFIED,
            reasoning="All requirements met",
            confidence_score=0.95,
            trace_context=TraceContext.model_validate(trace_context),
        )
        assert event.decision == ScreeningDecision.QUALIFIED

    def test_detail_type(self):
        """Verify detail_type class method."""
        assert ScreeningCompletedEvent.detail_type() == "ScreeningCompleted"

    def test_all_decisions(self, trace_context: dict, campaign_id: str, provider_id: str):
        """All screening decisions are valid."""
        for decision in ScreeningDecision:
            event = ScreeningCompletedEvent(
                campaign_id=campaign_id,
                provider_id=provider_id,
                decision=decision,
                trace_context=TraceContext.model_validate(trace_context),
            )
            assert event.decision == decision


class TestFollowUpTriggeredEvent:
    """Tests for FollowUpTriggered event."""

    def test_valid_event(self, follow_up_event: dict):
        """Valid FollowUpTriggered event."""
        event = FollowUpTriggeredEvent(
            campaign_id=follow_up_event["campaign_id"],
            provider_id=follow_up_event["provider_id"],
            reason=FollowUpReason.NO_RESPONSE,
            follow_up_number=follow_up_event["follow_up_number"],
            days_since_last_contact=follow_up_event["days_since_contact"],
        )
        assert event.follow_up_number == 1
        assert event.reason == FollowUpReason.NO_RESPONSE

    def test_detail_type(self):
        """Verify detail_type class method."""
        assert FollowUpTriggeredEvent.detail_type() == "FollowUpTriggered"

    def test_follow_up_number_bounds(self, campaign_id: str, provider_id: str):
        """follow_up_number must be 1-3."""
        with pytest.raises(ValidationError, match="follow_up_number"):
            FollowUpTriggeredEvent(
                campaign_id=campaign_id,
                provider_id=provider_id,
                follow_up_number=0,  # Too low
                days_since_last_contact=3,
            )

        with pytest.raises(ValidationError, match="follow_up_number"):
            FollowUpTriggeredEvent(
                campaign_id=campaign_id,
                provider_id=provider_id,
                follow_up_number=4,  # Too high
                days_since_last_contact=3,
            )


class TestParseEvent:
    """Tests for parse_event function."""

    def test_parse_new_campaign(self, new_campaign_event: dict):
        """Parse NewCampaignRequested event."""
        event = parse_event("NewCampaignRequested", new_campaign_event)
        assert isinstance(event, NewCampaignRequestedEvent)

    def test_parse_send_message(self, send_message_event: dict):
        """Parse SendMessageRequested event."""
        event = parse_event("SendMessageRequested", send_message_event)
        assert isinstance(event, SendMessageRequestedEvent)

    def test_parse_unknown_type(self, new_campaign_event: dict):
        """Unknown event type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown event type"):
            parse_event("UnknownEventType", new_campaign_event)



class TestModelImmutability:
    """Tests verifying models are frozen/immutable."""

    def test_trace_context_frozen(self, trace_id: str):
        """TraceContext is immutable."""
        ctx = TraceContext(trace_id=trace_id)
        with pytest.raises(ValidationError):
            ctx.trace_id = "new_value"

    def test_attachment_frozen(self):
        """Attachment is immutable."""
        attachment = Attachment(
            filename="test.pdf",
            s3_path="s3://bucket/test.pdf",
            content_type="application/pdf",
            size_bytes=100,
        )
        with pytest.raises(ValidationError):
            attachment.filename = "new.pdf"

    def test_provider_state_frozen(
        self, campaign_id: str, provider_id: str, frozen_time: int
    ):
        """ProviderState is immutable."""
        state = ProviderState(
            campaign_id=campaign_id,
            provider_id=provider_id,
            status=ProviderStatus.INVITED,
            last_contacted_at=frozen_time,
            provider_email="test@example.com",
            provider_market="atlanta",
        )
        with pytest.raises(ValidationError):
            state.status = ProviderStatus.QUALIFIED
