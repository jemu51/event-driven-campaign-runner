"""
Email Thread Tools

DynamoDB operations for email conversation threading.
Enables persistent storage and retrieval of email history.
"""

import time
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError

from agents.shared.config import get_settings
from agents.shared.models.email_thread import (
    EmailMessage,
    EmailDirection,
    EmailThread,
    EmailAttachment,
)


log = structlog.get_logger()


def create_thread_id(campaign_id: str, market_id: str, provider_id: str) -> str:
    """
    Create composite thread ID.
    
    Thread ID uniquely identifies a conversation between the system
    and a specific provider for a campaign/market combination.
    
    Args:
        campaign_id: Campaign identifier
        market_id: Market identifier
        provider_id: Provider identifier
        
    Returns:
        Composite thread ID in format: campaign_id#market_id#provider_id
    """
    return f"{campaign_id}#{market_id}#{provider_id}"


def parse_thread_id(thread_id: str) -> tuple[str, str, str]:
    """
    Parse composite thread ID into components.
    
    Args:
        thread_id: Composite thread ID
        
    Returns:
        Tuple of (campaign_id, market_id, provider_id)
        
    Raises:
        ValueError: If thread_id format is invalid
    """
    parts = thread_id.split("#")
    if len(parts) != 3:
        raise ValueError(f"Invalid thread_id format: {thread_id}")
    return parts[0], parts[1], parts[2]


def _get_dynamodb_table():
    """Get DynamoDB table resource."""
    settings = get_settings()
    dynamodb = boto3.resource("dynamodb", **settings.dynamodb_config)
    return dynamodb.Table(settings.dynamodb_table_name)


def save_email_to_thread(message: EmailMessage) -> None:
    """
    Persist email message to thread history.
    
    Saves the message to DynamoDB using the thread PK/SK pattern.
    
    Args:
        message: EmailMessage to persist
        
    Raises:
        ClientError: If DynamoDB operation fails
    """
    table = _get_dynamodb_table()
    item = message.to_dynamodb()
    
    log.info(
        "email_thread_save",
        thread_id=message.thread_id,
        sequence_number=message.sequence_number,
        direction=message.direction.value,
    )
    
    try:
        table.put_item(Item=item)
        log.debug("email_thread_saved", thread_id=message.thread_id)
    except ClientError as e:
        log.error(
            "email_thread_save_error",
            thread_id=message.thread_id,
            error=str(e),
        )
        raise


def load_thread_history(
    thread_id: str,
    limit: int | None = None,
    ascending: bool = True,
) -> list[EmailMessage]:
    """
    Load conversation history for a thread.
    
    Retrieves all messages in a thread, ordered by sequence number.
    
    Args:
        thread_id: Composite thread ID
        limit: Maximum number of messages to return (None = all)
        ascending: If True, oldest first. If False, newest first.
        
    Returns:
        List of EmailMessage ordered by sequence number
    """
    table = _get_dynamodb_table()
    pk = f"THREAD#{thread_id}"
    
    query_kwargs: dict[str, Any] = {
        "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
        "ExpressionAttributeValues": {
            ":pk": pk,
            ":sk_prefix": "MSG#",
        },
        "ScanIndexForward": ascending,
    }
    
    if limit:
        query_kwargs["Limit"] = limit
    
    log.debug(
        "email_thread_load",
        thread_id=thread_id,
        limit=limit,
    )
    
    try:
        response = table.query(**query_kwargs)
        items = response.get("Items", [])
        
        messages = [EmailMessage.from_dynamodb(item) for item in items]
        
        log.debug(
            "email_thread_loaded",
            thread_id=thread_id,
            message_count=len(messages),
        )
        
        return messages
        
    except ClientError as e:
        log.error(
            "email_thread_load_error",
            thread_id=thread_id,
            error=str(e),
        )
        raise


def get_thread(
    thread_id: str,
    limit: int | None = None,
) -> EmailThread:
    """
    Load complete thread with metadata.
    
    Args:
        thread_id: Composite thread ID
        limit: Maximum number of messages to include
        
    Returns:
        EmailThread with all messages loaded
    """
    campaign_id, market_id, provider_id = parse_thread_id(thread_id)
    messages = load_thread_history(thread_id, limit=limit)
    
    return EmailThread(
        thread_id=thread_id,
        campaign_id=campaign_id,
        market_id=market_id,
        provider_id=provider_id,
        messages=messages,
    )


def get_next_sequence_number(thread_id: str) -> int:
    """
    Get next sequence number for thread.
    
    Queries the thread to find the highest existing sequence number
    and returns the next value.
    
    Args:
        thread_id: Composite thread ID
        
    Returns:
        Next sequence number (1 if thread is empty)
    """
    messages = load_thread_history(thread_id, limit=1, ascending=False)
    
    if not messages:
        return 1
    
    return messages[0].sequence_number + 1


def format_thread_for_context(
    messages: list[EmailMessage],
    max_messages: int | None = None,
) -> str:
    """
    Format thread history for LLM context.
    
    Creates a human-readable representation of the conversation
    suitable for inclusion in LLM prompts.
    
    Args:
        messages: List of EmailMessage in the thread
        max_messages: Maximum number of recent messages to include
        
    Returns:
        Formatted conversation history string
    """
    if not messages:
        return "[No conversation history]"
    
    # Take only the most recent messages if limit specified
    messages_to_format = messages
    if max_messages and len(messages_to_format) > max_messages:
        messages_to_format = messages_to_format[-max_messages:]
    
    lines = [f"=== Conversation History ({len(messages)} total message(s)) ===\n"]
    
    for i, message in enumerate(messages_to_format, 1):
        lines.append(f"--- Message {i} ---")
        lines.append(message.to_context_string())
    
    return "\n".join(lines)


def get_thread_summary(thread_id: str) -> dict[str, Any]:
    """
    Get summary statistics for a thread without loading all messages.
    
    Args:
        thread_id: Composite thread ID
        
    Returns:
        Dictionary with thread summary statistics
    """
    messages = load_thread_history(thread_id)
    
    if not messages:
        return {
            "thread_id": thread_id,
            "message_count": 0,
            "outbound_count": 0,
            "inbound_count": 0,
            "first_message_at": None,
            "last_message_at": None,
        }
    
    outbound_count = sum(1 for m in messages if m.direction == EmailDirection.OUTBOUND)
    inbound_count = sum(1 for m in messages if m.direction == EmailDirection.INBOUND)
    
    return {
        "thread_id": thread_id,
        "message_count": len(messages),
        "outbound_count": outbound_count,
        "inbound_count": inbound_count,
        "first_message_at": messages[0].timestamp,
        "last_message_at": messages[-1].timestamp,
    }


def create_outbound_message(
    thread_id: str,
    subject: str,
    body_text: str,
    message_id: str,
    email_from: str,
    email_to: str,
    message_type: str,
    body_html: str | None = None,
    in_reply_to: str | None = None,
    attachments: list[EmailAttachment] | None = None,
    metadata: dict[str, Any] | None = None,
) -> EmailMessage:
    """
    Create and save an outbound email message.
    
    Convenience function that creates the message with the next
    sequence number and saves it to the thread.
    
    Args:
        thread_id: Composite thread ID
        subject: Email subject
        body_text: Plain text body
        message_id: SES message ID
        email_from: Sender address
        email_to: Recipient address
        message_type: Type of message (initial_outreach, follow_up, etc.)
        body_html: Optional HTML body
        in_reply_to: Optional parent message ID
        attachments: Optional list of attachments
        metadata: Optional additional metadata
        
    Returns:
        Created and saved EmailMessage
    """
    sequence_number = get_next_sequence_number(thread_id)
    
    message = EmailMessage(
        thread_id=thread_id,
        sequence_number=sequence_number,
        direction=EmailDirection.OUTBOUND,
        timestamp=int(time.time()),
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        message_id=message_id,
        in_reply_to=in_reply_to,
        email_from=email_from,
        email_to=email_to,
        message_type=message_type,
        attachments=attachments or [],
        metadata=metadata or {},
    )
    
    save_email_to_thread(message)
    return message


def create_inbound_message(
    thread_id: str,
    subject: str,
    body_text: str,
    message_id: str,
    email_from: str,
    email_to: str,
    body_html: str | None = None,
    in_reply_to: str | None = None,
    attachments: list[EmailAttachment] | None = None,
    metadata: dict[str, Any] | None = None,
) -> EmailMessage:
    """
    Create and save an inbound email message.
    
    Convenience function that creates the message with the next
    sequence number and saves it to the thread.
    
    Args:
        thread_id: Composite thread ID
        subject: Email subject
        body_text: Plain text body
        message_id: Email message ID
        email_from: Sender address (provider)
        email_to: Recipient address (system)
        body_html: Optional HTML body
        in_reply_to: Optional parent message ID
        attachments: Optional list of attachments
        metadata: Optional additional metadata
        
    Returns:
        Created and saved EmailMessage
    """
    sequence_number = get_next_sequence_number(thread_id)
    
    message = EmailMessage(
        thread_id=thread_id,
        sequence_number=sequence_number,
        direction=EmailDirection.INBOUND,
        timestamp=int(time.time()),
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        message_id=message_id,
        in_reply_to=in_reply_to,
        email_from=email_from,
        email_to=email_to,
        message_type="provider_response",
        attachments=attachments or [],
        metadata=metadata or {},
    )
    
    save_email_to_thread(message)
    return message
