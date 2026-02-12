'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { chatCampaignAssistant } from '@/lib/api';
import {
  ChatMessage,
  CampaignFormData,
  CampaignChatRequest,
  CampaignChatResponse,
} from '@/lib/types';

interface UseCampaignChatOptions {
  currentFormData: CampaignFormData;
  onFieldsExtracted: (fields: Partial<CampaignFormData>) => void;
}

export function useCampaignChat({ currentFormData, onFieldsExtracted }: UseCampaignChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content: "Hi! I'm here to help you create a campaign. Please tell me about your campaign requirements, including the Buyer ID, campaign type, markets, and other details.",
      timestamp: new Date(),
    },
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Use ref to always have latest messages for API calls
  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const sendMessage = useCallback(
    async (message: string) => {
      if (!message.trim() || loading) return;

      const userMessage: ChatMessage = {
        role: 'user',
        content: message.trim(),
        timestamp: new Date(),
      };

      // Add user message to UI immediately
      setMessages((prev) => [...prev, userMessage]);
      setLoading(true);
      setError(null);

      try {
        // Use ref to get messages before the new user message was added
        const conversationHistory = messagesRef.current;

        const request: CampaignChatRequest = {
          message: userMessage.content,
          conversation_history: conversationHistory, // Messages before adding userMessage
          current_form_data: currentFormData,
        };

        const response: CampaignChatResponse = await chatCampaignAssistant(request);

        // Add assistant response
        const assistantMessage: ChatMessage = {
          role: 'assistant',
          content: response.message,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, assistantMessage]);

        // Extract and apply fields to form
        if (response.extracted_fields) {
          const formUpdates: Partial<CampaignFormData> = {};

          if (response.extracted_fields.campaignType) {
            formUpdates.campaignType = response.extracted_fields.campaignType;
          }
          if (response.extracted_fields.markets && response.extracted_fields.markets.length > 0) {
            formUpdates.markets = response.extracted_fields.markets.join(', ');
          }
          if (response.extracted_fields.providersPerMarket !== undefined) {
            formUpdates.providersPerMarket = response.extracted_fields.providersPerMarket;
          }
          if (response.extracted_fields.requiredEquipment && response.extracted_fields.requiredEquipment.length > 0) {
            formUpdates.requiredEquipment = response.extracted_fields.requiredEquipment.join(', ');
          }
          if (response.extracted_fields.requiredDocuments && response.extracted_fields.requiredDocuments.length > 0) {
            formUpdates.requiredDocuments = response.extracted_fields.requiredDocuments.join(', ');
          }
          if (response.extracted_fields.insuranceMinCoverage !== undefined) {
            formUpdates.insuranceMinCoverage = response.extracted_fields.insuranceMinCoverage;
          }
          if (response.extracted_fields.travelRequired !== undefined) {
            formUpdates.travelRequired = response.extracted_fields.travelRequired;
          }
          if (response.extracted_fields.buyer_id) {
            formUpdates.buyer_id = response.extracted_fields.buyer_id;
          }

          // Only update if there are actual changes
          if (Object.keys(formUpdates).length > 0) {
            onFieldsExtracted(formUpdates);
          }
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to send message';
        setError(errorMessage);
        const errorMsg: ChatMessage = {
          role: 'assistant',
          content: `Sorry, I encountered an error: ${errorMessage}. Please try again.`,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMsg]);
      } finally {
        setLoading(false);
      }
    },
    [currentFormData, loading, onFieldsExtracted]
  );

  const clearChat = useCallback(() => {
    setMessages([
      {
        role: 'assistant',
        content: "Hi! I'm here to help you create a campaign. Please tell me about your campaign requirements, including the Buyer ID, campaign type, markets, and other details.",
        timestamp: new Date(),
      },
    ]);
    setError(null);
  }, []);

  return {
    messages,
    loading,
    error,
    sendMessage,
    clearChat,
  };
}
