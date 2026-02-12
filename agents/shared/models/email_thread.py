"""
Email Thread Model

Pydantic models for email conversation threading.
Enables chat-like viewing of email history between system and providers.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EmailDirection(str, Enum):
    """Direction of an email message in a thread."""
    
    OUTBOUND = "OUTBOUND"  # System → Provider
    INBOUND = "INBOUND"    # Provider → System


class EmailAttachment(BaseModel):
    """Attachment metadata for an email message."""
    
    filename: str = Field(..., description="Original filename")
    s3_path: str = Field(..., description="S3 path where attachment is stored")
    content_type: str = Field(..., description="MIME content type")
    size_bytes: int = Field(..., ge=0, description="File size in bytes")


class EmailMessage(BaseModel):
    """
    Single email message in a conversation thread.
    
    Represents both outbound (system to provider) and inbound
    (provider to system) messages in a unified format.
    """
    
    # Thread identification
    thread_id: str = Field(
        ...,
        description="Composite thread ID: `campaign_id#market_id#provider_id`",
    )
    sequence_number: int = Field(
        ...,
        ge=1,
        description="1-based sequence number within the thread",
    )
    
    # Message direction and timing
    direction: EmailDirection = Field(
        ...,
        description="Whether message is outbound or inbound",
    )
    timestamp: int = Field(
        ...,
        description="Unix epoch timestamp when message was sent/received",
    )
    
    # Email content
    subject: str = Field(..., description="Email subject line")
    body_text: str = Field(..., description="Plain text email body")
    body_html: str | None = Field(
        default=None,
        description="HTML email body if available",
    )
    
    # Email metadata
    message_id: str = Field(
        ...,
        description="SES/email message ID for threading",
    )
    in_reply_to: str | None = Field(
        default=None,
        description="Message ID this is a reply to",
    )
    email_from: str = Field(..., description="Sender email address")
    email_to: str = Field(..., description="Recipient email address")
    
    # Message classification
    message_type: str = Field(
        ...,
        description="Type of message (initial_outreach, follow_up, provider_response, etc.)",
    )
    
    # Attachments and metadata
    attachments: list[EmailAttachment] = Field(
        default_factory=list,
        description="List of email attachments",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (e.g., llm_generated, template_used)",
    )
    
    def to_dynamodb(self) -> dict[str, Any]:
        """
        Convert to DynamoDB item format.
        
        Uses PK/SK pattern:
        - PK: THREAD#<thread_id>
        - SK: MSG#<sequence_number> (zero-padded to 5 digits)
        
        Returns:
            DynamoDB item dictionary
        """
        return {
            "PK": f"THREAD#{self.thread_id}",
            "SK": f"MSG#{self.sequence_number:05d}",
            "thread_id": self.thread_id,
            "sequence_number": self.sequence_number,
            "direction": self.direction.value,
            "timestamp": self.timestamp,
            "subject": self.subject,
            "body_text": self.body_text,
            "body_html": self.body_html,
            "message_id": self.message_id,
            "in_reply_to": self.in_reply_to,
            "email_from": self.email_from,
            "email_to": self.email_to,
            "message_type": self.message_type,
            "attachments": [att.model_dump() for att in self.attachments],
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dynamodb(cls, item: dict[str, Any]) -> "EmailMessage":
        """
        Parse from DynamoDB item.
        
        Args:
            item: DynamoDB item dictionary
            
        Returns:
            EmailMessage instance
        """
        attachments = [
            EmailAttachment(**att) 
            for att in item.get("attachments", [])
        ]
        
        return cls(
            thread_id=item["thread_id"],
            sequence_number=item["sequence_number"],
            direction=EmailDirection(item["direction"]),
            timestamp=item["timestamp"],
            subject=item["subject"],
            body_text=item["body_text"],
            body_html=item.get("body_html"),
            message_id=item["message_id"],
            in_reply_to=item.get("in_reply_to"),
            email_from=item["email_from"],
            email_to=item["email_to"],
            message_type=item["message_type"],
            attachments=attachments,
            metadata=item.get("metadata", {}),
        )
    
    def to_context_string(self) -> str:
        """
        Format message for LLM context.
        
        Returns:
            Human-readable string representation of the message
        """
        direction_label = "SENT" if self.direction == EmailDirection.OUTBOUND else "RECEIVED"
        attachment_info = f" [{len(self.attachments)} attachment(s)]" if self.attachments else ""
        
        return f"""[{direction_label}] {self.message_type}
Subject: {self.subject}
From: {self.email_from}
To: {self.email_to}{attachment_info}

{self.body_text}
"""


class EmailThread(BaseModel):
    """
    A complete email conversation thread.
    
    Contains all messages between the system and a provider
    for a specific campaign/market combination.
    """
    
    thread_id: str = Field(
        ...,
        description="Composite thread ID: campaign_id#market_id#provider_id",
    )
    campaign_id: str = Field(..., description="Campaign ID")
    market_id: str = Field(..., description="Market ID")
    provider_id: str = Field(..., description="Provider ID")
    messages: list[EmailMessage] = Field(
        default_factory=list,
        description="Ordered list of messages in the thread",
    )
    
    @property
    def message_count(self) -> int:
        """Total number of messages in thread."""
        return len(self.messages)
    
    @property
    def outbound_count(self) -> int:
        """Number of outbound messages."""
        return sum(1 for m in self.messages if m.direction == EmailDirection.OUTBOUND)
    
    @property
    def inbound_count(self) -> int:
        """Number of inbound messages."""
        return sum(1 for m in self.messages if m.direction == EmailDirection.INBOUND)
    
    @property
    def last_message(self) -> EmailMessage | None:
        """Get the most recent message in the thread."""
        return self.messages[-1] if self.messages else None
    
    @property
    def last_outbound(self) -> EmailMessage | None:
        """Get the most recent outbound message."""
        for message in reversed(self.messages):
            if message.direction == EmailDirection.OUTBOUND:
                return message
        return None
    
    @property
    def last_inbound(self) -> EmailMessage | None:
        """Get the most recent inbound message."""
        for message in reversed(self.messages):
            if message.direction == EmailDirection.INBOUND:
                return message
        return None
    
    def to_context_string(self, max_messages: int | None = None) -> str:
        """
        Format thread for LLM context.
        
        Args:
            max_messages: Maximum number of recent messages to include
            
        Returns:
            Formatted conversation history string
        """
        messages_to_format = self.messages
        if max_messages and len(messages_to_format) > max_messages:
            messages_to_format = messages_to_format[-max_messages:]
        
        if not messages_to_format:
            return "[No conversation history]"
        
        lines = [f"=== Email Thread ({self.message_count} message(s)) ===\n"]
        for i, message in enumerate(messages_to_format, 1):
            lines.append(f"--- Message {i} ---")
            lines.append(message.to_context_string())
        
        return "\n".join(lines)
