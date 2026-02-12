"""
Unit tests for TextractCompletion Lambda handler.

Tests cover:
- Document processor: document_processor.py
- Handler utilities: handler.py
"""

import pytest


# ============================================================================
# Document Processor Tests
# ============================================================================

class TestDocumentTypeClassification:
    """Tests for classify_document_type function."""
    
    def test_classify_insurance_certificate(self):
        """Test classification of insurance certificate."""
        from lambdas.textract_completion.document_processor import classify_document_type
        
        ocr_text = """
        CERTIFICATE OF LIABILITY INSURANCE
        Policy Number: GL-12345-2024
        Named Insured: ABC Construction LLC
        General Aggregate: $2,000,000
        Each Occurrence: $1,000,000
        Policy Expiration: 12/31/2024
        """
        
        doc_type, confidence = classify_document_type(ocr_text)
        
        assert doc_type == "insurance_certificate"
        assert confidence >= 0.6  # Should have reasonable confidence
    
    def test_classify_license(self):
        """Test classification of contractor license."""
        from lambdas.textract_completion.document_processor import classify_document_type
        
        ocr_text = """
        CONTRACTOR LICENSE
        License Number: C-987654
        Issued by: State Licensing Board
        Type: General Contractor
        Valid Until: 06/30/2025
        """
        
        doc_type, confidence = classify_document_type(ocr_text)
        
        assert doc_type == "license"
        assert confidence >= 0.5
    
    def test_classify_certification(self):
        """Test classification of professional certification."""
        from lambdas.textract_completion.document_processor import classify_document_type
        
        ocr_text = """
        CompTIA Network+ Certification
        Awarded to: John Smith
        Certification ID: COMP001234567
        Issue Date: 01/15/2023
        Expiration: 01/15/2026
        """
        
        doc_type, confidence = classify_document_type(ocr_text)
        
        assert doc_type == "certification"
        assert confidence >= 0.5
    
    def test_classify_w9(self):
        """Test classification of W-9 form."""
        from lambdas.textract_completion.document_processor import classify_document_type
        
        ocr_text = """
        Form W-9
        Request for Taxpayer Identification Number
        Name (as shown on your income tax return): ABC Corp
        Employer Identification Number: 12-3456789
        """
        
        doc_type, confidence = classify_document_type(ocr_text)
        
        assert doc_type == "w9"
        assert confidence >= 0.5
    
    def test_classify_unknown_document(self):
        """Test classification of unrecognized document."""
        from lambdas.textract_completion.document_processor import classify_document_type
        
        ocr_text = "Random text that doesn't match any document type patterns"
        
        doc_type, confidence = classify_document_type(ocr_text)
        
        assert doc_type == "other"
        assert confidence < 0.5


class TestDocumentExtractionResult:
    """Tests for DocumentExtractionResult dataclass."""
    
    def test_extraction_result_to_event_payload(self):
        """Test conversion to event payload format."""
        from lambdas.textract_completion.document_processor import DocumentExtractionResult
        
        result = DocumentExtractionResult(
            document_type="insurance_certificate",
            ocr_text="Certificate of Insurance...",
            extracted_fields={
                "expiry_date": "12/31/2024",
                "coverage_amount": "2000000",
            },
            confidence_scores={
                "expiry_date": 0.95,
                "coverage_amount": 0.88,
            },
            classification_confidence=0.92,
        )
        
        payload = result.to_event_payload()
        
        assert "ocr_text" in payload
        assert "extracted_fields" in payload
        assert "confidence_scores" in payload
        assert payload["extracted_fields"]["expiry_date"] == "12/31/2024"
    
    def test_extraction_result_with_errors(self):
        """Test extraction result with errors."""
        from lambdas.textract_completion.document_processor import DocumentExtractionResult
        
        result = DocumentExtractionResult(
            document_type="other",
            ocr_text="Corrupted text...",
            extraction_errors=["Failed to extract expiry_date", "Unknown format"],
        )
        
        assert len(result.extraction_errors) == 2


class TestExtractedField:
    """Tests for ExtractedField dataclass."""
    
    def test_extracted_field_creation(self):
        """Test ExtractedField creation."""
        from lambdas.textract_completion.document_processor import ExtractedField
        
        field = ExtractedField(
            name="expiry_date",
            value="2024-12-31",
            raw_value="December 31, 2024",
            confidence=0.95,
            pattern_matched=r"expir.*date.*(\d+)",
        )
        
        assert field.name == "expiry_date"
        assert field.value == "2024-12-31"
        assert field.confidence == 0.95
    
    def test_extracted_field_frozen(self):
        """Test ExtractedField is immutable."""
        from lambdas.textract_completion.document_processor import ExtractedField
        
        field = ExtractedField(name="test", value="value")
        
        with pytest.raises(Exception):
            field.name = "changed"


# ============================================================================
# Handler Utilities Tests
# ============================================================================

class TestExtractIdsFromS3Path:
    """Tests for _extract_ids_from_s3_path function."""
    
    def test_extract_ids_from_valid_path(self):
        """Test extracting IDs from valid S3 path."""
        from lambdas.textract_completion.handler import _extract_ids_from_s3_path
        
        s3_path = "s3://bucket/documents/camp-001/prov-001/insurance.pdf"
        campaign_id, provider_id = _extract_ids_from_s3_path(s3_path)
        
        assert campaign_id == "camp-001"
        assert provider_id == "prov-001"
    
    def test_extract_ids_uuid_format(self):
        """Test extracting UUID-formatted IDs."""
        from lambdas.textract_completion.handler import _extract_ids_from_s3_path
        
        s3_path = "s3://bucket/documents/550e8400-e29b-41d4-a716/660e8500-f30c/doc.pdf"
        campaign_id, provider_id = _extract_ids_from_s3_path(s3_path)
        
        assert campaign_id == "550e8400-e29b-41d4-a716"
        assert provider_id == "660e8500-f30c"
    
    def test_extract_ids_invalid_path_returns_none(self):
        """Test that invalid paths return None."""
        from lambdas.textract_completion.handler import _extract_ids_from_s3_path
        
        # No documents/ prefix
        campaign_id, provider_id = _extract_ids_from_s3_path(
            "s3://bucket/other/path/file.pdf"
        )
        assert campaign_id is None
        assert provider_id is None


class TestParseTextractNotification:
    """Tests for _parse_sns_notification function."""
    
    def test_parse_sns_records_format(self):
        """Test parsing SNS Lambda trigger format."""
        from lambdas.textract_completion.handler import _parse_sns_notification
        import json
        
        textract_data = {"JobId": "job-123", "Status": "SUCCEEDED"}
        event = {
            "Records": [{
                "EventSource": "aws:sns",
                "Sns": {
                    "Message": json.dumps(textract_data)
                }
            }]
        }
        
        result = _parse_sns_notification(event)
        
        assert result["JobId"] == "job-123"
        assert result["Status"] == "SUCCEEDED"
    
    def test_parse_direct_message_format(self):
        """Test parsing direct SNS message format."""
        from lambdas.textract_completion.handler import _parse_sns_notification
        import json
        
        textract_data = {"JobId": "job-456", "Status": "SUCCEEDED"}
        event = {"Message": json.dumps(textract_data)}
        
        result = _parse_sns_notification(event)
        
        assert result["JobId"] == "job-456"
    
    def test_parse_direct_textract_format(self):
        """Test parsing direct Textract notification format."""
        from lambdas.textract_completion.handler import _parse_sns_notification
        
        event = {"JobId": "job-789", "Status": "SUCCEEDED"}
        
        result = _parse_sns_notification(event)
        
        assert result["JobId"] == "job-789"
    
    def test_parse_invalid_event_raises(self):
        """Test that invalid events raise ValueError."""
        from lambdas.textract_completion.handler import _parse_sns_notification
        
        with pytest.raises(ValueError, match="Unable to parse"):
            _parse_sns_notification({"Invalid": "format"})
    
    def test_parse_empty_records_raises(self):
        """Test that empty Records raises ValueError."""
        from lambdas.textract_completion.handler import _parse_sns_notification
        
        with pytest.raises(ValueError, match="Empty Records"):
            _parse_sns_notification({"Records": []})


# ============================================================================
# Integration Tests
# ============================================================================

class TestDocumentProcessorIntegration:
    """Integration tests for document processing."""
    
    def test_insurance_high_confidence_classification(self):
        """Test that well-formatted insurance doc gets high confidence."""
        from lambdas.textract_completion.document_processor import classify_document_type
        
        # Very explicit insurance certificate text
        ocr_text = """
        CERTIFICATE OF LIABILITY INSURANCE
        
        This certificate is issued as a matter of information only.
        
        Policy Number: GL-2024-12345
        Named Insured: Premium Contractors LLC
        
        GENERAL LIABILITY INSURANCE
        
        General Aggregate: $2,000,000
        Products - Comp/Op Agg: $2,000,000
        Each Occurrence: $1,000,000
        Personal & Adv Injury: $1,000,000
        
        Policy Period: 01/01/2024 to 01/01/2025
        Policy Expiration: 01/01/2025
        
        Certificate Holder:
        Network Installation Corp
        123 Business Way
        Atlanta, GA 30301
        """
        
        doc_type, confidence = classify_document_type(ocr_text)
        
        assert doc_type == "insurance_certificate"
        # With this many keywords, confidence should be fairly high
        assert confidence >= 0.6
