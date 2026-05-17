export type AssetType = "Azione" | "ETF" | "Crypto" | "Bond ETF";
export type Signal = "BUY" | "HOLD" | "REDUCE" | "SELL";

export type WatchAsset = {
  symbol: string;
  name: string;
  type: AssetType;
  price: number;
  change: number;
  signal: Signal;
  score: number;
  exposure: string;
};

export const watchlist: WatchAsset[] = [
  {
    symbol: "MSFT",
    name: "Microsoft Corp.",
    type: "Azione",
    price: 427.18,
    change: 1.84,
    signal: "BUY",
    score: 78,
    exposure: "Core equity",
  },
  {
    symbol: "VWCE",
    name: "Vanguard FTSE All-World",
    type: "ETF",
    price: 122.42,
    change: 0.36,
    signal: "HOLD",
    score: 65,
    exposure: "Global equity",
  },
  {
    symbol: "BTC",
    name: "Bitcoin",
    type: "Crypto",
    price: 67280,
    change: -2.15,
    signal: "REDUCE",
    score: 48,
    exposure: "High volatility",
  },
  {
    symbol: "AGGH",
    name: "iShares Core Global Aggregate Bond",
    type: "Bond ETF",
    price: 5.21,
    change: 0.12,
    signal: "HOLD",
    score: 61,
    exposure: "Defensive income",
  },
  {
    symbol: "NVDA",
    name: "NVIDIA Corp.",
    type: "Azione",
    price: 104.7,
    change: 2.67,
    signal: "BUY",
    score: 82,
    exposure: "Growth equity",
  },
];

export const portfolioPositions = [
  { symbol: "VWCE", type: "ETF", value: 18500, weight: 41, pnl: 7.8 },
  { symbol: "MSFT", type: "Azione", value: 8900, weight: 20, pnl: 12.4 },
  { symbol: "AGGH", type: "Bond ETF", value: 7600, weight: 17, pnl: 1.3 },
  { symbol: "BTC", type: "Crypto", value: 5200, weight: 12, pnl: -4.6 },
  { symbol: "Liquidita", type: "Cash", value: 4500, weight: 10, pnl: 0 },
];

export const equityCurve = [
  { month: "Gen", value: 42100, benchmark: 41800 },
  { month: "Feb", value: 42850, benchmark: 42140 },
  { month: "Mar", value: 41920, benchmark: 41680 },
  { month: "Apr", value: 43800, benchmark: 42780 },
  { month: "Mag", value: 44700, benchmark: 43120 },
  { month: "Giu", value: 46150, benchmark: 43890 },
  { month: "Lug", value: 45640, benchmark: 44230 },
  { month: "Ago", value: 47220, benchmark: 45100 },
  { month: "Set", value: 48140, benchmark: 45520 },
];

export const allocation = [
  { name: "ETF azionari", value: 41, color: "#22D3EE" },
  { name: "Azioni", value: 20, color: "#34D399" },
  { name: "Obbligazionario", value: 17, color: "#60A5FA" },
  { name: "Crypto", value: 12, color: "#F59E0B" },
  { name: "Cash", value: 10, color: "#FB7185" },
];

export const signals = [
  { symbol: "NVDA", signal: "BUY" as Signal, score: 82, reason: "Trend positivo e momentum sopra media." },
  { symbol: "MSFT", signal: "BUY" as Signal, score: 78, reason: "Qualita alta, volatilita controllata." },
  { symbol: "BTC", signal: "REDUCE" as Signal, score: 48, reason: "Peso vicino al limite di rischio." },
  { symbol: "AGGH", signal: "HOLD" as Signal, score: 61, reason: "Stabilizzatore di portafoglio." },
];

export const technicalSeries = [
  { day: "Lun", price: 100, sma: 98, rsi: 52 },
  { day: "Mar", price: 103, sma: 99, rsi: 57 },
  { day: "Mer", price: 101, sma: 100, rsi: 54 },
  { day: "Gio", price: 106, sma: 102, rsi: 61 },
  { day: "Ven", price: 109, sma: 104, rsi: 66 },
  { day: "Lun", price: 112, sma: 106, rsi: 69 },
  { day: "Mar", price: 111, sma: 108, rsi: 64 },
];

export const newsItems = [
  {
    source: "Market Desk",
    title: "I settori tech e healthcare guidano la rotazione verso qualita",
    sentiment: "positivo",
    score: 0.42,
    time: "09:40",
  },
  {
    source: "Macro Brief",
    title: "Rendimenti obbligazionari stabili in attesa dei prossimi dati inflazione",
    sentiment: "neutrale",
    score: 0.04,
    time: "11:15",
  },
  {
    source: "Crypto Wire",
    title: "Volatilita crypto in aumento dopo prese di profitto sui principali asset",
    sentiment: "negativo",
    score: -0.31,
    time: "13:05",
  },
];

export const backtestCurve = [
  { period: "2020", strategy: 10000, benchmark: 10000 },
  { period: "2021", strategy: 11800, benchmark: 11250 },
  { period: "2022", strategy: 10900, benchmark: 10400 },
  { period: "2023", strategy: 13400, benchmark: 12200 },
  { period: "2024", strategy: 15100, benchmark: 13900 },
  { period: "2025", strategy: 16600, benchmark: 14850 },
];
