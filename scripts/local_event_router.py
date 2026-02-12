"""
Local Event Router

Routes events in-process instead of using EventBridge.
Used for local development and testing.
"""

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from agents.shared.models.events import BaseEvent

log = structlog.get_logger()

# In-memory event queue for UI
event_queue: list[dict[str, Any]] = []


def local_event_router(detail_type: str, detail: dict[str, Any]) -> Any:
    """
    Route event to appropriate agent handler.

    Args:
        detail_type: EventBridge detail-type
        detail: Event detail payload

    Returns:
        Handler result or None
    """
    # Lazy imports to avoid circular dependencies
    from agents.campaign_planner.agent import handle_new_campaign_requested
    from agents.communication.agent import (
        handle_reply_to_provider_requested,
        handle_send_message_requested,
    )
    from agents.screening.agent import (
        handle_document_processed,
        handle_provider_response_received,
    )

    handlers = {
        "NewCampaignRequested": handle_new_campaign_requested,
        "SendMessageRequested": handle_send_message_requested,
        "ProviderResponseReceived": handle_provider_response_received,
        "DocumentProcessed": handle_document_processed,
        "ReplyToProviderRequested": handle_reply_to_provider_requested,
        "FollowUpTriggered": handle_send_message_requested,  # Same handler
    }

    handler = handlers.get(detail_type)
    if not handler:
        log.warning("no_handler_for_event", detail_type=detail_type)
        return None

    # Log event to in-memory queue and persist to DynamoDB
    timestamp_iso = datetime.now(timezone.utc).isoformat()
    campaign_id = detail.get("campaign_id")
    provider_id = detail.get("provider_id")

    event_entry = {
        "type": detail_type,
        "detail": detail,
        "campaign_id": campaign_id,
        "provider_id": provider_id,
        "timestamp": timestamp_iso,
    }
    event_queue.append(event_entry)

    # Persist event to DynamoDB
    if campaign_id:
        try:
            from agents.shared.tools.dynamodb import save_event_record

            save_event_record(
                campaign_id=campaign_id,
                event_type=detail_type,
                detail=detail,
                timestamp=timestamp_iso,
                provider_id=provider_id,
            )
        except Exception as persist_err:
            log.debug("event_persist_failed", error=str(persist_err))

    log.info(
        "routing_event",
        detail_type=detail_type,
        campaign_id=detail.get("campaign_id"),
    )

    try:
        result = handler(detail_type, detail)
        log.info("event_handled", detail_type=detail_type, success=True)

        # Handle ScreeningCompleted -> trigger confirmation email + check campaign status
        if detail_type == "ScreeningCompleted":
            decision = detail.get("decision")
            if decision == "QUALIFIED":
                _trigger_qualified_confirmation(detail)
            # Check if all providers are in terminal states -> mark campaign COMPLETED
            _check_campaign_completion(detail.get("campaign_id"))

        return result
    except Exception as e:
        log.error(
            "event_handler_failed",
            detail_type=detail_type,
            error=str(e),
            exc_info=True,
        )
        # Don't re-raise to keep the system running
        return None


def _check_campaign_completion(campaign_id: str | None) -> None:
    """Check if all providers in a campaign are in terminal states."""
    if not campaign_id:
        return
    try:
        from agents.shared.tools.dynamodb import (
            list_campaign_providers,
            update_campaign_status,
        )
        from agents.shared.models.dynamo import CampaignStatus

        providers = list_campaign_providers(campaign_id)
        if not providers:
            return
        
        terminal_statuses = {"QUALIFIED", "REJECTED"}
        all_terminal = all(p.status.value in terminal_statuses for p in providers)
        
        if all_terminal:
            update_campaign_status(campaign_id, CampaignStatus.COMPLETED)
            log.info("campaign_marked_completed", campaign_id=campaign_id)
    except Exception as e:
        log.debug("campaign_completion_check_failed", error=str(e))


def _trigger_qualified_confirmation(screening_detail: dict[str, Any]) -> None:
    """Trigger confirmation email after qualification."""
    campaign_id = screening_detail["campaign_id"]
    provider_id = screening_detail["provider_id"]

    # Load provider state to get email
    from agents.shared.tools.dynamodb import load_provider_state

    provider_state = load_provider_state(campaign_id, provider_id)

    if not provider_state:
        log.warning(
            "provider_state_not_found_for_confirmation",
            campaign_id=campaign_id,
            provider_id=provider_id,
        )
        return

    from agents.shared.models.events import (
        MessageType,
        SendMessageRequestedEvent,
    )

    # Emit SendMessageRequested for confirmation
    confirmation_event = SendMessageRequestedEvent(
        campaign_id=campaign_id,
        provider_id=provider_id,
        provider_email=provider_state.provider_email,
        provider_name=provider_state.provider_name,
        provider_market=provider_state.provider_market,
        message_type=MessageType.QUALIFIED_CONFIRMATION,
        template_data=None,
    )

    local_event_router(
        "SendMessageRequested", confirmation_event.to_eventbridge_detail()
    )


def patch_eventbridge():
    """
    Monkey-patch EventBridge tools to route locally.

    Call this before importing agents to ensure all event emissions
    are routed through local_event_router.
    """
    from agents.shared.tools import eventbridge as eb_module

    original_send_event = eb_module.send_event
    original_send_events_batch = eb_module.send_events_batch

    def patched_send_event(event: BaseEvent, **kwargs) -> str:
        """Patched send_event that routes locally."""
        detail_type = event.detail_type()
        detail = event.to_eventbridge_detail()
        local_event_router(detail_type, detail)
        return f"local-event-{detail_type}-{detail.get('campaign_id', 'unknown')}"

    def patched_send_events_batch(events: list[BaseEvent], **kwargs) -> list[str]:
        """Patched send_events_batch that routes locally."""
        event_ids = []
        for event in events:
            detail_type = event.detail_type()
            detail = event.to_eventbridge_detail()
            local_event_router(detail_type, detail)
            event_ids.append(
                f"local-event-{detail_type}-{detail.get('campaign_id', 'unknown')}"
            )
        return event_ids

    eb_module.send_event = patched_send_event
    eb_module.send_events_batch = patched_send_events_batch

    log.info("eventbridge_patched_for_local_mode")


def get_event_queue() -> list[dict[str, Any]]:
    """Get current event queue (for API endpoints)."""
    return event_queue.copy()


def clear_event_queue() -> None:
    """Clear event queue (for testing)."""
    event_queue.clear()
