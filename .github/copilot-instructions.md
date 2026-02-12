# Agent-Driven Recruitment Automation System

## Project Overview

This is an **event-driven, agent-based recruitment automation system** built on AWS Bedrock AgentCore using Strands AI agents. The system automates provider outreach, screening, and decisioning for an online marketplace by replacing staff-driven workflows with autonomous AI agents.

**Core Philosophy:**
- Agents never wait — they think, act, persist state, and exit
- All long-term state lives in DynamoDB, not agent memory
- Events wake agents, not polling or loops
- Email is the UI for providers
- Each agent has a single responsibility

**Demo Scenario:**
The system is designed to support a "Satellite Upgrade" campaign:
- 3 markets (Atlanta, Chicago, Milwaukee)
- 5 providers per market target
- Equipment screening (bucket truck, spectrum analyzer, travel)
- Insurance document upload and verification
- Buyer certification approval flow

See **PHASE 10** in ARCHITECHTURE.md for complete demo scenario details.

## Tech Stack

### Core Technologies
- **Python 3.12+** - Primary language
- **AWS Bedrock AgentCore** - Agent runtime (via Strands AI framework)
- **AWS DynamoDB** - Persistent state store
- **AWS EventBridge** - Event backbone
- **AWS SES** - Email communication
- **AWS SNS** - Inbound email routing
- **AWS Lambda** - Event processors
- **AWS S3** - Document storage
- **AWS Textract** - Document OCR
- **Strands AI SDK** - Agent development framework

### Development Tools
- **pytest** - Testing framework
- **moto** - AWS service mocking
- **boto3** - AWS SDK
- **pydantic** - Data validation
- **python-dotenv** - Environment management

## Project Structure

This is the target scaffold described in ARCHITECHTURE.md and built phase-by-phase.

```
/
├── ARCHITECHTURE.md                      # Source of truth
├── .github/
│   ├── copilot-instructions.md
│   └── instructions/
│       ├── agents.instructions.md
│       └── events.instructions.md
├── contracts/
│   ├── events.json                       # Event schema definitions
│   └── state_machine.json                # Provider state transitions (derived)
├── agents/
│   ├── campaign_planner/
│   ├── communication/
│   ├── screening/
│   └── shared/
│       ├── llm/                          # Bedrock LLM client and schemas
│       ├── models/                       # Shared Pydantic models
│       └── tools/                        # Shared agent tools
├── lambdas/
│   ├── process_inbound_email/
│   ├── send_follow_ups/
│   └── textract_completion/
└── tests/                                # Added in Phase 9
```

## Coding Guidelines

### General Principles
1. **Explicit over implicit** - No magic, clear intent
2. **Type hints everywhere** - Use Python 3.12+ type annotations
3. **Fail fast** - Validate early, raise meaningful exceptions
4. **Immutable by default** - Prefer frozen dataclasses, tuples
5. **No shared mutable state** - Agents are stateless

### Python Style
- Follow **PEP 8** with 88-character line length (Black formatter)
- Use **absolute imports** from project root
- Prefer **pathlib.Path** over string paths
- Use **structural pattern matching** (match/case) for state transitions
- **f-strings** for string formatting, no `.format()` or `%`

### Agent Development Rules
1. **Never use time.sleep() or while loops** - Agents must exit after acting
2. **Never call another agent directly** - Only emit events
3. **Never invent state values** - Use only defined states in `state_machine.json`
4. **Always validate events** - Use Pydantic models from `contracts/`
5. **Tool calls must be idempotent** - Same input = same output

### DynamoDB Patterns
- **PK format:** `SESSION#<campaign_id>`
- **SK format:** `PROVIDER#<provider_id>`
- **GSI1 PK format:** `<status>#<expected_next_event>`
- **Timestamps:** Unix epoch (int), not ISO strings
- **Updates:** Use conditional writes with `expected_version`

### Event Naming
- Use the PascalCase event names from ARCHITECHTURE.md as the EventBridge `detail-type`.
- `source` can be namespaced (e.g., `recruitment.agents.screening`) but is not the contract name.

### Error Handling
```python
# Good - specific, actionable errors
if not provider_record:
    raise ProviderNotFoundError(
        provider_id=provider_id,
        campaign_id=campaign_id
    )

# Bad - generic exceptions
if not provider_record:
    raise Exception("Provider not found")
```

### Testing Requirements
- **Unit tests required** for all agent logic
- **Integration tests required** for event flows
- **No mocking DynamoDB** in integration tests - use local instance
- **Test isolation** - each test creates/tears down its own state
- **Fixtures** for common event payloads in `tests/fixtures/`

## Build & Test Commands (available as phases land)

### Local Development
```bash
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

pip install -e ".[dev]"

# Run tests once test suites exist
pytest -v

# Run a specific agent once implemented
strands run agents/campaign_planner --event-file <event.json>

black .
ruff check --fix .
mypy agents/ lambdas/
```

### AWS Deployment
```bash
# Build agent package
strands build agents/campaign_planner

# Deploy agent to AgentCore
strands deploy agents/campaign_planner --env production

# Tail agent logs
strands logs agents/campaign_planner --follow
```

## Architecture Patterns

### Event Flow Example
```
1. Buyer creates campaign
   → Lambda emits: NewCampaignRequested

2. Campaign Planner Agent:
   - Loads requirements
   - Queries provider database
   - Writes provider records to DynamoDB (status=INVITED)
   - Emits: SendMessageRequested (one per provider)
   - EXITS

3. Communication Agent (per provider):
   - Drafts personalized email
   - Sends via SES
   - Updates DynamoDB (status=WAITING_RESPONSE)
   - EXITS

4. Days later: Provider replies
   → SES → SNS → ProcessInboundEmail Lambda
   → Emits: ProviderResponseReceived

5. Screening Agent:
   - Loads provider state
   - Classifies response
   - Updates state
   - Emits next action event
   - EXITS
```

### State Persistence Pattern
```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class ProviderState:
    campaign_id: str
    provider_id: str
    status: str  # Must be from state_machine.json
    expected_next_event: str
    last_contacted_at: int
    email_thread_id: str | None
    artifacts: dict[str, str]  # filename -> S3 path
    
    def to_dynamodb(self) -> dict:
        """Convert to DynamoDB item"""
        return {
            "PK": f"SESSION#{self.campaign_id}",
            "SK": f"PROVIDER#{self.provider_id}",
            "status": self.status,
            "expected_next_event": self.expected_next_event,
            "last_contacted_at": self.last_contacted_at,
            "email_thread_id": self.email_thread_id,
            "artifacts": self.artifacts,
            "GSI1PK": f"{self.status}#{self.expected_next_event}"
        }
```

### Agent Tool Pattern
```python
from strands import tool

@tool
def update_provider_state(
    campaign_id: str,
    provider_id: str,
    new_status: str,
    expected_next_event: str
) -> dict:
    """Update provider state in DynamoDB"""
    # Load current state
    state = load_provider_state(campaign_id, provider_id)
    
    # Validate state transition
    validate_transition(state.status, new_status)
    
    # Update with conditional write
    updated = dynamodb.update_item(
        Key={"PK": f"SESSION#{campaign_id}", "SK": f"PROVIDER#{provider_id}"},
        UpdateExpression="SET #status = :new_status, ...",
        ConditionExpression="attribute_exists(PK) AND #status = :old_status",
        ...
    )
    
    return updated
```

## Common Pitfalls to Avoid

1. **❌ DON'T: Loop waiting for responses**
   ```python
   # Bad
   while not provider_responded:
       time.sleep(60)
       check_response()
   ```
   **✅ DO: Exit and wait for event**
   ```python
   # Good
   update_state(status="WAITING_RESPONSE", expected_next_event="PROVIDER_RESPONSE")
   # Agent exits here, woken by ProviderResponseReceived event
   ```

2. **❌ DON'T: Store state in agent memory**
   ```python
   # Bad - lost when agent exits
   self.provider_responses = []
   ```
   **✅ DO: Store in DynamoDB**
   ```python
   # Good
   dynamodb.put_item(Item={...})
   ```

3. **❌ DON'T: Call agents directly**
   ```python
   # Bad
   communication_agent.send_email(provider)
   ```
   **✅ DO: Emit events**
   ```python
   # Good
   eventbridge.put_events(Entries=[{
       "DetailType": "SendMessageRequested",
       "Detail": json.dumps({...})
   }])
   ```

4. **❌ DON'T: Use string literals for states**
   ```python
   # Bad
   provider.status = "waiting_for_response"
   ```
   **✅ DO: Use enums from contracts**
   ```python
   # Good
   from contracts.states import ProviderStatus
   provider.status = ProviderStatus.WAITING_RESPONSE
   ```

5. **❌ DON'T: Call LLM without feature flag**
   ```python
   # Bad - can't disable for testing
   email = llm_client.generate_email(prompt)
   ```
   **✅ DO: Use feature flag with fallback**
   ```python
   # Good
   if settings.llm_enabled:
       email = generate_email_with_llm(context)
   else:
       email = draft_email_from_template(data)
   ```

6. **❌ DON'T: Parse raw LLM text**
   ```python
   # Bad - fragile, error-prone
   response = llm.invoke("Generate email")
   subject = response.split("Subject:")[1].strip()
   ```
   **✅ DO: Use structured output**
   ```python
   # Good
   from agents.shared.llm.schemas import EmailGenerationOutput
   result = llm.invoke_structured(prompt, EmailGenerationOutput)
   subject = result.subject  # Type-safe, validated
   ```

## Debugging & Observability

### Tracing
- All agents emit OpenTelemetry traces automatically
- View traces in AWS X-Ray or your preferred backend
- Trace IDs propagate across events via `trace_context` field

### Logging
```python
import structlog

log = structlog.get_logger()

# Good - structured logs
log.info(
    "provider_state_updated",
    campaign_id=campaign_id,
    provider_id=provider_id,
    old_status=old_status,
    new_status=new_status
)

# Bad - unstructured
print(f"Updated {provider_id} from {old_status} to {new_status}")
```

### Monitoring Key Metrics
- Provider state transition rates
- Time in each state
- Event processing latency
- DLQ message count
- SES bounce/complaint rates

## Security & Compliance

- **Never log PII** - provider emails, documents, etc.
- **Encrypt at rest** - DynamoDB encryption enabled
- **Encrypt in transit** - TLS for all AWS service calls
- **IAM least privilege** - agents have minimal permissions
- **Audit trail** - all state changes logged to CloudTrail

## Resources

- [Strands AI Documentation](https://docs.strands.ai)
- [AWS Bedrock AgentCore Guide](https://docs.aws.amazon.com/bedrock/agentcore)
- [Event-Driven Architecture Patterns](internal link)
- [DynamoDB Single Table Design](internal link)

## Getting Help

For questions or issues:
1. Check existing tests for examples
2. Review agent implementation in `agents/`
3. Consult architecture docs in `docs/architecture/`

## Progress Tracking

**IMPORTANT:** Always maintain a log of work completed in `PROGRESS.md`

After completing any significant task or milestone:
1. Update `PROGRESS.md` with:
   - **Date** of completion (YYYY-MM-DD)
   - **Task** description (reference BUILD_PLAN.md phases)
   - **Changes** made (files created/modified, agents implemented, tests added)
   - **Status** (✅ Completed, 🔄 In Progress, ⚠️ Blocked)
   - **Notes** (challenges, decisions, follow-ups)

2. Format entries as:
```markdown
### [PHASE X] - Task Name
**Date:** YYYY-MM-DD | **Status:** ✅ Completed

- Change 1: description
- Change 2: description
- Dependencies: list any blocking items

**Notes:** any relevant context or learnings
```

3. Use this format to ensure:
   - Clear audit trail of development progress
   - Quick reference for current project state
   - Easy identification of what needs to come next
   - Continuity if development is paused/resumed

This log is the single source of truth for project status alongside ARCHITECHTURE.md and BUILD_PLAN.md.

## Phase Review Process

**CRITICAL:** After completing each BUILD_PLAN.md phase, perform a mandatory review before proceeding.

### Review Steps (After Each Phase)

1. **Architecture Alignment Check**
   - Verify implementation matches ARCHITECHTURE.md patterns
   - Confirm event types match `contracts/events.json`
   - Confirm state transitions match `contracts/state_machine.json`
   - Ensure DynamoDB patterns match `contracts/dynamodb_schema.json`

2. **Demo Scenario Compatibility**
   - Validate code supports PHASE 10 demo (Satellite Upgrade):
     - 3 markets: Atlanta, Chicago, Milwaukee
     - 5 providers per market target
     - Equipment: bucket_truck, spectrum_analyzer
     - Insurance: $2M minimum, Textract OCR
   - Check keywords match `contracts/requirements_schema.json`

3. **Agent Principles Verification**
   - No `time.sleep()` or `while` loops (agents never wait)
   - No direct agent-to-agent calls (events only)
   - State persisted to DynamoDB before agent exit
   - Tools are idempotent

4. **Forward Compatibility**
   - Interfaces stable for downstream phases
   - Event payloads include all fields needed by consumers
   - No breaking changes to shared infrastructure

5. **Code Quality**
   - Type hints on all functions
   - Pydantic validation on inputs
   - Structured logging (structlog)
   - Tests for core logic

### Review Documentation

Add review results to PROGRESS.md after each phase:

```markdown
**Review Performed:** YYYY-MM-DD
- Architecture alignment: ✅/⚠️
- Demo compatibility: ✅/⚠️
- Agent principles: ✅/⚠️
- Forward compatibility: ✅/⚠️
- Code quality: ✅/⚠️

**Review Notes:**
- Deviations from architecture (with justification)
- Demo scenario gaps
- Risks for downstream phases
```

### Review Triggers

**Perform review when:**
- Completing any phase in BUILD_PLAN.md
- Before starting implementation of a dependent phase
- After significant refactoring
- When contracts are modified

**Do NOT skip review** even if phase seems straightforward—forward compatibility issues compound.
