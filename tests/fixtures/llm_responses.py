"""
LLM Response Fixtures for Testing

Predefined LLM response fixtures for deterministic testing.
Matches the Pydantic schemas in agents/shared/llm/schemas.py.
"""

from datetime import date

from agents.shared.llm.schemas import (
    EmailGenerationOutput,
    ResponseClassificationOutput,
    EquipmentExtractionOutput,
    InsuranceDocumentOutput,
    ScreeningDecisionOutput,
)


# =============================================================================
# Email Generation Fixtures
# =============================================================================

MOCK_EMAIL_INITIAL_OUTREACH = EmailGenerationOutput(
    subject="Opportunity: Satellite Upgrade technicians needed in Atlanta",
    body_text="""Hi John,

We have an exciting opportunity for satellite upgrade work in the Atlanta area starting next month.

Based on your experience, we believe you'd be a great fit for this project. The work involves upgrading residential satellite equipment, and we're looking for technicians with:
- Bucket truck or aerial lift access
- Spectrum analyzer equipment
- Willingness to travel within the Atlanta metro area

If you're interested, please reply to this email with your availability and any questions you may have. We'd also need proof of insurance (minimum $2M coverage) before we can proceed.

Please reply directly to this email to ensure your response reaches us.

Best regards,
Recruitment Team""",
    tone="professional",
    includes_call_to_action=True,
    personalization_elements=["provider name", "market", "equipment requirements"],
)


MOCK_EMAIL_FOLLOW_UP = EmailGenerationOutput(
    subject="Following up: Satellite Upgrade opportunity in Atlanta",
    body_text="""Hi John,

I wanted to follow up on my previous email about the satellite upgrade opportunity in Atlanta.

We're still looking for qualified technicians for this project, and I wanted to make sure you saw our initial outreach.

If you're interested in learning more or have any questions about the opportunity, please don't hesitate to reply.

Best regards,
Recruitment Team""",
    tone="friendly",
    includes_call_to_action=True,
    personalization_elements=["provider name", "market", "reference to previous email"],
)


MOCK_EMAIL_DOCUMENT_REQUEST = EmailGenerationOutput(
    subject="Document needed: Insurance certificate for Atlanta project",
    body_text="""Hi John,

Thank you for your interest in the satellite upgrade project!

To proceed with your application, we need a copy of your insurance certificate showing minimum $2,000,000 in coverage. Please attach the document to your reply to this email.

Note: Please ensure any attached files are under 30MB.

If you have any questions about the requirements, feel free to ask.

Best regards,
Recruitment Team""",
    tone="professional",
    includes_call_to_action=True,
    personalization_elements=["provider name", "document type", "coverage requirement"],
)


# =============================================================================
# Response Classification Fixtures
# =============================================================================

MOCK_CLASSIFICATION_POSITIVE = ResponseClassificationOutput(
    intent="positive",
    confidence=0.95,
    reasoning="Provider expresses clear interest in the opportunity and asks about next steps",
    key_phrases=["interested", "sounds great", "when can I start"],
    sentiment="positive",
)


MOCK_CLASSIFICATION_NEGATIVE = ResponseClassificationOutput(
    intent="negative",
    confidence=0.92,
    reasoning="Provider explicitly declines the opportunity",
    key_phrases=["not interested", "please remove me", "no thanks"],
    sentiment="negative",
)


MOCK_CLASSIFICATION_QUESTION = ResponseClassificationOutput(
    intent="question",
    confidence=0.88,
    reasoning="Provider is asking questions about the opportunity before committing",
    key_phrases=["what is the pay rate", "how long is the project", "can you tell me more"],
    sentiment="neutral",
)


MOCK_CLASSIFICATION_DOCUMENT_ONLY = ResponseClassificationOutput(
    intent="document_only",
    confidence=0.90,
    reasoning="Email contains minimal text with an attachment, appears to be document submission",
    key_phrases=["attached", "see attached", "here is my"],
    sentiment="neutral",
)


MOCK_CLASSIFICATION_AMBIGUOUS = ResponseClassificationOutput(
    intent="ambiguous",
    confidence=0.45,
    reasoning="Response is unclear and doesn't clearly indicate interest or disinterest",
    key_phrases=[],
    sentiment="neutral",
)


# =============================================================================
# Equipment Extraction Fixtures
# =============================================================================

MOCK_EQUIPMENT_COMPLETE = EquipmentExtractionOutput(
    equipment_confirmed=["bucket_truck", "spectrum_analyzer"],
    equipment_denied=[],
    travel_willing=True,
    certifications_mentioned=["OSHA 10", "CompTIA Network+"],
    concerns_raised=[],
    confidence=0.92,
)


MOCK_EQUIPMENT_PARTIAL = EquipmentExtractionOutput(
    equipment_confirmed=["bucket_truck"],
    equipment_denied=["spectrum_analyzer"],
    travel_willing=True,
    certifications_mentioned=["OSHA 10"],
    concerns_raised=["Doesn't own spectrum analyzer, would need to rent"],
    confidence=0.85,
)


MOCK_EQUIPMENT_MISSING = EquipmentExtractionOutput(
    equipment_confirmed=[],
    equipment_denied=["bucket_truck", "spectrum_analyzer"],
    travel_willing=None,
    certifications_mentioned=[],
    concerns_raised=["Provider doesn't have required equipment"],
    confidence=0.88,
)


MOCK_EQUIPMENT_NO_TRAVEL = EquipmentExtractionOutput(
    equipment_confirmed=["bucket_truck", "spectrum_analyzer"],
    equipment_denied=[],
    travel_willing=False,
    certifications_mentioned=["OSHA 10"],
    concerns_raised=["Provider stated they cannot travel outside their city"],
    confidence=0.90,
)


# =============================================================================
# Insurance Document Fixtures
# =============================================================================

MOCK_INSURANCE_VALID = InsuranceDocumentOutput(
    is_insurance_document=True,
    policy_holder="John Smith DBA Smith Installations",
    coverage_amount=2500000,
    expiry_date=date(2027, 12, 31),
    policy_number="POL-2024-12345",
    insurance_company="SafeGuard Insurance Co",
    is_valid=True,
    validation_errors=[],
    confidence=0.94,
)


MOCK_INSURANCE_EXPIRED = InsuranceDocumentOutput(
    is_insurance_document=True,
    policy_holder="John Smith",
    coverage_amount=2000000,
    expiry_date=date(2024, 6, 30),
    policy_number="POL-2023-98765",
    insurance_company="ABC Insurance",
    is_valid=False,
    validation_errors=["Policy has expired"],
    confidence=0.91,
)


MOCK_INSURANCE_INSUFFICIENT_COVERAGE = InsuranceDocumentOutput(
    is_insurance_document=True,
    policy_holder="John Smith",
    coverage_amount=1000000,
    expiry_date=date(2027, 12, 31),
    policy_number="POL-2024-55555",
    insurance_company="Budget Insurance Inc",
    is_valid=False,
    validation_errors=["Coverage amount ($1,000,000) is below minimum ($2,000,000)"],
    confidence=0.89,
)


MOCK_INSURANCE_NOT_INSURANCE = InsuranceDocumentOutput(
    is_insurance_document=False,
    policy_holder=None,
    coverage_amount=None,
    expiry_date=None,
    policy_number=None,
    insurance_company=None,
    is_valid=False,
    validation_errors=["Document is not an insurance certificate"],
    confidence=0.75,
)


# =============================================================================
# Screening Decision Fixtures
# =============================================================================

MOCK_DECISION_QUALIFIED = ScreeningDecisionOutput(
    decision="QUALIFIED",
    confidence=0.92,
    reasoning="Provider meets all requirements: has required equipment, willing to travel, and valid insurance on file",
    next_action="Schedule onboarding call",
    missing_items=[],
    questions_for_provider=[],
)


MOCK_DECISION_NEEDS_DOCUMENT = ScreeningDecisionOutput(
    decision="NEEDS_DOCUMENT",
    confidence=0.88,
    reasoning="Provider expressed interest and has equipment, but insurance certificate is missing",
    next_action="Request insurance certificate submission",
    missing_items=["insurance_certificate"],
    questions_for_provider=[],
)


MOCK_DECISION_NEEDS_CLARIFICATION = ScreeningDecisionOutput(
    decision="NEEDS_CLARIFICATION",
    confidence=0.75,
    reasoning="Provider's response about equipment ownership is unclear",
    next_action="Send clarification request about equipment",
    missing_items=[],
    questions_for_provider=["Do you own a bucket truck or have access to one?", "Can you confirm your spectrum analyzer model?"],
)


MOCK_DECISION_REJECTED = ScreeningDecisionOutput(
    decision="REJECTED",
    confidence=0.95,
    reasoning="Provider explicitly declined the opportunity",
    next_action="Update status and close session",
    missing_items=[],
    questions_for_provider=[],
)


MOCK_DECISION_UNDER_REVIEW = ScreeningDecisionOutput(
    decision="UNDER_REVIEW",
    confidence=0.55,
    reasoning="Provider situation is complex and requires manual review",
    next_action="Flag for human review",
    missing_items=["verification of equipment access"],
    questions_for_provider=[],
)


# =============================================================================
# Fixture Collections
# =============================================================================

EMAIL_FIXTURES = {
    "initial_outreach": MOCK_EMAIL_INITIAL_OUTREACH,
    "follow_up": MOCK_EMAIL_FOLLOW_UP,
    "document_request": MOCK_EMAIL_DOCUMENT_REQUEST,
}

CLASSIFICATION_FIXTURES = {
    "positive": MOCK_CLASSIFICATION_POSITIVE,
    "negative": MOCK_CLASSIFICATION_NEGATIVE,
    "question": MOCK_CLASSIFICATION_QUESTION,
    "document_only": MOCK_CLASSIFICATION_DOCUMENT_ONLY,
    "ambiguous": MOCK_CLASSIFICATION_AMBIGUOUS,
}

EQUIPMENT_FIXTURES = {
    "complete": MOCK_EQUIPMENT_COMPLETE,
    "partial": MOCK_EQUIPMENT_PARTIAL,
    "missing": MOCK_EQUIPMENT_MISSING,
    "no_travel": MOCK_EQUIPMENT_NO_TRAVEL,
}

INSURANCE_FIXTURES = {
    "valid": MOCK_INSURANCE_VALID,
    "expired": MOCK_INSURANCE_EXPIRED,
    "insufficient_coverage": MOCK_INSURANCE_INSUFFICIENT_COVERAGE,
    "not_insurance": MOCK_INSURANCE_NOT_INSURANCE,
}

DECISION_FIXTURES = {
    "qualified": MOCK_DECISION_QUALIFIED,
    "needs_document": MOCK_DECISION_NEEDS_DOCUMENT,
    "needs_clarification": MOCK_DECISION_NEEDS_CLARIFICATION,
    "rejected": MOCK_DECISION_REJECTED,
    "under_review": MOCK_DECISION_UNDER_REVIEW,
}
