'use client';

import { useCallback, useEffect, useState } from 'react';
import { Campaign } from '@/lib/types';
import { getCampaign } from '@/lib/api';

export function useCampaign(campaignId: string | null) {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!campaignId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getCampaign(campaignId);
      setCampaign(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch campaign');
    } finally {
      setLoading(false);
    }
  }, [campaignId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { campaign, loading, error, refresh };
}
