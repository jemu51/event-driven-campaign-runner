"""
Communication Agent

Event handler for SendMessageRequested events.
Drafts and sends personalized emails to providers.

This agent:
1. Receives SendMessageRequested events
2. Loads provider state from DynamoDB (if exists)
3. Loads conversation history for context
4. Drafts personalized email using LLM (or template fallback)
5. Sends email via SES with Reply-To encoding
6. Saves email to thread history
7. Updates provider state (WAITING_RESPONSE)
8. Exits immediately

Following agent principles:
- No waiting or loops
- State persisted to DynamoDB before exit
- Events are the only communication mechanism
"""

import time
from typing import Any

import structlog

from agents.communication.config import get_communication_config
from agents.communication.models import (
    CommunicationResult,
    EmailDraft,
    EmailResult,
)
from agents.communication.prompts import get_system_prompt
from agents.communication.tools import (
    draft_email,
    send_provider_email,
)
from agents.communication.llm_tools import (
    generate_email_with_llm,
    create_draft_from_llm_output,
    get_provider_type,
    is_llm_email_enabled,
)
from agents.shared.exceptions import ProviderNotFoundError, RecruitmentError
from agents.shared.models.events import (
    MessageType,
    ReplyToProviderRequestedEvent,
    SendMessageRequestedEvent,
    parse_event,
)
from agents.shared.models.email_thread import EmailDirection
from agents.shared.state_machine import ProviderStatus
from agents.shared.tools.dynamodb import (
    load_provider_state,
    update_provider_state,
)
from agents.shared.tools.email_thread import (
    create_thread_id,
    create_outbound_message,
    load_thread_history,
    format_thread_for_context,
)

log = structlog.get_logger()


class CommunicationError(RecruitmentError):
    """Error during communication agent execution."""
    
    def __init__(
        self,
        message: str,
        campaign_id: str,
        provider_id: str,
        *,
        email_sent: bool = False,
        errors: list[str] | None = None,
    ):
        super().__init__(
            message,
            campaign_id=campaign_id,
            provider_id=provider_id,
        )
        self.campaign_id = campaign_id
        self.provider_id = provider_id
        self.email_sent = email_sent
        self.errors = errors or []


def handle_send_message_requested(
    detail_type: str,
    detail: dict[str, Any],
) -> CommunicationResult:
    """
    Handle SendMessageRequested event.
    
    This is the main entry point for the Communication Agent.
    Called when EventBridge delivers a SendMessageRequested event.
    
    Args:
        detail_type: EventBridge detail-type (should be "SendMessageRequested")
        detail: Event detail payload
        
    Returns:
        CommunicationResult with summary of actions taken
        
    Raises:
        CommunicationError: If communication fails
        ValidationError: If event payload is invalid
    """
    log.info(
        "communication_agent_invoked",
        detail_type=detail_type,
    )
    
    # 1. Parse and validate event
    event = parse_event(detail_type, detail)
    if not isinstance(event, SendMessageRequestedEvent):
        raise CommunicationError(
            f"Unexpected event type: {detail_type}",
            campaign_id=detail.get("campaign_id", "unknown"),
            provider_id=detail.get("provider_id", "unknown"),
        )
    
    log.info(
        "event_received",
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        message_type=event.message_type.value,
    )
    
    # 2. Load provider state (if exists) for additional context
    provider_state = None
    try:
        provider_state = load_provider_state(
            event.campaign_id,
            event.provider_id,
        )
    except Exception as e:
        # Provider may not exist yet (first contact)
        log.debug(
            "provider_state_not_found",
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
            error=str(e),
        )
    
    # 3. Determine provider info from event or state
    provider_email = event.provider_email
    provider_name = event.provider_name
    provider_market = event.provider_market
    
    if provider_state:
        # Use state values if event doesn't have them
        provider_email = provider_email or provider_state.provider_email
        provider_name = provider_name or provider_state.provider_name
        provider_market = provider_market or provider_state.provider_market
    
    if not provider_email:
        raise CommunicationError(
            "No provider email address available",
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
        )
    
    # 4. Build template data
    template_data = {}
    if event.template_data:
        template_data = event.template_data.model_dump(exclude_none=True)
    
    # Add defaults for common template variables
    if "campaign_type" not in template_data:
        template_data["campaign_type"] = "work opportunity"
    if "market" not in template_data and provider_market:
        template_data["market"] = provider_market.title()
    
    # 4a. Load conversation history for LLM context
    conversation_history = []
    thread_id = None
    if provider_market:
        try:
            thread_id = create_thread_id(event.campaign_id, provider_market, event.provider_id)
            conversation_history = load_thread_history(thread_id, limit=5)
        except Exception as e:
            log.debug(
                "conversation_history_load_failed",
                error=str(e),
            )
    
    # 5. Draft email using LLM or template fallback
    llm_generated = False
    try:
        if is_llm_email_enabled():
            # Use LLM for email generation
            log.debug("using_llm_for_email_generation")
            provider_type = get_provider_type(provider_state)
            
            llm_output = generate_email_with_llm(
                campaign_id=event.campaign_id,
                provider_id=event.provider_id,
                provider_name=provider_name or "Provider",
                provider_market=provider_market or "Unknown",
                provider_email=provider_email,
                message_type=event.message_type.value,
                template_data=template_data,
                provider_type=provider_type,
                conversation_history=conversation_history,
            )
            
            draft = create_draft_from_llm_output(
                llm_output=llm_output,
                campaign_id=event.campaign_id,
                provider_id=event.provider_id,
                provider_email=provider_email,
                message_type=event.message_type.value,
            )
            llm_generated = True
        else:
            # Use template-based generation (fallback)
            log.debug("using_template_for_email_generation")
            draft = draft_email(
                campaign_id=event.campaign_id,
                provider_id=event.provider_id,
                provider_email=provider_email,
                provider_name=provider_name or "Provider",
                provider_market=provider_market or "Unknown",
                message_type=event.message_type.value,
                template_data=template_data,
                custom_message=event.custom_message,
            )
    except Exception as e:
        log.warning(
            "llm_email_generation_failed_using_fallback",
            error=str(e),
            error_type=type(e).__name__,
        )
        # Fallback to template-based generation
        try:
            draft = draft_email(
                campaign_id=event.campaign_id,
                provider_id=event.provider_id,
                provider_email=provider_email,
                provider_name=provider_name or "Provider",
                provider_market=provider_market or "Unknown",
                message_type=event.message_type.value,
                template_data=template_data,
                custom_message=event.custom_message,
            )
        except Exception as fallback_error:
            log.error(
                "email_drafting_failed",
                campaign_id=event.campaign_id,
                provider_id=event.provider_id,
                error=str(fallback_error),
            )
            raise CommunicationError(
                f"Failed to draft email: {fallback_error}",
                campaign_id=event.campaign_id,
                provider_id=event.provider_id,
                errors=[str(e), str(fallback_error)],
            ) from fallback_error
    
    log.info(
        "email_drafted",
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        subject=draft.subject[:50],
        llm_generated=llm_generated,
    )
    
    # 6. Send email via SES
    email_result = send_provider_email(draft)
    
    if not email_result.success:
        log.error(
            "email_sending_failed",
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
            error=email_result.error_message,
        )
        raise CommunicationError(
            f"Failed to send email: {email_result.error_message}",
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
            email_sent=False,
            errors=[email_result.error_message or "Unknown error"],
        )
    
    log.info(
        "email_sent",
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        message_id=email_result.message_id,
    )
    
    # 6b. Save email to thread history
    try:
        from agents.shared.config import get_settings
        
        settings = get_settings()
        thread_id = create_thread_id(
            campaign_id=event.campaign_id,
            market_id=provider_market or "unknown",
            provider_id=event.provider_id,
        )
        
        # create_outbound_message saves the message internally
        email_message = create_outbound_message(
            thread_id=thread_id,
            subject=draft.subject,
            body_text=draft.body_text,
            message_id=email_result.message_id or f"msg-{int(time.time())}",
            email_from=settings.ses_from_address,
            email_to=provider_email,
            message_type=event.message_type.value,
            metadata={"llm_generated": llm_generated},
        )
        
        log.debug(
            "email_saved_to_thread",
            thread_id=thread_id,
            message_id=email_result.message_id,
        )
    except Exception as thread_error:
        # Non-fatal: log but don't fail the operation
        log.warning(
            "failed_to_save_email_to_thread",
            error=str(thread_error),
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
        )
    
    # 7. Update provider state in DynamoDB
    state_updated = False
    new_status = None
    errors: list[str] = []
    
    # Use composite thread_id (not SES message_id) for consistent thread lookups
    composite_thread_id = thread_id or create_thread_id(
        campaign_id=event.campaign_id,
        market_id=provider_market or "unknown",
        provider_id=event.provider_id,
    )
    
    if provider_state:
        try:
            update_provider_state(
                campaign_id=event.campaign_id,
                provider_id=event.provider_id,
                new_status=ProviderStatus.WAITING_RESPONSE,
                email_thread_id=composite_thread_id,
            )
            state_updated = True
            new_status = ProviderStatus.WAITING_RESPONSE.value
            
            log.info(
                "provider_state_updated",
                campaign_id=event.campaign_id,
                provider_id=event.provider_id,
                new_status=ProviderStatus.WAITING_RESPONSE.value,
                email_thread_id=composite_thread_id,
            )
        except Exception as e:
            # Log but don't fail - email was already sent
            log.error(
                "state_update_failed",
                campaign_id=event.campaign_id,
                provider_id=event.provider_id,
                error=str(e),
            )
            errors.append(f"State update failed: {e}")
    else:
        log.warning(
            "no_provider_state_to_update",
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
        )
        errors.append("Provider state not found for update")
    
    # 8. Return result and exit
    result = CommunicationResult(
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        message_type=event.message_type.value,
        email_sent=True,
        message_id=email_result.message_id,
        state_updated=state_updated,
        new_status=new_status,
        errors=errors,
    )
    
    log.info(
        "communication_agent_completed",
        campaign_id=event.campaign_id,
        provider_id=event.provider_id,
        email_sent=result.email_sent,
        state_updated=result.state_updated,
    )
    
    return result


def handle_reply_to_provider_requested(
    detail_type: str,
    detail: dict[str, Any],
) -> CommunicationResult:
    """
    Handle ReplyToProviderRequested event.
    
    This is called when the screening agent needs to send a reply
    to a provider for missing documents, clarification, etc.
    
    Args:
        detail_type: EventBridge detail-type (should be "ReplyToProviderRequested")
        detail: Event detail payload
        
    Returns:
        CommunicationResult with summary of actions taken
        
    Raises:
        CommunicationError: If communication fails
        ValidationError: If event payload is invalid
    """
    log.info(
        "reply_handler_invoked",
        detail_type=detail_type,
    )
    
    # 1. Parse and validate event
    event = parse_event(detail_type, detail)
    if not isinstance(event, ReplyToProviderRequestedEvent):
        raise CommunicationError(
            f"Unexpected event type: {detail_type}",
            campaign_id=detail.get("campaign_id", "unknown"),
            provider_id=detail.get("provider_id", "unknown"),
        )
    
    # 2. Convert to SendMessageRequestedEvent format for reuse of existing logic
    # Map reply_type to message_type
    message_type_map = {
        "missing_document": MessageType.MISSING_DOCUMENT,
        "invalid_document": MessageType.MISSING_DOCUMENT,
        "clarification_needed": MessageType.CLARIFICATION,
        "additional_info": MessageType.CLARIFICATION,
    }
    message_type = message_type_map.get(
        event.reply_type.value,
        MessageType.CLARIFICATION,
    )
    
    # 3. Build template data from context
    from agents.shared.models.events import TemplateData
    
    template_data = TemplateData(
        missing_documents=event.context.missing_items if event.context.missing_items else None,
        question=(
            "; ".join(event.context.questions)
            if event.context.questions
            else None
        ),
    )
    
    # 4. Create a SendMessageRequested-style detail for the existing handler
    send_message_detail = {
        "campaign_id": event.campaign_id,
        "provider_id": event.provider_id,
        "provider_email": event.provider_email,
        "provider_name": event.provider_name,
        "provider_market": event.provider_market,
        "message_type": message_type.value,
        "template_data": template_data.model_dump(exclude_none=True),
    }
    
    if event.trace_context:
        send_message_detail["trace_context"] = event.trace_context.model_dump(exclude_none=True)
    
    # 5. Delegate to the existing send message handler
    return handle_send_message_requested("SendMessageRequested", send_message_detail)


# Agent entry point for Strands AgentCore
def main(event: dict[str, Any]) -> dict[str, Any]:
    """
    Main entry point for Strands AgentCore.
    
    Args:
        event: EventBridge event with detail-type and detail
        
    Returns:
        Result of communication operation
    """
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})
    
    # Route to appropriate handler based on event type
    if detail_type == "ReplyToProviderRequested":
        result = handle_reply_to_provider_requested(detail_type, detail)
    else:
        result = handle_send_message_requested(detail_type, detail)
    
    return result.model_dump()
