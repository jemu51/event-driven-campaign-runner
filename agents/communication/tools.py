"""
Communication Agent Tools

Tools for email drafting, template rendering, and sending.
All tools are idempotent and follow agent principles.
"""

from pathlib import Path
from typing import Any

import structlog

from agents.communication.config import get_communication_config
from agents.communication.models import (
    EmailDraft,
    EmailResult,
    EmailStatus,
    TemplateContext,
)
from agents.shared.config import get_settings
from agents.shared.exceptions import (
    InvalidEmailFormatError,
    SESError,
)
from agents.shared.tools.email import (
    encode_reply_to,
    send_ses_email,
)

log = structlog.get_logger()


# Template file mapping based on message type
TEMPLATE_FILES: dict[str, str] = {
    "initial_outreach": "initial_outreach.txt",
    "follow_up": "follow_up.txt",
    "missing_document": "missing_document.txt",
    "clarification": "clarification.txt",
    "qualified_confirmation": "qualified_confirmation.txt",
    "rejection": "rejection.txt",
}

# Subject templates based on message type
SUBJECT_TEMPLATES: dict[str, str] = {
    "initial_outreach": "Opportunity: {campaign_type} technicians needed in {market}",
    "follow_up": "Re: Opportunity: {campaign_type} in {market} - Follow Up",
    "missing_document": "Re: {campaign_type} - Document Required",
    "clarification": "Re: {campaign_type} - Quick Question",
    "qualified_confirmation": "{campaign_type} - You're Qualified!",
    "rejection": "Re: {campaign_type} - Application Status",
}


def get_template_path(message_type: str) -> Path:
    """
    Get the file path for a message type's template.
    
    Args:
        message_type: Type of message (e.g., initial_outreach)
        
    Returns:
        Path to template file
        
    Raises:
        ValueError: If message type is unknown
    """
    config = get_communication_config()
    
    if message_type not in TEMPLATE_FILES:
        raise ValueError(
            f"Unknown message type: '{message_type}'. "
            f"Valid types: {list(TEMPLATE_FILES.keys())}"
        )
    
    return config.template_path / TEMPLATE_FILES[message_type]


def load_template(message_type: str) -> str:
    """
    Load email template content for a message type.
    
    Args:
        message_type: Type of message (e.g., initial_outreach)
        
    Returns:
        Template content string
        
    Raises:
        FileNotFoundError: If template file doesn't exist
        ValueError: If message type is unknown
    """
    template_path = get_template_path(message_type)
    
    if not template_path.exists():
        log.warning(
            "template_not_found",
            message_type=message_type,
            path=str(template_path),
        )
        raise FileNotFoundError(f"Template not found: {template_path}")
    
    log.debug(
        "loading_template",
        message_type=message_type,
        path=str(template_path),
    )
    
    return template_path.read_text(encoding="utf-8")


def render_template(
    template_content: str,
    context: TemplateContext | dict[str, Any],
) -> str:
    """
    Render an email template with context variables.
    
    Supports Jinja2-style {{ variable }} syntax.
    
    Args:
        template_content: Template string with placeholders
        context: Template variables
        
    Returns:
        Rendered template string
    """
    from jinja2 import Template, UndefinedError
    
    config = get_communication_config()
    
    # Convert context to dict if needed
    if isinstance(context, TemplateContext):
        variables = context.to_template_vars()
    else:
        variables = context
    
    log.debug(
        "rendering_template",
        variables=list(variables.keys()),
    )
    
    try:
        if config.template_format == "jinja2":
            template = Template(template_content)
            return template.render(**variables)
        else:
            # Simple f-string style with .format()
            return template_content.format(**variables)
    except (UndefinedError, KeyError) as e:
        log.error(
            "template_render_failed",
            error=str(e),
            available_vars=list(variables.keys()),
        )
        raise ValueError(f"Template render failed: {e}") from e


def render_subject(
    message_type: str,
    context: TemplateContext | dict[str, Any],
) -> str:
    """
    Render email subject for a message type.
    
    Args:
        message_type: Type of message
        context: Template variables
        
    Returns:
        Rendered subject string
    """
    config = get_communication_config()
    
    subject_template = SUBJECT_TEMPLATES.get(
        message_type,
        "Opportunity in {market}"
    )
    
    # Convert context to dict if needed
    if isinstance(context, TemplateContext):
        variables = context.to_template_vars()
    else:
        variables = context
    
    # Provide defaults for missing values
    defaults = {
        "campaign_type": "Work Opportunity",
        "market": "your area",
    }
    variables = {**defaults, **variables}
    
    subject = subject_template.format(**variables)
    
    # Apply prefix if configured
    if config.default_subject_prefix:
        subject = f"{config.default_subject_prefix}{subject}"
    
    return subject


def draft_email(
    campaign_id: str,
    provider_id: str,
    provider_email: str,
    provider_name: str,
    provider_market: str,
    message_type: str,
    template_data: dict[str, Any] | None = None,
    custom_message: str | None = None,
) -> EmailDraft:
    """
    Draft an email for a provider.
    
    Loads the template, renders it with context, and prepares
    the email for sending.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        provider_email: Provider's email address
        provider_name: Provider's display name
        provider_market: Target market
        message_type: Type of message to send
        template_data: Additional template variables
        custom_message: Custom message to use instead of template
        
    Returns:
        EmailDraft ready for sending
    """
    log.info(
        "drafting_email",
        campaign_id=campaign_id,
        provider_id=provider_id,
        message_type=message_type,
    )
    
    # Build context for template rendering
    context = TemplateContext(
        provider_name=provider_name,
        provider_email=provider_email,
        provider_market=provider_market,
        provider_id=provider_id,
        campaign_id=campaign_id,
        **(template_data or {}),
    )
    
    # Use custom message or render template
    if custom_message:
        body_text = custom_message
        template_name = None
    else:
        try:
            template_content = load_template(message_type)
            body_text = render_template(template_content, context)
            template_name = TEMPLATE_FILES.get(message_type)
        except FileNotFoundError:
            # Fallback to generic message
            log.warning(
                "using_fallback_template",
                message_type=message_type,
            )
            body_text = _get_fallback_message(context, message_type)
            template_name = "fallback"
    
    # Render subject
    subject = render_subject(message_type, context)
    
    # Encode Reply-To address
    reply_to = encode_reply_to(campaign_id, provider_id)
    
    draft = EmailDraft(
        subject=subject,
        body_text=body_text,
        to_address=provider_email,
        reply_to=reply_to,
        campaign_id=campaign_id,
        provider_id=provider_id,
        message_type=message_type,
        template_name=template_name,
    )
    
    log.info(
        "email_drafted",
        campaign_id=campaign_id,
        provider_id=provider_id,
        subject=subject[:50],
        template=template_name,
    )
    
    return draft


def send_provider_email(draft: EmailDraft) -> EmailResult:
    """
    Send a drafted email to a provider via SES.
    
    Args:
        draft: EmailDraft to send
        
    Returns:
        EmailResult with success/failure status
    """
    log.info(
        "sending_provider_email",
        campaign_id=draft.campaign_id,
        provider_id=draft.provider_id,
        to=draft.to_address,
    )
    
    try:
        message_id = send_ses_email(
            to_address=draft.to_address,
            subject=draft.subject,
            body_text=draft.body_text,
            body_html=draft.body_html,
            reply_to=draft.reply_to,
        )
        
        result = EmailResult.success_result(
            message_id=message_id,
            campaign_id=draft.campaign_id,
            provider_id=draft.provider_id,
            message_type=draft.message_type,
            recipient=draft.to_address,
        )
        
        log.info(
            "email_sent_successfully",
            campaign_id=draft.campaign_id,
            provider_id=draft.provider_id,
            message_id=message_id,
        )
        
        return result
    
    except (SESError, InvalidEmailFormatError) as e:
        log.error(
            "email_send_failed",
            campaign_id=draft.campaign_id,
            provider_id=draft.provider_id,
            error=str(e),
        )
        
        error_code = getattr(e, "error_code", None)
        
        return EmailResult.failure_result(
            campaign_id=draft.campaign_id,
            provider_id=draft.provider_id,
            message_type=draft.message_type,
            recipient=draft.to_address,
            error_message=str(e),
            error_code=error_code,
        )


def _get_fallback_message(
    context: TemplateContext,
    message_type: str,
) -> str:
    """
    Generate a fallback message when template is not available.
    
    Args:
        context: Template context
        message_type: Type of message
        
    Returns:
        Fallback message text
    """
    provider_name = context.provider_name or "Provider"
    market = context.provider_market or "your area"
    campaign_type = context.campaign_type or "work opportunity"
    
    if message_type == "initial_outreach":
        return f"""Hi {provider_name},

We have a {campaign_type} opportunity in {market} and believe you would be a great fit.

We're looking for qualified technicians to join our network. If you're interested, please reply to this email with your availability.

Best regards,
The Recruitment Team
"""
    elif message_type == "follow_up":
        return f"""Hi {provider_name},

We wanted to follow up on our previous email about the {campaign_type} opportunity in {market}.

We're still looking for qualified technicians and would love to hear from you. Please reply if you're interested.

Best regards,
The Recruitment Team
"""
    elif message_type == "missing_document":
        missing = context.missing_documents or ["required documents"]
        docs_str = ", ".join(missing) if isinstance(missing, list) else missing
        return f"""Hi {provider_name},

Thank you for your interest in the {campaign_type} opportunity.

To complete your application, we need the following document(s): {docs_str}

Please reply to this email with the attached document(s).

Best regards,
The Recruitment Team
"""
    elif message_type == "qualified_confirmation":
        return f"""Hi {provider_name},

Congratulations! You've been qualified for the {campaign_type} opportunity in {market}.

We'll be in touch with next steps soon.

Best regards,
The Recruitment Team
"""
    elif message_type == "rejection":
        return f"""Hi {provider_name},

Thank you for your interest in the {campaign_type} opportunity.

Unfortunately, we're unable to move forward with your application at this time.

We appreciate your time and wish you the best in your future endeavors.

Best regards,
The Recruitment Team
"""
    else:
        return f"""Hi {provider_name},

Thank you for your interest in working with us.

If you have any questions, please reply to this email.

Best regards,
The Recruitment Team
"""
