'use client';

import { useEventStream } from '@/hooks/useEventStream';

const EVENT_COLORS: Record<string, string> = {
  NewCampaignRequested: 'border-l-blue-60',
  SendMessageRequested: 'border-l-green-60',
  ProviderResponseReceived: 'border-l-yellow-60',
  DocumentProcessed: 'border-l-purple-60',
  ScreeningCompleted: 'border-l-teal-60',
  ReplyToProviderRequested: 'border-l-orange-60',
  FollowUpTriggered: 'border-l-red-60',
};

export default function EventStream() {
  const { events, connected, paused, togglePause, clearEvents } = useEventStream();

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-30 flex flex-col h-full">
      <div className="p-4 border-b border-gray-30">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-primary">Live Events</h3>
          <div className="flex items-center gap-1.5">
            <button
              onClick={togglePause}
              className="text-xs px-2.5 py-1 rounded-md border border-gray-40 hover:bg-gray-20 transition-colors"
            >
              {paused ? 'Resume' : 'Pause'}
            </button>
            <button
              onClick={clearEvents}
              className="text-xs px-2.5 py-1 rounded-md border border-gray-40 hover:bg-gray-20 transition-colors"
            >
              Clear
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-xs text-gray-60">{events.length} events</span>
          <span
            className={`inline-flex h-2 w-2 rounded-full ${
              connected ? 'bg-green-60 animate-pulse' : 'bg-red-60'
            }`}
          />
          <span className="text-xs text-gray-60">
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2 max-h-[500px]">
        {events.length === 0 ? (
          <p className="text-sm text-gray-60 text-center py-8">No events yet. Create a campaign to start.</p>
        ) : (
          [...events].reverse().map((event, i) => {
            const borderColor = EVENT_COLORS[event.type] || 'border-l-gray-40';
            const time = new Date(event.timestamp).toLocaleTimeString();
            return (
              <div
                key={`${event.timestamp}-${i}`}
                className={`border-l-3 ${borderColor} pl-3 py-2 bg-gray-20 rounded-r-lg`}
                style={{ borderLeftWidth: '3px' }}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-80">{event.type}</span>
                  <span className="text-xs text-gray-60">{time}</span>
                </div>
                {event.provider_id && (
                  <p className="text-xs text-gray-70 mt-0.5">{event.provider_id}</p>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
