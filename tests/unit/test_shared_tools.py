"""
Unit tests for shared agent tools.

Tests cover:
- DynamoDB tools: load_provider_state, create_provider_record, update_provider_state
- EventBridge tools: send_event, send_events_batch
- Email tools: encode_reply_to, decode_reply_to, send_ses_email
- S3 tools: upload_document, download_document, parse_s3_uri
"""

import json
import os
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError

from agents.shared.models.dynamo import ProviderKey, ProviderState
from agents.shared.state_machine import ProviderStatus


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def mock_settings():
    """Provide mock settings for all tests."""
    # Also patch where get_settings is imported in email module
    with patch("agents.shared.config.get_settings") as mock, \
         patch("agents.shared.tools.email.get_settings") as email_mock, \
         patch("agents.shared.tools.s3.get_settings") as s3_mock, \
         patch("agents.shared.tools.eventbridge.get_settings") as eb_mock:
        settings = MagicMock()
        settings.aws_region = "us-west-2"
        settings.dynamodb_table_name = "RecruitmentSessions"
        settings.dynamodb_config = {"region_name": "us-west-2"}
        settings.eventbridge_bus_name = "recruitment"
        settings.eventbridge_source_prefix = "recruitment"
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
        eb_mock.return_value = settings
        yield settings


# ============================================================================
# Email Tools Tests
# ============================================================================

class TestEncodeReplyTo:
    """Tests for encode_reply_to function."""
    
    def test_encode_basic_ids(self, mock_settings):
        """Test encoding basic campaign and provider IDs."""
        from agents.shared.tools.email import encode_reply_to
        
        result = encode_reply_to(
            campaign_id="camp-001",
            provider_id="prov-001",
        )
        
        # Domain comes from settings.ses_reply_to_domain (test.example.com in test env)
        assert result == "campaign+camp-001_provider+prov-001@test.example.com"
    
    def test_encode_with_custom_domain(self, mock_settings):
        """Test encoding with custom domain."""
        from agents.shared.tools.email import encode_reply_to
        
        result = encode_reply_to(
            campaign_id="camp-002",
            provider_id="prov-002",
            domain="custom.example.com",
        )
        
        assert result == "campaign+camp-002_provider+prov-002@custom.example.com"
    
    def test_encode_uuid_style_ids(self, mock_settings):
        """Test encoding UUID-style identifiers."""
        from agents.shared.tools.email import encode_reply_to
        
        result = encode_reply_to(
            campaign_id="550e8400-e29b-41d4-a716",
            provider_id="660e8500-f30c-42d5-b817",
        )
        
        assert "550e8400-e29b-41d4-a716" in result
        assert "660e8500-f30c-42d5-b817" in result
    
    def test_encode_invalid_campaign_id_raises(self, mock_settings):
        """Test that invalid campaign ID raises error."""
        from agents.shared.exceptions import InvalidEmailFormatError
        from agents.shared.tools.email import encode_reply_to
        
        with pytest.raises(InvalidEmailFormatError):
            encode_reply_to(
                campaign_id="invalid@id",  # Contains @
                provider_id="prov-001",
            )
    
    def test_encode_invalid_provider_id_raises(self, mock_settings):
        """Test that invalid provider ID raises error."""
        from agents.shared.exceptions import InvalidEmailFormatError
        from agents.shared.tools.email import encode_reply_to
        
        with pytest.raises(InvalidEmailFormatError):
            encode_reply_to(
                campaign_id="camp-001",
                provider_id="invalid spaces",  # Contains spaces
            )


class TestDecodeReplyTo:
    """Tests for decode_reply_to function."""
    
    def test_decode_valid_address(self, mock_settings):
        """Test decoding a valid Reply-To address."""
        from agents.shared.tools.email import decode_reply_to
        
        result = decode_reply_to(
            "campaign+camp-001_provider+prov-001@example.com"
        )
        
        assert result.campaign_id == "camp-001"
        assert result.provider_id == "prov-001"
        assert result.domain == "example.com"
    
    def test_decode_with_subdomain(self, mock_settings):
        """Test decoding address with subdomain."""
        from agents.shared.tools.email import decode_reply_to
        
        result = decode_reply_to(
            "campaign+camp-002_provider+prov-002@reply.mail.example.com"
        )
        
        assert result.campaign_id == "camp-002"
        assert result.provider_id == "prov-002"
        assert result.domain == "reply.mail.example.com"
    
    def test_decode_invalid_format_raises(self, mock_settings):
        """Test that invalid format raises error."""
        from agents.shared.exceptions import InvalidEmailFormatError
        from agents.shared.tools.email import decode_reply_to
        
        with pytest.raises(InvalidEmailFormatError):
            decode_reply_to("invalid@example.com")
    
    def test_decode_missing_campaign_prefix_raises(self, mock_settings):
        """Test that missing campaign+ prefix raises error."""
        from agents.shared.exceptions import InvalidEmailFormatError
        from agents.shared.tools.email import decode_reply_to
        
        with pytest.raises(InvalidEmailFormatError):
            decode_reply_to("camp-001_provider+prov-001@example.com")


class TestDecodedReplyTo:
    """Tests for DecodedReplyTo dataclass."""
    
    def test_decoded_reply_to_frozen(self, mock_settings):
        """Test that DecodedReplyTo is immutable."""
        from agents.shared.tools.email import DecodedReplyTo
        
        decoded = DecodedReplyTo(
            campaign_id="camp-001",
            provider_id="prov-001",
            domain="example.com",
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            decoded.campaign_id = "changed"


class TestSendSESEmail:
    """Tests for send_ses_email function."""
    
    @patch("agents.shared.tools.email._get_client")
    def test_send_basic_email(self, mock_get_client, mock_settings):
        """Test sending a basic email."""
        from agents.shared.tools.email import send_ses_email
        
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "msg-12345"}
        mock_get_client.return_value = mock_client
        
        result = send_ses_email(
            to_address="provider@example.com",
            subject="Campaign Opportunity",
            body_text="You're invited to join our campaign.",
        )
        
        assert result == "msg-12345"
        mock_client.send_email.assert_called_once()
        
        call_kwargs = mock_client.send_email.call_args[1]
        assert call_kwargs["Destination"]["ToAddresses"] == ["provider@example.com"]
        assert call_kwargs["Message"]["Subject"]["Data"] == "Campaign Opportunity"
    
    @patch("agents.shared.tools.email._get_client")
    def test_send_with_reply_to(self, mock_get_client, mock_settings):
        """Test sending email with Reply-To address."""
        from agents.shared.tools.email import send_ses_email
        
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "msg-67890"}
        mock_get_client.return_value = mock_client
        
        result = send_ses_email(
            to_address="provider@example.com",
            subject="Test",
            body_text="Test body",
            reply_to="campaign+camp-001_provider+prov-001@reply.example.com",
        )
        
        call_kwargs = mock_client.send_email.call_args[1]
        assert "ReplyToAddresses" in call_kwargs
        assert call_kwargs["ReplyToAddresses"][0].startswith("campaign+camp-001")
    
    @patch("agents.shared.tools.email._get_client")
    def test_send_with_html_body(self, mock_get_client, mock_settings):
        """Test sending email with HTML body."""
        from agents.shared.tools.email import send_ses_email
        
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "msg-html"}
        mock_get_client.return_value = mock_client
        
        result = send_ses_email(
            to_address="provider@example.com",
            subject="Test",
            body_text="Plain text",
            body_html="<h1>HTML Body</h1>",
        )
        
        call_kwargs = mock_client.send_email.call_args[1]
        assert "Html" in call_kwargs["Message"]["Body"]


# ============================================================================
# S3 Tools Tests
# ============================================================================

class TestParseS3Uri:
    """Tests for _parse_s3_uri function."""
    
    def test_parse_valid_uri(self):
        """Test parsing a valid S3 URI."""
        from agents.shared.tools.s3 import _parse_s3_uri
        
        bucket, key = _parse_s3_uri("s3://my-bucket/path/to/file.pdf")
        
        assert bucket == "my-bucket"
        assert key == "path/to/file.pdf"
    
    def test_parse_uri_with_deep_path(self):
        """Test parsing URI with deep path."""
        from agents.shared.tools.s3 import _parse_s3_uri
        
        bucket, key = _parse_s3_uri(
            "s3://bucket/documents/camp-001/prov-001/insurance.pdf"
        )
        
        assert bucket == "bucket"
        assert key == "documents/camp-001/prov-001/insurance.pdf"
    
    def test_parse_invalid_scheme_raises(self):
        """Test that non-S3 scheme raises error."""
        from agents.shared.tools.s3 import _parse_s3_uri
        
        with pytest.raises(ValueError, match="Invalid S3 URI scheme"):
            _parse_s3_uri("http://example.com/file.pdf")
    
    def test_parse_uri_strips_leading_slash(self):
        """Test that leading slash is stripped from key."""
        from agents.shared.tools.s3 import _parse_s3_uri
        
        bucket, key = _parse_s3_uri("s3://bucket//key/file.pdf")
        
        assert key == "key/file.pdf"  # Leading slash stripped


class TestBuildDocumentKey:
    """Tests for _build_document_key function."""
    
    def test_build_key_format(self, mock_settings):
        """Test document key construction format."""
        from agents.shared.tools.s3 import _build_document_key
        
        key = _build_document_key(
            campaign_id="camp-001",
            provider_id="prov-001",
            filename="insurance.pdf",
        )
        
        # Should follow format: {prefix}{campaign_id}/{provider_id}/{timestamp}_{filename}
        assert key.startswith("documents/camp-001/prov-001/")
        assert key.endswith("_insurance.pdf")
    
    def test_build_key_with_custom_prefix(self, mock_settings):
        """Test key construction with custom prefix."""
        from agents.shared.tools.s3 import _build_document_key
        
        key = _build_document_key(
            campaign_id="camp-001",
            provider_id="prov-001",
            filename="doc.pdf",
            prefix="custom/",
        )
        
        assert key.startswith("custom/camp-001/prov-001/")
    
    def test_build_key_sanitizes_filename(self, mock_settings):
        """Test that path components are stripped from filename."""
        from agents.shared.tools.s3 import _build_document_key
        
        key = _build_document_key(
            campaign_id="camp-001",
            provider_id="prov-001",
            filename="/path/to/dangerous/../file.pdf",
        )
        
        # Should only contain the base filename
        assert "path" not in key or key.count("path") == 0


class TestUploadDocument:
    """Tests for upload_document function."""
    
    @patch("agents.shared.tools.s3._get_client")
    def test_upload_bytes_content(self, mock_get_client, mock_settings):
        """Test uploading bytes content."""
        from agents.shared.tools.s3 import upload_document
        
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        result = upload_document(
            content=b"PDF content here",
            campaign_id="camp-001",
            provider_id="prov-001",
            filename="test.pdf",
            content_type="application/pdf",
        )
        
        # Bucket name comes from environment (test-recruitment-documents in test env)
        assert result.startswith("s3://test-recruitment-documents/")
        assert "camp-001" in result
        assert "prov-001" in result
        mock_client.put_object.assert_called_once()
    
    @patch("agents.shared.tools.s3._get_client")
    def test_upload_with_metadata(self, mock_get_client, mock_settings):
        """Test uploading with metadata."""
        from agents.shared.tools.s3 import upload_document
        
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        result = upload_document(
            content=b"Content",
            campaign_id="camp-001",
            provider_id="prov-001",
            filename="doc.pdf",
            metadata={"original-name": "my document.pdf"},
        )
        
        call_kwargs = mock_client.put_object.call_args[1]
        assert "Metadata" in call_kwargs
        assert call_kwargs["Metadata"]["original-name"] == "my document.pdf"
    
    @patch("agents.shared.tools.s3._get_client")
    def test_upload_failure_raises(self, mock_get_client, mock_settings):
        """Test that S3 failure raises DocumentProcessingError."""
        from agents.shared.exceptions import DocumentProcessingError
        from agents.shared.tools.s3 import upload_document
        
        mock_client = MagicMock()
        mock_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "PutObject",
        )
        mock_get_client.return_value = mock_client
        
        with pytest.raises(DocumentProcessingError):
            upload_document(
                content=b"Content",
                campaign_id="camp-001",
                provider_id="prov-001",
                filename="doc.pdf",
            )


# ============================================================================
# EventBridge Tools Tests
# ============================================================================

class TestSendEvent:
    """Tests for send_event function."""
    
    @patch("agents.shared.tools.eventbridge._get_client")
    def test_send_event_success(self, mock_get_client, mock_settings):
        """Test successful event publication."""
        from agents.shared.models.events import SendMessageRequestedEvent
        from agents.shared.tools.eventbridge import send_event
        
        mock_client = MagicMock()
        mock_client.put_events.return_value = {
            "FailedEntryCount": 0,
            "Entries": [{"EventId": "event-123"}],
        }
        mock_get_client.return_value = mock_client
        
        event = SendMessageRequestedEvent(
            campaign_id="camp-001",
            provider_id="prov-001",
            provider_email="test@example.com",
            provider_name="Test Provider",
            message_type="initial_outreach",
        )
        
        result = send_event(event)
        
        assert result == "event-123"
        mock_client.put_events.assert_called_once()
    
    @patch("agents.shared.tools.eventbridge._get_client")
    def test_send_event_with_custom_source(self, mock_get_client, mock_settings):
        """Test event publication with custom source."""
        from agents.shared.models.events import SendMessageRequestedEvent
        from agents.shared.tools.eventbridge import send_event
        
        mock_client = MagicMock()
        mock_client.put_events.return_value = {
            "FailedEntryCount": 0,
            "Entries": [{"EventId": "event-456"}],
        }
        mock_get_client.return_value = mock_client
        
        event = SendMessageRequestedEvent(
            campaign_id="camp-001",
            provider_id="prov-001",
            provider_email="test@example.com",
            provider_name="Test Provider",
            message_type="initial_outreach",
        )
        
        result = send_event(event, source="custom.source")
        
        call_kwargs = mock_client.put_events.call_args[1]
        assert call_kwargs["Entries"][0]["Source"] == "custom.source"
    
    @patch("agents.shared.tools.eventbridge._get_client")
    def test_send_event_failure_raises(self, mock_get_client, mock_settings):
        """Test that EventBridge failure raises EventPublishError."""
        from agents.shared.exceptions import EventPublishError
        from agents.shared.models.events import SendMessageRequestedEvent
        from agents.shared.tools.eventbridge import send_event
        
        mock_client = MagicMock()
        mock_client.put_events.return_value = {
            "FailedEntryCount": 1,
            "Entries": [{
                "ErrorCode": "InternalException",
                "ErrorMessage": "Internal error",
            }],
        }
        mock_get_client.return_value = mock_client
        
        event = SendMessageRequestedEvent(
            campaign_id="camp-001",
            provider_id="prov-001",
            provider_email="test@example.com",
            provider_name="Test",
            message_type="initial_outreach",
        )
        
        with pytest.raises(EventPublishError):
            send_event(event)


class TestSendEventsBatch:
    """Tests for send_events_batch function."""
    
    @patch("agents.shared.tools.eventbridge._get_client")
    def test_send_batch_success(self, mock_get_client, mock_settings):
        """Test successful batch event publication."""
        from agents.shared.models.events import SendMessageRequestedEvent
        from agents.shared.tools.eventbridge import send_events_batch
        
        mock_client = MagicMock()
        mock_client.put_events.return_value = {
            "FailedEntryCount": 0,
            "Entries": [
                {"EventId": "event-1"},
                {"EventId": "event-2"},
            ],
        }
        mock_get_client.return_value = mock_client
        
        events = [
            SendMessageRequestedEvent(
                campaign_id="camp-001",
                provider_id="prov-001",
                provider_email="a@example.com",
                provider_name="Provider A",
                message_type="initial_outreach",
            ),
            SendMessageRequestedEvent(
                campaign_id="camp-001",
                provider_id="prov-002",
                provider_email="b@example.com",
                provider_name="Provider B",
                message_type="initial_outreach",
            ),
        ]
        
        result = send_events_batch(events)
        
        assert len(result) == 2
        assert "event-1" in result
        assert "event-2" in result
    
    def test_send_empty_batch_returns_empty(self, mock_settings):
        """Test that empty batch returns empty list."""
        from agents.shared.tools.eventbridge import send_events_batch
        
        result = send_events_batch([])
        
        assert result == []


# ============================================================================
# DynamoDB Tools Tests
# ============================================================================

class TestLoadProviderState:
    """Tests for load_provider_state function."""
    
    @patch("agents.shared.tools.dynamodb._get_table")
    def test_load_existing_provider(self, mock_get_table, mock_settings):
        """Test loading an existing provider."""
        from agents.shared.tools.dynamodb import load_provider_state
        
        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "PK": "SESSION#camp-001",
                "SK": "PROVIDER#prov-001",
                "campaign_id": "camp-001",
                "provider_id": "prov-001",
                "status": "WAITING_RESPONSE",
                "expected_next_event": "ProviderResponseReceived",
                "last_contacted_at": 1705312000,
                "provider_email": "test@example.com",
                "provider_market": "Atlanta",
                "version": 1,
                "created_at": 1705312000,
                "updated_at": 1705312000,
            }
        }
        mock_get_table.return_value = mock_table
        
        result = load_provider_state("camp-001", "prov-001")
        
        assert result is not None
        assert result.campaign_id == "camp-001"
        assert result.provider_id == "prov-001"
        assert result.status == ProviderStatus.WAITING_RESPONSE
    
    @patch("agents.shared.tools.dynamodb._get_table")
    def test_load_nonexistent_provider_returns_none(self, mock_get_table, mock_settings):
        """Test loading non-existent provider returns None."""
        from agents.shared.tools.dynamodb import load_provider_state
        
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # No Item
        mock_get_table.return_value = mock_table
        
        result = load_provider_state("camp-missing", "prov-missing")
        
        assert result is None


class TestCreateProviderRecord:
    """Tests for create_provider_record function."""
    
    @patch("agents.shared.tools.dynamodb._get_table")
    def test_create_new_provider(self, mock_get_table, mock_settings):
        """Test creating a new provider record."""
        from agents.shared.tools.dynamodb import create_provider_record
        
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}  # Success
        mock_get_table.return_value = mock_table
        
        result = create_provider_record(
            campaign_id="camp-001",
            provider_id="prov-001",
            provider_email="new@example.com",
            provider_market="Chicago",
            provider_name="New Provider",
        )
        
        assert result.campaign_id == "camp-001"
        assert result.provider_id == "prov-001"
        assert result.status == ProviderStatus.INVITED
        assert result.provider_market == "Chicago"
        mock_table.put_item.assert_called_once()
    
    @patch("agents.shared.tools.dynamodb._get_table")
    @patch("agents.shared.tools.dynamodb.load_provider_state")
    def test_create_idempotent_returns_existing(
        self, mock_load, mock_get_table, mock_settings
    ):
        """Test that create is idempotent - returns existing if exists."""
        from agents.shared.models.dynamo import ProviderState
        from agents.shared.tools.dynamodb import create_provider_record
        
        mock_table = MagicMock()
        mock_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "Exists"}},
            "PutItem",
        )
        mock_get_table.return_value = mock_table
        
        existing_state = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.WAITING_RESPONSE,
            expected_next_event="ProviderResponseReceived",
            last_contacted_at=1705312000,
            provider_email="existing@example.com",
            provider_market="Atlanta",
            version=2,
            created_at=1705311000,
            updated_at=1705312000,
        )
        mock_load.return_value = existing_state
        
        result = create_provider_record(
            campaign_id="camp-001",
            provider_id="prov-001",
            provider_email="new@example.com",
            provider_market="Chicago",
        )
        
        # Should return existing, not new
        assert result.provider_email == "existing@example.com"
        assert result.provider_market == "Atlanta"
        assert result.version == 2


class TestUpdateProviderState:
    """Tests for update_provider_state function."""
    
    @patch("agents.shared.tools.dynamodb._get_table")
    @patch("agents.shared.tools.dynamodb.load_provider_state")
    def test_update_valid_transition(
        self, mock_load, mock_get_table, mock_settings
    ):
        """Test updating with valid state transition."""
        from agents.shared.models.dynamo import ProviderState
        from agents.shared.tools.dynamodb import update_provider_state
        
        mock_table = MagicMock()
        mock_table.update_item.return_value = {}
        mock_get_table.return_value = mock_table
        
        current_state = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.INVITED,  # Can transition to WAITING_RESPONSE
            expected_next_event="ProviderResponseReceived",
            last_contacted_at=1705312000,
            provider_email="test@example.com",
            provider_market="Atlanta",
            version=1,
            created_at=1705312000,
            updated_at=1705312000,
        )
        mock_load.return_value = current_state
        
        result = update_provider_state(
            campaign_id="camp-001",
            provider_id="prov-001",
            new_status=ProviderStatus.WAITING_RESPONSE,
        )
        
        mock_table.update_item.assert_called_once()
    
    @patch("agents.shared.tools.dynamodb.load_provider_state")
    def test_update_nonexistent_provider_raises(self, mock_load, mock_settings):
        """Test updating non-existent provider raises error."""
        from agents.shared.exceptions import ProviderNotFoundError
        from agents.shared.tools.dynamodb import update_provider_state
        
        mock_load.return_value = None
        
        with pytest.raises(ProviderNotFoundError):
            update_provider_state(
                campaign_id="camp-missing",
                provider_id="prov-missing",
                new_status=ProviderStatus.WAITING_RESPONSE,
            )
    
    @patch("agents.shared.tools.dynamodb.load_provider_state")
    def test_update_invalid_transition_raises(self, mock_load, mock_settings):
        """Test invalid state transition raises error."""
        from agents.shared.exceptions import InvalidStateTransitionError
        from agents.shared.models.dynamo import ProviderState
        from agents.shared.tools.dynamodb import update_provider_state
        
        current_state = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.REJECTED,  # Terminal state
            expected_next_event=None,
            last_contacted_at=1705312000,
            provider_email="test@example.com",
            provider_market="Atlanta",
            version=1,
            created_at=1705312000,
            updated_at=1705312000,
        )
        mock_load.return_value = current_state
        
        with pytest.raises(InvalidStateTransitionError):
            update_provider_state(
                campaign_id="camp-001",
                provider_id="prov-001",
                new_status=ProviderStatus.QUALIFIED,  # Cannot go from REJECTED
            )


class TestProviderKey:
    """Tests for ProviderKey utility class."""

    def test_key_creation(self):
        """Create ProviderKey instance."""
        key = ProviderKey(campaign_id="camp-001", provider_id="prov-001")
        assert key.pk == "SESSION#camp-001"
        assert key.sk == "PROVIDER#prov-001"

    def test_to_key(self):
        """Generate DynamoDB key dict."""
        key = ProviderKey(campaign_id="camp-001", provider_id="prov-001")
        key_dict = key.to_key()
        
        assert key_dict["PK"] == "SESSION#camp-001"
        assert key_dict["SK"] == "PROVIDER#prov-001"

    def test_from_pk_sk(self):
        """Parse PK/SK strings to create key."""
        pk = "SESSION#camp-001"
        sk = "PROVIDER#prov-001"
        
        key = ProviderKey.from_pk_sk(pk, sk)
        
        assert key.campaign_id == "camp-001"
        assert key.provider_id == "prov-001"

    def test_provider_key_to_key(self):
        """Test ProviderKey.to_key() method."""
        from agents.shared.models.dynamo import ProviderKey
        
        key = ProviderKey(campaign_id="camp-xyz", provider_id="prov-abc")
        result = key.to_key()
        
        assert result["PK"] == "SESSION#camp-xyz"
        assert result["SK"] == "PROVIDER#prov-abc"

    def test_provider_key_properties(self):
        """Test ProviderKey property accessors."""
        from agents.shared.models.dynamo import ProviderKey
        
        key = ProviderKey(campaign_id="camp-xyz", provider_id="prov-abc")
        
        assert key.pk == "SESSION#camp-xyz"
        assert key.sk == "PROVIDER#prov-abc"


class TestProviderState:
    """Tests for ProviderState DynamoDB model."""

    def test_provider_state_creation(self):
        """Create ProviderState instance."""
        state = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.INVITED,
            expected_next_event="SendMessageRequested",
            last_contacted_at=1705312000,
            provider_email="test@example.com",
            provider_market="atlanta",
        )
        assert state.campaign_id == "camp-001"
        assert state.status == ProviderStatus.INVITED

    def test_pk_sk_properties(self):
        """Verify PK and SK property generation."""
        state = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.INVITED,
            last_contacted_at=1705312000,
            provider_email="test@example.com",
            provider_market="atlanta",
        )
        assert state.pk == "SESSION#camp-001"
        assert state.sk == "PROVIDER#prov-001"

    def test_gsi1pk_property(self):
        """Verify GSI1PK property generation."""
        state = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.INVITED,
            expected_next_event="SendMessageRequested",
            last_contacted_at=1705312000,
            provider_email="test@example.com",
            provider_market="atlanta",
        )
        assert state.gsi1pk == "INVITED#SendMessageRequested"

    def test_to_dynamodb(self):
        """Serialize to DynamoDB item format."""
        state = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.WAITING_RESPONSE,
            expected_next_event="ProviderResponseReceived",
            last_contacted_at=1705312000,
            provider_email="test@example.com",
            provider_market="chicago",
            email_thread_id="<abc123@mail.com>",
        )
        item = state.to_dynamodb()
        
        assert item["PK"] == "SESSION#camp-001"
        assert item["SK"] == "PROVIDER#prov-001"
        assert item["status"] == "WAITING_RESPONSE"
        assert item["GSI1PK"] == "WAITING_RESPONSE#ProviderResponseReceived"
        assert item["email_thread_id"] == "<abc123@mail.com>"

    def test_from_dynamodb(self):
        """Deserialize from DynamoDB item."""
        sample = {
            "PK": "SESSION#campaign-001",
            "SK": "PROVIDER#prov-001",
            "campaign_id": "campaign-001",
            "provider_id": "prov-001",
            "status": "INVITED",
            "expected_next_event": None,
            "last_contacted_at": 1705312000,
            "provider_email": "test@example.com",
            "provider_market": "atlanta",
            "version": 1,
            "created_at": 1705312000,
            "updated_at": 1705312000,
        }
        state = ProviderState.from_dynamodb(sample)
        
        assert state.campaign_id == "campaign-001"
        assert state.provider_id == "prov-001"
        assert state.status == ProviderStatus.INVITED
        assert state.provider_market == "atlanta"

    def test_with_updates(self):
        """Create new state with updates."""
        original = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.INVITED,
            last_contacted_at=1705312000,
            provider_email="test@example.com",
            provider_market="atlanta",
            version=1,
        )
        
        updated = original.with_updates(
            status=ProviderStatus.WAITING_RESPONSE,
            expected_next_event="ProviderResponseReceived",
        )
        
        # Original unchanged (frozen)
        assert original.status == ProviderStatus.INVITED
        assert original.version == 1
        
        # Updated is new instance
        assert updated.status == ProviderStatus.WAITING_RESPONSE
        assert updated.version == 2
        assert updated.updated_at is not None

    def test_defaults(self):
        """Verify default field values."""
        state = ProviderState(
            campaign_id="camp-001",
            provider_id="prov-001",
            status=ProviderStatus.INVITED,
            last_contacted_at=1705312000,
            provider_email="test@example.com",
            provider_market="atlanta",
        )
        
        assert state.equipment_confirmed == []
        assert state.equipment_missing == []
        assert state.documents_uploaded == []
        assert state.documents_pending == []
        assert state.artifacts == {}
        assert state.certifications == []
        assert state.version == 1


# ============================================================================
# Integration-style Tests
# ============================================================================
