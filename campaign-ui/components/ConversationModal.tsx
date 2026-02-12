'use client';

import { useEffect, useState } from 'react';
import { Provider, ConversationThread } from '@/lib/types';
import { getProviderConversation } from '@/lib/api';

interface ConversationModalProps {
  campaignId: string;
  provider: Provider;
  onClose: () => void;
}

export default function ConversationModal({
  campaignId,
  provider,
  onClose,
}: ConversationModalProps) {
  const [thread, setThread] = useState<ConversationThread | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await getProviderConversation(campaignId, provider.provider_id);
        setThread(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load conversation');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [campaignId, provider.provider_id]);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-30">
          <div>
            <h3 className="text-lg font-semibold text-primary">
              Conversation with {provider.name || provider.provider_id}
            </h3>
            <p className="text-xs text-gray-70">{provider.email} &middot; {provider.market}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-60 hover:text-gray-80 text-2xl leading-none p-1"
          >
            &times;
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-60" />
            </div>
          ) : error ? (
            <div className="bg-red-20 text-red-80 px-4 py-3 rounded-lg text-sm">{error}</div>
          ) : !thread || thread.messages.length === 0 ? (
            <p className="text-sm text-gray-60 text-center py-12">No messages yet.</p>
          ) : (
            thread.messages.map((msg, i) => {
              const isOutbound = msg.direction === 'OUTBOUND';
              return (
                <div
                  key={i}
                  className={`flex ${isOutbound ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-xl px-4 py-3 ${
                      isOutbound
                        ? 'bg-indigo-60 text-white'
                        : 'bg-gray-20 text-primary'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-xs font-medium ${isOutbound ? 'text-indigo-20' : 'text-gray-70'}`}>
                        {isOutbound ? 'System' : provider.name || 'Provider'}
                      </span>
                      <span className={`text-xs ${isOutbound ? 'text-indigo-20' : 'text-gray-60'}`}>
                        {msg.message_type.replace(/_/g, ' ')}
                      </span>
                    </div>
                    <p className={`text-xs mb-1 ${isOutbound ? 'text-white/90' : 'text-gray-70'}`}>
                      {msg.subject}
                    </p>
                    <p className="text-sm whitespace-pre-wrap">{msg.body_text}</p>
                    {msg.attachments.length > 0 && (
                      <div className={`mt-2 pt-2 border-t ${isOutbound ? 'border-indigo-40' : 'border-gray-30'}`}>
                        {msg.attachments.map((att, j) => (
                          <span
                            key={j}
                            className={`inline-flex items-center text-xs px-2 py-0.5 rounded ${
                              isOutbound ? 'bg-indigo-40 text-white' : 'bg-gray-30 text-gray-80'
                            }`}
                          >
                            {att.filename}
                          </span>
                        ))}
                      </div>
                    )}
                    <p className={`text-xs mt-1 ${isOutbound ? 'text-indigo-20' : 'text-gray-60'}`}>
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-gray-30 text-center">
          <span className="text-xs text-gray-60">
            {thread ? `${thread.message_count} message(s)` : ''}
          </span>
        </div>
      </div>
    </div>
  );
}
