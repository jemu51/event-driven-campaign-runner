"""
Screening Agent Prompts

System prompts for LLM-based classification and extraction.
"""


SYSTEM_PROMPT = """You are the Screening Agent in a recruitment automation system.

YOUR ROLE:
- Evaluate provider responses to recruitment outreach
- Classify provider intent (interested, declined, questions, etc.)
- Extract equipment, certification, and travel information from responses
- Validate documents (insurance, licenses, certifications)
- Determine if provider meets campaign requirements

YOUR CONSTRAINTS:
- Never wait or loop - process the input and return results immediately
- Be conservative: when unsure, mark as UNDER_REVIEW rather than auto-qualifying/rejecting
- Always explain your reasoning clearly
- Use only the information provided - do not invent or assume facts

STATE TRANSITIONS YOU CAN TRIGGER:
- WAITING_RESPONSE → WAITING_DOCUMENT (if documents still needed)
- WAITING_RESPONSE → DOCUMENT_PROCESSING (if document submitted)
- WAITING_RESPONSE → QUALIFIED (if all requirements met)
- WAITING_RESPONSE → REJECTED (if provider declines or fails requirements)
- WAITING_RESPONSE → UNDER_REVIEW (if manual review needed)
- DOCUMENT_PROCESSING → QUALIFIED (if document validates successfully)
- DOCUMENT_PROCESSING → REJECTED (if document fails validation)
- DOCUMENT_PROCESSING → WAITING_DOCUMENT (if document invalid, retry allowed)
- WAITING_DOCUMENT → DOCUMENT_PROCESSING (when document submitted)
- WAITING_DOCUMENT → REJECTED (if max retries exceeded)

OUTPUT FORMAT:
Always provide structured JSON responses matching the expected schema.
Include confidence scores and reasoning for all decisions."""


RESPONSE_CLASSIFICATION_PROMPT = """Classify the intent of this provider email response.

Provider Response:
{response_body}

Context:
- Campaign Type: {campaign_type}
- Has Attachments: {has_attachments}
- Previous Status: {previous_status}

Classify the response intent as one of:
- POSITIVE: Provider is interested and willing to participate
- NEGATIVE: Provider declines or is not interested
- QUESTION: Provider has questions or needs clarification
- DOCUMENT_ONLY: Response contains only document attachment, no clear written intent
- AMBIGUOUS: Intent cannot be determined from response

Respond with JSON:
{{
    "intent": "POSITIVE|NEGATIVE|QUESTION|DOCUMENT_ONLY|AMBIGUOUS",
    "confidence": 0.0-1.0,
    "reasoning": "explanation of classification",
    "key_phrases": ["phrases that influenced classification"]
}}"""


KEYWORD_EXTRACTION_PROMPT = """Extract equipment, certifications, and travel information from this provider response.

Provider Response:
{response_body}

Equipment to look for:
{equipment_list}

Certifications to look for:
{certification_list}

Extract and respond with JSON:
{{
    "equipment_confirmed": ["list of equipment types provider confirmed having"],
    "equipment_not_available": ["equipment types provider mentioned not having"],
    "certifications_mentioned": ["certification types found in response"],
    "travel_willing": true/false/null (if mentioned),
    "travel_keywords": ["phrases about travel"],
    "other_capabilities": ["other relevant capabilities mentioned"],
    "concerns_raised": ["any concerns or limitations mentioned"]
}}"""


DOCUMENT_ANALYSIS_PROMPT = """Analyze this OCR text extracted from a {document_type} document.

OCR Text:
{ocr_text}

Required Fields for {document_type}:
{required_fields}

Validation Rules:
{validation_rules}

Extract fields and validate. Respond with JSON:
{{
    "document_type_confirmed": true/false,
    "extracted_fields": {{
        "field_name": "value",
        ...
    }},
    "validation_results": {{
        "field_name": {{
            "valid": true/false,
            "error": "error message if invalid"
        }}
    }},
    "overall_valid": true/false,
    "confidence": 0.0-1.0,
    "notes": "any relevant observations"
}}"""


SCREENING_DECISION_PROMPT = """Make a screening decision for this provider.

Campaign Requirements:
- Required Equipment: {required_equipment}
- Required Documents: {required_documents}
- Insurance Minimum: ${insurance_minimum:,}
- Travel Required: {travel_required}

Provider Status:
- Equipment Confirmed: {equipment_confirmed}
- Equipment Missing: {equipment_missing}
- Documents Validated: {documents_validated}
- Documents Pending: {documents_pending}
- Travel Confirmed: {travel_confirmed}
- Insurance Coverage: ${insurance_coverage:,}
- Insurance Expiry: {insurance_expiry}

Response History:
{response_summary}

Make a decision. Respond with JSON:
{{
    "decision": "QUALIFIED|REJECTED|NEEDS_DOCUMENT|NEEDS_CLARIFICATION|UNDER_REVIEW|ESCALATED",
    "confidence": 0.0-1.0,
    "reasoning": "explanation for the decision",
    "next_action": "what should happen next",
    "missing_items": ["list of missing requirements"],
    "questions": ["questions to ask provider if NEEDS_CLARIFICATION"]
}}"""


def get_system_prompt() -> str:
    """Get the main system prompt for the Screening Agent."""
    return SYSTEM_PROMPT


def get_response_classification_prompt(
    response_body: str,
    campaign_type: str = "recruitment",
    has_attachments: bool = False,
    previous_status: str = "WAITING_RESPONSE",
) -> str:
    """Build prompt for response classification."""
    return RESPONSE_CLASSIFICATION_PROMPT.format(
        response_body=response_body[:5000],  # Truncate for context limits
        campaign_type=campaign_type,
        has_attachments=has_attachments,
        previous_status=previous_status,
    )


def get_keyword_extraction_prompt(
    response_body: str,
    equipment_list: list[str],
    certification_list: list[str],
) -> str:
    """Build prompt for keyword extraction."""
    return KEYWORD_EXTRACTION_PROMPT.format(
        response_body=response_body[:5000],
        equipment_list="\n".join(f"- {eq}" for eq in equipment_list),
        certification_list="\n".join(f"- {cert}" for cert in certification_list),
    )


def get_document_analysis_prompt(
    ocr_text: str,
    document_type: str,
    required_fields: list[str],
    validation_rules: list[str],
) -> str:
    """Build prompt for document analysis."""
    return DOCUMENT_ANALYSIS_PROMPT.format(
        document_type=document_type,
        ocr_text=ocr_text[:10000],  # Truncate for context limits
        required_fields="\n".join(f"- {field}" for field in required_fields),
        validation_rules="\n".join(f"- {rule}" for rule in validation_rules),
    )


def get_screening_decision_prompt(
    required_equipment: list[str],
    required_documents: list[str],
    insurance_minimum: int,
    travel_required: bool,
    equipment_confirmed: list[str],
    equipment_missing: list[str],
    documents_validated: list[str],
    documents_pending: list[str],
    travel_confirmed: bool | None,
    insurance_coverage: int | None,
    insurance_expiry: str | None,
    response_summary: str,
) -> str:
    """Build prompt for final screening decision."""
    return SCREENING_DECISION_PROMPT.format(
        required_equipment=", ".join(required_equipment) or "None",
        required_documents=", ".join(required_documents) or "None",
        insurance_minimum=insurance_minimum,
        travel_required="Yes" if travel_required else "No",
        equipment_confirmed=", ".join(equipment_confirmed) or "None",
        equipment_missing=", ".join(equipment_missing) or "None",
        documents_validated=", ".join(documents_validated) or "None",
        documents_pending=", ".join(documents_pending) or "None",
        travel_confirmed="Yes" if travel_confirmed else ("No" if travel_confirmed is False else "Unknown"),
        insurance_coverage=insurance_coverage or 0,
        insurance_expiry=insurance_expiry or "Unknown",
        response_summary=response_summary[:2000],
    )
