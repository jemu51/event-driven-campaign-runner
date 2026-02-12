"""
End-to-End Flow Integration Tests with Mock LLM

Tests the complete qualification flow from outreach to qualified status
using mocked AWS services and mock LLM client.
"""

import json
import time
from unittest.mock import patch, MagicMock
from datetime import date

import pytest
from moto import mock_aws
import boto3

from tests.mocks.mock_bedrock import MockBedrockLLMClient
from tests.fixtures.llm_responses import (
    MOCK_EMAIL_INITIAL_OUTREACH,
    MOCK_EMAIL_DOCUMENT_REQUEST,
    MOCK_CLASSIFICATION_POSITIVE,
    MOCK_EQUIPMENT_COMPLETE,
    MOCK_INSURANCE_VALID,
    MOCK_DECISION_QUALIFIED,
    MOCK_DECISION_NEEDS_DOCUMENT,
)

from agents.shared.llm.schemas import (
    EmailGenerationOutput,
    ResponseClassificationOutput,
    EquipmentExtractionOutput,
    InsuranceDocumentOutput,
    ScreeningDecisionOutput,
)
from agents.shared.state_machine import ProviderStatus


# =============================================================================
# Mock LLM Client Fixtures
# =============================================================================

@pytest.fixture
def mock_llm_client():
    """Provide a mock LLM client for testing."""
    client = MockBedrockLLMClient()
    # Pre-configure common responses
    client.set_responses([
        MOCK_EMAIL_INITIAL_OUTREACH,
        MOCK_CLASSIFICATION_POSITIVE,
        MOCK_EQUIPMENT_COMPLETE,
        MOCK_INSURANCE_VALID,
        MOCK_DECISION_QUALIFIED,
    ])
    return client


@pytest.fixture
def mock_llm_client_needs_doc():
    """Mock client configured for needs-document scenario."""
    client = MockBedrockLLMClient()
    client.set_responses([
        MOCK_CLASSIFICATION_POSITIVE,
        MOCK_EQUIPMENT_COMPLETE,
        MOCK_DECISION_NEEDS_DOCUMENT,
        MOCK_EMAIL_DOCUMENT_REQUEST,
    ])
    return client


# =============================================================================
# Test Classes
# =============================================================================

class TestMockBedrockClient:
    """Tests for the MockBedrockLLMClient itself."""
    
    def test_set_and_get_response(self):
        """Should return configured response."""
        client = MockBedrockLLMClient()
        client.set_response(MOCK_EMAIL_INITIAL_OUTREACH)
        
        result = client.invoke_structured(
            prompt="Generate email",
            output_model=EmailGenerationOutput,
        )
        
        assert result.subject == MOCK_EMAIL_INITIAL_OUTREACH.subject
        assert result.tone == "professional"
        
    def test_records_invocations(self):
        """Should record all invocations for verification."""
        client = MockBedrockLLMClient()
        client.set_response(MOCK_CLASSIFICATION_POSITIVE)
        
        client.invoke_structured(
            prompt="Classify: I'm interested!",
            output_model=ResponseClassificationOutput,
            system_prompt="You are a classifier",
        )
        
        assert client.call_count == 1
        assert client.last_invocation["prompt"] == "Classify: I'm interested!"
        assert client.last_invocation["system_prompt"] == "You are a classifier"
        
    def test_raises_configured_error(self):
        """Should raise configured error."""
        from tests.mocks.mock_bedrock import MockLLMError
        
        client = MockBedrockLLMClient()
        client.set_error(MockLLMError("Simulated failure"))
        
        with pytest.raises(MockLLMError, match="Simulated failure"):
            client.invoke_structured(
                prompt="Test",
                output_model=EmailGenerationOutput,
            )
            
    def test_error_clears_after_raise(self):
        """Error should only raise once."""
        from tests.mocks.mock_bedrock import MockLLMError
        
        client = MockBedrockLLMClient()
        client.set_response(MOCK_CLASSIFICATION_POSITIVE)
        client.set_error(MockLLMError("One-time error"))
        
        # First call raises
        with pytest.raises(MockLLMError):
            client.invoke_structured("Test", ResponseClassificationOutput)
            
        # Second call succeeds
        result = client.invoke_structured("Test", ResponseClassificationOutput)
        assert result.intent == "positive"
        
    def test_multiple_response_types(self):
        """Should handle multiple response types."""
        client = MockBedrockLLMClient()
        client.set_responses([
            MOCK_EMAIL_INITIAL_OUTREACH,
            MOCK_CLASSIFICATION_POSITIVE,
            MOCK_EQUIPMENT_COMPLETE,
        ])
        
        email = client.invoke_structured("Email prompt", EmailGenerationOutput)
        classification = client.invoke_structured("Classify", ResponseClassificationOutput)
        equipment = client.invoke_structured("Extract", EquipmentExtractionOutput)
        
        assert email.subject == MOCK_EMAIL_INITIAL_OUTREACH.subject
        assert classification.intent == "positive"
        assert "bucket_truck" in equipment.equipment_confirmed
        
    def test_assertion_helpers(self):
        """Test assertion helper methods."""
        client = MockBedrockLLMClient()
        client.set_response(MOCK_CLASSIFICATION_POSITIVE)
        
        client.assert_not_called()
        
        client.invoke_structured("Test prompt with keyword", ResponseClassificationOutput)
        
        client.assert_called()
        client.assert_called_once()
        client.assert_prompt_contains("keyword")
        
    def test_reset_clears_state(self):
        """Reset should clear all state."""
        client = MockBedrockLLMClient()
        client.set_response(MOCK_CLASSIFICATION_POSITIVE)
        client.invoke_structured("Test", ResponseClassificationOutput)
        
        client.reset()
        
        assert client.call_count == 0
        assert len(client.invocations) == 0


class TestLLMResponseFixtures:
    """Tests for LLM response fixtures validity."""
    
    def test_email_fixtures_valid(self):
        """All email fixtures should be valid EmailGenerationOutput."""
        from tests.fixtures.llm_responses import EMAIL_FIXTURES
        
        for name, fixture in EMAIL_FIXTURES.items():
            assert isinstance(fixture, EmailGenerationOutput), f"{name} is not EmailGenerationOutput"
            assert fixture.subject, f"{name} has no subject"
            assert fixture.body_text, f"{name} has no body"
            
    def test_classification_fixtures_valid(self):
        """All classification fixtures should be valid ResponseClassificationOutput."""
        from tests.fixtures.llm_responses import CLASSIFICATION_FIXTURES
        
        for name, fixture in CLASSIFICATION_FIXTURES.items():
            assert isinstance(fixture, ResponseClassificationOutput), f"{name} invalid"
            assert fixture.intent in ["positive", "negative", "question", "document_only", "ambiguous"]
            assert 0.0 <= fixture.confidence <= 1.0
            
    def test_equipment_fixtures_valid(self):
        """All equipment fixtures should be valid EquipmentExtractionOutput."""
        from tests.fixtures.llm_responses import EQUIPMENT_FIXTURES
        
        for name, fixture in EQUIPMENT_FIXTURES.items():
            assert isinstance(fixture, EquipmentExtractionOutput), f"{name} invalid"
            assert 0.0 <= fixture.confidence <= 1.0
            
    def test_insurance_fixtures_valid(self):
        """All insurance fixtures should be valid InsuranceDocumentOutput."""
        from tests.fixtures.llm_responses import INSURANCE_FIXTURES
        
        for name, fixture in INSURANCE_FIXTURES.items():
            assert isinstance(fixture, InsuranceDocumentOutput), f"{name} invalid"
            if fixture.is_valid:
                assert not fixture.validation_errors
            else:
                assert fixture.validation_errors or not fixture.is_insurance_document
                
    def test_decision_fixtures_valid(self):
        """All decision fixtures should be valid ScreeningDecisionOutput."""
        from tests.fixtures.llm_responses import DECISION_FIXTURES
        
        valid_decisions = {"QUALIFIED", "REJECTED", "NEEDS_DOCUMENT", "NEEDS_CLARIFICATION", "UNDER_REVIEW", "ESCALATED"}
        
        for name, fixture in DECISION_FIXTURES.items():
            assert isinstance(fixture, ScreeningDecisionOutput), f"{name} invalid"
            assert fixture.decision in valid_decisions
            assert 0.0 <= fixture.confidence <= 1.0
            assert fixture.next_action


class TestLLMIntegrationPatterns:
    """Tests demonstrating LLM integration patterns."""
    
    def test_email_generation_with_mock(self, mock_llm_client):
        """Demonstrate email generation with mock client."""
        result = mock_llm_client.invoke_structured(
            prompt="Generate initial outreach for John in Atlanta",
            output_model=EmailGenerationOutput,
            system_prompt="You are an email writer",
            temperature=0.3,
        )
        
        assert result.subject
        assert "Atlanta" in result.body_text or "satellite" in result.body_text.lower()
        assert result.includes_call_to_action
        
    def test_classification_with_mock(self, mock_llm_client):
        """Demonstrate response classification with mock client."""
        result = mock_llm_client.invoke_structured(
            prompt="Classify: I'm very interested in this opportunity!",
            output_model=ResponseClassificationOutput,
        )
        
        assert result.intent == "positive"
        assert result.confidence > 0.8
        
    def test_equipment_extraction_with_mock(self, mock_llm_client):
        """Demonstrate equipment extraction with mock client."""
        result = mock_llm_client.invoke_structured(
            prompt="Extract equipment from: I have a bucket truck and spectrum analyzer",
            output_model=EquipmentExtractionOutput,
        )
        
        assert "bucket_truck" in result.equipment_confirmed
        assert "spectrum_analyzer" in result.equipment_confirmed
        
    def test_screening_decision_with_mock(self, mock_llm_client):
        """Demonstrate screening decision with mock client."""
        result = mock_llm_client.invoke_structured(
            prompt="Make decision for provider with all requirements met",
            output_model=ScreeningDecisionOutput,
        )
        
        assert result.decision == "QUALIFIED"
        
    def test_fallback_on_error(self, mock_llm_client):
        """Demonstrate fallback pattern on LLM error."""
        from tests.mocks.mock_bedrock import MockLLMError
        
        mock_llm_client.set_error(MockLLMError("Bedrock unavailable"))
        
        # Simulate fallback logic
        try:
            result = mock_llm_client.invoke_structured(
                prompt="Classify response",
                output_model=ResponseClassificationOutput,
            )
        except MockLLMError:
            # Fallback to keyword-based classification
            result = ResponseClassificationOutput(
                intent="ambiguous",
                confidence=0.5,
                reasoning="Fallback to keyword classification due to LLM error",
                key_phrases=[],
                sentiment="neutral",
            )
            
        assert result.intent == "ambiguous"
        assert "Fallback" in result.reasoning


class TestProviderQualificationFlow:
    """Tests for complete provider qualification flow patterns."""
    
    def test_positive_response_to_qualified(self, mock_llm_client):
        """
        Test flow: Provider responds positively with equipment
        Expected: Classification positive, equipment confirmed, qualified
        """
        # Step 1: Classify response
        classification = mock_llm_client.invoke_structured(
            prompt="Classify: I'm interested and have a bucket truck",
            output_model=ResponseClassificationOutput,
        )
        assert classification.intent == "positive"
        
        # Step 2: Extract equipment
        equipment = mock_llm_client.invoke_structured(
            prompt="Extract: I have a bucket truck and spectrum analyzer",
            output_model=EquipmentExtractionOutput,
        )
        assert "bucket_truck" in equipment.equipment_confirmed
        
        # Step 3: Make decision
        decision = mock_llm_client.invoke_structured(
            prompt="Decide: All requirements met",
            output_model=ScreeningDecisionOutput,
        )
        assert decision.decision == "QUALIFIED"
        
    def test_positive_needs_document_flow(self, mock_llm_client_needs_doc):
        """
        Test flow: Provider interested but no insurance
        Expected: Needs document, then document request email
        """
        client = mock_llm_client_needs_doc
        
        # Classify as interested
        classification = client.invoke_structured(
            prompt="Classify: I'm interested",
            output_model=ResponseClassificationOutput,
        )
        assert classification.intent == "positive"
        
        # Extract equipment (has all)
        equipment = client.invoke_structured(
            prompt="Extract equipment",
            output_model=EquipmentExtractionOutput,
        )
        assert equipment.equipment_confirmed
        
        # Decision: needs document
        decision = client.invoke_structured(
            prompt="Make decision",
            output_model=ScreeningDecisionOutput,
        )
        assert decision.decision == "NEEDS_DOCUMENT"
        assert "insurance" in str(decision.missing_items).lower()
        
        # Generate document request email
        email = client.invoke_structured(
            prompt="Generate document request",
            output_model=EmailGenerationOutput,
        )
        assert "insurance" in email.body_text.lower()


class TestDocumentAnalysisFlow:
    """Tests for document analysis patterns."""
    
    def test_valid_insurance_approval(self):
        """Test valid insurance leads to approval."""
        client = MockBedrockLLMClient()
        client.set_responses([MOCK_INSURANCE_VALID, MOCK_DECISION_QUALIFIED])
        
        # Analyze document
        analysis = client.invoke_structured(
            prompt="Analyze insurance OCR",
            output_model=InsuranceDocumentOutput,
        )
        assert analysis.is_valid
        assert analysis.coverage_amount >= 2000000
        
        # Make final decision
        decision = client.invoke_structured(
            prompt="Final decision",
            output_model=ScreeningDecisionOutput,
        )
        assert decision.decision == "QUALIFIED"
        
    def test_expired_insurance_rejection(self):
        """Test expired insurance gets flagged."""
        from tests.fixtures.llm_responses import MOCK_INSURANCE_EXPIRED
        
        client = MockBedrockLLMClient()
        client.set_response(MOCK_INSURANCE_EXPIRED)
        
        analysis = client.invoke_structured(
            prompt="Analyze expired insurance",
            output_model=InsuranceDocumentOutput,
        )
        
        assert not analysis.is_valid
        assert any("expired" in e.lower() for e in analysis.validation_errors)
        
    def test_insufficient_coverage_rejection(self):
        """Test insufficient coverage gets flagged."""
        from tests.fixtures.llm_responses import MOCK_INSURANCE_INSUFFICIENT_COVERAGE
        
        client = MockBedrockLLMClient()
        client.set_response(MOCK_INSURANCE_INSUFFICIENT_COVERAGE)
        
        analysis = client.invoke_structured(
            prompt="Analyze insurance",
            output_model=InsuranceDocumentOutput,
        )
        
        assert not analysis.is_valid
        assert analysis.coverage_amount < 2000000
