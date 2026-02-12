#!/usr/bin/env python3
"""
Generate Sample Test Data

Creates realistic test data files for manual AWS Console testing
and validation of the recruitment automation system.
"""

import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tests.utils.event_generator import MockEventGenerator


def generate_sample_events():
    """Generate sample events for AWS EventBridge testing."""
    generator = MockEventGenerator(seed=42)
    
    events = {}
    
    # 1. New Campaign Requested
    campaign_event = generator.generate_new_campaign_event()
    campaign_id = campaign_event["campaign_id"]
    
    events["1_new_campaign_requested"] = {
        "Source": "recruitment.api",
        "DetailType": "NewCampaignRequested",
        "Detail": campaign_event,
        "EventBusName": "recruitment-events-dev",
    }
    
    # 2. Send Message Requested
    provider = generator.generate_provider_info(market="atlanta")
    message_event = generator.generate_send_message_event(campaign_id, provider)
    
    events["2_send_message_requested"] = {
        "Source": "recruitment.agents.campaign_planner",
        "DetailType": "SendMessageRequested",
        "Detail": message_event,
        "EventBusName": "recruitment-events-dev",
    }
    
    # 3. Provider Response (Positive)
    response_positive = generator.generate_provider_response_event(
        campaign_id=campaign_id,
        provider_id=provider["provider_id"],
        provider_email=provider["email"],
        sentiment="positive",
        has_attachments=True,
    )
    
    events["3_provider_response_positive"] = {
        "Source": "recruitment.email",
        "DetailType": "ProviderResponseReceived",
        "Detail": response_positive,
        "EventBusName": "recruitment-events-dev",
    }
    
    # 4. Document Processed
    doc_event = generator.generate_document_processed_event(
        campaign_id=campaign_id,
        provider_id=provider["provider_id"],
        is_valid=True,
    )
    
    events["4_document_processed"] = {
        "Source": "recruitment.textract",
        "DetailType": "DocumentProcessed",
        "Detail": doc_event,
        "EventBusName": "recruitment-events-dev",
    }
    
    # 5. Screening Completed (Qualified)
    screening_event = generator.generate_screening_completed_event(
        campaign_id=campaign_id,
        provider_id=provider["provider_id"],
        result="qualified",
        matched_equipment=["bucket_truck", "spectrum_analyzer"],
        missing_equipment=[],
    )
    
    events["5_screening_completed_qualified"] = {
        "Source": "recruitment.agents.screening",
        "DetailType": "ScreeningCompleted",
        "Detail": screening_event,
        "EventBusName": "recruitment-events-dev",
    }
    
    # 6. Provider Response (Rejected)
    provider_rejected = generator.generate_provider_info(market="chicago")
    response_rejected = generator.generate_provider_response_event(
        campaign_id=campaign_id,
        provider_id=provider_rejected["provider_id"],
        provider_email=provider_rejected["email"],
        sentiment="negative",
        has_attachments=False,
    )
    
    events["6_provider_response_negative"] = {
        "Source": "recruitment.email",
        "DetailType": "ProviderResponseReceived",
        "Detail": response_rejected,
        "EventBusName": "recruitment-events-dev",
    }
    
    return events


def generate_dynamodb_sample_data():
    """Generate sample DynamoDB items."""
    generator = MockEventGenerator(seed=123)
    
    campaign_id = "satellite-upgrade-demo-2026"
    items = []
    
    # Campaign metadata
    items.append({
        "PK": f"SESSION#{campaign_id}",
        "SK": "CAMPAIGN_INFO",
        "campaign_id": campaign_id,
        "campaign_name": "Satellite Upgrade Demo Campaign",
        "buyer_id": "buyer-demo-001",
        "status": "ACTIVE",
        "created_at": 1738800000,
        "target_markets": ["atlanta", "chicago", "milwaukee"],
        "providers_per_market": 5,
    })
    
    # Provider 1: QUALIFIED
    provider1 = generator.generate_provider_info(
        provider_id="prov-atl-001",
        market="atlanta",
        has_equipment=["bucket_truck", "spectrum_analyzer"],
    )
    items.append({
        "PK": f"SESSION#{campaign_id}",
        "SK": f"PROVIDER#{provider1['provider_id']}",
        "campaign_id": campaign_id,
        "provider_id": provider1["provider_id"],
        "provider_name": provider1["name"],
        "provider_email": provider1["email"],
        "provider_market": provider1["market"],
        "status": "QUALIFIED",
        "expected_next_event": None,
        "equipment_confirmed": provider1["equipment"],
        "equipment_missing": [],
        "travel_confirmed": True,
        "documents_uploaded": ["insurance_certificate"],
        "screening_notes": "Qualified. All requirements met.",
        "GSI1PK": "QUALIFIED#null",
        "GSI1SK": provider1["provider_id"],
        "created_at": 1738800000,
        "updated_at": 1738900000,
    })
    
    # Provider 2: REJECTED
    provider2 = generator.generate_provider_info(
        provider_id="prov-chi-002",
        market="chicago",
        has_equipment=["bucket_truck"],
    )
    items.append({
        "PK": f"SESSION#{campaign_id}",
        "SK": f"PROVIDER#{provider2['provider_id']}",
        "campaign_id": campaign_id,
        "provider_id": provider2["provider_id"],
        "provider_name": provider2["name"],
        "provider_email": provider2["email"],
        "provider_market": provider2["market"],
        "status": "REJECTED",
        "expected_next_event": None,
        "equipment_confirmed": ["bucket_truck"],
        "equipment_missing": ["spectrum_analyzer"],
        "travel_confirmed": True,
        "documents_uploaded": [],
        "screening_notes": "Rejected. Missing required spectrum_analyzer.",
        "GSI1PK": "REJECTED#null",
        "GSI1SK": provider2["provider_id"],
        "created_at": 1738800000,
        "updated_at": 1738850000,
    })
    
    # Provider 3: WAITING_RESPONSE
    provider3 = generator.generate_provider_info(
        provider_id="prov-mil-003",
        market="milwaukee",
    )
    items.append({
        "PK": f"SESSION#{campaign_id}",
        "SK": f"PROVIDER#{provider3['provider_id']}",
        "campaign_id": campaign_id,
        "provider_id": provider3["provider_id"],
        "provider_name": provider3["name"],
        "provider_email": provider3["email"],
        "provider_market": provider3["market"],
        "status": "WAITING_RESPONSE",
        "expected_next_event": "ProviderResponseReceived",
        "equipment_confirmed": [],
        "equipment_missing": [],
        "travel_confirmed": False,
        "documents_uploaded": [],
        "screening_notes": "Awaiting initial response.",
        "GSI1PK": "WAITING_RESPONSE#ProviderResponseReceived",
        "GSI1SK": provider3["provider_id"],
        "created_at": 1738800000,
        "updated_at": 1738800000,
    })
    
    return items


def main():
    """Generate all sample test data."""
    output_dir = project_root / "scripts" / "test_data"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("🎲 Generating sample test data...\n")
    
    # 1. Generate EventBridge events
    print("1️⃣  Generating EventBridge events...")
    events = generate_sample_events()
    events_file = output_dir / "eventbridge_sample_events.json"
    with open(events_file, "w") as f:
        json.dump(events, f, indent=2)
    print(f"   ✅ Saved {len(events)} events to {events_file}\n")
    
    # 2. Generate DynamoDB items
    print("2️⃣  Generating DynamoDB sample items...")
    dynamo_items = generate_dynamodb_sample_data()
    dynamo_file = output_dir / "dynamodb_sample_items.json"
    with open(dynamo_file, "w") as f:
        json.dump({"items": dynamo_items}, f, indent=2, default=str)
    print(f"   ✅ Saved {len(dynamo_items)} items to {dynamo_file}\n")
    
    # 3. Generate complete campaign flow
    print("3️⃣  Generating complete campaign flow...")
    generator = MockEventGenerator(seed=999)
    flow = generator.generate_complete_campaign_flow(
        num_providers=5,
        qualified_ratio=0.6,
    )
    flow_file = output_dir / "complete_campaign_flow.json"
    with open(flow_file, "w") as f:
        json.dump(flow, f, indent=2, default=str)
    print(f"   ✅ Saved complete flow to {flow_file}\n")
    
    # Print summary
    print("=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    print(f"EventBridge Events: {len(events)}")
    print(f"DynamoDB Items: {len(dynamo_items)}")
    print(f"Campaign Flow:")
    print(f"  - Providers: {len(flow['providers'])}")
    print(f"  - Messages: {len(flow['messages'])}")
    print(f"  - Responses: {len(flow['responses'])}")
    print(f"  - Documents: {len(flow['documents'])}")
    print(f"  - Screenings: {len(flow['screenings'])}")
    print()
    print(f"📁 All files saved to: {output_dir}")
    print()
    print("🚀 Next Steps:")
    print("   1. Use eventbridge_sample_events.json for AWS EventBridge testing")
    print("   2. Use dynamodb_sample_items.json for DynamoDB manual entry")
    print("   3. Use complete_campaign_flow.json for end-to-end validation")
    print()


if __name__ == "__main__":
    main()
