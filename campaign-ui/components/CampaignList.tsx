'use client';

import { useEffect, useState, useCallback } from 'react';
import { CampaignSummary, CAMPAIGN_STATUS_COLORS, STATUS_COLORS, STATUS_LABELS, PROVIDER_STATUS_ORDER } from '@/lib/types';
import { listCampaigns } from '@/lib/api';

interface CampaignListProps {
  onSelectCampaign: (campaignId: string) => void;
}

export default function CampaignList({ onSelectCampaign }: CampaignListProps) {
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await listCampaigns();
      setCampaigns(data.campaigns);
    } catch (err) {
      console.error('Failed to load campaigns:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  if (loading && campaigns.length === 0) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-30 p-6">
        <h2 className="text-lg font-semibold text-primary mb-4">Campaigns</h2>
        <div className="flex items-center justify-center py-8">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-60" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-30 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-primary">Campaigns</h2>
        <button
          onClick={refresh}
          className="text-xs px-2.5 py-1 rounded-md border border-gray-40 hover:bg-gray-20 transition-colors text-gray-70"
        >
          Refresh
        </button>
      </div>

      {campaigns.length === 0 ? (
        <p className="text-sm text-gray-60 text-center py-8">
          No campaigns yet. Create one to get started.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {campaigns.map((campaign) => {
            const statusColor = CAMPAIGN_STATUS_COLORS[campaign.status] || 'bg-gray-20 text-gray-80';
            return (
              <button
                key={campaign.campaign_id}
                onClick={() => onSelectCampaign(campaign.campaign_id)}
                className="w-full text-left bg-gray-20 hover:bg-gray-30 rounded-lg p-4 transition-colors border border-gray-30 hover:border-gray-40"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="min-w-0 flex-1">
                    <h3 className="font-medium text-primary text-sm truncate">
                      {campaign.campaign_id}
                    </h3>
                    <p className="text-xs text-gray-70 mt-0.5">
                      {campaign.campaign_type} &middot; {campaign.markets.join(', ')}
                    </p>
                  </div>
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ml-2 whitespace-nowrap ${statusColor}`}>
                    {campaign.status}
                  </span>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs text-gray-70">
                    {campaign.provider_count} providers
                  </span>
                  {PROVIDER_STATUS_ORDER.filter((status) => {
                    const raw = campaign.status_breakdown[status] ?? 0;
                    const count =
                      status === 'INVITED'
                        ? campaign.provider_count - (campaign.status_breakdown['INVITED'] ?? 0)
                        : raw;
                    return count > 0;
                  }).map((status) => {
                    const raw = campaign.status_breakdown[status] ?? 0;
                    const count =
                      status === 'INVITED'
                        ? campaign.provider_count - (campaign.status_breakdown['INVITED'] ?? 0)
                        : raw;
                    const label = STATUS_LABELS[status] ?? status;
                    return (
                      <span
                        key={status}
                        className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs ${STATUS_COLORS[status] ?? 'bg-gray-20 text-gray-70'}`}
                      >
                        {count} {label}
                      </span>
                    );
                  })}
                </div>
                <p className="text-xs text-gray-60 mt-2">
                  Created {new Date(campaign.created_at).toLocaleString()}
                </p>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
