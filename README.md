# Recruitment Automation (Email-Driven POC)

Event-driven, agent-based recruitment automation for provider outreach, screening, and qualification. AI agents (AWS Bedrock) replace staff workflows; email is the provider UI; state lives in DynamoDB; events drive all actions.

## What It Does

- **Campaign Planner** — Interprets requirements, selects providers, creates sessions, emits outreach events.
- **Communication Agent** — Drafts and sends emails via SES (or mock locally).
- **Screening Agent** — Classifies responses, triggers document processing (Textract), and decides qualified/rejected.
- **Inbound pipeline** — SES → Lambda → EventBridge; document processing and follow-ups are event-triggered.

Agents are stateless and event-reactive; they never poll or hold long-running state.

## Tech Stack

- **Backend:** Python 3.12, [Strands AI](https://strands.ai), AWS Bedrock (Claude), boto3, Pydantic.
- **Frontend:** Next.js 16 (App Router), React 19, Tailwind CSS.
- **AWS:** DynamoDB, S3, EventBridge, SES, SNS, Lambda, Textract (production).

## Project Layout

| Path | Purpose |
|------|---------|
| `agents/` | Campaign Planner, Communication, Screening agents + shared LLM, DynamoDB, EventBridge, S3, email tools |
| `lambdas/` | Process inbound email, send follow-ups, Textract completion handlers |
| `lambda_deployment/` | Per-Lambda build scripts and handler wrappers for AWS |
| `contracts/` | Event types, DynamoDB schema, state machine, document types |
| `campaign-ui/` | Next.js app: campaign list, create campaign, campaign dashboard, provider journey, event stream, simulate response |
| `scripts/` | `local_api_server.py` (FastAPI + in-process event routing), `local_event_router.py`, `local_textract_mock.py`, test data generation |
| `tests/` | Pytest unit and integration tests |
| `Docs/` | Architecture, local execution plan, flow docs |

## Prerequisites

- Python 3.12+
- Node 20+ (for campaign-ui)
- AWS credentials with Bedrock access (for LLM; local runs use real Bedrock, mocked DynamoDB/S3/EventBridge/SES/Textract)

## Quick Start (Local)

1. **Install backend**
   ```bash
   pip install -e ".[dev]"
   cp .env.local.example .env.local   # optional: tune Bedrock model/region
   ```

2. **Start API server** (mocked AWS, in-process events, real Bedrock)
   ```bash
   python scripts/local_api_server.py
   ```
   API: http://localhost:8000

3. **Start UI**
   ```bash
   cd campaign-ui
   npm install
   echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
   npm run dev
   ```
   App: http://localhost:3000

4. Create a campaign from the UI, then use **Simulate Response** on a provider to drive the screening flow and see the journey update.

## Configuration

- **Root:** `.env` / `.env.local` — backend and agents (see `.env.example` and `.env.local.example`).
- **Local:** `RECRUITMENT_*` vars in `.env.local`; mock endpoints use `mock`; Bedrock stays real.
- **campaign-ui:** `NEXT_PUBLIC_API_URL` in `campaign-ui/.env.local` (default `http://localhost:8000`).

## Testing

```bash
pytest
```

Optional: `pytest -m "not integration"` for unit-only. See `pyproject.toml` for coverage and markers.

## Deployment

- **Agents** run inside Lambda via wrappers in `lambda_deployment/` (Campaign Planner, Communication, Screening).
- **Lambdas** also include process-inbound-email, send-follow-ups, textract-completion.
- Deploy DynamoDB (with GSI), S3, EventBridge, SES, SNS, and Lambdas; set production env vars (no mock endpoints). See `ARCHITECHTURE.md` and `Docs/LOCAL_EXECUTION_PLAN.md`.

## Docs

- **ARCHITECHTURE.md** — Event contracts, state machine, DynamoDB design, phases, demo scenario.
- **Docs/LOCAL_EXECUTION_PLAN.md** — Local vs production, FastAPI/Next.js setup, checklist.
- **contracts/** — `events.json`, `dynamodb_schema.json`, `state_machine.json`.

## License

MIT (see `pyproject.toml`).
