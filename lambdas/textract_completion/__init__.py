"""
TextractCompletion Lambda

Triggered by Textract SNS completion events.
Extracts structured data from OCR results and emits DocumentProcessed events.

Trigger: SNS topic subscribed to Textract async job notifications
Output: EventBridge DocumentProcessed event

Flow:
1. Parse Textract SNS completion notification
2. Fetch Textract job results from API
3. Classify document type
4. Extract fields per document type rules
5. Emit DocumentProcessed event to EventBridge
"""

from lambdas.textract_completion.document_processor import (
    DocumentExtractionResult,
    ExtractedField,
    classify_document_type,
    extract_document_fields,
)
from lambdas.textract_completion.handler import lambda_handler

__all__ = [
    "lambda_handler",
    "DocumentExtractionResult",
    "ExtractedField",
    "classify_document_type",
    "extract_document_fields",
]
