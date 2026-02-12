#!/usr/bin/env python3
"""
Demo Script: Satellite Upgrade Campaign

Runs the PHASE 10 demo scenario from ARCHITECHTURE.md.
This script can:
1. Emit the NewCampaignRequested event to start the campaign
2. Simulate provider email responses
3. Display expected outcomes and trace execution

Usage:
    # Dry run - show what would happen
    python scripts/run_demo.py --dry-run

    # Execute against local (mocked) infrastructure
    python scripts/run_demo.py --local

    # Execute against real AWS (requires credentials)
    python scripts/run_demo.py --aws

    # Simulate individual provider responses
    python scripts/run_demo.py --simulate-responses

See ARCHITECHTURE.md PHASE 10 for complete demo scenario details.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Conditional imports (may not be available in all environments)
try:
    import structlog
    log = structlog.get_logger()
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger(__name__)


# --- Constants ---
FIXTURES_DIR = project_root / "tests" / "fixtures" / "demo"
CAMPAIGN_EVENT_FILE = FIXTURES_DIR / "new_campaign_event.json"
MOCK_PROVIDERS_FILE = FIXTURES_DIR / "mock_providers.json"
PROVIDER_RESPONSES_DIR = FIXTURES_DIR / "provider_responses"
DOCUMENTS_FILE = FIXTURES_DIR / "documents" / "insurance_documents.json"


@dataclass
class DemoStats:
    """Track demo execution statistics."""
    providers_invited: int = 0
    emails_sent: int = 0
    responses_received: int = 0
    documents_processed: int = 0
    qualified: int = 0
    rejected: int = 0
    waiting_document: int = 0
    errors: int = 0


class DemoRunner:
    """
    Orchestrates the Satellite Upgrade demo scenario.
    
    This follows the PHASE 10 demo flow from ARCHITECHTURE.md:
    1. NewCampaignRequested → Campaign Planner
    2. SendMessageRequested × 15 → Communication Agent
    3. ProviderResponseReceived × 15 → Screening Agent
    4. DocumentProcessed → Screening Agent (for attachments)
    5. ScreeningCompleted → Final results
    """
    
    def __init__(self, mode: str = "dry-run", verbose: bool = False):
        """
        Initialize demo runner.
        
        Args:
            mode: Execution mode (dry-run, local, aws, simulate-responses)
            verbose: Enable verbose output
        """
        self.mode = mode
        self.verbose = verbose
        self.stats = DemoStats()
        self.campaign_id = "satellite-upgrade-2026-02"
        
        # Load fixtures
        self.campaign_event = self._load_json(CAMPAIGN_EVENT_FILE)
        self.mock_providers = self._load_json(MOCK_PROVIDERS_FILE)
        self.documents = self._load_json(DOCUMENTS_FILE)
        self.provider_responses = self._load_provider_responses()
    
    def _load_json(self, path: Path) -> dict[str, Any]:
        """Load JSON fixture file."""
        if not path.exists():
            print(f"[WARNING] Fixture not found: {path}")
            return {}
        with open(path) as f:
            return json.load(f)
    
    def _load_provider_responses(self) -> dict[str, dict[str, Any]]:
        """Load all provider response fixtures."""
        responses = {}
        if PROVIDER_RESPONSES_DIR.exists():
            for response_file in PROVIDER_RESPONSES_DIR.glob("*.json"):
                with open(response_file) as f:
                    data = json.load(f)
                    provider_id = data.get("provider_id")
                    if provider_id:
                        responses[provider_id] = data
        return responses
    
    def _print_header(self, text: str) -> None:
        """Print formatted section header."""
        print(f"\n{'='*60}")
        print(f"  {text}")
        print(f"{'='*60}\n")
    
    def _print_step(self, step: int, text: str) -> None:
        """Print formatted step."""
        print(f"\n[STEP {step}] {text}")
        print("-" * 40)
    
    def _generate_trace_context(self) -> dict[str, str]:
        """Generate OpenTelemetry trace context."""
        return {
            "trace_id": uuid4().hex,
            "span_id": uuid4().hex[:16],
        }
    
    def run(self) -> None:
        """Execute the full demo scenario."""
        self._print_header("SATELLITE UPGRADE CAMPAIGN DEMO")
        print(f"Mode: {self.mode.upper()}")
        print(f"Campaign ID: {self.campaign_id}")
        print(f"Started: {datetime.now().isoformat()}")
        
        # Step 1: Campaign Creation
        self._step_campaign_creation()
        
        # Step 2: Provider Invitations
        self._step_provider_invitations()
        
        # Step 3: Simulate Provider Responses
        self._step_provider_responses()
        
        # Step 4: Document Processing
        self._step_document_processing()
        
        # Step 5: Show Final Results
        self._step_final_results()
        
        self._print_summary()
    
    def _step_campaign_creation(self) -> None:
        """Step 1: Emit NewCampaignRequested event."""
        self._print_step(1, "CAMPAIGN CREATION")
        
        event = self.campaign_event.get("raw_event", {})
        requirements = event.get("requirements", {})
        
        print(f"Campaign Type: {requirements.get('type', 'unknown')}")
        print(f"Markets: {', '.join(requirements.get('markets', []))}")
        print(f"Providers per Market: {requirements.get('providers_per_market', 0)}")
        print(f"Required Equipment: {', '.join(requirements.get('equipment', {}).get('required', []))}")
        print(f"Insurance Minimum: ${requirements.get('documents', {}).get('insurance_min_coverage', 0):,}")
        print(f"Travel Required: {requirements.get('travel_required', False)}")
        
        if self.mode == "dry-run":
            print("\n[DRY-RUN] Would emit NewCampaignRequested event to EventBridge")
        elif self.mode == "aws":
            self._emit_event_aws("NewCampaignRequested", event)
        elif self.mode == "local":
            self._emit_event_local("NewCampaignRequested", event)
        else:
            print("\n[SIMULATE] Processing NewCampaignRequested...")
    
    def _step_provider_invitations(self) -> None:
        """Step 2: Show provider invitations (SendMessageRequested events)."""
        self._print_step(2, "PROVIDER INVITATIONS")
        
        providers = self.mock_providers.get("providers", {})
        
        for market, market_providers in providers.items():
            print(f"\n{market.upper()} MARKET ({len(market_providers)} providers):")
            
            for provider in market_providers:
                self.stats.providers_invited += 1
                scenario = provider.get("demo_scenario", "unknown")
                expected = provider.get("expected_outcome", "unknown")
                
                print(f"  • {provider['name']} ({provider['provider_id']})")
                print(f"    Email: {provider['email']}")
                print(f"    Equipment: {', '.join(provider.get('equipment', []))}")
                print(f"    Scenario: {scenario} → Expected: {expected}")
                
                if self.mode in ("aws", "local"):
                    # Build SendMessageRequested event
                    message_event = self._build_send_message_event(provider)
                    if self.mode == "aws":
                        self._emit_event_aws("SendMessageRequested", message_event)
                    else:
                        self._emit_event_local("SendMessageRequested", message_event)
                    self.stats.emails_sent += 1
        
        print(f"\n[INFO] Total providers invited: {self.stats.providers_invited}")
    
    def _step_provider_responses(self) -> None:
        """Step 3: Simulate provider email responses."""
        self._print_step(3, "PROVIDER RESPONSES (Simulated)")
        
        providers = self.mock_providers.get("providers", {})
        
        for market, market_providers in providers.items():
            for provider in market_providers:
                provider_id = provider["provider_id"]
                response_data = self.provider_responses.get(provider_id, {})
                
                if not response_data:
                    print(f"  [SKIP] No response fixture for {provider_id}")
                    continue
                
                self.stats.responses_received += 1
                email_response = response_data.get("email_response", {})
                
                print(f"\n  Provider: {provider['name']} ({provider_id})")
                print(f"  Subject: {email_response.get('subject', 'N/A')}")
                print(f"  Has Attachment: {email_response.get('has_attachment', False)}")
                print(f"  Expected Outcome: {response_data.get('expected_outcome', 'N/A')}")
                
                if self.verbose:
                    body = email_response.get("body", "")
                    preview = body[:150] + "..." if len(body) > 150 else body
                    print(f"  Body Preview: {preview}")
                
                if self.mode in ("aws", "local"):
                    # Build ProviderResponseReceived event
                    response_event = self._build_provider_response_event(provider, response_data)
                    if self.mode == "aws":
                        self._emit_event_aws("ProviderResponseReceived", response_event)
                    else:
                        self._emit_event_local("ProviderResponseReceived", response_event)
    
    def _step_document_processing(self) -> None:
        """Step 4: Show document processing results."""
        self._print_step(4, "DOCUMENT PROCESSING (Textract Simulation)")
        
        documents = self.documents.get("documents", [])
        
        for doc in documents:
            self.stats.documents_processed += 1
            provider_id = doc.get("provider_id")
            status = doc.get("validation_status")
            textract = doc.get("mock_textract_output", {})
            extracted = textract.get("extracted_fields", {})
            
            print(f"\n  Document: {doc.get('filename')}")
            print(f"  Provider: {provider_id}")
            print(f"  Status: {status.upper()}")
            print(f"  Coverage: ${extracted.get('coverage_amount_usd', 0):,}")
            print(f"  Expires: {extracted.get('expiry_date', 'N/A')}")
            print(f"  Confidence: {textract.get('extraction_confidence', 0):.0%}")
            
            if status != "valid":
                reason = textract.get("validation_failure_reason", "Unknown")
                print(f"  Failure: {reason}")
            
            if self.mode in ("aws", "local"):
                # Build DocumentProcessed event
                doc_event = self._build_document_processed_event(doc)
                if self.mode == "aws":
                    self._emit_event_aws("DocumentProcessed", doc_event)
                else:
                    self._emit_event_local("DocumentProcessed", doc_event)
    
    def _step_final_results(self) -> None:
        """Step 5: Show expected final outcomes."""
        self._print_step(5, "EXPECTED OUTCOMES")
        
        providers = self.mock_providers.get("providers", {})
        outcomes: dict[str, list[str]] = {
            "QUALIFIED": [],
            "REJECTED": [],
            "WAITING_DOCUMENT": [],
        }
        
        for market, market_providers in providers.items():
            for provider in market_providers:
                expected = provider.get("expected_outcome", "UNKNOWN")
                provider_id = provider["provider_id"]
                if expected in outcomes:
                    outcomes[expected].append(f"{provider['name']} ({market})")
                
                # Update stats
                if expected == "QUALIFIED":
                    self.stats.qualified += 1
                elif expected == "REJECTED":
                    self.stats.rejected += 1
                elif expected == "WAITING_DOCUMENT":
                    self.stats.waiting_document += 1
        
        for outcome, providers_list in outcomes.items():
            print(f"\n{outcome} ({len(providers_list)}):")
            for p in providers_list:
                print(f"  • {p}")
    
    def _print_summary(self) -> None:
        """Print final summary statistics."""
        self._print_header("DEMO SUMMARY")
        
        print(f"Providers Invited:    {self.stats.providers_invited}")
        print(f"Emails Sent:          {self.stats.emails_sent}")
        print(f"Responses Received:   {self.stats.responses_received}")
        print(f"Documents Processed:  {self.stats.documents_processed}")
        print()
        print(f"QUALIFIED:            {self.stats.qualified}")
        print(f"REJECTED:             {self.stats.rejected}")
        print(f"WAITING_DOCUMENT:     {self.stats.waiting_document}")
        print(f"Errors:               {self.stats.errors}")
        print()
        print(f"Completed: {datetime.now().isoformat()}")
        print()
        
        # Verify against PHASE 10 expectations
        expected_qualified = 5  # From PHASE 10: ~7-8 qualify but 5 have valid insurance
        if self.stats.qualified >= expected_qualified:
            print("[✓] Demo meets qualification target")
        else:
            print(f"[!] Demo below target (expected ~{expected_qualified}+ qualified)")
    
    def _build_send_message_event(self, provider: dict[str, Any]) -> dict[str, Any]:
        """Build SendMessageRequested event for a provider."""
        return {
            "campaign_id": self.campaign_id,
            "provider_id": provider["provider_id"],
            "provider_email": provider["email"],
            "provider_name": provider["name"],
            "provider_market": provider["market"],
            "message_type": "initial_outreach",
            "template_data": {
                "campaign_type": "Satellite Upgrade",
                "market": provider["market"].title(),
                "equipment_list": "bucket truck, spectrum analyzer",
                "insurance_requirement": "$2,000,000 liability coverage",
                "next_steps": "Reply with your availability and attach insurance certificate",
            },
            "trace_context": self._generate_trace_context(),
        }
    
    def _build_provider_response_event(
        self, 
        provider: dict[str, Any],
        response_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Build ProviderResponseReceived event."""
        email_resp = response_data.get("email_response", {})
        
        attachments = []
        if email_resp.get("has_attachment"):
            attachments.append({
                "filename": email_resp.get("attachment_filename", "unknown.pdf"),
                "s3_path": f"s3://recruitment-documents/{self.campaign_id}/{provider['provider_id']}/insurance.pdf",
                "content_type": "application/pdf",
                "size_bytes": 256000,
            })
        
        return {
            "campaign_id": self.campaign_id,
            "provider_id": provider["provider_id"],
            "provider_email": provider["email"],
            "received_at": int(time.time()),
            "email_thread_id": f"msg-{uuid4().hex[:12]}",
            "message_id": f"<{uuid4()}@example.com>",
            "subject": email_resp.get("subject", "Re: Opportunity"),
            "body": email_resp.get("body", ""),
            "attachments": attachments,
            "trace_context": self._generate_trace_context(),
        }
    
    def _build_document_processed_event(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Build DocumentProcessed event from mock Textract output."""
        textract = doc.get("mock_textract_output", {})
        extracted = textract.get("extracted_fields", {})
        
        return {
            "campaign_id": self.campaign_id,
            "provider_id": doc.get("provider_id"),
            "document_type": doc.get("document_type", "insurance_certificate"),
            "s3_path": f"s3://recruitment-documents/{self.campaign_id}/{doc.get('provider_id')}/insurance.pdf",
            "extraction_results": extracted,
            "confidence_score": textract.get("extraction_confidence", 0.9),
            "validation_status": doc.get("validation_status", "unknown"),
            "trace_context": self._generate_trace_context(),
        }
    
    def _emit_event_aws(self, event_type: str, detail: dict[str, Any]) -> None:
        """Emit event to real AWS EventBridge."""
        try:
            from agents.shared.config import get_settings
            import boto3
            
            settings = get_settings()
            client = boto3.client("events", region_name=settings.aws_region)
            
            response = client.put_events(
                Entries=[
                    {
                        "EventBusName": settings.eventbridge_bus_name,
                        "Source": f"recruitment.demo.{event_type.lower()}",
                        "DetailType": event_type,
                        "Detail": json.dumps(detail),
                    }
                ]
            )
            
            if response.get("FailedEntryCount", 0) > 0:
                print(f"  [ERROR] Failed to emit {event_type}")
                self.stats.errors += 1
            else:
                print(f"  [AWS] Emitted {event_type}")
                
        except Exception as e:
            print(f"  [ERROR] AWS emit failed: {e}")
            self.stats.errors += 1
    
    def _emit_event_local(self, event_type: str, detail: dict[str, Any]) -> None:
        """Emit event to local/mocked EventBridge."""
        # In local mode, just log the event
        print(f"  [LOCAL] Would emit {event_type}: {detail.get('provider_id', detail.get('campaign_id', 'N/A'))}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run the Satellite Upgrade Campaign demo scenario",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --dry-run              Show what would happen without executing
  %(prog)s --local                Run against local/mocked infrastructure
  %(prog)s --aws                  Run against real AWS resources
  %(prog)s --simulate-responses   Simulate provider responses only
  %(prog)s --verbose              Enable verbose output
        """,
    )
    
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without executing",
    )
    mode_group.add_argument(
        "--local",
        action="store_true",
        help="Run against local/mocked infrastructure",
    )
    mode_group.add_argument(
        "--aws",
        action="store_true",
        help="Run against real AWS resources (requires credentials)",
    )
    mode_group.add_argument(
        "--simulate-responses",
        action="store_true",
        help="Only simulate provider responses",
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    
    parser.add_argument(
        "--campaign-id",
        default="satellite-upgrade-2026-02",
        help="Override campaign ID",
    )
    
    args = parser.parse_args()
    
    # Determine mode
    if args.dry_run:
        mode = "dry-run"
    elif args.local:
        mode = "local"
    elif args.aws:
        mode = "aws"
    elif args.simulate_responses:
        mode = "simulate-responses"
    else:
        mode = "dry-run"  # Default
    
    # Run demo
    runner = DemoRunner(mode=mode, verbose=args.verbose)
    if args.campaign_id:
        runner.campaign_id = args.campaign_id
    runner.run()


if __name__ == "__main__":
    main()
