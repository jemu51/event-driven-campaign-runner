"""
Communication Agent Configuration

Agent-specific settings for the Communication Agent.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CommunicationConfig(BaseSettings):
    """
    Communication Agent configuration.
    
    These settings are specific to the Communication Agent
    and extend the base system settings.
    """
    
    model_config = SettingsConfigDict(
        env_prefix="COMMUNICATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Template configuration
    template_directory: str = Field(
        default="agents/communication/templates",
        description="Directory containing email templates",
    )
    template_format: Literal["jinja2", "fstring"] = Field(
        default="jinja2",
        description="Template rendering format",
    )
    
    # Email defaults
    default_subject_prefix: str = Field(
        default="",
        description="Prefix to add to all email subjects",
    )
    include_unsubscribe_link: bool = Field(
        default=False,
        description="Include unsubscribe link in emails",
    )
    
    # Rate limiting
    max_emails_per_second: int = Field(
        default=14,
        ge=1,
        le=50,
        description="Maximum emails per second (SES rate limit)",
    )
    
    # LLM configuration for email drafting
    use_llm_drafting: bool = Field(
        default=False,
        description="Use LLM to personalize emails beyond templates",
    )
    llm_model_id: str = Field(
        default="anthropic.claude-3-sonnet-20240229-v1:0",
        description="Bedrock model ID for LLM drafting",
    )
    llm_max_tokens: int = Field(
        default=500,
        ge=100,
        le=2000,
        description="Maximum tokens for LLM response",
    )
    llm_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="LLM sampling temperature",
    )
    
    # Retry configuration
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retries for email sending",
    )
    retry_delay_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Delay between retries",
    )
    
    @property
    def template_path(self) -> Path:
        """Get absolute path to template directory."""
        base_path = Path(__file__).parent.parent.parent
        return base_path / self.template_directory


@lru_cache
def get_communication_config() -> CommunicationConfig:
    """Get cached Communication Agent configuration."""
    return CommunicationConfig()
