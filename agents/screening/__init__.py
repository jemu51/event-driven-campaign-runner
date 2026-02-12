"""
Screening Agent Package

Agent for processing provider responses and evaluating documents.
Handles ProviderResponseReceived and DocumentProcessed events.
"""

from agents.screening.agent import (
    ScreeningError,
    handle_document_processed,
    handle_provider_response_received,
)
from agents.screening.config import ScreeningConfig, get_screening_config
from agents.screening.models import (
    DocumentAnalysis,
    EquipmentMatch,
    ResponseClassification,
    ScreeningResult,
)
from agents.screening.tools import (
    classify_response,
    evaluate_document_ocr,
    extract_keywords,
    trigger_textract_async,
)

__all__ = [
    # Agent handlers
    "handle_provider_response_received",
    "handle_document_processed",
    "ScreeningError",
    # Config
    "ScreeningConfig",
    "get_screening_config",
    # Models
    "ResponseClassification",
    "EquipmentMatch",
    "DocumentAnalysis",
    "ScreeningResult",
    # Tools
    "classify_response",
    "extract_keywords",
    "trigger_textract_async",
    "evaluate_document_ocr",
]
