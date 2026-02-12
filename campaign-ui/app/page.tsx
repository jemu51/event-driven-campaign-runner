'use client';

import { Fragment } from 'react';
import { useRouter } from 'next/navigation';
import CampaignList from '@/components/CampaignList';

const FLOW_STEPS = [
  {
    step: 1,
    title: 'Create campaign',
    description: 'Set requirements, markets, and number of providers per market.',
    color: 'indigo',
  },
  {
    step: 2,
    title: 'Invite providers',
    description: 'System sends outreach to providers in each market.',
    color: 'blue',
  },
  {
    step: 3,
    title: 'Responses & documents',
    description: 'Providers reply and upload docs; we process with AI.',
    color: 'teal',
  },
  {
    step: 4,
    title: 'Screening',
    description: 'Review and qualify or reject based on requirements.',
    color: 'green',
  },
  {
    step: 5,
    title: 'Track & manage',
    description: 'View conversations, simulate responses, and monitor status.',
    color: 'gray',
  },
] as const;

export default function HomePage() {
  const router = useRouter();

  const handleSelectCampaign = (campaignId: string) => {
    router.push(`/campaigns/${campaignId}`);
  };

  const handleCreateCampaign = () => {
    router.push('/create');
  };

  return (
    <div className="space-y-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-primary">Campaign Dashboard</h1>
          <p className="text-gray-70 mt-1">
            Create and manage recruitment campaigns with AI-powered automation
          </p>
        </div>
        <button
          onClick={handleCreateCampaign}
          className="bg-indigo-60 hover:bg-indigo-80 text-white font-medium py-3 px-6 rounded-lg transition-colors text-base shadow-sm shrink-0"
        >
          Create New Campaign
        </button>
      </div>

      {/* How it works */}
      <section className="bg-white rounded-xl shadow-sm border border-gray-30 p-4">
        <h2 className="text-base font-semibold text-primary mb-0.5">How it works</h2>
        <p className="text-xs text-gray-70 mb-4">
          End-to-end flow from campaign creation to provider qualification
        </p>
        <div className="flex flex-col sm:flex-row sm:items-start gap-4 sm:gap-3 overflow-x-auto pb-1">
          {FLOW_STEPS.map((item, i) => (
            <Fragment key={item.step}>
              <div className="flex sm:flex-col sm:min-w-[120px] items-center sm:items-start gap-2 flex-1 min-w-0">
                <span
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white
                    ${item.color === 'indigo' ? 'bg-indigo-60' : ''}
                    ${item.color === 'blue' ? 'bg-blue-60' : ''}
                    ${item.color === 'teal' ? 'bg-teal-60' : ''}
                    ${item.color === 'green' ? 'bg-green-60' : ''}
                    ${item.color === 'gray' ? 'bg-gray-80' : ''}
                  `}
                >
                  {item.step}
                </span>
                <div className="flex-1 min-w-0 text-center sm:text-left">
                  <h3 className="text-xs font-medium text-primary leading-tight">{item.title}</h3>
                  <p className="text-[11px] text-gray-70 mt-0.5 leading-snug">{item.description}</p>
                </div>
              </div>
              {i < FLOW_STEPS.length - 1 ? (
                <div
                  className="hidden sm:block shrink-0 w-4 self-center mt-4 border-t border-gray-40 border-dashed"
                  aria-hidden
                />
              ) : null}
            </Fragment>
          ))}
        </div>
      </section>

      {/* Campaign List - Full Width Below */}
      <div className="mt-8">
        <CampaignList onSelectCampaign={handleSelectCampaign} />
      </div>
    </div>
  );
}
