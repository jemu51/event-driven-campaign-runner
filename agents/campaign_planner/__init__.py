"""
Campaign Planner Agent

Handler for NewCampaignRequested events. Selects providers per market,
creates DynamoDB records, and emits SendMessageRequested events.
"""

from agents.campaign_planner.agent import handle_new_campaign_requested
from agents.campaign_planner.models import CampaignRequirements, ProviderSelection
from agents.campaign_planner.tools import select_providers, batch_create_provider_records

__all__ = [
    "handle_new_campaign_requested",
    "CampaignRequirements",
    "ProviderSelection",
    "select_providers",
    "batch_create_provider_records",
]
