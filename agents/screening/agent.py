"""
Screening Agent

Event handlers for ProviderResponseReceived and DocumentProcessed events.
Evaluates provider responses and documents for campaign qualification.

This agent:
1. Receives ProviderResponseReceived or DocumentProcessed events
2. Loads current provider state from DynamoDB
3. Analyzes response/document
4. Updates provider state with screening results
5. Emits appropriate next events (SendMessageRequested or ScreeningCompleted)
6. Exits immediately

Following agent principles:
- No waiting or loops
- State persisted to DynamoDB before exit
- Events are the only communication mechanism
"""

from datetime import datetime
from typing import Any

import structlog

from agents.screening.config import get_screening_config
from agents.screening.models import (
    DocumentAnalysis,
    ScreeningDecision,
    ScreeningResult,
)
from agents.screening.prompts import get_system_prompt
from agents.screening.tools import (
    classify_response,
    determine_screening_outcome,
    evaluate_document_ocr,
    extract_keywords,
    map_decision_to_status,
    trigger_textract_async,
)
from agents.shared.exceptions import ProviderNotFoundError, RecruitmentError
from agents.shared.models.events import (
    DocumentProcessedEvent,
    DocumentType,
    MessageType,
    ProviderResponseReceivedEvent,
    ScreeningCompletedEvent,
    ScreeningResults,
    SendMessageRequestedEvent,
    TemplateData,
    TraceContext,
    parse_event,
)
from agents.shared.state_machine import ProviderStatus, validate_transition
from agents.shared.tools.dynamodb import (
    load_provider_state,
    update_provider_state,
)
from agents.shared.tools.eventbridge import send_event

# LLM imports for Phase 5 LLM Enhancement
from agents.screening.llm_tools import (
    classify_response_with_llm,
    extract_equipment_with_llm,
    analyze_document_with_llm,
    is_llm_screening_enabled,
    get_conversation_context_for_screening,
    get_campaign_type,
    load_equipment_keywords,
)

log = structlog.get_logger()


class ScreeningError(RecruitmentError):
    """Error during screening agent execution."""
    
    def __init__(
        self,
        message: str,
        campaign_id: str,
        provider_id: str,
        *,
        event_type: str | None = None,
        errors: list[str] | None = None,
    ):
        super().__init__(
            message,
            campaign_id=campaign_id,
            provider_id=provider_id,
        )
        self.campaign_id = campaign_id
        self.provider_id = provider_id
        self.event_type = event_type
        self.errors = errors or []


def _get_campaign_requirements(
    campaign_id: str,
) -> tuple[list[str], list[str], bool, int]:
    """
    Get campaign requirements from DynamoDB.
    
    Falls back to demo defaults if campaign record is not found.
    
    Returns:
        Tuple of (required_equipment, required_documents, travel_required, insurance_min)
    """
    from agents.shared.tools.dynamodb import load_campaign_record
    
    campaign = load_campaign_record(campaign_id)
    if campaign and campaign.requirements:
        reqs = campaign.requirements
        equipment = reqs.get("equipment", {})
        documents = reqs.get("documents", {})
        return (
            equipment.get("required", ["bucket_truck", "spectrum_analyzer"]),
            documents.get("required", ["insurance_certificate"]),
            reqs.get("travel_required", True),
            documents.get("insurance_min_coverage", 2_000_000),
        )
    
    # Fallback to demo defaults
    log.debug("using_default_campaign_requirements", campaign_id=campaign_id)
    return (
        ["bucket_truck", "spectrum_analyzer"],
        ["insurance_certificate"],
        True,
        2_000_000,
    )


def _convert_llm_classification(
    llm_output,
) -> "ResponseClassification":
    """
    Convert LLM classification output to internal ResponseClassification.
    
    Args:
        llm_output: ResponseClassificationOutput from LLM
        
    Returns:
        ResponseClassification model
    """
    from agents.screening.models import ResponseClassification, ResponseIntent
    
    # Map LLM intent to internal enum
    intent_map = {
        "positive": ResponseIntent.POSITIVE,
        "negative": ResponseIntent.NEGATIVE,
        "question": ResponseIntent.QUESTION,
        "document_only": ResponseIntent.DOCUMENT_ONLY,
        "ambiguous": ResponseIntent.AMBIGUOUS,
    }
    
    intent = intent_map.get(llm_output.intent.lower(), ResponseIntent.AMBIGUOUS)
    
    return ResponseClassification(
        intent=intent,
        confidence=llm_output.confidence,
        keywords_matched=llm_output.key_phrases,
        reasoning=llm_output.reasoning,
        has_attachment=False,  # Set by caller if needed
    )


def _convert_llm_extraction(
    llm_output,
    required_equipment: list[str],
) -> "KeywordExtractionResult":
    """
    Convert LLM extraction output to internal KeywordExtractionResult.
    
    Args:
        llm_output: EquipmentExtractionOutput from LLM
        required_equipment: List of required equipment types
        
    Returns:
        KeywordExtractionResult model
    """
    from agents.screening.models import (
        KeywordExtractionResult,
        EquipmentMatch,
        CertificationMatch,
    )
    
    # Build equipment matches
    equipment_matches = []
    for eq_type in required_equipment:
        matched = eq_type in llm_output.equipment_confirmed
        denied = eq_type in llm_output.equipment_denied
        
        equipment_matches.append(EquipmentMatch(
            equipment_type=eq_type,
            matched=matched,
            matched_keywords=[eq_type] if matched else [],
            confidence=llm_output.confidence if matched else 0.5,
        ))
    
    # Build certification matches
    certification_matches = [
        CertificationMatch(
            certification_type=cert.lower().replace(" ", "_").replace("+", "_plus"),
            matched=True,
            matched_keywords=[cert],
        )
        for cert in llm_output.certifications_mentioned
    ]
    
    return KeywordExtractionResult(
        equipment_matches=equipment_matches,
        certification_matches=certification_matches,
        travel_confirmed=llm_output.travel_willing,
        travel_keywords_matched=["travel"] if llm_output.travel_willing else [],
    )


def handle_provider_response_received(
    detail_type: str,
    detail: dict[str, Any],
) -> ScreeningResult:
    """
    Handle ProviderResponseReceived event.
    
    This is called when a provider replies to an outreach email.
    The agent analyzes the response, extracts keywords, and determines
    the next action.
    
    Args:
        detail_type: EventBridge detail-type (should be "ProviderResponseReceived")
        detail: Event detail payload
        
    Returns:
        ScreeningResult with decision and reasoning
        
    Raises:
        ScreeningError: If screening fails
        ValidationError: If event payload is invalid
    """
    log.info(
        "screening_agent_invoked",
        detail_type=detail_type,
    )
    
    # 1. Parse and validate event
    event = parse_event(detail_type, detail)
    if not isinstance(event, ProviderResponseReceivedEvent):
        raise ScreeningError(
            f"Unexpected event type: {detail_type}",
            campaign_id=detail.get("campaign_id", "unknown"),
            provider_id=detail.get("provider_id", "unknown"),
            event_type=detail_type,
        )
    
    log.info(
        "provider_response_received",
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        has_attachments=len(event.attachments) > 0,
        attachment_count=len(event.attachments),
        body_length=len(event.body) if event.body else 0,
    )
    
    # 2. Load current provider state
    provider_state = load_provider_state(event.campaign_id, event.provider_id)
    if not provider_state:
        raise ScreeningError(
            "Provider not found in database",
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
            event_type=detail_type,
        )
    
    log.debug(
        "provider_state_loaded",
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        current_status=provider_state.status.value,
    )
    
    # 3. Get campaign requirements
    (
        required_equipment,
        required_documents,
        travel_required,
        insurance_min,
    ) = _get_campaign_requirements(event.campaign_id)
    
    # 3b. Load conversation history for LLM context
    conversation_context = get_conversation_context_for_screening(
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        market=provider_state.provider_market or "unknown",
    )
    
    # 4. Classify response intent (LLM with fallback)
    llm_used_for_classification = False
    if is_llm_screening_enabled():
        try:
            llm_classification = classify_response_with_llm(
                response_body=event.body,
                has_attachments=len(event.attachments) > 0,
                campaign_type=get_campaign_type(event.campaign_id),
                previous_status=provider_state.status.value,
                conversation_history=conversation_context,
            )
            # Convert LLM output to internal format
            response_classification = _convert_llm_classification(llm_classification)
            llm_used_for_classification = True
            log.debug("used_llm_for_classification", intent=llm_classification.intent)
        except Exception as e:
            log.warning(
                "llm_classification_failed_using_fallback",
                error=str(e),
                error_type=type(e).__name__,
            )
            response_classification = classify_response(
                response_body=event.body,
                has_attachments=len(event.attachments) > 0,
            )
    else:
        response_classification = classify_response(
            response_body=event.body,
            has_attachments=len(event.attachments) > 0,
        )
    
    # 5. Extract keywords (LLM with fallback)
    llm_used_for_extraction = False
    if is_llm_screening_enabled():
        try:
            llm_extraction = extract_equipment_with_llm(
                response_body=event.body,
                required_equipment=required_equipment,
                equipment_keywords=load_equipment_keywords(),
            )
            # Convert LLM output to internal format
            keyword_extraction = _convert_llm_extraction(llm_extraction, required_equipment)
            llm_used_for_extraction = True
            log.debug(
                "used_llm_for_extraction",
                confirmed=llm_extraction.equipment_confirmed,
            )
        except Exception as e:
            log.warning(
                "llm_extraction_failed_using_fallback",
                error=str(e),
                error_type=type(e).__name__,
            )
            keyword_extraction = extract_keywords(
                response_body=event.body,
                required_equipment=required_equipment,
            )
    else:
        keyword_extraction = extract_keywords(
            response_body=event.body,
            required_equipment=required_equipment,
        )
    
    # 6. Handle attachments - trigger Textract if documents present
    textract_jobs = []
    if event.attachments:
        for attachment in event.attachments:
            # Check if attachment is a processable document
            if attachment.content_type in ["application/pdf", "image/jpeg", "image/png"]:
                try:
                    job_info = trigger_textract_async(
                        document_s3_path=attachment.s3_path,
                        campaign_id=event.campaign_id,
                        provider_id=event.provider_id,
                        document_type=_guess_document_type(attachment.filename),
                    )
                    textract_jobs.append(job_info)
                    log.info(
                        "textract_job_triggered",
                        job_id=job_info.job_id,
                        filename=attachment.filename,
                    )
                except Exception as e:
                    log.error(
                        "textract_trigger_failed",
                        filename=attachment.filename,
                        error=str(e),
                    )
    
    # 7. Determine screening outcome
    # If we triggered Textract, we need to wait for DocumentProcessed
    if textract_jobs:
        # Documents are processing - update state to DOCUMENT_PROCESSING
        new_status = ProviderStatus.DOCUMENT_PROCESSING
        
        result = ScreeningResult(
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
            decision=ScreeningDecision.NEEDS_DOCUMENT,  # Temporary until docs processed
            confidence=0.8,
            reasoning="Documents submitted and being processed via Textract",
            response_classification=response_classification,
            keyword_extraction=keyword_extraction,
            document_analyses=[],
            equipment_confirmed=[
                m.equipment_type for m in keyword_extraction.equipment_matches
                if m.matched
            ],
            equipment_missing=[
                eq for eq in required_equipment
                if eq not in [m.equipment_type for m in keyword_extraction.equipment_matches if m.matched]
            ],
            certifications_found=[
                m.certification_type for m in keyword_extraction.certification_matches
                if m.matched
            ],
            travel_confirmed=keyword_extraction.travel_confirmed,
            next_action="await_document_processing",
            missing_documents=[att.filename for att in event.attachments],
        )
        
    else:
        # No documents to process - make immediate decision
        result = determine_screening_outcome(
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
            response_classification=response_classification,
            keyword_extraction=keyword_extraction,
            document_analyses=[],
            required_equipment=required_equipment,
            required_documents=required_documents,
            travel_required=travel_required,
            existing_equipment_confirmed=list(provider_state.equipment_confirmed),
            existing_documents_uploaded=list(provider_state.documents_uploaded),
        )
        
        new_status = ProviderStatus.from_string(map_decision_to_status(result.decision))
    
    # 8. Validate state transition
    validate_transition(provider_state.status, new_status)
    
    # 9. Update provider state in DynamoDB
    update_kwargs: dict[str, Any] = {
        "screening_notes": result.reasoning,
        "equipment_confirmed": result.equipment_confirmed,
        "equipment_missing": result.equipment_missing,
    }
    
    if result.travel_confirmed is not None:
        update_kwargs["travel_confirmed"] = result.travel_confirmed
    
    if result.certifications_found:
        update_kwargs["certifications"] = result.certifications_found
    
    update_provider_state(
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        new_status=new_status,
        expected_version=provider_state.version,
        **update_kwargs,
    )
    
    log.info(
        "provider_state_updated",
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        new_status=new_status.value,
    )
    
    # 10. Emit next events based on decision
    _emit_next_events(
        result=result,
        new_status=new_status,
        provider_state=provider_state,
        trace_context=event.trace_context,
    )
    
    return result


def handle_document_processed(
    detail_type: str,
    detail: dict[str, Any],
) -> ScreeningResult:
    """
    Handle DocumentProcessed event.
    
    This is called when Textract completes OCR on a provider document.
    The agent validates the document and updates the screening decision.
    
    Args:
        detail_type: EventBridge detail-type (should be "DocumentProcessed")
        detail: Event detail payload
        
    Returns:
        ScreeningResult with decision and reasoning
        
    Raises:
        ScreeningError: If screening fails
        ValidationError: If event payload is invalid
    """
    log.info(
        "screening_agent_invoked",
        detail_type=detail_type,
    )
    
    # 1. Parse and validate event
    event = parse_event(detail_type, detail)
    if not isinstance(event, DocumentProcessedEvent):
        raise ScreeningError(
            f"Unexpected event type: {detail_type}",
            campaign_id=detail.get("campaign_id", "unknown"),
            provider_id=detail.get("provider_id", "unknown"),
            event_type=detail_type,
        )
    
    log.info(
        "document_processed",
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        document_type=event.document_type.value,
        job_id=event.job_id,
    )
    
    # 2. Load current provider state
    provider_state = load_provider_state(event.campaign_id, event.provider_id)
    if not provider_state:
        raise ScreeningError(
            "Provider not found in database",
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
            event_type=detail_type,
        )
    
    # 3. Get campaign requirements
    (
        required_equipment,
        required_documents,
        travel_required,
        insurance_min,
    ) = _get_campaign_requirements(event.campaign_id)
    
    # 4. Evaluate document OCR results (LLM with fallback)
    extracted_fields = event.extracted_fields.model_dump() if event.extracted_fields else {}
    
    llm_used_for_document = False
    if is_llm_screening_enabled() and event.ocr_text:
        try:
            # Use LLM for document analysis
            llm_doc_result = analyze_document_with_llm(
                document_type=event.document_type.value,
                ocr_text=event.ocr_text,
            )
            
            # Convert LLM output to DocumentAnalysis
            from agents.screening.models import (
                DocumentAnalysis,
                DocumentValidation,
                InsuranceDetails,
            )
            from datetime import date
            
            document_analysis = DocumentAnalysis(
                document_type=event.document_type.value,
                s3_path=event.document_s3_path,
                job_id=event.job_id,
                validation=DocumentValidation(
                    valid=llm_doc_result.is_valid,
                    errors=llm_doc_result.validation_errors,
                    confidence=llm_doc_result.confidence,
                ),
                insurance_details=InsuranceDetails(
                    coverage_amount=llm_doc_result.coverage_amount,
                    expiry_date=llm_doc_result.expiry_date,
                    policy_holder=llm_doc_result.policy_holder,
                    policy_number=llm_doc_result.policy_number,
                    valid=llm_doc_result.is_valid,
                ) if llm_doc_result.is_insurance_document else None,
                raw_text=event.ocr_text,
            )
            llm_used_for_document = True
            log.debug(
                "used_llm_for_document_analysis",
                document_type=event.document_type.value,
                is_valid=llm_doc_result.is_valid,
            )
        except Exception as e:
            log.warning(
                "llm_document_analysis_failed_using_fallback",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Fall through to rule-based analysis
            document_analysis = evaluate_document_ocr(
                document_type=event.document_type.value,
                ocr_text=event.ocr_text,
                extracted_fields=extracted_fields,
                confidence_scores=event.confidence_scores,
            )
            # Update with event details
            document_analysis = DocumentAnalysis(
                document_type=document_analysis.document_type,
                s3_path=event.document_s3_path,
                job_id=event.job_id,
                validation=document_analysis.validation,
                insurance_details=document_analysis.insurance_details,
                raw_text=document_analysis.raw_text,
            )
    else:
        # Rule-based document analysis
        document_analysis = evaluate_document_ocr(
            document_type=event.document_type.value,
            ocr_text=event.ocr_text,
            extracted_fields=extracted_fields,
            confidence_scores=event.confidence_scores,
        )
        # Update with event details
        document_analysis = DocumentAnalysis(
            document_type=document_analysis.document_type,
            s3_path=event.document_s3_path,
            job_id=event.job_id,
            validation=document_analysis.validation,
            insurance_details=document_analysis.insurance_details,
            raw_text=document_analysis.raw_text,
        )
    
    # 5. Update documents uploaded in state
    documents_uploaded = list(provider_state.documents_uploaded)
    if document_analysis.validation.valid and event.document_type.value not in documents_uploaded:
        documents_uploaded.append(event.document_type.value)
    
    # Update artifacts
    artifacts = dict(provider_state.artifacts)
    artifacts[event.document_s3_path.split("/")[-1]] = event.document_s3_path
    
    # 6. Determine screening outcome with updated document info
    result = determine_screening_outcome(
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        response_classification=None,  # No response in this event
        keyword_extraction=None,
        document_analyses=[document_analysis],
        required_equipment=required_equipment,
        required_documents=required_documents,
        travel_required=travel_required,
        existing_equipment_confirmed=list(provider_state.equipment_confirmed),
        existing_documents_uploaded=documents_uploaded,
    )
    
    new_status = ProviderStatus.from_string(map_decision_to_status(result.decision))
    
    # 7. Validate state transition
    validate_transition(provider_state.status, new_status)
    
    # 8. Update provider state
    update_kwargs2: dict[str, Any] = {
        "documents_uploaded": documents_uploaded,
        "artifacts": artifacts,
        "screening_notes": result.reasoning,
    }
    
    # Store extracted insurance data
    if document_analysis.insurance_details:
        extracted_data = dict(provider_state.extracted_data)
        extracted_data["insurance"] = {
            "coverage_amount": document_analysis.insurance_details.coverage_amount,
            "expiry_date": (
                document_analysis.insurance_details.expiry_date.isoformat()
                if document_analysis.insurance_details.expiry_date
                else None
            ),
            "policy_holder": document_analysis.insurance_details.policy_holder,
            "policy_number": document_analysis.insurance_details.policy_number,
            "valid": document_analysis.insurance_details.valid,
        }
        update_kwargs2["extracted_data"] = extracted_data
    
    update_provider_state(
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        new_status=new_status,
        expected_version=provider_state.version,
        **update_kwargs2,
    )
    
    log.info(
        "provider_state_updated",
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        new_status=new_status.value,
        document_valid=document_analysis.validation.valid,
    )
    
    # 9. Emit next events based on decision
    _emit_next_events(
        result=result,
        new_status=new_status,
        provider_state=provider_state,
        trace_context=event.trace_context,
    )
    
    return result


def _guess_document_type(filename: str) -> str | None:
    """Guess document type from filename."""
    filename_lower = filename.lower()
    
    if "insurance" in filename_lower or "coi" in filename_lower or "liability" in filename_lower:
        return DocumentType.INSURANCE_CERTIFICATE.value
    elif "license" in filename_lower:
        return DocumentType.LICENSE.value
    elif "cert" in filename_lower:
        return DocumentType.CERTIFICATION.value
    elif "w9" in filename_lower or "w-9" in filename_lower:
        return DocumentType.W9.value
    
    return None


def _emit_next_events(
    result: ScreeningResult,
    new_status: ProviderStatus,
    provider_state: Any,  # ProviderState
    trace_context: TraceContext | None,
) -> None:
    """
    Emit appropriate events based on screening result.
    
    Args:
        result: Screening result
        new_status: New provider status
        provider_state: Current provider state
        trace_context: Trace context for propagation
    """
    # Terminal states emit ScreeningCompleted
    if new_status in (ProviderStatus.QUALIFIED, ProviderStatus.REJECTED):
        screening_event = ScreeningCompletedEvent(
            campaign_id=result.campaign_id,
            provider_id=result.provider_id,
            decision=_convert_decision(result.decision),
            reasoning=result.reasoning,
            confidence_score=result.confidence,
            screening_results=ScreeningResults(
                equipment_confirmed=result.equipment_confirmed,
                equipment_missing=result.equipment_missing,
                travel_confirmed=result.travel_confirmed,
                documents_valid=result.documents_valid,
                insurance_coverage=result.insurance_coverage,
                insurance_expiry=result.insurance_expiry,
                certifications_found=result.certifications_found,
            ),
            artifacts_reviewed=[
                analysis.s3_path for analysis in result.document_analyses
                if analysis.s3_path
            ],
            trace_context=trace_context,
        )
        
        send_event(screening_event, source="recruitment.agents.screening")
        
        log.info(
            "screening_completed_event_emitted",
            campaign_id=result.campaign_id,
            provider_id=result.provider_id,
            decision=new_status.value,
        )
    
    # WAITING_DOCUMENT needs document request
    elif new_status == ProviderStatus.WAITING_DOCUMENT and result.missing_documents:
        message_event = SendMessageRequestedEvent(
            campaign_id=result.campaign_id,
            provider_id=result.provider_id,
            provider_email=provider_state.provider_email,
            provider_name=provider_state.provider_name,
            provider_market=provider_state.provider_market,
            message_type=MessageType.MISSING_DOCUMENT,
            template_data=TemplateData(
                missing_documents=result.missing_documents,
            ),
            trace_context=trace_context,
        )
        
        send_event(message_event, source="recruitment.agents.screening")
        
        log.info(
            "document_request_event_emitted",
            campaign_id=result.campaign_id,
            provider_id=result.provider_id,
            missing_documents=result.missing_documents,
        )
    
    # WAITING_RESPONSE with questions needs clarification
    elif new_status == ProviderStatus.WAITING_RESPONSE and result.questions_for_provider:
        message_event = SendMessageRequestedEvent(
            campaign_id=result.campaign_id,
            provider_id=result.provider_id,
            provider_email=provider_state.provider_email,
            provider_name=provider_state.provider_name,
            provider_market=provider_state.provider_market,
            message_type=MessageType.CLARIFICATION,
            template_data=TemplateData(
                question="; ".join(result.questions_for_provider),
            ),
            trace_context=trace_context,
        )
        
        send_event(message_event, source="recruitment.agents.screening")
        
        log.info(
            "clarification_event_emitted",
            campaign_id=result.campaign_id,
            provider_id=result.provider_id,
            questions=result.questions_for_provider,
        )


def _convert_decision(decision: ScreeningDecision) -> Any:
    """Convert local decision enum to shared event enum."""
    from agents.shared.models.events import ScreeningDecision as EventDecision
    
    mapping = {
        ScreeningDecision.QUALIFIED: EventDecision.QUALIFIED,
        ScreeningDecision.REJECTED: EventDecision.REJECTED,
        ScreeningDecision.UNDER_REVIEW: EventDecision.UNDER_REVIEW,
        ScreeningDecision.ESCALATED: EventDecision.ESCALATED,
    }
    return mapping.get(decision, EventDecision.UNDER_REVIEW)
