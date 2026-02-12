"""
Tests for Communication Agent LLM Integration

Tests for:
- LLM prompts construction
- LLM email generation tools
- Draft creation from LLM output
- Feature flag checks
"""

from unittest.mock import MagicMock, patch
import pytest

from agents.communication.llm_prompts import (
    EMAIL_GENERATION_SYSTEM_PROMPT,
    build_email_generation_prompt,
    build_reply_email_prompt,
)
from agents.communication.llm_tools import (
    get_provider_type,
    generate_email_with_llm,
    generate_reply_email_with_llm,
    create_draft_from_llm_output,
    is_llm_email_enabled,
)
from agents.communication.models import EmailDraft
from agents.shared.llm import EmailGenerationOutput


# =============================================================================
# LLM Prompt Tests
# =============================================================================

class TestEmailGenerationSystemPrompt:
    """Tests for system prompt."""
    
    def test_system_prompt_exists(self):
        """System prompt should be defined."""
        assert EMAIL_GENERATION_SYSTEM_PROMPT is not None
        assert len(EMAIL_GENERATION_SYSTEM_PROMPT) > 100
    
    def test_system_prompt_contains_key_instructions(self):
        """System prompt should contain key instructions."""
        prompt = EMAIL_GENERATION_SYSTEM_PROMPT.lower()
        # Check for key elements
        assert "email" in prompt
        assert "professional" in prompt or "tone" in prompt


class TestBuildEmailGenerationPrompt:
    """Tests for email generation prompt builder."""
    
    def test_build_initial_outreach_prompt(self):
        """Should build prompt for initial outreach."""
        prompt = build_email_generation_prompt(
            message_type="initial_outreach",
            provider_name="John's Tech Services",
            provider_market="Atlanta",
            provider_type="independent_contractor",
            template_data={"campaign_name": "Satellite Upgrade"},
            conversation_history="[No previous conversation]",
        )
        
        assert "initial_outreach" in prompt.lower() or "initial" in prompt.lower()
        assert "John's Tech Services" in prompt
        assert "Atlanta" in prompt
        assert "Satellite Upgrade" in prompt
    
    def test_build_follow_up_prompt(self):
        """Should build prompt for follow-up emails."""
        prompt = build_email_generation_prompt(
            message_type="follow_up",
            provider_name="Tech Corp LLC",
            provider_market="Chicago",
            provider_type="corporate",
            template_data={"days_since_contact": 3},
            conversation_history="Previous: Initial outreach sent",
        )
        
        assert "follow_up" in prompt.lower() or "follow" in prompt.lower()
        assert "Tech Corp LLC" in prompt
        assert "Chicago" in prompt
    
    def test_prompt_includes_conversation_history(self):
        """Should include conversation history in prompt."""
        history = "From: Provider\nSubject: Re: Opportunity\nBody: I'm interested!"
        
        prompt = build_email_generation_prompt(
            message_type="clarification",
            provider_name="Test Provider",
            provider_market="Milwaukee",
            provider_type="independent_contractor",
            template_data={},
            conversation_history=history,
        )
        
        assert "interested" in prompt.lower()


class TestBuildReplyEmailPrompt:
    """Tests for reply email prompt builder."""
    
    def test_build_reply_prompt_missing_attachment(self):
        """Should build prompt for missing attachment reply."""
        prompt = build_reply_email_prompt(
            provider_name="John Doe",
            provider_market="Atlanta",
            provider_type="independent_contractor",
            reply_reason="missing_attachment",
            context={"missing_items": ["insurance_certificate"]},
            conversation_history="Previous conversation...",
        )
        
        assert "John Doe" in prompt
        assert "Atlanta" in prompt
        # Should reference the missing item
        assert "insurance" in prompt.lower() or "missing" in prompt.lower()
    
    def test_build_reply_prompt_clarification_needed(self):
        """Should build prompt for clarification reply."""
        prompt = build_reply_email_prompt(
            provider_name="Tech Services Inc",
            provider_market="Chicago",
            provider_type="corporate",
            reply_reason="clarification_needed",
            context={"questions": ["Do you have a bucket truck?"]},
            conversation_history="Previous conversation...",
        )
        
        assert "Tech Services Inc" in prompt
        assert "bucket truck" in prompt.lower() or "question" in prompt.lower()


# =============================================================================
# Provider Type Detection Tests
# =============================================================================

class TestGetProviderType:
    """Tests for provider type detection."""
    
    def test_none_provider_state(self):
        """Should default to independent_contractor for None."""
        result = get_provider_type(None)
        assert result == "independent_contractor"
    
    def test_corporate_llc(self):
        """Should detect LLC as corporate."""
        mock_state = MagicMock()
        mock_state.provider_name = "Smith Services LLC"
        
        result = get_provider_type(mock_state)
        assert result == "corporate"
    
    def test_corporate_inc(self):
        """Should detect Inc as corporate."""
        mock_state = MagicMock()
        mock_state.provider_name = "TechCorp Inc"
        
        result = get_provider_type(mock_state)
        assert result == "corporate"
    
    def test_corporate_corp(self):
        """Should detect Corp as corporate."""
        mock_state = MagicMock()
        mock_state.provider_name = "Atlanta Tech Corp"
        
        result = get_provider_type(mock_state)
        assert result == "corporate"
    
    def test_independent_contractor(self):
        """Should default to independent_contractor for individuals."""
        mock_state = MagicMock()
        mock_state.provider_name = "John Smith"
        
        result = get_provider_type(mock_state)
        assert result == "independent_contractor"
    
    def test_empty_name(self):
        """Should handle empty name."""
        mock_state = MagicMock()
        mock_state.provider_name = ""
        
        result = get_provider_type(mock_state)
        assert result == "independent_contractor"
    
    def test_missing_name_attribute(self):
        """Should handle missing provider_name attribute."""
        mock_state = MagicMock(spec=[])  # No attributes
        
        result = get_provider_type(mock_state)
        assert result == "independent_contractor"


# =============================================================================
# LLM Email Generation Tests
# =============================================================================

class TestGenerateEmailWithLLM:
    """Tests for LLM email generation."""
    
    def test_generate_email_calls_llm(self):
        """Should call LLM with correct parameters."""
        # Create mock LLM client
        mock_client = MagicMock()
        mock_output = EmailGenerationOutput(
            subject="Exciting Opportunity in Atlanta",
            body_text="Dear John, We have an opportunity...",
            tone="professional",
            includes_call_to_action=True,
            personalization_elements=["market", "name"],
        )
        mock_client.invoke_structured.return_value = mock_output
        
        result = generate_email_with_llm(
            campaign_id="camp-123",
            provider_id="prov-456",
            provider_name="John Smith",
            provider_market="Atlanta",
            provider_email="john@example.com",
            message_type="initial_outreach",
            template_data={"campaign_name": "Satellite Upgrade"},
            client=mock_client,
        )
        
        # Verify LLM was called
        mock_client.invoke_structured.assert_called_once()
        call_kwargs = mock_client.invoke_structured.call_args.kwargs
        
        assert call_kwargs["output_schema"] == EmailGenerationOutput
        assert "system_prompt" in call_kwargs
        
        # Verify result
        assert result.subject == "Exciting Opportunity in Atlanta"
        assert result.tone == "professional"
    
    def test_generate_email_with_conversation_history(self):
        """Should use provided conversation history."""
        mock_client = MagicMock()
        mock_output = EmailGenerationOutput(
            subject="Re: Your Interest",
            body_text="Thank you for your response...",
            tone="friendly",
            includes_call_to_action=True,
            personalization_elements=["previous_response"],
        )
        mock_client.invoke_structured.return_value = mock_output
        
        history = [MagicMock()]  # Mock email messages
        
        with patch("agents.communication.llm_tools.format_thread_for_context") as mock_format:
            mock_format.return_value = "Formatted history"
            
            result = generate_email_with_llm(
                campaign_id="camp-123",
                provider_id="prov-456",
                provider_name="Jane Doe",
                provider_market="Chicago",
                provider_email="jane@example.com",
                message_type="follow_up",
                template_data={},
                conversation_history=history,
                client=mock_client,
            )
        
        mock_format.assert_called_once_with(history, max_messages=5)
        assert result.subject == "Re: Your Interest"


class TestGenerateReplyEmailWithLLM:
    """Tests for LLM reply email generation."""
    
    def test_generate_reply_email(self):
        """Should generate reply email with LLM."""
        mock_client = MagicMock()
        mock_output = EmailGenerationOutput(
            subject="Re: Missing Document",
            body_text="We noticed your insurance document...",
            tone="friendly",
            includes_call_to_action=True,
            personalization_elements=["missing_doc"],
        )
        mock_client.invoke_structured.return_value = mock_output
        
        result = generate_reply_email_with_llm(
            campaign_id="camp-123",
            provider_id="prov-456",
            provider_name="Mike Johnson",
            provider_market="Milwaukee",
            provider_email="mike@example.com",
            reply_reason="missing_attachment",
            context={"missing_items": ["insurance_certificate"]},
            client=mock_client,
        )
        
        mock_client.invoke_structured.assert_called_once()
        assert "Missing Document" in result.subject


# =============================================================================
# Draft Creation Tests
# =============================================================================

class TestCreateDraftFromLLMOutput:
    """Tests for creating EmailDraft from LLM output."""
    
    @patch("agents.communication.llm_tools.get_settings")
    @patch("agents.communication.llm_tools.encode_reply_to")
    def test_create_draft_from_llm_output(self, mock_encode, mock_settings):
        """Should create valid EmailDraft from LLM output."""
        # Setup mocks
        mock_settings.return_value = MagicMock(
            ses_from_address="noreply@example.com",
            ses_from_name="Recruitment Team",
            ses_reply_to_domain="reply.example.com",
        )
        mock_encode.return_value = "reply-camp123-prov456@reply.example.com"
        
        llm_output = EmailGenerationOutput(
            subject="Join Our Network",
            body_text="Dear Provider,\n\nWe are excited to invite you...",
            tone="professional",
            includes_call_to_action=True,
            personalization_elements=["name", "market"],
        )
        
        draft = create_draft_from_llm_output(
            llm_output=llm_output,
            campaign_id="camp-123",
            provider_id="prov-456",
            provider_email="provider@example.com",
            message_type="initial_outreach",
        )
        
        assert isinstance(draft, EmailDraft)
        assert draft.campaign_id == "camp-123"
        assert draft.provider_id == "prov-456"
        assert draft.to_address == "provider@example.com"
        assert draft.subject == "Join Our Network"
        assert "excited" in draft.body_text.lower()
        assert draft.message_type == "initial_outreach"
        
        # EmailDraft doesn't have metadata field - just verify core fields
        assert draft.template_name is None  # LLM-generated, no template
    
    @patch("agents.communication.llm_tools.get_settings")
    @patch("agents.communication.llm_tools.encode_reply_to")
    def test_draft_uses_reply_to_encoding(self, mock_encode, mock_settings):
        """Should encode reply-to address correctly."""
        mock_settings.return_value = MagicMock(
            ses_from_address="noreply@example.com",
            ses_from_name="Team",
            ses_reply_to_domain="reply.example.com",
        )
        mock_encode.return_value = "encoded-reply@reply.example.com"
        
        llm_output = EmailGenerationOutput(
            subject="Test",
            body_text="Test body",
            tone="professional",
            includes_call_to_action=False,
            personalization_elements=[],
        )
        
        draft = create_draft_from_llm_output(
            llm_output=llm_output,
            campaign_id="test-campaign",
            provider_id="test-provider",
            provider_email="test@test.com",
            message_type="test",
        )
        
        mock_encode.assert_called_once_with(
            campaign_id="test-campaign",
            provider_id="test-provider",
            domain="reply.example.com",
        )
        assert draft.reply_to == "encoded-reply@reply.example.com"


# =============================================================================
# Feature Flag Tests
# =============================================================================

class TestIsLLMEmailEnabled:
    """Tests for LLM email feature flag."""
    
    @patch("agents.communication.llm_tools.get_llm_settings")
    def test_enabled_when_feature_is_on(self, mock_settings):
        """Should return True when email feature is enabled."""
        mock_settings_instance = MagicMock()
        mock_settings_instance.is_feature_enabled.return_value = True
        mock_settings.return_value = mock_settings_instance
        
        result = is_llm_email_enabled()
        
        assert result is True
        mock_settings_instance.is_feature_enabled.assert_called_once_with("email")
    
    @patch("agents.communication.llm_tools.get_llm_settings")
    def test_disabled_when_feature_is_off(self, mock_settings):
        """Should return False when email feature is disabled."""
        mock_settings_instance = MagicMock()
        mock_settings_instance.is_feature_enabled.return_value = False
        mock_settings.return_value = mock_settings_instance
        
        result = is_llm_email_enabled()
        
        assert result is False


# =============================================================================
# Integration-like Tests (with mocked LLM)
# =============================================================================

class TestLLMEmailGenerationFlow:
    """End-to-end flow tests with mocked LLM."""
    
    @patch("agents.communication.llm_tools.get_settings")
    @patch("agents.communication.llm_tools.encode_reply_to")
    def test_full_email_generation_flow(self, mock_encode, mock_settings):
        """Test complete flow from LLM generation to draft."""
        # Setup
        mock_settings.return_value = MagicMock(
            ses_from_address="recruit@example.com",
            ses_from_name="Recruitment",
            ses_reply_to_domain="reply.example.com",
        )
        mock_encode.return_value = "reply@reply.example.com"
        
        mock_client = MagicMock()
        mock_output = EmailGenerationOutput(
            subject="Satellite Upgrade Opportunity in Atlanta",
            body_text="Hi John,\n\nWe're reaching out about an exciting opportunity...",
            tone="friendly",
            includes_call_to_action=True,
            personalization_elements=["name", "market", "campaign"],
        )
        mock_client.invoke_structured.return_value = mock_output
        
        # Generate email with LLM
        llm_result = generate_email_with_llm(
            campaign_id="sat-upgrade-2024",
            provider_id="provider-001",
            provider_name="John Smith",
            provider_market="Atlanta",
            provider_email="john@techservices.com",
            message_type="initial_outreach",
            template_data={
                "campaign_name": "Satellite Upgrade",
                "requirements": ["bucket_truck", "spectrum_analyzer"],
            },
            client=mock_client,
        )
        
        # Convert to draft
        draft = create_draft_from_llm_output(
            llm_output=llm_result,
            campaign_id="sat-upgrade-2024",
            provider_id="provider-001",
            provider_email="john@techservices.com",
            message_type="initial_outreach",
        )
        
        # Verify complete flow
        assert llm_result.subject == "Satellite Upgrade Opportunity in Atlanta"
        assert draft.campaign_id == "sat-upgrade-2024"
        assert draft.provider_id == "provider-001"
        assert draft.to_address == "john@techservices.com"
        assert draft.subject == llm_result.subject
        assert draft.body_text == llm_result.body_text
        assert draft.template_name is None  # LLM-generated
