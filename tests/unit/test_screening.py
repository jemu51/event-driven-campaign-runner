"""
Test Screening Agent

Unit tests for response classification, keyword extraction, and document validation.
"""

from datetime import date, timedelta

import pytest

from agents.screening.models import (
    CertificationMatch,
    DocumentValidationResult,
    EquipmentMatch,
    KeywordExtractionResult,
    ResponseClassification,
    ResponseIntent,
    ScreeningDecision,
)
from agents.screening.tools import (
    CERTIFICATION_KEYWORDS,
    EQUIPMENT_KEYWORDS,
    TRAVEL_NEGATIVE_KEYWORDS,
    TRAVEL_POSITIVE_KEYWORDS,
    classify_response,
    extract_keywords,
    _normalize_text,
)


class TestNormalizeText:
    """Tests for _normalize_text helper."""

    def test_lowercase(self):
        """Text is converted to lowercase."""
        assert _normalize_text("HELLO WORLD") == "hello world"

    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        assert _normalize_text("  hello  ") == "hello"

    def test_preserves_internal_spaces(self):
        """Internal spaces are preserved."""
        assert _normalize_text("hello world") == "hello world"


class TestEquipmentKeywords:
    """Tests for EQUIPMENT_KEYWORDS configuration."""

    def test_bucket_truck_keywords(self):
        """bucket_truck has expected keywords."""
        keywords = EQUIPMENT_KEYWORDS.get("bucket_truck", [])
        assert "bucket truck" in keywords
        assert "bucket" in keywords
        assert len(keywords) > 3

    def test_spectrum_analyzer_keywords(self):
        """spectrum_analyzer has expected keywords."""
        keywords = EQUIPMENT_KEYWORDS.get("spectrum_analyzer", [])
        assert "spectrum analyzer" in keywords
        assert "spectrum" in keywords

    def test_fiber_splicer_keywords(self):
        """fiber_splicer has expected keywords."""
        keywords = EQUIPMENT_KEYWORDS.get("fiber_splicer", [])
        assert "fiber splicer" in keywords or "fusion splicer" in keywords


class TestCertificationKeywords:
    """Tests for CERTIFICATION_KEYWORDS configuration."""

    def test_comptia_network_plus(self):
        """comptia_network_plus has expected keywords."""
        keywords = CERTIFICATION_KEYWORDS.get("comptia_network_plus", [])
        assert any("network" in kw.lower() for kw in keywords)

    def test_osha_10_keywords(self):
        """osha_10 has expected keywords."""
        keywords = CERTIFICATION_KEYWORDS.get("osha_10", [])
        assert any("osha" in kw.lower() for kw in keywords)


class TestClassifyResponse:
    """Tests for classify_response function."""

    def test_positive_response_interested(self):
        """Response with positive keywords is classified as POSITIVE."""
        response = "I'm interested in this opportunity! I'd love to participate."
        result = classify_response(response)
        
        assert isinstance(result, ResponseClassification)
        assert result.intent == ResponseIntent.POSITIVE
        assert result.confidence > 0.5

    def test_negative_response_decline(self):
        """Response with negative keywords is classified as NEGATIVE."""
        response = "Thanks but no thanks. I'm not interested in this work."
        result = classify_response(response)
        
        assert result.intent == ResponseIntent.NEGATIVE
        assert result.confidence > 0.5

    def test_question_response(self):
        """Response with questions is classified as QUESTION."""
        response = "What is the pay rate? How long is the project? Can you tell me more?"
        result = classify_response(response)
        
        assert result.intent == ResponseIntent.QUESTION
        assert result.confidence > 0.5

    def test_document_only_response(self):
        """Short message with attachment is DOCUMENT_ONLY."""
        response = "Here's my insurance doc."
        result = classify_response(response, has_attachments=True)
        
        assert result.intent == ResponseIntent.DOCUMENT_ONLY or result.intent == ResponseIntent.AMBIGUOUS

    def test_ambiguous_response(self):
        """Unclear response is AMBIGUOUS."""
        response = "Ok."
        result = classify_response(response, has_attachments=False)
        
        # Short ambiguous response
        assert result.confidence <= 0.6

    def test_classification_includes_matched_keywords(self):
        """Result includes matched keywords."""
        response = "I'm interested! I'd like to participate in this project."
        result = classify_response(response)
        
        assert len(result.keywords_matched) > 0

    def test_empty_response(self):
        """Empty response is AMBIGUOUS."""
        response = ""
        result = classify_response(response)
        
        assert result.intent == ResponseIntent.AMBIGUOUS


class TestExtractKeywords:
    """Tests for extract_keywords function."""

    def test_extract_bucket_truck(self):
        """Detects bucket truck equipment."""
        response = "I have a bucket truck and a ladder."
        result = extract_keywords(response, required_equipment=["bucket_truck"])
        
        assert isinstance(result, KeywordExtractionResult)
        bucket_match = next(
            (m for m in result.equipment_matches if m.equipment_type == "bucket_truck"),
            None,
        )
        assert bucket_match is not None
        assert bucket_match.matched is True

    def test_extract_spectrum_analyzer(self):
        """Detects spectrum analyzer equipment."""
        response = "My equipment includes a spectrum analyzer for RF testing."
        result = extract_keywords(response, required_equipment=["spectrum_analyzer"])
        
        spectrum_match = next(
            (m for m in result.equipment_matches if m.equipment_type == "spectrum_analyzer"),
            None,
        )
        assert spectrum_match is not None
        assert spectrum_match.matched is True

    def test_extract_multiple_equipment(self):
        """Detects multiple equipment types."""
        response = "I have bucket truck, spectrum analyzer, and cable tester."
        result = extract_keywords(
            response,
            required_equipment=["bucket_truck", "spectrum_analyzer", "cable_tester"],
        )
        
        matched = [m.equipment_type for m in result.equipment_matches if m.matched]
        assert "bucket_truck" in matched
        assert "spectrum_analyzer" in matched
        assert "cable_tester" in matched

    def test_extract_missing_equipment(self):
        """Reports missing equipment."""
        response = "I only have a ladder."
        result = extract_keywords(
            response,
            required_equipment=["bucket_truck", "spectrum_analyzer"],
        )
        
        bucket = next(
            (m for m in result.equipment_matches if m.equipment_type == "bucket_truck"),
            None,
        )
        assert bucket is not None
        assert bucket.matched is False

    def test_extract_certifications(self):
        """Detects certifications."""
        response = "I have OSHA 10 certification and CompTIA Network+."
        result = extract_keywords(
            response,
            required_certifications=["osha_10", "comptia_network_plus"],
        )
        
        osha = next(
            (m for m in result.certification_matches if m.certification_type == "osha_10"),
            None,
        )
        assert osha is not None
        assert osha.matched is True

    def test_extract_travel_positive(self):
        """Detects positive travel confirmation."""
        response = "Yes, I can travel to other markets if needed."
        result = extract_keywords(response)
        
        assert result.travel_confirmed is True
        assert len(result.travel_keywords_matched) > 0

    def test_extract_travel_negative(self):
        """Detects negative travel confirmation."""
        response = "I cannot travel. I prefer local work only."
        result = extract_keywords(response)
        
        assert result.travel_confirmed is False
        assert len(result.travel_keywords_matched) > 0

    def test_extract_no_travel_mention(self):
        """No travel mention returns None."""
        response = "I have a bucket truck and spectrum analyzer."
        result = extract_keywords(response)
        
        assert result.travel_confirmed is None


class TestResponseClassification:
    """Tests for ResponseClassification model."""

    def test_create_classification(self):
        """Create valid ResponseClassification."""
        classification = ResponseClassification(
            intent=ResponseIntent.POSITIVE,
            confidence=0.85,
            keywords_matched=["interested", "participate"],
            has_attachment=False,
        )
        assert classification.intent == ResponseIntent.POSITIVE
        assert classification.confidence == 0.85

    def test_confidence_bounds(self):
        """Confidence must be 0-1."""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            ResponseClassification(
                intent=ResponseIntent.POSITIVE,
                confidence=1.5,  # Too high
            )


class TestEquipmentMatch:
    """Tests for EquipmentMatch model."""

    def test_matched_equipment(self):
        """Create matched equipment result."""
        match = EquipmentMatch(
            equipment_type="bucket_truck",
            matched=True,
            matched_keywords=["bucket truck", "bucket"],
            confidence=1.0,
        )
        assert match.matched is True
        assert len(match.matched_keywords) == 2

    def test_unmatched_equipment(self):
        """Create unmatched equipment result."""
        match = EquipmentMatch(
            equipment_type="bucket_truck",
            matched=False,
            matched_keywords=[],
            confidence=0.0,
        )
        assert match.matched is False


class TestKeywordExtractionResult:
    """Tests for KeywordExtractionResult model."""

    def test_full_extraction_result(self):
        """Create complete extraction result."""
        result = KeywordExtractionResult(
            equipment_matches=[
                EquipmentMatch(
                    equipment_type="bucket_truck",
                    matched=True,
                    matched_keywords=["bucket truck"],
                ),
            ],
            certification_matches=[
                CertificationMatch(
                    certification_type="osha_10",
                    matched=True,
                    matched_keywords=["osha 10"],
                ),
            ],
            travel_confirmed=True,
            travel_keywords_matched=["can travel"],
        )
        
        assert len(result.equipment_matches) == 1
        assert len(result.certification_matches) == 1
        assert result.travel_confirmed is True


class TestScreeningDecision:
    """Tests for ScreeningDecision enum."""

    def test_all_decisions_defined(self):
        """All expected decisions are defined."""
        expected = [
            "QUALIFIED", "REJECTED", "NEEDS_DOCUMENT",
            "NEEDS_CLARIFICATION", "UNDER_REVIEW", "ESCALATED",
        ]
        actual = [d.value for d in ScreeningDecision]
        for exp in expected:
            assert exp in actual, f"Missing decision: {exp}"


class TestResponseIntent:
    """Tests for ResponseIntent enum."""

    def test_all_intents_defined(self):
        """All expected intents are defined."""
        expected = ["positive", "negative", "question", "document_only", "ambiguous"]
        actual = [i.value for i in ResponseIntent]
        assert sorted(expected) == sorted(actual)


class TestTravelKeywords:
    """Tests for travel keyword lists."""

    def test_positive_travel_keywords_exist(self):
        """Positive travel keywords are defined."""
        assert len(TRAVEL_POSITIVE_KEYWORDS) > 0
        assert "can travel" in TRAVEL_POSITIVE_KEYWORDS

    def test_negative_travel_keywords_exist(self):
        """Negative travel keywords are defined."""
        assert len(TRAVEL_NEGATIVE_KEYWORDS) > 0
        assert any("cannot" in kw or "can't" in kw for kw in TRAVEL_NEGATIVE_KEYWORDS)


class TestCertificationMatch:
    """Tests for CertificationMatch model."""

    def test_matched_certification(self):
        """Create matched certification result."""
        match = CertificationMatch(
            certification_type="comptia_network_plus",
            matched=True,
            matched_keywords=["network+", "comptia network plus"],
        )
        assert match.matched is True
        assert match.certification_type == "comptia_network_plus"


class TestClassificationEdgeCases:
    """Tests for edge cases in classification."""

    def test_mixed_signals_positive_stronger(self):
        """When positive outweighs negative, classify as POSITIVE."""
        response = (
            "I'm definitely interested! I'd love to do this work. "
            "Although I have some concerns about the timeline."
        )
        result = classify_response(response)
        # Positive should dominate
        assert result.intent == ResponseIntent.POSITIVE

    def test_mixed_signals_negative_stronger(self):
        """When negative outweighs positive, classify as NEGATIVE."""
        response = (
            "I appreciate the offer but I'm not interested. "
            "I'm declining this opportunity. No thanks."
        )
        result = classify_response(response)
        assert result.intent == ResponseIntent.NEGATIVE

    def test_case_insensitive_matching(self):
        """Keywords match case-insensitively."""
        response = "I HAVE A BUCKET TRUCK AND SPECTRUM ANALYZER"
        result = extract_keywords(
            response,
            required_equipment=["bucket_truck", "spectrum_analyzer"],
        )
        
        matched = [m.equipment_type for m in result.equipment_matches if m.matched]
        assert "bucket_truck" in matched
        assert "spectrum_analyzer" in matched


class TestDocumentScenarios:
    """Tests for document-related screening scenarios."""

    def test_insurance_mentioned(self):
        """Detect when insurance is mentioned."""
        response = "I have valid insurance. Here's my certificate attached."
        result = classify_response(response, has_attachments=True)
        
        # Should recognize this as a document submission
        assert result.has_attachment is True

    def test_equipment_in_document_context(self):
        """Extract equipment from detailed response."""
        response = """
        Hello, I'm interested in the satellite upgrade project.
        
        My equipment includes:
        - A 2019 Altec bucket truck (28ft reach)
        - Anritsu spectrum analyzer
        - Various hand tools and ladders
        
        I also hold CompTIA Network+ certification.
        """
        result = extract_keywords(
            response,
            required_equipment=["bucket_truck", "spectrum_analyzer", "ladder"],
            required_certifications=["comptia_network_plus"],
        )
        
        matched_equipment = [m.equipment_type for m in result.equipment_matches if m.matched]
        matched_certs = [m.certification_type for m in result.certification_matches if m.matched]
        
        assert "bucket_truck" in matched_equipment
        assert "spectrum_analyzer" in matched_equipment
        assert "ladder" in matched_equipment
        assert "comptia_network_plus" in matched_certs
