"""
Campaign Planner Models

Pydantic models for campaign planning operations.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketPriority(str, Enum):
    """Market priority for provider selection."""
    
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ProviderInfo(BaseModel):
    """
    Information about a provider from the provider database.
    
    This represents a provider available for selection in a campaign.
    """
    
    model_config = ConfigDict(frozen=True)
    
    provider_id: str = Field(..., description="Unique provider identifier")
    email: str = Field(..., description="Provider's email address")
    name: str = Field(..., description="Provider's display name")
    market: str = Field(..., description="Provider's primary market")
    
    # Capabilities
    equipment: list[str] = Field(default_factory=list, description="Available equipment")
    certifications: list[str] = Field(default_factory=list, description="Provider certifications")
    
    # Availability
    available: bool = Field(default=True, description="Whether provider is currently available")
    travel_willing: bool = Field(default=False, description="Whether provider is willing to travel")
    
    # Scoring data
    rating: float = Field(default=0.0, ge=0.0, le=5.0, description="Provider rating (0-5)")
    completed_jobs: int = Field(default=0, ge=0, description="Number of completed jobs")
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional provider data")


class ProviderSelection(BaseModel):
    """
    Result of provider selection for a market.
    
    Contains the selected providers and selection metadata.
    """
    
    model_config = ConfigDict(frozen=True)
    
    market: str = Field(..., description="Market for which providers were selected")
    providers: list[ProviderInfo] = Field(..., description="Selected providers")
    total_available: int = Field(
        default=0,
        ge=0,
        description="Total available providers in market",
    )
    selection_reason: str | None = Field(
        default=None,
        description="Reason for selection criteria used",
    )


class CampaignRequirements(BaseModel):
    """
    Parsed campaign requirements for provider selection.
    
    This is a view of the Requirements from the event, optimized for
    provider selection logic. Derived from contracts/requirements_schema.json.
    """
    
    model_config = ConfigDict(frozen=True)
    
    campaign_id: str = Field(..., description="Campaign identifier")
    buyer_id: str = Field(..., description="Buyer/client identifier")
    campaign_type: str = Field(..., description="Type of campaign (e.g., satellite_upgrade)")
    
    # Market configuration
    markets: list[str] = Field(default_factory=list, description="Target markets")
    providers_per_market: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of providers to recruit per market",
    )
    
    # Equipment requirements
    required_equipment: list[str] = Field(
        default_factory=list,
        description="Required equipment (must have all)",
    )
    optional_equipment: list[str] = Field(
        default_factory=list,
        description="Optional equipment (nice to have)",
    )
    
    # Document requirements
    required_documents: list[str] = Field(
        default_factory=list,
        description="Required document types",
    )
    insurance_min_coverage: int = Field(
        default=0,
        ge=0,
        description="Minimum insurance coverage in dollars",
    )
    
    # Certification requirements
    required_certifications: list[str] = Field(
        default_factory=list,
        description="Required certifications",
    )
    preferred_certifications: list[str] = Field(
        default_factory=list,
        description="Preferred certifications (nice to have)",
    )
    
    # Other requirements
    travel_required: bool = Field(
        default=False,
        description="Whether providers must be willing to travel",
    )
    
    @property
    def total_providers_needed(self) -> int:
        """Total number of providers needed across all markets."""
        return len(self.markets) * self.providers_per_market
    
    @field_validator("markets", mode="before")
    @classmethod
    def normalize_markets(cls, v: list[str]) -> list[str]:
        """Normalize market names to lowercase."""
        if not v:
            return v
        return [m.lower().strip() for m in v]


class PlanningResult(BaseModel):
    """
    Result of campaign planning operation.
    
    Contains all selected providers and planning metadata.
    """
    
    model_config = ConfigDict(frozen=True)
    
    campaign_id: str = Field(..., description="Campaign identifier")
    total_providers_selected: int = Field(
        default=0,
        ge=0,
        description="Total providers selected across all markets",
    )
    providers_by_market: dict[str, list[ProviderInfo]] = Field(
        default_factory=dict,
        description="Map of market -> selected providers",
    )
    events_emitted: int = Field(
        default=0,
        ge=0,
        description="Number of SendMessageRequested events emitted",
    )
    records_created: int = Field(
        default=0,
        ge=0,
        description="Number of DynamoDB records created",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Any errors encountered during planning",
    )
    
    @property
    def success(self) -> bool:
        """Whether planning completed without errors."""
        return len(self.errors) == 0 and self.total_providers_selected > 0
