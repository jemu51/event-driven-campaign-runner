"""
Screening Agent LLM Prompts

System prompts and prompt builders for LLM-powered screening operations.
"""

CLASSIFICATION_SYSTEM_PROMPT = """You are an AI assistant analyzing provider responses in a recruitment automation system.

Your task is to classify the intent of provider emails accurately and extract relevant information.

CONTEXT:
- Providers receive outreach emails about work opportunities (e.g., satellite installation, equipment upgrades)
- They may respond with interest, questions, documents, or decline
- Your classification informs the next action in the workflow

CLASSIFICATION CATEGORIES:
- POSITIVE: Provider expresses clear interest and willingness to participate
- NEGATIVE: Provider declines, is not interested, or explicitly refuses
- QUESTION: Provider has questions that need answering before they can commit
- DOCUMENT_ONLY: Email contains primarily a document attachment with minimal text
- AMBIGUOUS: Cannot determine clear intent from the response

GUIDELINES:
- Be conservative: if unsure, classify as AMBIGUOUS
- Consider the full context of the message
- Look for explicit statements of interest or decline
- "I'll think about it" is AMBIGUOUS, not POSITIVE
- Questions about pay, schedule, or requirements should be classified as QUESTION

You MUST respond with valid JSON matching the required schema."""


EQUIPMENT_EXTRACTION_SYSTEM_PROMPT = """You are an AI assistant extracting equipment and qualification information from provider responses.

Your task is to identify what equipment and certifications a provider mentions having or not having.

GUIDELINES:
- Only mark equipment as CONFIRMED if the provider clearly states they have it
- Mark as DENIED if they explicitly say they don't have it
- Mark as NOT_MENTIONED if they don't address it at all
- Look for synonyms and related terms (e.g., "boom truck" = "bucket truck")
- Extract any certifications or licenses mentioned
- Detect travel willingness based on their statements

Be precise and conservative. Inferred information should be marked with lower confidence.

You MUST respond with valid JSON matching the required schema."""


DOCUMENT_ANALYSIS_SYSTEM_PROMPT = """You are an AI assistant analyzing OCR text extracted from documents.

Your task is to identify and validate document contents, particularly for:
- Insurance certificates
- Professional licenses
- Certifications
- W-9 tax forms

GUIDELINES:
- First confirm this is the expected document type
- Extract all required fields with their values
- Validate extracted values against provided rules
- Note any concerns about document validity
- Flag potential issues like expired dates, incorrect coverage amounts

For insurance documents, pay special attention to:
- Coverage amount (must meet minimum requirements)
- Expiry date (must not be expired or expiring soon)
- Policy holder name (should match provider)
- Policy number and insurance company

You MUST respond with valid JSON matching the required schema."""


SCREENING_DECISION_SYSTEM_PROMPT = """You are an AI assistant making screening decisions for providers in recruitment campaigns.

Your task is to synthesize all available information and make a qualification decision.

DECISION OPTIONS:
- QUALIFIED: All requirements met, provider should be approved
- REJECTED: Provider does not meet requirements or has declined
- NEEDS_DOCUMENT: Provider is missing required documents, request submission
- NEEDS_CLARIFICATION: Need more information from provider before deciding
- UNDER_REVIEW: Edge case requiring manual review
- ESCALATED: Serious issue requiring human intervention

GUIDELINES:
- Consider all evidence: response intent, equipment, documents, conversation history
- Be thorough but fair - don't reject for minor missing information
- Prefer NEEDS_CLARIFICATION over REJECTED for incomplete responses
- Provide clear reasoning for your decision
- Flag any concerns that should be noted but don't affect the decision

You MUST respond with valid JSON matching the required schema."""


def build_classification_prompt(
    response_body: str,
    has_attachments: bool,
    campaign_type: str,
    previous_status: str,
    conversation_history: str,
) -> str:
    """
    Build prompt for response classification.
    
    Args:
        response_body: The provider's email body text
        has_attachments: Whether the email has attachments
        campaign_type: Type of campaign (e.g., "satellite_upgrade")
        previous_status: Provider's previous status in the workflow
        conversation_history: Formatted previous conversation
        
    Returns:
        Formatted prompt string
    """
    attachment_note = (
        "The email includes document attachments."
        if has_attachments
        else "The email has no attachments."
    )
    
    return f"""Analyze the following provider response and classify their intent.

CAMPAIGN TYPE: {campaign_type}
PROVIDER'S PREVIOUS STATUS: {previous_status}
{attachment_note}

CONVERSATION HISTORY:
{conversation_history}

---

PROVIDER'S RESPONSE:
{response_body}

---

Based on this response, classify the provider's intent and provide your analysis.
Include:
1. The classification category (POSITIVE, NEGATIVE, QUESTION, DOCUMENT_ONLY, or AMBIGUOUS)
2. Your confidence level (0-1)
3. Key phrases that led to your classification
4. Any concerns or notes about the response"""


def build_equipment_extraction_prompt(
    response_body: str,
    required_equipment: list[str],
    equipment_keywords: dict[str, list[str]],
    required_certifications: list[str] | None = None,
) -> str:
    """
    Build prompt for equipment extraction.
    
    Args:
        response_body: The provider's email body text
        required_equipment: List of required equipment types
        equipment_keywords: Dict mapping equipment types to keyword synonyms
        required_certifications: Optional list of required certifications
        
    Returns:
        Formatted prompt string
    """
    # Format equipment list with synonyms
    equipment_list = ""
    for eq_type in required_equipment:
        synonyms = equipment_keywords.get(eq_type, [eq_type])
        equipment_list += f"- {eq_type}: {', '.join(synonyms)}\n"
    
    cert_list = ""
    if required_certifications:
        cert_list = f"\nREQUIRED CERTIFICATIONS:\n"
        for cert in required_certifications:
            cert_list += f"- {cert}\n"
    
    return f"""Extract equipment and qualification information from this provider response.

EQUIPMENT TO LOOK FOR (with synonyms):
{equipment_list}
{cert_list}

---

PROVIDER'S RESPONSE:
{response_body}

---

Identify:
1. Which required equipment the provider confirms having
2. Which equipment they explicitly say they don't have
3. Any equipment not mentioned
4. Certifications or licenses mentioned
5. Travel willingness (yes, no, or not mentioned)
6. Any concerns or limitations stated"""


def build_document_analysis_prompt(
    document_type: str,
    ocr_text: str,
    required_fields: list[str],
    validation_rules: dict[str, str],
) -> str:
    """
    Build prompt for document analysis.
    
    Args:
        document_type: Type of document (e.g., "insurance_certificate")
        ocr_text: OCR-extracted text from the document
        required_fields: List of fields to extract
        validation_rules: Dict of field -> validation rule description
        
    Returns:
        Formatted prompt string
    """
    fields_str = "\n".join(f"- {field}" for field in required_fields)
    rules_str = "\n".join(
        f"- {field}: {rule}" 
        for field, rule in validation_rules.items()
    )
    
    return f"""Analyze this {document_type} document and extract required information.

DOCUMENT TYPE: {document_type}

FIELDS TO EXTRACT:
{fields_str}

VALIDATION RULES:
{rules_str}

---

OCR TEXT:
{ocr_text}

---

For each required field:
1. Extract the value if present
2. Validate against the rules
3. Note any concerns or issues
4. Indicate confidence in the extraction"""


def build_screening_decision_prompt(
    campaign_requirements: dict,
    equipment_confirmed: list[str],
    equipment_missing: list[str],
    travel_confirmed: bool | None,
    documents_validated: list[str],
    documents_pending: list[str],
    response_classification: str,
    conversation_summary: str,
) -> str:
    """
    Build prompt for final screening decision.
    
    Args:
        campaign_requirements: Dict of campaign requirements
        equipment_confirmed: List of confirmed equipment
        equipment_missing: List of missing equipment
        travel_confirmed: Whether travel is confirmed (None if not addressed)
        documents_validated: List of validated document types
        documents_pending: List of pending document types
        response_classification: Classification of provider's response
        conversation_summary: Summary of conversation history
        
    Returns:
        Formatted prompt string
    """
    req_str = "\n".join(f"- {k}: {v}" for k, v in campaign_requirements.items())
    
    travel_status = (
        "Yes" if travel_confirmed is True
        else "No" if travel_confirmed is False
        else "Not confirmed"
    )
    
    return f"""Make a screening decision for this provider based on all available information.

CAMPAIGN REQUIREMENTS:
{req_str}

PROVIDER STATUS:
- Equipment Confirmed: {', '.join(equipment_confirmed) or 'None confirmed'}
- Equipment Missing: {', '.join(equipment_missing) or 'None missing'}
- Travel Confirmed: {travel_status}
- Documents Validated: {', '.join(documents_validated) or 'None yet'}
- Documents Pending: {', '.join(documents_pending) or 'None'}
- Response Classification: {response_classification}

CONVERSATION HISTORY:
{conversation_summary}

---

Based on this information:
1. Make a decision (QUALIFIED, REJECTED, NEEDS_DOCUMENT, NEEDS_CLARIFICATION, UNDER_REVIEW, or ESCALATED)
2. Explain your reasoning
3. List any concerns or notes
4. Suggest next steps if applicable"""
