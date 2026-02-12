"""
Email Tools

Idempotent tools for SES email operations and Reply-To encoding/decoding.
Configuration follows contracts/email_config.json.
"""

import re
from dataclasses import dataclass
from email.headerregistry import Address

import boto3
from botocore.exceptions import ClientError
import structlog

from agents.shared.config import get_settings
from agents.shared.exceptions import InvalidEmailFormatError, SESError

log = structlog.get_logger()

# Reply-To pattern from contracts/email_config.json
REPLY_TO_PATTERN = re.compile(
    r"^campaign\+([a-zA-Z0-9-]+)_provider\+([a-zA-Z0-9-]+)@(.+)$"
)


@dataclass(frozen=True)
class DecodedReplyTo:
    """Decoded components from a Reply-To address."""
    
    campaign_id: str
    provider_id: str
    domain: str


def _get_client():
    """Get SES client."""
    settings = get_settings()
    return boto3.client("ses", **settings.ses_config)


def encode_reply_to(
    campaign_id: str,
    provider_id: str,
    *,
    domain: str | None = None,
) -> str:
    """
    Encode campaign and provider IDs into a Reply-To address.
    
    Format: campaign+{campaign_id}_provider+{provider_id}@{domain}
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        domain: Override domain (default: from settings)
        
    Returns:
        Encoded Reply-To address
        
    Raises:
        InvalidEmailFormatError: If IDs contain invalid characters
    """
    settings = get_settings()
    email_domain = domain or settings.ses_reply_to_domain
    
    # Validate IDs contain only allowed characters
    id_pattern = re.compile(r"^[a-zA-Z0-9-]+$")
    if not id_pattern.match(campaign_id):
        raise InvalidEmailFormatError(
            email_address=campaign_id,
            expected_pattern="^[a-zA-Z0-9-]+$",
        )
    if not id_pattern.match(provider_id):
        raise InvalidEmailFormatError(
            email_address=provider_id,
            expected_pattern="^[a-zA-Z0-9-]+$",
        )
    
    reply_to = f"campaign+{campaign_id}_provider+{provider_id}@{email_domain}"
    
    log.debug(
        "encoded_reply_to",
        campaign_id=campaign_id,
        provider_id=provider_id,
        reply_to=reply_to,
    )
    
    return reply_to


def decode_reply_to(reply_to_address: str) -> DecodedReplyTo:
    """
    Decode campaign and provider IDs from a Reply-To address.
    
    Args:
        reply_to_address: Encoded Reply-To address
        
    Returns:
        DecodedReplyTo with campaign_id, provider_id, domain
        
    Raises:
        InvalidEmailFormatError: If address doesn't match expected format
    """
    match = REPLY_TO_PATTERN.match(reply_to_address)
    
    if not match:
        log.warning(
            "invalid_reply_to_format",
            reply_to=reply_to_address,
        )
        raise InvalidEmailFormatError(
            email_address=reply_to_address,
            expected_pattern=REPLY_TO_PATTERN.pattern,
        )
    
    decoded = DecodedReplyTo(
        campaign_id=match.group(1),
        provider_id=match.group(2),
        domain=match.group(3),
    )
    
    log.debug(
        "decoded_reply_to",
        campaign_id=decoded.campaign_id,
        provider_id=decoded.provider_id,
        domain=decoded.domain,
    )
    
    return decoded


def send_ses_email(
    to_address: str,
    subject: str,
    body_text: str,
    *,
    body_html: str | None = None,
    reply_to: str | None = None,
    from_address: str | None = None,
    from_name: str | None = None,
    configuration_set: str | None = None,
) -> str:
    """
    Send an email via SES.
    
    Args:
        to_address: Recipient email address
        subject: Email subject
        body_text: Plain text body
        body_html: Optional HTML body
        reply_to: Reply-To address (for provider identification)
        from_address: Override from address
        from_name: Override from display name
        configuration_set: Override configuration set
        
    Returns:
        SES message ID
        
    Raises:
        SESError: If send fails
    """
    settings = get_settings()
    client = _get_client()
    
    sender = from_address or settings.ses_from_address
    sender_name = from_name or settings.ses_from_name
    config_set = configuration_set or settings.ses_configuration_set
    
    # Format sender with display name
    if sender_name:
        source = f"{sender_name} <{sender}>"
    else:
        source = sender
    
    message_body = {"Text": {"Data": body_text, "Charset": "UTF-8"}}
    if body_html:
        message_body["Html"] = {"Data": body_html, "Charset": "UTF-8"}
    
    send_params = {
        "Source": source,
        "Destination": {"ToAddresses": [to_address]},
        "Message": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": message_body,
        },
    }
    
    if reply_to:
        send_params["ReplyToAddresses"] = [reply_to]
    
    if config_set:
        send_params["ConfigurationSetName"] = config_set
    
    log.info(
        "sending_ses_email",
        to=to_address,
        subject=subject[:50],
        reply_to=reply_to,
    )
    
    try:
        response = client.send_email(**send_params)
        message_id = response["MessageId"]
        
        log.info(
            "ses_email_sent",
            message_id=message_id,
            to=to_address,
        )
        
        return message_id
    
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        
        log.error(
            "ses_send_failed",
            to=to_address,
            error_code=error_code,
            error_message=error_message,
        )
        
        raise SESError(
            operation="send",
            recipient=to_address,
            error_message=f"{error_code}: {error_message}",
        ) from e


def send_templated_email(
    to_address: str,
    template_name: str,
    template_data: dict,
    *,
    reply_to: str | None = None,
    from_address: str | None = None,
    configuration_set: str | None = None,
) -> str:
    """
    Send a templated email via SES.
    
    Uses SES templates for consistent formatting.
    
    Args:
        to_address: Recipient email address
        template_name: SES template name
        template_data: Template variables
        reply_to: Reply-To address
        from_address: Override from address
        configuration_set: Override configuration set
        
    Returns:
        SES message ID
        
    Raises:
        SESError: If send fails
    """
    import json
    
    settings = get_settings()
    client = _get_client()
    
    sender = from_address or settings.ses_from_address
    config_set = configuration_set or settings.ses_configuration_set
    
    send_params = {
        "Source": sender,
        "Destination": {"ToAddresses": [to_address]},
        "Template": template_name,
        "TemplateData": json.dumps(template_data),
    }
    
    if reply_to:
        send_params["ReplyToAddresses"] = [reply_to]
    
    if config_set:
        send_params["ConfigurationSetName"] = config_set
    
    log.info(
        "sending_templated_email",
        to=to_address,
        template=template_name,
        reply_to=reply_to,
    )
    
    try:
        response = client.send_templated_email(**send_params)
        message_id = response["MessageId"]
        
        log.info(
            "templated_email_sent",
            message_id=message_id,
            to=to_address,
            template=template_name,
        )
        
        return message_id
    
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        
        log.error(
            "ses_templated_send_failed",
            to=to_address,
            template=template_name,
            error_code=error_code,
            error_message=error_message,
        )
        
        raise SESError(
            operation="send_templated",
            recipient=to_address,
            error_message=f"{error_code}: {error_message}",
        ) from e


def validate_email_address(email: str) -> bool:
    """
    Validate an email address format.
    
    Uses email-validator library for RFC compliance.
    
    Args:
        email: Email address to validate
        
    Returns:
        True if valid
        
    Raises:
        InvalidEmailFormatError: If invalid
    """
    from email_validator import validate_email, EmailNotValidError
    
    try:
        validate_email(email, check_deliverability=False)
        return True
    except EmailNotValidError as e:
        raise InvalidEmailFormatError(
            email_address=email,
            expected_pattern="RFC 5321",
        ) from e
