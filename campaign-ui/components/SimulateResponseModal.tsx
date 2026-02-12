'use client';

import { useState } from 'react';
import { Provider } from '@/lib/types';
import { simulateProviderResponse } from '@/lib/api';

interface SimulateResponseModalProps {
  campaignId: string;
  provider: Provider;
  onClose: () => void;
  onSimulated: () => void;
}

export default function SimulateResponseModal({
  campaignId,
  provider,
  onClose,
  onSimulated,
}: SimulateResponseModalProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [emailBody, setEmailBody] = useState(
    `Yes, I'm interested in this opportunity! I have a bucket truck and spectrum analyzer available. I can travel and am ready to start. Please find my insurance certificate attached.`
  );
  const [hasAttachment, setHasAttachment] = useState(true);
  const [attachmentFilename, setAttachmentFilename] = useState('insurance_certificate.pdf');

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);

    try {
      await simulateProviderResponse({
        campaign_id: campaignId,
        provider_id: provider.provider_id,
        email_body: emailBody,
        has_attachment: hasAttachment,
        attachment_filename: attachmentFilename,
      });
      onSimulated();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to simulate response');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-primary">Simulate Provider Response</h3>
          <button onClick={onClose} className="text-gray-60 hover:text-gray-80 text-xl leading-none">&times;</button>
        </div>

        <div className="text-sm text-gray-80">
          <p>Simulating response from <strong>{provider.name || provider.provider_id}</strong></p>
          <p className="text-xs text-gray-60">{provider.email}</p>
        </div>

        {error && (
          <div className="bg-red-20 border border-red-40 text-red-80 px-4 py-3 rounded-lg text-sm">{error}</div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-80 mb-1">Email Body</label>
          <textarea
            value={emailBody}
            onChange={(e) => setEmailBody(e.target.value)}
            rows={5}
            className="w-full px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60"
          />
        </div>

        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="hasAttachment"
            checked={hasAttachment}
            onChange={(e) => setHasAttachment(e.target.checked)}
            className="h-4 w-4 text-indigo-60 rounded border-gray-40"
          />
          <label htmlFor="hasAttachment" className="text-sm text-gray-80">Include Document Attachment</label>
        </div>

        {hasAttachment && (
          <div>
            <label className="block text-sm font-medium text-gray-80 mb-1">Filename</label>
            <input
              type="text"
              value={attachmentFilename}
              onChange={(e) => setAttachmentFilename(e.target.value)}
              className="w-full px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60"
            />
          </div>
        )}

        <div className="flex gap-3 pt-2">
          <button
            onClick={onClose}
            className="flex-1 bg-gray-20 hover:bg-gray-30 text-gray-80 font-medium py-2.5 px-4 rounded-lg transition-colors text-sm"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={loading || !emailBody.trim()}
            className="flex-1 bg-indigo-60 hover:bg-indigo-80 disabled:bg-indigo-40 text-white font-medium py-2.5 px-4 rounded-lg transition-colors text-sm"
          >
            {loading ? 'Simulating...' : 'Send Response'}
          </button>
        </div>
      </div>
    </div>
  );
}
