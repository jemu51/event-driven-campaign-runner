"""
Campaign Planner Agent

Event handler for NewCampaignRequested events.
Orchestrates provider selection and initial outreach.

This agent:
1. Receives NewCampaignRequested events
2. Selects providers per market based on requirements
3. Creates DynamoDB records (status=INVITED)
4. Emits SendMessageRequested events
5. Exits immediately

Following agent principles:
- No waiting or loops
- State persisted to DynamoDB before exit
- Events are the only communication mechanism
"""

from typing import Any

import structlog

from agents.campaign_planner.config import get_campaign_planner_config
from agents.campaign_planner.models import (
    CampaignRequirements,
    PlanningResult,
    ProviderInfo,
)
from agents.campaign_planner.prompts import get_system_prompt
from agents.campaign_planner.tools import (
    batch_create_provider_records,
    build_send_message_events,
    emit_send_message_events,
    parse_campaign_requirements,
    select_providers,
)
from agents.shared.exceptions import RecruitmentError
from agents.shared.models.events import (
    NewCampaignRequestedEvent,
    TraceContext,
    parse_event,
)

log = structlog.get_logger()


class CampaignPlanningError(RecruitmentError):
    """Error during campaign planning."""
    
    def __init__(
        self,
        message: str,
        campaign_id: str,
        *,
        errors: list[str] | None = None,
    ):
        super().__init__(message, campaign_id=campaign_id)
        self.campaign_id = campaign_id
        self.errors = errors or []


def handle_new_campaign_requested(
    detail_type: str,
    detail: dict[str, Any],
) -> PlanningResult:
    """
    Handle NewCampaignRequested event.
    
    This is the main entry point for the Campaign Planner agent.
    Called when EventBridge delivers a NewCampaignRequested event.
    
    Args:
        detail_type: EventBridge detail-type (should be "NewCampaignRequested")
        detail: Event detail payload
        
    Returns:
        PlanningResult with summary of actions taken
        
    Raises:
        CampaignPlanningError: If planning fails
        ValidationError: If event payload is invalid
    """
    log.info(
        "campaign_planner_invoked",
        detail_type=detail_type,
    )
    
    # 1. Parse and validate event
    event = parse_event(detail_type, detail)
    if not isinstance(event, NewCampaignRequestedEvent):
        raise CampaignPlanningError(
            f"Unexpected event type: {detail_type}",
            campaign_id=detail.get("campaign_id", "unknown"),
        )
    
    log.info(
        "event_received",
        campaign_id=event.campaign_id,
        buyer_id=event.buyer_id,
        markets=event.requirements.markets,
        providers_per_market=event.requirements.providers_per_market,
    )
    
    # 2. Parse requirements into agent model
    requirements = parse_campaign_requirements(
        campaign_id=event.campaign_id,
        buyer_id=event.buyer_id,
        requirements=event.requirements,
    )
    
    log.info(
        "requirements_parsed",
        campaign_id=requirements.campaign_id,
        campaign_type=requirements.campaign_type,
        total_providers_needed=requirements.total_providers_needed,
        required_equipment=requirements.required_equipment,
        required_documents=requirements.required_documents,
        travel_required=requirements.travel_required,
    )
    
    # 3. Select providers for each market
    all_providers: list[ProviderInfo] = []
    providers_by_market: dict[str, list[ProviderInfo]] = {}
    errors: list[str] = []
    
    for market in requirements.markets:
        try:
            selection = select_providers(requirements, market)
            all_providers.extend(selection.providers)
            providers_by_market[market] = selection.providers
            
            if len(selection.providers) < requirements.providers_per_market:
                errors.append(
                    f"Market {market}: Only {len(selection.providers)} of "
                    f"{requirements.providers_per_market} providers available"
                )
        except Exception as e:
            log.error(
                "provider_selection_failed",
                market=market,
                error=str(e),
            )
            errors.append(f"Market {market}: Selection failed - {str(e)}")
    
    if not all_providers:
        raise CampaignPlanningError(
            "No providers selected for any market",
            campaign_id=requirements.campaign_id,
            errors=errors,
        )
    
    log.info(
        "providers_selected",
        campaign_id=requirements.campaign_id,
        total_selected=len(all_providers),
        by_market={m: len(p) for m, p in providers_by_market.items()},
    )
    
    # 4. Create DynamoDB records (status=INVITED)
    try:
        created_records = batch_create_provider_records(
            campaign_id=requirements.campaign_id,
            providers=all_providers,
            required_documents=requirements.required_documents,
        )
    except Exception as e:
        log.error(
            "dynamodb_records_failed",
            campaign_id=requirements.campaign_id,
            error=str(e),
        )
        raise CampaignPlanningError(
            f"Failed to create provider records: {str(e)}",
            campaign_id=requirements.campaign_id,
            errors=errors,
        ) from e
    
    log.info(
        "dynamodb_records_created",
        campaign_id=requirements.campaign_id,
        count=len(created_records),
    )
    
    # 5. Build and emit SendMessageRequested events
    events = build_send_message_events(
        campaign_id=requirements.campaign_id,
        providers=all_providers,
        requirements=requirements,
        trace_context=event.trace_context,
    )
    
    try:
        event_ids = emit_send_message_events(events)
    except Exception as e:
        log.error(
            "event_emission_failed",
            campaign_id=requirements.campaign_id,
            error=str(e),
        )
        # Let this propagate for DLQ capture - events not sent
        raise CampaignPlanningError(
            f"Failed to emit SendMessageRequested events: {str(e)}",
            campaign_id=requirements.campaign_id,
            errors=errors,
        ) from e
    
    log.info(
        "events_emitted",
        campaign_id=requirements.campaign_id,
        count=len(event_ids),
    )
    
    # 6. Build and return result
    result = PlanningResult(
        campaign_id=requirements.campaign_id,
        total_providers_selected=len(all_providers),
        providers_by_market=providers_by_market,
        events_emitted=len(event_ids),
        records_created=len(created_records),
        errors=errors,
    )
    
    log.info(
        "campaign_planning_complete",
        campaign_id=requirements.campaign_id,
        success=result.success,
        providers_selected=result.total_providers_selected,
        events_emitted=result.events_emitted,
        errors_count=len(result.errors),
    )
    
    # Agent exits here - no waiting, no loops
    return result


# --- Agent Definition for Strands Runtime ---

# System prompt for LLM-based reasoning (if needed)
SYSTEM_PROMPT = get_system_prompt()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda entry point.
    
    This function is invoked by EventBridge via Lambda.
    It extracts the event details and delegates to the handler.
    
    Args:
        event: Lambda event (EventBridge wrapped)
        context: Lambda context object
        
    Returns:
        Handler result as dict
    """
    # EventBridge wraps the event in this structure
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})
    
    log.info(
        "lambda_invoked",
        detail_type=detail_type,
        request_id=getattr(context, "aws_request_id", "local"),
    )
    
    try:
        result = handle_new_campaign_requested(detail_type, detail)
        return result.model_dump()
    except CampaignPlanningError as e:
        log.error(
            "campaign_planning_error",
            campaign_id=e.campaign_id,
            errors=e.errors,
        )
        raise
    except Exception as e:
        log.error(
            "unexpected_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


# For Strands agent runtime
async def strands_handler(event: dict[str, Any]) -> dict[str, Any]:
    """
    Strands agent runtime entry point.
    
    This function is invoked by Strands when an event matches
    the agent's event pattern.
    
    Args:
        event: EventBridge event payload
        
    Returns:
        Handler result as dict
    """
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})
    
    result = handle_new_campaign_requested(detail_type, detail)
    return result.model_dump()
