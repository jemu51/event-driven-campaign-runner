# Shared Tools
"""
Tool implementations for agents.

All tools are idempotent and designed for use with Strands AI framework.
"""

from agents.shared.tools.dynamodb import (
    load_provider_state,
    create_provider_record,
    update_provider_state,
    list_campaign_providers,
    find_dormant_sessions,
)
from agents.shared.tools.eventbridge import (
    send_event,
    send_events_batch,
)
from agents.shared.tools.email import (
    encode_reply_to,
    decode_reply_to,
    send_ses_email,
)
from agents.shared.tools.s3 import (
    upload_document,
    download_document,
    list_documents,
    get_document_url,
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

__all__ = [
    # DynamoDB tools
    "load_provider_state",
    "create_provider_record",
    "update_provider_state",
    "list_campaign_providers",
    "find_dormant_sessions",
    # EventBridge tools
    "send_event",
    "send_events_batch",
    # Email tools
    "encode_reply_to",
    "decode_reply_to",
    "send_ses_email",
    # S3 tools
    "upload_document",
    "download_document",
    "list_documents",
    "get_document_url",
    # Email Thread tools
    "create_thread_id",
    "parse_thread_id",
    "save_email_to_thread",
    "load_thread_history",
    "get_thread",
    "get_next_sequence_number",
    "format_thread_for_context",
    "create_outbound_message",
    "create_inbound_message",
    "get_thread_summary",
]
