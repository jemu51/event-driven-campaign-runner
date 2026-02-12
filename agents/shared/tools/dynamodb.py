"""
DynamoDB Tools

Idempotent tools for provider state persistence in DynamoDB.
All operations follow the schema defined in contracts/dynamodb_schema.json.
"""

from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError
import structlog

from agents.shared.config import get_settings
from agents.shared.exceptions import (
    ConditionalWriteError,
    DynamoDBError,
    ProviderNotFoundError,
)
from agents.shared.models.dynamo import (
    CampaignRecord,
    CampaignStatus,
    EventRecord,
    ProviderKey,
    ProviderState,
)
from agents.shared.state_machine import (
    ProviderStatus,
    get_expected_event,
    validate_transition,
)

log = structlog.get_logger()


def _get_table():
    """Get DynamoDB table resource."""
    settings = get_settings()
    dynamodb = boto3.resource("dynamodb", **settings.dynamodb_config)
    return dynamodb.Table(settings.dynamodb_table_name)


def _get_client():
    """Get DynamoDB client."""
    settings = get_settings()
    return boto3.client("dynamodb", **settings.dynamodb_config)


def load_provider_state(
    campaign_id: str,
    provider_id: str,
    *,
    consistent_read: bool = True,
) -> ProviderState | None:
    """
    Load provider state from DynamoDB.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        consistent_read: Use strongly consistent read (default True)
        
    Returns:
        ProviderState if found, None otherwise
        
    Raises:
        DynamoDBError: On DynamoDB operation failure
    """
    settings = get_settings()
    table = _get_table()
    key = ProviderKey(campaign_id, provider_id)
    
    log.debug(
        "loading_provider_state",
        campaign_id=campaign_id,
        provider_id=provider_id,
    )
    
    try:
        response = table.get_item(
            Key=key.to_key(),
            ConsistentRead=consistent_read,
        )
    except ClientError as e:
        log.error(
            "dynamodb_get_failed",
            campaign_id=campaign_id,
            provider_id=provider_id,
            error=str(e),
        )
        raise DynamoDBError(
            operation="get",
            table_name=settings.dynamodb_table_name,
            error_message=str(e),
        ) from e
    
    item = response.get("Item")
    if not item:
        log.debug(
            "provider_not_found",
            campaign_id=campaign_id,
            provider_id=provider_id,
        )
        return None
    
    return ProviderState.from_dynamodb(item)


def create_provider_record(
    campaign_id: str,
    provider_id: str,
    provider_email: str,
    provider_market: str,
    *,
    provider_name: str | None = None,
    status: ProviderStatus = ProviderStatus.INVITED,
    documents_pending: list[str] | None = None,
) -> ProviderState:
    """
    Create a new provider record in DynamoDB.
    
    This is idempotent - if the record already exists, it returns the existing record.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        provider_email: Provider's email address
        provider_market: Market assignment
        provider_name: Provider's display name
        status: Initial status (default: INVITED)
        documents_pending: List of required document types
        
    Returns:
        Created or existing ProviderState
        
    Raises:
        DynamoDBError: On DynamoDB operation failure
    """
    settings = get_settings()
    table = _get_table()
    
    now = int(datetime.now(timezone.utc).timestamp())
    
    state = ProviderState(
        campaign_id=campaign_id,
        provider_id=provider_id,
        status=status,
        expected_next_event=get_expected_event(status),
        last_contacted_at=now,
        provider_email=provider_email,
        provider_market=provider_market,
        provider_name=provider_name,
        documents_pending=documents_pending or [],
        created_at=now,
        updated_at=now,
        version=1,
    )
    
    log.info(
        "creating_provider_record",
        campaign_id=campaign_id,
        provider_id=provider_id,
        status=status.value,
        market=provider_market,
    )
    
    try:
        # Conditional write to ensure idempotency
        table.put_item(
            Item=state.to_dynamodb(),
            ConditionExpression="attribute_not_exists(PK)",
        )
        log.info(
            "provider_record_created",
            campaign_id=campaign_id,
            provider_id=provider_id,
        )
        return state
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Record already exists - return existing (idempotent)
            log.info(
                "provider_record_already_exists",
                campaign_id=campaign_id,
                provider_id=provider_id,
            )
            existing = load_provider_state(campaign_id, provider_id)
            if existing:
                return existing
            # Edge case: record deleted between check and load
            raise ProviderNotFoundError(provider_id, campaign_id) from e
        
        log.error(
            "dynamodb_put_failed",
            campaign_id=campaign_id,
            provider_id=provider_id,
            error=str(e),
        )
        raise DynamoDBError(
            operation="put",
            table_name=settings.dynamodb_table_name,
            error_message=str(e),
        ) from e


def update_provider_state(
    campaign_id: str,
    provider_id: str,
    new_status: ProviderStatus | str,
    *,
    expected_version: int | None = None,
    expected_next_event: str | None = None,
    email_thread_id: str | None = None,
    equipment_confirmed: list[str] | None = None,
    equipment_missing: list[str] | None = None,
    travel_confirmed: bool | None = None,
    documents_uploaded: list[str] | None = None,
    documents_pending: list[str] | None = None,
    artifacts: dict[str, str] | None = None,
    extracted_data: dict[str, Any] | None = None,
    certifications: list[str] | None = None,
    screening_notes: str | None = None,
) -> ProviderState:
    """
    Update provider state in DynamoDB.
    
    Validates state transition and uses conditional write for optimistic locking.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        new_status: New provider status
        expected_version: Expected current version for optimistic locking
        expected_next_event: Override expected next event
        email_thread_id: SES thread ID
        equipment_confirmed: Confirmed equipment list
        equipment_missing: Missing equipment list
        travel_confirmed: Travel confirmation flag
        documents_uploaded: Uploaded document types
        documents_pending: Pending document types
        artifacts: Document artifacts (filename -> S3 path)
        extracted_data: OCR extracted fields
        certifications: Provider certifications
        screening_notes: Screening summary
        
    Returns:
        Updated ProviderState
        
    Raises:
        ProviderNotFoundError: If provider doesn't exist
        InvalidStateTransitionError: If transition is invalid
        ConditionalWriteError: If version mismatch
        DynamoDBError: On other DynamoDB failures
    """
    settings = get_settings()
    table = _get_table()
    
    # Convert string to enum if needed
    if isinstance(new_status, str):
        new_status = ProviderStatus(new_status)
    
    # Load current state to validate transition
    current = load_provider_state(campaign_id, provider_id)
    if not current:
        raise ProviderNotFoundError(provider_id, campaign_id)
    
    # Validate transition (raises if invalid)
    if current.status != new_status:
        validate_transition(current.status, new_status)
    
    # Check version if provided
    if expected_version is not None and current.version != expected_version:
        raise ConditionalWriteError(
            table_name=settings.dynamodb_table_name,
            expected_version=expected_version,
            actual_version=current.version,
        )
    
    now = int(datetime.now(timezone.utc).timestamp())
    
    # Build update expression dynamically
    update_parts = [
        "#status = :new_status",
        "#expected_next_event = :expected_next_event",
        "#gsi1pk = :gsi1pk",
        "#updated_at = :updated_at",
        "#version = :new_version",
        "#last_contacted_at = :last_contacted_at",
    ]
    
    expr_names = {
        "#status": "status",
        "#expected_next_event": "expected_next_event",
        "#gsi1pk": "GSI1PK",
        "#updated_at": "updated_at",
        "#version": "version",
        "#last_contacted_at": "last_contacted_at",
    }
    
    next_event = expected_next_event or get_expected_event(new_status)
    gsi1pk = f"{new_status.value}#{next_event or 'None'}"
    
    expr_values: dict[str, Any] = {
        ":new_status": new_status.value,
        ":expected_next_event": next_event,
        ":gsi1pk": gsi1pk,
        ":updated_at": now,
        ":new_version": current.version + 1,
        ":current_version": current.version,
        ":last_contacted_at": now,
    }
    
    # Add optional fields
    optional_updates = [
        ("email_thread_id", email_thread_id),
        ("equipment_confirmed", equipment_confirmed),
        ("equipment_missing", equipment_missing),
        ("travel_confirmed", travel_confirmed),
        ("documents_uploaded", documents_uploaded),
        ("documents_pending", documents_pending),
        ("artifacts", artifacts),
        ("extracted_data", extracted_data),
        ("certifications", certifications),
        ("screening_notes", screening_notes),
    ]
    
    for field_name, value in optional_updates:
        if value is not None:
            update_parts.append(f"#{field_name} = :{field_name}")
            expr_names[f"#{field_name}"] = field_name
            expr_values[f":{field_name}"] = value
    
    update_expression = "SET " + ", ".join(update_parts)
    
    log.info(
        "updating_provider_state",
        campaign_id=campaign_id,
        provider_id=provider_id,
        old_status=current.status.value,
        new_status=new_status.value,
        version=current.version,
    )
    
    try:
        key = ProviderKey(campaign_id, provider_id)
        table.update_item(
            Key=key.to_key(),
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ConditionExpression="attribute_exists(PK) AND #version = :current_version",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            log.warning(
                "conditional_write_failed",
                campaign_id=campaign_id,
                provider_id=provider_id,
                expected_version=current.version,
            )
            raise ConditionalWriteError(
                table_name=settings.dynamodb_table_name,
                expected_version=current.version,
            ) from e
        
        log.error(
            "dynamodb_update_failed",
            campaign_id=campaign_id,
            provider_id=provider_id,
            error=str(e),
        )
        raise DynamoDBError(
            operation="update",
            table_name=settings.dynamodb_table_name,
            error_message=str(e),
        ) from e
    
    # Return updated state (reload to get full record)
    updated = load_provider_state(campaign_id, provider_id)
    if not updated:
        raise ProviderNotFoundError(provider_id, campaign_id)
    
    log.info(
        "provider_state_updated",
        campaign_id=campaign_id,
        provider_id=provider_id,
        new_status=new_status.value,
        new_version=updated.version,
    )
    
    return updated


def list_campaign_providers(
    campaign_id: str,
    *,
    status_filter: ProviderStatus | None = None,
    limit: int | None = None,
) -> list[ProviderState]:
    """
    List all providers for a campaign.
    
    Args:
        campaign_id: Campaign identifier
        status_filter: Optional status to filter by
        limit: Maximum number of results
        
    Returns:
        List of ProviderState records
    """
    settings = get_settings()
    table = _get_table()
    
    query_params = {
        "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
        "ExpressionAttributeValues": {
            ":pk": f"SESSION#{campaign_id}",
            ":sk_prefix": "PROVIDER#",
        },
    }
    
    if status_filter:
        query_params["FilterExpression"] = "#status = :status"
        query_params["ExpressionAttributeNames"] = {"#status": "status"}
        query_params["ExpressionAttributeValues"][":status"] = status_filter.value
    
    if limit:
        query_params["Limit"] = limit
    
    log.debug(
        "listing_campaign_providers",
        campaign_id=campaign_id,
        status_filter=status_filter.value if status_filter else None,
    )
    
    try:
        response = table.query(**query_params)
        items = response.get("Items", [])
        
        # Handle pagination if needed
        while "LastEvaluatedKey" in response and (limit is None or len(items) < limit):
            query_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = table.query(**query_params)
            items.extend(response.get("Items", []))
        
        return [ProviderState.from_dynamodb(item) for item in items]
    
    except ClientError as e:
        log.error(
            "dynamodb_query_failed",
            campaign_id=campaign_id,
            error=str(e),
        )
        raise DynamoDBError(
            operation="query",
            table_name=settings.dynamodb_table_name,
            error_message=str(e),
        ) from e


def find_dormant_sessions(
    status: ProviderStatus,
    expected_event: str,
    threshold_timestamp: int,
    *,
    limit: int = 100,
) -> list[ProviderState]:
    """
    Find providers in dormant sessions past threshold.
    
    Uses GSI1 to efficiently query by status and expected event.
    
    Args:
        status: Provider status to query
        expected_event: Expected next event type
        threshold_timestamp: Unix timestamp threshold (find records older than this)
        limit: Maximum results
        
    Returns:
        List of dormant ProviderState records
    """
    settings = get_settings()
    table = _get_table()
    
    gsi1pk = f"{status.value}#{expected_event}"
    
    log.debug(
        "finding_dormant_sessions",
        status=status.value,
        expected_event=expected_event,
        threshold=threshold_timestamp,
    )
    
    try:
        response = table.query(
            IndexName=settings.dynamodb_gsi1_name,
            KeyConditionExpression="GSI1PK = :gsi1pk AND last_contacted_at < :threshold",
            ExpressionAttributeValues={
                ":gsi1pk": gsi1pk,
                ":threshold": threshold_timestamp,
            },
            Limit=limit,
        )
        
        items = response.get("Items", [])
        return [ProviderState.from_dynamodb(item) for item in items]
    
    except ClientError as e:
        log.error(
            "dynamodb_gsi_query_failed",
            gsi1pk=gsi1pk,
            error=str(e),
        )
        raise DynamoDBError(
            operation="query",
            table_name=settings.dynamodb_table_name,
            error_message=str(e),
        ) from e


# =====================================================
# Campaign Record Operations
# =====================================================


def create_campaign_record(
    campaign_id: str,
    buyer_id: str,
    campaign_type: str,
    requirements: dict[str, Any],
    markets: list[str],
    provider_count: int = 0,
) -> CampaignRecord:
    """
    Create a campaign record in DynamoDB.
    
    Idempotent — returns existing record if already present.
    """
    table = _get_table()
    now = int(datetime.now(timezone.utc).timestamp())
    
    record = CampaignRecord(
        campaign_id=campaign_id,
        buyer_id=buyer_id,
        campaign_type=campaign_type,
        requirements=requirements,
        markets=markets,
        status=CampaignStatus.RUNNING,
        provider_count=provider_count,
        created_at=now,
        updated_at=now,
    )
    
    log.info("creating_campaign_record", campaign_id=campaign_id)
    
    try:
        table.put_item(
            Item=record.to_dynamodb(),
            ConditionExpression="attribute_not_exists(PK)",
        )
        return record
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            log.info("campaign_record_already_exists", campaign_id=campaign_id)
            existing = load_campaign_record(campaign_id)
            if existing:
                return existing
        raise


def load_campaign_record(campaign_id: str) -> CampaignRecord | None:
    """Load a campaign record from DynamoDB."""
    table = _get_table()
    
    try:
        response = table.get_item(
            Key={"PK": f"CAMPAIGN#{campaign_id}", "SK": "METADATA"},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return None
        return CampaignRecord.from_dynamodb(item)
    except ClientError as e:
        log.error("campaign_load_failed", campaign_id=campaign_id, error=str(e))
        return None


def update_campaign_status(campaign_id: str, new_status: CampaignStatus) -> None:
    """Update campaign status."""
    table = _get_table()
    now = int(datetime.now(timezone.utc).timestamp())
    
    try:
        table.update_item(
            Key={"PK": f"CAMPAIGN#{campaign_id}", "SK": "METADATA"},
            UpdateExpression="SET #s = :status, #u = :updated_at",
            ExpressionAttributeNames={"#s": "status", "#u": "updated_at"},
            ExpressionAttributeValues={":status": new_status.value, ":updated_at": now},
            ConditionExpression="attribute_exists(PK)",
        )
        log.info("campaign_status_updated", campaign_id=campaign_id, status=new_status.value)
    except ClientError as e:
        log.warning("campaign_status_update_failed", campaign_id=campaign_id, error=str(e))


def update_campaign_provider_count(campaign_id: str, provider_count: int) -> None:
    """Update the provider count on a campaign record."""
    table = _get_table()
    now = int(datetime.now(timezone.utc).timestamp())
    
    try:
        table.update_item(
            Key={"PK": f"CAMPAIGN#{campaign_id}", "SK": "METADATA"},
            UpdateExpression="SET provider_count = :count, updated_at = :updated_at",
            ExpressionAttributeValues={":count": provider_count, ":updated_at": now},
            ConditionExpression="attribute_exists(PK)",
        )
    except ClientError as e:
        log.warning("campaign_provider_count_update_failed", campaign_id=campaign_id, error=str(e))


def list_all_campaigns(limit: int = 50) -> list[CampaignRecord]:
    """
    List all campaigns using GSI1 (GSI1PK = 'CAMPAIGNS').
    
    Returns campaigns sorted by creation time (newest first).
    """
    settings = get_settings()
    table = _get_table()
    
    try:
        response = table.query(
            IndexName=settings.dynamodb_gsi1_name,
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={":pk": "CAMPAIGNS"},
            ScanIndexForward=False,
            Limit=limit,
        )
        items = response.get("Items", [])
        return [CampaignRecord.from_dynamodb(item) for item in items]
    except ClientError as e:
        log.error("list_campaigns_failed", error=str(e))
        return []


# =====================================================
# Event Record Operations
# =====================================================


def save_event_record(
    campaign_id: str,
    event_type: str,
    detail: dict[str, Any],
    timestamp: str,
    provider_id: str | None = None,
) -> None:
    """Save an event record to DynamoDB."""
    import time as _time
    
    table = _get_table()
    timestamp_ms = int(_time.time() * 1000)
    
    record = EventRecord(
        campaign_id=campaign_id,
        provider_id=provider_id,
        event_type=event_type,
        detail=detail,
        timestamp=timestamp,
        timestamp_ms=timestamp_ms,
    )
    
    try:
        table.put_item(Item=record.to_dynamodb())
    except ClientError as e:
        log.warning("event_save_failed", event_type=event_type, error=str(e))


def list_campaign_events(
    campaign_id: str,
    limit: int = 200,
) -> list[EventRecord]:
    """List all events for a campaign, ordered by time."""
    table = _get_table()
    
    try:
        response = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"EVENTS#{campaign_id}",
                ":prefix": "EVT#",
            },
            ScanIndexForward=True,
            Limit=limit,
        )
        items = response.get("Items", [])
        return [EventRecord.from_dynamodb(item) for item in items]
    except ClientError as e:
        log.error("list_events_failed", campaign_id=campaign_id, error=str(e))
        return []
