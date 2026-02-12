# Event Contract Development Instructions

## Purpose

This file guides development of **event schemas and contracts** that form the communication backbone of our agent-driven recruitment automation system.

## Event-Driven Architecture Principles

### Events Are the Single Source of Truth
- All agent coordination happens through events
- No direct agent-to-agent calls
- No shared queues or message brokers
- EventBridge is the only event transport

### Events Are Immutable
- Once published, events cannot be changed
- Use versioning for schema evolution
- Old versions must be supported during transitions

### Events Are Self-Describing
- Include all context needed to process
- No implicit state or side-channel dependencies
- Trace context propagated for observability

## Event Schema Structure

### Base Event Schema

All events must follow this structure:

```json
{
  "version": "0",
  "id": "uuid",
  "detail-type": "EventName",
  "source": "recruitment.agents.<agent_name>",
  "account": "aws-account-id",
  "time": "iso8601-timestamp",
  "region": "aws-region",
  "resources": [],
  "detail": {
    // Event-specific payload
    "campaign_id": "string",
    "provider_id": "string",
    "trace_context": {
      "trace_id": "string",
      "span_id": "string"
    }
    // ... additional fields
  }
}
```

### Event Naming Conventions

`detail-type` must match the PascalCase event names listed in ARCHITECHTURE.md, e.g.:

- `NewCampaignRequested`
- `SendMessageRequested`
- `ProviderResponseReceived`
- `ScreeningCompleted`
- `FollowUpTriggered`
- `DocumentProcessed`
- `ReplyToProviderRequested`

## Event Catalog

### Location
`contracts/events.json` - Single source of truth for all events

### Schema Format

```json
{
  "events": {
    "NewCampaignRequested": {
      "version": "1.0.0",
      "source": "recruitment.api",
      "description": "Buyer creates new recruitment campaign",
      "detail_schema": {
        "type": "object",
        "required": ["campaign_id", "buyer_id", "requirements"],
        "properties": {
          "campaign_id": {
            "type": "string",
            "pattern": "^campaign-[a-zA-Z0-9]+$"
          },
          "buyer_id": {
            "type": "string"
          },
          "requirements": {
            "type": "object",
            "required": ["skills", "budget", "timeline"],
            "properties": {
              "skills": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1
              },
              "budget": {
                "type": "object",
                "required": ["min", "max", "currency"],
                "properties": {
                  "min": {"type": "number", "minimum": 0},
                  "max": {"type": "number", "minimum": 0},
                  "currency": {"type": "string", "enum": ["USD", "EUR", "GBP"]}
                }
              },
              "timeline": {
                "type": "object",
                "required": ["start_date", "duration_days"],
                "properties": {
                  "start_date": {"type": "string", "format": "date"},
                  "duration_days": {"type": "integer", "minimum": 1}
                }
              }
            }
          },
          "trace_context": {
            "$ref": "#/definitions/trace_context"
          }
        }
      },
      "triggers": ["CampaignPlannerAgent"],
      "produces": ["SendMessageRequested"],
      "changelog": [
        {
          "version": "1.0.0",
          "date": "2024-01-01",
          "changes": "Initial version"
        }
      ]
    },
    
    "SendMessageRequested": {
      "version": "1.0.0",
      "source": "recruitment.agents.campaign_planner",
      "description": "Request to send email to provider",
      "detail_schema": {
        "type": "object",
        "required": [
          "campaign_id",
          "provider_id",
          "message_type"
        ],
        "properties": {
          "campaign_id": {"type": "string"},
          "provider_id": {"type": "string"},
          "provider_email": {"type": "string", "format": "email"},
          "provider_name": {"type": "string"},
          "provider_market": {"type": "string"},
          "message_type": {
            "type": "string",
            "enum": ["initial_outreach", "follow_up", "missing_document", "clarification"]
          },
          "template_data": {
            "type": "object",
            "description": "Data for email template rendering",
            "properties": {
              "campaign_type": {"type": "string"},
              "market": {"type": "string"},
              "equipment_list": {"type": "string"},
              "insurance_requirement": {"type": "string"},
              "missing_documents": {"type": "array", "items": {"type": "string"}}
            }
          },
          "custom_message": {"type": "string"},
          "trace_context": {
            "$ref": "#/definitions/trace_context"
          }
        }
      },
      "triggers": ["CommunicationAgent"],
      "produces": [],
      "changelog": [
        {
          "version": "1.0.0",
          "date": "2024-01-01",
          "changes": "Initial version"
        }
      ]
    },
    
    "ProviderResponseReceived": {
      "version": "1.0.0",
      "source": "recruitment.lambdas.process_inbound_email",
      "description": "Provider replied to outreach email",
      "detail_schema": {
        "type": "object",
        "required": [
          "campaign_id",
          "provider_id",
          "body",
          "received_at",
          "email_thread_id"
        ],
        "properties": {
          "campaign_id": {"type": "string"},
          "provider_id": {"type": "string"},
          "body": {
            "type": "string",
            "minLength": 1,
            "maxLength": 10000
          },
          "attachments": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["filename", "s3_path", "content_type", "size_bytes"],
              "properties": {
                "filename": {"type": "string"},
                "s3_path": {"type": "string", "pattern": "^s3://"},
                "content_type": {"type": "string"},
                "size_bytes": {"type": "integer", "minimum": 0}
              }
            }
          },
          "received_at": {"type": "integer", "minimum": 0},
          "email_thread_id": {"type": "string"},
          "trace_context": {
            "$ref": "#/definitions/trace_context"
          }
        }
      },
      "triggers": ["ScreeningAgent"],
      "produces": [
        "SendMessageRequested",
        "DocumentProcessed",
        "ScreeningCompleted"
      ],
      "changelog": [
        {
          "version": "1.0.0",
          "date": "2024-01-01",
          "changes": "Initial version"
        }
      ]
    },
    
    "DocumentProcessed": {
      "version": "1.0.0",
      "source": "recruitment.lambdas.textract_completion",
      "description": "Textract finished processing document",
      "detail_schema": {
        "type": "object",
        "required": [
          "campaign_id",
          "provider_id",
          "document_s3_path",
          "extracted_text",
          "job_id"
        ],
        "properties": {
          "campaign_id": {"type": "string"},
          "provider_id": {"type": "string"},
          "document_s3_path": {"type": "string", "pattern": "^s3://"},
          "extracted_text": {"type": "string"},
          "structured_data": {
            "type": "object",
            "description": "Optional structured data extracted via Textract Analyze"
          },
          "job_id": {"type": "string"},
          "trace_context": {
            "$ref": "#/definitions/trace_context"
          }
        }
      },
      "triggers": ["ScreeningAgent"],
      "produces": ["ScreeningCompleted", "SendMessageRequested"],
      "changelog": [
        {
          "version": "1.0.0",
          "date": "2024-01-01",
          "changes": "Initial version"
        }
      ]
    },
    
    "ScreeningCompleted": {
      "version": "1.0.0",
      "source": "recruitment.agents.screening",
      "description": "Provider screening finished with decision",
      "detail_schema": {
        "type": "object",
        "required": [
          "campaign_id",
          "provider_id",
          "decision",
          "reasoning"
        ],
        "properties": {
          "campaign_id": {"type": "string"},
          "provider_id": {"type": "string"},
          "decision": {
            "type": "string",
            "enum": ["QUALIFIED", "REJECTED", "ESCALATED"]
          },
          "reasoning": {
            "type": "string",
            "description": "Human-readable explanation of decision"
          },
          "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "artifacts_reviewed": {
            "type": "array",
            "items": {"type": "string"}
          },
          "trace_context": {
            "$ref": "#/definitions/trace_context"
          }
        }
      },
      "triggers": ["NotificationAgent"],
      "produces": [],
      "changelog": [
        {
          "version": "1.0.0",
          "date": "2024-01-01",
          "changes": "Initial version"
        }
      ]
    },
    
    "FollowUpTriggered": {
      "version": "1.0.0",
      "source": "recruitment.lambdas.send_follow_ups",
      "description": "Scheduled follow-up reminder triggered",
      "detail_schema": {
        "type": "object",
        "required": [
          "campaign_id",
          "provider_id",
          "follow_up_number",
          "days_since_last_contact"
        ],
        "properties": {
          "campaign_id": {"type": "string"},
          "provider_id": {"type": "string"},
          "follow_up_number": {
            "type": "integer",
            "minimum": 1,
            "maximum": 3
          },
          "days_since_last_contact": {"type": "integer", "minimum": 0},
          "trace_context": {
            "$ref": "#/definitions/trace_context"
          }
        }
      },
      "triggers": ["CommunicationAgent"],
      "produces": ["SendMessageRequested"],
      "changelog": [
        {
          "version": "1.0.0",
          "date": "2024-01-01",
          "changes": "Initial version"
        }
      ]
    },
    
    "ReplyToProviderRequested": {
      "version": "1.0.0",
      "source": "recruitment.agents.screening",
      "description": "Request to send a reply to provider for missing or invalid content",
      "detail_schema": {
        "type": "object",
        "required": [
          "campaign_id",
          "provider_id",
          "reply_reason"
        ],
        "properties": {
          "campaign_id": {"type": "string"},
          "provider_id": {"type": "string"},
          "reply_reason": {
            "type": "string",
            "enum": ["missing_attachment", "invalid_document", "incomplete_response", "clarification_needed"]
          },
          "original_message_id": {"type": "string"},
          "context": {
            "type": "object",
            "description": "Additional context for the reply (e.g., missing_documents, questions)"
          },
          "trace_context": {
            "$ref": "#/definitions/trace_context"
          }
        }
      },
      "triggers": ["CommunicationAgent"],
      "produces": [],
      "changelog": [
        {
          "version": "1.0.0",
          "date": "2026-02-08",
          "changes": "Initial version for LLM-powered reply generation"
        }
      ]
    }
  },
  
  "definitions": {
    "trace_context": {
      "type": "object",
      "required": ["trace_id"],
      "properties": {
        "trace_id": {
          "type": "string",
          "pattern": "^[a-f0-9]{32}$"
        },
        "span_id": {
          "type": "string",
          "pattern": "^[a-f0-9]{16}$"
        },
        "parent_span_id": {
          "type": "string",
          "pattern": "^[a-f0-9]{16}$"
        }
      }
    }
  }
}
```

## Event Development Workflow

### 1. Design Phase

Before writing code:

1. **Identify the business event** - What happened or needs to happen?
2. **Determine event type** - Domain event or command?
3. **Define payload** - What data is needed to process this event?
4. **Document triggers** - Which agents/lambdas respond?
5. **Document produces** - What events does processing emit?

### 2. Schema Definition

Add event to `contracts/events.json`:

```bash
# Use JSON Schema validator
pip install jsonschema

# Validate schema
python scripts/validate_event_schemas.py
```

### 3. Generate Pydantic Models

Auto-generate type-safe models from schemas:

```bash
# Generate models for all events
python scripts/generate_event_models.py

# Output: agents/shared/models/events.py
```

Generated code example:

```python
# Auto-generated from contracts/events.json
# DO NOT EDIT MANUALLY

from pydantic import BaseModel, Field
from typing import Literal, Optional

class ProviderResponseReceived(BaseModel):
    """Provider replied to outreach email"""
    
    campaign_id: str
    provider_id: str
    body: str = Field(..., min_length=1, max_length=10000)
    attachments: list[dict] = Field(default_factory=list)
    received_at: int = Field(..., ge=0)
    email_thread_id: str
    trace_context: TraceContext
    
    class Config:
        frozen = True
```

### 4. Testing Events

Write tests for event validation:

```python
# tests/unit/test_event_schemas.py

import pytest
from agents.shared.models.events import ProviderResponseReceived

def test_provider_response_valid():
    """Valid event passes validation"""
    event = ProviderResponseReceived(
        campaign_id="campaign-123",
        provider_id="provider-456",
        body="I'm interested",
        received_at=1640000000,
        email_thread_id="thread-789",
        trace_context={"trace_id": "a" * 32}
    )
    assert event.campaign_id == "campaign-123"

def test_provider_response_missing_required():
    """Event missing required field fails"""
    with pytest.raises(ValidationError):
        ProviderResponseReceived(
            campaign_id="campaign-123",
            # Missing provider_id
            body="I'm interested",
            received_at=1640000000,
            email_thread_id="thread-789"
        )

def test_provider_response_invalid_timestamp():
    """Negative timestamp fails validation"""
    with pytest.raises(ValidationError):
        ProviderResponseReceived(
            campaign_id="campaign-123",
            provider_id="provider-456",
            body="I'm interested",
            received_at=-1,  # Invalid
            email_thread_id="thread-789",
            trace_context={"trace_id": "a" * 32}
        )
```

## EventBridge Integration

### Subscribing to Events

Define EventBridge rules in infrastructure:

```python
# infrastructure/eventbridge/rules.py

rules = [
    {
        "name": "screening-agent-on-provider-response",
        "description": "Wake screening agent when provider responds",
        "event_pattern": {
            "source": ["recruitment.lambdas.process_inbound_email"],
            "detail-type": ["ProviderResponseReceived"]
        },
        "targets": [
            {
                "arn": "arn:aws:bedrock:agent:screening",
                "dead_letter_config": {
                    "arn": "arn:aws:sqs:screening-dlq"
                }
            }
        ]
    },
    {
        "name": "communication-agent-on-send-request",
        "description": "Wake communication agent to send email",
        "event_pattern": {
            "source": [
                "recruitment.agents.campaign_planner",
                "recruitment.agents.screening"
            ],
            "detail-type": ["SendMessageRequested"]
        },
        "targets": [
            {
                "arn": "arn:aws:bedrock:agent:communication",
                "dead_letter_config": {
                    "arn": "arn:aws:sqs:communication-dlq"
                }
            }
        ]
    }
]
```

### Publishing Events

Use the shared `send_event` tool:

```python
from agents.shared.tools import send_event

# Inside agent logic
await send_event(
    detail_type="ScreeningCompleted",
    detail={
        "campaign_id": campaign_id,
        "provider_id": provider_id,
        "decision": "QUALIFIED",
        "reasoning": "All requirements met",
        "confidence_score": 0.95,
        "trace_context": propagate_trace_context(event)
    }
)
```

## Event Versioning

### Backward Compatibility

When evolving events, maintain backward compatibility:

**✅ Safe Changes:**
- Adding optional fields
- Adding new enum values (if consumers handle unknown values)
- Relaxing validation (e.g., increasing max length)

**❌ Breaking Changes:**
- Removing fields
- Renaming fields
- Changing field types
- Making optional fields required
- Removing enum values

### Version Migration

For breaking changes:

1. **Create new version** - `ProviderResponseReceived_v2`
2. **Publish both versions** - Dual-publish during transition
3. **Update consumers** - Migrate agents one by one
4. **Deprecate old version** - After all consumers migrated
5. **Remove old version** - After deprecation period

Example:

```python
# Publish both versions during migration
await send_event(
    detail_type="ProviderResponseReceived",  # v1
    detail={...}
)

await send_event(
    detail_type="ProviderResponseReceived_v2",  # v2
    detail={...}  # New schema
)
```

## Trace Context Propagation

### Purpose
Enable distributed tracing across event-driven workflows

### Implementation

```python
import uuid

def create_trace_context(parent_context: dict | None = None) -> dict:
    """
    Create trace context for new event.
    
    Args:
        parent_context: Optional parent trace context to inherit from
        
    Returns:
        New trace context with propagated trace_id
    """
    if parent_context:
        trace_id = parent_context["trace_id"]
        parent_span_id = parent_context["span_id"]
    else:
        trace_id = uuid.uuid4().hex
        parent_span_id = None
    
    return {
        "trace_id": trace_id,
        "span_id": uuid.uuid4().hex[:16],
        "parent_span_id": parent_span_id
    }

# Usage in agent
def handle_event(event: ProviderResponseReceived):
    # Propagate trace context to downstream events
    trace_ctx = create_trace_context(event.trace_context)
    
    await send_event(
        detail_type="ScreeningCompleted",
        detail={
            ...
            "trace_context": trace_ctx
        }
    )
```

## Event Replay Strategy

### Dead Letter Queues

Every EventBridge rule must have DLQ:

```python
# Failed events go to SQS for manual inspection/replay
"dead_letter_config": {
    "arn": "arn:aws:sqs:region:account:agent-dlq"
}
```

### Replay Process

1. **Inspect failure** - Check DLQ message and logs
2. **Fix root cause** - Update agent code or data
3. **Replay event** - Send message back to EventBridge
4. **Verify success** - Check state was updated correctly

```bash
# Replay script
python scripts/replay_dlq_messages.py \
  --queue-url https://sqs.../agent-dlq \
  --max-messages 10
```

## Event Documentation

### Required Documentation

For each event, document:

1. **Business purpose** - Why does this event exist?
2. **Trigger conditions** - What causes this event?
3. **Processing SLA** - How fast must it be processed?
4. **Consumers** - Which agents/lambdas subscribe?
5. **Side effects** - What state changes occur?
6. **Error scenarios** - What can go wrong?

### Example

```markdown
## ProviderResponseReceived

**Purpose:** Notifies system that a provider has replied to outreach email

**Triggers:**
- Provider sends email to campaign+X_provider+Y@domain.com
- SES receives email and routes to SNS
- ProcessInboundEmail lambda parses and publishes event

**SLA:** Must be processed within 5 minutes

**Consumers:**
- ScreeningAgent (primary)
- AnalyticsCollector (secondary, metrics only)

**State Changes:**
- Provider status: WAITING_RESPONSE → WAITING_DOCUMENT or UNDER_REVIEW
- Artifacts updated with attachment S3 paths

**Error Scenarios:**
- Missing campaign_id in email → Dead lettered
- Unparseable attachment → Log warning, continue
- DynamoDB throttling → Automatic retry with backoff
```

## Best Practices

1. **Include all context** - Don't rely on external state lookups
2. **Keep payloads small** - EventBridge has 256KB limit
3. **Use enums** - For finite value sets
4. **Validate early** - Use Pydantic models
5. **Document changes** - Update changelog in schema
6. **Version carefully** - Breaking changes need migration plan
7. **Test thoroughly** - Unit tests for all validation paths
8. **Trace everything** - Propagate trace context in all events

## Resources

- [Event Schemas](../contracts/events.json)
- [State Machine](../contracts/state_machine.json)
- [EventBridge Patterns](https://docs.aws.amazon.com/eventbridge/patterns.html)
- [JSON Schema](https://json-schema.org/)
