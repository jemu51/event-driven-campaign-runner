"""
Screening Agent Models

Pydantic models for screening operations.
"""

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResponseIntent(str, Enum):
    """Classification of provider response intent."""
    
    POSITIVE = "positive"
    """Provider is interested and willing to participate."""
    
    NEGATIVE = "negative"
    """Provider declines or is not interested."""
    
    QUESTION = "question"
    """Provider has questions or needs clarification."""
    
    DOCUMENT_ONLY = "document_only"
    """Response contains only document attachment, no clear intent."""
    
    AMBIGUOUS = "ambiguous"
    """Intent cannot be determined from response."""


class ScreeningDecision(str, Enum):
    """Screening decision outcome."""
    
    QUALIFIED = "QUALIFIED"
    """Provider meets all requirements."""
    
    REJECTED = "REJECTED"
    """Provider does not meet requirements or declined."""
    
    NEEDS_DOCUMENT = "NEEDS_DOCUMENT"
    """Provider needs to submit required documents."""
    
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    """More information needed from provider."""
    
    UNDER_REVIEW = "UNDER_REVIEW"
    """Manual review required."""
    
    ESCALATED = "ESCALATED"
    """Edge case requiring human intervention."""


class ResponseClassification(BaseModel):
    """
    Classification result of a provider's response.
    """
    
    model_config = ConfigDict(frozen=True)
    
    intent: ResponseIntent = Field(..., description="Detected intent of the response")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the classification",
    )
    keywords_matched: list[str] = Field(
        default_factory=list,
        description="Keywords that contributed to the classification",
    )
    reasoning: str | None = Field(
        default=None,
        description="Explanation for the classification (if LLM-based)",
    )
    has_attachment: bool = Field(
        default=False,
        description="Whether response includes attachments",
    )


class EquipmentMatch(BaseModel):
    """
    Equipment keyword match result.
    """
    
    model_config = ConfigDict(frozen=True)
    
    equipment_type: str = Field(..., description="Equipment type ID (e.g., bucket_truck)")
    matched: bool = Field(..., description="Whether equipment was found in response")
    matched_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords that matched for this equipment",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence of the match",
    )


class CertificationMatch(BaseModel):
    """
    Certification keyword match result.
    """
    
    model_config = ConfigDict(frozen=True)
    
    certification_type: str = Field(
        ...,
        description="Certification type ID (e.g., comptia_network_plus)",
    )
    matched: bool = Field(..., description="Whether certification was found")
    matched_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords that matched",
    )


class KeywordExtractionResult(BaseModel):
    """
    Result of keyword extraction from provider response.
    """
    
    model_config = ConfigDict(frozen=True)
    
    equipment_matches: list[EquipmentMatch] = Field(
        default_factory=list,
        description="Equipment matches found in response",
    )
    certification_matches: list[CertificationMatch] = Field(
        default_factory=list,
        description="Certification matches found in response",
    )
    travel_confirmed: bool | None = Field(
        default=None,
        description="Whether travel willingness was confirmed (None if not mentioned)",
    )
    travel_keywords_matched: list[str] = Field(
        default_factory=list,
        description="Keywords matched for travel confirmation",
    )


class DocumentValidationResult(BaseModel):
    """
    Result of document validation.
    """
    
    model_config = ConfigDict(frozen=True)
    
    document_type: str = Field(..., description="Type of document validated")
    valid: bool = Field(..., description="Whether document passes all validation rules")
    errors: list[str] = Field(
        default_factory=list,
        description="Validation errors, if any",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking warnings",
    )
    extracted_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Fields extracted from document",
    )
    confidence_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Confidence score per extracted field",
    )


class InsuranceValidation(BaseModel):
    """
    Insurance document validation details.
    """
    
    model_config = ConfigDict(frozen=True)
    
    valid: bool = Field(..., description="Whether insurance meets requirements")
    coverage_amount: int | None = Field(
        default=None,
        description="Coverage amount in dollars",
    )
    expiry_date: date | None = Field(
        default=None,
        description="Policy expiry date",
    )
    policy_holder: str | None = Field(
        default=None,
        description="Name on policy",
    )
    policy_number: str | None = Field(
        default=None,
        description="Policy number",
    )
    is_expired: bool = Field(default=False, description="Whether policy has expired")
    is_below_minimum: bool = Field(
        default=False,
        description="Whether coverage is below minimum",
    )
    days_until_expiry: int | None = Field(
        default=None,
        description="Days remaining until expiry",
    )


class DocumentAnalysis(BaseModel):
    """
    Complete analysis of a document from Textract.
    """
    
    model_config = ConfigDict(frozen=True)
    
    document_type: str = Field(..., description="Classified document type")
    s3_path: str = Field(..., description="S3 path of the document")
    job_id: str = Field(..., description="Textract job ID")
    validation: DocumentValidationResult = Field(
        ...,
        description="Validation result",
    )
    insurance_details: InsuranceValidation | None = Field(
        default=None,
        description="Insurance-specific details (if applicable)",
    )
    raw_text: str | None = Field(
        default=None,
        description="Raw OCR text (truncated for storage)",
    )


class ScreeningResult(BaseModel):
    """
    Complete screening result for a provider.
    """
    
    model_config = ConfigDict(frozen=True)
    
    campaign_id: str = Field(..., description="Campaign identifier")
    provider_id: str = Field(..., description="Provider identifier")
    decision: ScreeningDecision = Field(..., description="Screening decision")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the decision",
    )
    reasoning: str = Field(..., description="Human-readable explanation")
    
    # Response analysis
    response_classification: ResponseClassification | None = Field(
        default=None,
        description="Response classification (if from email response)",
    )
    keyword_extraction: KeywordExtractionResult | None = Field(
        default=None,
        description="Keyword extraction results",
    )
    
    # Document analysis
    document_analyses: list[DocumentAnalysis] = Field(
        default_factory=list,
        description="Analysis results for submitted documents",
    )
    
    # Aggregated results
    equipment_confirmed: list[str] = Field(
        default_factory=list,
        description="Equipment provider confirmed having",
    )
    equipment_missing: list[str] = Field(
        default_factory=list,
        description="Required equipment not confirmed",
    )
    certifications_found: list[str] = Field(
        default_factory=list,
        description="Certifications found/confirmed",
    )
    travel_confirmed: bool | None = Field(
        default=None,
        description="Whether travel willingness confirmed",
    )
    documents_valid: bool | None = Field(
        default=None,
        description="Whether all required documents are valid",
    )
    insurance_coverage: int | None = Field(
        default=None,
        description="Verified insurance coverage amount",
    )
    insurance_expiry: date | None = Field(
        default=None,
        description="Insurance expiry date",
    )
    
    # Next actions
    next_action: str | None = Field(
        default=None,
        description="Next action to take (e.g., 'send_follow_up', 'request_document')",
    )
    missing_documents: list[str] = Field(
        default_factory=list,
        description="Documents still required",
    )
    questions_for_provider: list[str] = Field(
        default_factory=list,
        description="Questions to ask provider",
    )
    
    @property
    def is_terminal(self) -> bool:
        """Check if this decision is terminal (QUALIFIED or REJECTED)."""
        return self.decision in (ScreeningDecision.QUALIFIED, ScreeningDecision.REJECTED)


class TextractJobInfo(BaseModel):
    """
    Information about an async Textract job.
    """
    
    model_config = ConfigDict(frozen=True)
    
    job_id: str = Field(..., description="Textract job ID")
    document_s3_path: str = Field(..., description="S3 path of document being processed")
    document_type: str | None = Field(
        default=None,
        description="Expected document type",
    )
    campaign_id: str = Field(..., description="Campaign ID")
    provider_id: str = Field(..., description="Provider ID")
    started_at: int = Field(..., description="Unix timestamp when job was started")
