"""
Lambda Handler Wrapper for Campaign Planner Agent

This module provides the AWS Lambda entry point for the Campaign Planner agent.
It wraps the agent's event handler function for Lambda execution.
"""

import json
import structlog
from typing import Any

from agents.campaign_planner.agent import handle_new_campaign_requested

log = structlog.get_logger()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler for Campaign Planner agent.
    
    Handles EventBridge events of type 'NewCampaignRequested'.
    
    Args:
        event: EventBridge event (or direct invocation payload)
        context: Lambda context
        
    Returns:
        Dict with statusCode and body
    """
    log.info(
        "campaign_planner_lambda_invoked",
        event_source=event.get("source"),
        detail_type=event.get("detail-type"),
    )
    
    try:
        # Extract detail-type and detail from EventBridge event
        detail_type = event.get("detail-type", "NewCampaignRequested")
        detail = event.get("detail", event)
        
        # Handle the event
        result = handle_new_campaign_requested(detail_type, detail)
        
        # Calculate markets_processed from providers_by_market
        markets_processed = len(result.providers_by_market)
        
        log.info(
            "campaign_planner_lambda_success",
            campaign_id=result.campaign_id,
            providers_selected=result.total_providers_selected,
            markets_processed=markets_processed,
            events_emitted=result.events_emitted,
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": result.success,
                "campaign_id": result.campaign_id,
                "total_providers_selected": result.total_providers_selected,
                "markets_processed": markets_processed,
                "events_emitted": result.events_emitted,
                "records_created": result.records_created,
                "errors": result.errors,
            }),
        }
        
    except Exception as e:
        log.error(
            "campaign_planner_lambda_error",
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
