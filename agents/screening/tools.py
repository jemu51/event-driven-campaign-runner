"""
Screening Agent Tools

Idempotent tools for provider response classification, keyword extraction,
document processing, and screening evaluation.
"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError
import structlog

from agents.screening.config import get_screening_config
from agents.screening.models import (
    CertificationMatch,
    DocumentAnalysis,
    DocumentValidationResult,
    EquipmentMatch,
    InsuranceValidation,
    KeywordExtractionResult,
    ResponseClassification,
    ResponseIntent,
    ScreeningDecision,
    ScreeningResult,
    TextractJobInfo,
)
from agents.shared.config import get_settings
from agents.shared.exceptions import DocumentProcessingError
from agents.shared.models.events import Attachment, DocumentType

log = structlog.get_logger()


# --- Equipment and Certification Keywords from contracts/requirements_schema.json ---

EQUIPMENT_KEYWORDS: dict[str, list[str]] = {
    "bucket_truck": [
        "bucket truck", "bucket", "aerial lift", "boom truck",
        "cherry picker", "man lift", "aerial platform",
    ],
    "spectrum_analyzer": [
        "spectrum analyzer", "spectrum", "rf analyzer",
        "signal analyzer", "frequency analyzer",
    ],
    "fiber_splicer": [
        "fiber splicer", "fusion splicer", "splicer",
        "fiber optic splicer", "splicing machine",
    ],
    "otdr": [
        "otdr", "optical time domain reflectometer",
        "fiber tester", "reflectometer",
    ],
    "cable_tester": [
        "cable tester", "network tester", "fluke",
        "cable certifier", "lan tester",
    ],
    "ladder": [
        "ladder", "extension ladder", "24ft ladder",
        "28ft ladder", "32ft ladder",
    ],
}

CERTIFICATION_KEYWORDS: dict[str, list[str]] = {
    "comptia_network_plus": [
        "comptia network+", "comptia network plus", "network+", "n10",
    ],
    "bicsi": [
        "bicsi", "rcdd", "bicsi installer", "bicsi technician",
    ],
    "fcc_license": [
        "fcc", "fcc license", "grol", "general radiotelephone", "radio operator",
    ],
    "osha_10": [
        "osha 10", "osha10", "osha-10", "10 hour osha",
    ],
    "osha_30": [
        "osha 30", "osha30", "osha-30", "30 hour osha",
    ],
}

TRAVEL_POSITIVE_KEYWORDS = [
    "can travel", "willing to travel", "will travel", "travel is ok",
    "travel is fine", "no problem with travel", "available to travel",
    "can relocate", "mobile", "flexible location",
]

TRAVEL_NEGATIVE_KEYWORDS = [
    "cannot travel", "can't travel", "not willing to travel",
    "no travel", "local only", "not mobile", "cannot relocate",
]


def _normalize_text(text: str) -> str:
    """Normalize text for keyword matching."""
    return text.lower().strip()


def classify_response(
    response_body: str,
    has_attachments: bool = False,
) -> ResponseClassification:
    """
    Classify the intent of a provider's email response.
    
    Uses keyword-based classification by default, with optional LLM classification.
    
    Args:
        response_body: Email body text
        has_attachments: Whether the email has attachments
        
    Returns:
        ResponseClassification with intent and confidence
    """
    config = get_screening_config()
    normalized = _normalize_text(response_body)
    
    # Count keyword matches
    positive_matches = []
    negative_matches = []
    question_matches = []
    
    for keyword in config.positive_response_keywords:
        if keyword.lower() in normalized:
            positive_matches.append(keyword)
    
    for keyword in config.negative_response_keywords:
        if keyword.lower() in normalized:
            negative_matches.append(keyword)
    
    for keyword in config.question_response_keywords:
        if keyword.lower() in normalized:
            question_matches.append(keyword)
    
    # Determine intent based on keyword counts
    positive_score = len(positive_matches)
    negative_score = len(negative_matches)
    question_score = len(question_matches)
    
    # Decision logic
    if negative_score > 0 and negative_score >= positive_score:
        intent = ResponseIntent.NEGATIVE
        confidence = min(0.9, 0.5 + (negative_score * 0.1))
        matched = negative_matches
    elif positive_score > 0 and positive_score > question_score:
        intent = ResponseIntent.POSITIVE
        confidence = min(0.9, 0.5 + (positive_score * 0.1))
        matched = positive_matches
    elif question_score > 0:
        intent = ResponseIntent.QUESTION
        confidence = min(0.85, 0.5 + (question_score * 0.1))
        matched = question_matches
    elif has_attachments and len(normalized) < 100:
        # Short message with attachment likely just document submission
        intent = ResponseIntent.DOCUMENT_ONLY
        confidence = 0.7
        matched = []
    else:
        intent = ResponseIntent.AMBIGUOUS
        confidence = 0.5
        matched = positive_matches + negative_matches + question_matches
    
    log.info(
        "response_classified",
        intent=intent.value,
        confidence=confidence,
        positive_matches=positive_score,
        negative_matches=negative_score,
        question_matches=question_score,
        has_attachments=has_attachments,
    )
    
    return ResponseClassification(
        intent=intent,
        confidence=confidence,
        keywords_matched=matched,
        has_attachment=has_attachments,
    )


def extract_keywords(
    response_body: str,
    required_equipment: list[str] | None = None,
    required_certifications: list[str] | None = None,
) -> KeywordExtractionResult:
    """
    Extract equipment, certification, and travel keywords from response.
    
    Args:
        response_body: Email body text
        required_equipment: List of required equipment types to look for
        required_certifications: List of required certification types
        
    Returns:
        KeywordExtractionResult with all extracted information
    """
    normalized = _normalize_text(response_body)
    
    # Equipment matching
    equipment_matches = []
    equipment_to_check = required_equipment if required_equipment else list(EQUIPMENT_KEYWORDS.keys())
    
    for equipment_type in equipment_to_check:
        keywords = EQUIPMENT_KEYWORDS.get(equipment_type, [])
        matched_keywords = [kw for kw in keywords if kw.lower() in normalized]
        
        equipment_matches.append(EquipmentMatch(
            equipment_type=equipment_type,
            matched=len(matched_keywords) > 0,
            matched_keywords=matched_keywords,
            confidence=1.0 if matched_keywords else 0.0,
        ))
    
    # Certification matching
    cert_matches = []
    certs_to_check = required_certifications if required_certifications else list(CERTIFICATION_KEYWORDS.keys())
    
    for cert_type in certs_to_check:
        keywords = CERTIFICATION_KEYWORDS.get(cert_type, [])
        matched_keywords = [kw for kw in keywords if kw.lower() in normalized]
        
        cert_matches.append(CertificationMatch(
            certification_type=cert_type,
            matched=len(matched_keywords) > 0,
            matched_keywords=matched_keywords,
        ))
    
    # Travel keyword matching
    travel_confirmed: bool | None = None
    travel_keywords_matched = []
    
    for keyword in TRAVEL_POSITIVE_KEYWORDS:
        if keyword.lower() in normalized:
            travel_confirmed = True
            travel_keywords_matched.append(keyword)
    
    if travel_confirmed is None:
        for keyword in TRAVEL_NEGATIVE_KEYWORDS:
            if keyword.lower() in normalized:
                travel_confirmed = False
                travel_keywords_matched.append(keyword)
    
    log.info(
        "keywords_extracted",
        equipment_found=[m.equipment_type for m in equipment_matches if m.matched],
        certs_found=[m.certification_type for m in cert_matches if m.matched],
        travel_confirmed=travel_confirmed,
    )
    
    return KeywordExtractionResult(
        equipment_matches=equipment_matches,
        certification_matches=cert_matches,
        travel_confirmed=travel_confirmed,
        travel_keywords_matched=travel_keywords_matched,
    )


def trigger_textract_async(
    document_s3_path: str,
    campaign_id: str,
    provider_id: str,
    document_type: str | None = None,
) -> TextractJobInfo:
    """
    Start an async Textract job for document analysis.
    
    The job will complete asynchronously and publish to SNS,
    which triggers the TextractCompletion Lambda.
    
    Args:
        document_s3_path: S3 URI of the document (s3://bucket/key)
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        document_type: Expected document type (optional)
        
    Returns:
        TextractJobInfo with job details
        
    Raises:
        DocumentProcessingError: If Textract job fails to start
    """
    config = get_screening_config()
    settings = get_settings()
    
    # Parse S3 path
    if not document_s3_path.startswith("s3://"):
        raise ValueError(f"Invalid S3 path: {document_s3_path}")
    
    parts = document_s3_path[5:].split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid S3 path format: {document_s3_path}")
    
    bucket, key = parts
    
    log.info(
        "starting_textract_job",
        campaign_id=campaign_id,
        provider_id=provider_id,
        document_type=document_type,
        s3_bucket=bucket,
        s3_key=key,
    )
    
    try:
        textract = boto3.client("textract", **settings.textract_config)
        
        # Build Textract request
        request: dict[str, Any] = {
            "DocumentLocation": {
                "S3Object": {
                    "Bucket": bucket,
                    "Name": key,
                }
            },
            "FeatureTypes": config.textract_features,
        }
        
        # Add notification config if SNS topic is configured
        if config.textract_sns_topic_arn and config.textract_role_arn:
            request["NotificationChannel"] = {
                "SNSTopicArn": config.textract_sns_topic_arn,
                "RoleArn": config.textract_role_arn,
            }
        
        # Add client request token for idempotency
        request["ClientRequestToken"] = f"{campaign_id}_{provider_id}_{key.split('/')[-1]}"[:64]
        
        response = textract.start_document_analysis(**request)
        job_id = response["JobId"]
        
        log.info(
            "textract_job_started",
            job_id=job_id,
            campaign_id=campaign_id,
            provider_id=provider_id,
        )
        
        return TextractJobInfo(
            job_id=job_id,
            document_s3_path=document_s3_path,
            document_type=document_type,
            campaign_id=campaign_id,
            provider_id=provider_id,
            started_at=int(datetime.now(timezone.utc).timestamp()),
        )
        
    except ClientError as e:
        log.error(
            "textract_start_failed",
            error=str(e),
            campaign_id=campaign_id,
            provider_id=provider_id,
        )
        raise DocumentProcessingError(
            message=f"Failed to start Textract job: {e}",
            document_path=document_s3_path,
            operation="start_document_analysis",
        ) from e


def _parse_date(date_str: str) -> date | None:
    """Parse date from various formats."""
    if not date_str:
        return None
    
    # Common date formats
    formats = [
        "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d/%m/%Y", "%d-%m-%Y",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    
    return None


def _parse_currency(amount_str: str) -> int | None:
    """Parse currency amount to integer dollars."""
    if not amount_str:
        return None
    
    # Remove common currency symbols and commas
    cleaned = re.sub(r"[$,\s]", "", amount_str)
    
    # Handle millions notation
    if "m" in cleaned.lower():
        cleaned = re.sub(r"[mM]", "", cleaned)
        try:
            return int(float(cleaned) * 1_000_000)
        except ValueError:
            pass
    
    try:
        # Handle decimal amounts
        value = float(cleaned)
        return int(value)
    except ValueError:
        return None


def evaluate_document_ocr(
    document_type: str,
    ocr_text: str | None,
    extracted_fields: dict[str, Any] | None,
    confidence_scores: dict[str, float] | None = None,
) -> DocumentAnalysis:
    """
    Evaluate OCR results and validate document against requirements.
    
    Args:
        document_type: Type of document (insurance_certificate, license, etc.)
        ocr_text: Raw OCR text (optional)
        extracted_fields: Pre-extracted fields from Textract
        confidence_scores: Confidence scores per field
        
    Returns:
        DocumentAnalysis with validation results
    """
    config = get_screening_config()
    extracted = extracted_fields or {}
    scores = confidence_scores or {}
    errors: list[str] = []
    warnings: list[str] = []
    
    log.info(
        "evaluating_document",
        document_type=document_type,
        has_ocr_text=bool(ocr_text),
        field_count=len(extracted),
    )
    
    # Document-type specific validation
    insurance_details: InsuranceValidation | None = None
    
    if document_type == DocumentType.INSURANCE_CERTIFICATE.value:
        # Extract insurance-specific fields
        expiry_str = extracted.get("expiry_date", "")
        coverage_str = extracted.get("coverage_amount", "")
        policy_holder = extracted.get("policy_holder", "")
        policy_number = extracted.get("policy_number", "")
        
        expiry_date = _parse_date(str(expiry_str)) if expiry_str else None
        coverage_amount = _parse_currency(str(coverage_str)) if coverage_str else None
        
        # Validate expiry
        is_expired = False
        days_until_expiry: int | None = None
        
        if expiry_date:
            today = date.today()
            days_until_expiry = (expiry_date - today).days
            is_expired = expiry_date < today
            
            if is_expired:
                errors.append(f"Insurance expired on {expiry_date.isoformat()}")
            elif days_until_expiry < config.insurance_expiry_buffer_days:
                warnings.append(
                    f"Insurance expires in {days_until_expiry} days "
                    f"(< {config.insurance_expiry_buffer_days} day buffer)"
                )
        else:
            warnings.append("Could not extract expiry date from document")
        
        # Validate coverage amount
        is_below_minimum = False
        if coverage_amount:
            if coverage_amount < config.insurance_min_coverage_dollars:
                is_below_minimum = True
                errors.append(
                    f"Coverage ${coverage_amount:,} is below "
                    f"${config.insurance_min_coverage_dollars:,} minimum"
                )
        else:
            warnings.append("Could not extract coverage amount from document")
        
        # Check confidence thresholds
        for field_name, score in scores.items():
            if score < config.textract_confidence_threshold:
                warnings.append(
                    f"Low confidence ({score:.2f}) for field: {field_name}"
                )
        
        insurance_details = InsuranceValidation(
            valid=not is_expired and not is_below_minimum and bool(coverage_amount),
            coverage_amount=coverage_amount,
            expiry_date=expiry_date,
            policy_holder=str(policy_holder) if policy_holder else None,
            policy_number=str(policy_number) if policy_number else None,
            is_expired=is_expired,
            is_below_minimum=is_below_minimum,
            days_until_expiry=days_until_expiry,
        )
        
        overall_valid = insurance_details.valid
        
    else:
        # Generic validation for other document types
        # Check for required fields based on type
        overall_valid = len(errors) == 0
    
    validation = DocumentValidationResult(
        document_type=document_type,
        valid=overall_valid,
        errors=errors,
        warnings=warnings,
        extracted_fields=extracted,
        confidence_scores=scores,
    )
    
    log.info(
        "document_evaluation_complete",
        document_type=document_type,
        valid=overall_valid,
        error_count=len(errors),
        warning_count=len(warnings),
    )
    
    return DocumentAnalysis(
        document_type=document_type,
        s3_path="",  # Caller should set this
        job_id="",   # Caller should set this
        validation=validation,
        insurance_details=insurance_details,
        raw_text=ocr_text[:1000] if ocr_text else None,  # Truncate for storage
    )


def determine_screening_outcome(
    campaign_id: str,
    provider_id: str,
    response_classification: ResponseClassification | None,
    keyword_extraction: KeywordExtractionResult | None,
    document_analyses: list[DocumentAnalysis],
    required_equipment: list[str],
    required_documents: list[str],
    travel_required: bool,
    existing_equipment_confirmed: list[str] | None = None,
    existing_documents_uploaded: list[str] | None = None,
) -> ScreeningResult:
    """
    Determine the screening outcome based on all available information.
    
    This is the main decision logic that determines if a provider should be
    QUALIFIED, REJECTED, or need further action.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        response_classification: Classification of provider's response
        keyword_extraction: Extracted keywords from response
        document_analyses: List of analyzed documents
        required_equipment: Required equipment types
        required_documents: Required document types
        travel_required: Whether travel is required
        existing_equipment_confirmed: Previously confirmed equipment
        existing_documents_uploaded: Previously uploaded documents
        
    Returns:
        ScreeningResult with decision and reasoning
    """
    config = get_screening_config()
    
    # Aggregate equipment from response and existing state
    equipment_confirmed = list(existing_equipment_confirmed or [])
    if keyword_extraction:
        for match in keyword_extraction.equipment_matches:
            if match.matched and match.equipment_type not in equipment_confirmed:
                equipment_confirmed.append(match.equipment_type)
    
    equipment_missing = [eq for eq in required_equipment if eq not in equipment_confirmed]
    
    # Aggregate certifications
    certifications_found: list[str] = []
    if keyword_extraction:
        for match in keyword_extraction.certification_matches:
            if match.matched:
                certifications_found.append(match.certification_type)
    
    # Aggregate documents
    documents_validated: list[str] = list(existing_documents_uploaded or [])
    documents_with_errors: list[str] = []
    insurance_coverage: int | None = None
    insurance_expiry: date | None = None
    
    for analysis in document_analyses:
        if analysis.validation.valid:
            if analysis.document_type not in documents_validated:
                documents_validated.append(analysis.document_type)
            
            # Extract insurance details
            if analysis.insurance_details:
                insurance_coverage = analysis.insurance_details.coverage_amount
                insurance_expiry = analysis.insurance_details.expiry_date
        else:
            documents_with_errors.append(analysis.document_type)
    
    documents_pending = [doc for doc in required_documents if doc not in documents_validated]
    
    # Determine travel status
    travel_confirmed = None
    if keyword_extraction:
        travel_confirmed = keyword_extraction.travel_confirmed
    
    # Build reasoning
    reasoning_parts: list[str] = []
    
    # Decision logic
    decision: ScreeningDecision
    confidence = 0.8
    next_action: str | None = None
    questions: list[str] = []
    
    # Check for negative response
    if response_classification and response_classification.intent == ResponseIntent.NEGATIVE:
        decision = ScreeningDecision.REJECTED
        confidence = response_classification.confidence
        reasoning_parts.append("Provider declined the opportunity")
    
    # Check for questions needing clarification
    elif response_classification and response_classification.intent == ResponseIntent.QUESTION:
        decision = ScreeningDecision.NEEDS_CLARIFICATION
        confidence = response_classification.confidence
        reasoning_parts.append("Provider has questions that need to be answered")
        next_action = "send_clarification"
    
    # Check equipment requirements
    elif equipment_missing:
        if len(equipment_missing) == len(required_equipment):
            # No required equipment confirmed
            decision = ScreeningDecision.NEEDS_CLARIFICATION
            reasoning_parts.append(f"Required equipment not confirmed: {', '.join(equipment_missing)}")
            questions.append(f"Do you have access to: {', '.join(equipment_missing)}?")
            next_action = "send_follow_up"
        else:
            # Partial equipment match
            decision = ScreeningDecision.UNDER_REVIEW
            reasoning_parts.append(
                f"Partial equipment match. Confirmed: {', '.join(equipment_confirmed)}. "
                f"Missing: {', '.join(equipment_missing)}"
            )
    
    # Check travel requirement
    elif travel_required and travel_confirmed is False:
        decision = ScreeningDecision.REJECTED
        reasoning_parts.append("Provider cannot travel but travel is required")
    
    # Check document requirements
    elif documents_pending:
        decision = ScreeningDecision.NEEDS_DOCUMENT
        reasoning_parts.append(f"Missing required documents: {', '.join(documents_pending)}")
        next_action = "request_document"
    
    # Check for document validation errors
    elif documents_with_errors:
        decision = ScreeningDecision.NEEDS_DOCUMENT
        reasoning_parts.append(
            f"Documents failed validation: {', '.join(documents_with_errors)}. "
            "Provider should resubmit."
        )
        next_action = "request_document_retry"
    
    # All requirements met
    elif config.enable_auto_qualification:
        decision = ScreeningDecision.QUALIFIED
        reasoning_parts.append("All requirements verified:")
        if equipment_confirmed:
            reasoning_parts.append(f"  - Equipment: {', '.join(equipment_confirmed)}")
        if documents_validated:
            reasoning_parts.append(f"  - Documents: {', '.join(documents_validated)}")
        if travel_required and travel_confirmed:
            reasoning_parts.append("  - Travel: Confirmed")
        if insurance_coverage:
            reasoning_parts.append(f"  - Insurance: ${insurance_coverage:,}")
        confidence = 0.95
    
    # Default to under review
    else:
        decision = ScreeningDecision.UNDER_REVIEW
        reasoning_parts.append("Manual review required before final qualification")
    
    # Handle ambiguous responses
    if response_classification and response_classification.intent == ResponseIntent.AMBIGUOUS:
        if decision not in (ScreeningDecision.QUALIFIED, ScreeningDecision.REJECTED):
            decision = ScreeningDecision.UNDER_REVIEW
            reasoning_parts.insert(0, "Response intent was ambiguous.")
            confidence = min(confidence, 0.6)
    
    reasoning = " ".join(reasoning_parts)
    
    log.info(
        "screening_decision_made",
        campaign_id=campaign_id,
        provider_id=provider_id,
        decision=decision.value,
        confidence=confidence,
        equipment_confirmed=equipment_confirmed,
        equipment_missing=equipment_missing,
        documents_validated=documents_validated,
        documents_pending=documents_pending,
    )
    
    return ScreeningResult(
        campaign_id=campaign_id,
        provider_id=provider_id,
        decision=decision,
        confidence=confidence,
        reasoning=reasoning,
        response_classification=response_classification,
        keyword_extraction=keyword_extraction,
        document_analyses=document_analyses,
        equipment_confirmed=equipment_confirmed,
        equipment_missing=equipment_missing,
        certifications_found=certifications_found,
        travel_confirmed=travel_confirmed,
        documents_valid=len(documents_validated) > 0 and len(documents_with_errors) == 0,
        insurance_coverage=insurance_coverage,
        insurance_expiry=insurance_expiry,
        next_action=next_action,
        missing_documents=documents_pending,
        questions_for_provider=questions,
    )


def map_decision_to_status(
    decision: ScreeningDecision,
    current_status: str | None = None,
) -> str:
    """
    Map screening decision to provider status.
    
    Args:
        decision: Screening decision
        current_status: Current provider status (for context-aware mapping)
        
    Returns:
        Provider status string for state transition
    """
    mapping = {
        ScreeningDecision.QUALIFIED: "QUALIFIED",
        ScreeningDecision.REJECTED: "REJECTED",
        ScreeningDecision.NEEDS_DOCUMENT: "WAITING_DOCUMENT",
        ScreeningDecision.NEEDS_CLARIFICATION: "WAITING_RESPONSE",
        ScreeningDecision.UNDER_REVIEW: "UNDER_REVIEW",
        ScreeningDecision.ESCALATED: "ESCALATED",
    }
    
    # Context-aware mapping: if in DOCUMENT_PROCESSING and need clarification,
    # go to UNDER_REVIEW instead of WAITING_RESPONSE (invalid transition)
    if (
        decision == ScreeningDecision.NEEDS_CLARIFICATION
        and current_status == "DOCUMENT_PROCESSING"
    ):
        return "UNDER_REVIEW"
    
    return mapping.get(decision, "UNDER_REVIEW")
