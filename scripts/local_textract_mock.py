"""
Local Textract Mock

Simulates Textract document processing by immediately emitting
DocumentProcessed events with fixture data.
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from agents.shared.models.events import (
    DocumentProcessedEvent,
    DocumentType,
    ExtractedFields,
)

log = structlog.get_logger()


def mock_textract_processing(
    document_s3_path: str,
    campaign_id: str,
    provider_id: str,
    document_type: str | None = None,
) -> dict[str, Any]:
    """
    Mock Textract processing by building a DocumentProcessed event detail.

    Uses fixture data if available, or generates realistic mock data.

    Returns:
        DocumentProcessed event detail dict
    """
    # Try to load fixture data
    fixture_data = _load_fixture_data(document_s3_path, document_type)

    if fixture_data:
        extracted_fields = ExtractedFields(
            **fixture_data.get("extracted_fields", {})
        )
        document_type_enum = DocumentType(
            fixture_data.get("document_type", "insurance_certificate")
        )
    else:
        # Generate mock data
        extracted_fields = ExtractedFields(
            expiry_date=date(2027, 1, 14),
            coverage_amount=2_000_000,
            policy_holder="Provider Name",
            policy_number="POL-12345",
            insurance_company="Mock Insurance Co",
        )
        document_type_enum = DocumentType(document_type or "insurance_certificate")

    event = DocumentProcessedEvent(
        campaign_id=campaign_id,
        provider_id=provider_id,
        document_s3_path=document_s3_path,
        document_type=document_type_enum,
        job_id=f"mock-textract-{campaign_id}-{provider_id}",
        ocr_text=_generate_mock_ocr_text(document_type_enum),
        extracted_fields=extracted_fields,
        confidence_scores={
            "expiry_date": 0.95,
            "coverage_amount": 0.92,
            "policy_holder": 0.88,
            "policy_number": 0.90,
        },
    )

    log.info(
        "mock_textract_completed",
        campaign_id=campaign_id,
        provider_id=provider_id,
        document_type=document_type_enum.value,
    )

    return event.to_eventbridge_detail()


def _load_fixture_data(
    document_s3_path: str, document_type: str | None
) -> dict[str, Any] | None:
    """Load fixture data if available."""
    try:
        fixture_path = (
            Path(__file__).parent.parent
            / "tests"
            / "fixtures"
            / "demo"
            / "documents"
            / "insurance_documents.json"
        )
        if fixture_path.exists():
            with open(fixture_path) as f:
                fixtures = json.load(f)
                # Return first matching fixture or first fixture
                return fixtures[0] if fixtures else None
    except Exception as e:
        log.debug("fixture_load_failed", error=str(e))
    return None


def _generate_mock_ocr_text(document_type: DocumentType) -> str:
    """Generate mock OCR text based on document type."""
    if document_type == DocumentType.INSURANCE_CERTIFICATE:
        return """
        CERTIFICATE OF INSURANCE
        Policy Number: POL-12345
        Insured: Provider Name
        Coverage Amount: $2,000,000
        Expiration Date: January 14, 2027
        Insurance Company: Mock Insurance Co
        """
    return "Mock OCR text content"


def patch_textract_tools():
    """
    Patch Textract tools to use mock processing.

    Call this before importing screening agent.
    """
    from agents.screening import tools as screening_tools

    def patched_trigger_textract_async(
        document_s3_path: str,
        campaign_id: str,
        provider_id: str,
        document_type: str | None = None,
    ):
        """Patched trigger that immediately processes documents."""
        from scripts.local_event_router import local_event_router

        # Emit DocumentProcessed immediately
        event_detail = mock_textract_processing(
            document_s3_path, campaign_id, provider_id, document_type
        )
        local_event_router("DocumentProcessed", event_detail)

        # Return mock job info
        from agents.screening.models import TextractJobInfo

        return TextractJobInfo(
            job_id=f"mock-{campaign_id}-{provider_id}",
            document_s3_path=document_s3_path,
            document_type=document_type,
            campaign_id=campaign_id,
            provider_id=provider_id,
            started_at=int(datetime.now(timezone.utc).timestamp()),
        )

    screening_tools.trigger_textract_async = patched_trigger_textract_async
    log.info("textract_tools_patched_for_local_mode")
