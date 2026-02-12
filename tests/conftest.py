"""
Pytest Configuration and Shared Fixtures

Provides moto AWS mocking, sample events, and test utilities.
"""

import json
import os
from datetime import datetime
from typing import Any, Generator
from unittest.mock import patch
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
import pytest
from moto import mock_aws

# Set test environment before importing application modules
os.environ["RECRUITMENT_DYNAMODB_TABLE_NAME"] = "TestRecruitmentSessions"
os.environ["RECRUITMENT_S3_BUCKET_NAME"] = "test-recruitment-documents"
os.environ["RECRUITMENT_EVENTBRIDGE_BUS_NAME"] = "test-recruitment"
os.environ["RECRUITMENT_SES_FROM_ADDRESS"] = "test@example.com"
os.environ["RECRUITMENT_SES_REPLY_TO_DOMAIN"] = "test.example.com"
os.environ["RECRUITMENT_AWS_REGION"] = "us-west-2"
os.environ["AWS_DEFAULT_REGION"] = "us-west-2"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"


# --- Time Fixtures ---


@pytest.fixture
def frozen_time() -> int:
    """Fixed Unix timestamp for deterministic tests."""
    return 1738800000  # 2025-02-06 00:00:00 UTC


@pytest.fixture
def frozen_datetime(frozen_time: int) -> datetime:
    """Fixed datetime for deterministic tests."""
    return datetime.utcfromtimestamp(frozen_time)


# --- AWS Mocking Fixtures ---


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for moto."""
    return {
        "aws_access_key_id": "testing",
        "aws_secret_access_key": "testing",
        "region_name": "us-west-2",
    }


@pytest.fixture
def mock_dynamodb(aws_credentials):
    """
    Create a mocked DynamoDB table.
    
    Creates the RecruitmentSessions table with GSI1 per schema.
    """
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", **aws_credentials)
        
        # Create table matching contracts/dynamodb_schema.json
        try:
            table = dynamodb.create_table(
                TableName="TestRecruitmentSessions",
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                    {"AttributeName": "GSI1PK", "AttributeType": "S"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "GSI1",
                        "KeySchema": [
                            {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                            {"AttributeName": "SK", "KeyType": "RANGE"},
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
            
            # Wait for table to be created
            table.meta.client.get_waiter("table_exists").wait(
                TableName="TestRecruitmentSessions"
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceInUseException":
                raise
            table = dynamodb.Table("TestRecruitmentSessions")
            # Ensure clean state when the table already exists in the mock backend.
            scan_kwargs: dict[str, object] = {
                "ProjectionExpression": "PK, SK",
            }
            while True:
                response = table.scan(**scan_kwargs)
                items = response.get("Items", [])
                if items:
                    with table.batch_writer() as batch:
                        for item in items:
                            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                scan_kwargs["ExclusiveStartKey"] = last_key
        
        yield dynamodb


@pytest.fixture
def mock_s3(aws_credentials):
    """Create a mocked S3 bucket."""
    with mock_aws():
        s3 = boto3.client("s3", **aws_credentials)
        s3.create_bucket(Bucket="test-recruitment-documents")
        yield s3


@pytest.fixture
def mock_ses(aws_credentials):
    """Create a mocked SES client with verified identity."""
    with mock_aws():
        ses = boto3.client("ses", **aws_credentials)
        # Verify sender identity
        ses.verify_email_identity(EmailAddress="test@example.com")
        yield ses


@pytest.fixture
def mock_eventbridge(aws_credentials):
    """Create a mocked EventBridge client with bus."""
    with mock_aws():
        events = boto3.client("events", **aws_credentials)
        events.create_event_bus(Name="test-recruitment")
        yield events


@pytest.fixture
def mock_aws_all(aws_credentials):
    """
    Mock all AWS services used by the application.
    
    Provides a complete mocked AWS environment.
    """
    with mock_aws():
        # DynamoDB
        dynamodb = boto3.resource("dynamodb", **aws_credentials)
        dynamodb.create_table(
            TableName="TestRecruitmentSessions",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "SK", "KeyType": "RANGE"},
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
        
        # S3
        s3 = boto3.client("s3", **aws_credentials)
        s3.create_bucket(Bucket="test-recruitment-documents")
        
        # SES
        ses = boto3.client("ses", **aws_credentials)
        ses.verify_email_identity(EmailAddress="test@example.com")
        
        # EventBridge
        events = boto3.client("events", **aws_credentials)
        events.create_event_bus(Name="test-recruitment")
        
        yield {
            "dynamodb": dynamodb,
            "s3": s3,
            "ses": ses,
            "events": events,
        }


# --- ID Fixtures ---


@pytest.fixture
def campaign_id() -> str:
    """Sample campaign ID."""
    return "campaign-satellite-2025"


@pytest.fixture
def provider_id() -> str:
    """Sample provider ID."""
    return "prov-atl-001"


@pytest.fixture
def trace_id() -> str:
    """Valid 32-character hex trace ID."""
    return "a" * 32


@pytest.fixture
def span_id() -> str:
    """Valid 16-character hex span ID."""
    return "b" * 16


# --- Event Fixtures ---


@pytest.fixture
def trace_context(trace_id: str, span_id: str) -> dict[str, str]:
    """Sample trace context."""
    return {
        "trace_id": trace_id,
        "span_id": span_id,
    }


@pytest.fixture
def sample_requirements() -> dict[str, Any]:
    """Sample campaign requirements for satellite upgrade."""
    return {
        "type": "satellite_upgrade",
        "markets": ["atlanta", "chicago", "milwaukee"],
        "providers_per_market": 5,
        "equipment": {
            "required": ["bucket_truck", "spectrum_analyzer"],
            "optional": ["ladder"],
        },
        "documents": {
            "required": ["insurance_certificate"],
            "insurance_min_coverage": 2000000,
        },
        "certifications": {
            "required": [],
            "preferred": ["comptia_network_plus", "osha_10"],
        },
        "travel_required": True,
    }


@pytest.fixture
def new_campaign_event(
    campaign_id: str,
    trace_context: dict[str, str],
    sample_requirements: dict[str, Any],
) -> dict[str, Any]:
    """Sample NewCampaignRequested event."""
    return {
        "campaign_id": campaign_id,
        "buyer_id": "buyer-acme-corp",
        "requirements": sample_requirements,
        "trace_context": trace_context,
    }


@pytest.fixture
def send_message_event(
    campaign_id: str,
    provider_id: str,
    trace_context: dict[str, str],
) -> dict[str, Any]:
    """Sample SendMessageRequested event."""
    return {
        "campaign_id": campaign_id,
        "provider_id": provider_id,
        "provider_email": "john.smith@techservices.com",
        "message_type": "initial_outreach",
        "template_data": {
            "campaign_type": "Satellite Upgrade",
            "market": "Atlanta",
            "equipment_list": "bucket truck, spectrum analyzer",
            "insurance_requirement": "$2M liability coverage",
        },
        "trace_context": trace_context,
    }


@pytest.fixture
def provider_response_event(
    campaign_id: str,
    provider_id: str,
    trace_context: dict[str, str],
) -> dict[str, Any]:
    """Sample ProviderResponseReceived event."""
    return {
        "campaign_id": campaign_id,
        "provider_id": provider_id,
        "from_address": "john.smith@techservices.com",
        "subject": "Re: Opportunity: Satellite Upgrade technicians needed in Atlanta",
        "body": "I'm interested in this opportunity. I have a bucket truck and spectrum analyzer. I can travel if needed.",
        "received_at": 1738837800,  # Unix timestamp: 2025-02-06T10:30:00Z
        "email_thread_id": f"msg-{uuid4().hex[:12]}",
        "message_id": f"<{uuid4()}@mail.example.com>",
        "attachments": [],
        "trace_context": trace_context,
    }


@pytest.fixture
def provider_response_with_attachment(
    provider_response_event: dict[str, Any],
) -> dict[str, Any]:
    """Sample ProviderResponseReceived event with attachment."""
    event = provider_response_event.copy()
    event["attachments"] = [
        {
            "filename": "insurance_certificate.pdf",
            "s3_path": "s3://test-recruitment-documents/documents/campaign-satellite-2025/prov-atl-001/20250206_103000_insurance_certificate.pdf",
            "content_type": "application/pdf",
            "size_bytes": 125000,
        }
    ]
    return event


@pytest.fixture
def document_processed_event(
    campaign_id: str,
    provider_id: str,
    trace_context: dict[str, str],
) -> dict[str, Any]:
    """Sample DocumentProcessed event."""
    return {
        "campaign_id": campaign_id,
        "provider_id": provider_id,
        "document_type": "insurance_certificate",
        "s3_path": "s3://test-recruitment-documents/documents/campaign-satellite-2025/prov-atl-001/insurance.pdf",
        "extracted_fields": {
            "expiry_date": "2026-06-15",
            "coverage_amount": 2500000,
            "policy_holder": "John Smith",
            "policy_number": "POL-2025-12345",
            "insurance_company": "Liberty Mutual",
        },
        "confidence_scores": {
            "expiry_date": 0.95,
            "coverage_amount": 0.92,
            "policy_holder": 0.88,
        },
        "trace_context": trace_context,
    }


@pytest.fixture
def follow_up_event(
    campaign_id: str,
    provider_id: str,
    trace_context: dict[str, str],
) -> dict[str, Any]:
    """Sample FollowUpTriggered event."""
    return {
        "campaign_id": campaign_id,
        "provider_id": provider_id,
        "reason": "no_response",
        "days_since_contact": 3,
        "follow_up_number": 1,
        "trace_context": trace_context,
    }


# --- Provider State Fixtures ---


@pytest.fixture
def sample_provider_state(
    campaign_id: str,
    provider_id: str,
    frozen_time: int,
) -> dict[str, Any]:
    """Sample provider state as DynamoDB item."""
    return {
        "PK": f"SESSION#{campaign_id}",
        "SK": f"PROVIDER#{provider_id}",
        "campaign_id": campaign_id,
        "provider_id": provider_id,
        "status": "INVITED",
        "expected_next_event": "SendMessageRequested",
        "last_contacted_at": frozen_time,
        "provider_email": "john.smith@techservices.com",
        "provider_market": "atlanta",
        "provider_name": "John Smith",
        "version": 1,
        "GSI1PK": "INVITED#SendMessageRequested",
    }


@pytest.fixture
def waiting_response_state(sample_provider_state: dict[str, Any]) -> dict[str, Any]:
    """Provider state in WAITING_RESPONSE status."""
    state = sample_provider_state.copy()
    state["status"] = "WAITING_RESPONSE"
    state["expected_next_event"] = "ProviderResponseReceived"
    state["GSI1PK"] = "WAITING_RESPONSE#ProviderResponseReceived"
    state["email_thread_id"] = f"<{uuid4()}@mail.example.com>"
    return state


@pytest.fixture
def document_processing_state(sample_provider_state: dict[str, Any]) -> dict[str, Any]:
    """Provider state in DOCUMENT_PROCESSING status."""
    state = sample_provider_state.copy()
    state["status"] = "DOCUMENT_PROCESSING"
    state["expected_next_event"] = "DocumentProcessed"
    state["GSI1PK"] = "DOCUMENT_PROCESSING#DocumentProcessed"
    state["documents_uploaded"] = ["insurance_certificate"]
    state["artifacts"] = {
        "insurance_certificate.pdf": "s3://test-recruitment-documents/documents/campaign-satellite-2025/prov-atl-001/insurance.pdf"
    }
    return state


# --- Email Fixtures ---


@pytest.fixture
def sample_email_raw() -> str:
    """Raw MIME email for parsing tests."""
    return """From: John Smith <john.smith@techservices.com>
To: campaign+campaign-satellite-2025_provider+prov-atl-001@test.example.com
Subject: Re: Opportunity: Satellite Upgrade technicians needed in Atlanta
Date: Thu, 06 Feb 2025 10:30:00 -0500
Message-ID: <abc123@mail.techservices.com>
Content-Type: text/plain; charset="UTF-8"

Hi,

I'm interested in this opportunity. I have a bucket truck and spectrum analyzer.
I'm willing to travel if needed.

Best,
John Smith
"""


@pytest.fixture
def sample_sns_ses_event(sample_email_raw: str) -> dict[str, Any]:
    """Sample SNS event from SES for inbound email."""
    import base64
    
    return {
        "Records": [
            {
                "EventSource": "aws:sns",
                "EventVersion": "1.0",
                "Sns": {
                    "Type": "Notification",
                    "MessageId": str(uuid4()),
                    "TopicArn": "arn:aws:sns:us-west-2:123456789012:ses-inbound",
                    "Subject": "SES Notification",
                    "Message": json.dumps({
                        "notificationType": "Received",
                        "mail": {
                            "timestamp": "2025-02-06T15:30:00.000Z",
                            "source": "john.smith@techservices.com",
                            "messageId": "abc123",
                            "destination": [
                                "campaign+campaign-satellite-2025_provider+prov-atl-001@test.example.com"
                            ],
                            "headersTruncated": False,
                            "headers": [],
                            "commonHeaders": {
                                "from": ["John Smith <john.smith@techservices.com>"],
                                "to": ["campaign+campaign-satellite-2025_provider+prov-atl-001@test.example.com"],
                                "subject": "Re: Opportunity: Satellite Upgrade",
                            },
                        },
                        "receipt": {
                            "timestamp": "2025-02-06T15:30:00.000Z",
                            "processingTimeMillis": 500,
                            "recipients": [
                                "campaign+campaign-satellite-2025_provider+prov-atl-001@test.example.com"
                            ],
                            "action": {
                                "type": "SNS",
                                "topicArn": "arn:aws:sns:us-west-2:123456789012:ses-inbound",
                            },
                        },
                        "content": base64.b64encode(sample_email_raw.encode()).decode(),
                    }),
                    "Timestamp": "2025-02-06T15:30:01.000Z",
                },
            }
        ]
    }


# --- Provider Info Fixtures ---


@pytest.fixture
def sample_provider_info() -> dict[str, Any]:
    """Sample provider info for Campaign Planner tests."""
    return {
        "provider_id": "prov-atl-001",
        "email": "john.smith@techservices.com",
        "name": "John Smith",
        "market": "atlanta",
        "equipment": ["bucket_truck", "spectrum_analyzer", "ladder"],
        "certifications": ["comptia_network_plus", "osha_10"],
        "available": True,
        "travel_willing": True,
        "rating": 4.8,
        "completed_jobs": 127,
    }


@pytest.fixture
def mock_providers_atlanta() -> list[dict[str, Any]]:
    """Mock providers for Atlanta market."""
    return [
        {
            "provider_id": "prov-atl-001",
            "email": "john.smith@techservices.com",
            "name": "John Smith",
            "market": "atlanta",
            "equipment": ["bucket_truck", "spectrum_analyzer"],
            "certifications": ["comptia_network_plus"],
            "available": True,
            "travel_willing": True,
            "rating": 4.8,
            "completed_jobs": 127,
        },
        {
            "provider_id": "prov-atl-002",
            "email": "sarah.johnson@fieldtech.net",
            "name": "Sarah Johnson",
            "market": "atlanta",
            "equipment": ["bucket_truck", "fiber_splicer"],
            "certifications": ["bicsi"],
            "available": True,
            "travel_willing": False,
            "rating": 4.5,
            "completed_jobs": 89,
        },
        {
            "provider_id": "prov-atl-003",
            "email": "mike.davis@networkpros.com",
            "name": "Mike Davis",
            "market": "atlanta",
            "equipment": ["spectrum_analyzer"],
            "certifications": [],
            "available": True,
            "travel_willing": True,
            "rating": 4.2,
            "completed_jobs": 45,
        },
    ]


# --- LLM Mock Fixtures ---


@pytest.fixture
def mock_llm_client():
    """
    Provide a mock LLM client for testing without AWS Bedrock.
    
    Pre-configured with common response types.
    """
    from tests.mocks.mock_bedrock import MockBedrockLLMClient
    from tests.fixtures.llm_responses import (
        MOCK_EMAIL_INITIAL_OUTREACH,
        MOCK_CLASSIFICATION_POSITIVE,
        MOCK_EQUIPMENT_COMPLETE,
        MOCK_INSURANCE_VALID,
        MOCK_DECISION_QUALIFIED,
    )
    
    client = MockBedrockLLMClient()
    client.set_responses([
        MOCK_EMAIL_INITIAL_OUTREACH,
        MOCK_CLASSIFICATION_POSITIVE,
        MOCK_EQUIPMENT_COMPLETE,
        MOCK_INSURANCE_VALID,
        MOCK_DECISION_QUALIFIED,
    ])
    return client


@pytest.fixture
def mock_llm_disabled():
    """
    Fixture that patches LLM settings to disable all LLM features.
    
    Use this to test template fallback behavior.
    """
    from unittest.mock import MagicMock
    from agents.shared.llm.config import LLMSettings
    
    mock_settings = MagicMock(spec=LLMSettings)
    mock_settings.llm_enabled = False
    mock_settings.use_llm_for_email = False
    mock_settings.use_llm_for_classification = False
    mock_settings.use_llm_for_screening = False
    mock_settings.use_llm_for_document_analysis = False
    mock_settings.is_feature_enabled.return_value = False
    
    with patch("agents.shared.llm.config.get_llm_settings", return_value=mock_settings):
        yield mock_settings


@pytest.fixture
def mock_llm_email_only():
    """
    Fixture that enables LLM only for email generation.
    
    Classification and screening use template fallback.
    """
    from unittest.mock import MagicMock
    from agents.shared.llm.config import LLMSettings
    
    mock_settings = MagicMock(spec=LLMSettings)
    mock_settings.llm_enabled = True
    mock_settings.use_llm_for_email = True
    mock_settings.use_llm_for_classification = False
    mock_settings.use_llm_for_screening = False
    mock_settings.use_llm_for_document_analysis = False
    
    def is_feature_enabled(feature):
        return feature == "email"
    
    mock_settings.is_feature_enabled.side_effect = is_feature_enabled
    
    with patch("agents.shared.llm.config.get_llm_settings", return_value=mock_settings):
        yield mock_settings
