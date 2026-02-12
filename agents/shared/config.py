"""
Configuration Management

Pydantic-settings based configuration for the recruitment automation system.
All settings can be overridden via environment variables.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Environment variables are prefixed with RECRUITMENT_ and are case-insensitive.
    Example: RECRUITMENT_DYNAMODB_TABLE_NAME=MyTable
    """
    
    model_config = SettingsConfigDict(
        env_prefix="RECRUITMENT_",
        env_file=[".env.local", ".env"],  # Try .env.local first
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # DynamoDB Configuration
    dynamodb_table_name: str = Field(
        default="RecruitmentSessions",
        description="DynamoDB table name for provider state",
    )
    dynamodb_gsi1_name: str = Field(
        default="GSI1",
        description="GSI1 index name for dormant session queries",
    )
    dynamodb_endpoint_url: str | None = Field(
        default=None,
        description="DynamoDB endpoint URL (for local development)",
    )
    
    # EventBridge Configuration
    eventbridge_bus_name: str = Field(
        default="recruitment",
        description="EventBridge event bus name",
    )
    eventbridge_source_prefix: str = Field(
        default="recruitment",
        description="Prefix for EventBridge event sources",
    )
    eventbridge_endpoint_url: str | None = Field(
        default=None,
        description="EventBridge endpoint URL (use 'mock' for local)",
    )
    
    # SES Configuration
    ses_domain: str = Field(
        default="recruitment.example.com",
        description="SES verified domain for sending emails",
    )
    ses_from_address: str = Field(
        default="recruitment@recruitment.example.com",
        description="From address for outbound emails",
    )
    ses_from_name: str = Field(
        default="Recruitment Team",
        description="Display name for outbound emails",
    )
    ses_configuration_set: str | None = Field(
        default=None,
        description="SES configuration set for tracking",
    )
    ses_endpoint_url: str | None = Field(
        default=None,
        description="SES endpoint URL (use 'mock' for local)",
    )
    
    # S3 Configuration
    s3_bucket_name: str = Field(
        default="recruitment-documents",
        description="S3 bucket for document storage",
    )
    s3_documents_prefix: str = Field(
        default="documents/",
        description="Prefix for uploaded documents",
    )
    s3_inbound_emails_prefix: str = Field(
        default="inbound-emails/",
        description="Prefix for inbound email storage",
    )
    s3_endpoint_url: str | None = Field(
        default=None,
        description="S3 endpoint URL (for local development)",
    )
    
    # AWS Configuration
    aws_region: str = Field(
        default="us-west-2",
        description="AWS region",
    )
    aws_account_id: str | None = Field(
        default=None,
        description="AWS account ID (for ARN construction)",
    )
    
    # Application Configuration
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )
    
    # Follow-up Configuration
    follow_up_threshold_days: int = Field(
        default=3,
        description="Days before triggering follow-up for dormant sessions",
    )
    max_follow_ups: int = Field(
        default=3,
        description="Maximum number of follow-up attempts",
    )
    
    # Textract Configuration
    textract_sns_topic_arn: str | None = Field(
        default=None,
        description="SNS topic ARN for Textract completion notifications",
    )
    textract_role_arn: str | None = Field(
        default=None,
        description="IAM role ARN for Textract to send SNS notifications",
    )
    textract_endpoint_url: str | None = Field(
        default=None,
        description="Textract endpoint URL (use 'mock' for local)",
    )
    
    @property
    def is_local(self) -> bool:
        """Detect if running in local mode."""
        return (
            self.environment == "development"
            or self.dynamodb_endpoint_url == "mock"
            or self.eventbridge_endpoint_url == "mock"
        )
    
    @property
    def ses_reply_to_domain(self) -> str:
        """Domain used in Reply-To address encoding."""
        return self.ses_domain
    
    @property
    def dynamodb_config(self) -> dict:
        """DynamoDB client configuration."""
        config = {"region_name": self.aws_region}
        if self.dynamodb_endpoint_url and self.dynamodb_endpoint_url != "mock":
            config["endpoint_url"] = self.dynamodb_endpoint_url
        return config
    
    @property
    def s3_config(self) -> dict:
        """S3 client configuration."""
        config = {"region_name": self.aws_region}
        if self.s3_endpoint_url and self.s3_endpoint_url != "mock":
            config["endpoint_url"] = self.s3_endpoint_url
        return config
    
    @property
    def eventbridge_config(self) -> dict:
        """EventBridge client configuration."""
        config = {"region_name": self.aws_region}
        if self.eventbridge_endpoint_url and self.eventbridge_endpoint_url != "mock":
            config["endpoint_url"] = self.eventbridge_endpoint_url
        return config
    
    @property
    def ses_config(self) -> dict:
        """SES client configuration."""
        config = {"region_name": self.aws_region}
        if self.ses_endpoint_url and self.ses_endpoint_url != "mock":
            config["endpoint_url"] = self.ses_endpoint_url
        return config
    
    @property
    def textract_config(self) -> dict:
        """Textract client configuration."""
        config = {"region_name": self.aws_region}
        if self.textract_endpoint_url and self.textract_endpoint_url != "mock":
            config["endpoint_url"] = self.textract_endpoint_url
        return config


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Get cached application settings.
    
    Uses lru_cache to ensure settings are loaded only once.
    Call Settings.model_validate({}) in tests to override.
    """
    return Settings()
