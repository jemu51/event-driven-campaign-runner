"""
Communication Agent

Handles SendMessageRequested events and sends personalized emails to providers.

This agent:
1. Receives SendMessageRequested events
2. Loads provider state from DynamoDB
3. Drafts personalized email using templates
4. Sends email via SES with Reply-To encoding
5. Updates provider state (WAITING_RESPONSE)
6. Exits immediately

Following agent principles:
- No waiting or loops
- State persisted to DynamoDB before exit
- Events are the only communication mechanism
"""

from agents.communication.agent import (
    CommunicationError,
    handle_send_message_requested,
)
from agents.communication.config import (
    CommunicationConfig,
    get_communication_config,
)
from agents.communication.models import (
    EmailDraft,
    EmailResult,
    TemplateContext,
)
from agents.communication.prompts import (
    COMMUNICATION_AGENT_SYSTEM_PROMPT,
    get_system_prompt,
)
from agents.communication.tools import (
    draft_email,
    load_template,
    render_template,
    send_provider_email,
)

__all__ = [
    # Agent
    "handle_send_message_requested",
    "CommunicationError",
    # Config
    "CommunicationConfig",
    "get_communication_config",
    # Models
    "EmailDraft",
    "EmailResult",
    "TemplateContext",
    # Prompts
    "COMMUNICATION_AGENT_SYSTEM_PROMPT",
    "get_system_prompt",
    # Tools
    "draft_email",
    "load_template",
    "render_template",
    "send_provider_email",
]
