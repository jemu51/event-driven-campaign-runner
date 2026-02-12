
# Agent-Driven Recruitment Automation — Final Build Plan

## Objective

Build an **event-driven, agent-based recruitment system** that automates provider outreach, screening, and decisioning inside an online marketplace.

The system replaces staff-driven workflows with **Strands AI agents running on AWS Bedrock AgentCore**, while supporting:

* Long-running recruitment campaigns
* Asynchronous provider responses (days later)
* Email-based interaction with attachments
* Stateless agents with persistent external memory

---

## Core Principles (Non-Negotiable)

1. **Agents never wait** — they think, act, persist state, and exit.
2. **All long-term state lives in DynamoDB**, not agent memory.
3. **Events wake agents**, not polling or loops.
4. **Email is the UI** for providers.
5. **Each agent has a single responsibility.**

---

## PHASE 1 — System Contracts

### 1.1 Event Types (Single Source of Truth)

Define these events in `/contracts/events.json`:

* `NewCampaignRequested`
* `SendMessageRequested`
* `ProviderResponseReceived`
* `ScreeningCompleted`
* `FollowUpTriggered`
* `DocumentProcessed`
* `ReplyToProviderRequested`

Agents **only** react to events.
Agents **never** call each other directly.

---

### 1.2 Provider State Machine

Allowed states:

```
INVITED
WAITING_RESPONSE
WAITING_DOCUMENT
DOCUMENT_PROCESSING
UNDER_REVIEW
QUALIFIED
REJECTED
ESCALATED
```

Agents must **not invent states**.

---

## PHASE 2 — Persistent State (DynamoDB)

### 2.1 Table: `RecruitmentSessions`

| Attribute           | Purpose                     |
| ------------------- | --------------------------- |
| PK                  | `SESSION#<campaign_id>`     |
| SK                  | `PROVIDER#<provider_id>`    |
| status              | Provider state              |
| expected_next_event | What wakes the agent        |
| last_contacted_at   | Unix timestamp              |
| email_thread_id     | SES message/thread tracking |
| artifacts           | S3 doc paths + OCR output   |
| audit_log           | Optional (append-only)      |

**Extended Fields for Demo Scenario:**

| Attribute              | Purpose                                    |
| ---------------------- | ------------------------------------------ |
| provider_email         | Provider's email address                   |
| provider_market        | Market assignment (e.g., "atlanta")        |
| equipment_confirmed    | Array of confirmed equipment               |
| equipment_missing      | Array of missing required equipment        |
| travel_confirmed       | Boolean - travel willingness               |
| documents_uploaded     | Array of uploaded document types           |
| documents_pending      | Array of still-needed document types       |
| screening_notes        | Human-readable screening summary           |

This table is the **only memory** agents rely on.

**Example Record:**

```json
{
  "PK": "SESSION#satellite-upgrade-2026-02",
  "SK": "PROVIDER#prov-001",
  "status": "WAITING_DOCUMENT",
  "expected_next_event": "ProviderResponseReceived",
  "last_contacted_at": 1738800000,
  "email_thread_id": "msg-abc123",
  "provider_email": "tech@example.com",
  "provider_market": "atlanta",
  "equipment_confirmed": ["bucket_truck"],
  "equipment_missing": ["spectrum_analyzer"],
  "travel_confirmed": true,
  "documents_uploaded": [],
  "documents_pending": ["insurance_certificate"],
  "screening_notes": "Has bucket truck, missing spectrum analyzer. Travel confirmed.",
  "artifacts": {},
  "GSI1PK": "WAITING_DOCUMENT#ProviderResponseReceived"
}
```

---

### 2.2 GSI for Dormant Sessions

**GSI1**

```
Partition Key: status#expected_next_event
Sort Key: last_contacted_at (Number)
```

Example PK:

```
WAITING_RESPONSE#PROVIDER_RESPONSE
```

This supports:

* Reminder queries
* Long-wait handling
* Zero table scans

---

## PHASE 3 — Event Backbone

### 3.1 EventBridge

* Create a dedicated EventBridge bus
* Every Lambda and Agent subscribes via rules
* **Attach DLQ to every rule** for observability and replay

---

## PHASE 4 — Communication Layer (Email)

### 4.1 Outbound Email (SES)

* Verified domain
* Emails sent via Communication Agent
* Reply-To format:

```
campaign+<campaign_id>_provider+<provider_id>@yourdomain.com
```

This is the **only identity mechanism** for inbound replies.

---

### 4.2 Inbound Email Pipeline

Flow:

```
Provider Reply
 → SES Receipt Rule (catch-all domain)
 → SNS Topic
 → Lambda: ProcessInboundEmail
 → EventBridge: ProviderResponseReceived
```

---

### 4.3 `ProcessInboundEmail` Lambda Responsibilities

* Parse SNS → SES event
* Extract:

  * Reply-To (preferred) or To header
  * campaign_id
  * provider_id
  * body text
  * attachments
* Store attachments in S3
* Emit:

```json
{
  "detail-type": "ProviderResponseReceived",
  "detail": {
    "campaign_id": "...",
    "provider_id": "...",
    "body": "...",
    "attachments": ["s3://..."],
    "received_at": 1710000000,
    "email_thread_id": "..."
  }
}
```

---

## PHASE 5 — Agents (Strands + AgentCore)

Each agent is deployed **independently** to Bedrock AgentCore.

---

### 5.1 Campaign Planner Agent

**Triggered by:** `NewCampaignRequested`

**Responsibilities:**

1. Interpret buyer requirements
2. Select matching providers (mock or real)
3. Create provider records in DynamoDB
4. Set:

   * status = INVITED
   * expected_next_event = PROVIDER_RESPONSE
5. Emit `SendMessageRequested`

**Execution:** One-shot, no waiting.

---

### 5.2 Communication Agent

**Triggered by:** `SendMessageRequested`

**Responsibilities:**

* Draft human-like email
* Send via SES
* Update DynamoDB:

  * last_contacted_at
  * email_thread_id
  * status → WAITING_RESPONSE

**No business logic. No decisions.**

---

### 5.3 Screening Agent

**Triggered by:** `ProviderResponseReceived`

**Responsibilities:**

1. Load provider state
2. Classify response:

   * Document attached?
   * Missing info?
   * Irrelevant?
3. If attachment:

   * Store in S3
   * Set status = DOCUMENT_PROCESSING
   * Trigger Textract async job
4. If no attachment:

   * Ask follow-up (emit `SendMessageRequested`)
5. Exit

---

## PHASE 6 — Document Processing

### 6.1 Textract Async Flow

```
S3 Upload
 → Textract Async Job
 → Completion Lambda
 → EventBridge: DocumentProcessed
```

### 6.2 On `DocumentProcessed`

Screening Agent resumes:

* Read OCR output
* Extract keywords / expiry dates
* Update artifacts
* Decide:

  * QUALIFIED
  * WAITING_DOCUMENT
  * REJECTED
* Emit next action event

---

## PHASE 7 — Dormant Sessions (Long-Wait Handling)

### 7.1 Dormant Session Pattern

* Agent writes:

  ```
  expected_next_event
  last_contacted_at
  ```
* Agent exits
* **No compute is running**

---

### 7.2 Reminder Scheduler

EventBridge Scheduled Rule (daily):

Lambda `SendFollowUps`:

* Query GSI1:

  ```
  status#expected_next_event = WAITING_RESPONSE#PROVIDER_RESPONSE
  AND last_contacted_at < now - threshold
  ```
* Emit `SendMessageRequested`

---

## PHASE 8 — Campaign Completion

When enough providers qualify:

* Screening Agent emits `ScreeningCompleted`
* Optional Buyer Notification Agent sends summary
* Campaign marked complete in DynamoDB

---

## PHASE 9 — Testing & Local Development

### 9.1 Local Development

* Define event schemas first
* Run agents locally:

  ```
  strands run
  ```
* Mock tools:

  * DynamoDB (moto)
  * SES (stub)
  * EventBridge/SNS (in-memory)

---

### 9.2 Incremental Deployment

* Deploy one agent at a time to AgentCore
* Validate with real emails using your own domain
* Observe DLQs and traces

---

### 9.3 Observability

* Enable OpenTelemetry (Strands + AgentCore native)
* Trace:

  * Event → Agent → Tool → Event
* Monitor:

  * Drop-offs
  * Time-to-response
  * Qualification rates

---

## PHASE 10 — Demo Scenario: Satellite Upgrade Campaign

### 10.1 Overview

The POC demonstrates a realistic "Satellite Upgrade" recruitment campaign that exercises all system components.

**Campaign Parameters:**
* **Type:** Satellite dish installation and upgrade
* **Markets:** 3 geographic regions (Atlanta, Chicago, Milwaukee)
* **Target:** 5 qualified providers per market (15 total)
* **Timeline:** Async responses over days/weeks

---

### 10.2 Screening Requirements

**Equipment Requirements:**
* Bucket truck (required)
* Spectrum analyzer (required)
* Fiber splicer (optional)

**Qualifications:**
* Travel willingness to assigned market
* Valid insurance certificate (minimum $2M coverage)
* Certifications (CompTIA Network+, BICSI, or FCC license preferred)

**Document Verification:**
* Insurance certificate upload via email attachment
* Textract OCR extraction of:
  * Policy expiry date
  * Coverage amount
  * Policy holder name

---

### 10.3 Demo Flow

```
1. NewCampaignRequested
   ├─ campaign_id: "satellite-upgrade-2026-02"
   ├─ markets: ["atlanta", "chicago", "milwaukee"]
   ├─ providers_per_market: 5
   └─ requirements:
       ├─ equipment: ["bucket_truck", "spectrum_analyzer"]
       ├─ insurance_min_coverage: 2000000
       └─ travel_required: true

2. Campaign Planner Agent
   ├─ Selects 15 candidate providers
   ├─ Creates DynamoDB records (status=INVITED)
   └─ Emits 15 × SendMessageRequested

3. Communication Agent
   └─ Sends personalized emails:
       "We're seeking satellite upgrade technicians in [MARKET].
        Requirements:
        - Bucket truck and spectrum analyzer
        - Willing to travel
        - Insurance certificate ($2M+ coverage)
        
        Please reply with your equipment and attach your insurance cert."

4. Provider Responses (Async, Days Later)
   ├─ Provider A (Atlanta): "Yes, I have both. Cert attached." [PDF]
   ├─ Provider B (Chicago): "I have bucket truck only."
   ├─ Provider C (Milwaukee): "Can travel, have equipment." [No attachment]
   └─ Providers D-O: Various responses

5. Screening Agent (Per Response)
   ├─ Text Analysis:
   │   ├─ Equipment keywords: "bucket truck", "spectrum analyzer"
   │   └─ Travel confirmation: "can travel", "willing to travel"
   ├─ Document Processing:
   │   ├─ S3 upload → Textract
   │   ├─ Extract expiry date, coverage amount
   │   └─ Validate: expiry > today AND coverage >= $2M
   └─ State Transitions:
       ├─ Has equipment + insurance → QUALIFIED
       ├─ Missing equipment → REJECTED
       ├─ Missing insurance → WAITING_DOCUMENT (send follow-up)
       └─ Edge cases → UNDER_REVIEW (manual review)

6. Follow-Up Flow
   └─ If WAITING_DOCUMENT > 3 days:
       Emit FollowUpTriggered
       → "We still need your insurance certificate."

7. Campaign Completion
   ├─ When 5 providers QUALIFIED per market:
   │   └─ Emit ScreeningCompleted
   └─ Buyer notification:
       "15 providers screened, 15 qualified:
        - Atlanta: [Provider list]
        - Chicago: [Provider list]
        - Milwaukee: [Provider list]"
```

---

### 10.4 Test Data Requirements

**Mock Providers (15 total):**
* 5 with complete equipment + valid insurance
* 3 with partial equipment (missing spectrum analyzer)
* 4 with equipment but no insurance attached
* 2 with expired insurance certificates
* 1 with irrelevant response

**Sample Insurance PDFs:**
* Valid cert: `insurance_acme_valid_2027.pdf`
* Expired cert: `insurance_expired_2025.pdf`
* Low coverage: `insurance_1M_coverage.pdf`

**Expected Outcomes:**
* ~7-8 providers reach QUALIFIED
* ~3-4 providers in WAITING_DOCUMENT
* ~2-3 providers REJECTED
* ~1-2 providers UNDER_REVIEW

---

### 10.5 Event Schema Example

```json
{
  "detail-type": "NewCampaignRequested",
  "detail": {
    "campaign_id": "satellite-upgrade-2026-02",
    "buyer_id": "acme-networks",
    "requirements": {
      "type": "satellite_upgrade",
      "markets": ["atlanta", "chicago", "milwaukee"],
      "providers_per_market": 5,
      "equipment": {
        "required": ["bucket_truck", "spectrum_analyzer"],
        "optional": ["fiber_splicer"]
      },
      "documents": {
        "required": ["insurance_certificate"],
        "insurance_min_coverage": 2000000
      },
      "certifications": {
        "preferred": ["CompTIA Network+", "BICSI", "FCC"]
      },
      "travel_required": true
    }
  }
}
```

---

### 10.6 Success Metrics

**System Performance:**
* All 15 providers contacted within 5 minutes
* Email delivery rate > 95%
* Response classification accuracy > 90%
* Document OCR success rate > 95%

**Business Outcomes:**
* Time to first qualified provider: < 24 hours
* Campaign completion time: < 7 days
* Manual review rate: < 20%
* Provider satisfaction: Seamless email experience

---

## Final Mental Model (for Copilot)

* **Agents = decision engines**
* **Events = clock**
* **DynamoDB = memory**
* **SES = UI**
* **Time does not exist inside agents**

---

### Instruction to Copilot / Cursor

> Build this system **phase by phase**, respecting agent boundaries, event contracts, and DynamoDB as the sole source of truth.
> Do not introduce long-running processes, polling agents, or in-memory state.
> 
> **Reference the demo scenario in PHASE 10** when implementing agents to ensure screening logic handles real-world requirements (equipment keywords, document validation, market assignment).
