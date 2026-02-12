"""
ProcessInboundEmail Lambda

Processes inbound provider emails received via SES → SNS.
Parses email content, stores attachments to S3, and emits ProviderResponseReceived events.

Flow:
    Provider Reply
    → SES Receipt Rule
    → SNS Topic
    → This Lambda
    → EventBridge: ProviderResponseReceived
"""

from lambdas.process_inbound_email.attachment_handler import (
    AttachmentInfo,
    process_attachments,
    store_attachment,
)
from lambdas.process_inbound_email.email_parser import (
    EmailParseResult,
    extract_email_body,
    parse_ses_notification,
)
from lambdas.process_inbound_email.handler import lambda_handler

__all__ = [
    "AttachmentInfo",
    "EmailParseResult",
    "extract_email_body",
    "lambda_handler",
    "parse_ses_notification",
    "process_attachments",
    "store_attachment",
]
