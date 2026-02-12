"""
DynamoDB Models

Pydantic models for DynamoDB items in the RecruitmentSessions table.
Schema derived from contracts/dynamodb_schema.json.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
import structlog

from agents.shared.state_machine import ProviderStatus, get_expected_event

log = structlog.get_logger()


# =====================================================
# Campaign Status
# =====================================================


class CampaignStatus(str, Enum):
    """Campaign lifecycle status."""
    
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"


# =====================================================
# Campaign Record
# =====================================================


class CampaignRecord(BaseModel):
    """
    Campaign record stored in DynamoDB.
    
    PK: CAMPAIGN#<campaign_id>
    SK: METADATA
    GSI1PK: CAMPAIGNS  (fixed — enables listing all campaigns)
    last_contacted_at: <created_at>  (reuse GSI1 sort key)
    """
    
    model_config = ConfigDict(frozen=True)
    
    campaign_id: str = Field(..., description="Campaign identifier")
    buyer_id: str = Field(..., description="Buyer/client identifier")
    campaign_type: str = Field(..., description="Campaign type (e.g., satellite-upgrade)")
    requirements: dict[str, Any] = Field(default_factory=dict, description="Full campaign requirements")
    markets: list[str] = Field(default_factory=list, description="Target markets")
    status: CampaignStatus = Field(default=CampaignStatus.RUNNING, description="Campaign status")
    provider_count: int = Field(default=0, description="Total providers in campaign")
    created_at: int = Field(..., description="Unix epoch timestamp")
    updated_at: int = Field(..., description="Unix epoch timestamp")
    
    @property
    def pk(self) -> str:
        return f"CAMPAIGN#{self.campaign_id}"
    
    @property
    def sk(self) -> str:
        return "METADATA"
    
    def to_dynamodb(self) -> dict[str, Any]:
        """Convert to DynamoDB item."""
        return {
            "PK": self.pk,
            "SK": self.sk,
            "campaign_id": self.campaign_id,
            "buyer_id": self.buyer_id,
            "campaign_type": self.campaign_type,
            "requirements": self.requirements,
            "markets": self.markets,
            "status": self.status.value,
            "provider_count": self.provider_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            # Reuse GSI1 for listing campaigns
            "GSI1PK": "CAMPAIGNS",
            "last_contacted_at": self.created_at,
        }
    
    @classmethod
    def from_dynamodb(cls, item: dict[str, Any]) -> "CampaignRecord":
        """Parse from DynamoDB item."""
        return cls(
            campaign_id=item.get("campaign_id", ""),
            buyer_id=item.get("buyer_id", ""),
            campaign_type=item.get("campaign_type", ""),
            requirements=item.get("requirements", {}),
            markets=item.get("markets", []),
            status=CampaignStatus(item.get("status", "RUNNING")),
            provider_count=item.get("provider_count", 0),
            created_at=item.get("created_at", 0),
            updated_at=item.get("updated_at", 0),
        )


# =====================================================
# Event Record
# =====================================================


class EventRecord(BaseModel):
    """
    Persisted event record in DynamoDB.
    
    PK: EVENTS#<campaign_id>
    SK: EVT#<timestamp_ms>#<event_type>
    """
    
    model_config = ConfigDict(frozen=True)
    
    campaign_id: str = Field(..., description="Campaign identifier")
    provider_id: str | None = Field(default=None, description="Provider identifier")
    event_type: str = Field(..., description="Event type (e.g., SendMessageRequested)")
    detail: dict[str, Any] = Field(default_factory=dict, description="Full event payload")
    timestamp: str = Field(..., description="ISO timestamp")
    timestamp_ms: int = Field(..., description="Millisecond timestamp for ordering")
    
    @property
    def pk(self) -> str:
        return f"EVENTS#{self.campaign_id}"
    
    @property
    def sk(self) -> str:
        return f"EVT#{self.timestamp_ms:015d}#{self.event_type}"
    
    def to_dynamodb(self) -> dict[str, Any]:
        """Convert to DynamoDB item."""
        item: dict[str, Any] = {
            "PK": self.pk,
            "SK": self.sk,
            "campaign_id": self.campaign_id,
            "event_type": self.event_type,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "timestamp_ms": self.timestamp_ms,
        }
        if self.provider_id:
            item["provider_id"] = self.provider_id
        return item
    
    @classmethod
    def from_dynamodb(cls, item: dict[str, Any]) -> "EventRecord":
        """Parse from DynamoDB item."""
        return cls(
            campaign_id=item.get("campaign_id", ""),
            provider_id=item.get("provider_id"),
            event_type=item.get("event_type", ""),
            detail=item.get("detail", {}),
            timestamp=item.get("timestamp", ""),
            timestamp_ms=item.get("timestamp_ms", 0),
        )


class ProviderState(BaseModel):
    """
    Provider state record stored in DynamoDB.
    
    This model represents a single provider's state within a campaign.
    PK: SESSION#<campaign_id>
    SK: PROVIDER#<provider_id>
    """
    
    model_config = ConfigDict(frozen=True)
    
    # Key fields
    campaign_id: str = Field(..., description="Campaign identifier")
    provider_id: str = Field(..., description="Provider identifier")
    
    # Required state fields
    status: ProviderStatus = Field(..., description="Current provider state")
    expected_next_event: str | None = Field(
        default=None,
        description="Event type that will wake the agent next",
    )
    last_contacted_at: int = Field(..., description="Unix epoch timestamp of last contact")
    provider_email: str = Field(..., description="Provider's email address")
    provider_market: str = Field(..., description="Market assignment (e.g., atlanta)")
    
    # Optional state fields
    email_thread_id: str | None = Field(default=None, description="SES message/thread ID")
    provider_name: str | None = Field(default=None, description="Provider's display name")
    
    # Equipment tracking
    equipment_confirmed: list[str] = Field(
        default_factory=list,
        description="Confirmed equipment (e.g., bucket_truck)",
    )
    equipment_missing: list[str] = Field(
        default_factory=list,
        description="Missing required equipment",
    )
    travel_confirmed: bool | None = Field(
        default=None,
        description="Whether provider confirmed travel willingness",
    )
    
    # Document tracking
    documents_uploaded: list[str] = Field(
        default_factory=list,
        description="Uploaded document types",
    )
    documents_pending: list[str] = Field(
        default_factory=list,
        description="Still-needed document types",
    )
    artifacts: dict[str, str] = Field(
        default_factory=dict,
        description="Map of filename -> S3 path",
    )
    extracted_data: dict[str, Any] = Field(
        default_factory=dict,
        description="OCR/Textract extracted fields",
    )
    
    # Certifications
    certifications: list[str] = Field(
        default_factory=list,
        description="Provider's certifications",
    )
    
    # Audit/notes
    screening_notes: str | None = Field(
        default=None,
        description="Human-readable screening summary",
    )
    
    # Metadata
    created_at: int | None = Field(default=None, description="Record creation timestamp")
    updated_at: int | None = Field(default=None, description="Last update timestamp")
    version: int = Field(default=1, description="Optimistic locking version")
    
    @property
    def pk(self) -> str:
        """DynamoDB partition key."""
        return f"SESSION#{self.campaign_id}"
    
    @property
    def sk(self) -> str:
        """DynamoDB sort key."""
        return f"PROVIDER#{self.provider_id}"
    
    @property
    def gsi1pk(self) -> str:
        """GSI1 partition key for dormant session queries."""
        event = self.expected_next_event or "None"
        return f"{self.status.value}#{event}"
    
    def to_dynamodb(self) -> dict[str, Any]:
        """
        Convert to DynamoDB item format.
        
        Returns a dict ready for put_item/update_item operations.
        """
        item = {
            "PK": self.pk,
            "SK": self.sk,
            "campaign_id": self.campaign_id,
            "provider_id": self.provider_id,
            "status": self.status.value,
            "expected_next_event": self.expected_next_event or get_expected_event(self.status),
            "last_contacted_at": self.last_contacted_at,
            "provider_email": self.provider_email,
            "provider_market": self.provider_market,
            "GSI1PK": self.gsi1pk,
            "version": self.version,
        }
        
        # Add optional fields if present
        if self.email_thread_id:
            item["email_thread_id"] = self.email_thread_id
        if self.provider_name:
            item["provider_name"] = self.provider_name
        if self.equipment_confirmed:
            item["equipment_confirmed"] = self.equipment_confirmed
        if self.equipment_missing:
            item["equipment_missing"] = self.equipment_missing
        if self.travel_confirmed is not None:
            item["travel_confirmed"] = self.travel_confirmed
        if self.documents_uploaded:
            item["documents_uploaded"] = self.documents_uploaded
        if self.documents_pending:
            item["documents_pending"] = self.documents_pending
        if self.artifacts:
            item["artifacts"] = self.artifacts
        if self.extracted_data:
            item["extracted_data"] = self.extracted_data
        if self.certifications:
            item["certifications"] = self.certifications
        if self.screening_notes:
            item["screening_notes"] = self.screening_notes
        if self.created_at:
            item["created_at"] = self.created_at
        if self.updated_at:
            item["updated_at"] = self.updated_at
        
        return item
    
    @classmethod
    def from_dynamodb(cls, item: dict[str, Any]) -> "ProviderState":
        """
        Create ProviderState from DynamoDB item.
        
        Args:
            item: DynamoDB item dict (with or without type descriptors)
            
        Returns:
            ProviderState instance
        """
        # Handle both raw and typed DynamoDB responses
        def extract_value(val: Any) -> Any:
            if isinstance(val, dict) and len(val) == 1:
                type_key = list(val.keys())[0]
                if type_key in ("S", "N", "BOOL", "L", "M", "NULL"):
                    inner = val[type_key]
                    if type_key == "N":
                        return int(inner) if "." not in str(inner) else float(inner)
                    if type_key == "L":
                        return [extract_value(v) for v in inner]
                    if type_key == "M":
                        return {k: extract_value(v) for k, v in inner.items()}
                    if type_key == "NULL":
                        return None
                    return inner
            return val
        
        # Parse PK/SK to extract IDs if not present directly
        pk = extract_value(item.get("PK", ""))
        sk = extract_value(item.get("SK", ""))
        
        campaign_id = extract_value(item.get("campaign_id"))
        if not campaign_id and pk.startswith("SESSION#"):
            campaign_id = pk.replace("SESSION#", "")
        
        provider_id = extract_value(item.get("provider_id"))
        if not provider_id and sk.startswith("PROVIDER#"):
            provider_id = sk.replace("PROVIDER#", "")
        
        status_str = extract_value(item.get("status", "INVITED"))
        status = ProviderStatus(status_str) if isinstance(status_str, str) else status_str
        
        return cls(
            campaign_id=campaign_id,
            provider_id=provider_id,
            status=status,
            expected_next_event=extract_value(item.get("expected_next_event")),
            last_contacted_at=extract_value(item.get("last_contacted_at", 0)),
            provider_email=extract_value(item.get("provider_email", "")),
            provider_market=extract_value(item.get("provider_market", "")),
            email_thread_id=extract_value(item.get("email_thread_id")),
            provider_name=extract_value(item.get("provider_name")),
            equipment_confirmed=extract_value(item.get("equipment_confirmed", [])),
            equipment_missing=extract_value(item.get("equipment_missing", [])),
            travel_confirmed=extract_value(item.get("travel_confirmed")),
            documents_uploaded=extract_value(item.get("documents_uploaded", [])),
            documents_pending=extract_value(item.get("documents_pending", [])),
            artifacts=extract_value(item.get("artifacts", {})),
            extracted_data=extract_value(item.get("extracted_data", {})),
            certifications=extract_value(item.get("certifications", [])),
            screening_notes=extract_value(item.get("screening_notes")),
            created_at=extract_value(item.get("created_at")),
            updated_at=extract_value(item.get("updated_at")),
            version=extract_value(item.get("version", 1)),
        )
    
    def with_updates(self, **updates: Any) -> "ProviderState":
        """
        Create a new ProviderState with the specified updates.
        
        Since ProviderState is frozen, this returns a new instance.
        
        Args:
            **updates: Fields to update
            
        Returns:
            New ProviderState with updates applied
        """
        data = self.model_dump()
        data.update(updates)
        # Increment version on update
        data["version"] = self.version + 1
        data["updated_at"] = int(datetime.now(timezone.utc).timestamp())
        return ProviderState.model_validate(data)


@dataclass(frozen=True)
class ProviderKey:
    """
    DynamoDB key for a provider record.
    
    Utility class for key construction.
    """
    
    campaign_id: str
    provider_id: str
    
    @property
    def pk(self) -> str:
        return f"SESSION#{self.campaign_id}"
    
    @property
    def sk(self) -> str:
        return f"PROVIDER#{self.provider_id}"
    
    def to_key(self) -> dict[str, str]:
        """Return DynamoDB key dict."""
        return {"PK": self.pk, "SK": self.sk}
    
    @classmethod
    def from_pk_sk(cls, pk: str, sk: str) -> "ProviderKey":
        """Parse PK/SK strings to create key."""
        campaign_id = pk.replace("SESSION#", "")
        provider_id = sk.replace("PROVIDER#", "")
        return cls(campaign_id=campaign_id, provider_id=provider_id)
