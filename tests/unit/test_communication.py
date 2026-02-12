"""
Test Communication Agent

Unit tests for email drafting, template rendering, and sending.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents.communication.models import (
    EmailDraft,
    EmailResult,
    EmailStatus,
    TemplateContext,
)
from agents.communication.tools import (
    SUBJECT_TEMPLATES,
    TEMPLATE_FILES,
    draft_email,
    get_template_path,
    load_template,
    render_subject,
    render_template,
)
from agents.shared.tools.email import (
    DecodedReplyTo,
    decode_reply_to,
    encode_reply_to,
)


class TestTemplateContext:
    """Tests for TemplateContext model."""

    def test_create_context(self, campaign_id: str, provider_id: str):
        """Create TemplateContext with required fields."""
        ctx = TemplateContext(
            provider_name="John Smith",
            provider_email="john@example.com",
            provider_market="atlanta",
            provider_id=provider_id,
            campaign_id=campaign_id,
        )
        assert ctx.provider_name == "John Smith"
        assert ctx.campaign_id == campaign_id

    def test_context_extra_fields(self, campaign_id: str, provider_id: str):
        """TemplateContext allows extra fields."""
        ctx = TemplateContext(
            provider_name="John",
            provider_email="john@example.com",
            provider_market="atlanta",
            provider_id=provider_id,
            campaign_id=campaign_id,
            custom_field="custom value",  # Extra field
        )
        assert ctx.model_dump()["custom_field"] == "custom value"

    def test_to_template_vars(self, campaign_id: str, provider_id: str):
        """to_template_vars returns non-None fields."""
        ctx = TemplateContext(
            provider_name="John",
            provider_email="john@example.com",
            provider_market="atlanta",
            provider_id=provider_id,
            campaign_id=campaign_id,
            equipment_list="bucket truck, spectrum analyzer",
            missing_documents=None,  # Should be excluded
        )
        vars = ctx.to_template_vars()
        
        assert "provider_name" in vars
        assert "equipment_list" in vars
        # to_template_vars excludes None values
        assert "missing_documents" not in vars


class TestEmailDraft:
    """Tests for EmailDraft model."""

    def test_create_draft(self, campaign_id: str, provider_id: str):
        """Create valid EmailDraft."""
        draft = EmailDraft(
            subject="Test Subject",
            body_text="Test body content",
            to_address="test@example.com",
            reply_to="campaign+test_provider+test@example.com",
            campaign_id=campaign_id,
            provider_id=provider_id,
            message_type="initial_outreach",
        )
        assert draft.subject == "Test Subject"
        assert draft.message_type == "initial_outreach"

    def test_draft_with_html(self, campaign_id: str, provider_id: str):
        """EmailDraft can include HTML body."""
        draft = EmailDraft(
            subject="Test",
            body_text="Plain text",
            body_html="<p>HTML text</p>",
            to_address="test@example.com",
            reply_to="test@example.com",
            campaign_id=campaign_id,
            provider_id=provider_id,
            message_type="initial_outreach",
        )
        assert draft.body_html == "<p>HTML text</p>"

    def test_subject_validation(self, campaign_id: str, provider_id: str):
        """Subject cannot be empty."""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError, match="Subject cannot be empty"):
            EmailDraft(
                subject="   ",  # Whitespace only
                body_text="Test body",
                to_address="test@example.com",
                reply_to="test@example.com",
                campaign_id=campaign_id,
                provider_id=provider_id,
                message_type="test",
            )

    def test_body_validation(self, campaign_id: str, provider_id: str):
        """Body cannot be empty."""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError, match="Body cannot be empty"):
            EmailDraft(
                subject="Test Subject",
                body_text="",
                to_address="test@example.com",
                reply_to="test@example.com",
                campaign_id=campaign_id,
                provider_id=provider_id,
                message_type="test",
            )


class TestEmailResult:
    """Tests for EmailResult model."""

    def test_success_result(self, campaign_id: str, provider_id: str):
        """Create success result."""
        result = EmailResult.success_result(
            message_id="abc123",
            campaign_id=campaign_id,
            provider_id=provider_id,
            message_type="initial_outreach",
            recipient="test@example.com",
        )
        assert result.success is True
        assert result.status == EmailStatus.SENT
        assert result.message_id == "abc123"

    def test_failure_result(self, campaign_id: str, provider_id: str):
        """Create failure result."""
        result = EmailResult(
            success=False,
            status=EmailStatus.FAILED,
            campaign_id=campaign_id,
            provider_id=provider_id,
            message_type="initial_outreach",
            recipient="test@example.com",
            error_message="Invalid address",
            error_code="InvalidParameterValue",
        )
        assert result.success is False
        assert result.error_message == "Invalid address"


class TestTemplateFiles:
    """Tests for template file mappings."""

    def test_all_message_types_have_templates(self):
        """Each message type maps to a template file."""
        expected_types = [
            "initial_outreach",
            "follow_up",
            "missing_document",
            "clarification",
            "qualified_confirmation",
            "rejection",
        ]
        for msg_type in expected_types:
            assert msg_type in TEMPLATE_FILES

    def test_all_message_types_have_subjects(self):
        """Each message type has a subject template."""
        for msg_type in TEMPLATE_FILES:
            assert msg_type in SUBJECT_TEMPLATES


class TestGetTemplatePath:
    """Tests for get_template_path function."""

    def test_valid_message_type(self):
        """Valid message type returns Path."""
        path = get_template_path("initial_outreach")
        assert isinstance(path, Path)
        assert path.name == "initial_outreach.txt"

    def test_invalid_message_type(self):
        """Invalid message type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown message type"):
            get_template_path("invalid_type")


class TestRenderTemplate:
    """Tests for render_template function."""

    def test_render_simple_template(self, campaign_id: str, provider_id: str):
        """Render template with simple substitutions."""
        template = "Hello {{ provider_name }}! Welcome to {{ campaign_type }}."
        context = TemplateContext(
            provider_name="John",
            provider_email="john@example.com",
            provider_market="atlanta",
            provider_id=provider_id,
            campaign_id=campaign_id,
            campaign_type="Satellite Upgrade",
        )
        
        result = render_template(template, context)
        assert "Hello John!" in result
        assert "Satellite Upgrade" in result

    def test_render_with_dict_context(self):
        """Template renders with dict context."""
        template = "Market: {{ market }}, Equipment: {{ equipment }}"
        context = {"market": "Chicago", "equipment": "bucket truck"}
        
        result = render_template(template, context)
        assert "Chicago" in result
        assert "bucket truck" in result

    def test_missing_variable_renders_empty(self):
        """Missing template variable renders empty by default (Jinja2 behavior)."""
        template = "Hello {{ missing_var }}!"
        context = {"some_var": "value"}
        
        # Jinja2 with default settings renders undefined as empty string
        result = render_template(template, context)
        assert result == "Hello !"


class TestRenderSubject:
    """Tests for render_subject function."""

    def test_render_initial_outreach_subject(self, campaign_id: str, provider_id: str):
        """Render initial outreach subject."""
        context = TemplateContext(
            provider_name="John",
            provider_email="john@example.com",
            provider_market="Atlanta",
            provider_id=provider_id,
            campaign_id=campaign_id,
            campaign_type="Satellite Upgrade",
        )
        
        subject = render_subject("initial_outreach", context)
        assert "Satellite Upgrade" in subject
        # Subject template uses 'market' key derived from provider_market or default
        assert "your area" in subject or "atlanta" in subject.lower()

    def test_render_subject_with_defaults(self, campaign_id: str, provider_id: str):
        """Subject uses defaults for missing values."""
        context = TemplateContext(
            provider_name="John",
            provider_email="john@example.com",
            provider_market="atlanta",
            provider_id=provider_id,
            campaign_id=campaign_id,
            # campaign_type not provided
        )
        
        subject = render_subject("initial_outreach", context)
        # Should use default for campaign_type
        assert len(subject) > 0

    def test_render_subject_unknown_type_uses_default(
        self, campaign_id: str, provider_id: str
    ):
        """Unknown message type uses default subject template."""
        context = TemplateContext(
            provider_name="John",
            provider_email="john@example.com",
            provider_market="Chicago",
            provider_id=provider_id,
            campaign_id=campaign_id,
        )
        
        # Unknown type should fall back to default
        subject = render_subject("unknown_type", context)
        # Default template uses 'market' key with fallback to 'your area'
        assert "your area" in subject or "chicago" in subject.lower()


class TestReplyToEncoding:
    """Tests for Reply-To address encoding/decoding."""

    def test_encode_reply_to(self, campaign_id: str, provider_id: str):
        """Encode campaign and provider IDs into Reply-To."""
        reply_to = encode_reply_to(campaign_id, provider_id, domain="test.example.com")
        
        assert f"campaign+{campaign_id}" in reply_to
        assert f"provider+{provider_id}" in reply_to
        assert reply_to.endswith("@test.example.com")

    def test_decode_reply_to(self, campaign_id: str, provider_id: str):
        """Decode Reply-To to extract IDs."""
        reply_to = f"campaign+{campaign_id}_provider+{provider_id}@test.example.com"
        
        decoded = decode_reply_to(reply_to)
        
        assert decoded.campaign_id == campaign_id
        assert decoded.provider_id == provider_id
        assert decoded.domain == "test.example.com"

    def test_encode_decode_roundtrip(self, campaign_id: str, provider_id: str):
        """Encoding and decoding preserves IDs."""
        original_reply_to = encode_reply_to(
            campaign_id, provider_id, domain="mail.test.com"
        )
        decoded = decode_reply_to(original_reply_to)
        
        assert decoded.campaign_id == campaign_id
        assert decoded.provider_id == provider_id

    def test_invalid_reply_to_format(self):
        """Invalid Reply-To format raises error."""
        from agents.shared.exceptions import InvalidEmailFormatError
        
        with pytest.raises(InvalidEmailFormatError):
            decode_reply_to("invalid@example.com")

    def test_invalid_campaign_id_characters(self):
        """Campaign ID with invalid characters raises error."""
        from agents.shared.exceptions import InvalidEmailFormatError
        
        with pytest.raises(InvalidEmailFormatError):
            encode_reply_to("campaign@invalid", "provider-123")


class TestDraftEmail:
    """Tests for draft_email function."""

    def test_draft_initial_outreach(self, campaign_id: str, provider_id: str):
        """Draft initial outreach email."""
        # This would normally load templates, so we need to mock
        with patch("agents.communication.tools.load_template") as mock_load:
            mock_load.return_value = (
                "Hello {{ provider_name }},\n\n"
                "We have an opportunity in {{ provider_market }}.\n\n"
                "Requirements: {{ equipment_list }}\n\n"
                "Best regards"
            )
            
            draft = draft_email(
                campaign_id=campaign_id,
                provider_id=provider_id,
                provider_email="test@example.com",
                provider_name="Test Provider",
                provider_market="Atlanta",
                message_type="initial_outreach",
                template_data={
                    "campaign_type": "Satellite Upgrade",
                    "equipment_list": "bucket truck, spectrum analyzer",
                },
            )
            
            assert isinstance(draft, EmailDraft)
            assert "Test Provider" in draft.body_text
            assert "Atlanta" in draft.body_text
            assert draft.to_address == "test@example.com"
            assert draft.campaign_id == campaign_id

    def test_draft_with_custom_message(self, campaign_id: str, provider_id: str):
        """Draft email with custom message."""
        draft = draft_email(
            campaign_id=campaign_id,
            provider_id=provider_id,
            provider_email="test@example.com",
            provider_name="Test Provider",
            provider_market="Chicago",
            message_type="clarification",
            custom_message="This is a custom message for you.",
        )
        
        assert isinstance(draft, EmailDraft)
        assert draft.body_text == "This is a custom message for you."


class TestEmailTemplates:
    """Tests for email template files existence."""

    def test_initial_outreach_template_exists(self):
        """initial_outreach.txt template exists."""
        path = get_template_path("initial_outreach")
        assert path.exists(), f"Template not found: {path}"

    def test_follow_up_template_exists(self):
        """follow_up.txt template exists."""
        path = get_template_path("follow_up")
        assert path.exists(), f"Template not found: {path}"

    def test_missing_document_template_exists(self):
        """missing_document.txt template exists."""
        path = get_template_path("missing_document")
        assert path.exists(), f"Template not found: {path}"

    def test_qualified_confirmation_template_exists(self):
        """qualified_confirmation.txt template exists."""
        path = get_template_path("qualified_confirmation")
        assert path.exists(), f"Template not found: {path}"

    def test_rejection_template_exists(self):
        """rejection.txt template exists."""
        path = get_template_path("rejection")
        assert path.exists(), f"Template not found: {path}"

    def test_clarification_template_exists(self):
        """clarification.txt template exists."""
        path = get_template_path("clarification")
        assert path.exists(), f"Template not found: {path}"


class TestEmailStatus:
    """Tests for EmailStatus enum."""

    def test_all_statuses_defined(self):
        """All expected email statuses are defined."""
        expected = ["pending", "sent", "failed", "bounced"]
        actual = [s.value for s in EmailStatus]
        assert sorted(expected) == sorted(actual)
