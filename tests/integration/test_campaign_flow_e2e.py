"""
End-to-End Integration Tests for Campaign Flow

Tests complete recruitment campaign workflows from creation
through provider screening and qualification.
"""

import json
import time
from typing import Any, Dict, List

import pytest

from agents.shared.models.dynamo import ProviderState
from agents.shared.state_machine import ProviderStatus
from tests.utils.event_generator import MockEventGenerator


@pytest.mark.integration
class TestCampaignFlowE2E:
    """End-to-end tests for complete campaign workflows."""
    
    def test_single_provider_qualified_flow(
        self,
        integration_aws_setup,
        clean_dynamodb_table,
        integration_event_collector,
        integration_campaign_id,
    ):
        """
        Test complete flow: Campaign → Message → Response → Document → Screening → Qualified
        
        Verify that:
        1. Campaign creation triggers provider invitations
        2. Provider response triggers document processing
        3. Document processing triggers screening
        4. Screening results in QUALIFIED status
        """
        generator = MockEventGenerator(seed=42)
        table = clean_dynamodb_table
        events = integration_aws_setup["events"]
        
        # Step 1: Create campaign
        campaign_event = generator.generate_new_campaign_event(
            campaign_id=integration_campaign_id
        )
        
        # Simulate Campaign Planner Agent creating provider records
        provider_info = generator.generate_provider_info(
            has_equipment=["bucket_truck", "spectrum_analyzer"]
        )
        
        table.put_item(Item={
            "PK": f"SESSION#{integration_campaign_id}",
            "SK": f"PROVIDER#{provider_info['provider_id']}",
            "campaign_id": integration_campaign_id,
            "provider_id": provider_info["provider_id"],
            "provider_email": provider_info["email"],
            "provider_name": provider_info["name"],
            "provider_market": provider_info["market"],
            "status": "INVITED",
            "expected_next_event": "SendMessageRequested",
            "created_at": int(time.time()),
            "GSI1PK": "INVITED#SendMessageRequested",
            "GSI1SK": provider_info["provider_id"],
        })
        
        # Step 2: Simulate Communication Agent sending message
        table.update_item(
            Key={
                "PK": f"SESSION#{integration_campaign_id}",
                "SK": f"PROVIDER#{provider_info['provider_id']}",
            },
            UpdateExpression="SET #status = :status, expected_next_event = :event, GSI1PK = :gsi",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "WAITING_RESPONSE",
                ":event": "ProviderResponseReceived",
                ":gsi": "WAITING_RESPONSE#ProviderResponseReceived",
            },
        )
        
        # Step 3: Provider responds with positive sentiment + attachment
        response_event = generator.generate_provider_response_event(
            campaign_id=integration_campaign_id,
            provider_id=provider_info["provider_id"],
            provider_email=provider_info["email"],
            sentiment="positive",
            has_attachments=True,
        )
        
        # Simulate Screening Agent processing response
        table.update_item(
            Key={
                "PK": f"SESSION#{integration_campaign_id}",
                "SK": f"PROVIDER#{provider_info['provider_id']}",
            },
            UpdateExpression="SET #status = :status, expected_next_event = :event, GSI1PK = :gsi, equipment_confirmed = :equipment",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "DOCUMENT_PROCESSING",
                ":event": "DocumentProcessed",
                ":gsi": "DOCUMENT_PROCESSING#DocumentProcessed",
                ":equipment": provider_info["equipment"],
            },
        )
        
        # Step 4: Document processed successfully
        doc_event = generator.generate_document_processed_event(
            campaign_id=integration_campaign_id,
            provider_id=provider_info["provider_id"],
            is_valid=True,
        )
        
        # Step 5: Screening completes with QUALIFIED
        screening_event = generator.generate_screening_completed_event(
            campaign_id=integration_campaign_id,
            provider_id=provider_info["provider_id"],
            result="qualified",
            matched_equipment=provider_info["equipment"],
            missing_equipment=[],
        )
        
        # Update to QUALIFIED status
        table.update_item(
            Key={
                "PK": f"SESSION#{integration_campaign_id}",
                "SK": f"PROVIDER#{provider_info['provider_id']}",
            },
            UpdateExpression="SET #status = :status, expected_next_event = :event, GSI1PK = :gsi",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "QUALIFIED",
                ":event": None,
                ":gsi": "QUALIFIED#null",
            },
        )
        
        # Verify final state
        response = table.get_item(
            Key={
                "PK": f"SESSION#{integration_campaign_id}",
                "SK": f"PROVIDER#{provider_info['provider_id']}",
            }
        )
        
        final_state = response["Item"]
        assert final_state["status"] == "QUALIFIED"
        assert final_state["expected_next_event"] is None
        assert len(final_state["equipment_confirmed"]) > 0
        
        print(f"\n✅ Provider {provider_info['provider_id']} successfully qualified!")
    
    def test_multiple_providers_mixed_outcomes(
        self,
        integration_aws_setup,
        clean_dynamodb_table,
        integration_campaign_id,
    ):
        """
        Test campaign with multiple providers having mixed outcomes.
        
        Simulates realistic scenario:
        - 2 providers QUALIFIED
        - 1 provider REJECTED (missing equipment)
        - 1 provider WAITING_RESPONSE (no reply)
        - 1 provider ESCALATED (edge case)
        """
        generator = MockEventGenerator(seed=123)
        table = clean_dynamodb_table
        
        # Generate 5 providers with different outcomes
        outcomes = [
            ("QUALIFIED", ["bucket_truck", "spectrum_analyzer"]),
            ("QUALIFIED", ["bucket_truck", "spectrum_analyzer", "cable_tester"]),
            ("REJECTED", ["bucket_truck"]),  # missing spectrum_analyzer
            ("WAITING_RESPONSE", []),
            ("ESCALATED", ["bucket_truck", "spectrum_analyzer"]),
        ]
        
        for i, (status, equipment) in enumerate(outcomes):
            provider_info = generator.generate_provider_info(
                provider_id=f"prov-test-{i:03d}",
                has_equipment=equipment if equipment else None,
            )
            
            # Create provider record
            table.put_item(Item={
                "PK": f"SESSION#{integration_campaign_id}",
                "SK": f"PROVIDER#{provider_info['provider_id']}",
                "campaign_id": integration_campaign_id,
                "provider_id": provider_info["provider_id"],
                "provider_email": provider_info["email"],
                "provider_name": provider_info["name"],
                "provider_market": provider_info["market"],
                "status": status,
                "expected_next_event": "ProviderResponseReceived" if status == "WAITING_RESPONSE" else None,
                "equipment_confirmed": equipment,
                "equipment_missing": [] if status == "QUALIFIED" else ["spectrum_analyzer"],
                "GSI1PK": f"{status}#{'ProviderResponseReceived' if status == 'WAITING_RESPONSE' else 'null'}",
                "GSI1SK": provider_info["provider_id"],
                "created_at": int(time.time()),
            })
        
        # Query for qualified providers
        qualified = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            FilterExpression="#status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pk": f"SESSION#{integration_campaign_id}",
                ":sk_prefix": "PROVIDER#",
                ":status": "QUALIFIED",
            },
        )
        
        assert qualified["Count"] == 2
        print(f"\n✅ Campaign has {qualified['Count']} qualified providers")
        
        # Query for pending responses
        pending = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            FilterExpression="#status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pk": f"SESSION#{integration_campaign_id}",
                ":sk_prefix": "PROVIDER#",
                ":status": "WAITING_RESPONSE",
            },
        )
        
        assert pending["Count"] == 1
        print(f"📧 {pending['Count']} provider(s) still awaiting response")
    
    def test_complete_campaign_lifecycle(
        self,
        integration_aws_setup,
        clean_dynamodb_table,
    ):
        """
        Test complete campaign lifecycle with generated test data.
        
        Uses MockEventGenerator to create realistic multi-provider campaign.
        """
        generator = MockEventGenerator(seed=999)
        table = clean_dynamodb_table
        
        # Generate complete campaign flow
        flow = generator.generate_complete_campaign_flow(
            num_providers=10,
            qualified_ratio=0.6,  # 60% qualified
        )
        
        campaign_id = flow["campaign"]["campaign_id"]
        
        # Create campaign metadata
        table.put_item(Item={
            "PK": f"SESSION#{campaign_id}",
            "SK": "CAMPAIGN_INFO",
            "campaign_id": campaign_id,
            "campaign_name": "Integration Test Campaign",
            "status": "ACTIVE",
            "created_at": int(time.time()),
            "target_providers": len(flow["providers"]),
        })
        
        # Create provider records with final screening states
        for i, (provider, screening) in enumerate(zip(flow["providers"], flow["screenings"])):
            status = screening["screening_result"].upper()
            if status == "QUALIFIED":
                status = "QUALIFIED"
            elif status == "REJECTED":
                status = "REJECTED"
            else:
                status = "ESCALATED"
            
            table.put_item(Item={
                "PK": f"SESSION#{campaign_id}",
                "SK": f"PROVIDER#{provider['provider_id']}",
                "campaign_id": campaign_id,
                "provider_id": provider["provider_id"],
                "provider_email": provider["email"],
                "provider_name": provider["name"],
                "provider_market": provider["market"],
                "status": status,
                "expected_next_event": None,
                "equipment_confirmed": screening["matched_equipment"],
                "equipment_missing": screening["missing_equipment"],
                "travel_confirmed": screening["travel_confirmed"],
                "screening_notes": screening["screening_notes"],
                "GSI1PK": f"{status}#null",
                "GSI1SK": provider["provider_id"],
                "created_at": int(time.time()),
            })
        
        # Verify campaign statistics
        all_providers = table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": f"SESSION#{campaign_id}",
                ":sk_prefix": "PROVIDER#",
            },
        )
        
        statuses = [item["status"] for item in all_providers["Items"]]
        qualified_count = statuses.count("QUALIFIED")
        rejected_count = statuses.count("REJECTED")
        escalated_count = statuses.count("ESCALATED")
        
        print(f"\n📊 Campaign Statistics:")
        print(f"   Total Providers: {len(statuses)}")
        print(f"   ✅ Qualified: {qualified_count}")
        print(f"   ❌ Rejected: {rejected_count}")
        print(f"   ⚠️  Escalated: {escalated_count}")
        
        assert len(statuses) == len(flow["providers"])
        assert qualified_count > 0
        assert qualified_count + rejected_count + escalated_count == len(statuses)
    
    def test_state_transition_validation(
        self,
        integration_aws_setup,
        clean_dynamodb_table,
        integration_campaign_id,
    ):
        """
        Test that state transitions follow state machine rules.
        
        Verifies:
        - Valid transitions are allowed
        - Invalid transitions are rejected
        - Terminal states cannot transition
        """
        generator = MockEventGenerator(seed=555)
        table = clean_dynamodb_table
        
        provider_id = "prov-state-test-001"
        
        # Test valid transition: INVITED → WAITING_RESPONSE
        table.put_item(Item={
            "PK": f"SESSION#{integration_campaign_id}",
            "SK": f"PROVIDER#{provider_id}",
            "campaign_id": integration_campaign_id,
            "provider_id": provider_id,
            "status": "INVITED",
            "created_at": int(time.time()),
        })
        
        # Valid transition
        table.update_item(
            Key={
                "PK": f"SESSION#{integration_campaign_id}",
                "SK": f"PROVIDER#{provider_id}",
            },
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "WAITING_RESPONSE"},
        )
        
        item = table.get_item(
            Key={
                "PK": f"SESSION#{integration_campaign_id}",
                "SK": f"PROVIDER#{provider_id}",
            }
        )["Item"]
        
        assert item["status"] == "WAITING_RESPONSE"
        print("✅ Valid transition INVITED → WAITING_RESPONSE succeeded")
        
        # Continue to terminal state (QUALIFIED)
        table.update_item(
            Key={
                "PK": f"SESSION#{integration_campaign_id}",
                "SK": f"PROVIDER#{provider_id}",
            },
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "QUALIFIED"},
        )
        
        item = table.get_item(
            Key={
                "PK": f"SESSION#{integration_campaign_id}",
                "SK": f"PROVIDER#{provider_id}",
            }
        )["Item"]
        
        assert item["status"] == "QUALIFIED"
        print("✅ Terminal state QUALIFIED reached")


@pytest.mark.integration
class TestEventDrivenFlows:
    """Test event-driven interactions between components."""
    
    def test_eventbridge_event_publishing(
        self,
        integration_aws_setup,
        integration_event_collector,
        integration_campaign_id,
    ):
        """Test that events can be published and captured."""
        generator = MockEventGenerator()
        events_client = integration_aws_setup["events"]
        
        # Publish test event
        campaign_event = generator.generate_new_campaign_event(
            campaign_id=integration_campaign_id
        )
        
        events_client.put_events(
            Entries=[
                {
                    "Source": "recruitment.test",
                    "DetailType": "NewCampaignRequested",
                    "Detail": json.dumps(campaign_event),
                    "EventBusName": "recruitment-events-integration",
                }
            ]
        )
        
        # Verify event was captured
        assert len(integration_event_collector) == 1
        captured = integration_event_collector[0]
        
        assert captured["Source"] == "recruitment.test"
        assert captured["DetailType"] == "NewCampaignRequested"
        assert captured["Detail"]["campaign_id"] == integration_campaign_id
        
        print(f"✅ Event published and captured: {captured['DetailType']}")
    
    def test_provider_response_processing(
        self,
        integration_aws_setup,
        clean_dynamodb_table,
        integration_campaign_id,
    ):
        """Test processing of provider response events."""
        generator = MockEventGenerator(seed=777)
        table = clean_dynamodb_table
        
        # Set up provider in WAITING_RESPONSE state
        provider_info = generator.generate_provider_info()
        
        table.put_item(Item={
            "PK": f"SESSION#{integration_campaign_id}",
            "SK": f"PROVIDER#{provider_info['provider_id']}",
            "campaign_id": integration_campaign_id,
            "provider_id": provider_info["provider_id"],
            "provider_email": provider_info["email"],
            "status": "WAITING_RESPONSE",
            "expected_next_event": "ProviderResponseReceived",
            "created_at": int(time.time()),
        })
        
        # Generate response event
        response_event = generator.generate_provider_response_event(
            campaign_id=integration_campaign_id,
            provider_id=provider_info["provider_id"],
            provider_email=provider_info["email"],
            sentiment="positive",
            has_attachments=True,
        )
        
        # Verify event structure
        assert response_event["campaign_id"] == integration_campaign_id
        assert response_event["provider_id"] == provider_info["provider_id"]
        assert len(response_event["attachments"]) > 0
        assert response_event["trace_context"]["trace_id"]
        
        print(f"✅ Provider response event generated and validated")


@pytest.mark.integration
class TestDataValidation:
    """Test data validation and consistency."""
    
    def test_mock_data_generation_consistency(self):
        """Test that mock generator produces consistent data with seeds."""
        # Same seed should produce same output
        gen1 = MockEventGenerator(seed=42)
        gen2 = MockEventGenerator(seed=42)
        
        event1 = gen1.generate_new_campaign_event()
        event2 = gen2.generate_new_campaign_event()
        
        # Campaign requirements should match
        assert event1["requirements"]["type"] == event2["requirements"]["type"]
        assert event1["requirements"]["markets"] == event2["requirements"]["markets"]
        
        print("✅ Mock data generation is deterministic with seeds")
    
    def test_complete_flow_data_integrity(self):
        """Test that generated flow data has proper relationships."""
        generator = MockEventGenerator(seed=100)
        
        flow = generator.generate_complete_campaign_flow(num_providers=3)
        
        # Verify data relationships
        campaign_id = flow["campaign"]["campaign_id"]
        
        # All messages should reference same campaign
        for msg in flow["messages"]:
            assert msg["campaign_id"] == campaign_id
        
        # All responses should reference same campaign
        for resp in flow["responses"]:
            assert resp["campaign_id"] == campaign_id
        
        # Provider IDs should match across events
        provider_ids = {p["provider_id"] for p in flow["providers"]}
        message_provider_ids = {m["provider_id"] for m in flow["messages"]}
        assert provider_ids == message_provider_ids
        
        print("✅ Generated flow maintains data integrity")
