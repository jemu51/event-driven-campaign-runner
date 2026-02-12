'use client';

import { useState, useEffect, useRef } from 'react';
import { Provider, ConversationThread, STATUS_COLORS, STATUS_LABELS } from '@/lib/types';
import { getProviderConversation, simulateProviderResponse, updateProviderStatus } from '@/lib/api';
import SimulateResponseModal from './SimulateResponseModal';

interface ProviderInboxProps {
  providers: Provider[];
  campaignId: string;
  onSimulated: () => void;
}

export default function ProviderInbox({ providers, campaignId, onSimulated }: ProviderInboxProps) {
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(
    providers.length > 0 ? providers[0].provider_id : null
  );
  const [thread, setThread] = useState<ConversationThread | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSimModal, setShowSimModal] = useState(false);
  const [manualReply, setManualReply] = useState('');
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showScreeningNotes, setShowScreeningNotes] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState<string | null>(null);
  const [showStatusModal, setShowStatusModal] = useState(false);
  const [statusNotes, setStatusNotes] = useState('');

  const selectedProvider = providers.find((p) => p.provider_id === selectedProviderId) || null;

  const filteredProviders = providers.filter((p) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      (p.name || '').toLowerCase().includes(q) ||
      p.provider_id.toLowerCase().includes(q) ||
      p.email.toLowerCase().includes(q) ||
      p.market.toLowerCase().includes(q)
    );
  });

  // Fetch conversation when selected provider changes
  useEffect(() => {
    if (!selectedProviderId) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    setThread(null);
    setShowScreeningNotes(false); // Reset screening notes visibility when provider changes

    getProviderConversation(campaignId, selectedProviderId)
      .then((data) => {
        if (!cancelled) setThread(data);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : 'Failed to load conversation');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [campaignId, selectedProviderId]);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [thread]);

  const canSimulate =
    selectedProvider &&
    (selectedProvider.status === 'WAITING_RESPONSE' ||
      selectedProvider.status === 'WAITING_DOCUMENT');

  const refreshConversation = async () => {
    if (!selectedProviderId) return;
    try {
      const data = await getProviderConversation(campaignId, selectedProviderId);
      setThread(data);
    } catch {
      /* ignore */
    }
  };

  const handleManualReply = async () => {
    if (!manualReply.trim() || !selectedProvider) return;
    setSending(true);
    try {
      await simulateProviderResponse({
        campaign_id: campaignId,
        provider_id: selectedProvider.provider_id,
        email_body: manualReply,
        has_attachment: false,
      });
      setManualReply('');
      await refreshConversation();
      onSimulated();
    } catch {
      /* silently fail for now */
    } finally {
      setSending(false);
    }
  };

  const handleStatusUpdate = async (newStatus: 'QUALIFIED' | 'REJECTED' | 'UNDER_REVIEW' | 'ESCALATED') => {
    if (!selectedProvider || updatingStatus) return;
    setUpdatingStatus(newStatus);
    try {
      await updateProviderStatus(
        campaignId,
        selectedProvider.provider_id,
        newStatus,
        statusNotes.trim() || undefined
      );
      setShowStatusModal(false);
      setStatusNotes('');
      onSimulated(); // Refresh the provider list
    } catch (err) {
      console.error('Failed to update provider status:', err);
      alert('Failed to update provider status. Please try again.');
    } finally {
      setUpdatingStatus(null);
    }
  };

  const canManuallyUpdate = selectedProvider && 
    (selectedProvider.status === 'UNDER_REVIEW' || 
     selectedProvider.status === 'ESCALATED' ||
     selectedProvider.status === 'WAITING_RESPONSE' ||
     selectedProvider.status === 'WAITING_DOCUMENT' ||
     selectedProvider.status === 'DOCUMENT_PROCESSING');

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-30 overflow-hidden flex h-[calc(100vh-340px)] min-h-[520px]">
      {/* ─── Provider Sidebar ─── */}
      <div className="w-64 border-r border-gray-30 flex flex-col shrink-0">
        {/* Sidebar header */}
        <div className="p-3 border-b border-gray-30 bg-gray-20">
          <h3 className="text-sm font-semibold text-primary">Providers</h3>
          <p className="text-xs text-gray-60 mb-2">{providers.length} total</p>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search providers…"
            className="w-full px-3 py-1.5 border border-gray-30 rounded-lg text-xs bg-white focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60 outline-none"
          />
        </div>

        {/* Provider list */}
        <div className="flex-1 overflow-y-auto">
          {filteredProviders.length === 0 ? (
            <p className="text-xs text-gray-60 text-center py-8">No providers found.</p>
          ) : (
            filteredProviders.map((provider) => {
              const isSelected = provider.provider_id === selectedProviderId;
              const statusColor = STATUS_COLORS[provider.status] ?? 'bg-gray-20 text-gray-80';
              const statusLabel = STATUS_LABELS[provider.status] ?? provider.status;

              return (
                <div
                  key={provider.provider_id}
                  onClick={() => setSelectedProviderId(provider.provider_id)}
                  className={`px-3 py-3 border-b border-gray-20 cursor-pointer transition-colors ${
                    isSelected
                      ? 'bg-indigo-20/60 border-l-[3px] border-l-indigo-60'
                      : 'hover:bg-gray-10 border-l-[3px] border-l-transparent'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p
                        className={`text-sm font-medium truncate ${
                          isSelected ? 'text-indigo-80' : 'text-primary'
                        }`}
                      >
                        {provider.name || provider.provider_id}
                      </p>
                      <p className="text-[11px] text-gray-60 truncate mt-0.5">
                        {provider.provider_id}
                      </p>
                    </div>
                    <span
                      className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium ml-1 shrink-0 ${statusColor}`}
                    >
                      {statusLabel}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <span className="inline-flex items-center px-1.5 py-0.5 bg-gray-20 text-gray-70 rounded text-[10px]">
                      {provider.market}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ─── Conversation Panel ─── */}
      <div className="flex-1 flex flex-col min-w-0">
        {selectedProvider ? (
          <>
            {/* Conversation header */}
            <div className="px-5 py-3 border-b border-gray-30 bg-gray-20 shrink-0">
              <div className="flex items-center justify-between">
                <div className="min-w-0">
                  <h3 className="text-base font-semibold text-primary truncate">
                    {selectedProvider.name || selectedProvider.provider_id}
                  </h3>
                  <p className="text-xs text-gray-70 truncate">{selectedProvider.email}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0 ml-4">
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      STATUS_COLORS[selectedProvider.status] ?? 'bg-gray-20 text-gray-80'
                    }`}
                  >
                    {STATUS_LABELS[selectedProvider.status] ?? selectedProvider.status}
                  </span>
                  {canManuallyUpdate && (
                    <button
                      onClick={() => setShowStatusModal(true)}
                      className="px-3 py-1.5 text-xs bg-indigo-60 hover:bg-indigo-80 text-white rounded-lg transition-colors font-medium"
                      title="Update provider status"
                    >
                      Update Status
                    </button>
                  )}
                  <button
                    onClick={refreshConversation}
                    className="p-1.5 rounded-lg hover:bg-gray-30 text-gray-60 hover:text-gray-80 transition-colors"
                    title="Refresh conversation"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                      />
                    </svg>
                  </button>
                </div>
              </div>
              {/* Detail chips */}
              <div className="flex flex-wrap items-center gap-2 mt-2">
                <span className="inline-flex items-center px-2 py-0.5 bg-white rounded text-[11px] text-gray-70 border border-gray-30">
                  {selectedProvider.market}
                </span>
                <span className="text-[11px] text-gray-60">{selectedProvider.provider_id}</span>
                {selectedProvider.equipment_confirmed?.length > 0 && (
                  <span className="inline-flex items-center px-2 py-0.5 bg-green-20 text-green-80 rounded text-[10px]">
                    {selectedProvider.equipment_confirmed.length} equipment confirmed
                  </span>
                )}
                {selectedProvider.documents_uploaded?.length > 0 && (
                  <span className="inline-flex items-center px-2 py-0.5 bg-blue-20 text-blue-80 rounded text-[10px]">
                    {selectedProvider.documents_uploaded.length} documents uploaded
                  </span>
                )}
                {selectedProvider.screening_notes && (
                  <button
                    onClick={() => setShowScreeningNotes(!showScreeningNotes)}
                    className="inline-flex items-center px-2 py-0.5 bg-yellow-20 text-yellow-80 rounded text-[10px] hover:bg-yellow-30 transition-colors cursor-pointer"
                  >
                    {showScreeningNotes ? 'Hide screening notes' : 'Has screening notes'}
                  </button>
                )}
              </div>
              {/* Screening notes display */}
              {showScreeningNotes && selectedProvider.screening_notes && (
                <div className="mt-3 pt-3 border-t border-gray-30">
                  <p className="text-xs text-gray-80 bg-white rounded-lg p-3 border border-gray-30 whitespace-pre-wrap">
                    {selectedProvider.screening_notes}
                  </p>
                </div>
              )}
            </div>

            {/* Messages area */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-gray-10">
              {loading ? (
                <div className="flex items-center justify-center py-16">
                  <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-indigo-60" />
                </div>
              ) : error ? (
                <div className="bg-red-20 text-red-80 px-4 py-3 rounded-lg text-sm">{error}</div>
              ) : !thread || thread.messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-gray-50">
                  <svg
                    className="w-12 h-12 mb-3 text-gray-40"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                    />
                  </svg>
                  <p className="text-sm">No messages yet</p>
                  <p className="text-xs text-gray-50 mt-1">
                    Conversation will appear here once emails are exchanged
                  </p>
                </div>
              ) : (
                thread.messages.map((msg, i) => {
                  const isOutbound = msg.direction === 'OUTBOUND';
                  return (
                    <div key={i} className="group">
                      <div className={`flex ${isOutbound ? 'justify-end' : 'justify-start'}`}>
                        <div
                          className={`max-w-[75%] rounded-2xl px-4 py-3 ${
                            isOutbound
                              ? 'bg-indigo-60 text-white rounded-br-md'
                              : 'bg-white text-primary shadow-sm border border-gray-30 rounded-bl-md'
                          }`}
                        >
                          {/* Sender & type */}
                          <div className="flex items-center gap-2 mb-1">
                            <span
                              className={`text-[11px] font-semibold ${
                                isOutbound ? 'text-indigo-20' : 'text-gray-80'
                              }`}
                            >
                              {isOutbound ? 'System' : selectedProvider.name || 'Provider'}
                            </span>
                            <span
                              className={`text-[10px] px-1.5 py-0.5 rounded ${
                                isOutbound ? 'bg-indigo-40/40 text-indigo-20' : 'bg-gray-20 text-gray-60'
                              }`}
                            >
                              {msg.message_type.replace(/_/g, ' ')}
                            </span>
                          </div>
                          {/* Subject */}
                          {msg.subject && (
                            <p
                              className={`text-xs mb-1.5 font-medium ${
                                isOutbound ? 'text-white/80' : 'text-gray-60'
                              }`}
                            >
                              {msg.subject}
                            </p>
                          )}
                          {/* Body */}
                          <p className="text-sm whitespace-pre-wrap leading-relaxed">
                            {msg.body_text}
                          </p>
                          {/* Attachments */}
                          {msg.attachments.length > 0 && (
                            <div
                              className={`mt-2 pt-2 border-t flex flex-wrap gap-1 ${
                                isOutbound ? 'border-indigo-40/50' : 'border-gray-20'
                              }`}
                            >
                              {msg.attachments.map((att, j) => (
                                <span
                                  key={j}
                                  className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-lg ${
                                    isOutbound
                                      ? 'bg-indigo-40/40 text-white'
                                      : 'bg-gray-20 text-gray-80'
                                  }`}
                                >
                                  <svg
                                    className="w-3 h-3"
                                    fill="none"
                                    stroke="currentColor"
                                    viewBox="0 0 24 24"
                                  >
                                    <path
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                      strokeWidth={2}
                                      d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                                    />
                                  </svg>
                                  {att.filename}
                                </span>
                              ))}
                            </div>
                          )}
                          {/* Timestamp */}
                          <p
                            className={`text-[10px] mt-1.5 ${
                              isOutbound ? 'text-indigo-20/80' : 'text-gray-50'
                            }`}
                          >
                            {new Date(msg.timestamp).toLocaleString()}
                          </p>
                        </div>
                      </div>
                      {/* Simulate Response after OUTBOUND messages */}
                      {isOutbound && canSimulate && (
                        <div className="flex justify-end mt-1 mr-2">
                          <button
                            onClick={() => setShowSimModal(true)}
                            className="inline-flex items-center gap-1 text-[11px] text-indigo-60 hover:text-indigo-80 hover:bg-indigo-20 px-2 py-0.5 rounded transition-colors opacity-60 group-hover:opacity-100"
                          >
                            <svg
                              className="w-3 h-3"
                              fill="none"
                              stroke="currentColor"
                              viewBox="0 0 24 24"
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6"
                              />
                            </svg>
                            Simulate Response
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Manual reply input */}
            <div className="px-4 py-3 border-t border-gray-30 bg-white shrink-0">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={manualReply}
                  onChange={(e) => setManualReply(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleManualReply();
                    }
                  }}
                  placeholder="Type a reply as buyer/staff…"
                  disabled={sending}
                  className="flex-1 px-4 py-2.5 border border-gray-30 rounded-full text-sm bg-gray-10 focus:bg-white focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60 outline-none transition-colors disabled:opacity-50"
                />
                <button
                  onClick={handleManualReply}
                  disabled={!manualReply.trim() || sending}
                  className="bg-indigo-60 hover:bg-indigo-80 disabled:bg-gray-40 disabled:text-gray-60 text-white p-2.5 rounded-full transition-colors shrink-0"
                  title="Send reply"
                >
                  {sending ? (
                    <div className="w-5 h-5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  ) : (
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                      />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          </>
        ) : (
          /* Empty state - no provider selected */
          <div className="flex-1 flex items-center justify-center text-gray-50">
            <div className="text-center">
              <svg
                className="w-20 h-20 mx-auto mb-4 text-gray-30"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1}
                  d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                />
              </svg>
              <p className="text-sm font-medium text-gray-60">Select a provider</p>
              <p className="text-xs text-gray-50 mt-1">
                Choose a provider from the list to view their conversation
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Simulate Response Modal */}
      {showSimModal && selectedProvider && (
        <SimulateResponseModal
          campaignId={campaignId}
          provider={selectedProvider}
          onClose={() => setShowSimModal(false)}
          onSimulated={async () => {
            setShowSimModal(false);
            onSimulated();
            await refreshConversation();
          }}
        />
      )}

      {/* Status Update Modal */}
      {showStatusModal && selectedProvider && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-primary mb-2">Update Provider Status</h3>
            <p className="text-sm text-gray-70 mb-4">
              Current status: <span className="font-medium">{STATUS_LABELS[selectedProvider.status] ?? selectedProvider.status}</span>
            </p>
            
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-80 mb-2">
                New Status
              </label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => handleStatusUpdate('QUALIFIED')}
                  disabled={updatingStatus !== null}
                  className="px-4 py-2 text-sm bg-green-60 hover:bg-green-80 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
                >
                  {updatingStatus === 'QUALIFIED' ? 'Qualifying...' : 'Qualify'}
                </button>
                <button
                  onClick={() => handleStatusUpdate('REJECTED')}
                  disabled={updatingStatus !== null}
                  className="px-4 py-2 text-sm bg-red-60 hover:bg-red-80 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
                >
                  {updatingStatus === 'REJECTED' ? 'Rejecting...' : 'Reject'}
                </button>
                <button
                  onClick={() => handleStatusUpdate('UNDER_REVIEW')}
                  disabled={updatingStatus !== null}
                  className="px-4 py-2 text-sm bg-orange-60 hover:bg-orange-80 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
                >
                  {updatingStatus === 'UNDER_REVIEW' ? 'Updating...' : 'Mark for Review'}
                </button>
                <button
                  onClick={() => handleStatusUpdate('ESCALATED')}
                  disabled={updatingStatus !== null}
                  className="px-4 py-2 text-sm bg-teal-60 hover:bg-teal-80 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
                >
                  {updatingStatus === 'ESCALATED' ? 'Escalating...' : 'Escalate'}
                </button>
              </div>
            </div>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-80 mb-2">
                Notes (optional)
              </label>
              <textarea
                value={statusNotes}
                onChange={(e) => setStatusNotes(e.target.value)}
                placeholder="Add notes about this status change..."
                className="w-full px-3 py-2 border border-gray-30 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60 outline-none resize-none"
                rows={3}
              />
            </div>

            <div className="flex gap-2 justify-end">
              <button
                onClick={() => {
                  setShowStatusModal(false);
                  setStatusNotes('');
                }}
                className="px-4 py-2 text-sm border border-gray-40 rounded-lg hover:bg-gray-20 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
