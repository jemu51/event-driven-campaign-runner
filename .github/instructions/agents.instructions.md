# Agent Development Instructions

## Purpose

This file provides specific guidance for developing **Strands AI agents** that run on AWS Bedrock AgentCore. These agents are the core of our event-driven recruitment automation system.

## Agent Architecture Principles

### 1. Agents Are Ephemeral
- Agents wake up on events, perform actions, and **exit immediately**
- No long-running processes, no event loops, no waiting
- Compute cost is zero when agents aren't processing

### 2. Agents Are Stateless
- All persistent state must live in **DynamoDB**
- Agent memory is cleared between invocations
- Each invocation starts fresh with event payload

### 3. Agents Communicate Via Events
- Agents **never** call each other directly
- All inter-agent communication happens through **EventBridge**
- Events are the only coordination mechanism

### 4. Agents Have Single Responsibility
- Each agent does **one thing well**
- Campaign Planner = planning only
- Communication Agent = email only
- Screening Agent = evaluation only

## Agent File Structure

```
agents/<agent_name>/
├── __init__.py
├── agent.py              # Main agent logic
├── tools.py              # Agent tool definitions
├── llm_tools.py          # LLM-powered tool definitions (optional)
├── llm_prompts.py        # LLM system/user prompts (optional)
├── prompts.py            # System prompts
├── models.py             # Pydantic models for events/state
├── config.py             # Agent configuration
└── tests/
    ├── test_agent.py
    ├── test_tools.py
    └── test_llm_tools.py  # LLM tool tests (optional)
```

## Agent Implementation Template

```python
# agents/<agent_name>/agent.py

from strands import Agent, tool
from .models import InputEvent, OutputEvent
from .tools import update_provider_state, send_event
import structlog

log = structlog.get_logger()

agent = Agent(
    name="<agent_name>",
    instructions="""
    You are the <Agent Name> agent in a recruitment automation system.
    
    YOUR ROLE:
    - [Specific responsibility]
    
    YOUR CONSTRAINTS:
    - Never wait or loop
    - Always update DynamoDB before exiting
    - Only emit events, never call other agents
    - Validate all inputs against schemas
    
    EXECUTION FLOW:
    1. Parse incoming event
    2. Load current state from DynamoDB
    3. Perform your specific logic
    4. Update state in DynamoDB
    5. Emit next event(s)
    6. Exit
    """,
    tools=[update_provider_state, send_event, ...]
)

@agent.on_event("EventTypeName")
async def handle_event(event: InputEvent):
    """
    Handle <EventTypeName> event.
    
    This function is called when EventBridge delivers the event.
    Must complete quickly and exit cleanly.
    """
    log.info(
        "event_received",
        event_type=event.detail_type,
        campaign_id=event.campaign_id
    )
    
    try:
        # 1. Validate input
        event.validate()
        
        # 2. Load state
        state = await load_provider_state(
            event.campaign_id,
            event.provider_id
        )
        
        # 3. Business logic
        result = await process_logic(event, state)
        
        # 4. Persist state
        await update_provider_state(
            campaign_id=event.campaign_id,
            provider_id=event.provider_id,
            new_status=result.new_status,
            expected_next_event=result.expected_next_event
        )
        
        # 5. Emit next event
        await send_event(
            detail_type=result.next_event_type,
            detail=result.next_event_payload
        )
        
        log.info("event_processed_successfully")
        
    except Exception as e:
        log.error(
            "event_processing_failed",
            error=str(e),
            event_id=event.id
        )
        # DLQ will capture this for replay
        raise
```

## Tool Development Guidelines

### Tool Definition Pattern

```python
# agents/<agent_name>/tools.py

from strands import tool
from typing import Literal
import boto3

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('RecruitmentSessions')

@tool
def update_provider_state(
    campaign_id: str,
    provider_id: str,
    new_status: Literal[
        "INVITED",
        "WAITING_RESPONSE",
        "WAITING_DOCUMENT",
        "DOCUMENT_PROCESSING",
        "UNDER_REVIEW",
        "QUALIFIED",
        "REJECTED",
        "ESCALATED"
    ],
    expected_next_event: str,
    email_thread_id: str | None = None,
    artifacts: dict[str, str] | None = None
) -> dict:
    """
    Update provider state in DynamoDB.
    
    This is the PRIMARY state persistence mechanism.
    All agents must use this to record state changes.
    
    Args:
        campaign_id: Campaign identifier
        provider_id: Provider identifier
        new_status: New provider status (from state machine)
        expected_next_event: Event type that will wake agent next
        email_thread_id: Optional SES thread ID
        artifacts: Optional dict of filename -> S3 path
        
    Returns:
        Updated DynamoDB item
        
    Raises:
        ConditionalCheckFailedException: If concurrent update detected
        ProviderNotFoundError: If provider doesn't exist
    """
    import time
    
    pk = f"SESSION#{campaign_id}"
    sk = f"PROVIDER#{provider_id}"
    gsi1_pk = f"{new_status}#{expected_next_event}"
    
    update_expr = (
        "SET #status = :status, "
        "expected_next_event = :event, "
        "last_contacted_at = :timestamp, "
        "GSI1PK = :gsi1pk"
    )
    expr_values = {
        ":status": new_status,
        ":event": expected_next_event,
        ":timestamp": int(time.time()),
        ":gsi1pk": gsi1_pk
    }
    
    if email_thread_id:
        update_expr += ", email_thread_id = :thread_id"
        expr_values[":thread_id"] = email_thread_id
    
    if artifacts:
        update_expr += ", artifacts = :artifacts"
        expr_values[":artifacts"] = artifacts
    
    response = table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression=update_expr,
        ExpressionAttributeNames={
            "#status": "status"  # 'status' is a reserved word
        },
        ExpressionAttributeValues=expr_values,
        ConditionExpression="attribute_exists(PK)",
        ReturnValues="ALL_NEW"
    )
    
    return response["Attributes"]


@tool
def send_event(
    detail_type: str,
    detail: dict,
    source: str = "recruitment.agents"
) -> dict:
    """
    Emit event to EventBridge.
    
    This is how agents trigger other agents.
    
    Args:
        detail_type: Event type (e.g., "SendMessageRequested")
        detail: Event payload
        source: Event source namespace
        
    Returns:
        EventBridge response
    """
    import json
    import boto3
    
    eventbridge = boto3.client('events')
    
    response = eventbridge.put_events(
        Entries=[{
            'Source': source,
            'DetailType': detail_type,
            'Detail': json.dumps(detail),
            'EventBusName': 'recruitment-events'
        }]
    )
    
    if response['FailedEntryCount'] > 0:
        raise EventPublishError(
            f"Failed to publish event: {response['Entries'][0]['ErrorMessage']}"
        )
    
    return response
```

### Tool Best Practices

1. **Type hints are mandatory** - Include return types and param types
2. **Docstrings required** - Include Args, Returns, Raises sections
3. **Validation first** - Check inputs before side effects
4. **Idempotency** - Same inputs should produce same outputs
5. **Error handling** - Raise specific exceptions with context

## State Machine Validation

### Always Validate State Transitions

```python
# agents/shared/state_machine.py

from typing import Literal
from enum import Enum

class ProviderStatus(str, Enum):
    INVITED = "INVITED"
    WAITING_RESPONSE = "WAITING_RESPONSE"
    WAITING_DOCUMENT = "WAITING_DOCUMENT"
    DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
    UNDER_REVIEW = "UNDER_REVIEW"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"

# Valid transitions map
VALID_TRANSITIONS = {
    ProviderStatus.INVITED: {
        ProviderStatus.WAITING_RESPONSE
    },
    ProviderStatus.WAITING_RESPONSE: {
        ProviderStatus.WAITING_DOCUMENT,
        ProviderStatus.REJECTED,
        ProviderStatus.QUALIFIED
    },
    ProviderStatus.WAITING_DOCUMENT: {
        ProviderStatus.DOCUMENT_PROCESSING,
        ProviderStatus.REJECTED
    },
    ProviderStatus.DOCUMENT_PROCESSING: {
        ProviderStatus.UNDER_REVIEW,
        ProviderStatus.WAITING_DOCUMENT,
        ProviderStatus.REJECTED
    },
    ProviderStatus.UNDER_REVIEW: {
        ProviderStatus.QUALIFIED,
        ProviderStatus.REJECTED,
        ProviderStatus.ESCALATED
    },
    # Terminal states have no transitions
    ProviderStatus.QUALIFIED: set(),
    ProviderStatus.REJECTED: set(),
    ProviderStatus.ESCALATED: set()
}

def validate_transition(
    current: ProviderStatus,
    next: ProviderStatus
) -> None:
    """
    Validate state transition is allowed.
    
    Raises:
        InvalidStateTransitionError: If transition not allowed
    """
    if next not in VALID_TRANSITIONS[current]:
        raise InvalidStateTransitionError(
            f"Cannot transition from {current} to {next}. "
            f"Valid transitions: {VALID_TRANSITIONS[current]}"
        )
```

## Event Schema Validation

### Use Pydantic Models

```python
# agents/<agent_name>/models.py

from pydantic import BaseModel, Field, field_validator
from datetime import datetime

class ProviderResponseReceived(BaseModel):
    """
    Event emitted when provider replies to outreach email.
    
    This event wakes the Screening Agent.
    """
    campaign_id: str = Field(..., pattern=r'^[a-zA-Z0-9-]+$')
    provider_id: str = Field(..., pattern=r'^[a-zA-Z0-9-]+$')
    body: str = Field(..., min_length=1)
    attachments: list[str] = Field(default_factory=list)
    received_at: int = Field(..., ge=0)
    email_thread_id: str
    
    @field_validator('attachments')
    @classmethod
    def validate_s3_paths(cls, v: list[str]) -> list[str]:
        for path in v:
            if not path.startswith('s3://'):
                raise ValueError(f"Invalid S3 path: {path}")
        return v

    class Config:
        frozen = True  # Immutable
```

## LLM Integration Patterns

### Structured Output with Pydantic

All LLM calls must return structured output via Pydantic models:

```python
from agents.shared.llm import BedrockLLMClient
from agents.shared.llm.schemas import EmailGenerationOutput

def generate_email_with_llm(
    campaign_id: str,
    provider_name: str,
    message_type: str,
    conversation_history: list,
) -> EmailGenerationOutput:
    """
    Generate personalized email using LLM.
    
    Returns structured output - never raw text.
    """
    client = BedrockLLMClient()
    return client.invoke_structured(
        prompt=build_prompt(...),
        output_schema=EmailGenerationOutput,
        system_prompt=EMAIL_GENERATION_SYSTEM_PROMPT,
    )
```

### Feature Flag Pattern

All LLM functionality must be toggleable:

```python
from agents.shared.llm.config import LLMSettings

settings = LLMSettings()

# LLM-enabled path with template fallback
if settings.llm_enabled:
    result = generate_email_with_llm(...)
    draft = create_draft_from_llm_output(result)
else:
    # Existing template-based logic (always available)
    draft = draft_email_from_template(...)
```

### LLM Tool Best Practices

1. **Always use structured output** - Never parse raw LLM text
2. **Include feature flags** - Allow disabling LLM for testing
3. **Provide fallback** - Template/rule-based fallback when LLM disabled
4. **Log LLM decisions** - Include reasoning in structured output
5. **Validate LLM output** - Pydantic validates automatically

### Common LLM Output Schemas

Defined in `agents/shared/llm/schemas.py`:

- `EmailGenerationOutput` - Email subject, body, tone, personalization
- `ResponseClassificationOutput` - Intent, confidence, sentiment
- `EquipmentExtractionOutput` - Equipment confirmed/denied, certifications
- `InsuranceDocumentOutput` - Policy details, validity, expiry
- `ScreeningDecisionOutput` - Decision, reasoning, next action

---

## Email Thread History

### Purpose

Store email conversation history for:
- LLM context (personalization, continuity)
- Chat-like thread display
- Debugging and audit trail

### DynamoDB Pattern

```python
# Thread PK/SK pattern (same table as RecruitmentSessions)
PK = "THREAD#<campaign_id>#<market_id>#<provider_id>"
SK = "MSG#<sequence_number>"  # 00001, 00002, etc.
```

### Email Thread Tools

```python
from agents.shared.tools.email_thread import (
    create_thread_id,
    save_email_to_thread,
    load_thread_history,
    format_thread_for_context,
    EmailMessage,
    EmailDirection,
)

# Create thread ID
thread_id = create_thread_id(campaign_id, market_id, provider_id)

# Save outbound email
save_email_to_thread(EmailMessage(
    thread_id=thread_id,
    sequence_number=get_next_sequence_number(thread_id),
    direction=EmailDirection.OUTBOUND,
    timestamp=int(time.time()),
    subject="Subject",
    body_text="Email body",
    message_id="ses-message-id",
    email_from="from@example.com",
    email_to="to@example.com",
    message_type="initial_outreach",
))

# Load history for LLM context
messages = load_thread_history(thread_id, limit=5)
context = format_thread_for_context(messages)
```

### Thread History Rules

1. **Save all emails** - Both inbound and outbound
2. **Sequence numbers** - Atomic increment per thread
3. **Limit for LLM** - Load last 5 messages for context
4. **Format for LLM** - Use `format_thread_for_context()` helper

---

## Testing Agents

### Unit Test Pattern

```python
# agents/<agent_name>/tests/test_agent.py

import pytest
from moto import mock_dynamodb, mock_events
from agents.screening.agent import handle_provider_response
from agents.screening.models import ProviderResponseReceived

@pytest.fixture
def dynamodb_table():
    """Setup mock DynamoDB table"""
    with mock_dynamodb():
        import boto3
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.create_table(
            TableName='RecruitmentSessions',
            KeySchema=[
                {'AttributeName': 'PK', 'KeyType': 'HASH'},
                {'AttributeName': 'SK', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'PK', 'AttributeType': 'S'},
                {'AttributeName': 'SK', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        yield table

@pytest.fixture
def provider_state(dynamodb_table):
    """Create test provider state"""
    dynamodb_table.put_item(Item={
        'PK': 'SESSION#campaign-123',
        'SK': 'PROVIDER#provider-456',
        'status': 'WAITING_RESPONSE',
        'expected_next_event': 'PROVIDER_RESPONSE',
        'last_contacted_at': 1640000000
    })

@mock_events
async def test_handle_provider_response_with_attachment(
    dynamodb_table,
    provider_state
):
    """Test screening agent handles response with document"""
    event = ProviderResponseReceived(
        campaign_id='campaign-123',
        provider_id='provider-456',
        body='Here is my certificate',
        attachments=['s3://bucket/cert.pdf'],
        received_at=1640000100,
        email_thread_id='thread-789'
    )
    
    result = await handle_provider_response(event)
    
    # Verify state updated
    item = dynamodb_table.get_item(
        Key={
            'PK': 'SESSION#campaign-123',
            'SK': 'PROVIDER#provider-456'
        }
    )['Item']
    
    assert item['status'] == 'DOCUMENT_PROCESSING'
    assert item['expected_next_event'] == 'DOCUMENT_PROCESSED'
    assert 's3://bucket/cert.pdf' in item['artifacts'].values()
```

## Agent-Specific Guidance

### Campaign Planner Agent

**Responsibility:** Orchestrate new campaigns

**Key Logic:**
- Parse buyer requirements
- Query available providers
- Create provider records
- Emit SendMessageRequested for each provider

**Critical:** Must batch EventBridge calls (max 10 events per PutEvents)

### Communication Agent

**Responsibility:** Send emails only

**Key Logic:**
- Draft personalized email using LLM
- Send via SES
- Track thread ID
- Update state to WAITING_RESPONSE

**Critical:** Must handle SES rate limits (14 emails/sec max)

### Screening Agent

**Responsibility:** Evaluate provider responses

**Key Logic:**
- Classify response intent
- Check for attachments
- Extract info from text
- Trigger Textract if needed
- Decide next state

**Critical:** Complex state machine - follow VALID_TRANSITIONS strictly

## Common Mistakes to Avoid

### ❌ Storing State in Memory

```python
# BAD - lost when agent exits
class ScreeningAgent:
    def __init__(self):
        self.provider_responses = {}  # ❌ Gone forever
```

### ✅ Storing State in DynamoDB

```python
# GOOD - persists across invocations
await update_provider_state(
    campaign_id=campaign_id,
    provider_id=provider_id,
    new_status="UNDER_REVIEW"
)
```

### ❌ Calling Other Agents

```python
# BAD - tight coupling
communication_agent.send_email(provider)  # ❌
```

### ✅ Emitting Events

```python
# GOOD - loose coupling
await send_event(
    detail_type="SendMessageRequested",
    detail={
        "campaign_id": campaign_id,
        "provider_id": provider_id,
        "email_body": email_body
    }
)
```

### ❌ Waiting in Agent

```python
# BAD - blocks execution
while not document_processed:  # ❌
    await asyncio.sleep(60)
    check_status()
```

### ❌ LLM Without Feature Flag

```python
# BAD - no way to disable LLM for testing
result = llm_client.invoke(prompt)  # ❌
email = create_email(result)
```

### ✅ LLM With Feature Flag

```python
# GOOD - toggleable with fallback
if settings.llm_enabled:
    result = llm_client.invoke_structured(prompt, schema)
    email = create_email_from_llm(result)
else:
    email = create_email_from_template(data)
```

### ❌ Parsing Raw LLM Text

```python
# BAD - fragile parsing
response = llm.invoke("Generate email")
subject = response.split("Subject:")[1].split("\n")[0]  # ❌
```

### ✅ Structured LLM Output

```python
# GOOD - Pydantic-validated output
result = llm.invoke_structured(
    prompt="Generate email",
    output_schema=EmailGenerationOutput
)
subject = result.subject  # Type-safe, validated
```

### ✅ Exiting and Resuming

```python
# GOOD - exit and wait for event
await update_provider_state(
    new_status="DOCUMENT_PROCESSING",
    expected_next_event="DOCUMENT_PROCESSED"
)
# Agent exits here
# Textract completion triggers DocumentProcessed event
# Agent wakes up and continues
```

## Deployment Checklist

Before deploying an agent:

- [ ] All tools have type hints and docstrings
- [ ] State transitions validated against state machine
- [ ] Events use Pydantic models from contracts/
- [ ] Unit tests cover happy path and error cases
- [ ] Integration test verifies end-to-end flow
- [ ] No time.sleep(), while loops, or polling
- [ ] All DynamoDB writes are conditional
- [ ] Structured logging used throughout
- [ ] Error handling raises specific exceptions
- [ ] Agent exits cleanly after emitting events

## Resources

- [Strands AI Agent Guide](https://docs.strands.ai/agents)
- [AWS Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/agentcore)
- [Event Contracts](../contracts/events.json)
- [State Machine Definition](../contracts/state_machine.json)
