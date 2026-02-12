"""
FastAPI Backend Server for Local Development

Provides REST API endpoints for the Next.js campaign dashboard.
Routes events in-process and serves real-time event streams.
"""

import os
import re
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

# Set environment for local mode BEFORE any other imports
os.environ["RECRUITMENT_DYNAMODB_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_S3_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_EVENTBRIDGE_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_SES_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_TEXTRACT_ENDPOINT_URL"] = "mock"
os.environ["RECRUITMENT_ENVIRONMENT"] = "development"
os.environ["RECRUITMENT_DYNAMODB_TABLE_NAME"] = "RecruitmentSessions-local"
os.environ["RECRUITMENT_S3_BUCKET_NAME"] = "recruitment-documents-local"
os.environ["RECRUITMENT_EVENTBRIDGE_BUS_NAME"] = "recruitment-local"

# Configure moto to allow Bedrock calls to pass through to real AWS.
# This must be done BEFORE starting mock_aws.
from moto.core.config import default_user_config

default_user_config["core"]["passthrough"]["urls"] = [
    r"https?://bedrock-runtime\..*\.amazonaws\.com/.*",
    r"https?://bedrock\..*\.amazonaws\.com/.*",
]
# Do NOT let moto overwrite AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY with fake
# credentials; we need real credentials for Bedrock passthrough.
default_user_config["core"]["mock_credentials"] = False

from moto import mock_aws

mock = mock_aws()
mock.start()

import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()

# Clear settings caches so new env vars take effect
from agents.shared.config import get_settings
from agents.shared.llm.config import get_llm_settings

get_settings.cache_clear()
get_llm_settings.cache_clear()

# Patch event routing and textract BEFORE importing agents
from scripts.local_event_router import (
    clear_event_queue,
    get_event_queue,
    local_event_router,
    patch_eventbridge,
)
from scripts.local_textract_mock import patch_textract_tools

patch_eventbridge()
patch_textract_tools()

# Now import FastAPI and agent modules
import boto3
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional

from agents.shared.config import get_settings as _get_settings
from agents.shared.models.events import (
    NewCampaignRequestedEvent,
    ProviderResponseReceivedEvent,
    Requirements,
)
from agents.shared.tools.dynamodb import (
    create_campaign_record,
    list_all_campaigns,
    list_campaign_events,
    list_campaign_providers,
    load_campaign_record,
    load_provider_state,
    update_campaign_provider_count,
)
from agents.shared.tools.email_thread import (
    create_inbound_message,
    create_thread_id,
    get_thread,
    load_thread_history,
)
from agents.shared.models.email_thread import EmailAttachment
from agents.shared.llm.bedrock_client import get_llm_client
from agents.shared.llm.requirements_normalizer import normalize_campaign_requirements


def setup_local_dynamodb():
    """Create DynamoDB table for local development."""
    settings = _get_settings()
    dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)

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
                {"AttributeName": "last_contacted_at", "AttributeType": "N"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": settings.dynamodb_gsi1_name,
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "last_contacted_at", "KeyType": "RANGE"},
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
        table.meta.client.get_waiter("table_exists").wait(
            TableName=settings.dynamodb_table_name
        )
        log.info("dynamodb_table_created", table_name=settings.dynamodb_table_name)
    except Exception as e:
        if "ResourceInUseException" not in str(e):
            log.warning("dynamodb_table_setup_error", error=str(e))


def setup_local_s3():
    """Create S3 bucket for local development."""
    settings = _get_settings()
    s3 = boto3.client("s3", region_name=settings.aws_region)

    try:
        s3.create_bucket(
            Bucket=settings.s3_bucket_name,
            CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
        )
        log.info("s3_bucket_created", bucket_name=settings.s3_bucket_name)
    except Exception as e:
        if "BucketAlreadyOwnedByYou" not in str(e) and "BucketAlreadyExists" not in str(e):
            log.warning("s3_bucket_setup_error", error=str(e))


def setup_local_ses():
    """Verify SES email identity for local development."""
    settings = _get_settings()
    ses = boto3.client("ses", region_name=settings.aws_region)

    try:
        ses.verify_email_identity(EmailAddress=settings.ses_from_address)
        log.info("ses_identity_verified", email=settings.ses_from_address)
    except Exception as e:
        log.warning("ses_identity_setup_error", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    setup_local_dynamodb()
    setup_local_s3()
    setup_local_ses()
    log.info("local_aws_resources_initialized")
    yield
    log.info("shutting_down")


app = FastAPI(
    title="Recruitment Automation API",
    description="Local development server for recruitment automation",
    lifespan=lifespan,
)

# CORS configuration
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if os.environ.get("CORS_ORIGINS"):
    origins.extend(
        o.strip() for o in os.environ["CORS_ORIGINS"].split(",") if o.strip()
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================
# API Endpoints
# =====================================================


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "environment": "local", "version": "0.1.0"}


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
        reqs = campaign_data["requirements"]
        # Normalize equipment and document names to canonical IDs (handles typos)
        reqs = normalize_campaign_requirements(reqs)
        # Sanitize campaign type for campaign_id: only [a-zA-Z0-9-] allowed
        raw_type = (reqs.get("type") or "campaign").strip()
        slug = re.sub(r"[^a-zA-Z0-9-]+", "-", raw_type).strip("-") or "campaign"
        campaign_id = (
            f"{slug}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )

        # Save campaign record to DynamoDB FIRST
        create_campaign_record(
            campaign_id=campaign_id,
            buyer_id=campaign_data["buyer_id"],
            campaign_type=reqs["type"],
            requirements=reqs,
            markets=reqs.get("markets", []),
        )

        event = NewCampaignRequestedEvent(
            campaign_id=campaign_id,
            buyer_id=campaign_data["buyer_id"],
            requirements=Requirements(**reqs),
        )

        local_event_router("NewCampaignRequested", event.to_eventbridge_detail())

        # Update provider count after campaign planner runs
        providers = list_campaign_providers(campaign_id)
        if providers:
            update_campaign_provider_count(campaign_id, len(providers))

        return {
            "campaign_id": campaign_id,
            "status": "created",
        }
    except Exception as e:
        log.error("campaign_creation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/campaigns")
async def list_campaigns_endpoint():
    """List all campaigns with status summaries."""
    try:
        campaigns = list_all_campaigns()
        result = []
        for c in campaigns:
            # Get live provider breakdown
            providers = list_campaign_providers(c.campaign_id)
            status_counts: dict[str, int] = {}
            for p in providers:
                s = p.status.value
                status_counts[s] = status_counts.get(s, 0) + 1
            
            # Derive live status
            terminal = {"QUALIFIED", "REJECTED"}
            if providers and all(p.status.value in terminal for p in providers):
                live_status = "COMPLETED"
            elif c.status.value == "STOPPED":
                live_status = "STOPPED"
            else:
                live_status = "RUNNING"
            
            result.append({
                "campaign_id": c.campaign_id,
                "campaign_type": c.campaign_type,
                "buyer_id": c.buyer_id,
                "markets": c.markets,
                "status": live_status,
                "provider_count": len(providers),
                "status_breakdown": status_counts,
                "created_at": datetime.fromtimestamp(c.created_at, tz=timezone.utc).isoformat(),
            })
        return {"campaigns": result}
    except Exception as e:
        log.error("list_campaigns_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    """Get campaign details with provider status breakdown."""
    try:
        providers = list_campaign_providers(campaign_id)
        campaign = load_campaign_record(campaign_id)

        status_counts: dict[str, int] = {}
        for provider in providers:
            status = provider.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

        # Derive live status
        terminal = {"QUALIFIED", "REJECTED"}
        if providers and all(p.status.value in terminal for p in providers):
            live_status = "COMPLETED"
        elif campaign and campaign.status.value == "STOPPED":
            live_status = "STOPPED"
        else:
            live_status = "RUNNING"

        return {
            "campaign_id": campaign_id,
            "campaign_type": campaign.campaign_type if campaign else None,
            "buyer_id": campaign.buyer_id if campaign else None,
            "markets": campaign.markets if campaign else [],
            "requirements": campaign.requirements if campaign else {},
            "status": live_status,
            "providers": [
                {
                    "provider_id": p.provider_id,
                    "name": p.provider_name,
                    "email": p.provider_email,
                    "market": p.provider_market,
                    "status": p.status.value,
                    "equipment_confirmed": p.equipment_confirmed,
                    "documents_uploaded": p.documents_uploaded,
                    "screening_notes": p.screening_notes,
                }
                for p in providers
            ],
            "status_breakdown": status_counts,
            "total_providers": len(providers),
            "created_at": (
                datetime.fromtimestamp(campaign.created_at, tz=timezone.utc).isoformat()
                if campaign else None
            ),
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
            e
            for e in get_event_queue()
            if e.get("campaign_id") == campaign_id
            and e.get("provider_id") == provider_id
        ]
        events.sort(key=lambda x: x["timestamp"])

        # Build journey timeline
        journey = []
        for event in events:
            journey.append(
                {
                    "phase": _map_event_to_phase(event["type"]),
                    "event_type": event["type"],
                    "timestamp": event["timestamp"],
                    "label": _get_event_label(event),
                }
            )

        return {
            "provider_id": provider_id,
            "name": provider.provider_name,
            "email": provider.provider_email,
            "market": provider.provider_market,
            "status": provider.status.value,
            "journey": journey,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "journey_fetch_failed",
            campaign_id=campaign_id,
            provider_id=provider_id,
            error=str(e),
        )
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
        attachments = []
        if response_data.get("has_attachment"):
            filename = response_data.get("attachment_filename", "document.pdf")
            s3_path = (
                f"s3://recruitment-documents-local/documents/"
                f"{response_data['campaign_id']}/{response_data['provider_id']}/{filename}"
            )
            attachments.append(
                {
                    "filename": filename,
                    "s3_path": s3_path,
                    "content_type": "application/pdf",
                    "size_bytes": 50000,
                }
            )

            # Upload a dummy file to S3 so Textract mock can find it
            try:
                settings = _get_settings()
                s3 = boto3.client("s3", region_name=settings.aws_region)
                bucket = settings.s3_bucket_name
                key = s3_path.replace(f"s3://{bucket}/", "")
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=b"mock-document-content",
                    ContentType="application/pdf",
                )
            except Exception as upload_err:
                log.warning("mock_upload_failed", error=str(upload_err))

        campaign_id = response_data["campaign_id"]
        provider_id = response_data["provider_id"]

        # Save inbound message to email thread
        try:
            provider = load_provider_state(campaign_id, provider_id)
            market = provider.provider_market if provider else "unknown"
            thread_id = create_thread_id(campaign_id, market, provider_id)
            
            thread_attachments = [
                EmailAttachment(
                    filename=a["filename"],
                    s3_path=a["s3_path"],
                    content_type=a["content_type"],
                    size_bytes=a["size_bytes"],
                )
                for a in attachments
            ]
            
            create_inbound_message(
                thread_id=thread_id,
                subject="Re: Recruitment Opportunity",
                body_text=response_data["email_body"],
                message_id=f"sim-{int(time.time())}",
                email_from="provider@example.com",
                email_to=_get_settings().ses_from_address,
                attachments=thread_attachments,
                metadata={"simulated": True},
            )
        except Exception as thread_err:
            log.warning("inbound_thread_save_failed", error=str(thread_err))

        event = ProviderResponseReceivedEvent(
            campaign_id=campaign_id,
            provider_id=provider_id,
            body=response_data["email_body"],
            attachments=attachments,
            received_at=int(time.time()),
            email_thread_id=f"{campaign_id}#{provider_id}",
            from_address="provider@example.com",
            subject="Re: Recruitment Opportunity",
        )

        local_event_router(
            "ProviderResponseReceived", event.to_eventbridge_detail()
        )

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


@app.get("/api/campaigns/{campaign_id}/providers/{provider_id}/conversation")
async def get_provider_conversation(campaign_id: str, provider_id: str):
    """Get email conversation history for a provider (chat-style thread)."""
    try:
        provider = load_provider_state(campaign_id, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        market = provider.provider_market or "unknown"
        thread_id = create_thread_id(campaign_id, market, provider_id)
        messages = load_thread_history(thread_id)

        return {
            "thread_id": thread_id,
            "provider_id": provider_id,
            "provider_name": provider.provider_name,
            "message_count": len(messages),
            "messages": [
                {
                    "direction": m.direction.value,
                    "message_type": m.message_type,
                    "subject": m.subject,
                    "body_text": m.body_text,
                    "timestamp": datetime.fromtimestamp(m.timestamp, tz=timezone.utc).isoformat(),
                    "email_from": m.email_from,
                    "email_to": m.email_to,
                    "attachments": [
                        {"filename": a.filename, "content_type": a.content_type}
                        for a in m.attachments
                    ],
                    "metadata": m.metadata,
                }
                for m in messages
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("conversation_fetch_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


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
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                last_count = len(current_events)
            await asyncio.sleep(0.5)  # Poll every 500ms

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# =====================================================
# Campaign Chat Assistant Models
# =====================================================


class ChatMessage(BaseModel):
    """A single chat message in the conversation."""
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class CampaignFormData(BaseModel):
    """Current form data state."""
    campaignType: Optional[str] = None
    markets: Optional[str] = None  # Comma-separated string
    providersPerMarket: Optional[int] = None
    requiredEquipment: Optional[str] = None  # Comma-separated string
    requiredDocuments: Optional[str] = None  # Comma-separated string
    insuranceMinCoverage: Optional[int] = None
    travelRequired: Optional[bool] = None
    buyer_id: Optional[str] = None


class CampaignChatRequest(BaseModel):
    """Request for campaign chat assistant."""
    message: str = Field(..., description="User's message")
    conversation_history: list[ChatMessage] = Field(default_factory=list, description="Previous conversation messages")
    current_form_data: Optional[CampaignFormData] = Field(None, description="Current form state")


class ExtractedFields(BaseModel):
    """Fields extracted from the conversation."""
    campaignType: Optional[str] = None
    markets: Optional[list[str]] = None
    providersPerMarket: Optional[int] = None
    requiredEquipment: Optional[list[str]] = None
    requiredDocuments: Optional[list[str]] = None
    insuranceMinCoverage: Optional[int] = None
    travelRequired: Optional[bool] = None
    buyer_id: Optional[str] = None


class CampaignChatResponse(BaseModel):
    """Response from campaign chat assistant."""
    message: str = Field(..., description="Assistant's response message")
    extracted_fields: ExtractedFields = Field(..., description="Fields extracted from conversation")
    missing_fields: list[str] = Field(default_factory=list, description="List of missing required fields")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score for extraction")
    is_complete: bool = Field(..., description="Whether all required fields are present")


class CampaignChatStreamChunk(BaseModel):
    """A single chunk in the streaming response."""
    type: str = Field(..., description="Chunk type: 'message', 'fields', 'complete'")
    content: str = Field(default="", description="Content for message chunks")
    extracted_fields: Optional[ExtractedFields] = None
    is_complete: Optional[bool] = None


# =====================================================
# Campaign Chat Assistant Endpoint
# =====================================================


@app.post("/api/campaigns/chat")
async def chat_campaign_assistant(request: CampaignChatRequest):
    """
    Chat endpoint for LLM-powered campaign form assistance.
    
    Uses Bedrock LLM to extract campaign requirements from natural conversation
    and provides structured feedback on missing fields.
    
    Request body:
    {
        "message": "I want to create a campaign for satellite upgrades",
        "conversation_history": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! I can help you create a campaign..."}
        ],
        "current_form_data": {
            "campaignType": "satellite-upgrade",
            "markets": "atlanta, chicago"
        }
    }
    
    Response:
    {
        "message": "I've extracted the following information...",
        "extracted_fields": {...},
        "missing_fields": ["buyer_id", "requiredEquipment"],
        "confidence": 0.85,
        "is_complete": false
    }
    """
    try:
        from agents.shared.llm.bedrock_client import get_llm_client
        
        llm_client = get_llm_client()
        
        # Build conversation context
        conversation_text = ""
        for msg in request.conversation_history[-10:]:  # Last 10 messages for context
            role_label = "User" if msg.role == "user" else "Assistant"
            conversation_text += f"{role_label}: {msg.content}\n\n"
        conversation_text += f"User: {request.message}\n\n"
        
        # Build current form state context
        form_context = ""
        if request.current_form_data:
            form_data = request.current_form_data
            if form_data.campaignType:
                form_context += f"- Campaign Type: {form_data.campaignType}\n"
            if form_data.markets:
                form_context += f"- Markets: {form_data.markets}\n"
            if form_data.providersPerMarket:
                form_context += f"- Providers per Market: {form_data.providersPerMarket}\n"
            if form_data.requiredEquipment:
                form_context += f"- Required Equipment: {form_data.requiredEquipment}\n"
            if form_data.requiredDocuments:
                form_context += f"- Required Documents: {form_data.requiredDocuments}\n"
            if form_data.insuranceMinCoverage:
                form_context += f"- Insurance Min Coverage: ${form_data.insuranceMinCoverage:,}\n"
            if form_data.travelRequired is not None:
                form_context += f"- Travel Required: {form_data.travelRequired}\n"
            if form_data.buyer_id:
                form_context += f"- Buyer ID: {form_data.buyer_id}\n"
        
        # System prompt for the LLM
        system_prompt = """You are a helpful assistant for creating recruitment campaigns. 
Your goal is to extract campaign requirements from natural conversation and guide users to provide all necessary information.

REQUIRED fields for a campaign:
1. buyer_id (string) - REQUIRED: The buyer/company ID creating this campaign
2. campaignType (string) - Campaign type, e.g., "satellite-upgrade", "fiber-installation"
3. markets (array of strings) - Geographic markets, e.g., ["atlanta", "chicago"]
4. providersPerMarket (number, 1-20) - Number of providers needed per market
5. requiredEquipment (array of strings) - Equipment needed, e.g., ["bucket_truck", "spectrum_analyzer"]
6. requiredDocuments (array of strings) - Documents needed, e.g., ["insurance_certificate"]
7. insuranceMinCoverage (number) - Minimum insurance coverage in USD
8. travelRequired (boolean) - Whether travel is required

Instructions:
- Extract information from the user's message
- Be conversational and friendly
- If buyer_id is missing, politely ask for it (it's REQUIRED)
- Ask for missing fields one at a time, starting with the most important
- Validate extracted data (e.g., providersPerMarket should be 1-20)
- Return structured JSON with extracted fields and a friendly message
- If all required fields are present, confirm completion"""
        
        # Build the prompt
        prompt = f"""Conversation history:
{conversation_text}

Current form state:
{form_context if form_context else "No fields filled yet"}

Please extract campaign information from the user's latest message and respond with:
1. A friendly message acknowledging what you've extracted
2. Any missing REQUIRED fields (especially buyer_id if not provided)
3. Validation of the extracted data

Remember: buyer_id is REQUIRED - always ask for it if missing."""
        
        # Merge current form data into extracted fields (preserve existing data)
        merged_fields = ExtractedFields()
        if request.current_form_data:
            form_data = request.current_form_data
            if form_data.campaignType:
                merged_fields.campaignType = form_data.campaignType
            if form_data.markets:
                merged_fields.markets = [m.strip() for m in form_data.markets.split(",") if m.strip()]
            if form_data.providersPerMarket is not None:
                merged_fields.providersPerMarket = form_data.providersPerMarket
            if form_data.requiredEquipment:
                merged_fields.requiredEquipment = [e.strip() for e in form_data.requiredEquipment.split(",") if e.strip()]
            if form_data.requiredDocuments:
                merged_fields.requiredDocuments = [d.strip() for d in form_data.requiredDocuments.split(",") if d.strip()]
            if form_data.insuranceMinCoverage is not None:
                merged_fields.insuranceMinCoverage = form_data.insuranceMinCoverage
            if form_data.travelRequired is not None:
                merged_fields.travelRequired = form_data.travelRequired
            if form_data.buyer_id:
                merged_fields.buyer_id = form_data.buyer_id
        
        # Call LLM with structured output
        response = llm_client.invoke_structured(
            prompt=prompt,
            output_schema=CampaignChatResponse,
            system_prompt=system_prompt,
            temperature=0.3,
        )
        
        # Merge LLM extracted fields with existing form data (LLM values override if present)
        if response.extracted_fields.campaignType:
            merged_fields.campaignType = response.extracted_fields.campaignType
        if response.extracted_fields.markets:
            merged_fields.markets = response.extracted_fields.markets
        if response.extracted_fields.providersPerMarket is not None:
            merged_fields.providersPerMarket = response.extracted_fields.providersPerMarket
        if response.extracted_fields.requiredEquipment:
            merged_fields.requiredEquipment = response.extracted_fields.requiredEquipment
        if response.extracted_fields.requiredDocuments:
            merged_fields.requiredDocuments = response.extracted_fields.requiredDocuments
        if response.extracted_fields.insuranceMinCoverage is not None:
            merged_fields.insuranceMinCoverage = response.extracted_fields.insuranceMinCoverage
        if response.extracted_fields.travelRequired is not None:
            merged_fields.travelRequired = response.extracted_fields.travelRequired
        if response.extracted_fields.buyer_id:
            merged_fields.buyer_id = response.extracted_fields.buyer_id
        
        # Update response with merged fields
        response.extracted_fields = merged_fields
        
        # Determine missing fields
        missing = []
        if not merged_fields.buyer_id:
            missing.append("buyer_id")
        if not merged_fields.campaignType:
            missing.append("campaignType")
        if not merged_fields.markets:
            missing.append("markets")
        if merged_fields.providersPerMarket is None:
            missing.append("providersPerMarket")
        
        response.missing_fields = missing
        response.is_complete = len(missing) == 0
        
        return response
        
    except Exception as e:
        log.error("campaign_chat_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat assistant error: {str(e)}")


@app.post("/api/campaigns/chat/stream")
async def chat_campaign_assistant_stream(request: CampaignChatRequest):
    """
    Streaming version of the chat endpoint.
    
    Returns Server-Sent Events (SSE) stream with:
    - Message chunks as they're generated
    - Extracted fields when available
    - Completion status
    """
    import asyncio
    import json
    
    async def stream_generator():
        try:
            from agents.shared.llm.bedrock_client import get_llm_client
            
            llm_client = get_llm_client()
            
            # For now, we'll use non-streaming LLM call and simulate streaming
            # In the future, this can be enhanced with actual Bedrock streaming
            response = await chat_campaign_assistant(request)
            
            # Stream the message word by word (simulated)
            words = response.message.split()
            for i, word in enumerate(words):
                chunk = CampaignChatStreamChunk(
                    type="message",
                    content=word + (" " if i < len(words) - 1 else ""),
                )
                yield f"data: {chunk.model_dump_json()}\n\n"
                await asyncio.sleep(0.05)  # Small delay for streaming effect
            
            # Send extracted fields
            chunk = CampaignChatStreamChunk(
                type="fields",
                extracted_fields=response.extracted_fields,
            )
            yield f"data: {chunk.model_dump_json()}\n\n"
            
            # Send completion status
            chunk = CampaignChatStreamChunk(
                type="complete",
                is_complete=response.is_complete,
            )
            yield f"data: {chunk.model_dump_json()}\n\n"
            
        except Exception as e:
            log.error("campaign_chat_stream_failed", error=str(e), exc_info=True)
            error_chunk = CampaignChatStreamChunk(
                type="error",
                content=f"Error: {str(e)}",
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
    
    return StreamingResponse(stream_generator(), media_type="text/event-stream")


# =====================================================
# Helper Functions
# =====================================================


def _map_event_to_phase(event_type: str) -> str:
    """Map event type to journey phase."""
    mapping = {
        "NewCampaignRequested": "invited",
        "SendMessageRequested": "email_sent",
        "ProviderResponseReceived": "response_received",
        "DocumentProcessed": "document_processed",
        "ScreeningCompleted": "qualified",
        "ReplyToProviderRequested": "reply_sent",
        "FollowUpTriggered": "follow_up",
    }
    return mapping.get(event_type, "unknown")


def _get_event_label(event: dict[str, Any]) -> str:
    """Generate human-readable label for event."""
    event_type = event["type"]
    detail = event.get("detail", {})

    if event_type == "NewCampaignRequested":
        return "Campaign created"
    elif event_type == "SendMessageRequested":
        msg_type = detail.get("message_type", "unknown")
        return f"Email sent: {msg_type}"
    elif event_type == "ProviderResponseReceived":
        return "Response received"
    elif event_type == "DocumentProcessed":
        doc_type = detail.get("document_type", "unknown")
        return f"Document processed: {doc_type}"
    elif event_type == "ScreeningCompleted":
        decision = detail.get("decision", "unknown")
        return f"Screening: {decision}"
    elif event_type == "ReplyToProviderRequested":
        return "Reply requested"
    elif event_type == "FollowUpTriggered":
        return "Follow-up triggered"

    return event_type


if __name__ == "__main__":
    import uvicorn

    log.info("starting_local_api_server", host="0.0.0.0", port=8000)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
