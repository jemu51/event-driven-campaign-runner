"""
Structured Output Schemas for LLM Responses

Pydantic models that define the expected structure of LLM outputs.
All LLM calls return one of these models for type-safe, validated responses.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class EmailGenerationOutput(BaseModel):
    """
    Structured output for email generation.
    
    Used by the Communication Agent to generate personalized emails
    for provider outreach, follow-ups, and document requests.
    """
    
    subject: str = Field(
        ...,
        max_length=200,
        description="Email subject line, concise and action-oriented",
    )
    body_text: str = Field(
        ...,
        description="Plain text email body with proper formatting",
    )
    tone: Literal["formal", "professional", "friendly"] = Field(
        ...,
        description="Tone used in the email based on provider type",
    )
    includes_call_to_action: bool = Field(
        ...,
        description="Whether the email includes a clear call-to-action",
    )
    personalization_elements: list[str] = Field(
        default_factory=list,
        description="List of personalization elements used (e.g., provider name, market)",
    )


class ResponseClassificationOutput(BaseModel):
    """
    Structured output for provider response classification.
    
    Used by the Screening Agent to classify the intent of
    provider email responses.
    """
    
    intent: Literal["positive", "negative", "question", "document_only", "ambiguous"] = Field(
        ...,
        description="Classified intent of the provider response",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the classification (0.0-1.0)",
    )
    reasoning: str = Field(
        ...,
        description="Explanation of why this classification was chosen",
    )
    key_phrases: list[str] = Field(
        default_factory=list,
        description="Key phrases from the response that influenced classification",
    )
    sentiment: Literal["positive", "neutral", "negative"] = Field(
        ...,
        description="Overall sentiment of the response",
    )


class EquipmentExtractionOutput(BaseModel):
    """
    Structured output for equipment extraction from provider responses.
    
    Used by the Screening Agent to identify equipment, certifications,
    and travel willingness from provider emails.
    """
    
    equipment_confirmed: list[str] = Field(
        default_factory=list,
        description="Equipment types the provider confirms having (use keywords from requirements_schema.json)",
    )
    equipment_denied: list[str] = Field(
        default_factory=list,
        description="Equipment types the provider explicitly says they don't have",
    )
    travel_willing: bool | None = Field(
        default=None,
        description="Whether provider is willing to travel (None if not mentioned)",
    )
    certifications_mentioned: list[str] = Field(
        default_factory=list,
        description="Certifications mentioned by the provider",
    )
    concerns_raised: list[str] = Field(
        default_factory=list,
        description="Any concerns or limitations stated by the provider",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the extraction (0.0-1.0)",
    )


class InsuranceDocumentOutput(BaseModel):
    """
    Structured output for insurance document analysis.
    
    Used by the Screening Agent to validate insurance certificates
    extracted via Textract OCR.
    """
    
    is_insurance_document: bool = Field(
        ...,
        description="Whether the document is an insurance certificate",
    )
    policy_holder: str | None = Field(
        default=None,
        description="Name of the policy holder",
    )
    coverage_amount: int | None = Field(
        default=None,
        description="Coverage amount in dollars (integer)",
    )
    expiry_date: date | None = Field(
        default=None,
        description="Policy expiry date",
    )
    policy_number: str | None = Field(
        default=None,
        description="Insurance policy number",
    )
    insurance_company: str | None = Field(
        default=None,
        description="Name of the insurance company",
    )
    is_valid: bool = Field(
        ...,
        description="Whether the document passes validation rules",
    )
    validation_errors: list[str] = Field(
        default_factory=list,
        description="List of validation errors if any",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the analysis (0.0-1.0)",
    )


class ScreeningDecisionOutput(BaseModel):
    """
    Structured output for final screening decision.
    
    Used by the Screening Agent to make a decision about
    provider qualification based on all available data.
    """
    
    decision: Literal[
        "QUALIFIED",
        "REJECTED",
        "NEEDS_DOCUMENT",
        "NEEDS_CLARIFICATION",
        "UNDER_REVIEW",
        "ESCALATED",
    ] = Field(
        ...,
        description="Screening decision for the provider",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the decision (0.0-1.0)",
    )
    reasoning: str = Field(
        ...,
        description="Explanation of the decision reasoning",
    )
    next_action: str = Field(
        ...,
        description="Recommended next action to take",
    )
    missing_items: list[str] = Field(
        default_factory=list,
        description="Items still missing that prevent qualification",
    )
    questions_for_provider: list[str] = Field(
        default_factory=list,
        description="Follow-up questions to ask the provider",
    )
