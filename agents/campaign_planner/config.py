"""
Campaign Planner Configuration

Agent-specific settings for the Campaign Planner agent.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CampaignPlannerConfig(BaseSettings):
    """
    Campaign Planner agent configuration.
    
    These settings are specific to the Campaign Planner agent
    and extend the base system settings.
    """
    
    model_config = SettingsConfigDict(
        env_prefix="CAMPAIGN_PLANNER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Provider selection limits
    max_providers_per_market: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum providers to select per market",
    )
    min_providers_per_market: int = Field(
        default=1,
        ge=1,
        description="Minimum providers to select per market",
    )
    
    # Batch processing
    event_batch_size: int = Field(
        default=10,
        ge=1,
        le=10,
        description="Max events per EventBridge batch (AWS limit: 10)",
    )
    dynamo_batch_size: int = Field(
        default=25,
        ge=1,
        le=25,
        description="Max items per DynamoDB batch write (AWS limit: 25)",
    )
    
    # Provider database configuration
    provider_database_table: str = Field(
        default="ProviderDatabase",
        description="DynamoDB table containing available providers",
    )
    use_mock_providers: bool = Field(
        default=True,
        description="Use mock provider data instead of real database",
    )
    
    # Feature flags
    enable_deduplication: bool = Field(
        default=True,
        description="Skip providers who already have active campaigns",
    )
    validate_email_addresses: bool = Field(
        default=True,
        description="Validate provider email format before selection",
    )
    
    # Timeouts and retries
    provider_selection_timeout_seconds: int = Field(
        default=30,
        ge=1,
        description="Timeout for provider selection operation",
    )


@lru_cache
def get_campaign_planner_config() -> CampaignPlannerConfig:
    """Get cached Campaign Planner configuration."""
    return CampaignPlannerConfig()
