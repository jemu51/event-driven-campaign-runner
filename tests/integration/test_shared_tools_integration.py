"""
Integration Tests for Shared Tools

Tests cross-component interactions:
- Email encode/decode roundtrip with real settings
- DynamoDB GSI1 format alignment with query patterns
- S3 key patterns that enable ID extraction
"""

from unittest.mock import MagicMock, patch

import pytest

from agents.shared.state_machine import ProviderStatus


@pytest.fixture(autouse=True)
def mock_settings():
    """Provide mock settings for all tests."""
    with patch("agents.shared.config.get_settings") as mock, \
         patch("agents.shared.tools.email.get_settings") as email_mock, \
         patch("agents.shared.tools.s3.get_settings") as s3_mock:
        settings = MagicMock()
        settings.aws_region = "us-west-2"
        settings.dynamodb_table_name = "RecruitmentSessions"
        settings.dynamodb_config = {"region_name": "us-west-2"}
        settings.s3_bucket_name = "test-recruitment-documents"
        settings.s3_documents_prefix = "documents/"
        settings.s3_config = {"region_name": "us-west-2"}
        settings.ses_from_address = "noreply@example.com"
        settings.ses_from_name = "Recruitment Platform"
        settings.ses_reply_to_domain = "test.example.com"
        settings.ses_configuration_set = "recruitment-emails"
        mock.return_value = settings
        email_mock.return_value = settings
        s3_mock.return_value = settings
        yield settings


class TestEmailFlowIntegration:
    """Integration tests for email encode/decode flow."""
    
    def test_encode_decode_roundtrip(self, mock_settings):
        """Test that encoding then decoding returns original values."""
        from agents.shared.tools.email import decode_reply_to, encode_reply_to
        
        original_campaign_id = "550e8400-e29b-41d4"
        original_provider_id = "660e8500-f30c"
        
        encoded = encode_reply_to(
            campaign_id=original_campaign_id,
            provider_id=original_provider_id,
        )
        
        decoded = decode_reply_to(encoded)
        
        assert decoded.campaign_id == original_campaign_id
        assert decoded.provider_id == original_provider_id


class TestDynamoDBStateTransitionFlow:
    """Integration tests for DynamoDB state transitions."""
    
    def test_gsi1pk_format_matches_query_expectations(self):
        """Test that GSI1PK format matches SendFollowUps query format."""
        from agents.shared.models.dynamo import ProviderState
        
        state = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.WAITING_RESPONSE,
            expected_next_event="ProviderResponseReceived",
            last_contacted_at=1705312000,
            provider_email="test@example.com",
            provider_market="Atlanta",
            version=1,
            created_at=1705312000,
            updated_at=1705312000,
        )
        
        item = state.to_dynamodb()
        
        # GSI1PK format must match what SendFollowUps queries
        expected_gsi1pk = f"{state.status.value}#{state.expected_next_event}"
        assert item["GSI1PK"] == expected_gsi1pk
        assert item["GSI1PK"] == "WAITING_RESPONSE#ProviderResponseReceived"


class TestS3KeyPatternIntegration:
    """Integration tests for S3 key patterns."""
    
    def test_key_format_enables_id_extraction(self, mock_settings):
        """Test that built keys enable campaign/provider ID extraction."""
        from agents.shared.tools.s3 import _build_document_key
        from lambdas.textract_completion.handler import _extract_ids_from_s3_path
        
        key = _build_document_key(
            campaign_id="camp-001",
            provider_id="prov-001",
            filename="insurance.pdf",
        )
        
        # Key should enable ID extraction
        assert "camp-001" in key
        assert "prov-001" in key
        
        # Verify structure (documents/{campaign}/{provider}/...)
        parts = key.split("/")
        assert len(parts) >= 4  # prefix/campaign/provider/filename
