"""
Lambda Handler Wrapper for Communication Agent

This module provides the AWS Lambda entry point for the Communication agent.
It wraps the agent's event handler functions for Lambda execution.
"""

import json
import structlog
from typing import Any

from agents.communication.agent import (
    handle_send_message_requested,
    handle_reply_to_provider_requested,
)

log = structlog.get_logger()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler for Communication agent.
    
    Handles EventBridge events:
    - SendMessageRequested: Initial outreach or follow-up emails
    - ReplyToProviderRequested: Reply to provider responses
    
    Args:
        event: EventBridge event (or direct invocation payload)
        context: Lambda context
        
    Returns:
        Dict with statusCode and body
    """
    detail_type = event.get("detail-type", "SendMessageRequested")
    
    log.info(
        "communication_lambda_invoked",
        event_source=event.get("source"),
        detail_type=detail_type,
    )
    
    try:
        detail = event.get("detail", event)
        
        # Route to appropriate handler based on event type
        if detail_type == "ReplyToProviderRequested":
            result = handle_reply_to_provider_requested(detail_type, detail)
        else:
            # Default to SendMessageRequested
            result = handle_send_message_requested(detail_type, detail)
        
        log.info(
            "communication_lambda_success",
            campaign_id=result.campaign_id,
            provider_id=result.provider_id,
            email_sent=result.email_sent,
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": True,
                "campaign_id": result.campaign_id,
                "provider_id": result.provider_id,
                "email_sent": result.email_sent,
                "message_id": result.message_id,
            }),
        }
        
    except Exception as e:
        log.error(
            "communication_lambda_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        
        return {
            "statusCode": 500,
            "body": json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }),
        }
