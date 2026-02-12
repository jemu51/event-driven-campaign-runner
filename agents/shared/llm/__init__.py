"""
LLM Infrastructure for Recruitment Agents

Provides AWS Bedrock integration with structured output support.
Uses Strands Agents SDK for model invocation.

This package provides:
- BedrockLLMClient for Claude invocation with Pydantic structured output
- LLMSettings for configuration management
- Structured output schemas for email generation, response classification, etc.
"""

from agents.shared.llm.schemas import (
    EmailGenerationOutput,
    ResponseClassificationOutput,
    EquipmentExtractionOutput,
    InsuranceDocumentOutput,
    ScreeningDecisionOutput,
)
from agents.shared.llm.config import LLMSettings, get_llm_settings
from agents.shared.llm.bedrock_client import BedrockLLMClient, get_llm_client


__all__ = [
    # Client
    "BedrockLLMClient",
    "get_llm_client",
    # Settings
    "LLMSettings",
    "get_llm_settings",
    # Schemas
    "EmailGenerationOutput",
    "ResponseClassificationOutput",
    "EquipmentExtractionOutput",
    "InsuranceDocumentOutput",
    "ScreeningDecisionOutput",
]
