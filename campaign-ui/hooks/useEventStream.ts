'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { EventItem } from '@/lib/types';
import { getEventStreamUrl } from '@/lib/api';

export function useEventStream() {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const pausedRef = useRef(false);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = new EventSource(getEventStreamUrl());
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnected(true);
    };

    es.onmessage = (event) => {
      if (pausedRef.current) return;
      try {
        const data = JSON.parse(event.data) as EventItem;
        setEvents((prev) => [...prev, data]);
      } catch (e) {
        console.error('Failed to parse event:', e);
      }
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
      // Reconnect after 3 seconds
      setTimeout(connect, 3000);
    };

    return es;
  }, []);

  useEffect(() => {
    const es = connect();
    return () => {
      es?.close();
      eventSourceRef.current?.close();
    };
  }, [connect]);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  const togglePause = useCallback(() => {
    setPaused((prev) => !prev);
  }, []);

  return { events, connected, paused, togglePause, clearEvents };
}
