# Production-Ready Local Execution Plan — Demo & Deployment Ready

**Status:** ✅ Verified & Ready for Implementation  
**Goal:** Production-ready codebase that runs locally with mocked AWS services (except Bedrock) and deploys seamlessly to AWS

---

## Executive Summary

This plan enables:
- ✅ **Local Development:** Mock AWS services (DynamoDB, S3, EventBridge, SES, Textract) + **Real Bedrock LLM**
- ✅ **Production Deployment:** Same codebase works with real AWS services (SES, EventBridge, SNS, S3, DynamoDB, Textract, Bedrock)
- ✅ **Professional UI:** Next.js campaign runner dashboard with real-time updates
- ✅ **Zero Code Changes:** Agents and Lambdas work identically in local and production environments
- ✅ **Demo Ready:** Interactive journey visualization showing provider lifecycle

---

## Architecture Overview

### Local Development Environment
```
┌─────────────────────────────────────────────────────────────────┐
│  Next.js Campaign Dashboard (localhost:3000)                    │
│  • Campaign creation & management                                │
│  • Provider journey visualization                               │
│  • Real-time event streaming                                    │
│  • Response simulation                                          │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP/REST
┌──────────────────────▼──────────────────────────────────────────┐
│  FastAPI Backend (localhost:8000)                               │
│  • Campaign API endpoints                                       │
│  • Provider journey API                                         │
│  • Event streaming (SSE)                                        │
│  • In-process event orchestration                               │
└──────────────────────┬──────────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┬──────────────┐
        │              │              │              │
┌───────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐ ┌─────▼──────┐
│ Moto Mock    │ │ Real AWS │ │ Moto Mock  │ │ Moto Mock  │
│ DynamoDB + S3│ │ Bedrock  │ │ EventBridge│ │ SES        │
│              │ │ (LLM)    │ │            │ │            │
└──────────────┘ └──────────┘ └────────────┘ └────────────┘
```

### Production Deployment (AWS)
```
┌─────────────────────────────────────────────────────────────────┐
│  Next.js App (Vercel/Amplify/CloudFront + S3)                   │
│  Same UI codebase - only API URL changes                        │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTPS/REST
┌──────────────────────▼──────────────────────────────────────────┐
│  API Gateway + Lambda Functions                                  │
│  • Campaign Planner Lambda                                       │
│  • Communication Lambda                                          │
│  • Screening Lambda                                              │
│  • Process Inbound Email Lambda                                  │
│  • Textract Completion Lambda                                    │
│  • Send Follow-ups Lambda                                        │
└──────────────────────┬──────────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┬──────────────┐
        │              │              │              │
┌───────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐ ┌─────▼──────┐
│ Real AWS     │ │ Real AWS │ │ Real AWS   │ │ Real AWS   │
│ DynamoDB + S3│ │ Bedrock  │ │ EventBridge│ │ SES + SNS  │
│              │ │ (LLM)    │ │            │ │            │
└──────────────┘ └──────────┘ └────────────┘ └────────────┘
```

**Key Principle:** Code in `agents/` and `lambdas/` is **environment-agnostic**. Only configuration changes between local and production.

---

## Core Requirements

### 1. Mock AWS Services (Local Only)
- **DynamoDB:** Moto mock for provider state storage
- **S3:** Moto mock for document storage
- **EventBridge:** In-process event routing (no real EventBridge calls)
- **SES:** Moto mock (emails logged, not sent)
- **Textract:** Synchronous mock that immediately emits `DocumentProcessed` events
- **SNS:** Not needed locally (events routed in-process)

### 2. Real AWS Service (Always)
- **Bedrock:** Real API calls for LLM features (email generation, classification, screening, document analysis)

### 3. Production Readiness
- **Environment Detection:** Automatic detection via `RECRUITMENT_ENVIRONMENT` or endpoint URLs
- **Error Handling:** Production-grade error handling and logging
- **Monitoring:** Structured logging compatible with CloudWatch
- **Idempotency:** All operations are idempotent
- **Type Safety:** Full Pydantic validation for all events and models

---

## Phase 1: Configuration & Environment Setup

### 1.1 Update Shared Config for Local/Production Detection

**File:** `agents/shared/config.py`

Add support for `.env.local` and endpoint URL detection:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RECRUITMENT_",
        env_file=[".env.local", ".env"],  # Try .env.local first
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # ... existing fields ...
    
    # Add endpoint URLs for local development
    eventbridge_endpoint_url: str | None = Field(
        default=None,
        description="EventBridge endpoint URL (use 'mock' for local)",
    )
    
    ses_endpoint_url: str | None = Field(
        default=None,
        description="SES endpoint URL (use 'mock' for local)",
    )
    
    textract_endpoint_url: str | None = Field(
        default=None,
        description="Textract endpoint URL (use 'mock' for local)",
    )
    
    @property
    def is_local(self) -> bool:
        """Detect if running in local mode."""
        return (
            self.environment == "development"
            or self.dynamodb_endpoint_url == "mock"
            or self.eventbridge_endpoint_url == "mock"
        )
    
    @property
    def eventbridge_config(self) -> dict:
        """EventBridge client configuration."""
        config = {"region_name": self.aws_region}
        if self.eventbridge_endpoint_url and self.eventbridge_endpoint_url != "mock":
            config["endpoint_url"] = self.eventbridge_endpoint_url
        return config
    
    @property
    def ses_config(self) -> dict:
        """SES client configuration."""
        config = {"region_name": self.aws_region}
        if self.ses_endpoint_url and self.ses_endpoint_url != "mock":
            config["endpoint_url"] = self.ses_endpoint_url
        return config
    
    @property
    def textract_config(self) -> dict:
        """Textract client configuration."""
        config = {"region_name": self.aws_region}
        if self.textract_endpoint_url and self.textract_endpoint_url != "mock":
            config["endpoint_url"] = self.textract_endpoint_url
        return config
```

### 1.2 Update EventBridge Tools

**File:** `agents/shared/tools/eventbridge.py`

```python
def _get_client():
    """Get EventBridge client."""
    settings = get_settings()
    return boto3.client("events", **settings.eventbridge_config)
```

### 1.3 Update SES Tools

**File:** `agents/shared/tools/email.py` (if exists) or `agents/communication/tools.py`

Ensure SES client uses `settings.ses_config`:

```python
def _get_ses_client():
    """Get SES client."""
    settings = get_settings()
    return boto3.client("ses", **settings.ses_config)
```

### 1.4 Update Textract Tools

**File:** `agents/screening/tools.py`

Already uses `settings.textract_config` (line 308), but ensure it handles mock mode:

```python
def trigger_textract_async(...) -> TextractJobInfo:
    # ... existing code ...
    
    # In local mode, skip real Textract and emit DocumentProcessed immediately
    settings = get_settings()
    if settings.is_local:
        return _mock_textract_processing(document_s3_path, campaign_id, provider_id, document_type)
    
    # ... real Textract code ...
```

### 1.5 Create `.env.local` Template

**File:** `.env.local.example` (committed) and `.env.local` (gitignored)

```bash
# ============================================
# LOCAL DEVELOPMENT CONFIGURATION
# ============================================

# Environment
RECRUITMENT_ENVIRONMENT=development
RECRUITMENT_LOG_LEVEL=DEBUG

# AWS Mock Endpoints (use 'mock' to enable in-process routing)
RECRUITMENT_DYNAMODB_ENDPOINT_URL=mock
RECRUITMENT_S3_ENDPOINT_URL=mock
RECRUITMENT_EVENTBRIDGE_ENDPOINT_URL=mock
RECRUITMENT_SES_ENDPOINT_URL=mock
RECRUITMENT_TEXTRACT_ENDPOINT_URL=mock

# AWS Resources (local names)
RECRUITMENT_DYNAMODB_TABLE_NAME=RecruitmentSessions-local
RECRUITMENT_S3_BUCKET_NAME=recruitment-documents-local
RECRUITMENT_EVENTBRIDGE_BUS_NAME=recruitment-local

# AWS Region (for Bedrock)
RECRUITMENT_AWS_REGION=us-west-2

# ============================================
# BEDROCK CONFIGURATION (REAL AWS)
# ============================================
# Ensure AWS credentials are configured:
# - ~/.aws/credentials or
# - AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY env vars

RECRUITMENT_LLM_ENABLED=true
RECRUITMENT_USE_LLM_FOR_EMAIL=true
RECRUITMENT_USE_LLM_FOR_CLASSIFICATION=true
RECRUITMENT_USE_LLM_FOR_SCREENING=true
RECRUITMENT_USE_LLM_FOR_DOCUMENT_ANALYSIS=true
RECRUITMENT_BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
RECRUITMENT_BEDROCK_REGION=us-west-2

# ============================================
# OPTIONAL: Override Bedrock endpoint
# ============================================
# RECRUITMENT_BEDROCK_ENDPOINT_URL=https://bedrock-runtime.us-west-2.amazonaws.com
```

---

## Phase 2: Local Event Orchestration

### 2.1 Create Local Event Router

**File:** `scripts/local_event_router.py`

```python
"""
Local Event Router

Routes events in-process instead of using EventBridge.
Used for local development and testing.
"""

import json
from datetime import datetime, timezone
from typing import Any

import structlog

from agents.campaign_planner.agent import handle_new_campaign_requested
from agents.communication.agent import handle_send_message_requested
from agents.screening.agent import (
    handle_provider_response_received,
    handle_document_processed,
)
from agents.shared.models.events import (
    BaseEvent,
    DocumentProcessedEvent,
    ReplyToProviderRequestedEvent,
    ScreeningCompletedEvent,
    SendMessageRequestedEvent,
)

log = structlog.get_logger()

# In-memory event queue for UI
event_queue: list[dict[str, Any]] = []


def local_event_router(detail_type: str, detail: dict[str, Any]) -> Any:
    """
    Route event to appropriate agent handler.
    
    Args:
        detail_type: EventBridge detail-type
        detail: Event detail payload
        
    Returns:
        Handler result or None
    """
    handlers = {
        "NewCampaignRequested": handle_new_campaign_requested,
        "SendMessageRequested": handle_send_message_requested,
        "ProviderResponseReceived": handle_provider_response_received,
        "DocumentProcessed": handle_document_processed,
        "ReplyToProviderRequested": handle_send_message_requested,  # Same handler
        "FollowUpTriggered": handle_send_message_requested,  # Same handler
    }
    
    handler = handlers.get(detail_type)
    if not handler:
        log.warning("no_handler_for_event", detail_type=detail_type)
        return None
    
    # Log event to queue for UI
    event_queue.append({
        "type": detail_type,
        "detail": detail,
        "campaign_id": detail.get("campaign_id"),
        "provider_id": detail.get("provider_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    
    log.info("routing_event", detail_type=detail_type, campaign_id=detail.get("campaign_id"))
    
    try:
        result = handler(detail_type, detail)
        log.info("event_handled", detail_type=detail_type, success=True)
        
        # Handle ScreeningCompleted → trigger confirmation email
        if detail_type == "ScreeningCompleted":
            decision = detail.get("decision")
            if decision == "QUALIFIED":
                _trigger_qualified_confirmation(detail)
        
        return result
    except Exception as e:
        log.error("event_handler_failed", detail_type=detail_type, error=str(e), exc_info=True)
        raise


def _trigger_qualified_confirmation(screening_detail: dict[str, Any]) -> None:
    """Trigger confirmation email after qualification."""
    campaign_id = screening_detail["campaign_id"]
    provider_id = screening_detail["provider_id"]
    
    # Load provider state to get email
    from agents.shared.tools.dynamodb import load_provider_state
    provider_state = load_provider_state(campaign_id, provider_id)
    
    if not provider_state:
        log.warning("provider_state_not_found_for_confirmation", campaign_id=campaign_id, provider_id=provider_id)
        return
    
    # Emit SendMessageRequested for confirmation
    confirmation_event = SendMessageRequestedEvent(
        campaign_id=campaign_id,
        provider_id=provider_id,
        provider_email=provider_state.provider_email,
        provider_name=provider_state.provider_name,
        provider_market=provider_state.provider_market,
        message_type="qualified_confirmation",
        template_data=None,
    )
    
    local_event_router("SendMessageRequested", confirmation_event.to_eventbridge_detail())


def patch_eventbridge():
    """
    Monkey-patch EventBridge tools to route locally.
    
    Call this before importing agents to ensure all event emissions
    are routed through local_event_router.
    """
    from agents.shared.tools import eventbridge as eb_module
    
    original_send_event = eb_module.send_event
    original_send_events_batch = eb_module.send_events_batch
    
    def patched_send_event(event: BaseEvent, **kwargs) -> str:
        """Patched send_event that routes locally."""
        detail_type = event.__class__.detail_type()
        detail = event.to_eventbridge_detail()
        local_event_router(detail_type, detail)
        return f"local-event-{detail_type}-{detail.get('campaign_id', 'unknown')}"
    
    def patched_send_events_batch(events: list[BaseEvent], **kwargs) -> list[str]:
        """Patched send_events_batch that routes locally."""
        event_ids = []
        for event in events:
            detail_type = event.__class__.detail_type()
            detail = event.to_eventbridge_detail()
            local_event_router(detail_type, detail)
            event_ids.append(f"local-event-{detail_type}-{detail.get('campaign_id', 'unknown')}")
        return event_ids
    
    eb_module.send_event = patched_send_event
    eb_module.send_events_batch = patched_send_events_batch
    
    log.info("eventbridge_patched_for_local_mode")


def get_event_queue() -> list[dict[str, Any]]:
    """Get current event queue (for API endpoints)."""
    return event_queue.copy()


def clear_event_queue() -> None:
    """Clear event queue (for testing)."""
    event_queue.clear()
```

### 2.2 Create Textract Mock

**File:** `scripts/local_textract_mock.py`

```python
"""
Local Textract Mock

Simulates Textract document processing by immediately emitting
DocumentProcessed events with fixture data.
"""

import json
from datetime import date, datetime, timezone
from typing import Any

import structlog

from agents.shared.models.events import DocumentProcessedEvent, DocumentType, ExtractedFields

log = structlog.get_logger()


def mock_textract_processing(
    document_s3_path: str,
    campaign_id: str,
    provider_id: str,
    document_type: str | None = None,
) -> dict[str, Any]:
    """
    Mock Textract processing by emitting DocumentProcessed immediately.
    
    Uses fixture data from tests/fixtures/demo/documents/insurance_documents.json
    or generates realistic mock data.
    
    Returns:
        DocumentProcessed event detail dict
    """
    # Try to load fixture data
    fixture_data = _load_fixture_data(document_s3_path, document_type)
    
    if fixture_data:
        extracted_fields = ExtractedFields(**fixture_data.get("extracted_fields", {}))
        document_type_enum = DocumentType(fixture_data.get("document_type", "insurance_certificate"))
    else:
        # Generate mock data
        extracted_fields = ExtractedFields(
            expiry_date=date(2027, 1, 14),
            coverage_amount=2_000_000,
            policy_holder="Provider Name",
            policy_number="POL-12345",
            insurance_company="Mock Insurance Co",
        )
        document_type_enum = DocumentType(document_type or "insurance_certificate")
    
    event_detail = DocumentProcessedEvent(
        campaign_id=campaign_id,
        provider_id=provider_id,
        document_s3_path=document_s3_path,
        document_type=document_type_enum,
        job_id=f"mock-textract-{campaign_id}-{provider_id}",
        ocr_text=_generate_mock_ocr_text(document_type_enum),
        extracted_fields=extracted_fields,
        confidence_scores={
            "expiry_date": 0.95,
            "coverage_amount": 0.92,
            "policy_holder": 0.88,
            "policy_number": 0.90,
        },
    )
    
    log.info(
        "mock_textract_completed",
        campaign_id=campaign_id,
        provider_id=provider_id,
        document_type=document_type_enum.value,
    )
    
    return event_detail.to_eventbridge_detail()


def _load_fixture_data(document_s3_path: str, document_type: str | None) -> dict[str, Any] | None:
    """Load fixture data if available."""
    try:
        from pathlib import Path
        fixture_path = Path(__file__).parent.parent / "tests" / "fixtures" / "demo" / "documents" / "insurance_documents.json"
        if fixture_path.exists():
            with open(fixture_path) as f:
                fixtures = json.load(f)
                # Return first matching fixture or first fixture
                return fixtures[0] if fixtures else None
    except Exception as e:
        log.debug("fixture_load_failed", error=str(e))
    return None


def _generate_mock_ocr_text(document_type: DocumentType) -> str:
    """Generate mock OCR text based on document type."""
    if document_type == DocumentType.INSURANCE_CERTIFICATE:
        return """
        CERTIFICATE OF INSURANCE
        Policy Number: POL-12345
        Insured: Provider Name
        Coverage Amount: $2,000,000
        Expiration Date: January 14, 2027
        Insurance Company: Mock Insurance Co
        """
    return "Mock OCR text content"


def patch_textract_tools():
    """
    Patch Textract tools to use mock processing.
    
    Call this before importing screening agent.
    """
    from agents.screening import tools as screening_tools
    
    original_trigger = screening_tools.trigger_textract_async
    
    def patched_trigger_textract_async(
        document_s3_path: str,
        campaign_id: str,
        provider_id: str,
        document_type: str | None = None,
    ):
        """Patched trigger that immediately processes documents."""
        from scripts.local_event_router import local_event_router
        
        # Emit DocumentProcessed immediately
        event_detail = mock_textract_processing(document_s3_path, campaign_id, provider_id, document_type)
        local_event_router("DocumentProcessed", event_detail)
        
        # Return mock job info
        from agents.screening.tools import TextractJobInfo
        return TextractJobInfo(
            job_id=f"mock-{campaign_id}-{provider_id}",
            document_s3_path=document_s3_path,
            document_type=document_type,
            campaign_id=campaign_id,
            provider_id=provider_id,
            started_at=int(datetime.now(timezone.utc).timestamp()),
        )
    
    screening_tools.trigger_textract_async = patched_trigger_textract_async
    log.info("textract_tools_patched_for_local_mode")
```

---

## Phase 3: FastAPI Backend Server

### 3.1 Create FastAPI Server

**File:** `scripts/local_api_server.py`

```python
"""
FastAPI Backend Server for Local Development

Provides REST API endpoints for the Next.js campaign dashboard.
Routes events in-process and serves real-time event streams.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from moto import mock_dynamodb, mock_s3, mock_ses, mock_events

from agents.shared.config import get_settings
from agents.shared.models.events import NewCampaignRequestedEvent, ProviderResponseReceivedEvent
from agents.shared.tools.dynamodb import setup_dynamodb_table
from agents.shared.tools.s3 import setup_s3_bucket
from scripts.local_event_router import (
    clear_event_queue,
    get_event_queue,
    local_event_router,
    patch_eventbridge,
)
from scripts.local_textract_mock import patch_textract_tools

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()

# Apply mocks
mock_dynamodb().start()
mock_s3().start()
mock_ses().start()
mock_events().start()

# Set environment for local mode
os.environ["RECRUITMENT_DYNAMODB_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_S3_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_EVENTBRIDGE_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_SES_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_TEXTRACT_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_ENVIRONMENT"] = "development"

# Patch event routing BEFORE importing agents
patch_eventbridge()
patch_textract_tools()

# Now import agents (they'll use patched functions)
from agents.shared.tools.dynamodb import load_provider_state, query_providers_by_campaign


def setup_dynamodb_table():
    """Create DynamoDB table for local development."""
    import boto3
    settings = get_settings()
    dynamodb = boto3.resource("dynamodb", **settings.dynamodb_config)
    
    try:
        table = dynamodb.create_table(
            TableName=settings.dynamodb_table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": settings.dynamodb_gsi1_name,
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                    "ProvisionedThroughput": {
                        "ReadCapacityUnits": 5,
                        "WriteCapacityUnits": 5,
                    },
                }
            ],
            ProvisionedThroughput={
                "ReadCapacityUnits": 5,
                "WriteCapacityUnits": 5,
            },
        )
        table.meta.client.get_waiter("table_exists").wait(TableName=settings.dynamodb_table_name)
        log.info("dynamodb_table_created", table_name=settings.dynamodb_table_name)
    except Exception as e:
        if "ResourceInUseException" not in str(e):
            log.warning("dynamodb_table_exists_or_error", error=str(e))


def setup_s3_bucket():
    """Create S3 bucket for local development."""
    import boto3
    settings = get_settings()
    s3 = boto3.client("s3", **settings.s3_config)
    
    try:
        s3.create_bucket(
            Bucket=settings.s3_bucket_name,
            CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
        )
        log.info("s3_bucket_created", bucket_name=settings.s3_bucket_name)
    except Exception as e:
        if "BucketAlreadyOwnedByYou" not in str(e) and "BucketAlreadyExists" not in str(e):
            log.warning("s3_bucket_exists_or_error", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Setup local AWS resources
    setup_dynamodb_table()
    setup_s3_bucket()
    log.info("local_aws_resources_initialized")
    yield
    log.info("shutting_down")


app = FastAPI(title="Recruitment Automation API", lifespan=lifespan)

# CORS configuration
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if os.environ.get("CORS_ORIGINS"):
    origins.extend(o.strip() for o in os.environ["CORS_ORIGINS"].split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "environment": "local"}


@app.post("/api/campaigns")
async def create_campaign(campaign_data: dict[str, Any]):
    """
    Create a new campaign.
    
    Request body:
    {
        "buyer_id": "buyer-001",
        "requirements": {
            "type": "satellite_upgrade",
            "markets": ["atlanta", "chicago"],
            "providers_per_market": 5,
            "equipment": {"required": ["bucket_truck", "spectrum_analyzer"]},
            "documents": {"required": ["insurance_certificate"], "insurance_min_coverage": 2000000}
        }
    }
    """
    try:
        event = NewCampaignRequestedEvent(
            campaign_id=f"{campaign_data['requirements']['type']}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            buyer_id=campaign_data["buyer_id"],
            requirements=campaign_data["requirements"],
        )
        
        local_event_router("NewCampaignRequested", event.to_eventbridge_detail())
        
        return {
            "campaign_id": event.campaign_id,
            "status": "created",
        }
    except Exception as e:
        log.error("campaign_creation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    """Get campaign details with provider status breakdown."""
    try:
        providers = query_providers_by_campaign(campaign_id)
        
        status_counts = {}
        for provider in providers:
            status = provider.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "campaign_id": campaign_id,
            "providers": [
                {
                    "provider_id": p.provider_id,
                    "name": p.provider_name,
                    "email": p.provider_email,
                    "market": p.provider_market,
                    "status": p.status,
                }
                for p in providers
            ],
            "status_breakdown": status_counts,
            "total_providers": len(providers),
        }
    except Exception as e:
        log.error("campaign_fetch_failed", campaign_id=campaign_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/campaigns/{campaign_id}/providers/{provider_id}/journey")
async def get_provider_journey(campaign_id: str, provider_id: str):
    """Get provider journey timeline."""
    try:
        provider = load_provider_state(campaign_id, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        
        # Filter events for this provider
        events = [
            e for e in get_event_queue()
            if e.get("campaign_id") == campaign_id and e.get("provider_id") == provider_id
        ]
        events.sort(key=lambda x: x["timestamp"])
        
        # Build journey timeline
        journey = []
        for event in events:
            journey.append({
                "phase": _map_event_to_phase(event["type"]),
                "timestamp": event["timestamp"],
                "label": _get_event_label(event),
                "detail": event["detail"],
            })
        
        return {
            "provider_id": provider_id,
            "name": provider.provider_name,
            "email": provider.provider_email,
            "market": provider.provider_market,
            "status": provider.status,
            "journey": journey,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("journey_fetch_failed", campaign_id=campaign_id, provider_id=provider_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/simulate/provider-response")
async def simulate_provider_response(response_data: dict[str, Any]):
    """
    Simulate a provider response email.
    
    Request body:
    {
        "campaign_id": "satellite-upgrade-202602111200",
        "provider_id": "prov-atl-001",
        "email_body": "Yes, I'm interested! I have bucket truck...",
        "has_attachment": true,
        "attachment_filename": "insurance.pdf"
    }
    """
    try:
        import time
        
        event = ProviderResponseReceivedEvent(
            campaign_id=response_data["campaign_id"],
            provider_id=response_data["provider_id"],
            body=response_data["email_body"],
            attachments=[
                {
                    "filename": response_data.get("attachment_filename", "document.pdf"),
                    "s3_path": f"s3://recruitment-documents-local/documents/{response_data['campaign_id']}/{response_data['provider_id']}/{response_data.get('attachment_filename', 'document.pdf')}",
                    "content_type": "application/pdf",
                    "size_bytes": 50000,
                }
            ] if response_data.get("has_attachment") else [],
            received_at=int(time.time()),
            email_thread_id=f"{response_data['campaign_id']}#{response_data['provider_id']}",
            from_address="provider@example.com",
            subject="Re: Satellite Upgrade Opportunity",
        )
        
        local_event_router("ProviderResponseReceived", event.to_eventbridge_detail())
        
        return {"status": "simulated", "event_type": "ProviderResponseReceived"}
    except Exception as e:
        log.error("simulation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events")
async def get_events(
    campaign_id: str | None = Query(None),
    provider_id: str | None = Query(None),
):
    """Get filtered events."""
    events = get_event_queue()
    
    if campaign_id:
        events = [e for e in events if e.get("campaign_id") == campaign_id]
    if provider_id:
        events = [e for e in events if e.get("provider_id") == provider_id]
    
    return {"events": events, "count": len(events)}


@app.get("/api/events/stream")
async def stream_events():
    """Server-Sent Events stream for real-time updates."""
    import asyncio
    import json
    
    async def event_generator():
        last_count = 0
        while True:
            current_events = get_event_queue()
            if len(current_events) > last_count:
                # Send new events
                for event in current_events[last_count:]:
                    yield f"data: {json.dumps(event)}\n\n"
                last_count = len(current_events)
            await asyncio.sleep(0.5)  # Poll every 500ms
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _map_event_to_phase(event_type: str) -> str:
    """Map event type to journey phase."""
    mapping = {
        "NewCampaignRequested": "invited",
        "SendMessageRequested": "email_sent",
        "ProviderResponseReceived": "response_received",
        "DocumentProcessed": "document_processed",
        "ScreeningCompleted": "qualified",  # or "rejected"
        "ReplyToProviderRequested": "reply_sent",
    }
    return mapping.get(event_type, "unknown")


def _get_event_label(event: dict[str, Any]) -> str:
    """Generate human-readable label for event."""
    event_type = event["type"]
    detail = event["detail"]
    
    if event_type == "SendMessageRequested":
        return f"Email sent: {detail.get('message_type', 'unknown')}"
    elif event_type == "ProviderResponseReceived":
        return "Response received"
    elif event_type == "DocumentProcessed":
        return f"Document processed: {detail.get('document_type', 'unknown')}"
    elif event_type == "ScreeningCompleted":
        return f"Screening completed: {detail.get('decision', 'unknown')}"
    
    return event_type


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## Phase 4: Next.js Campaign Dashboard

### 4.1 Project Setup

```bash
cd /path/to/netdev-ai-poc-email-driven
npx create-next-app@latest campaign-ui --typescript --tailwind --app --no-src-dir --import-alias "@/*"
cd campaign-ui
npx shadcn@latest init  # For professional UI components
```

### 4.2 Project Structure

```
campaign-ui/
├── app/
│   ├── page.tsx                    # Landing: campaign list + create
│   ├── campaigns/
│   │   └── [id]/
│   │       └── page.tsx            # Campaign dashboard
│   ├── layout.tsx
│   └── globals.css
├── components/
│   ├── CampaignForm.tsx            # Create campaign form
│   ├── CampaignCard.tsx            # Campaign summary card
│   ├── ProviderJourneyCard.tsx     # Provider card with journey timeline
│   ├── EventStream.tsx             # Live events (SSE)
│   ├── SimulateResponseModal.tsx   # Provider response simulator
│   └── ui/                         # shadcn components
├── lib/
│   ├── api.ts                      # API client
│   └── types.ts                    # TypeScript types
├── hooks/
│   ├── useEventStream.ts           # SSE hook
│   └── useCampaign.ts              # Campaign data fetching
└── .env.local                      # NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 4.3 API Client

**File:** `campaign-ui/lib/api.ts`

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface CreateCampaignInput {
  buyer_id: string;
  requirements: {
    type: string;
    markets: string[];
    providers_per_market: number;
    equipment: { required: string[]; optional?: string[] };
    documents: { required: string[]; insurance_min_coverage?: number };
    certifications?: { required: string[]; preferred?: string[] };
    travel_required?: boolean;
  };
}

export interface Campaign {
  campaign_id: string;
  providers: Provider[];
  status_breakdown: Record<string, number>;
  total_providers: number;
}

export interface Provider {
  provider_id: string;
  name: string;
  email: string;
  market: string;
  status: string;
}

export interface ProviderJourney {
  provider_id: string;
  name: string;
  email: string;
  market: string;
  status: string;
  journey: JourneyStep[];
}

export interface JourneyStep {
  phase: string;
  timestamp: string;
  label: string;
  detail: any;
}

export async function createCampaign(data: CreateCampaignInput): Promise<{ campaign_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/api/campaigns`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Failed to create campaign');
  return res.json();
}

export async function getCampaign(id: string): Promise<Campaign> {
  const res = await fetch(`${API_BASE}/api/campaigns/${id}`);
  if (!res.ok) throw new Error('Failed to fetch campaign');
  return res.json();
}

export async function getProviderJourney(campaignId: string, providerId: string): Promise<ProviderJourney> {
  const res = await fetch(`${API_BASE}/api/campaigns/${campaignId}/providers/${providerId}/journey`);
  if (!res.ok) throw new Error('Failed to fetch journey');
  return res.json();
}

export async function simulateProviderResponse(data: {
  campaign_id: string;
  provider_id: string;
  email_body: string;
  has_attachment?: boolean;
  attachment_filename?: string;
}): Promise<{ status: string; event_type: string }> {
  const res = await fetch(`${API_BASE}/api/simulate/provider-response`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Failed to simulate response');
  return res.json();
}

export function getEventStreamUrl(): string {
  return `${API_BASE}/api/events/stream`;
}
```

### 4.4 Key UI Components

**Provider Journey Card** (`components/ProviderJourneyCard.tsx`):
- Shows provider status badge
- Displays vertical timeline of journey phases
- Color-coded phases (invited → email sent → response → screening → qualified/rejected)
- Expandable details for each phase
- "Simulate Response" button for WAITING_RESPONSE providers

**Event Stream** (`components/EventStream.tsx`):
- Real-time SSE connection
- Scrollable list of events
- Filter by campaign/provider
- Pause/resume functionality

**Campaign Dashboard** (`app/campaigns/[id]/page.tsx`):
- Status metrics cards (INVITED, WAITING_RESPONSE, QUALIFIED, etc.)
- Grid of provider journey cards
- Live event stream panel
- Refresh button

---

## Phase 5: Production Deployment Readiness

### 5.1 Environment Configuration

**Local (.env.local):**
```bash
RECRUITMENT_ENVIRONMENT=development
RECRUITMENT_DYNAMODB_ENDPOINT_URL=mock
# ... other mocks ...
```

**Production (Lambda environment variables):**
```bash
RECRUITMENT_ENVIRONMENT=production
# No endpoint URLs = use real AWS services
RECRUITMENT_DYNAMODB_TABLE_NAME=RecruitmentSessions-prod
RECRUITMENT_S3_BUCKET_NAME=recruitment-documents-prod
RECRUITMENT_EVENTBRIDGE_BUS_NAME=recruitment-prod
# Bedrock uses default AWS credentials
```

### 5.2 Lambda Deployment

All Lambda handlers in `lambdas/` are production-ready:
- `process_inbound_email/handler.py` — Handles SNS→SES notifications
- `textract_completion/handler.py` — Processes Textract completion notifications
- `send_follow_ups/handler.py` — Scheduled follow-up triggers

Agent handlers in `agents/` are called by Lambda wrappers in `lambda_deployment/`.

### 5.3 Deployment Checklist

- [ ] **DynamoDB Table:** Create with GSI1 index
- [ ] **S3 Bucket:** Create with lifecycle policies
- [ ] **EventBridge Bus:** Create custom bus with rules
- [ ] **SES Domain:** Verify domain and configure inbound rules
- [ ] **SNS Topics:** Create for SES and Textract notifications
- [ ] **Lambda Functions:** Deploy all handlers with proper IAM roles
- [ ] **API Gateway:** Create REST API (if using API Gateway instead of direct Lambda URLs)
- [ ] **Bedrock:** Ensure model access is granted
- [ ] **Environment Variables:** Set production values in Lambda configs
- [ ] **CloudWatch Logs:** Configure log groups and retention

---

## Phase 6: Implementation Checklist

### Configuration & Setup
- [ ] Update `agents/shared/config.py` with endpoint URL support
- [ ] Update `agents/shared/tools/eventbridge.py` to use config
- [ ] Update `agents/shared/tools/email.py` (SES) to use config
- [ ] Update `agents/screening/tools.py` to handle mock Textract
- [ ] Create `.env.local.example` template
- [ ] Create `.env.local` (gitignored) with local config

### Local Orchestration
- [ ] Create `scripts/local_event_router.py`
- [ ] Create `scripts/local_textract_mock.py`
- [ ] Test event routing with all event types
- [ ] Test Textract mock with fixture data

### FastAPI Backend
- [ ] Create `scripts/local_api_server.py`
- [ ] Add campaign creation endpoint
- [ ] Add campaign fetch endpoint
- [ ] Add provider journey endpoint
- [ ] Add event streaming (SSE)
- [ ] Add response simulation endpoint
- [ ] Test all endpoints

### Next.js Frontend
- [ ] Initialize Next.js project
- [ ] Install shadcn/ui components
- [ ] Create API client (`lib/api.ts`)
- [ ] Create types (`lib/types.ts`)
- [ ] Create CampaignForm component
- [ ] Create ProviderJourneyCard component
- [ ] Create EventStream component
- [ ] Create SimulateResponseModal component
- [ ] Create campaign dashboard page
- [ ] Create landing page
- [ ] Add real-time updates (SSE)
- [ ] Polish UI with loading states and error handling

### Testing & Validation
- [ ] Test full campaign flow locally
- [ ] Verify Bedrock calls are made (check AWS console)
- [ ] Verify mocks work correctly
- [ ] Test provider response simulation
- [ ] Test document processing flow
- [ ] Verify event queue and journey timeline
- [ ] Test error scenarios

### Documentation
- [ ] Update README with local setup instructions
- [ ] Document environment variables
- [ ] Create deployment guide
- [ ] Document API endpoints

---

## Quick Start Guide

### 1. Setup Environment

```bash
# Clone and install dependencies
cd netdev-ai-poc-email-driven

# Add FastAPI dependencies to pyproject.toml [project.optional-dependencies.dev]:
# "fastapi>=0.115.0",
# "uvicorn[standard]>=0.30.0",

pip install -e ".[dev]"

# Create .env.local from template
cp .env.example .env.local
# Edit .env.local with your Bedrock credentials

# Ensure AWS credentials are configured for Bedrock
aws configure  # Or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
```

### 2. Start Backend

```bash
# Terminal 1: FastAPI server
python scripts/local_api_server.py
# Server runs on http://localhost:8000
```

### 3. Start Frontend

```bash
# Terminal 2: Next.js app
cd campaign-ui
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
# App runs on http://localhost:3000
```

### 4. Create Campaign

1. Open http://localhost:3000
2. Fill out campaign form:
   - Campaign type: `satellite_upgrade`
   - Markets: `atlanta`, `chicago`
   - Providers per market: `5`
   - Required equipment: `bucket_truck`, `spectrum_analyzer`
   - Required documents: `insurance_certificate`
   - Minimum insurance: `2000000`
3. Click "Create Campaign"
4. View dashboard with provider cards
5. Click "Simulate Response" on any provider
6. Watch journey timeline update in real-time

---

## Production Deployment

### Deploy to AWS

1. **Infrastructure:** Use CDK/Terraform/CloudFormation to create:
   - DynamoDB table with GSI1
   - S3 bucket
   - EventBridge custom bus
   - SES verified domain
   - SNS topics
   - Lambda functions with proper IAM roles

2. **Lambda Deployment:**
   ```bash
   # Each lambda has a build script
   cd lambda_deployment/campaign_planner
   ./build_lambda.sh
   # Upload zip to Lambda function
   ```

3. **Environment Variables:** Set in Lambda configuration:
   - `RECRUITMENT_ENVIRONMENT=production`
   - `RECRUITMENT_DYNAMODB_TABLE_NAME=RecruitmentSessions-prod`
   - `RECRUITMENT_S3_BUCKET_NAME=recruitment-documents-prod`
   - `RECRUITMENT_EVENTBRIDGE_BUS_NAME=recruitment-prod`
   - (No endpoint URLs = use real AWS)

4. **Frontend Deployment:**
   ```bash
   cd campaign-ui
   echo "NEXT_PUBLIC_API_URL=https://api.yourdomain.com" > .env.production
   npm run build
   # Deploy to Vercel/Amplify/CloudFront
   ```

---

## Key Differences: Local vs Production

| Aspect | Local | Production |
|--------|-------|------------|
| **DynamoDB** | Moto mock (in-process) | Real DynamoDB |
| **S3** | Moto mock (in-process) | Real S3 |
| **EventBridge** | In-process routing | Real EventBridge |
| **SES** | Moto mock (logs only) | Real SES |
| **Textract** | Synchronous mock | Real Textract (async) |
| **Bedrock** | Real AWS API | Real AWS API |
| **Agents** | Direct function calls | Lambda invocations |
| **API** | FastAPI (localhost:8000) | API Gateway + Lambda |
| **Frontend** | Next.js dev server | Vercel/Amplify/CloudFront |

**Code Changes:** None. Only configuration differs.

---

## Success Criteria

✅ **Local Development:**
- Campaign creation works
- Providers are selected and invited
- Emails are "sent" (logged, not actually sent)
- Provider responses can be simulated
- Documents are processed (mocked Textract)
- Screening decisions are made (with real Bedrock)
- Journey timeline updates in real-time

✅ **Production Readiness:**
- Same codebase works with real AWS services
- No code changes needed for deployment
- Proper error handling and logging
- Idempotent operations
- Type-safe event handling

✅ **Demo Ready:**
- Professional UI with real-time updates
- Clear visualization of provider journey
- Interactive simulation capabilities
- Production-grade user experience

---

## Next Steps

1. **Implement Phase 1-3:** Configuration and backend
2. **Implement Phase 4:** Frontend dashboard
3. **Test locally:** Full end-to-end flow
4. **Prepare deployment:** Infrastructure as code
5. **Deploy to staging:** Test with real AWS services
6. **Demo to stakeholders:** Showcase the system
7. **Deploy to production:** Go live!

---

**Last Updated:** 2026-02-11  
**Status:** Ready for Implementation
