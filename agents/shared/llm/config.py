"""
LLM Configuration Settings

Pydantic-settings based configuration for LLM/Bedrock integration.
All settings can be overridden via environment variables with RECRUITMENT_ prefix.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    """
    LLM-specific settings for AWS Bedrock integration.
    
    These settings control LLM behavior and can be used to disable
    LLM features for testing or fallback to template-based behavior.
    
    Environment variables are prefixed with RECRUITMENT_ and are case-insensitive.
    Example: RECRUITMENT_LLM_ENABLED=false
    """
    
    model_config = SettingsConfigDict(
        env_prefix="RECRUITMENT_",
        env_file=[".env.local", ".env"],  # Try .env.local first
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Global LLM Toggle
    llm_enabled: bool = Field(
        default=True,
        description="Global toggle for LLM features. Set to false to use template fallback.",
    )
    
    # Feature-specific LLM Toggles
    use_llm_for_email: bool = Field(
        default=True,
        description="Use LLM for email generation in Communication Agent",
    )
    use_llm_for_classification: bool = Field(
        default=True,
        description="Use LLM for response classification in Screening Agent",
    )
    use_llm_for_screening: bool = Field(
        default=True,
        description="Use LLM for screening decisions in Screening Agent",
    )
    use_llm_for_document_analysis: bool = Field(
        default=True,
        description="Use LLM for document analysis with OCR fallback",
    )
    
    # AWS Bedrock Configuration
    bedrock_model_id: str = Field(
        default="anthropic.claude-3-sonnet-20240229-v1:0",
        description="AWS Bedrock model ID for Claude",
    )
    bedrock_region: str = Field(
        default="us-west-2",
        description="AWS region for Bedrock service",
    )
    bedrock_endpoint_url: str | None = Field(
        default=None,
        description="Custom Bedrock endpoint URL (for local testing or VPC endpoints)",
    )
    
    # LLM Parameters
    llm_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="LLM sampling temperature (lower = more deterministic)",
    )
    llm_max_tokens: int = Field(
        default=4096,
        gt=0,
        le=100000,
        description="Maximum tokens for LLM response",
    )
    llm_top_p: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Top-p (nucleus) sampling parameter",
    )
    
    # Retry Configuration
    llm_max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retry attempts for failed LLM calls",
    )
    llm_retry_delay_seconds: float = Field(
        default=1.0,
        ge=0.0,
        description="Initial delay between retries (exponential backoff)",
    )
    
    # Timeout Configuration
    llm_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="Timeout for LLM API calls in seconds",
    )
    
    def is_feature_enabled(self, feature: Literal["email", "classification", "screening", "document"]) -> bool:
        """
        Check if a specific LLM feature is enabled.
        
        Both the global toggle and the feature-specific toggle must be True.
        
        Args:
            feature: Feature name to check
            
        Returns:
            True if the feature is enabled, False otherwise
        """
        if not self.llm_enabled:
            return False
        
        feature_flags = {
            "email": self.use_llm_for_email,
            "classification": self.use_llm_for_classification,
            "screening": self.use_llm_for_screening,
            "document": self.use_llm_for_document_analysis,
        }
        
        return feature_flags.get(feature, False)


@lru_cache(maxsize=1)
def get_llm_settings() -> LLMSettings:
    """
    Get cached LLM settings instance.
    
    Uses lru_cache to ensure settings are loaded only once.
    For testing, use LLMSettings() directly with overrides.
    
    Returns:
        LLMSettings instance with environment variable overrides applied
    """
    return LLMSettings()
