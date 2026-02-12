"""
Document Processor

Extracts structured data from Textract OCR results based on document type.
Field extraction rules are derived from contracts/document_types.json.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import structlog

log = structlog.get_logger()


# --- Document Type Definitions ---

DOCUMENT_TYPE_PATTERNS = {
    "insurance_certificate": [
        r"(?i)certificate\s*of\s*(?:liability\s*)?insurance",
        r"(?i)commercial\s*general\s*liability",
        r"(?i)general\s*aggregate",
        r"(?i)each\s*occurrence",
        r"(?i)policy\s*number",
        r"(?i)insured",
        r"(?i)certificate\s*holder",
    ],
    "license": [
        r"(?i)(?:contractor|professional|trade)\s*license",
        r"(?i)license\s*(?:number|#|no\.?)",
        r"(?i)issued\s*by\s*.+(?:board|department|commission)",
    ],
    "certification": [
        r"(?i)CompTIA\s*Network\+?",
        r"(?i)BICSI",
        r"(?i)certif(?:ied|ication)",
        r"(?i)awarded\s*to",
        r"(?i)FCC\s*(?:license|certification)",
    ],
    "w9": [
        r"(?i)request\s*for\s*taxpayer",
        r"(?i)form\s*w-?9",
        r"(?i)taxpayer\s*identification\s*number",
        r"(?i)employer\s*identification\s*number",
    ],
}


# --- Extraction Patterns (from contracts/document_types.json) ---

EXTRACTION_RULES = {
    "insurance_certificate": {
        "expiry_date": [
            r"(?i)expir(?:es?|ation|y)\s*(?:date)?\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"(?i)valid\s*(?:until|through|to)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"(?i)policy\s*end\s*(?:date)?\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        ],
        "coverage_amount": [
            r"(?i)(?:general\s*)?(?:aggregate|liability)\s*(?:limit)?\s*:?\s*\$?([\d,]+(?:\.\d{2})?)",
            r"(?i)each\s*occurrence\s*:?\s*\$?([\d,]+(?:\.\d{2})?)",
            r"(?i)coverage\s*(?:amount|limit)\s*:?\s*\$?([\d,]+(?:\.\d{2})?)",
        ],
        "policy_holder": [
            r"(?i)(?:named\s*)?insured\s*:?\s*([A-Za-z][A-Za-z0-9\s&,.'-]+)",
            r"(?i)policy\s*holder\s*:?\s*([A-Za-z][A-Za-z0-9\s&,.'-]+)",
        ],
        "policy_number": [
            r"(?i)policy\s*(?:no\.?|number|#)\s*:?\s*([A-Z0-9-]+)",
        ],
        "insurance_company": [
            r"(?i)(?:insurance\s*)?(?:company|carrier|insurer)\s*:?\s*([A-Za-z][A-Za-z0-9\s&,.'-]+)",
        ],
    },
    "license": {
        "license_number": [
            r"(?i)license\s*(?:no\.?|number|#)\s*:?\s*([A-Z0-9-]+)",
        ],
        "expiry_date": [
            r"(?i)expir(?:es?|ation|y)\s*(?:date)?\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            r"(?i)valid\s*(?:until|through|to)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        ],
        "license_type": [
            r"(?i)(?:license\s*)?type\s*:?\s*([A-Za-z][A-Za-z0-9\s-]+)",
        ],
        "holder_name": [
            r"(?i)(?:issued\s*to|name|holder)\s*:?\s*([A-Za-z][A-Za-z\s,.'-]+)",
        ],
    },
    "certification": {
        "certification_name": [
            r"(?i)(CompTIA\s*Network\+)",
            r"(?i)(BICSI\s*[A-Za-z0-9]+)",
            r"(?i)(FCC\s*(?:License|Certification))",
            r"(?i)certif(?:ied|ication)\s*(?:in|for)?\s*:?\s*([A-Za-z][A-Za-z0-9\s-]+)",
        ],
        "certification_id": [
            r"(?i)(?:cert(?:ification)?\s*)?(?:id|number|#)\s*:?\s*([A-Z0-9-]+)",
        ],
        "issue_date": [
            r"(?i)issue(?:d)?\s*(?:date)?\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        ],
        "expiry_date": [
            r"(?i)expir(?:es?|ation|y)\s*(?:date)?\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        ],
        "holder_name": [
            r"(?i)(?:awarded\s*to|name|holder|recipient)\s*:?\s*([A-Za-z][A-Za-z\s,.'-]+)",
        ],
    },
    "w9": {
        "business_name": [
            r"(?i)name\s*\(as\s*shown\s*on\s*your\s*income\s*tax\s*return\)\s*:?\s*([A-Za-z][A-Za-z0-9\s&,.'-]+)",
        ],
        "tax_classification": [
            r"(?i)(?:federal\s*tax\s*)?classification\s*:?\s*([A-Za-z][A-Za-z\s/]+)",
        ],
    },
}

# Confidence thresholds per document type
CONFIDENCE_THRESHOLDS = {
    "insurance_certificate": 0.8,
    "license": 0.8,
    "certification": 0.75,
    "w9": 0.85,
    "other": 0.7,
}


@dataclass(frozen=True)
class ExtractedField:
    """A single extracted field from a document."""
    
    name: str
    value: str | int | None
    raw_value: str | None = None
    confidence: float = 0.0
    pattern_matched: str | None = None


@dataclass
class DocumentExtractionResult:
    """Complete document extraction result."""
    
    document_type: str
    ocr_text: str
    extracted_fields: dict[str, Any] = field(default_factory=dict)
    confidence_scores: dict[str, float] = field(default_factory=dict)
    classification_confidence: float = 0.0
    extraction_errors: list[str] = field(default_factory=list)
    
    def to_event_payload(self) -> dict[str, Any]:
        """Convert to DocumentProcessed event payload format."""
        return {
            "ocr_text": self.ocr_text,
            "extracted_fields": self.extracted_fields,
            "confidence_scores": self.confidence_scores,
        }


def classify_document_type(ocr_text: str) -> tuple[str, float]:
    """
    Classify document type based on OCR text content.
    
    Args:
        ocr_text: Raw OCR text from Textract
        
    Returns:
        Tuple of (document_type, confidence)
    """
    normalized_text = ocr_text.lower()
    scores: dict[str, int] = {}
    
    for doc_type, patterns in DOCUMENT_TYPE_PATTERNS.items():
        score = 0
        for pattern in patterns:
            if re.search(pattern, ocr_text, re.IGNORECASE):
                score += 1
        scores[doc_type] = score
    
    if not scores or max(scores.values()) == 0:
        log.warning("document_type_unknown", text_preview=ocr_text[:200])
        return "other", 0.3
    
    # Find document type with highest score
    best_type = max(scores, key=scores.get)
    max_score = scores[best_type]
    total_patterns = len(DOCUMENT_TYPE_PATTERNS.get(best_type, []))
    
    # Calculate confidence based on pattern match ratio
    confidence = min(0.95, 0.5 + (max_score / max(total_patterns, 1)) * 0.5)
    
    log.info(
        "document_classified",
        document_type=best_type,
        confidence=confidence,
        pattern_matches=max_score,
        total_patterns=total_patterns,
    )
    
    return best_type, confidence


def _parse_date(date_str: str) -> str | None:
    """
    Parse date string to ISO 8601 format.
    
    Handles formats like: MM/DD/YYYY, MM-DD-YYYY, MM/DD/YY
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    
    # Try common date formats
    formats = [
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%m/%d/%y",
        "%m-%d-%y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]
    
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    log.warning("date_parse_failed", date_str=date_str)
    return None


def _parse_currency(amount_str: str) -> int | None:
    """
    Parse currency string to integer (dollars).
    
    Handles formats like: $1,000,000.00, 2000000, 1,500,000
    """
    if not amount_str:
        return None
    
    # Remove currency symbols, commas, and whitespace
    cleaned = re.sub(r"[$,\s]", "", amount_str)
    
    # Handle decimals - take integer portion
    if "." in cleaned:
        cleaned = cleaned.split(".")[0]
    
    try:
        return int(cleaned)
    except ValueError:
        log.warning("currency_parse_failed", amount_str=amount_str)
        return None


def _extract_field_value(
    ocr_text: str,
    field_name: str,
    patterns: list[str],
    textract_blocks: list[dict[str, Any]] | None = None,
) -> ExtractedField:
    """
    Extract a single field value using regex patterns.
    
    Args:
        ocr_text: Raw OCR text
        field_name: Name of the field being extracted
        patterns: List of regex patterns to try
        textract_blocks: Optional Textract block data for confidence scores
        
    Returns:
        ExtractedField with extracted value and metadata
    """
    for pattern in patterns:
        match = re.search(pattern, ocr_text, re.IGNORECASE)
        if match:
            raw_value = match.group(1).strip() if match.groups() else match.group(0).strip()
            
            # Clean up the extracted value
            # Remove trailing punctuation and extra whitespace
            raw_value = re.sub(r"[,;:\s]+$", "", raw_value).strip()
            
            # Parse based on field type
            if "date" in field_name.lower():
                parsed_value = _parse_date(raw_value)
            elif "amount" in field_name.lower() or "coverage" in field_name.lower():
                parsed_value = _parse_currency(raw_value)
            else:
                parsed_value = raw_value
            
            # Estimate confidence based on pattern specificity
            # More specific patterns get higher confidence
            pattern_specificity = len(pattern) / 100  # Longer patterns = more specific
            base_confidence = 0.75
            confidence = min(0.95, base_confidence + (pattern_specificity * 0.2))
            
            return ExtractedField(
                name=field_name,
                value=parsed_value,
                raw_value=raw_value,
                confidence=confidence,
                pattern_matched=pattern,
            )
    
    return ExtractedField(name=field_name, value=None, confidence=0.0)


def extract_document_fields(
    document_type: str,
    ocr_text: str,
    textract_blocks: list[dict[str, Any]] | None = None,
) -> DocumentExtractionResult:
    """
    Extract all fields from a document based on its type.
    
    Args:
        document_type: Classified document type
        ocr_text: Raw OCR text from Textract
        textract_blocks: Optional Textract block data for enhanced extraction
        
    Returns:
        DocumentExtractionResult with all extracted fields
    """
    result = DocumentExtractionResult(
        document_type=document_type,
        ocr_text=ocr_text,
    )
    
    # Get extraction rules for this document type
    rules = EXTRACTION_RULES.get(document_type, {})
    
    if not rules:
        log.info(
            "no_extraction_rules",
            document_type=document_type,
        )
        return result
    
    # Extract each field
    for field_name, patterns in rules.items():
        try:
            extracted = _extract_field_value(
                ocr_text=ocr_text,
                field_name=field_name,
                patterns=patterns,
                textract_blocks=textract_blocks,
            )
            
            if extracted.value is not None:
                result.extracted_fields[field_name] = extracted.value
                result.confidence_scores[field_name] = extracted.confidence
                
                log.info(
                    "field_extracted",
                    field_name=field_name,
                    confidence=extracted.confidence,
                    raw_value=extracted.raw_value,
                )
            else:
                log.info(
                    "field_not_found",
                    field_name=field_name,
                    document_type=document_type,
                )
                
        except Exception as e:
            error_msg = f"Error extracting {field_name}: {e}"
            result.extraction_errors.append(error_msg)
            log.error(
                "field_extraction_error",
                field_name=field_name,
                error=str(e),
            )
    
    log.info(
        "document_extraction_complete",
        document_type=document_type,
        fields_extracted=len(result.extracted_fields),
        total_fields=len(rules),
        errors=len(result.extraction_errors),
    )
    
    return result


def get_textract_text_from_blocks(blocks: list[dict[str, Any]]) -> str:
    """
    Extract plain text from Textract block structure.
    
    Args:
        blocks: List of Textract blocks from GetDocumentAnalysis
        
    Returns:
        Concatenated text from LINE and WORD blocks
    """
    lines = []
    
    for block in blocks:
        if block.get("BlockType") == "LINE":
            text = block.get("Text", "")
            if text:
                lines.append(text)
    
    return "\n".join(lines)


def get_key_value_pairs(blocks: list[dict[str, Any]]) -> dict[str, str]:
    """
    Extract key-value pairs from Textract FORMS analysis.
    
    Args:
        blocks: List of Textract blocks from GetDocumentAnalysis
        
    Returns:
        Dictionary of key-value pairs found in forms
    """
    key_value_pairs = {}
    key_map = {}
    value_map = {}
    block_map = {block["Id"]: block for block in blocks}
    
    # First pass: identify KEY_VALUE_SET blocks
    for block in blocks:
        block_type = block.get("BlockType")
        
        if block_type == "KEY_VALUE_SET":
            entity_types = block.get("EntityTypes", [])
            
            if "KEY" in entity_types:
                key_map[block["Id"]] = block
            elif "VALUE" in entity_types:
                value_map[block["Id"]] = block
    
    # Second pass: link keys to values
    for key_id, key_block in key_map.items():
        # Find associated value block
        value_text = ""
        key_text = ""
        
        # Get key text
        for relationship in key_block.get("Relationships", []):
            if relationship["Type"] == "CHILD":
                for child_id in relationship["Ids"]:
                    child = block_map.get(child_id, {})
                    if child.get("BlockType") == "WORD":
                        key_text += child.get("Text", "") + " "
            elif relationship["Type"] == "VALUE":
                for value_id in relationship["Ids"]:
                    value_block = value_map.get(value_id)
                    if value_block:
                        for rel in value_block.get("Relationships", []):
                            if rel["Type"] == "CHILD":
                                for child_id in rel["Ids"]:
                                    child = block_map.get(child_id, {})
                                    if child.get("BlockType") == "WORD":
                                        value_text += child.get("Text", "") + " "
        
        key_text = key_text.strip()
        value_text = value_text.strip()
        
        if key_text and value_text:
            key_value_pairs[key_text] = value_text
    
    return key_value_pairs


def validate_insurance_fields(extracted_fields: dict[str, Any]) -> dict[str, Any]:
    """
    Validate insurance-specific field constraints.
    
    Args:
        extracted_fields: Extracted field values
        
    Returns:
        Validation results with is_valid, errors, and warnings
    """
    validation = {
        "is_valid": True,
        "errors": [],
        "warnings": [],
    }
    
    # Check expiry date
    expiry_date_str = extracted_fields.get("expiry_date")
    if expiry_date_str:
        try:
            expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
            if expiry_date < date.today():
                validation["is_valid"] = False
                validation["errors"].append("Insurance certificate has expired")
        except ValueError:
            validation["warnings"].append("Could not validate expiry date format")
    else:
        validation["warnings"].append("Expiry date not found in document")
    
    # Check coverage amount (minimum $2M)
    coverage_amount = extracted_fields.get("coverage_amount")
    if coverage_amount:
        if coverage_amount < 2_000_000:
            validation["is_valid"] = False
            validation["errors"].append(
                f"Insurance coverage ${coverage_amount:,} is below $2M minimum"
            )
    else:
        validation["warnings"].append("Coverage amount not found in document")
    
    # Check policy holder
    if not extracted_fields.get("policy_holder"):
        validation["warnings"].append("Policy holder name not found")
    
    return validation
