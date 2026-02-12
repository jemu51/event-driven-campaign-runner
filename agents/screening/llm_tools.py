"""
Screening Agent LLM Tools

LLM-powered tools for response classification, equipment extraction,
document analysis, and screening decisions.
"""

import structlog

from agents.screening.llm_prompts import (
    CLASSIFICATION_SYSTEM_PROMPT,
    EQUIPMENT_EXTRACTION_SYSTEM_PROMPT,
    DOCUMENT_ANALYSIS_SYSTEM_PROMPT,
    SCREENING_DECISION_SYSTEM_PROMPT,
    build_classification_prompt,
    build_equipment_extraction_prompt,
    build_document_analysis_prompt,
    build_screening_decision_prompt,
)
from agents.shared.llm import (
    BedrockLLMClient,
    get_llm_client,
    get_llm_settings,
    ResponseClassificationOutput,
    EquipmentExtractionOutput,
    InsuranceDocumentOutput,
    ScreeningDecisionOutput,
)
from agents.shared.llm.bedrock_client import LLMInvocationError, LLMParsingError
from agents.shared.tools.email_thread import (
    create_thread_id,
    load_thread_history,
    format_thread_for_context,
)


log = structlog.get_logger()


def is_llm_screening_enabled() -> bool:
    """
    Check if LLM screening is enabled.
    
    Returns:
        True if LLM is enabled for screening operations
    """
    settings = get_llm_settings()
    return settings.is_feature_enabled("screening")


def load_equipment_keywords() -> dict[str, list[str]]:
    """
    Load equipment keywords from contracts/requirements_schema.json.
    
    Returns:
        Dict mapping equipment types to their keyword synonyms
    """
    # Default keywords matching contracts/requirements_schema.json
    return {
        "bucket_truck": [
            "bucket truck", "boom truck", "aerial lift",
            "cherry picker", "man lift", "bucket",
        ],
        "spectrum_analyzer": [
            "spectrum analyzer", "signal analyzer", "rf analyzer",
            "frequency analyzer", "spectrum",
        ],
        "fiber_splicer": [
            "fiber splicer", "fusion splicer", "fiber optic splicer",
        ],
        "cable_tester": [
            "cable tester", "network tester", "lan tester", "cable analyzer",
        ],
        "ladder": [
            "ladder", "extension ladder", "step ladder", "a-frame",
        ],
        "hand_tools": [
            "hand tools", "basic tools", "tool kit", "toolset",
        ],
    }


def load_certification_keywords() -> list[str]:
    """
    Load certification types from contracts/requirements_schema.json.
    
    Returns:
        List of certification types
    """
    return [
        "CompTIA Network+",
        "BICSI Installer",
        "OSHA 10",
        "OSHA 30",
        "FCC License",
        "Tower Climbing",
    ]


def get_campaign_type(campaign_id: str) -> str:
    """
    Determine campaign type from campaign ID.
    
    Args:
        campaign_id: Campaign identifier
        
    Returns:
        Campaign type string (e.g., "satellite_upgrade")
    """
    # Default to satellite_upgrade for demo
    if "satellite" in campaign_id.lower():
        return "satellite_upgrade"
    elif "fiber" in campaign_id.lower():
        return "fiber_installation"
    else:
        return "general_installation"


def classify_response_with_llm(
    response_body: str,
    has_attachments: bool,
    campaign_type: str,
    previous_status: str,
    conversation_history: str,
    client: BedrockLLMClient | None = None,
) -> ResponseClassificationOutput:
    """
    Classify provider response using LLM.
    
    Considers:
    - Response text semantics
    - Attachment presence
    - Conversation context
    - Campaign requirements
    
    Args:
        response_body: The provider's email text
        has_attachments: Whether email has attachments
        campaign_type: Type of campaign
        previous_status: Provider's previous status
        conversation_history: Formatted conversation history
        client: Optional LLM client (for testing)
        
    Returns:
        ResponseClassificationOutput with intent, confidence, keywords
        
    Raises:
        LLMInvocationError: If LLM call fails
        LLMParsingError: If response cannot be parsed
    """
    log.info(
        "llm_classification_start",
        has_attachments=has_attachments,
        response_length=len(response_body) if response_body else 0,
    )
    
    prompt = build_classification_prompt(
        response_body=response_body or "",
        has_attachments=has_attachments,
        campaign_type=campaign_type,
        previous_status=previous_status,
        conversation_history=conversation_history,
    )
    
    llm_client = client or get_llm_client()
    
    result = llm_client.invoke_structured(
        prompt=prompt,
        output_schema=ResponseClassificationOutput,
        system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
    )
    
    log.info(
        "llm_classification_complete",
        intent=result.intent,
        confidence=result.confidence,
    )
    
    return result


def extract_equipment_with_llm(
    response_body: str,
    required_equipment: list[str],
    equipment_keywords: dict[str, list[str]] | None = None,
    required_certifications: list[str] | None = None,
    client: BedrockLLMClient | None = None,
) -> EquipmentExtractionOutput:
    """
    Extract equipment mentions using LLM.
    
    Uses equipment keywords from contracts/requirements_schema.json
    for context-aware extraction.
    
    Args:
        response_body: The provider's email text
        required_equipment: List of required equipment types
        equipment_keywords: Dict of equipment type to keywords (optional)
        required_certifications: List of required certifications (optional)
        client: Optional LLM client (for testing)
        
    Returns:
        EquipmentExtractionOutput with equipment status
        
    Raises:
        LLMInvocationError: If LLM call fails
        LLMParsingError: If response cannot be parsed
    """
    log.info(
        "llm_equipment_extraction_start",
        required_equipment=required_equipment,
        response_length=len(response_body) if response_body else 0,
    )
    
    # Use default keywords if not provided
    if equipment_keywords is None:
        equipment_keywords = load_equipment_keywords()
    
    prompt = build_equipment_extraction_prompt(
        response_body=response_body or "",
        required_equipment=required_equipment,
        equipment_keywords=equipment_keywords,
        required_certifications=required_certifications,
    )
    
    llm_client = client or get_llm_client()
    
    result = llm_client.invoke_structured(
        prompt=prompt,
        output_schema=EquipmentExtractionOutput,
        system_prompt=EQUIPMENT_EXTRACTION_SYSTEM_PROMPT,
    )
    
    log.info(
        "llm_equipment_extraction_complete",
        confirmed_count=len(result.equipment_confirmed),
        denied_count=len(result.equipment_denied),
        travel_willing=result.travel_willing,
    )
    
    return result


def analyze_document_with_llm(
    document_type: str,
    ocr_text: str,
    required_fields: list[str] | None = None,
    validation_rules: dict[str, str] | None = None,
    client: BedrockLLMClient | None = None,
) -> InsuranceDocumentOutput:
    """
    Analyze document OCR output using LLM.
    
    Handles edge cases where Textract extraction is incomplete.
    
    Args:
        document_type: Type of document (e.g., "insurance_certificate")
        ocr_text: OCR-extracted text from the document
        required_fields: Fields to extract (uses defaults if None)
        validation_rules: Validation rules (uses defaults if None)
        client: Optional LLM client (for testing)
        
    Returns:
        InsuranceDocumentOutput with extracted and validated fields
        
    Raises:
        LLMInvocationError: If LLM call fails
        LLMParsingError: If response cannot be parsed
    """
    log.info(
        "llm_document_analysis_start",
        document_type=document_type,
        ocr_text_length=len(ocr_text) if ocr_text else 0,
    )
    
    # Default fields and rules for insurance certificates
    if required_fields is None:
        if document_type == "insurance_certificate":
            required_fields = [
                "policy_number",
                "policy_holder",
                "insurance_company",
                "coverage_amount",
                "expiry_date",
            ]
        else:
            required_fields = ["document_id", "holder_name", "expiry_date"]
    
    if validation_rules is None:
        validation_rules = {
            "expiry_date": "Must not be expired (after today's date)",
            "coverage_amount": "Must be at least $2,000,000 for insurance",
        }
    
    prompt = build_document_analysis_prompt(
        document_type=document_type,
        ocr_text=ocr_text or "",
        required_fields=required_fields,
        validation_rules=validation_rules,
    )
    
    llm_client = client or get_llm_client()
    
    result = llm_client.invoke_structured(
        prompt=prompt,
        output_schema=InsuranceDocumentOutput,
        system_prompt=DOCUMENT_ANALYSIS_SYSTEM_PROMPT,
    )
    
    log.info(
        "llm_document_analysis_complete",
        document_type=document_type,
        is_valid=result.is_valid,
        coverage_amount=result.coverage_amount,
    )
    
    return result


def make_screening_decision_with_llm(
    campaign_requirements: dict,
    equipment_confirmed: list[str],
    equipment_missing: list[str],
    travel_confirmed: bool | None,
    documents_validated: list[str],
    documents_pending: list[str],
    response_classification: str,
    conversation_history: str,
    client: BedrockLLMClient | None = None,
) -> ScreeningDecisionOutput:
    """
    Make final screening decision using LLM.
    
    Synthesizes all screening data into a decision with reasoning.
    
    Args:
        campaign_requirements: Dict of campaign requirements
        equipment_confirmed: List of confirmed equipment types
        equipment_missing: List of missing equipment types
        travel_confirmed: Whether travel is confirmed (None if not addressed)
        documents_validated: List of validated document types
        documents_pending: List of pending document types
        response_classification: Classification of provider's response
        conversation_history: Formatted conversation summary
        client: Optional LLM client (for testing)
        
    Returns:
        ScreeningDecisionOutput with decision and reasoning
        
    Raises:
        LLMInvocationError: If LLM call fails
        LLMParsingError: If response cannot be parsed
    """
    log.info(
        "llm_screening_decision_start",
        equipment_confirmed=equipment_confirmed,
        equipment_missing=equipment_missing,
        documents_validated=documents_validated,
    )
    
    prompt = build_screening_decision_prompt(
        campaign_requirements=campaign_requirements,
        equipment_confirmed=equipment_confirmed,
        equipment_missing=equipment_missing,
        travel_confirmed=travel_confirmed,
        documents_validated=documents_validated,
        documents_pending=documents_pending,
        response_classification=response_classification,
        conversation_summary=conversation_history,
    )
    
    llm_client = client or get_llm_client()
    
    result = llm_client.invoke_structured(
        prompt=prompt,
        output_schema=ScreeningDecisionOutput,
        system_prompt=SCREENING_DECISION_SYSTEM_PROMPT,
    )
    
    log.info(
        "llm_screening_decision_complete",
        decision=result.decision,
        confidence=result.confidence,
    )
    
    return result


def get_conversation_context_for_screening(
    campaign_id: str,
    provider_id: str,
    market: str,
    max_messages: int = 10,
) -> str:
    """
    Load and format conversation history for screening context.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        market: Provider's market
        max_messages: Maximum messages to include
        
    Returns:
        Formatted conversation history string
    """
    try:
        thread_id = create_thread_id(campaign_id, market, provider_id)
        messages = load_thread_history(thread_id, limit=max_messages)
        
        if messages:
            return format_thread_for_context(messages, max_messages=max_messages)
        else:
            return "[No previous conversation]"
            
    except Exception as e:
        log.debug(
            "conversation_history_load_failed",
            error=str(e),
            campaign_id=campaign_id,
            provider_id=provider_id,
        )
        return "[Conversation history unavailable]"
