'use client';

import { useState } from 'react';
import { Provider, STATUS_LABELS, STATUS_COLORS } from '@/lib/types';
import SimulateResponseModal from './SimulateResponseModal';
import ConversationModal from './ConversationModal';

interface ProviderCardProps {
  provider: Provider;
  campaignId: string;
  onSimulated: () => void;
}

export default function ProviderCard({ provider, campaignId, onSimulated }: ProviderCardProps) {
  const [showSimModal, setShowSimModal] = useState(false);
  const [showConvoModal, setShowConvoModal] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  const statusColor = STATUS_COLORS[provider.status] ?? 'bg-gray-20 text-gray-80';
  const statusLabel = STATUS_LABELS[provider.status] ?? provider.status;

  return (
    <>
      <div
        className="bg-white rounded-xl shadow-sm border border-gray-30 p-5 hover:shadow-md transition-shadow cursor-pointer"
        onClick={() => setShowConvoModal(true)}
      >
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="font-semibold text-primary">{provider.name || provider.provider_id}</h3>
            <p className="text-sm text-gray-70">{provider.email}</p>
          </div>
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusColor}`}>
            {statusLabel}
          </span>
        </div>

        <div className="flex items-center gap-2 mb-3">
          <span className="inline-flex items-center px-2 py-0.5 bg-gray-20 text-gray-70 rounded text-xs">
            {provider.market}
          </span>
          <span className="text-xs text-gray-60">{provider.provider_id}</span>
        </div>

        {(provider.equipment_confirmed?.length > 0 || provider.documents_uploaded?.length > 0) && (
          <div className="mb-3 space-y-1">
            {provider.equipment_confirmed?.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {provider.equipment_confirmed.map((eq) => (
                  <span key={eq} className="inline-flex items-center px-2 py-0.5 bg-green-20 text-green-80 rounded text-xs">
                    {eq.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            )}
            {provider.documents_uploaded?.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {provider.documents_uploaded.map((doc) => (
                  <span key={doc} className="inline-flex items-center px-2 py-0.5 bg-blue-20 text-blue-80 rounded text-xs">
                    {doc.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {provider.screening_notes && (
          <button
            onClick={(e) => { e.stopPropagation(); setShowDetails(!showDetails); }}
            className="text-xs text-blue-60 hover:text-blue-80 mb-2"
          >
            {showDetails ? 'Hide notes' : 'Show screening notes'}
          </button>
        )}

        {showDetails && provider.screening_notes && (
          <p className="text-xs text-gray-80 bg-gray-20 rounded-lg p-2 mb-3">{provider.screening_notes}</p>
        )}

        <div className="flex gap-2 mt-2">
          <button
            onClick={(e) => { e.stopPropagation(); setShowConvoModal(true); }}
            className="flex-1 bg-gray-20 hover:bg-gray-30 text-gray-80 font-medium py-2 px-3 rounded-lg transition-colors text-xs"
          >
            View Conversation
          </button>
          {(provider.status === 'WAITING_RESPONSE' || provider.status === 'WAITING_DOCUMENT') && (
            <button
              onClick={(e) => { e.stopPropagation(); setShowSimModal(true); }}
              className="flex-1 bg-indigo-20 hover:bg-indigo-40 text-indigo-80 font-medium py-2 px-3 rounded-lg transition-colors text-xs"
            >
              Simulate Response
            </button>
          )}
        </div>
      </div>

      {showSimModal && (
        <SimulateResponseModal
          campaignId={campaignId}
          provider={provider}
          onClose={() => setShowSimModal(false)}
          onSimulated={() => {
            setShowSimModal(false);
            onSimulated();
          }}
        />
      )}

      {showConvoModal && (
        <ConversationModal
          campaignId={campaignId}
          provider={provider}
          onClose={() => setShowConvoModal(false)}
        />
      )}
    </>
  );
}
