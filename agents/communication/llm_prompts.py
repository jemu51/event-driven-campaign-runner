"""
LLM Prompts for Communication Agent

System prompts and user prompt builders for LLM-powered email generation.
"""


EMAIL_GENERATION_SYSTEM_PROMPT = """You are an AI assistant helping draft professional recruitment emails for a provider marketplace.

YOUR ROLE:
Draft personalized outreach emails to service providers (technicians, contractors) about work opportunities.

RULES:
1. Personalize content for the provider based on their market and previous interactions
2. Corporate providers: Use formal tone with professional greetings
3. Independent contractors: Use professional but warm/friendly tone
4. Always include "Please reply to this email" or similar instruction
5. When requesting documents, always include "Please attach files under 30MB"
6. Keep emails concise but complete (150-300 words ideal)
7. Include a clear call-to-action specific to the message type
8. Reference the specific campaign/opportunity and market location
9. Never include fictional contact numbers or addresses
10. Sign off appropriately based on message type

MESSAGE TYPES AND EXPECTATIONS:
- initial_outreach: Introduce the opportunity, highlight key requirements, ask for interest
- follow_up: Remind about opportunity, reference previous contact, re-engage
- missing_document: Request specific documents, explain why needed
- clarification: Ask for more information, reference what's unclear
- qualified_confirmation: Congratulate, confirm qualification, outline next steps
- rejection: Thank for interest, explain reason professionally, leave door open

TONE GUIDELINES:
- formal: "Dear [Name]", "We are pleased to...", "Best regards,"
- professional: "Hi [Name]", "We wanted to reach out...", "Thanks,"
- friendly: "Hi [Name]!", "Great news!", "Looking forward to hearing from you!"

OUTPUT FORMAT:
You must output valid JSON matching the required schema exactly. No markdown, no extra text."""


def build_email_generation_prompt(
    message_type: str,
    provider_name: str,
    provider_market: str,
    provider_type: str,
    template_data: dict,
    conversation_history: str,
) -> str:
    """
    Build the user prompt for email generation.
    
    Args:
        message_type: Type of message (initial_outreach, follow_up, etc.)
        provider_name: Provider's display name
        provider_market: Target market (e.g., Atlanta, Chicago)
        provider_type: Provider type (corporate, independent_contractor)
        template_data: Additional context data for the email
        conversation_history: Formatted conversation history string
        
    Returns:
        Complete user prompt for LLM
    """
    # Format template data for the prompt
    template_context = "\n".join(
        f"- {key}: {value}" 
        for key, value in template_data.items() 
        if value is not None
    ) or "No additional context provided."
    
    # Determine recommended tone
    tone = "formal" if provider_type == "corporate" else "professional"
    
    prompt = f"""Generate a {message_type} email for a recruitment campaign.

RECIPIENT INFORMATION:
- Name: {provider_name}
- Market: {provider_market}
- Provider Type: {provider_type}
- Recommended Tone: {tone}

CAMPAIGN/TEMPLATE CONTEXT:
{template_context}

CONVERSATION HISTORY:
{conversation_history}

REQUIREMENTS:
1. Generate a compelling subject line (max 200 chars)
2. Write the email body in plain text format
3. Use the recommended tone ({tone})
4. Include a clear call-to-action appropriate for {message_type}
5. Reference previous conversation if history exists
6. For document requests, include "Reply to this email with attachments under 30MB"
7. Sign the email as "The Recruitment Team"

Generate the email now. Output only valid JSON matching the schema."""

    return prompt


def build_reply_email_prompt(
    provider_name: str,
    provider_market: str,
    provider_type: str,
    reply_reason: str,
    context: dict,
    conversation_history: str,
) -> str:
    """
    Build prompt for generating a reply email.
    
    Used by Screening Agent to request replies to provider emails.
    
    Args:
        provider_name: Provider's display name
        provider_market: Target market
        provider_type: Provider type (corporate, independent_contractor)
        reply_reason: Reason for reply (missing_attachment, invalid_document, etc.)
        context: Additional context (missing_items, questions, etc.)
        conversation_history: Formatted conversation history
        
    Returns:
        User prompt for reply email generation
    """
    # Determine recommended tone
    tone = "formal" if provider_type == "corporate" else "professional"
    
    # Format context
    context_str = "\n".join(
        f"- {key}: {value}" 
        for key, value in context.items() 
        if value
    ) or "No additional context."
    
    # Map reply reason to action
    action_map = {
        "missing_attachment": "Request the provider to attach missing documents",
        "invalid_document": "Explain the document issue and request a corrected version",
        "incomplete_response": "Ask for more details about their equipment/availability",
        "clarification_needed": "Ask specific clarifying questions",
    }
    action = action_map.get(reply_reason, "Follow up with the provider")
    
    prompt = f"""Generate a reply email responding to a provider's previous message.

REPLY CONTEXT:
- Reason for reply: {reply_reason}
- Action needed: {action}

RECIPIENT INFORMATION:
- Name: {provider_name}
- Market: {provider_market}
- Provider Type: {provider_type}
- Recommended Tone: {tone}

ADDITIONAL CONTEXT:
{context_str}

CONVERSATION HISTORY:
{conversation_history}

REQUIREMENTS:
1. Generate a clear subject line (can use "Re: <previous subject>" format)
2. Reference their previous message/response
3. Clearly explain what is needed from them
4. Be polite and maintain positive relationship
5. Use the recommended tone ({tone})
6. For document requests, mention file size limit (30MB)
7. Include clear call-to-action

Generate the reply email now. Output only valid JSON matching the schema."""

    return prompt


# Message type specific guidance for template fallback
MESSAGE_TYPE_SUBJECTS = {
    "initial_outreach": "Opportunity: {campaign_type} technicians needed in {market}",
    "follow_up": "Following up: {campaign_type} opportunity in {market}",
    "missing_document": "Action Required: Documentation needed for {campaign_type}",
    "clarification": "Question about your {campaign_type} application",
    "qualified_confirmation": "Great news! You're approved for {campaign_type}",
    "rejection": "Update on your {campaign_type} application",
}


MESSAGE_TYPE_CTAs = {
    "initial_outreach": "Please reply to this email if you're interested in this opportunity.",
    "follow_up": "Please reply to let us know if you're still interested.",
    "missing_document": "Please reply to this email with the required documents attached (files under 30MB).",
    "clarification": "Please reply with your answers to help us move forward.",
    "qualified_confirmation": "We'll be in touch with assignment details soon.",
    "rejection": "Thank you for your interest. Please feel free to apply for future opportunities.",
}
