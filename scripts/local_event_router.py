"""
Local Event Router

Routes events in-process instead of using EventBridge.
Used for local development and testing.

Events emitted during handler execution (re-entrant calls) are deferred
to a queue and processed sequentially after the current handler completes.
This mirrors AWS EventBridge behaviour where events are delivered
asynchronously and handlers never nest.
"""

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from agents.shared.models.events import BaseEvent

log = structlog.get_logger()

# In-memory event queue for UI (SSE stream)
event_queue: list[dict[str, Any]] = []

# --- Deferred-event queue ---------------------------------------------------
# When a handler emits a new event (e.g. mock Textract emitting
# DocumentProcessed inside handle_provider_response_received), the event is
# appended here instead of being processed immediately.  After the top-level
# handler returns and its state is saved, the queue is drained one event at a
# time — exactly like EventBridge in production.
_deferred_queue: list[tuple[str, dict[str, Any]]] = []
_handling: bool = False


def local_event_router(detail_type: str, detail: dict[str, Any]) -> Any:
    """
    Route event to appropriate agent handler.

    If called while another handler is already executing (re-entrant),
    the event is queued and processed after the current handler completes.
    This mirrors AWS EventBridge behaviour where events are never nested.

    Args:
        detail_type: EventBridge detail-type
        detail: Event detail payload

    Returns:
        Handler result or None
    """
    global _handling

    if _handling:
        # Re-entrant call — queue for processing after the current handler
        _deferred_queue.append((detail_type, detail))
        log.warning(
            "event_deferred",
            detail_type=detail_type,
            campaign_id=detail.get("campaign_id"),
            queue_depth=len(_deferred_queue),
        )
        return None

    _handling = True
    try:
        result = _route_and_handle(detail_type, detail)

        # Drain events that were emitted during handling.
        # Each handler may itself emit more events — they also get queued
        # and are picked up on subsequent iterations.
        if _deferred_queue:
            log.warning(
                "deferred_queue_drain_start",
                queue_size=len(_deferred_queue),
                events=[dt for dt, _ in _deferred_queue],
            )
        while _deferred_queue:
            deferred_type, deferred_detail = _deferred_queue.pop(0)
            log.warning(
                "processing_deferred_event",
                detail_type=deferred_type,
                campaign_id=deferred_detail.get("campaign_id"),
            )
            _route_and_handle(deferred_type, deferred_detail)

        return result
    finally:
        _handling = False


def _route_and_handle(detail_type: str, detail: dict[str, Any]) -> Any:
    """
    Execute a single event through its handler.

    This is the core routing logic, extracted so it can be called both for
    the initial event and for each deferred event without re-entry guards.
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

    def handle_screening_completed(detail_type: str, detail: dict[str, Any]) -> None:
        """
        Handle ScreeningCompleted event.

        This is a no-op handler that allows the post-handler logic to run.
        The actual work (confirmation email, campaign completion) is done
        in the post-handler block below.
        """
        log.info("screening_completed_received", detail=detail)
        return None

    handlers = {
        "NewCampaignRequested": handle_new_campaign_requested,
        "SendMessageRequested": handle_send_message_requested,
        "ProviderResponseReceived": handle_provider_response_received,
        "DocumentProcessed": handle_document_processed,
        "ReplyToProviderRequested": handle_reply_to_provider_requested,
        "FollowUpTriggered": handle_send_message_requested,  # Same handler
        "ScreeningCompleted": handle_screening_completed,
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
        campaign_id=campaign_id,
    )

    try:
        result = handler(detail_type, detail)
        log.warning(
            "event_handled_ok",
            detail_type=detail_type,
            campaign_id=campaign_id,
        )

        # Handle ScreeningCompleted -> trigger confirmation email + check campaign status
        if detail_type == "ScreeningCompleted":
            decision = detail.get("decision")
            if decision == "QUALIFIED":
                _trigger_qualified_confirmation(detail)
            # Check if all providers are in terminal states -> mark campaign COMPLETED
            _check_campaign_completion(detail.get("campaign_id"))

        return result
    except Exception as e:
        log.warning(
            "event_handler_FAILED",
            detail_type=detail_type,
            error=str(e),
            error_type=type(e).__name__,
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
