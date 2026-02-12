"""
Integration test fixtures and configuration.

Integration tests use real AWS services (with moto mocking)
to test complete event-driven flows.
"""

import json
import os
from typing import Any, Dict, Generator, List
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws

# Set integration test environment
os.environ["INTEGRATION_TEST"] = "true"


@pytest.fixture(scope="session")
def integration_aws_setup():
    """
    Set up complete AWS environment for integration tests.
    
    This fixture runs once per test session and provides
    a fully mocked AWS environment with all services.
    """
    with mock_aws():
        # Initialize clients
        dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        s3 = boto3.client("s3", region_name="us-west-2")
        ses = boto3.client("ses", region_name="us-west-2")
        events_client = boto3.client("events", region_name="us-west-2")
        lambda_client = boto3.client("lambda", region_name="us-west-2")
        sns = boto3.client("sns", region_name="us-west-2")
        
        # Create DynamoDB table
        table = dynamodb.create_table(
            TableName="RecruitmentSessions-integration",
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
                    "IndexName": "GSI1",
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
                "ReadCapacityUnits": 10,
                "WriteCapacityUnits": 10,
            },
        )
        table.meta.client.get_waiter("table_exists").wait(
            TableName="RecruitmentSessions-integration"
        )
        
        # Create S3 buckets
        # Create S3 buckets (requires LocationConstraint for non us-east-1 regions)
        s3.create_bucket(
            Bucket="recruitment-documents-integration",
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"}
        )
        s3.create_bucket(
            Bucket="recruitment-emails-integration",
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"}
        )
        # Create SES verified identities
        ses.verify_email_identity(EmailAddress="noreply@recruitment-test.com")
        ses.verify_email_identity(EmailAddress="john.smith@techservices.com")
        
        # Create EventBridge bus
        events_client.create_event_bus(Name="recruitment-events-integration")
        
        # Create SNS topics
        inbound_topic = sns.create_topic(Name="recruitment-inbound-email-integration")
        ops_topic = sns.create_topic(Name="recruitment-ops-alerts-integration")
        textract_topic = sns.create_topic(Name="recruitment-textract-completion-integration")
        
        yield {
            "dynamodb": dynamodb,
            "table": table,
            "s3": s3,
            "ses": ses,
            "events": events_client,
            "lambda": lambda_client,
            "sns": sns,
            "inbound_topic_arn": inbound_topic["TopicArn"],
            "ops_topic_arn": ops_topic["TopicArn"],
            "textract_topic_arn": textract_topic["TopicArn"],
        }


@pytest.fixture
def integration_event_collector(integration_aws_setup):
    """
    Collect events published to EventBridge during tests.
    
    Useful for verifying event-driven flows.
    """
    collected_events = []
    
    def collect_event(event: Dict[str, Any]):
        """Store event for later verification."""
        collected_events.append(event)
    
    # Mock EventBridge put_events to capture events
    original_put_events = integration_aws_setup["events"].put_events
    
    def mock_put_events(**kwargs):
        entries = kwargs.get("Entries", [])
        for entry in entries:
            collected_events.append({
                "Source": entry.get("Source"),
                "DetailType": entry.get("DetailType"),
                "Detail": json.loads(entry.get("Detail", "{}")),
                "EventBusName": entry.get("EventBusName"),
            })
        return original_put_events(**kwargs)
    
    integration_aws_setup["events"].put_events = mock_put_events
    
    yield collected_events
    
    # Restore original
    integration_aws_setup["events"].put_events = original_put_events


@pytest.fixture
def clean_dynamodb_table(integration_aws_setup):
    """Clean DynamoDB table before each test."""
    table = integration_aws_setup["table"]
    
    # Delete all items
    scan = table.scan()
    with table.batch_writer() as batch:
        for item in scan["Items"]:
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
    
    yield table


@pytest.fixture
def integration_campaign_id() -> str:
    """Generate unique campaign ID for integration test."""
    return f"integration-test-{uuid4().hex[:12]}"


@pytest.fixture
def integration_provider_ids() -> List[str]:
    """Generate unique provider IDs for integration test."""
    return [f"prov-integration-{i:03d}" for i in range(1, 6)]
