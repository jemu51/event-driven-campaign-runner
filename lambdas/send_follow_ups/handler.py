"""
SendFollowUps Lambda Handler

Main entry point for the scheduled follow-up Lambda.
Queries for dormant provider sessions and emits FollowUpTriggered events.

Trigger: EventBridge Scheduled Rule (e.g., cron(0 0 * * ? *) for daily midnight)
Output: EventBridge FollowUpTriggered events

Flow:
1. Parse scheduled event (optional custom parameters)
2. Build dormant session queries for each monitored state
3. Query GSI1 for providers past threshold in each state
4. Calculate follow-up number and reason for each dormant provider
5. Emit FollowUpTriggered events in batches
6. Return summary of follow-ups triggered
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import boto3
import structlog
from botocore.exceptions import ClientError

from lambdas.send_follow_ups.query_builder import (
    DormantSessionQuery,
    FollowUpReason,
    QueryResult,
    build_dormant_session_queries,
    calculate_follow_up_number,
    days_since_contact,
)

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
DYNAMODB_TABLE_NAME = os.environ.get("RECRUITMENT_DYNAMODB_TABLE_NAME", "RecruitmentSessions")
DYNAMODB_GSI1_NAME = os.environ.get("RECRUITMENT_DYNAMODB_GSI1_NAME", "GSI1")
EVENTBRIDGE_BUS_NAME = os.environ.get("RECRUITMENT_EVENTBRIDGE_BUS_NAME", "recruitment")
EVENTBRIDGE_SOURCE = os.environ.get(
    "RECRUITMENT_EVENTBRIDGE_SOURCE", "recruitment.lambdas.send_follow_ups"
)
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

# Follow-up configuration
MAX_FOLLOW_UPS = int(os.environ.get("RECRUITMENT_MAX_FOLLOW_UPS", "3"))
MAX_RESULTS_PER_QUERY = int(os.environ.get("RECRUITMENT_MAX_RESULTS_PER_QUERY", "100"))
EVENTBRIDGE_BATCH_SIZE = 10  # EventBridge limit


def _get_dynamodb_table():
    """Get DynamoDB table resource."""
    endpoint_url = os.environ.get("RECRUITMENT_DYNAMODB_ENDPOINT_URL")
    if endpoint_url:
        dynamodb = boto3.resource("dynamodb", endpoint_url=endpoint_url, region_name=AWS_REGION)
    else:
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return dynamodb.Table(DYNAMODB_TABLE_NAME)


def _get_eventbridge_client():
    """Get EventBridge client."""
    endpoint_url = os.environ.get("RECRUITMENT_EVENTBRIDGE_ENDPOINT_URL")
    if endpoint_url:
        return boto3.client("events", endpoint_url=endpoint_url, region_name=AWS_REGION)
    return boto3.client("events", region_name=AWS_REGION)


@dataclass
class FollowUpEvent:
    """
    A follow-up event to be emitted.
    
    Matches the FollowUpTriggered schema in contracts/events.json.
    """
    
    campaign_id: str
    provider_id: str
    reason: FollowUpReason
    follow_up_number: int
    days_since_last_contact: int
    current_status: str
    trace_context: dict[str, str] | None = None
    
    def to_eventbridge_detail(self) -> dict[str, Any]:
        """Convert to EventBridge detail payload."""
        detail = {
            "campaign_id": self.campaign_id,
            "provider_id": self.provider_id,
            "reason": self.reason.value,
            "follow_up_number": self.follow_up_number,
            "days_since_last_contact": self.days_since_last_contact,
            "current_status": self.current_status,
        }
        if self.trace_context:
            detail["trace_context"] = self.trace_context
        return detail


@dataclass
class FollowUpResult:
    """Summary of follow-up processing."""
    
    queries_executed: int = 0
    queries_succeeded: int = 0
    dormant_providers_found: int = 0
    follow_ups_emitted: int = 0
    follow_ups_skipped: int = 0  # Providers at max follow-ups
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    
    @property
    def succeeded(self) -> bool:
        """Whether processing completed without critical errors."""
        return self.queries_succeeded > 0 or self.queries_executed == 0


def _query_dormant_sessions(
    query: DormantSessionQuery,
    now: datetime,
) -> QueryResult:
    """
    Query DynamoDB GSI1 for dormant sessions matching the query spec.
    
    Args:
        query: Query specification
        now: Current datetime for threshold calculation
        
    Returns:
        QueryResult with matching providers
    """
    table = _get_dynamodb_table()
    threshold = query.get_threshold_timestamp(now)
    
    start_time = time.time()
    result = QueryResult(query=query, threshold_timestamp=threshold)
    
    log.debug(
        "querying_dormant_sessions",
        gsi1pk=query.gsi1pk,
        threshold=threshold,
        threshold_date=datetime.utcfromtimestamp(threshold).isoformat(),
    )
    
    try:
        response = table.query(
            IndexName=DYNAMODB_GSI1_NAME,
            KeyConditionExpression="GSI1PK = :gsi1pk AND last_contacted_at < :threshold",
            ExpressionAttributeValues={
                ":gsi1pk": query.gsi1pk,
                ":threshold": threshold,
            },
            Limit=MAX_RESULTS_PER_QUERY,
        )
        
        result.providers = response.get("Items", [])
        result.query_time_ms = (time.time() - start_time) * 1000
        
        log.info(
            "dormant_sessions_found",
            gsi1pk=query.gsi1pk,
            count=len(result.providers),
            query_time_ms=result.query_time_ms,
        )
        
    except ClientError as e:
        result.error = str(e)
        result.query_time_ms = (time.time() - start_time) * 1000
        log.error(
            "dormant_session_query_failed",
            gsi1pk=query.gsi1pk,
            error=str(e),
        )
    
    return result


def _extract_ids_from_keys(item: dict[str, Any]) -> tuple[str, str]:
    """
    Extract campaign_id and provider_id from DynamoDB item keys.
    
    Args:
        item: DynamoDB item with PK and SK
        
    Returns:
        Tuple of (campaign_id, provider_id)
    """
    pk = item.get("PK", "")
    sk = item.get("SK", "")
    
    # PK format: SESSION#<campaign_id>
    campaign_id = pk.replace("SESSION#", "") if pk.startswith("SESSION#") else pk
    
    # SK format: PROVIDER#<provider_id>
    provider_id = sk.replace("PROVIDER#", "") if sk.startswith("PROVIDER#") else sk
    
    return campaign_id, provider_id


def _build_follow_up_events(
    query_results: list[QueryResult],
    trace_context: dict[str, str] | None = None,
) -> tuple[list[FollowUpEvent], int]:
    """
    Build FollowUpEvent objects from query results.
    
    Calculates follow-up number and filters out providers at max.
    
    Args:
        query_results: Results from dormant session queries
        trace_context: Optional trace context to propagate
        
    Returns:
        Tuple of (list of follow-up events, count of skipped)
    """
    events: list[FollowUpEvent] = []
    skipped = 0
    
    for result in query_results:
        if not result.succeeded:
            continue
        
        for item in result.providers:
            campaign_id, provider_id = _extract_ids_from_keys(item)
            last_contacted = item.get("last_contacted_at", 0)
            current_status = item.get("status", "")
            
            # Calculate follow-up number
            follow_up_num = calculate_follow_up_number(
                last_contacted,
                result.query.days_threshold,
                MAX_FOLLOW_UPS,
            )
            
            # Skip if at max follow-ups
            if follow_up_num > MAX_FOLLOW_UPS:
                log.debug(
                    "provider_at_max_follow_ups",
                    campaign_id=campaign_id,
                    provider_id=provider_id,
                    follow_up_num=follow_up_num,
                )
                skipped += 1
                continue
            
            days_since = days_since_contact(last_contacted)
            
            events.append(
                FollowUpEvent(
                    campaign_id=campaign_id,
                    provider_id=provider_id,
                    reason=result.query.follow_up_reason,
                    follow_up_number=follow_up_num,
                    days_since_last_contact=days_since,
                    current_status=current_status,
                    trace_context=trace_context,
                )
            )
            
            log.debug(
                "follow_up_event_built",
                campaign_id=campaign_id,
                provider_id=provider_id,
                reason=result.query.follow_up_reason.value,
                follow_up_number=follow_up_num,
                days_since_contact=days_since,
            )
    
    return events, skipped


def _emit_follow_up_events(events: list[FollowUpEvent]) -> tuple[int, list[str]]:
    """
    Emit FollowUpTriggered events to EventBridge in batches.
    
    Args:
        events: List of follow-up events to emit
        
    Returns:
        Tuple of (successfully emitted count, list of errors)
    """
    if not events:
        return 0, []
    
    client = _get_eventbridge_client()
    emitted = 0
    errors: list[str] = []
    
    # Process in batches (EventBridge limit: 10 per request)
    for i in range(0, len(events), EVENTBRIDGE_BATCH_SIZE):
        batch = events[i : i + EVENTBRIDGE_BATCH_SIZE]
        
        entries = [
            {
                "EventBusName": EVENTBRIDGE_BUS_NAME,
                "Source": EVENTBRIDGE_SOURCE,
                "DetailType": "FollowUpTriggered",
                "Detail": json.dumps(event.to_eventbridge_detail()),
            }
            for event in batch
        ]
        
        log.debug(
            "emitting_follow_up_batch",
            batch_size=len(entries),
            batch_number=(i // EVENTBRIDGE_BATCH_SIZE) + 1,
        )
        
        try:
            response = client.put_events(Entries=entries)
            
            # Track failed entries
            failed_count = response.get("FailedEntryCount", 0)
            if failed_count > 0:
                for j, entry in enumerate(response.get("Entries", [])):
                    if "ErrorCode" in entry:
                        err_msg = f"Event {i + j} failed: {entry.get('ErrorCode')} - {entry.get('ErrorMessage')}"
                        errors.append(err_msg)
                        log.warning("follow_up_event_failed", error=err_msg)
            
            emitted += len(batch) - failed_count
            
        except ClientError as e:
            err_msg = f"Batch {(i // EVENTBRIDGE_BATCH_SIZE) + 1} failed: {e}"
            errors.append(err_msg)
            log.error("follow_up_batch_failed", error=str(e))
    
    log.info(
        "follow_up_events_emitted",
        total=emitted,
        errors=len(errors),
    )
    
    return emitted, errors


def _parse_scheduled_event(event: dict[str, Any]) -> dict[str, Any]:
    """
    Parse scheduled EventBridge event for optional configuration.
    
    The scheduled rule can include custom parameters in the detail:
    - custom_thresholds: Override days thresholds per status
    - dry_run: If true, query but don't emit events
    
    Args:
        event: Lambda event payload
        
    Returns:
        Configuration dict
    """
    config = {
        "custom_thresholds": None,
        "dry_run": False,
        "trace_context": None,
    }
    
    # Check for detail payload (scheduled events may include config)
    detail = event.get("detail", {})
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            pass
    
    if isinstance(detail, dict):
        config["custom_thresholds"] = detail.get("custom_thresholds")
        config["dry_run"] = detail.get("dry_run", False)
        config["trace_context"] = detail.get("trace_context")
    
    return config


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Main Lambda handler for scheduled follow-up processing.
    
    Triggered by EventBridge Scheduled Rule to detect dormant provider
    sessions and emit FollowUpTriggered events for the Communication Agent.
    
    Args:
        event: EventBridge scheduled event
        context: Lambda context
        
    Returns:
        Processing result summary
    """
    start_time = time.time()
    
    # Parse event for any custom configuration
    config = _parse_scheduled_event(event)
    
    log.info(
        "follow_up_processing_started",
        dry_run=config["dry_run"],
        has_custom_thresholds=config["custom_thresholds"] is not None,
    )
    
    result = FollowUpResult()
    now = datetime.now(timezone.utc)
    
    try:
        # Build queries for all monitored dormant states
        queries = build_dormant_session_queries(
            custom_thresholds=config["custom_thresholds"],
        )
        result.queries_executed = len(queries)
        
        # Execute each query
        query_results: list[QueryResult] = []
        for query in queries:
            qr = _query_dormant_sessions(query, now)
            query_results.append(qr)
            
            if qr.succeeded:
                result.queries_succeeded += 1
                result.dormant_providers_found += qr.count
            else:
                result.errors.append(f"Query {query.gsi1pk}: {qr.error}")
        
        # Build follow-up events
        follow_up_events, skipped = _build_follow_up_events(
            query_results,
            trace_context=config["trace_context"],
        )
        result.follow_ups_skipped = skipped
        
        # Emit events (unless dry run)
        if config["dry_run"]:
            log.info(
                "dry_run_mode",
                follow_ups_would_emit=len(follow_up_events),
            )
            result.follow_ups_emitted = 0
        else:
            emitted, emit_errors = _emit_follow_up_events(follow_up_events)
            result.follow_ups_emitted = emitted
            result.errors.extend(emit_errors)
        
    except Exception as e:
        log.exception("follow_up_processing_failed", error=str(e))
        result.errors.append(f"Critical error: {e}")
    
    result.duration_ms = (time.time() - start_time) * 1000
    
    log.info(
        "follow_up_processing_completed",
        queries_executed=result.queries_executed,
        queries_succeeded=result.queries_succeeded,
        dormant_found=result.dormant_providers_found,
        follow_ups_emitted=result.follow_ups_emitted,
        follow_ups_skipped=result.follow_ups_skipped,
        errors=len(result.errors),
        duration_ms=result.duration_ms,
    )
    
    return {
        "statusCode": 200 if result.succeeded else 500,
        "body": {
            "message": "Follow-up processing complete",
            "queries_executed": result.queries_executed,
            "queries_succeeded": result.queries_succeeded,
            "dormant_providers_found": result.dormant_providers_found,
            "follow_ups_emitted": result.follow_ups_emitted,
            "follow_ups_skipped": result.follow_ups_skipped,
            "errors": result.errors if result.errors else None,
            "duration_ms": round(result.duration_ms, 2),
        },
    }
