"""
Normalize campaign requirement strings to canonical equipment and document IDs.

Maps typoed or natural-language input (e.g. "sepcktur analyzer", "insurence ceritficate")
to canonical IDs used by the campaign planner and screening (e.g. spectrum_analyzer,
insurance_certificate). Uses LLM when available; falls back to unchanged requirements
on failure or when LLM is disabled.
"""

from __future__ import annotations

import copy
from typing import Any

import structlog
from pydantic import BaseModel, Field

from agents.shared.llm.bedrock_client import (
    LLMInvocationError,
    LLMParsingError,
    get_llm_client,
)

log = structlog.get_logger()

# Canonical IDs used by campaign_planner/tools.py MOCK_PROVIDERS and screening
CANONICAL_EQUIPMENT = [
    "bucket_truck",
    "spectrum_analyzer",
    "fiber_splicer",
    "otdr",
    "cable_tester",
    "ladder",
    "hand_tools",
]
CANONICAL_DOCUMENTS = [
    "insurance_certificate",
    "license",
    "certification",
    "w9",
    "other",
]


class NormalizedRequirementsOutput(BaseModel):
    """LLM output: mapped equipment and document IDs (canonical only)."""

    equipment_required: list[str] = Field(
        default_factory=list,
        description="Canonical equipment IDs for required equipment",
    )
    equipment_optional: list[str] = Field(
        default_factory=list,
        description="Canonical equipment IDs for optional equipment",
    )
    documents_required: list[str] = Field(
        default_factory=list,
        description="Canonical document type IDs for required documents",
    )


def _filter_canonical(values: list[str], canonical: list[str]) -> list[str]:
    """Return only values that are in canonical; preserve order; dedupe."""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        v_clean = (v or "").strip().lower()
        if v_clean in canonical and v_clean not in seen:
            seen.add(v_clean)
            out.append(v_clean)
    return out


def normalize_campaign_requirements(reqs: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize equipment and document names in campaign requirements to canonical IDs.

    Uses LLM to map typoed or natural-language strings to canonical IDs. If LLM
    is disabled or fails, returns reqs unchanged so the flow never breaks.

    Args:
        reqs: Raw requirements dict with equipment.required, equipment.optional,
              documents.required (and other keys left unchanged).

    Returns:
        New requirements dict with equipment and documents normalized where possible.
    """
    equipment = reqs.get("equipment") or {}
    documents = reqs.get("documents") or {}
    required_eq = equipment.get("required") or []
    optional_eq = equipment.get("optional") or []
    required_doc = documents.get("required") or []

    # Normalize to lists of strings
    if not isinstance(required_eq, list):
        required_eq = [required_eq] if required_eq else []
    if not isinstance(optional_eq, list):
        optional_eq = [optional_eq] if optional_eq else []
    if not isinstance(required_doc, list):
        required_doc = [required_doc] if required_doc else []

    required_eq = [str(x).strip() for x in required_eq if x]
    optional_eq = [str(x).strip() for x in optional_eq if x]
    required_doc = [str(x).strip() for x in required_doc if x]

    if not required_eq and not optional_eq and not required_doc:
        return reqs

    prompt = f"""Map each user-provided item to exactly one canonical ID. Ignore spelling and use meaning.

Canonical equipment IDs (use only these): {", ".join(CANONICAL_EQUIPMENT)}
Canonical document IDs (use only these): {", ".join(CANONICAL_DOCUMENTS)}

User-provided required equipment: {required_eq}
User-provided optional equipment: {optional_eq}
User-provided required documents: {required_doc}

For each user item, pick the best-matching canonical ID (e.g. "spectrum analyzer" or "sepcktur analyzer" -> spectrum_analyzer, "insurance certificate" or "insurence ceritficate" -> insurance_certificate). If no good match exists, omit that item from the output list. Output only canonical IDs."""

    system_prompt = (
        "You are a normalization assistant. Output only valid JSON matching the schema. "
        "Map typoed or natural-language equipment and document names to the given canonical IDs."
    )

    try:
        client = get_llm_client()
        out = client.invoke_structured(
            prompt=prompt,
            output_schema=NormalizedRequirementsOutput,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=512,
        )
    except (LLMInvocationError, LLMParsingError) as e:
        log.warning(
            "requirements_normalization_fallback",
            error=str(e),
            reason="llm_disabled_or_failed",
        )
        return reqs

    # Restrict to canonical lists only
    norm_req_eq = _filter_canonical(out.equipment_required, CANONICAL_EQUIPMENT)
    norm_opt_eq = _filter_canonical(out.equipment_optional, CANONICAL_EQUIPMENT)
    norm_req_doc = _filter_canonical(out.documents_required, CANONICAL_DOCUMENTS)

    # If LLM returned nothing for a list but user had sent values, keep any that are already canonical
    if required_eq and not norm_req_eq:
        norm_req_eq = _filter_canonical(required_eq, CANONICAL_EQUIPMENT)
    if required_doc and not norm_req_doc:
        norm_req_doc = _filter_canonical(required_doc, CANONICAL_DOCUMENTS)

    log.info(
        "requirements_normalized",
        equipment_required_before=required_eq,
        equipment_required_after=norm_req_eq,
        equipment_optional_after=norm_opt_eq,
        documents_required_before=required_doc,
        documents_required_after=norm_req_doc,
    )

    result = copy.deepcopy(reqs)
    result.setdefault("equipment", {})
    result["equipment"]["required"] = norm_req_eq
    result["equipment"]["optional"] = norm_opt_eq
    result.setdefault("documents", {})
    result["documents"]["required"] = norm_req_doc
    return result
