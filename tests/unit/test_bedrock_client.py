"""
Unit Tests for Bedrock LLM Client

Tests the LLM infrastructure without making real AWS calls.
Uses mocking to test parsing, error handling, and configuration.
"""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from agents.shared.llm import (
    BedrockLLMClient,
    LLMSettings,
    EmailGenerationOutput,
    ResponseClassificationOutput,
    EquipmentExtractionOutput,
    InsuranceDocumentOutput,
    ScreeningDecisionOutput,
)
from agents.shared.llm.bedrock_client import (
    LLMInvocationError,
    LLMParsingError,
)


# --- Fixtures ---


@pytest.fixture
def mock_llm_settings():
    """LLM settings with LLM enabled."""
    return LLMSettings(
        llm_enabled=True,
        bedrock_model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        bedrock_region="us-west-2",
        llm_temperature=0.3,
        llm_max_tokens=4096,
    )


@pytest.fixture
def mock_llm_settings_disabled():
    """LLM settings with LLM disabled."""
    return LLMSettings(
        llm_enabled=False,
    )


@pytest.fixture
def mock_agent_response():
    """Factory for creating mock agent responses."""
    def _create(data: dict) -> MagicMock:
        mock = MagicMock()
        mock.__str__ = lambda self: json.dumps(data)
        return mock
    return _create


# --- Settings Tests ---


class TestLLMSettings:
    """Tests for LLMSettings configuration."""
    
    def test_default_settings(self):
        """Test default settings values."""
        settings = LLMSettings()
        
        assert settings.llm_enabled is True
        assert settings.use_llm_for_email is True
        assert settings.use_llm_for_classification is True
        assert settings.use_llm_for_screening is True
        assert settings.bedrock_model_id == "anthropic.claude-3-sonnet-20240229-v1:0"
        assert settings.llm_temperature == 0.3
    
    def test_environment_override(self, monkeypatch):
        """Test settings can be overridden via environment variables."""
        monkeypatch.setenv("RECRUITMENT_LLM_ENABLED", "false")
        monkeypatch.setenv("RECRUITMENT_BEDROCK_MODEL_ID", "anthropic.claude-3-opus")
        monkeypatch.setenv("RECRUITMENT_LLM_TEMPERATURE", "0.7")
        
        settings = LLMSettings()
        
        assert settings.llm_enabled is False
        assert settings.bedrock_model_id == "anthropic.claude-3-opus"
        assert settings.llm_temperature == 0.7
    
    def test_is_feature_enabled_global_disabled(self, mock_llm_settings_disabled):
        """Test that all features are disabled when global toggle is off."""
        assert mock_llm_settings_disabled.is_feature_enabled("email") is False
        assert mock_llm_settings_disabled.is_feature_enabled("classification") is False
        assert mock_llm_settings_disabled.is_feature_enabled("screening") is False
        assert mock_llm_settings_disabled.is_feature_enabled("document") is False
    
    def test_is_feature_enabled_specific_disabled(self):
        """Test that specific features can be disabled individually."""
        settings = LLMSettings(
            llm_enabled=True,
            use_llm_for_email=False,
            use_llm_for_classification=True,
        )
        
        assert settings.is_feature_enabled("email") is False
        assert settings.is_feature_enabled("classification") is True


# --- Schema Tests ---


class TestEmailGenerationOutput:
    """Tests for EmailGenerationOutput schema."""
    
    def test_valid_email_output(self):
        """Test creating valid email generation output."""
        output = EmailGenerationOutput(
            subject="Opportunity: Satellite Upgrade technicians needed",
            body_text="Dear Provider, We have an exciting opportunity...",
            tone="professional",
            includes_call_to_action=True,
            personalization_elements=["provider name", "market"],
        )
        
        assert output.subject == "Opportunity: Satellite Upgrade technicians needed"
        assert output.tone == "professional"
        assert output.includes_call_to_action is True
        assert len(output.personalization_elements) == 2
    
    def test_subject_max_length(self):
        """Test that subject line has max length validation."""
        with pytest.raises(ValueError):
            EmailGenerationOutput(
                subject="x" * 201,  # Exceeds 200 char limit
                body_text="Body",
                tone="formal",
                includes_call_to_action=True,
            )


class TestResponseClassificationOutput:
    """Tests for ResponseClassificationOutput schema."""
    
    def test_valid_classification(self):
        """Test creating valid response classification."""
        output = ResponseClassificationOutput(
            intent="positive",
            confidence=0.95,
            reasoning="Provider clearly expresses interest",
            key_phrases=["I'm interested", "count me in"],
            sentiment="positive",
        )
        
        assert output.intent == "positive"
        assert output.confidence == 0.95
        assert output.sentiment == "positive"
    
    def test_confidence_bounds(self):
        """Test confidence must be between 0 and 1."""
        with pytest.raises(ValueError):
            ResponseClassificationOutput(
                intent="positive",
                confidence=1.5,  # Invalid: > 1
                reasoning="Test",
                sentiment="positive",
            )
        
        with pytest.raises(ValueError):
            ResponseClassificationOutput(
                intent="positive",
                confidence=-0.1,  # Invalid: < 0
                reasoning="Test",
                sentiment="positive",
            )


class TestEquipmentExtractionOutput:
    """Tests for EquipmentExtractionOutput schema."""
    
    def test_valid_extraction(self):
        """Test creating valid equipment extraction."""
        output = EquipmentExtractionOutput(
            equipment_confirmed=["bucket_truck", "spectrum_analyzer"],
            equipment_denied=["ladder"],
            travel_willing=True,
            certifications_mentioned=["CompTIA Network+"],
            concerns_raised=[],
            confidence=0.92,
        )
        
        assert "bucket_truck" in output.equipment_confirmed
        assert output.travel_willing is True
        assert output.confidence == 0.92
    
    def test_optional_travel_willing(self):
        """Test travel_willing can be None."""
        output = EquipmentExtractionOutput(
            equipment_confirmed=[],
            confidence=0.5,
        )
        
        assert output.travel_willing is None


class TestInsuranceDocumentOutput:
    """Tests for InsuranceDocumentOutput schema."""
    
    def test_valid_insurance_document(self):
        """Test creating valid insurance document output."""
        output = InsuranceDocumentOutput(
            is_insurance_document=True,
            policy_holder="John's Electric LLC",
            coverage_amount=2000000,
            expiry_date=date(2027, 12, 31),
            policy_number="POL-123456",
            insurance_company="StateFarm",
            is_valid=True,
            validation_errors=[],
            confidence=0.95,
        )
        
        assert output.is_insurance_document is True
        assert output.coverage_amount == 2000000
        assert output.is_valid is True
    
    def test_invalid_insurance_with_errors(self):
        """Test insurance document with validation errors."""
        output = InsuranceDocumentOutput(
            is_insurance_document=True,
            coverage_amount=500000,  # Below $2M minimum
            is_valid=False,
            validation_errors=["Coverage amount below $2M minimum"],
            confidence=0.88,
        )
        
        assert output.is_valid is False
        assert len(output.validation_errors) == 1


class TestScreeningDecisionOutput:
    """Tests for ScreeningDecisionOutput schema."""
    
    def test_qualified_decision(self):
        """Test qualified screening decision."""
        output = ScreeningDecisionOutput(
            decision="QUALIFIED",
            confidence=0.97,
            reasoning="Provider meets all requirements",
            next_action="Send confirmation email",
            missing_items=[],
            questions_for_provider=[],
        )
        
        assert output.decision == "QUALIFIED"
        assert len(output.missing_items) == 0
    
    def test_needs_document_decision(self):
        """Test needs document screening decision."""
        output = ScreeningDecisionOutput(
            decision="NEEDS_DOCUMENT",
            confidence=0.85,
            reasoning="Insurance certificate not provided",
            next_action="Request insurance certificate",
            missing_items=["insurance_certificate"],
            questions_for_provider=[],
        )
        
        assert output.decision == "NEEDS_DOCUMENT"
        assert "insurance_certificate" in output.missing_items


# --- Client Tests ---


class TestBedrockLLMClient:
    """Tests for BedrockLLMClient."""
    
    def test_client_initialization(self, mock_llm_settings):
        """Test client can be initialized with settings."""
        client = BedrockLLMClient(settings=mock_llm_settings)
        
        assert client.settings == mock_llm_settings
        assert client.settings.llm_enabled is True
    
    def test_invoke_when_disabled_raises_error(self, mock_llm_settings_disabled):
        """Test that invoking with LLM disabled raises error."""
        client = BedrockLLMClient(settings=mock_llm_settings_disabled)
        
        with pytest.raises(LLMInvocationError, match="LLM is disabled"):
            client.invoke_structured(
                prompt="Test prompt",
                output_schema=EmailGenerationOutput,
            )
    
    @patch("agents.shared.llm.bedrock_client.Agent")
    @patch("agents.shared.llm.bedrock_client.BedrockModel")
    def test_invoke_structured_success(
        self,
        mock_bedrock_model,
        mock_agent_class,
        mock_llm_settings,
    ):
        """Test successful structured invocation."""
        # Set up mock response
        response_data = {
            "subject": "Test Subject",
            "body_text": "Test body content",
            "tone": "professional",
            "includes_call_to_action": True,
            "personalization_elements": ["name"],
        }
        
        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = json.dumps(response_data)
        mock_agent_class.return_value = mock_agent_instance
        
        client = BedrockLLMClient(settings=mock_llm_settings)
        
        result = client.invoke_structured(
            prompt="Generate an email",
            output_schema=EmailGenerationOutput,
            system_prompt="You are an email writer",
        )
        
        assert isinstance(result, EmailGenerationOutput)
        assert result.subject == "Test Subject"
        assert result.tone == "professional"
    
    @patch("agents.shared.llm.bedrock_client.Agent")
    @patch("agents.shared.llm.bedrock_client.BedrockModel")
    def test_invoke_structured_with_markdown_response(
        self,
        mock_bedrock_model,
        mock_agent_class,
        mock_llm_settings,
    ):
        """Test parsing response wrapped in markdown code blocks."""
        response_data = {
            "intent": "positive",
            "confidence": 0.9,
            "reasoning": "Provider interested",
            "key_phrases": ["interested"],
            "sentiment": "positive",
        }
        
        # Response wrapped in markdown
        markdown_response = f"```json\n{json.dumps(response_data)}\n```"
        
        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = markdown_response
        mock_agent_class.return_value = mock_agent_instance
        
        client = BedrockLLMClient(settings=mock_llm_settings)
        
        result = client.invoke_structured(
            prompt="Classify response",
            output_schema=ResponseClassificationOutput,
        )
        
        assert isinstance(result, ResponseClassificationOutput)
        assert result.intent == "positive"
    
    def test_parse_response_invalid_json(self, mock_llm_settings):
        """Test parsing error on invalid JSON."""
        client = BedrockLLMClient(settings=mock_llm_settings)
        
        with pytest.raises(LLMParsingError, match="Failed to parse"):
            client._parse_response(
                "This is not valid JSON",
                EmailGenerationOutput,
            )
    
    def test_parse_response_schema_mismatch(self, mock_llm_settings):
        """Test parsing error when JSON doesn't match schema."""
        client = BedrockLLMClient(settings=mock_llm_settings)
        
        # Valid JSON but wrong structure
        invalid_data = json.dumps({"wrong_field": "value"})
        
        with pytest.raises(LLMParsingError, match="does not match schema"):
            client._parse_response(invalid_data, EmailGenerationOutput)
    
    def test_build_structured_prompt(self, mock_llm_settings):
        """Test structured prompt includes schema."""
        client = BedrockLLMClient(settings=mock_llm_settings)
        
        prompt = client._build_structured_prompt(
            "Generate an email",
            EmailGenerationOutput,
        )
        
        assert "Generate an email" in prompt
        assert "subject" in prompt
        assert "body_text" in prompt
        assert "JSON" in prompt


# --- Integration-like Tests (with mocks) ---


class TestLLMClientIntegration:
    """Integration-style tests with full mock chain."""
    
    @patch("agents.shared.llm.bedrock_client.Agent")
    @patch("agents.shared.llm.bedrock_client.BedrockModel")
    def test_equipment_extraction_flow(
        self,
        mock_bedrock_model,
        mock_agent_class,
        mock_llm_settings,
    ):
        """Test complete equipment extraction flow."""
        response_data = {
            "equipment_confirmed": ["bucket_truck", "spectrum_analyzer"],
            "equipment_denied": [],
            "travel_willing": True,
            "certifications_mentioned": ["CompTIA Network+"],
            "concerns_raised": [],
            "confidence": 0.92,
        }
        
        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = json.dumps(response_data)
        mock_agent_class.return_value = mock_agent_instance
        
        client = BedrockLLMClient(settings=mock_llm_settings)
        
        result = client.invoke_structured(
            prompt="""
            Extract equipment from this response:
            "Yes, I have a bucket truck and spectrum analyzer. 
            I'm willing to travel for work. I hold CompTIA Network+ certification."
            """,
            output_schema=EquipmentExtractionOutput,
        )
        
        assert "bucket_truck" in result.equipment_confirmed
        assert "spectrum_analyzer" in result.equipment_confirmed
        assert result.travel_willing is True
        assert "CompTIA Network+" in result.certifications_mentioned
    
    @patch("agents.shared.llm.bedrock_client.Agent")
    @patch("agents.shared.llm.bedrock_client.BedrockModel")
    def test_screening_decision_flow(
        self,
        mock_bedrock_model,
        mock_agent_class,
        mock_llm_settings,
    ):
        """Test complete screening decision flow."""
        response_data = {
            "decision": "NEEDS_DOCUMENT",
            "confidence": 0.88,
            "reasoning": "Provider has equipment but missing insurance",
            "next_action": "Request insurance certificate",
            "missing_items": ["insurance_certificate"],
            "questions_for_provider": [],
        }
        
        mock_agent_instance = MagicMock()
        mock_agent_instance.return_value = json.dumps(response_data)
        mock_agent_class.return_value = mock_agent_instance
        
        client = BedrockLLMClient(settings=mock_llm_settings)
        
        result = client.invoke_structured(
            prompt="Make screening decision for provider with equipment but no insurance",
            output_schema=ScreeningDecisionOutput,
        )
        
        assert result.decision == "NEEDS_DOCUMENT"
        assert "insurance_certificate" in result.missing_items
