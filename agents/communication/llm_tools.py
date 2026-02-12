"""
LLM-Powered Email Generation Tools

Tools for generating personalized emails using AWS Bedrock Claude.
Provides structured output via Pydantic models.
"""

import structlog

from agents.communication.llm_prompts import (
    EMAIL_GENERATION_SYSTEM_PROMPT,
    build_email_generation_prompt,
    build_reply_email_prompt,
)
from agents.communication.models import EmailDraft
from agents.shared.llm import (
    BedrockLLMClient,
    get_llm_client,
    EmailGenerationOutput,
    get_llm_settings,
)
from agents.shared.llm.bedrock_client import LLMInvocationError, LLMParsingError
from agents.shared.tools.email_thread import (
    create_thread_id,
    load_thread_history,
    format_thread_for_context,
)
from agents.shared.tools.email import encode_reply_to
from agents.shared.config import get_settings


log = structlog.get_logger()


def get_provider_type(provider_state) -> str:
    """
    Determine provider type for tone adjustment.
    
    Args:
        provider_state: Provider state from DynamoDB (or None)
        
    Returns:
        Provider type string: 'corporate' or 'independent_contractor'
    """
    # Default to independent_contractor if we don't have state
    if not provider_state:
        return "independent_contractor"
    
    # Check provider_name for corporate indicators
    name = getattr(provider_state, "provider_name", "") or ""
    corporate_indicators = ["LLC", "Inc", "Corp", "Ltd", "Company", "Services"]
    
    for indicator in corporate_indicators:
        if indicator.lower() in name.lower():
            return "corporate"
    
    return "independent_contractor"


def generate_email_with_llm(
    campaign_id: str,
    provider_id: str,
    provider_name: str,
    provider_market: str,
    provider_email: str,
    message_type: str,
    template_data: dict,
    provider_type: str = "independent_contractor",
    conversation_history: list | None = None,
    client: BedrockLLMClient | None = None,
) -> EmailGenerationOutput:
    """
    Generate personalized email using LLM.
    
    The LLM personalizes based on:
    - Provider history and market
    - Provider type (corporate vs independent)
    - Previous conversation context
    - Campaign requirements
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        provider_name: Provider's display name
        provider_market: Target market
        provider_email: Provider's email address
        message_type: Type of message (initial_outreach, follow_up, etc.)
        template_data: Additional context data
        provider_type: Provider type for tone adjustment
        conversation_history: Optional pre-loaded conversation history
        client: Optional LLM client (for testing)
        
    Returns:
        EmailGenerationOutput with subject, body, tone, etc.
        
    Raises:
        LLMInvocationError: If LLM call fails
        LLMParsingError: If response cannot be parsed
    """
    log.info(
        "llm_email_generation_start",
        campaign_id=campaign_id,
        provider_id=provider_id,
        message_type=message_type,
    )
    
    # Load conversation history if not provided
    conversation_context = "[No previous conversation]"
    if conversation_history is not None:
        conversation_context = format_thread_for_context(conversation_history, max_messages=5)
    else:
        try:
            thread_id = create_thread_id(campaign_id, provider_market, provider_id)
            messages = load_thread_history(thread_id, limit=5)
            if messages:
                conversation_context = format_thread_for_context(messages, max_messages=5)
        except Exception as e:
            log.debug(
                "conversation_history_load_failed",
                error=str(e),
            )
    
    # Build prompt
    prompt = build_email_generation_prompt(
        message_type=message_type,
        provider_name=provider_name,
        provider_market=provider_market,
        provider_type=provider_type,
        template_data=template_data,
        conversation_history=conversation_context,
    )
    
    # Get LLM client
    llm_client = client or get_llm_client()
    
    # Invoke LLM with structured output
    result = llm_client.invoke_structured(
        prompt=prompt,
        output_schema=EmailGenerationOutput,
        system_prompt=EMAIL_GENERATION_SYSTEM_PROMPT,
    )
    
    log.info(
        "llm_email_generation_success",
        campaign_id=campaign_id,
        provider_id=provider_id,
        subject_preview=result.subject[:50] if result.subject else None,
        tone=result.tone,
    )
    
    return result


def generate_reply_email_with_llm(
    campaign_id: str,
    provider_id: str,
    provider_name: str,
    provider_market: str,
    provider_email: str,
    reply_reason: str,
    context: dict,
    provider_type: str = "independent_contractor",
    conversation_history: list | None = None,
    client: BedrockLLMClient | None = None,
) -> EmailGenerationOutput:
    """
    Generate reply email using LLM.
    
    Used when Screening Agent requests a reply to provider's message.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        provider_name: Provider's display name
        provider_market: Target market
        provider_email: Provider's email address
        reply_reason: Reason for reply (missing_attachment, etc.)
        context: Additional context (missing_items, questions)
        provider_type: Provider type for tone adjustment
        conversation_history: Optional pre-loaded conversation history
        client: Optional LLM client (for testing)
        
    Returns:
        EmailGenerationOutput with subject, body, tone, etc.
    """
    log.info(
        "llm_reply_generation_start",
        campaign_id=campaign_id,
        provider_id=provider_id,
        reply_reason=reply_reason,
    )
    
    # Load conversation history if not provided
    conversation_context = "[No previous conversation]"
    if conversation_history is not None:
        conversation_context = format_thread_for_context(conversation_history, max_messages=5)
    else:
        try:
            thread_id = create_thread_id(campaign_id, provider_market, provider_id)
            messages = load_thread_history(thread_id, limit=5)
            if messages:
                conversation_context = format_thread_for_context(messages, max_messages=5)
        except Exception as e:
            log.debug(
                "conversation_history_load_failed",
                error=str(e),
            )
    
    # Build prompt
    prompt = build_reply_email_prompt(
        provider_name=provider_name,
        provider_market=provider_market,
        provider_type=provider_type,
        reply_reason=reply_reason,
        context=context,
        conversation_history=conversation_context,
    )
    
    # Get LLM client
    llm_client = client or get_llm_client()
    
    # Invoke LLM with structured output
    result = llm_client.invoke_structured(
        prompt=prompt,
        output_schema=EmailGenerationOutput,
        system_prompt=EMAIL_GENERATION_SYSTEM_PROMPT,
    )
    
    log.info(
        "llm_reply_generation_success",
        campaign_id=campaign_id,
        provider_id=provider_id,
        reply_reason=reply_reason,
    )
    
    return result


def create_draft_from_llm_output(
    llm_output: EmailGenerationOutput,
    campaign_id: str,
    provider_id: str,
    provider_email: str,
    message_type: str,
) -> EmailDraft:
    """
    Convert LLM output to EmailDraft for sending.
    
    Creates a fully-formed email draft ready for SES sending,
    including Reply-To address encoding.
    
    Args:
        llm_output: LLM-generated email content
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        provider_email: Recipient email address
        message_type: Type of message
        
    Returns:
        EmailDraft ready for sending
    """
    # Encode Reply-To address for response tracking
    settings = get_settings()
    reply_to = encode_reply_to(
        campaign_id=campaign_id,
        provider_id=provider_id,
        domain=settings.ses_reply_to_domain,
    )
    
    return EmailDraft(
        campaign_id=campaign_id,
        provider_id=provider_id,
        to_address=provider_email,
        reply_to=reply_to,
        subject=llm_output.subject,
        body_text=llm_output.body_text,
        body_html=None,  # LLM generates plain text only
        message_type=message_type,
        template_name=None,  # LLM-generated, no template
    )


def is_llm_email_enabled() -> bool:
    """
    Check if LLM email generation is enabled.
    
    Returns:
        True if LLM is enabled for email generation
    """
    settings = get_llm_settings()
    return settings.is_feature_enabled("email")
