"""
ProcessInboundEmail Lambda Handler

Main entry point for processing inbound provider emails.
Parses SNS→SES notifications and emits ProviderResponseReceived events.

Trigger: SNS topic subscribed to SES inbound email rule
Output: EventBridge ProviderResponseReceived event

Flow:
1. Parse SNS notification
2. Extract email content (embedded or from S3)
3. Decode campaign_id and provider_id from Reply-To
4. Store attachments to S3
5. Emit ProviderResponseReceived event to EventBridge
"""

import json
import os
import time
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError

from lambdas.process_inbound_email.attachment_handler import (
    AttachmentInfo,
    fetch_email_from_s3,
    process_attachments,
)
from lambdas.process_inbound_email.email_parser import (
    EmailParseResult,
    extract_email_body,
    parse_ses_notification,
)

# Email thread imports for Phase 4 LLM Enhancement
from agents.shared.tools.email_thread import (
    create_thread_id,
    create_inbound_message,
)
from agents.shared.models.email_thread import EmailAttachment
from agents.shared.tools.dynamodb import load_provider_state

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()

# Environment configuration
EVENTBRIDGE_BUS_NAME = os.environ.get("RECRUITMENT_EVENTBRIDGE_BUS_NAME", "recruitment")
EVENTBRIDGE_SOURCE = os.environ.get(
    "RECRUITMENT_EVENTBRIDGE_SOURCE", "recruitment.lambdas.process_inbound_email"
)


def _get_eventbridge_client():
    """Get EventBridge client."""
    region = os.environ.get("AWS_REGION", "us-west-2")
    endpoint_url = os.environ.get("RECRUITMENT_EVENTBRIDGE_ENDPOINT_URL")

    if endpoint_url:
        return boto3.client("events", endpoint_url=endpoint_url, region_name=region)
    return boto3.client("events", region_name=region)


def _build_provider_response_event(
    parse_result: EmailParseResult,
    attachments: list[AttachmentInfo],
    email_thread_id: str,
    trace_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Build ProviderResponseReceived event payload.

    Matches schema in contracts/events.json.
    
    Args:
        parse_result: Parsed email content
        attachments: Stored attachment info
        email_thread_id: Composite thread ID (campaign#market#provider)
        trace_context: Optional trace context for distributed tracing
    """
    event_detail = {
        "campaign_id": parse_result.campaign_id,
        "provider_id": parse_result.provider_id,
        "body": parse_result.body,
        "attachments": [att.to_dict() for att in attachments],
        "received_at": int(time.time()),
        "email_thread_id": email_thread_id,
        "from_address": parse_result.from_address,
        "subject": parse_result.subject,
    }

    if trace_context:
        event_detail["trace_context"] = trace_context

    return event_detail


def _emit_event(detail: dict[str, Any]) -> str:
    """
    Emit ProviderResponseReceived event to EventBridge.

    Returns:
        EventBridge event ID

    Raises:
        RuntimeError: If event publication fails
    """
    client = _get_eventbridge_client()

    log.info(
        "emitting_event",
        detail_type="ProviderResponseReceived",
        campaign_id=detail.get("campaign_id"),
        provider_id=detail.get("provider_id"),
    )

    try:
        response = client.put_events(
            Entries=[
                {
                    "EventBusName": EVENTBRIDGE_BUS_NAME,
                    "Source": EVENTBRIDGE_SOURCE,
                    "DetailType": "ProviderResponseReceived",
                    "Detail": json.dumps(detail),
                }
            ]
        )
    except ClientError as e:
        log.error("eventbridge_put_failed", error=str(e))
        raise RuntimeError(f"Failed to emit event: {e}") from e

    # Check for failed entries
    if response.get("FailedEntryCount", 0) > 0:
        failed = response["Entries"][0]
        error_msg = f"EventBridge entry failed: {failed.get('ErrorMessage')}"
        log.error(
            "eventbridge_entry_failed",
            error_code=failed.get("ErrorCode"),
            error_message=failed.get("ErrorMessage"),
        )
        raise RuntimeError(error_msg)

    event_id = response["Entries"][0]["EventId"]
    log.info("event_emitted", event_id=event_id)

    return event_id


def _get_thread_id_for_provider(
    campaign_id: str,
    provider_id: str,
) -> tuple[str, str | None]:
    """
    Get composite thread ID for a provider by loading their state.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        
    Returns:
        Tuple of (thread_id, market) where market may be None if state not found
        
    Note:
        If provider state is not found, uses 'unknown' as the market.
        The Screening Agent MUST update the thread ID when processing
        if the provider state exists with a real market.
    """
    try:
        provider_state = load_provider_state(campaign_id, provider_id)
        if provider_state:
            market = provider_state.provider_market
            thread_id = create_thread_id(
                campaign_id=campaign_id,
                market_id=market,
                provider_id=provider_id,
            )
            return thread_id, market
        else:
            log.warning(
                "provider_state_not_found_for_thread_id",
                campaign_id=campaign_id,
                provider_id=provider_id,
                action="using_unknown_market_fallback",
                note="Screening agent must reconcile thread ID if provider state exists",
            )
    except Exception as e:
        log.warning(
            "failed_to_load_provider_state_for_thread_id",
            campaign_id=campaign_id,
            provider_id=provider_id,
            error=str(e),
            action="using_unknown_market_fallback",
        )
    
    # Fallback: use a deterministic but generic thread ID
    # IMPORTANT: 'unknown' signals that the Screening Agent should:
    # 1. Load the actual provider state
    # 2. Create/update thread with correct market if different
    # 3. Migrate any 'unknown' thread messages to the correct thread
    thread_id = create_thread_id(
        campaign_id=campaign_id,
        market_id="unknown",  # Signals thread needs reconciliation
        provider_id=provider_id,
    )
    return thread_id, None


def _save_inbound_email_to_thread(
    parse_result: EmailParseResult,
    attachments: list[AttachmentInfo],
    thread_id: str,
) -> bool:
    """
    Save inbound email to thread history for LLM context.
    
    Args:
        parse_result: Parsed email content
        attachments: Stored attachment info
        thread_id: Pre-computed composite thread ID
        
    Returns:
        True if saved successfully, False otherwise
    """
    try:
        
        # Convert attachments to EmailAttachment objects
        email_attachments = [
            EmailAttachment(
                filename=att.original_filename,
                content_type=att.content_type,
                s3_path=att.s3_path,
                size_bytes=att.size_bytes,
            )
            for att in attachments
        ]
        
        # Determine the "to" address (system address that received the email)
        email_to = (
            parse_result.to_addresses[0] 
            if parse_result.to_addresses 
            else "recruitment@system.example.com"
        )
        
        # create_inbound_message saves the message internally
        email_message = create_inbound_message(
            thread_id=thread_id,
            subject=parse_result.subject or "",
            body_text=parse_result.body,
            message_id=parse_result.message_id,
            email_from=parse_result.from_address,
            email_to=email_to,
            in_reply_to=parse_result.in_reply_to,
            attachments=email_attachments if email_attachments else None,
        )
        
        log.debug(
            "inbound_email_saved_to_thread",
            thread_id=thread_id,
            message_id=parse_result.message_id,
            subject=parse_result.subject[:50] if parse_result.subject else None,
        )
        
        return True
        
    except Exception as e:
        # Non-fatal: log the error but don't fail the Lambda
        log.warning(
            "failed_to_save_inbound_email_to_thread",
            error=str(e),
            campaign_id=parse_result.campaign_id,
            provider_id=parse_result.provider_id,
        )
        return False


def _extract_s3_reference(sns_message: dict) -> tuple[str, str] | None:
    """
    Extract S3 bucket/key from SES action if email is stored in S3.

    Returns:
        Tuple of (bucket, key) or None if embedded
    """
    receipt = sns_message.get("receipt", {})
    action = receipt.get("action", {})

    if action.get("type") == "S3":
        return action.get("bucketName"), action.get(
            "objectKey", action.get("objectKeyPrefix", "")
        )

    return None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler for processing inbound emails.

    Args:
        event: SNS event containing SES notification
        context: Lambda context

    Returns:
        Response dict with processing status
    """
    request_id = getattr(context, "aws_request_id", "local")

    log.info(
        "processing_inbound_email",
        request_id=request_id,
        event_keys=list(event.keys()),
    )

    try:
        # Handle SNS Records format (Lambda trigger)
        if "Records" in event:
            for record in event["Records"]:
                # Each record is an SNS message
                response = _process_sns_record(record, request_id)
            return response

        # Handle direct SNS message (for testing)
        if "Message" in event:
            return _process_sns_message(json.loads(event["Message"]), request_id)

        # Handle raw SES notification (for testing)
        if "mail" in event or "content" in event:
            return _process_sns_message(event, request_id)

        log.error("unknown_event_format", event_keys=list(event.keys()))
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Unknown event format"}),
        }

    except Exception as e:
        log.error("lambda_handler_failed", error=str(e), exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }


def _process_sns_record(record: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Process a single SNS record from Lambda event."""
    sns_data = record.get("Sns", {})
    message = sns_data.get("Message", "{}")

    try:
        sns_message = json.loads(message)
    except json.JSONDecodeError as e:
        log.error("sns_message_parse_failed", error=str(e))
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid SNS message JSON"}),
        }

    return _process_sns_message(sns_message, request_id)


def _process_sns_message(
    sns_message: dict[str, Any], request_id: str
) -> dict[str, Any]:
    """
    Process SES notification from SNS.

    Handles both embedded content and S3 reference modes.
    """
    # Check notification type
    notification_type = sns_message.get("notificationType")

    # Handle bounce/complaint notifications
    if notification_type in ("Bounce", "Complaint"):
        log.info(
            "received_delivery_notification",
            type=notification_type,
            message_id=sns_message.get("mail", {}).get("messageId"),
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "status": "skipped",
                    "reason": f"{notification_type} notification - not a provider response",
                }
            ),
        }

    # Check if email is in S3
    s3_ref = _extract_s3_reference(sns_message)

    if s3_ref:
        bucket, key = s3_ref
        log.info("email_stored_in_s3", bucket=bucket, key=key)

        try:
            raw_email = fetch_email_from_s3(bucket, key)
            parse_result = extract_email_body(raw_email)
        except ClientError as e:
            log.error("s3_fetch_failed", bucket=bucket, key=key, error=str(e))
            return {
                "statusCode": 500,
                "body": json.dumps({"error": f"Failed to fetch email from S3: {e}"}),
            }
    else:
        # Parse embedded content
        try:
            parse_result = parse_ses_notification(sns_message)
        except ValueError as e:
            # This shouldn't happen if S3 check worked, but handle it
            log.error("parse_ses_notification_failed", error=str(e))
            return {
                "statusCode": 500,
                "body": json.dumps({"error": str(e)}),
            }

    # Validate we have identifiers
    if not parse_result.campaign_id or not parse_result.provider_id:
        log.warning(
            "missing_identifiers",
            from_address=parse_result.from_address,
            to_addresses=parse_result.to_addresses,
            parse_errors=parse_result.parse_errors,
        )
        return {
            "statusCode": 400,
            "body": json.dumps(
                {
                    "error": "Could not identify campaign/provider from email addressing",
                    "details": parse_result.parse_errors,
                }
            ),
        }

    log.info(
        "email_parsed",
        campaign_id=parse_result.campaign_id,
        provider_id=parse_result.provider_id,
        from_address=parse_result.from_address,
        subject=parse_result.subject,
        body_length=len(parse_result.body),
        attachment_count=len(parse_result.attachments),
    )

    # Validate email body is not empty
    if not parse_result.body.strip():
        log.warning(
            "empty_email_body",
            campaign_id=parse_result.campaign_id,
            provider_id=parse_result.provider_id,
            from_address=parse_result.from_address,
            subject=parse_result.subject,
            has_attachments=len(parse_result.attachments) > 0,
        )
        # Continue processing - attachment-only emails are valid
        # Screening Agent will handle empty body classification

    # Process attachments
    stored_attachments: list[AttachmentInfo] = []

    if parse_result.attachments:
        stored, failed = process_attachments(
            parse_result.attachments,
            parse_result.campaign_id,
            parse_result.provider_id,
            continue_on_error=True,
        )
        stored_attachments = stored

        if failed:
            log.warning(
                "some_attachments_failed",
                failed_count=len(failed),
                failed_files=[f[0] for f in failed],
            )

    # Get composite thread ID once and use consistently
    # This ensures thread history and event both use the same ID
    thread_id, market = _get_thread_id_for_provider(
        parse_result.campaign_id,
        parse_result.provider_id,
    )
    
    if market is None:
        log.warning(
            "provider_state_missing_on_inbound",
            campaign_id=parse_result.campaign_id,
            provider_id=parse_result.provider_id,
            thread_id=thread_id,
            note="Thread ID uses 'pending' market - screening agent should handle",
        )
    
    # Save inbound email to thread history (for LLM context)
    # This is non-blocking - failure doesn't prevent event emission
    thread_saved = _save_inbound_email_to_thread(parse_result, stored_attachments, thread_id)

    # Build and emit event with consistent thread_id
    event_detail = _build_provider_response_event(
        parse_result,
        stored_attachments,
        email_thread_id=thread_id,
        trace_context={"trace_id": request_id.replace("-", "")[:32].ljust(32, "0")},
    )

    event_id = _emit_event(event_detail)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "status": "processed",
                "event_id": event_id,
                "campaign_id": parse_result.campaign_id,
                "provider_id": parse_result.provider_id,
                "attachments_stored": len(stored_attachments),
                "thread_saved": thread_saved,
            }
        ),
    }
