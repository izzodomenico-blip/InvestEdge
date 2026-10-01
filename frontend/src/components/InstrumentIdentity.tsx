import type { IdentifierScheme, TradeRepublicStatus } from "../lib/api";

type InstrumentIdentityProps = {
  identifierScheme: IdentifierScheme | null;
  identifier: string | null;
  ticker: string | null;
  mic: string | null;
  venueName: string | null;
  currency: string | null;
  tradeRepublicStatus: TradeRepublicStatus;
};

// Lo stato Trade Republic descrive la fonte della conferma, non la negoziabilità.
export const tradeRepublicLabels: Record<TradeRepublicStatus, string> = {
  NEVER_SEEN: "TR: mai visto",
  CATALOGED: "TR: nel catalogo, non verificato",
  VERIFIED: "TR: verificato manualmente",
  UNAVAILABLE: "TR: non disponibile",
};

const tradeRepublicStyles: Record<TradeRepublicStatus, string> = {
  NEVER_SEEN: "border-slate-700 text-slate-500",
  CATALOGED: "border-slate-600 text-slate-300",
  VERIFIED: "border-emerald-300/30 text-emerald-200",
  UNAVAILABLE: "border-rose-300/30 text-rose-200",
};

/** Identificativo primario, venue, valuta e stato Trade Republic di una riga del catalogo. */
export function InstrumentIdentity({
  identifierScheme,
  identifier,
  ticker,
  mic,
  venueName,
  currency,
  tradeRepublicStatus,
}: InstrumentIdentityProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
      {identifier ? (
        <span>
          <span className="text-slate-500">{identifierScheme ?? "ID"}</span>{" "}
          <span className="font-mono text-slate-200">{identifier}</span>
        </span>
      ) : (
        <span className="text-slate-500">Identificativo non verificato</span>
      )}
      {ticker ? (
        <span className="inline-flex items-center gap-1.5">
          <span className="font-mono font-semibold text-white">{ticker}</span>
          {mic && <span className="font-mono text-slate-300">{mic}</span>}
          {venueName && <span className="text-slate-500">{venueName}</span>}
          {currency && <span className="font-mono text-slate-300">{currency}</span>}
        </span>
      ) : (
        <span className="text-slate-500">Listing non risolto</span>
      )}
      <span className={`rounded-md border px-1.5 py-0.5 text-[10px] ${tradeRepublicStyles[tradeRepublicStatus]}`}>
        {tradeRepublicLabels[tradeRepublicStatus]}
      </span>
    </div>
  );
}
