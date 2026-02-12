'use client';

import { useParams } from 'next/navigation';
import { useCampaign } from '@/hooks/useCampaign';
import ProviderInbox from '@/components/ProviderInbox';
import EventStream from '@/components/EventStream';
import { STATUS_COLORS, STATUS_LABELS, CAMPAIGN_STATUS_COLORS, PROVIDER_STATUS_ORDER } from '@/lib/types';

export default function CampaignPage() {
  const params = useParams();
  const campaignId = params.id as string;
  const { campaign, loading, error, refresh } = useCampaign(campaignId);

  if (loading && !campaign) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-60" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-20 border border-red-40 text-red-80 px-6 py-4 rounded-lg">
        <h3 className="font-medium">Error loading campaign</h3>
        <p className="text-sm mt-1">{error}</p>
        <button onClick={refresh} className="text-sm underline mt-2">Retry</button>
      </div>
    );
  }

  if (!campaign) return null;

  const campaignStatusColor = CAMPAIGN_STATUS_COLORS[campaign.status] || 'bg-gray-20 text-gray-80';

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <a href="/" className="text-gray-60 hover:text-gray-80 text-sm">&larr; Back</a>
          </div>
          <div className="flex items-center gap-3 mt-1">
            <h1 className="text-2xl font-bold text-primary">{campaignId}</h1>
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${campaignStatusColor}`}>
              {campaign.status}
            </span>
          </div>
          <p className="text-gray-70 text-sm">
            {campaign.total_providers} providers across{' '}
            {new Set(campaign.providers.map((p) => p.market)).size} markets
            {campaign.campaign_type && ` \u00b7 ${campaign.campaign_type}`}
          </p>
          {campaign.created_at && (
            <p className="text-xs text-gray-60 mt-0.5">
              Created {new Date(campaign.created_at).toLocaleString()}
            </p>
          )}
        </div>
        <button
          onClick={refresh}
          className="bg-white border border-gray-40 hover:bg-gray-20 text-gray-80 font-medium py-2 px-4 rounded-lg transition-colors text-sm flex items-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </button>
      </div>

      {/* Status Metrics - Invited = providers we sent first mail to; others = backend counts */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        {PROVIDER_STATUS_ORDER.map((status) => {
          const rawCount = campaign.status_breakdown[status] ?? 0;
          const count =
            status === 'INVITED'
              ? campaign.total_providers - (campaign.status_breakdown['INVITED'] ?? 0)
              : rawCount;
          const color = STATUS_COLORS[status] ?? 'bg-gray-20 text-gray-80';
          const label = STATUS_LABELS[status] ?? status;
          return (
            <div key={status} className="bg-white rounded-xl shadow-sm border border-gray-30 p-3 text-center">
              <p className="text-2xl font-bold text-primary">{count}</p>
              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium mt-1 ${color}`}>
                {label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Provider Inbox + Event Stream side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Provider Inbox (WhatsApp-style) */}
        <div className="lg:col-span-3 space-y-3">
          <h2 className="text-lg font-semibold text-primary">
            Provider Inbox
            <span className="text-sm font-normal text-gray-70 ml-2">
              Select a provider to view conversation
            </span>
          </h2>
          <ProviderInbox
            providers={campaign.providers}
            campaignId={campaignId}
            onSimulated={refresh}
          />
        </div>

        {/* Event Stream */}
        <div className="lg:col-span-1">
          <EventStream />
        </div>
      </div>
    </div>
  );
}
