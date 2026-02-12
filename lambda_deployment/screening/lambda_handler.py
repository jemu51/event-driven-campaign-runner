"""
Lambda Handler Wrapper for Screening Agent

This module provides the AWS Lambda entry point for the Screening agent.
It wraps the agent's event handler functions for Lambda execution.
"""

import json
import structlog
from typing import Any

from agents.screening.agent import (
    handle_provider_response_received,
    handle_document_processed,
)

log = structlog.get_logger()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler for Screening agent.
    
    Handles EventBridge events:
    - ProviderResponseReceived: Classify and evaluate provider email responses
    - DocumentProcessed: Evaluate processed documents (insurance, etc.)
    
    Args:
        event: EventBridge event (or direct invocation payload)
        context: Lambda context
        
    Returns:
        Dict with statusCode and body
    """
    detail_type = event.get("detail-type", "ProviderResponseReceived")
    
    log.info(
        "screening_lambda_invoked",
        event_source=event.get("source"),
        detail_type=detail_type,
    )
    
    try:
        detail = event.get("detail", event)
        
        # Route to appropriate handler based on event type
        if detail_type == "DocumentProcessed":
            result = handle_document_processed(detail_type, detail)
        else:
            # Default to ProviderResponseReceived
            result = handle_provider_response_received(detail_type, detail)
        
        log.info(
            "screening_lambda_success",
            campaign_id=result.campaign_id,
            provider_id=result.provider_id,
            decision=result.decision.value if result.decision else None,
            reasoning=result.reasoning,
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": True,
                "campaign_id": result.campaign_id,
                "provider_id": result.provider_id,
                "decision": result.decision.value if result.decision else None,
                "reasoning": result.reasoning,
                "next_action": result.next_action,
                "equipment_confirmed": result.equipment_confirmed,
                "equipment_missing": result.equipment_missing,
                "documents_valid": result.documents_valid,
            }),
        }
        
    except Exception as e:
        log.error(
            "screening_lambda_error",
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
