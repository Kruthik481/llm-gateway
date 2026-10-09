export type PublicStats = { requests_today: number; cache_hit_rate: number; fallbacks_today: number };

export type KeyRow = {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  requests_24h: number;
};

export type CreatedKey = { id: string; name: string; prefix: string; created_at: string; key: string };

export type Percentiles = { p50: number | null; p95: number | null };

export type UsageSummary = {
  days: { day: string; requests: number; tokens: number }[];
  cost_by_model: { model: string; cost_usd: string }[];
  cache_saved_usd: string;
  providers: { provider: string; requests: number }[];
  fallbacks: number;
  latency_ms: Percentiles;
  ttft_ms: Percentiles;
  budget: { used: number; limit: number };
};

export type RecentRow = {
  created_at: string;
  key_prefix: string;
  model: string;
  provider: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: string;
  cache_hit: boolean;
  status: 'ok' | 'error' | 'partial';
  latency_ms: number;
  ttft_ms: number | null;
  attempts: number;
};

export type GatewayMeta = {
  provider: string;
  cache: 'hit' | 'miss' | 'bypass';
  attempts: number;
  cost_usd: string;
  saved_usd: string;
  ttft_ms: number | null;
};
