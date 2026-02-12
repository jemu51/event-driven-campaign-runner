"""
Tests for Screening Agent LLM Integration

Tests for:
- LLM prompts construction
- LLM classification, extraction, and analysis tools
- Feature flag checks
- Fallback behavior
"""

from unittest.mock import MagicMock, patch
import pytest

from agents.screening.llm_prompts import (
    CLASSIFICATION_SYSTEM_PROMPT,
    EQUIPMENT_EXTRACTION_SYSTEM_PROMPT,
    DOCUMENT_ANALYSIS_SYSTEM_PROMPT,
    SCREENING_DECISION_SYSTEM_PROMPT,
    build_classification_prompt,
    build_equipment_extraction_prompt,
    build_document_analysis_prompt,
    build_screening_decision_prompt,
)
from agents.screening.llm_tools import (
    is_llm_screening_enabled,
    load_equipment_keywords,
    load_certification_keywords,
    get_campaign_type,
    classify_response_with_llm,
    extract_equipment_with_llm,
    analyze_document_with_llm,
    make_screening_decision_with_llm,
    get_conversation_context_for_screening,
)
from agents.shared.llm import (
    ResponseClassificationOutput,
    EquipmentExtractionOutput,
    InsuranceDocumentOutput,
    ScreeningDecisionOutput,
)


# =============================================================================
# System Prompt Tests
# =============================================================================

class TestSystemPrompts:
    """Tests for system prompts."""
    
    def test_classification_prompt_exists(self):
        """Classification system prompt should be defined."""
        assert CLASSIFICATION_SYSTEM_PROMPT is not None
        assert len(CLASSIFICATION_SYSTEM_PROMPT) > 100
        assert "positive" in CLASSIFICATION_SYSTEM_PROMPT.lower()
        assert "negative" in CLASSIFICATION_SYSTEM_PROMPT.lower()
    
    def test_equipment_extraction_prompt_exists(self):
        """Equipment extraction system prompt should be defined."""
        assert EQUIPMENT_EXTRACTION_SYSTEM_PROMPT is not None
        assert len(EQUIPMENT_EXTRACTION_SYSTEM_PROMPT) > 100
    
    def test_document_analysis_prompt_exists(self):
        """Document analysis system prompt should be defined."""
        assert DOCUMENT_ANALYSIS_SYSTEM_PROMPT is not None
        assert len(DOCUMENT_ANALYSIS_SYSTEM_PROMPT) > 100
    
    def test_screening_decision_prompt_exists(self):
        """Screening decision system prompt should be defined."""
        assert SCREENING_DECISION_SYSTEM_PROMPT is not None
        assert len(SCREENING_DECISION_SYSTEM_PROMPT) > 100
        assert "qualified" in SCREENING_DECISION_SYSTEM_PROMPT.lower()


# =============================================================================
# Prompt Builder Tests
# =============================================================================

class TestBuildClassificationPrompt:
    """Tests for classification prompt builder."""
    
    def test_build_classification_prompt(self):
        """Should build classification prompt with all context."""
        prompt = build_classification_prompt(
            response_body="I'm interested in this opportunity. I have a bucket truck.",
            has_attachments=True,
            campaign_type="satellite_upgrade",
            previous_status="WAITING_RESPONSE",
            conversation_history="Previous: Initial outreach sent",
        )
        
        assert "interested" in prompt.lower()
        assert "bucket truck" in prompt.lower()
        assert "satellite_upgrade" in prompt
        assert "WAITING_RESPONSE" in prompt
        assert "attachments" in prompt.lower()
    
    def test_build_classification_prompt_no_attachments(self):
        """Should note when no attachments present."""
        prompt = build_classification_prompt(
            response_body="Test response",
            has_attachments=False,
            campaign_type="general_installation",
            previous_status="INVITED",
            conversation_history="[No previous conversation]",
        )
        
        assert "no attachments" in prompt.lower()


class TestBuildEquipmentExtractionPrompt:
    """Tests for equipment extraction prompt builder."""
    
    def test_build_equipment_extraction_prompt(self):
        """Should build prompt with equipment keywords."""
        prompt = build_equipment_extraction_prompt(
            response_body="I have a bucket truck and spectrum analyzer.",
            required_equipment=["bucket_truck", "spectrum_analyzer"],
            equipment_keywords={
                "bucket_truck": ["bucket truck", "boom truck"],
                "spectrum_analyzer": ["spectrum analyzer", "signal analyzer"],
            },
        )
        
        assert "bucket_truck" in prompt
        assert "spectrum_analyzer" in prompt
        assert "boom truck" in prompt
    
    def test_build_equipment_extraction_with_certifications(self):
        """Should include certifications when provided."""
        prompt = build_equipment_extraction_prompt(
            response_body="Test response",
            required_equipment=["bucket_truck"],
            equipment_keywords={"bucket_truck": ["bucket truck"]},
            required_certifications=["CompTIA Network+", "OSHA 10"],
        )
        
        assert "CompTIA Network+" in prompt
        assert "OSHA 10" in prompt


class TestBuildDocumentAnalysisPrompt:
    """Tests for document analysis prompt builder."""
    
    def test_build_document_analysis_prompt(self):
        """Should build prompt for document analysis."""
        prompt = build_document_analysis_prompt(
            document_type="insurance_certificate",
            ocr_text="Policy Number: ABC123\nCoverage: $2,000,000\nExpires: 12/31/2027",
            required_fields=["policy_number", "coverage_amount", "expiry_date"],
            validation_rules={"coverage_amount": "Must be at least $2,000,000"},
        )
        
        assert "insurance_certificate" in prompt
        assert "Policy Number: ABC123" in prompt
        assert "coverage_amount" in prompt
        assert "$2,000,000" in prompt


class TestBuildScreeningDecisionPrompt:
    """Tests for screening decision prompt builder."""
    
    def test_build_screening_decision_prompt(self):
        """Should build comprehensive decision prompt."""
        prompt = build_screening_decision_prompt(
            campaign_requirements={"equipment": ["bucket_truck"], "travel": True},
            equipment_confirmed=["bucket_truck"],
            equipment_missing=[],
            travel_confirmed=True,
            documents_validated=["insurance_certificate"],
            documents_pending=[],
            response_classification="positive",
            conversation_summary="Provider expressed interest on Day 1...",
        )
        
        assert "bucket_truck" in prompt
        assert "bucket_truck" in prompt  # From confirmed list
        assert "Yes" in prompt  # Travel confirmed
        assert "insurance_certificate" in prompt


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestHelperFunctions:
    """Tests for helper functions."""
    
    def test_load_equipment_keywords(self):
        """Should load equipment keywords dictionary."""
        keywords = load_equipment_keywords()
        
        assert isinstance(keywords, dict)
        assert "bucket_truck" in keywords
        assert "spectrum_analyzer" in keywords
        assert isinstance(keywords["bucket_truck"], list)
        assert "bucket truck" in keywords["bucket_truck"]
    
    def test_load_certification_keywords(self):
        """Should load certification types list."""
        certs = load_certification_keywords()
        
        assert isinstance(certs, list)
        assert "CompTIA Network+" in certs
        assert "OSHA 10" in certs
    
    def test_get_campaign_type_satellite(self):
        """Should detect satellite campaign type."""
        result = get_campaign_type("satellite-upgrade-2026-q1")
        assert result == "satellite_upgrade"
    
    def test_get_campaign_type_fiber(self):
        """Should detect fiber campaign type."""
        result = get_campaign_type("fiber-installation-atlanta")
        assert result == "fiber_installation"
    
    def test_get_campaign_type_default(self):
        """Should default to general_installation."""
        result = get_campaign_type("random-campaign-123")
        assert result == "general_installation"


class TestIsLLMScreeningEnabled:
    """Tests for LLM screening feature flag."""
    
    @patch("agents.screening.llm_tools.get_llm_settings")
    def test_enabled_when_feature_on(self, mock_settings):
        """Should return True when screening feature enabled."""
        mock_settings_instance = MagicMock()
        mock_settings_instance.is_feature_enabled.return_value = True
        mock_settings.return_value = mock_settings_instance
        
        result = is_llm_screening_enabled()
        
        assert result is True
        mock_settings_instance.is_feature_enabled.assert_called_once_with("screening")
    
    @patch("agents.screening.llm_tools.get_llm_settings")
    def test_disabled_when_feature_off(self, mock_settings):
        """Should return False when screening feature disabled."""
        mock_settings_instance = MagicMock()
        mock_settings_instance.is_feature_enabled.return_value = False
        mock_settings.return_value = mock_settings_instance
        
        result = is_llm_screening_enabled()
        
        assert result is False


# =============================================================================
# LLM Tool Tests
# =============================================================================

class TestClassifyResponseWithLLM:
    """Tests for LLM response classification."""
    
    def test_classify_response_calls_llm(self):
        """Should call LLM with correct parameters."""
        mock_client = MagicMock()
        mock_output = ResponseClassificationOutput(
            intent="positive",
            confidence=0.95,
            reasoning="Provider expresses clear interest",
            key_phrases=["interested", "sounds great"],
            sentiment="positive",
        )
        mock_client.invoke_structured.return_value = mock_output
        
        result = classify_response_with_llm(
            response_body="I'm interested! This sounds great.",
            has_attachments=False,
            campaign_type="satellite_upgrade",
            previous_status="WAITING_RESPONSE",
            conversation_history="[No previous]",
            client=mock_client,
        )
        
        mock_client.invoke_structured.assert_called_once()
        assert result.intent == "positive"
        assert result.confidence == 0.95


class TestExtractEquipmentWithLLM:
    """Tests for LLM equipment extraction."""
    
    def test_extract_equipment_calls_llm(self):
        """Should call LLM with correct parameters."""
        mock_client = MagicMock()
        mock_output = EquipmentExtractionOutput(
            equipment_confirmed=["bucket_truck"],
            equipment_denied=["spectrum_analyzer"],
            travel_willing=True,
            certifications_mentioned=["OSHA 10"],
            concerns_raised=[],
            confidence=0.9,
        )
        mock_client.invoke_structured.return_value = mock_output
        
        result = extract_equipment_with_llm(
            response_body="I have a bucket truck but no spectrum analyzer. I can travel.",
            required_equipment=["bucket_truck", "spectrum_analyzer"],
            client=mock_client,
        )
        
        mock_client.invoke_structured.assert_called_once()
        assert "bucket_truck" in result.equipment_confirmed
        assert "spectrum_analyzer" in result.equipment_denied
        assert result.travel_willing is True


class TestAnalyzeDocumentWithLLM:
    """Tests for LLM document analysis."""
    
    def test_analyze_document_calls_llm(self):
        """Should call LLM for document analysis."""
        from datetime import date
        mock_client = MagicMock()
        mock_output = InsuranceDocumentOutput(
            is_insurance_document=True,
            is_valid=True,
            policy_number="POL-12345",
            policy_holder="John Smith",
            insurance_company="Safe Insurance Co",
            coverage_amount=2500000,
            expiry_date=date(2027, 12, 31),
            confidence=0.92,
            validation_errors=[],
        )
        mock_client.invoke_structured.return_value = mock_output
        
        result = analyze_document_with_llm(
            document_type="insurance_certificate",
            ocr_text="Policy: POL-12345\nCoverage: $2,500,000\nExpires: 12/31/2027",
            client=mock_client,
        )
        
        mock_client.invoke_structured.assert_called_once()
        assert result.is_valid is True
        assert result.coverage_amount == 2500000


class TestMakeScreeningDecisionWithLLM:
    """Tests for LLM screening decision."""
    
    def test_make_decision_calls_llm(self):
        """Should call LLM for screening decision."""
        mock_client = MagicMock()
        mock_output = ScreeningDecisionOutput(
            decision="QUALIFIED",
            confidence=0.88,
            reasoning="Provider meets all requirements: equipment, travel, documents",
            next_action="Schedule onboarding",
            missing_items=[],
            questions_for_provider=[],
        )
        mock_client.invoke_structured.return_value = mock_output
        
        result = make_screening_decision_with_llm(
            campaign_requirements={"equipment": ["bucket_truck"], "travel": True},
            equipment_confirmed=["bucket_truck"],
            equipment_missing=[],
            travel_confirmed=True,
            documents_validated=["insurance_certificate"],
            documents_pending=[],
            response_classification="positive",
            conversation_history="..."
            ,
            client=mock_client,
        )
        
        mock_client.invoke_structured.assert_called_once()
        assert result.decision == "QUALIFIED"
        assert result.confidence == 0.88


# =============================================================================
# Conversation Context Tests
# =============================================================================

class TestGetConversationContext:
    """Tests for conversation context loading."""
    
    @patch("agents.screening.llm_tools.load_thread_history")
    @patch("agents.screening.llm_tools.create_thread_id")
    @patch("agents.screening.llm_tools.format_thread_for_context")
    def test_loads_and_formats_history(
        self, mock_format, mock_create_id, mock_load
    ):
        """Should load and format conversation history."""
        mock_create_id.return_value = "thread-123"
        mock_load.return_value = [MagicMock(), MagicMock()]
        mock_format.return_value = "Formatted conversation..."
        
        result = get_conversation_context_for_screening(
            campaign_id="camp-123",
            provider_id="prov-456",
            market="Atlanta",
        )
        
        mock_create_id.assert_called_once_with("camp-123", "Atlanta", "prov-456")
        mock_load.assert_called_once()
        mock_format.assert_called_once()
        assert result == "Formatted conversation..."
    
    @patch("agents.screening.llm_tools.load_thread_history")
    @patch("agents.screening.llm_tools.create_thread_id")
    def test_returns_no_conversation_when_empty(self, mock_create_id, mock_load):
        """Should return placeholder when no history."""
        mock_create_id.return_value = "thread-123"
        mock_load.return_value = []
        
        result = get_conversation_context_for_screening(
            campaign_id="camp-123",
            provider_id="prov-456",
            market="Atlanta",
        )
        
        assert "[No previous conversation]" in result
    
    @patch("agents.screening.llm_tools.create_thread_id")
    def test_handles_load_failure_gracefully(self, mock_create_id):
        """Should handle errors and return unavailable message."""
        mock_create_id.side_effect = Exception("Connection failed")
        
        result = get_conversation_context_for_screening(
            campaign_id="camp-123",
            provider_id="prov-456",
            market="Atlanta",
        )
        
        assert "unavailable" in result.lower()
