"""
Mock Event Generator for Testing

Generates realistic test data for recruitment automation system.
Supports randomized provider responses, documents, and scenarios.
"""

import random
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from faker import Faker

fake = Faker()


class MockEventGenerator:
    """Generate mock events for testing."""
    
    # Equipment keywords from requirements_schema.json
    EQUIPMENT_TYPES = [
        "bucket_truck",
        "spectrum_analyzer",
        "fiber_splicer",
        "otdr",
        "cable_tester",
        "ladder",
    ]
    
    # Certification types
    CERTIFICATION_TYPES = [
        "comptia_network_plus",
        "bicsi",
        "fcc_license",
        "osha_10",
        "osha_30",
    ]
    
    # US Markets
    MARKETS = [
        "atlanta",
        "chicago",
        "milwaukee",
        "denver",
        "phoenix",
        "boston",
        "dallas",
        "seattle",
        "miami",
        "houston",
    ]
    
    # Response types for provider simulation
    RESPONSE_SENTIMENTS = ["positive", "negative", "partial", "question"]
    
    def __init__(self, seed: Optional[int] = None):
        """Initialize generator with optional seed for reproducibility."""
        # Use instance-level Random for true determinism across multiple generators
        self._rng = random.Random(seed)
        if seed:
            Faker.seed(seed)
        
        self.fake = Faker()
    
    def _sample(self, population: List, k: int) -> List:
        """Instance-level random.sample using self._rng."""
        return self._rng.sample(population, k)
    
    def _choice(self, seq: List):
        """Instance-level random.choice using self._rng."""
        return self._rng.choice(seq)
    
    def _randint(self, a: int, b: int) -> int:
        """Instance-level random.randint using self._rng."""
        return self._rng.randint(a, b)
    
    def _uniform(self, a: float, b: float) -> float:
        """Instance-level random.uniform using self._rng."""
        return self._rng.uniform(a, b)
    
    def generate_trace_context(self) -> Dict[str, str]:
        """Generate OpenTelemetry trace context."""
        return {
            "trace_id": secrets.token_hex(16),  # 32 hex chars
            "span_id": secrets.token_hex(8),    # 16 hex chars
        }
    
    def generate_campaign_id(self, prefix: str = "campaign") -> str:
        """Generate unique campaign ID."""
        timestamp = datetime.now().strftime("%Y%m")
        unique = uuid4().hex[:8]
        return f"{prefix}-{timestamp}-{unique}"
    
    def generate_provider_id(self, market: Optional[str] = None) -> str:
        """Generate provider ID with optional market prefix."""
        if not market:
            market = self._choice(self.MARKETS)
        unique = uuid4().hex[:8]
        return f"prov-{market[:3]}-{unique}"
    
    def generate_requirements(
        self,
        campaign_type: str = "satellite_upgrade",
        num_markets: int = 3,
        equipment_count: int = 2,
    ) -> Dict[str, Any]:
        """Generate campaign requirements."""
        markets = self._sample(self.MARKETS, min(num_markets, len(self.MARKETS)))
        required_equipment = self._sample(
            self.EQUIPMENT_TYPES,
            min(equipment_count, len(self.EQUIPMENT_TYPES))
        )
        optional_equipment = self._sample(
            [e for e in self.EQUIPMENT_TYPES if e not in required_equipment],
            min(2, len(self.EQUIPMENT_TYPES) - equipment_count)
        )
        
        return {
            "type": campaign_type,
            "markets": markets,
            "providers_per_market": self._randint(3, 10),
            "equipment": {
                "required": required_equipment,
                "optional": optional_equipment,
            },
            "documents": {
                "required": ["insurance_certificate"],
                "insurance_min_coverage": self._choice([1000000, 2000000, 5000000]),
            },
            "certifications": {
                "required": [],
                "preferred": self._sample(self.CERTIFICATION_TYPES, self._randint(1, 3)),
            },
            "travel_required": self._choice([True, False]),
        }
    
    def generate_new_campaign_event(
        self,
        campaign_id: Optional[str] = None,
        buyer_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate NewCampaignRequested event."""
        return {
            "campaign_id": campaign_id or self.generate_campaign_id(),
            "buyer_id": buyer_id or f"buyer-{self.fake.company_suffix()}-{uuid4().hex[:6]}",
            "requirements": self.generate_requirements(**kwargs),
            "trace_context": self.generate_trace_context(),
        }
    
    def generate_provider_info(
        self,
        provider_id: Optional[str] = None,
        market: Optional[str] = None,
        has_equipment: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate provider information."""
        if not market:
            market = self._choice(self.MARKETS)
        
        if not has_equipment:
            has_equipment = self._sample(
                self.EQUIPMENT_TYPES,
                self._randint(1, len(self.EQUIPMENT_TYPES))
            )
        
        return {
            "provider_id": provider_id or self.generate_provider_id(market),
            "name": self.fake.name(),
            "email": self.fake.email(),
            "market": market,
            "equipment": has_equipment,
            "certifications": self._sample(
                self.CERTIFICATION_TYPES,
                self._randint(0, 2)
            ),
            "available": self._choice([True, True, True, False]),  # 75% available
            "travel_willing": self._choice([True, True, False]),   # 66% willing
            "rating": round(self._uniform(3.5, 5.0), 1),
            "completed_jobs": self._randint(10, 500),
        }
    
    def generate_send_message_event(
        self,
        campaign_id: str,
        provider_info: Dict[str, Any],
        message_type: str = "initial_outreach",
    ) -> Dict[str, Any]:
        """Generate SendMessageRequested event."""
        return {
            "campaign_id": campaign_id,
            "provider_id": provider_info["provider_id"],
            "provider_email": provider_info["email"],
            "provider_name": provider_info["name"],
            "provider_market": provider_info["market"],
            "message_type": message_type,
            "template_data": {
                "campaign_type": "Satellite Upgrade",
                "market": provider_info["market"].title(),
                "equipment_list": ", ".join(provider_info["equipment"]),
                "insurance_requirement": "$2,000,000 liability coverage",
                "next_steps": "Reply to this email with your availability and equipment",
            },
            "trace_context": self.generate_trace_context(),
        }
    
    def generate_provider_response_event(
        self,
        campaign_id: str,
        provider_id: str,
        provider_email: str,
        sentiment: Literal["positive", "negative", "partial", "question"] = "positive",
        has_attachments: bool = False,
    ) -> Dict[str, Any]:
        """Generate ProviderResponseReceived event with customizable sentiment."""
        # Generate realistic email body based on sentiment
        bodies = {
            "positive": [
                "Hi,\n\nI'm very interested in this opportunity!\n\nI have a bucket truck and spectrum analyzer ready to go. I'm definitely willing to travel for the right projects.\n\nI'm attaching my insurance certificate below. Let me know what else you need!\n\nBest regards,",
                "Thanks for reaching out! This sounds like a great fit.\n\nEquipment: ✓ Bucket truck, ✓ Spectrum analyzer\nTravel: ✓ Yes, no problem\n\nSee attached insurance docs. Looking forward to working with you!",
                "Hello,\n\nCount me in! I've got all the required equipment and I'm ready to start whenever needed. Insurance certificate attached.\n\nThanks!",
            ],
            "negative": [
                "Thanks for thinking of me, but I don't have the equipment you're looking for. I'll have to pass on this one.",
                "Hi,\n\nI'm not available for travel right now, so I won't be able to take this on. Maybe next time!",
                "I don't think this is a good fit for me at this time. Thanks anyway.",
            ],
            "partial": [
                "Hi,\n\nI have the bucket truck but not the spectrum analyzer. Would that be a deal-breaker?\n\nLet me know!",
                "I'm interested but I'm not sure about the travel requirement. How much travel are we talking about?",
                "I have most of the equipment but my insurance is only $1M. Is that sufficient?",
            ],
            "question": [
                "Can you provide more details about the pay rate and project timeline?",
                "What's the expected duration for this project? And is there any training provided?",
                "Do you cover travel expenses? And what's the typical work schedule?",
            ],
        }
        
        body = self._choice(bodies[sentiment])
        
        # Generate attachments if requested
        attachments = []
        if has_attachments and sentiment in ["positive", "partial"]:
            attachments.append({
                "filename": "Insurance_Certificate_2026.pdf",
                "s3_path": f"s3://recruitment-emails-integration/attachments/{provider_id}/insurance_{uuid4().hex[:8]}.pdf",
                "content_type": "application/pdf",
                "size_bytes": self._randint(100000, 500000),
            })
        
        return {
            "campaign_id": campaign_id,
            "provider_id": provider_id,
            "provider_email": provider_email,
            "received_at": int(datetime.now().timestamp()),
            "email_thread_id": f"msg-{uuid4().hex[:12]}",
            "message_id": f"<{uuid4()}@{provider_email.split('@')[1]}>",
            "subject": "Re: OPPORTUNITY: Satellite Upgrade technicians needed",
            "body": body,
            "attachments": attachments,
            "trace_context": self.generate_trace_context(),
        }
    
    def generate_document_processed_event(
        self,
        campaign_id: str,
        provider_id: str,
        document_type: str = "insurance_certificate",
        is_valid: bool = True,
    ) -> Dict[str, Any]:
        """Generate DocumentProcessed event."""
        # Generate realistic extracted fields
        coverage_amount = self._choice([1000000, 2000000, 2500000, 5000000])
        expiry_date = (datetime.now() + timedelta(days=self._randint(30, 730))).strftime("%Y-%m-%d")
        
        extracted_fields = {
            "policy_holder": self.fake.name(),
            "insurance_company": self._choice([
                "State Farm",
                "Liberty Mutual",
                "Travelers",
                "Progressive",
                "Nationwide"
            ]),
            "policy_number": f"POL-{self._randint(100000, 999999)}",
            "coverage_type": "General Liability",
            "coverage_amount_usd": coverage_amount,
            "effective_date": (datetime.now() - timedelta(days=self._randint(30, 365))).strftime("%Y-%m-%d"),
            "expiry_date": expiry_date,
        }
        
        # Lower confidence for invalid documents
        base_confidence = 0.90 if is_valid else 0.60
        confidence_scores = {
            key: round(base_confidence + self._uniform(-0.10, 0.10), 2)
            for key in extracted_fields.keys()
        }
        
        return {
            "campaign_id": campaign_id,
            "provider_id": provider_id,
            "document_type": document_type,
            "s3_path": f"s3://recruitment-documents-integration/{campaign_id}/{provider_id}/{document_type}.pdf",
            "extraction_results": extracted_fields,
            "confidence_score": sum(confidence_scores.values()) / len(confidence_scores),
            "validation_status": "valid" if is_valid else "invalid",
            "trace_context": self.generate_trace_context(),
        }
    
    def generate_screening_completed_event(
        self,
        campaign_id: str,
        provider_id: str,
        result: Literal["qualified", "rejected", "escalated"] = "qualified",
        matched_equipment: Optional[List[str]] = None,
        missing_equipment: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate ScreeningCompleted event."""
        if not matched_equipment:
            matched_equipment = self._sample(self.EQUIPMENT_TYPES, self._randint(1, 4))
        if not missing_equipment:
            missing_equipment = []
        
        # Generate notes based on result
        notes = {
            "qualified": f"Provider meets all requirements. Equipment: {', '.join(matched_equipment)}. Travel confirmed. Insurance approved.",
            "rejected": f"Missing required equipment: {', '.join(missing_equipment) if missing_equipment else 'N/A'}. Does not meet minimum requirements.",
            "escalated": "Edge case detected. Manual review required for insurance verification.",
        }
        
        return {
            "campaign_id": campaign_id,
            "provider_id": provider_id,
            "screening_result": result,
            "confidence_score": round(self._uniform(0.80, 0.99), 2),
            "screening_notes": notes[result],
            "matched_equipment": matched_equipment,
            "missing_equipment": missing_equipment,
            "travel_confirmed": result != "rejected",
            "document_status": "approved" if result == "qualified" else "pending",
            "certifications_found": self._sample(self.CERTIFICATION_TYPES, self._randint(0, 2)),
            "trace_context": self.generate_trace_context(),
        }
    
    def generate_complete_campaign_flow(
        self,
        num_providers: int = 5,
        qualified_ratio: float = 0.6,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate a complete campaign flow with multiple providers.
        
        Returns a dict with event types as keys and lists of events.
        Simulates a realistic campaign with mixed outcomes.
        """
        campaign_id = self.generate_campaign_id()
        num_qualified = int(num_providers * qualified_ratio)
        
        # Generate campaign event (generate_new_campaign_event calls generate_requirements internally)
        campaign_event = self.generate_new_campaign_event(
            campaign_id=campaign_id,
        )
        
        # Generate providers
        providers = [
            self.generate_provider_info()
            for _ in range(num_providers)
        ]
        
        # Generate message requests
        message_events = [
            self.generate_send_message_event(campaign_id, provider)
            for provider in providers
        ]
        
        # Generate responses (qualified, partial, rejected)
        response_events = []
        document_events = []
        screening_events = []
        
        for i, provider in enumerate(providers):
            # Determine outcome
            if i < num_qualified:
                sentiment = "positive"
                has_attachments = True
                screening_result = "qualified"
            elif i < num_qualified + (num_providers - num_qualified) // 2:
                sentiment = "partial"
                has_attachments = False
                screening_result = "rejected"
            else:
                sentiment = "negative"
                has_attachments = False
                screening_result = "rejected"
            
            # Generate response
            response = self.generate_provider_response_event(
                campaign_id,
                provider["provider_id"],
                provider["email"],
                sentiment=sentiment,
                has_attachments=has_attachments,
            )
            response_events.append(response)
            
            # Generate document processing if attachment present
            if has_attachments:
                doc_event = self.generate_document_processed_event(
                    campaign_id,
                    provider["provider_id"],
                    is_valid=(screening_result == "qualified"),
                )
                document_events.append(doc_event)
            
            # Generate screening result
            screening_event = self.generate_screening_completed_event(
                campaign_id,
                provider["provider_id"],
                result=screening_result,
                matched_equipment=provider["equipment"][:2],
                missing_equipment=[] if screening_result == "qualified" else ["spectrum_analyzer"],
            )
            screening_events.append(screening_event)
        
        return {
            "campaign": campaign_event,
            "providers": providers,
            "messages": message_events,
            "responses": response_events,
            "documents": document_events,
            "screenings": screening_events,
        }


# Convenience function for quick random event generation
def generate_random_event(event_type: str, **kwargs) -> Dict[str, Any]:
    """Quick random event generator."""
    generator = MockEventGenerator()
    
    generators = {
        "new_campaign": generator.generate_new_campaign_event,
        "send_message": lambda: generator.generate_send_message_event(
            campaign_id=kwargs.get("campaign_id", generator.generate_campaign_id()),
            provider_info=kwargs.get("provider_info", generator.generate_provider_info()),
        ),
        "provider_response": lambda: generator.generate_provider_response_event(
            campaign_id=kwargs.get("campaign_id", generator.generate_campaign_id()),
            provider_id=kwargs.get("provider_id", generator.generate_provider_id()),
            provider_email=kwargs.get("provider_email", "test@example.com"),
        ),
        "document_processed": generator.generate_document_processed_event,
        "screening_completed": generator.generate_screening_completed_event,
    }
    
    if event_type not in generators:
        raise ValueError(f"Unknown event type: {event_type}")
    
    return generators[event_type]()
