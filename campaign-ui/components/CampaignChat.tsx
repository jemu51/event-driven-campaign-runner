'use client';

import { useState, useRef, useEffect } from 'react';
import { useCampaignChat } from '@/hooks/useCampaignChat';
import { CampaignFormData } from '@/lib/types';

// Helper function to format time consistently (avoid hydration mismatch)
function formatTime(date: Date): string {
  const hours = date.getHours().toString().padStart(2, '0');
  const minutes = date.getMinutes().toString().padStart(2, '0');
  return `${hours}:${minutes}`;
}

interface CampaignChatProps {
  currentFormData: CampaignFormData;
  onFieldsExtracted: (fields: Partial<CampaignFormData>) => void;
}

export default function CampaignChat({ currentFormData, onFieldsExtracted }: CampaignChatProps) {
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { messages, loading, error, sendMessage, clearChat } = useCampaignChat({
    currentFormData,
    onFieldsExtracted,
  });

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputValue.trim() && !loading) {
      sendMessage(inputValue);
      setInputValue('');
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-30 flex flex-col h-[600px]">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-30">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-primary">Campaign Assistant</h3>
          <span className="inline-flex h-2 w-2 rounded-full bg-green-60 animate-pulse" />
        </div>
        <button
          onClick={clearChat}
          className="text-xs px-2.5 py-1 rounded-md border border-gray-40 hover:bg-gray-20 transition-colors text-gray-70"
        >
          Clear
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-lg px-4 py-2 ${
                message.role === 'user'
                  ? 'bg-indigo-60 text-white'
                  : 'bg-gray-20 text-gray-90'
              }`}
            >
              <p className="text-sm whitespace-pre-wrap">{message.content}</p>
              {message.timestamp && (
                <p
                  className={`text-xs mt-1 ${
                    message.role === 'user' ? 'text-indigo-20' : 'text-gray-60'
                  }`}
                >
                  {formatTime(message.timestamp)}
                </p>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-20 text-gray-90 rounded-lg px-4 py-2">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-gray-60 rounded-full animate-bounce" />
                <span className="w-2 h-2 bg-gray-60 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
                <span className="w-2 h-2 bg-gray-60 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Error message */}
      {error && (
        <div className="px-4 pb-2">
          <div className="bg-red-20 border border-red-40 text-red-80 px-3 py-2 rounded-lg text-xs">
            {error}
          </div>
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-gray-30">
        <div className="flex gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Type your message..."
            disabled={loading}
            className="flex-1 px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60 disabled:bg-gray-20 disabled:cursor-not-allowed"
          />
          <button
            type="submit"
            disabled={!inputValue.trim() || loading}
            className="px-4 py-2 bg-indigo-60 hover:bg-indigo-80 disabled:bg-indigo-40 text-white font-medium rounded-lg transition-colors text-sm disabled:cursor-not-allowed"
          >
            Send
          </button>
        </div>
        <p className="text-xs text-gray-60 mt-2">
          Tell me about your campaign requirements, and I'll help fill out the form.
        </p>
      </form>
    </div>
  );
}
