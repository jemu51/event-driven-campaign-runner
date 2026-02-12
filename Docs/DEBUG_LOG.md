# Debug Log — Local Execution Plan Implementation

**Date:** 2026-02-11  
**Last Updated:** 2026-02-11  
**Status:** Implemented & Verified (Phase 2: Campaign Persistence + Conversations)

---

## Implementation Summary

Successfully implemented the LOCAL_EXECUTION_PLAN.md across all 4 phases:

### Phase 1: Configuration & Environment Setup
- Updated `agents/shared/config.py` with `eventbridge_endpoint_url`, `ses_endpoint_url`, `textract_endpoint_url` fields
- Added `is_local` property, `eventbridge_config`, `ses_config`, `textract_config` properties
- Updated `dynamodb_config` and `s3_config` to skip `"mock"` values
- Updated `env_file` to try `.env.local` first
- Updated `agents/shared/tools/eventbridge.py` `_get_client()` to use `settings.eventbridge_config`
- Updated `agents/shared/tools/email.py` `_get_client()` to use `settings.ses_config`
- Created `.env.local.example` (committed) and `.env.local` (gitignored)

### Phase 2: Local Event Orchestration
- Created `scripts/local_event_router.py` — in-process event routing with event queue for UI
- Created `scripts/local_textract_mock.py` — synchronous Textract mock with fixture data support

### Phase 3: FastAPI Backend Server
- Added `fastapi>=0.115.0` and `uvicorn[standard]>=0.30.0` to `pyproject.toml` dev deps
- Created `scripts/local_api_server.py` with full REST API:
  - `POST /api/campaigns` — Create campaign
  - `GET /api/campaigns/{id}` — Get campaign with provider breakdown
  - `GET /api/campaigns/{id}/providers/{pid}/journey` — Provider journey timeline
  - `POST /api/simulate/provider-response` — Simulate provider email response
  - `GET /api/events` — Filtered event list
  - `GET /api/events/stream` — SSE real-time event stream

### Phase 4: Next.js Campaign Dashboard
- Initialized Next.js 16 project with TypeScript + Tailwind CSS
- Created `lib/api.ts` (API client) and `lib/types.ts` (TypeScript types)
- Created `hooks/useEventStream.ts` (SSE) and `hooks/useCampaign.ts`
- Created components: `CampaignForm`, `ProviderCard`, `SimulateResponseModal`, `EventStream`
- Created pages: Landing page (`/`) and Campaign dashboard (`/campaigns/[id]`)

---

## Bug Fixes Applied

### 1. Screening Agent — `update_provider_state` call (agents/screening/agent.py)
**Problem:** Called `update_provider_state(..., updates=update_fields)` but function takes `new_status` as positional arg + individual kwargs, not an `updates` dict.  
**Fix:** Changed to `update_provider_state(..., new_status=new_status, **update_kwargs)` unpacking individual fields.

### 2. Screening Agent — `send_event` call (agents/screening/agent.py `_emit_next_events`)
**Problem:** Called `send_event(detail_type=..., detail=..., source=...)` but `send_event()` expects `event: BaseEvent` as first positional arg.  
**Fix:** Changed to `send_event(screening_event, source="recruitment.agents.screening")`.

### 3. Missing `textract_config` property (agents/shared/config.py)
**Problem:** `agents/screening/tools.py` line 308 uses `settings.textract_config` but `Settings` had no such property.  
**Fix:** Added `textract_config` property to `Settings` class.

---

## Verification

### End-to-end test results:
1. **Campaign creation** — Created campaign with 4 providers across 2 markets
2. **Email sending** — Mocked SES sent initial outreach emails to all providers
3. **Provider response** — Simulated positive response with equipment confirmation + document attachment
4. **Screening** — Equipment extracted (bucket_truck, spectrum_analyzer confirmed), document processing triggered
5. **State transitions** — Provider moved from INVITED → WAITING_RESPONSE → DOCUMENT_PROCESSING
6. **Event tracking** — All events logged to in-memory queue and available via API
7. **Journey timeline** — Provider journey shows SendMessageRequested → ProviderResponseReceived
8. **Frontend** — Next.js pages compile and render correctly (HTTP 200)

---

## Running Locally

### Start Backend (Terminal 1)
```bash
cd netdev-ai-poc-email-driven
.venv/bin/python scripts/local_api_server.py
# Server on http://localhost:8000
```

### Start Frontend (Terminal 2)
```bash
cd campaign-ui
npm run dev
# App on http://localhost:3000
```

### Demo Flow
1. Open http://localhost:3000
2. Fill campaign form and click "Create Campaign"
3. View provider cards on campaign dashboard
4. Click "Simulate Response" on a provider
5. Watch status update and events stream in real-time

---

## Known Issue: Bedrock LLM Errors in Logs

### Symptom
```
llm_invoke_error: 'An error occurred (404) when calling the ConverseStream operation: Not yet implemented'
```
or
```
llm_invoke_error: 'The security token included in the request is invalid'
```

### Cause
- The first error occurs when `moto.mock_aws()` intercepts Bedrock calls (moto doesn't implement Bedrock)
- The second error occurs when Bedrock calls pass through to real AWS but credentials are missing/invalid

### Fix Applied
1. **Moto passthrough** — Added Bedrock URL patterns to `moto.core.config.default_user_config["core"]["passthrough"]["urls"]` so Bedrock calls bypass moto and reach real AWS
2. **LLM Settings** — Updated `agents/shared/llm/config.py` to read `.env.local` first
3. **Cache clearing** — Added `get_llm_settings.cache_clear()` in server startup
4. **Default LLM_ENABLED=false** — Set in `.env.local` to avoid retry noise when no AWS credentials are configured

### To Enable Real Bedrock LLM
1. Configure AWS credentials: `aws configure` or set `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
2. Ensure Bedrock model access is granted in your AWS account
3. Set `RECRUITMENT_LLM_ENABLED=true` in `.env.local`

---

## Phase 2: Campaign Persistence, Events & Conversations (2026-02-11)

### Changes Made

**Backend - Data Models:**
- `agents/shared/models/dynamo.py` — Added `CampaignRecord` (PK: `CAMPAIGN#{id}`, SK: `METADATA`, GSI1PK: `CAMPAIGNS`) and `EventRecord` (PK: `EVENTS#{campaign_id}`, SK: `EVT#{ts}#{type}`) models
- `agents/shared/tools/dynamodb.py` — Added `create_campaign_record()`, `load_campaign_record()`, `update_campaign_status()`, `update_campaign_provider_count()`, `list_all_campaigns()`, `save_event_record()`, `list_campaign_events()`
- `agents/screening/agent.py` — `_get_campaign_requirements()` now loads from DynamoDB instead of hardcoded defaults

**Backend - Event Persistence & Campaign Status:**
- `scripts/local_event_router.py` — Events persisted to DynamoDB alongside in-memory queue; auto-checks campaign completion when all providers reach terminal states
- `scripts/local_api_server.py` — Campaign record saved on creation; inbound simulated responses saved to email thread

**Backend - New API Endpoints:**
- `GET /api/campaigns` — Lists all campaigns with live status derivation
- `GET /api/campaigns/{id}/providers/{pid}/conversation` — Chat-style email thread

**Frontend:**
- `CampaignList.tsx` — New component showing all campaigns with status badges, auto-refresh
- `ConversationModal.tsx` — New chat-style modal showing outbound/inbound messages
- `ProviderCard.tsx` — Updated with "View Conversation" button + clickable card
- `app/page.tsx` — Two-column layout: create form + campaign list
- `app/campaigns/[id]/page.tsx` — Shows campaign status badge, creation date, campaign type

### Verification
- Campaign creation persists to DynamoDB with full requirements
- `GET /api/campaigns` lists all campaigns with RUNNING/COMPLETED status
- Screening agent loads requirements from DB (not hardcoded)
- Conversation thread shows both OUTBOUND (initial_outreach) and INBOUND (simulated response)
- Events persisted to DynamoDB
- All frontend pages compile and render (HTTP 200)
