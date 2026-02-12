"""
Screening Agent Configuration

Agent-specific settings for the Screening Agent.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScreeningConfig(BaseSettings):
    """
    Screening agent configuration.
    
    These settings are specific to the Screening Agent
    and extend the base system settings.
    """
    
    model_config = SettingsConfigDict(
        env_prefix="SCREENING_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Insurance validation
    insurance_min_coverage_dollars: int = Field(
        default=2_000_000,
        ge=0,
        description="Minimum insurance coverage required in dollars",
    )
    insurance_expiry_buffer_days: int = Field(
        default=30,
        ge=0,
        description="Days before expiry to consider insurance as expiring soon",
    )
    
    # Equipment matching
    equipment_match_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for equipment keyword match",
    )
    
    # Textract configuration
    textract_features: list[str] = Field(
        default=["FORMS", "TABLES"],
        description="Textract features to use for document analysis",
    )
    textract_confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for OCR field extraction",
    )
    textract_sns_topic_arn: str = Field(
        default="",
        description="SNS topic ARN for Textract async completion notifications",
    )
    textract_role_arn: str = Field(
        default="",
        description="IAM role ARN for Textract to publish to SNS",
    )
    
    # Response classification
    positive_response_keywords: list[str] = Field(
        default=[
            "yes", "interested", "available", "accept", "confirm",
            "can do", "willing", "sounds good", "count me in",
            "i have", "i own", "we have",
        ],
        description="Keywords indicating positive response",
    )
    negative_response_keywords: list[str] = Field(
        default=[
            "no", "not interested", "decline", "pass", "busy",
            "unavailable", "cannot", "unable", "don't have",
            "not available", "opt out", "unsubscribe",
        ],
        description="Keywords indicating negative response",
    )
    question_response_keywords: list[str] = Field(
        default=[
            "?", "what", "when", "where", "how", "why", "which",
            "could you", "can you", "tell me more", "more info",
            "clarify", "explain", "details",
        ],
        description="Keywords indicating provider has questions",
    )
    
    # Escalation thresholds
    max_follow_ups: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum follow-up attempts before escalation",
    )
    ambiguous_response_threshold: int = Field(
        default=2,
        ge=1,
        description="Number of ambiguous responses before escalation",
    )
    
    # Feature flags
    enable_llm_classification: bool = Field(
        default=False,
        description="Use LLM for response classification (vs keyword-based)",
    )
    llm_model_id: str = Field(
        default="anthropic.claude-3-sonnet-20240229-v1:0",
        description="Bedrock model ID for LLM classification",
    )
    enable_auto_qualification: bool = Field(
        default=True,
        description="Automatically qualify providers meeting all requirements",
    )


@lru_cache
def get_screening_config() -> ScreeningConfig:
    """Get cached Screening configuration."""
    return ScreeningConfig()
