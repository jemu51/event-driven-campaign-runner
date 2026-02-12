"""
EventBridge Tools

Idempotent tools for publishing events to EventBridge.
Events follow schemas defined in contracts/events.json.
"""

import json
from typing import Any
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
import structlog

from agents.shared.config import get_settings
from agents.shared.exceptions import EventPublishError
from agents.shared.models.events import BaseEvent

log = structlog.get_logger()


def _get_client():
    """Get EventBridge client."""
    settings = get_settings()
    return boto3.client("events", **settings.eventbridge_config)


def send_event(
    event: BaseEvent,
    *,
    source: str | None = None,
    detail_type: str | None = None,
) -> str:
    """
    Publish a single event to EventBridge.
    
    Args:
        event: Event model to publish
        source: Override event source (default: from settings)
        detail_type: Override detail-type (default: from event class)
        
    Returns:
        EventBridge event ID
        
    Raises:
        EventPublishError: If publication fails
    """
    settings = get_settings()
    client = _get_client()
    
    # Determine source and detail-type
    event_source = source or f"{settings.eventbridge_source_prefix}.agents"
    event_detail_type = detail_type or event.detail_type()
    
    # Convert event to JSON
    detail = event.to_eventbridge_detail()
    
    log.info(
        "publishing_event",
        detail_type=event_detail_type,
        campaign_id=event.campaign_id,
        source=event_source,
    )
    
    try:
        response = client.put_events(
            Entries=[
                {
                    "EventBusName": settings.eventbridge_bus_name,
                    "Source": event_source,
                    "DetailType": event_detail_type,
                    "Detail": json.dumps(detail),
                }
            ]
        )
    except ClientError as e:
        log.error(
            "eventbridge_put_failed",
            detail_type=event_detail_type,
            error=str(e),
        )
        raise EventPublishError(
            event_type=event_detail_type,
            error_code=e.response["Error"]["Code"],
            error_message=e.response["Error"]["Message"],
        ) from e
    
    # Check for failed entries
    if response.get("FailedEntryCount", 0) > 0:
        failed = response["Entries"][0]
        log.error(
            "eventbridge_entry_failed",
            detail_type=event_detail_type,
            error_code=failed.get("ErrorCode"),
            error_message=failed.get("ErrorMessage"),
        )
        raise EventPublishError(
            event_type=event_detail_type,
            error_code=failed.get("ErrorCode"),
            error_message=failed.get("ErrorMessage"),
        )
    
    event_id = response["Entries"][0]["EventId"]
    log.info(
        "event_published",
        detail_type=event_detail_type,
        event_id=event_id,
        campaign_id=event.campaign_id,
    )
    
    return event_id


def send_events_batch(
    events: list[BaseEvent],
    *,
    source: str | None = None,
) -> list[str]:
    """
    Publish multiple events to EventBridge in batches.
    
    EventBridge supports max 10 events per request.
    This function handles batching automatically.
    
    Args:
        events: List of events to publish
        source: Override event source for all events
        
    Returns:
        List of EventBridge event IDs (one per successful event)
        
    Raises:
        EventPublishError: If any event fails to publish
    """
    if not events:
        return []
    
    settings = get_settings()
    client = _get_client()
    event_source = source or f"{settings.eventbridge_source_prefix}.agents"
    
    # Build all entries
    entries = []
    for event in events:
        entries.append({
            "EventBusName": settings.eventbridge_bus_name,
            "Source": event_source,
            "DetailType": event.detail_type(),
            "Detail": json.dumps(event.to_eventbridge_detail()),
        })
    
    log.info(
        "publishing_event_batch",
        count=len(events),
        source=event_source,
    )
    
    # Process in batches of 10 (EventBridge limit)
    BATCH_SIZE = 10
    all_event_ids: list[str] = []
    failed_events: list[dict] = []
    
    for i in range(0, len(entries), BATCH_SIZE):
        batch = entries[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        
        log.debug(
            "publishing_batch",
            batch_number=batch_num,
            batch_size=len(batch),
        )
        
        try:
            response = client.put_events(Entries=batch)
        except ClientError as e:
            log.error(
                "eventbridge_batch_failed",
                batch_number=batch_num,
                error=str(e),
            )
            raise EventPublishError(
                event_type="batch",
                error_code=e.response["Error"]["Code"],
                error_message=e.response["Error"]["Message"],
            ) from e
        
        # Collect results
        for j, entry in enumerate(response["Entries"]):
            if "EventId" in entry:
                all_event_ids.append(entry["EventId"])
            else:
                failed_events.append({
                    "index": i + j,
                    "error_code": entry.get("ErrorCode"),
                    "error_message": entry.get("ErrorMessage"),
                })
    
    # Report failures
    if failed_events:
        log.error(
            "some_events_failed",
            failed_count=len(failed_events),
            total_count=len(events),
            failures=failed_events,
        )
        # Raise error for first failure
        first_failure = failed_events[0]
        raise EventPublishError(
            event_type=f"batch[{first_failure['index']}]",
            error_code=first_failure.get("error_code"),
            error_message=first_failure.get("error_message"),
        )
    
    log.info(
        "batch_published",
        count=len(all_event_ids),
    )
    
    return all_event_ids


def send_raw_event(
    detail_type: str,
    detail: dict[str, Any],
    *,
    source: str | None = None,
) -> str:
    """
    Publish a raw event dict to EventBridge.
    
    Use this when you have a dict instead of a typed event model.
    Prefer send_event() with typed models when possible.
    
    Args:
        detail_type: EventBridge detail-type (e.g., "SendMessageRequested")
        detail: Event detail payload
        source: Override event source
        
    Returns:
        EventBridge event ID
        
    Raises:
        EventPublishError: If publication fails
    """
    settings = get_settings()
    client = _get_client()
    event_source = source or f"{settings.eventbridge_source_prefix}.agents"
    
    log.info(
        "publishing_raw_event",
        detail_type=detail_type,
        source=event_source,
    )
    
    try:
        response = client.put_events(
            Entries=[
                {
                    "EventBusName": settings.eventbridge_bus_name,
                    "Source": event_source,
                    "DetailType": detail_type,
                    "Detail": json.dumps(detail),
                }
            ]
        )
    except ClientError as e:
        log.error(
            "eventbridge_put_failed",
            detail_type=detail_type,
            error=str(e),
        )
        raise EventPublishError(
            event_type=detail_type,
            error_code=e.response["Error"]["Code"],
            error_message=e.response["Error"]["Message"],
        ) from e
    
    if response.get("FailedEntryCount", 0) > 0:
        failed = response["Entries"][0]
        raise EventPublishError(
            event_type=detail_type,
            error_code=failed.get("ErrorCode"),
            error_message=failed.get("ErrorMessage"),
        )
    
    return response["Entries"][0]["EventId"]
