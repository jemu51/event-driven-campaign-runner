# Shared Infrastructure for Recruitment Agents
"""
Shared infrastructure components for all recruitment agents.

This package provides:
- State machine definitions (ProviderStatus, valid transitions)
- Pydantic models for events and DynamoDB items
- Tool implementations for DynamoDB, EventBridge, SES, S3
- LLM infrastructure for Bedrock Claude integration
- Configuration management
- Custom exceptions
"""

from agents.shared.state_machine import ProviderStatus, VALID_TRANSITIONS, validate_transition
from agents.shared.exceptions import (
    ProviderNotFoundError,
    InvalidStateTransitionError,
    EventPublishError,
    InvalidEmailFormatError,
    DocumentProcessingError,
)
from agents.shared.config import Settings, get_settings

# LLM Infrastructure (optional import - may not be available in all contexts)
try:
    from agents.shared.llm import (
        BedrockLLMClient,
        get_llm_client,
        LLMSettings,
        get_llm_settings,
        EmailGenerationOutput,
        ResponseClassificationOutput,
        EquipmentExtractionOutput,
        InsuranceDocumentOutput,
        ScreeningDecisionOutput,
    )
    _llm_available = True
except ImportError:
    _llm_available = False

__all__ = [
    # State machine
    "ProviderStatus",
    "VALID_TRANSITIONS",
    "validate_transition",
    # Exceptions
    "ProviderNotFoundError",
    "InvalidStateTransitionError",
    "EventPublishError",
    "InvalidEmailFormatError",
    "DocumentProcessingError",
    # Config
    "Settings",
    "get_settings",
]

# Add LLM exports if available
if _llm_available:
    __all__.extend([
        # LLM Client
        "BedrockLLMClient",
        "get_llm_client",
        # LLM Settings
        "LLMSettings",
        "get_llm_settings",
        # LLM Schemas
        "EmailGenerationOutput",
        "ResponseClassificationOutput",
        "EquipmentExtractionOutput",
        "InsuranceDocumentOutput",
        "ScreeningDecisionOutput",
    ])
