"""
Campaign Planner Tools

Agent tools for provider selection and batch operations.
All tools are idempotent as required by agent development guidelines.
"""

from uuid import uuid4

import structlog

from agents.campaign_planner.config import get_campaign_planner_config
from agents.campaign_planner.models import (
    CampaignRequirements,
    ProviderInfo,
    ProviderSelection,
)
from agents.shared.config import get_settings
from agents.shared.models.dynamo import ProviderState
from agents.shared.models.events import (
    MessageType,
    Requirements,
    SendMessageRequestedEvent,
    TemplateData,
    TraceContext,
)
from agents.shared.state_machine import ProviderStatus
from agents.shared.tools.dynamodb import create_provider_record
from agents.shared.tools.eventbridge import send_events_batch

log = structlog.get_logger()


# --- Mock Provider Data for Demo ---
# This simulates the provider database. In production, this would
# query a real ProviderDatabase table or external service.

MOCK_PROVIDERS: dict[str, list[ProviderInfo]] = {
    "atlanta": [
        ProviderInfo(
            provider_id="prov-atl-001",
            email="john.smith@techservices.com",
            name="John Smith",
            market="atlanta",
            equipment=["bucket_truck", "spectrum_analyzer", "ladder"],
            certifications=["comptia_network_plus", "osha_10"],
            available=True,
            travel_willing=True,
            rating=4.8,
            completed_jobs=127,
        ),
        ProviderInfo(
            provider_id="prov-atl-002",
            email="sarah.johnson@fieldtech.net",
            name="Sarah Johnson",
            market="atlanta",
            equipment=["bucket_truck", "fiber_splicer", "otdr"],
            certifications=["bicsi", "osha_10"],
            available=True,
            travel_willing=False,
            rating=4.5,
            completed_jobs=89,
        ),
        ProviderInfo(
            provider_id="prov-atl-003",
            email="mike.davis@networkpros.com",
            name="Mike Davis",
            market="atlanta",
            equipment=["spectrum_analyzer", "cable_tester"],
            certifications=["comptia_network_plus", "fcc_license"],
            available=True,
            travel_willing=True,
            rating=4.2,
            completed_jobs=45,
        ),
        ProviderInfo(
            provider_id="prov-atl-004",
            email="lisa.chen@techelite.com",
            name="Lisa Chen",
            market="atlanta",
            equipment=["bucket_truck", "spectrum_analyzer"],
            certifications=["bicsi", "comptia_network_plus"],
            available=True,
            travel_willing=True,
            rating=4.9,
            completed_jobs=203,
        ),
        ProviderInfo(
            provider_id="prov-atl-005",
            email="robert.williams@fieldops.net",
            name="Robert Williams",
            market="atlanta",
            equipment=["ladder", "cable_tester"],
            certifications=["osha_10"],
            available=True,
            travel_willing=False,
            rating=3.9,
            completed_jobs=32,
        ),
    ],
    "chicago": [
        ProviderInfo(
            provider_id="prov-chi-001",
            email="david.martinez@windycitytech.com",
            name="David Martinez",
            market="chicago",
            equipment=["bucket_truck", "spectrum_analyzer", "fiber_splicer"],
            certifications=["comptia_network_plus", "bicsi", "osha_10"],
            available=True,
            travel_willing=True,
            rating=4.7,
            completed_jobs=156,
        ),
        ProviderInfo(
            provider_id="prov-chi-002",
            email="jennifer.lee@lakeshoreservices.net",
            name="Jennifer Lee",
            market="chicago",
            equipment=["bucket_truck", "otdr"],
            certifications=["bicsi", "fcc_license"],
            available=True,
            travel_willing=True,
            rating=4.6,
            completed_jobs=98,
        ),
        ProviderInfo(
            provider_id="prov-chi-003",
            email="james.wilson@midwestnet.com",
            name="James Wilson",
            market="chicago",
            equipment=["spectrum_analyzer", "cable_tester", "ladder"],
            certifications=["comptia_network_plus"],
            available=True,
            travel_willing=False,
            rating=4.3,
            completed_jobs=67,
        ),
        ProviderInfo(
            provider_id="prov-chi-004",
            email="amanda.brown@techconnect.net",
            name="Amanda Brown",
            market="chicago",
            equipment=["bucket_truck", "spectrum_analyzer"],
            certifications=["osha_10", "osha_30"],
            available=True,
            travel_willing=True,
            rating=4.4,
            completed_jobs=112,
        ),
        ProviderInfo(
            provider_id="prov-chi-005",
            email="chris.taylor@signalworks.com",
            name="Chris Taylor",
            market="chicago",
            equipment=["fiber_splicer", "otdr"],
            certifications=["bicsi"],
            available=False,  # Not currently available
            travel_willing=True,
            rating=4.1,
            completed_jobs=54,
        ),
    ],
    "milwaukee": [
        ProviderInfo(
            provider_id="prov-mil-001",
            email="tom.anderson@brewcitytech.com",
            name="Tom Anderson",
            market="milwaukee",
            equipment=["bucket_truck", "spectrum_analyzer", "ladder"],
            certifications=["comptia_network_plus", "osha_10"],
            available=True,
            travel_willing=True,
            rating=4.6,
            completed_jobs=89,
        ),
        ProviderInfo(
            provider_id="prov-mil-002",
            email="emily.white@lakefrontservices.net",
            name="Emily White",
            market="milwaukee",
            equipment=["bucket_truck", "fiber_splicer"],
            certifications=["bicsi", "osha_10"],
            available=True,
            travel_willing=False,
            rating=4.4,
            completed_jobs=71,
        ),
        ProviderInfo(
            provider_id="prov-mil-003",
            email="kevin.murphy@midwestsolutions.com",
            name="Kevin Murphy",
            market="milwaukee",
            equipment=["spectrum_analyzer", "cable_tester", "otdr"],
            certifications=["comptia_network_plus", "fcc_license"],
            available=True,
            travel_willing=True,
            rating=4.7,
            completed_jobs=145,
        ),
        ProviderInfo(
            provider_id="prov-mil-004",
            email="stephanie.garcia@wistech.net",
            name="Stephanie Garcia",
            market="milwaukee",
            equipment=["bucket_truck"],
            certifications=["osha_10"],
            available=True,
            travel_willing=True,
            rating=4.0,
            completed_jobs=28,
        ),
        ProviderInfo(
            provider_id="prov-mil-005",
            email="brian.clark@signalexperts.com",
            name="Brian Clark",
            market="milwaukee",
            equipment=["bucket_truck", "spectrum_analyzer", "fiber_splicer"],
            certifications=["bicsi", "comptia_network_plus", "osha_10"],
            available=True,
            travel_willing=True,
            rating=4.8,
            completed_jobs=178,
        ),
    ],
}


def _score_provider(
    provider: ProviderInfo,
    requirements: CampaignRequirements,
) -> float:
    """
    Score a provider based on campaign requirements.
    
    Higher scores indicate better fit.
    
    Args:
        provider: Provider to score
        requirements: Campaign requirements
        
    Returns:
        Score from 0.0 to 100.0
    """
    score = 0.0
    
    # Base score from rating (0-25 points)
    score += provider.rating * 5
    
    # Experience bonus (0-25 points)
    experience_score = min(provider.completed_jobs / 8, 25)
    score += experience_score
    
    # Equipment match (0-25 points)
    if requirements.required_equipment:
        matched = sum(
            1 for eq in requirements.required_equipment
            if eq in provider.equipment
        )
        equipment_score = (matched / len(requirements.required_equipment)) * 25
        score += equipment_score
    else:
        score += 25  # Full points if no equipment required
    
    # Certification match (0-15 points)
    if requirements.required_certifications:
        matched = sum(
            1 for cert in requirements.required_certifications
            if cert in provider.certifications
        )
        cert_score = (matched / len(requirements.required_certifications)) * 15
        score += cert_score
    else:
        score += 15  # Full points if no certifications required
    
    # Travel bonus (0-5 points)
    if requirements.travel_required:
        if provider.travel_willing:
            score += 5
        else:
            score -= 10  # Penalty for not willing when required
    else:
        score += 5  # Full points if travel not required
    
    # Optional equipment bonus (0-5 points)
    if requirements.optional_equipment:
        matched = sum(
            1 for eq in requirements.optional_equipment
            if eq in provider.equipment
        )
        optional_score = (matched / len(requirements.optional_equipment)) * 5
        score += optional_score
    
    return max(0.0, min(100.0, score))


def _filter_providers(
    providers: list[ProviderInfo],
    requirements: CampaignRequirements,
) -> list[ProviderInfo]:
    """
    Filter providers based on hard requirements.
    
    Args:
        providers: List of candidate providers
        requirements: Campaign requirements
        
    Returns:
        Filtered list of qualifying providers
    """
    filtered = []
    
    for provider in providers:
        # Must be available
        if not provider.available:
            continue
        
        # Must have all required equipment
        if requirements.required_equipment:
            if not all(eq in provider.equipment for eq in requirements.required_equipment):
                continue
        
        # Must have all required certifications
        if requirements.required_certifications:
            if not all(cert in provider.certifications for cert in requirements.required_certifications):
                continue
        
        # Must be willing to travel if required
        if requirements.travel_required and not provider.travel_willing:
            continue
        
        filtered.append(provider)
    
    return filtered


def select_providers(
    requirements: CampaignRequirements,
    market: str,
) -> ProviderSelection:
    """
    Select providers for a specific market based on campaign requirements.
    
    This function queries the provider database (or mock data), filters
    by requirements, scores candidates, and returns the top N.
    
    Args:
        requirements: Campaign requirements
        market: Target market
        
    Returns:
        ProviderSelection with selected providers
    """
    config = get_campaign_planner_config()
    market_lower = market.lower()
    
    log.info(
        "selecting_providers",
        campaign_id=requirements.campaign_id,
        market=market,
        providers_needed=requirements.providers_per_market,
    )
    
    # Get candidate providers for market
    if config.use_mock_providers:
        candidates = MOCK_PROVIDERS.get(market_lower, [])
    else:
        # TODO: Query real ProviderDatabase table
        log.warning("real_provider_database_not_implemented", market=market)
        candidates = []
    
    total_available = len([p for p in candidates if p.available])
    
    # Filter by hard requirements
    qualified = _filter_providers(candidates, requirements)
    
    log.debug(
        "providers_after_filter",
        market=market,
        total_candidates=len(candidates),
        qualified=len(qualified),
    )
    
    # Score and rank
    scored = [
        (provider, _score_provider(provider, requirements))
        for provider in qualified
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    
    # Select top N
    limit = min(requirements.providers_per_market, len(scored))
    selected = [provider for provider, _ in scored[:limit]]
    
    log.info(
        "providers_selected",
        campaign_id=requirements.campaign_id,
        market=market,
        selected=len(selected),
        requested=requirements.providers_per_market,
    )
    
    if len(selected) < requirements.providers_per_market:
        log.warning(
            "insufficient_providers",
            campaign_id=requirements.campaign_id,
            market=market,
            selected=len(selected),
            requested=requirements.providers_per_market,
        )
    
    return ProviderSelection(
        market=market,
        providers=selected,
        total_available=total_available,
        selection_reason=f"Top {limit} providers by score from {len(qualified)} qualified candidates",
    )


def batch_create_provider_records(
    campaign_id: str,
    providers: list[ProviderInfo],
    *,
    required_documents: list[str] | None = None,
) -> list[ProviderState]:
    """
    Create DynamoDB records for selected providers.
    
    This is idempotent - existing records are returned unchanged.
    
    Args:
        campaign_id: Campaign identifier
        providers: List of selected providers
        required_documents: Document types required for screening
        
    Returns:
        List of created/existing ProviderState records
    """
    created = []
    
    log.info(
        "creating_provider_records",
        campaign_id=campaign_id,
        count=len(providers),
    )
    
    for provider in providers:
        state = create_provider_record(
            campaign_id=campaign_id,
            provider_id=provider.provider_id,
            provider_email=provider.email,
            provider_market=provider.market,
            provider_name=provider.name,
            status=ProviderStatus.INVITED,
            documents_pending=required_documents or [],
        )
        created.append(state)
    
    log.info(
        "provider_records_created",
        campaign_id=campaign_id,
        count=len(created),
    )
    
    return created


def build_send_message_events(
    campaign_id: str,
    providers: list[ProviderInfo],
    requirements: CampaignRequirements,
    *,
    trace_context: TraceContext | None = None,
) -> list[SendMessageRequestedEvent]:
    """
    Build SendMessageRequested events for selected providers.
    
    Args:
        campaign_id: Campaign identifier
        providers: List of selected providers
        requirements: Campaign requirements for template data
        trace_context: Trace context to propagate
        
    Returns:
        List of SendMessageRequestedEvent objects
    """
    events = []
    
    # Format requirements for template
    equipment_list = ", ".join(requirements.required_equipment) if requirements.required_equipment else "None"
    insurance_req = f"${requirements.insurance_min_coverage:,}" if requirements.insurance_min_coverage else "Standard"
    
    for provider in providers:
        template_data = TemplateData(
            campaign_type=requirements.campaign_type,
            market=provider.market,
            equipment_list=equipment_list,
            insurance_requirement=insurance_req,
        )
        
        event = SendMessageRequestedEvent(
            campaign_id=campaign_id,
            provider_id=provider.provider_id,
            provider_email=provider.email,
            provider_name=provider.name,
            provider_market=provider.market,
            message_type=MessageType.INITIAL_OUTREACH,
            template_data=template_data,
            trace_context=trace_context,
        )
        events.append(event)
    
    return events


def emit_send_message_events(
    events: list[SendMessageRequestedEvent],
) -> list[str]:
    """
    Emit SendMessageRequested events to EventBridge.
    
    Uses batch operations with max 10 events per call.
    
    Args:
        events: List of events to emit
        
    Returns:
        List of EventBridge event IDs
        
    Raises:
        EventPublishError: If publication fails
    """
    if not events:
        return []
    
    settings = get_settings()
    source = f"{settings.eventbridge_source_prefix}.agents.campaign_planner"
    
    log.info(
        "emitting_send_message_events",
        count=len(events),
    )
    
    event_ids = send_events_batch(events, source=source)
    
    log.info(
        "send_message_events_emitted",
        count=len(event_ids),
    )
    
    return event_ids


def parse_campaign_requirements(
    campaign_id: str,
    buyer_id: str,
    requirements: Requirements,
) -> CampaignRequirements:
    """
    Parse Requirements from event into CampaignRequirements.
    
    Transforms the event schema into the agent's internal model.
    
    Args:
        campaign_id: Campaign identifier
        buyer_id: Buyer identifier
        requirements: Requirements from NewCampaignRequested event
        
    Returns:
        CampaignRequirements for provider selection
    """
    return CampaignRequirements(
        campaign_id=campaign_id,
        buyer_id=buyer_id,
        campaign_type=requirements.type,
        markets=requirements.markets,
        providers_per_market=requirements.providers_per_market,
        required_equipment=requirements.equipment.required,
        optional_equipment=requirements.equipment.optional,
        required_documents=requirements.documents.required,
        insurance_min_coverage=requirements.documents.insurance_min_coverage or 0,
        required_certifications=requirements.certifications.required,
        preferred_certifications=requirements.certifications.preferred,
        travel_required=requirements.travel_required,
    )
