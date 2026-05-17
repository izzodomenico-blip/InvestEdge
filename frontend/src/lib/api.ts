const API_URL =
  import.meta.env.VITE_API_BASE_URL ??
  import.meta.env.VITE_API_URL ??
  "http://127.0.0.1:8001";

export type Signal = "STRONG_BUY" | "BUY" | "HOLD" | "REDUCE" | "SELL";

export type Reason = {
  type: "positive" | "negative" | "neutral";
  message: string;
};

export type Asset = {
  id: number;
  symbol: string;
  name: string;
  asset_type: string;
  exchange: string | null;
  currency: string;
  sector: string | null;
  country: string | null;
  risk_level: string;
  last_price: number | null;
  daily_change_pct: number | null;
  score: number | null;
  signal: Signal | null;
  confidence: string | null;
  technical_summary: string | null;
  updated_at: string | null;
};

export type SignalRecord = {
  id: number;
  asset_id: number;
  symbol: string;
  signal: Signal;
  score: number;
  risk_level: string | null;
  confidence: string | null;
  technical_summary: string | null;
  reasons: Reason[];
  subscores: Record<string, number>;
  created_at: string;
};

export type DashboardResponse = {
  initialized: boolean;
  message: string | null;
  assets_count: number;
  positions_count: number;
  portfolio_value: number;
  signals_count: number;
  price_points_count: number;
  average_score: number | null;
  asset_type_breakdown: Record<string, number>;
  risk_breakdown: Record<string, number>;
  signal_breakdown: Record<string, number>;
  latest_signals: SignalRecord[];
  top_assets: Asset[];
  weakest_assets: Asset[];
  risky_assets: Asset[];
};

export type PricePoint = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adjusted_close: number;
  volume: number;
  source: string;
  sma_20: number | null;
  sma_50: number | null;
  sma_200: number | null;
  ema_12: number | null;
  ema_26: number | null;
  ema_50: number | null;
  ema_200: number | null;
  rsi_14: number | null;
  macd_line: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  bollinger_upper: number | null;
  bollinger_lower: number | null;
};

export type PriceHistory = {
  symbol: string;
  name: string;
  asset_type: string;
  currency: string;
  prices: PricePoint[];
};

export type TechnicalAnalysis = {
  asset: Asset;
  latest_price: number | null;
  indicators: Record<string, number>;
  conditions: Record<string, boolean>;
  support_resistance: Record<string, number | null>;
  subscores: Record<string, number>;
  score: number;
  signal: Signal;
  risk_level: string;
  confidence: string;
  reasons: Reason[];
  summaries: Record<string, string>;
  technical_summary: string;
};

async function parseError(response: Response) {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    return `API request failed: ${response.status}`;
  }
  return `API request failed: ${response.status}`;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`);

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<T>;
}
