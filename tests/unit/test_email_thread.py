"""
Unit Tests for Email Thread Infrastructure

Tests email thread models and DynamoDB operations with mocked AWS.
"""

import time
from unittest.mock import patch, MagicMock

import pytest
import boto3

from agents.shared.models.email_thread import (
    EmailMessage,
    EmailDirection,
    EmailAttachment,
    EmailThread,
)
from agents.shared.tools.email_thread import (
    create_thread_id,
    parse_thread_id,
    save_email_to_thread,
    load_thread_history,
    get_thread,
    get_next_sequence_number,
    format_thread_for_context,
    create_outbound_message,
    create_inbound_message,
    get_thread_summary,
)


# --- Fixtures ---


@pytest.fixture
def sample_thread_id():
    """Sample composite thread ID."""
    return "campaign-123#atlanta#provider-456"


@pytest.fixture
def sample_outbound_message(sample_thread_id):
    """Sample outbound email message."""
    return EmailMessage(
        thread_id=sample_thread_id,
        sequence_number=1,
        direction=EmailDirection.OUTBOUND,
        timestamp=1738800000,
        subject="Opportunity: Satellite Upgrade technicians needed",
        body_text="Dear Provider, We have an exciting opportunity...",
        body_html="<p>Dear Provider, We have an exciting opportunity...</p>",
        message_id="ses-message-id-001",
        in_reply_to=None,
        email_from="recruitment@example.com",
        email_to="provider@company.com",
        message_type="initial_outreach",
        attachments=[],
        metadata={"llm_generated": True},
    )


@pytest.fixture
def sample_inbound_message(sample_thread_id):
    """Sample inbound email message."""
    return EmailMessage(
        thread_id=sample_thread_id,
        sequence_number=2,
        direction=EmailDirection.INBOUND,
        timestamp=1738886400,
        subject="Re: Opportunity: Satellite Upgrade technicians needed",
        body_text="Yes, I'm interested! I have a bucket truck and spectrum analyzer.",
        message_id="email-message-id-002",
        in_reply_to="ses-message-id-001",
        email_from="provider@company.com",
        email_to="reply+campaign-123+provider-456@example.com",
        message_type="provider_response",
        attachments=[
            EmailAttachment(
                filename="insurance.pdf",
                s3_path="s3://bucket/documents/campaign-123/provider-456/insurance.pdf",
                content_type="application/pdf",
                size_bytes=125000,
            )
        ],
        metadata={},
    )


@pytest.fixture
def mock_dynamodb_table(mock_dynamodb):
    """Get the mocked DynamoDB table."""
    dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
    return dynamodb.Table("TestRecruitmentSessions")


# --- Model Tests ---


class TestEmailMessage:
    """Tests for EmailMessage model."""
    
    def test_create_outbound_message(self, sample_outbound_message):
        """Test creating an outbound message."""
        msg = sample_outbound_message
        
        assert msg.direction == EmailDirection.OUTBOUND
        assert msg.sequence_number == 1
        assert msg.message_type == "initial_outreach"
        assert msg.metadata.get("llm_generated") is True
    
    def test_create_inbound_message(self, sample_inbound_message):
        """Test creating an inbound message."""
        msg = sample_inbound_message
        
        assert msg.direction == EmailDirection.INBOUND
        assert msg.sequence_number == 2
        assert msg.in_reply_to == "ses-message-id-001"
        assert len(msg.attachments) == 1
    
    def test_to_dynamodb(self, sample_outbound_message):
        """Test DynamoDB serialization."""
        item = sample_outbound_message.to_dynamodb()
        
        assert item["PK"] == "THREAD#campaign-123#atlanta#provider-456"
        assert item["SK"] == "MSG#00001"
        assert item["direction"] == "OUTBOUND"
        assert item["subject"] == sample_outbound_message.subject
    
    def test_from_dynamodb(self, sample_outbound_message):
        """Test DynamoDB deserialization."""
        item = sample_outbound_message.to_dynamodb()
        restored = EmailMessage.from_dynamodb(item)
        
        assert restored.thread_id == sample_outbound_message.thread_id
        assert restored.direction == sample_outbound_message.direction
        assert restored.subject == sample_outbound_message.subject
    
    def test_to_context_string(self, sample_outbound_message):
        """Test context string formatting."""
        context = sample_outbound_message.to_context_string()
        
        assert "[SENT]" in context
        assert "initial_outreach" in context
        assert sample_outbound_message.subject in context
    
    def test_inbound_context_string(self, sample_inbound_message):
        """Test inbound message context string."""
        context = sample_inbound_message.to_context_string()
        
        assert "[RECEIVED]" in context
        assert "1 attachment(s)" in context


class TestEmailAttachment:
    """Tests for EmailAttachment model."""
    
    def test_create_attachment(self):
        """Test creating an attachment."""
        att = EmailAttachment(
            filename="insurance.pdf",
            s3_path="s3://bucket/path/insurance.pdf",
            content_type="application/pdf",
            size_bytes=125000,
        )
        
        assert att.filename == "insurance.pdf"
        assert att.size_bytes == 125000


class TestEmailThread:
    """Tests for EmailThread model."""
    
    def test_create_thread(self, sample_outbound_message, sample_inbound_message):
        """Test creating a thread."""
        thread = EmailThread(
            thread_id="campaign-123#atlanta#provider-456",
            campaign_id="campaign-123",
            market_id="atlanta",
            provider_id="provider-456",
            messages=[sample_outbound_message, sample_inbound_message],
        )
        
        assert thread.message_count == 2
        assert thread.outbound_count == 1
        assert thread.inbound_count == 1
    
    def test_thread_properties(self, sample_outbound_message, sample_inbound_message):
        """Test thread convenience properties."""
        thread = EmailThread(
            thread_id="campaign-123#atlanta#provider-456",
            campaign_id="campaign-123",
            market_id="atlanta",
            provider_id="provider-456",
            messages=[sample_outbound_message, sample_inbound_message],
        )
        
        assert thread.last_message == sample_inbound_message
        assert thread.last_outbound == sample_outbound_message
        assert thread.last_inbound == sample_inbound_message
    
    def test_empty_thread(self):
        """Test empty thread properties."""
        thread = EmailThread(
            thread_id="campaign-123#atlanta#provider-456",
            campaign_id="campaign-123",
            market_id="atlanta",
            provider_id="provider-456",
            messages=[],
        )
        
        assert thread.message_count == 0
        assert thread.last_message is None
        assert thread.last_outbound is None
    
    def test_thread_to_context_string(self, sample_outbound_message, sample_inbound_message):
        """Test thread context string formatting."""
        thread = EmailThread(
            thread_id="campaign-123#atlanta#provider-456",
            campaign_id="campaign-123",
            market_id="atlanta",
            provider_id="provider-456",
            messages=[sample_outbound_message, sample_inbound_message],
        )
        
        context = thread.to_context_string()
        
        assert "2 message(s)" in context
        assert "Message 1" in context
        assert "Message 2" in context


# --- Tool Tests ---


class TestThreadIdFunctions:
    """Tests for thread ID functions."""
    
    def test_create_thread_id(self):
        """Test creating composite thread ID."""
        thread_id = create_thread_id("campaign-123", "atlanta", "provider-456")
        
        assert thread_id == "campaign-123#atlanta#provider-456"
    
    def test_parse_thread_id(self):
        """Test parsing composite thread ID."""
        campaign_id, market_id, provider_id = parse_thread_id(
            "campaign-123#atlanta#provider-456"
        )
        
        assert campaign_id == "campaign-123"
        assert market_id == "atlanta"
        assert provider_id == "provider-456"
    
    def test_parse_thread_id_invalid(self):
        """Test parsing invalid thread ID raises error."""
        with pytest.raises(ValueError, match="Invalid thread_id format"):
            parse_thread_id("invalid-format")


class TestEmailThreadDynamoDB:
    """Tests for DynamoDB operations with mocked AWS."""
    
    def test_save_and_load_message(self, sample_outbound_message, mock_dynamodb):
        """Test saving and loading a message."""
        # Save message
        save_email_to_thread(sample_outbound_message)
        
        # Load thread
        messages = load_thread_history(sample_outbound_message.thread_id)
        
        assert len(messages) == 1
        assert messages[0].subject == sample_outbound_message.subject
        assert messages[0].direction == EmailDirection.OUTBOUND
    
    def test_load_empty_thread(self, mock_dynamodb):
        """Test loading an empty thread returns empty list."""
        messages = load_thread_history("nonexistent#thread#id")
        
        assert messages == []
    
    def test_get_next_sequence_number_empty(self, mock_dynamodb):
        """Test sequence number for empty thread is 1."""
        next_seq = get_next_sequence_number("empty#thread#id")
        
        assert next_seq == 1
    
    def test_get_next_sequence_number_existing(
        self, sample_outbound_message, mock_dynamodb
    ):
        """Test sequence number increments correctly."""
        # Save first message
        save_email_to_thread(sample_outbound_message)
        
        # Get next sequence
        next_seq = get_next_sequence_number(sample_outbound_message.thread_id)
        
        assert next_seq == 2
    
    def test_get_thread(
        self, sample_outbound_message, sample_inbound_message, mock_dynamodb
    ):
        """Test getting complete thread."""
        # Save both messages
        save_email_to_thread(sample_outbound_message)
        save_email_to_thread(sample_inbound_message)
        
        # Get thread
        thread = get_thread(sample_outbound_message.thread_id)
        
        assert thread.campaign_id == "campaign-123"
        assert thread.market_id == "atlanta"
        assert thread.provider_id == "provider-456"
        assert len(thread.messages) == 2
    
    def test_load_with_limit(self, mock_dynamodb):
        """Test loading thread with message limit."""
        thread_id = "campaign-test#atlanta#provider-test"
        
        # Create multiple messages
        for i in range(5):
            msg = EmailMessage(
                thread_id=thread_id,
                sequence_number=i + 1,
                direction=EmailDirection.OUTBOUND,
                timestamp=1738800000 + i * 3600,
                subject=f"Message {i + 1}",
                body_text=f"Body {i + 1}",
                message_id=f"msg-{i + 1}",
                email_from="from@example.com",
                email_to="to@example.com",
                message_type="follow_up",
            )
            save_email_to_thread(msg)
        
        # Load with limit
        messages = load_thread_history(thread_id, limit=3)
        
        assert len(messages) == 3
        assert messages[0].sequence_number == 1


class TestFormatThreadForContext:
    """Tests for context formatting functions."""
    
    def test_format_empty_thread(self):
        """Test formatting empty message list."""
        result = format_thread_for_context([])
        
        assert result == "[No conversation history]"
    
    def test_format_with_messages(self, sample_outbound_message, sample_inbound_message):
        """Test formatting messages for context."""
        result = format_thread_for_context([sample_outbound_message, sample_inbound_message])
        
        assert "Conversation History" in result
        assert "[SENT]" in result
        assert "[RECEIVED]" in result
    
    def test_format_with_limit(self, sample_outbound_message, sample_inbound_message):
        """Test formatting with message limit."""
        result = format_thread_for_context(
            [sample_outbound_message, sample_inbound_message],
            max_messages=1,
        )
        
        # Should only include the last message
        assert "Message 1" in result
        assert "[RECEIVED]" in result
        assert "[SENT]" not in result


class TestConvenienceFunctions:
    """Tests for convenience message creation functions."""
    
    def test_create_outbound_message(self, mock_dynamodb):
        """Test creating and saving outbound message."""
        thread_id = "campaign-new#chicago#provider-new"
        
        msg = create_outbound_message(
            thread_id=thread_id,
            subject="Test Subject",
            body_text="Test body",
            message_id="ses-123",
            email_from="system@example.com",
            email_to="provider@example.com",
            message_type="initial_outreach",
            metadata={"test": True},
        )
        
        assert msg.direction == EmailDirection.OUTBOUND
        assert msg.sequence_number == 1
        
        # Verify saved
        loaded = load_thread_history(thread_id)
        assert len(loaded) == 1
    
    def test_create_inbound_message(self, mock_dynamodb):
        """Test creating and saving inbound message."""
        thread_id = "campaign-new#chicago#provider-new"
        
        msg = create_inbound_message(
            thread_id=thread_id,
            subject="Re: Test Subject",
            body_text="Provider response",
            message_id="email-123",
            email_from="provider@example.com",
            email_to="reply@example.com",
        )
        
        assert msg.direction == EmailDirection.INBOUND
        assert msg.message_type == "provider_response"
        assert msg.sequence_number == 1
    
    def test_get_thread_summary(
        self, sample_outbound_message, sample_inbound_message, mock_dynamodb
    ):
        """Test getting thread summary."""
        # Save messages
        save_email_to_thread(sample_outbound_message)
        save_email_to_thread(sample_inbound_message)
        
        # Get summary
        summary = get_thread_summary(sample_outbound_message.thread_id)
        
        assert summary["message_count"] == 2
        assert summary["outbound_count"] == 1
        assert summary["inbound_count"] == 1
        assert summary["first_message_at"] == 1738800000
        assert summary["last_message_at"] == 1738886400