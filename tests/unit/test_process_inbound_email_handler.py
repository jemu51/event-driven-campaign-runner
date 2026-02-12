"""
Unit tests for ProcessInboundEmail Lambda handler.

Tests cover:
- Email parser: email_parser.py
- Attachment handler: attachment_handler.py
"""

from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Email Parser Tests
# ============================================================================

class TestEmailParseResult:
    """Tests for EmailParseResult dataclass."""
    
    def test_email_parse_result_required_fields(self):
        """Test EmailParseResult with required fields only."""
        from lambdas.process_inbound_email.email_parser import EmailParseResult
        
        result = EmailParseResult(
            from_address="provider@example.com",
            subject="Re: Satellite Campaign",
            body="I'm interested in the opportunity.",
            message_id="<abc123@mail.example.com>",
        )
        
        assert result.from_address == "provider@example.com"
        assert result.subject == "Re: Satellite Campaign"
        assert result.body == "I'm interested in the opportunity."
        assert result.message_id == "<abc123@mail.example.com>"
        assert result.campaign_id is None
        assert result.provider_id is None
        assert result.attachments == []
        assert result.parse_errors == []
    
    def test_email_parse_result_all_fields(self):
        """Test EmailParseResult with all fields populated."""
        from lambdas.process_inbound_email.email_parser import (
            EmailParseResult,
            AttachmentData,
        )
        
        attachment = AttachmentData(
            filename="insurance.pdf",
            content=b"PDF content",
            content_type="application/pdf",
            size_bytes=1024,
        )
        
        result = EmailParseResult(
            from_address="provider@example.com",
            subject="Re: Satellite Campaign",
            body="Here's my insurance doc.",
            message_id="<abc123@mail.example.com>",
            campaign_id="camp-001",
            provider_id="prov-001",
            received_at="2024-01-15T10:30:00Z",
            to_addresses=["campaign+camp-001_provider+prov-001@example.com"],
            cc_addresses=["admin@example.com"],
            in_reply_to="<original@mail.example.com>",
            references=["<ref1@mail.example.com>"],
            attachments=[attachment],
        )
        
        assert result.campaign_id == "camp-001"
        assert result.provider_id == "prov-001"
        assert len(result.attachments) == 1
        assert result.attachments[0].filename == "insurance.pdf"


class TestExtractAddress:
    """Tests for _extract_address helper function."""
    
    def test_extract_from_angle_brackets(self):
        """Test extracting address from 'Name <email>' format."""
        from lambdas.process_inbound_email.email_parser import _extract_address
        
        assert _extract_address("John Doe <john@example.com>") == "john@example.com"
        assert _extract_address("<john@example.com>") == "john@example.com"
    
    def test_extract_plain_email(self):
        """Test extracting plain email address."""
        from lambdas.process_inbound_email.email_parser import _extract_address
        
        assert _extract_address("john@example.com") == "john@example.com"
    
    def test_extract_with_whitespace(self):
        """Test handling whitespace in address."""
        from lambdas.process_inbound_email.email_parser import _extract_address
        
        assert _extract_address("  john@example.com  ") == "john@example.com"
    
    def test_extract_empty_string(self):
        """Test handling empty input."""
        from lambdas.process_inbound_email.email_parser import _extract_address
        
        assert _extract_address("") == ""
        assert _extract_address(None) == ""


class TestDecodeReplyTo:
    """Tests for decode_reply_to function in email parser."""
    
    def test_decode_valid_reply_to(self):
        """Test decoding a valid Reply-To address."""
        from lambdas.process_inbound_email.email_parser import decode_reply_to
        
        result = decode_reply_to(
            "campaign+camp-001_provider+prov-001@example.com"
        )
        
        assert result is not None
        assert result.campaign_id == "camp-001"
        assert result.provider_id == "prov-001"
        assert result.domain == "example.com"
    
    def test_decode_with_uuid_ids(self):
        """Test decoding with UUID-style identifiers."""
        from lambdas.process_inbound_email.email_parser import decode_reply_to
        
        result = decode_reply_to(
            "campaign+550e8400-e29b-41d4-a716-446655440000_provider+660e8500@mail.example.com"
        )
        
        assert result is not None
        assert result.campaign_id == "550e8400-e29b-41d4-a716-446655440000"
        assert result.provider_id == "660e8500"
    
    def test_decode_invalid_format_returns_none(self):
        """Test that invalid formats return None."""
        from lambdas.process_inbound_email.email_parser import decode_reply_to
        
        # Missing campaign+ prefix
        assert decode_reply_to("camp-001_provider+prov-001@example.com") is None
        
        # Missing provider+ prefix
        assert decode_reply_to("campaign+camp-001_prov-001@example.com") is None
        
        # Plain email
        assert decode_reply_to("test@example.com") is None
        
        # Empty string
        assert decode_reply_to("") is None


class TestExtractAddresses:
    """Tests for _extract_addresses helper function."""
    
    def test_extract_multiple_addresses(self):
        """Test extracting multiple comma-separated addresses."""
        from lambdas.process_inbound_email.email_parser import _extract_addresses
        
        result = _extract_addresses(
            "John <john@example.com>, Jane <jane@example.com>, bob@example.com"
        )
        
        assert len(result) == 3
        assert "john@example.com" in result
        assert "jane@example.com" in result
        assert "bob@example.com" in result
    
    def test_extract_single_address(self):
        """Test extracting single address."""
        from lambdas.process_inbound_email.email_parser import _extract_addresses
        
        result = _extract_addresses("john@example.com")
        assert result == ["john@example.com"]
    
    def test_extract_empty_returns_empty_list(self):
        """Test that empty input returns empty list."""
        from lambdas.process_inbound_email.email_parser import _extract_addresses
        
        assert _extract_addresses(None) == []
        assert _extract_addresses("") == []


class TestEmailIdentifiers:
    """Tests for EmailIdentifiers dataclass."""
    
    def test_email_identifiers_frozen(self):
        """Test that EmailIdentifiers is immutable."""
        from lambdas.process_inbound_email.email_parser import EmailIdentifiers
        
        identifiers = EmailIdentifiers(
            campaign_id="camp-001",
            provider_id="prov-001",
            domain="example.com",
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            identifiers.campaign_id = "changed"


# ============================================================================
# Attachment Handler Tests
# ============================================================================

class TestAttachmentInfo:
    """Tests for AttachmentInfo dataclass."""
    
    def test_attachment_info_to_dict(self):
        """Test AttachmentInfo.to_dict() method."""
        from lambdas.process_inbound_email.attachment_handler import AttachmentInfo
        
        info = AttachmentInfo(
            filename="insurance.pdf",
            s3_path="s3://bucket/attachments/camp-001/prov-001/123_insurance.pdf",
            content_type="application/pdf",
            size_bytes=102400,
        )
        
        result = info.to_dict()
        
        assert result["filename"] == "insurance.pdf"
        assert "camp-001" in result["s3_path"]
        assert result["content_type"] == "application/pdf"
        assert result["size_bytes"] == 102400
    
    def test_attachment_info_frozen(self):
        """Test that AttachmentInfo is immutable."""
        from lambdas.process_inbound_email.attachment_handler import AttachmentInfo
        
        info = AttachmentInfo(
            filename="test.pdf",
            s3_path="s3://bucket/test.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError
            info.filename = "changed.pdf"


class TestSanitizeFilename:
    """Tests for _sanitize_filename helper function."""
    
    def test_sanitize_removes_path_components(self):
        """Test that path components are removed."""
        from lambdas.process_inbound_email.attachment_handler import _sanitize_filename
        
        assert _sanitize_filename("/path/to/file.pdf") == "file.pdf"
        assert _sanitize_filename("C:\\Users\\file.pdf") == "file.pdf"
    
    def test_sanitize_replaces_spaces(self):
        """Test that spaces are replaced with underscores."""
        from lambdas.process_inbound_email.attachment_handler import _sanitize_filename
        
        assert _sanitize_filename("my file name.pdf") == "my_file_name.pdf"
    
    def test_sanitize_limits_length(self):
        """Test that long filenames are truncated."""
        from lambdas.process_inbound_email.attachment_handler import _sanitize_filename
        
        long_name = "a" * 250 + ".pdf"
        result = _sanitize_filename(long_name)
        assert len(result) <= 200


class TestBuildS3Key:
    """Tests for _build_s3_key helper function."""
    
    def test_build_s3_key_format(self):
        """Test S3 key construction format."""
        from lambdas.process_inbound_email.attachment_handler import _build_s3_key
        
        key = _build_s3_key(
            campaign_id="camp-001",
            provider_id="prov-001",
            filename="insurance.pdf",
            prefix="attachments/",
        )
        
        assert key.startswith("attachments/camp-001/prov-001/")
        assert key.endswith("_insurance.pdf")
        # Should contain timestamp
        assert len(key.split("/")[-1]) > len("insurance.pdf")
    
    def test_build_s3_key_sanitizes_filename(self):
        """Test that S3 key includes sanitized filename."""
        from lambdas.process_inbound_email.attachment_handler import _build_s3_key
        
        key = _build_s3_key(
            campaign_id="camp-001",
            provider_id="prov-001",
            filename="my document file.pdf",
            prefix="attachments/",
        )
        
        assert "my_document_file.pdf" in key


# ============================================================================
# Integration Tests
# ============================================================================

class TestProcessInboundEmailIntegration:
    """Integration tests for ProcessInboundEmail components."""
    
    def test_full_email_flow_decode_ids(self):
        """Test decoding campaign/provider IDs from Reply-To in To addresses."""
        from lambdas.process_inbound_email.email_parser import (
            _find_identifiers,
        )
        
        to_addresses = ["campaign+camp-001_provider+prov-001@example.com"]
        cc_addresses = []
        
        identifiers = _find_identifiers(to_addresses, cc_addresses)
        
        assert identifiers is not None
        assert identifiers.campaign_id == "camp-001"
        assert identifiers.provider_id == "prov-001"
