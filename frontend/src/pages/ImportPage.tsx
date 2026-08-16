import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Download, FileSpreadsheet, TriangleAlert } from "lucide-react";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import {
  apiGet,
  apiPost,
  type ImportApplyResult,
  type ImportPreview,
  type ImportStatus,
} from "../lib/api";
import { formatCurrency } from "../lib/format";

export function ImportPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<ImportStatus | null>(null);
  const [csvUrl, setCsvUrl] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [applied, setApplied] = useState<ImportApplyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showApplyConfirmation, setShowApplyConfirmation] = useState(false);
  const [previewInput, setPreviewInput] = useState<{ csv_url: string | null } | null>(null);
  const operationInFlight = useRef(false);
  const discardedRows = preview ? Math.max(0, preview.rows_total - preview.rows_valid) : 0;

  useEffect(() => {
    void apiGet<ImportStatus>("/import/google-sheets/status").then(setStatus).catch(() => null);
  }, []);

  async function runPreview() {
    if (operationInFlight.current) {
      return;
    }
    operationInFlight.current = true;
    const input = { csv_url: csvUrl || null };
    setBusy(true);
    setError(null);
    setApplied(null);
    setShowApplyConfirmation(false);
    setPreviewInput(null);
    try {
      setPreview(await apiPost<ImportPreview>("/import/google-sheets/preview", input));
      setPreviewInput(input);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Anteprima non riuscita.");
      setPreview(null);
    } finally {
      operationInFlight.current = false;
      setBusy(false);
    }
  }

  async function runApply() {
    if (!previewInput || operationInFlight.current) {
      if (operationInFlight.current) {
        return;
      }
      setError("Genera una nuova anteprima prima di sostituire le posizioni.");
      return;
    }
    operationInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<ImportApplyResult>("/import/google-sheets/apply", {
        ...previewInput,
        confirmation_token: preview?.confirmation_token,
      });
      setApplied(result);
      setPreview(null);
      setShowApplyConfirmation(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Importazione non riuscita.");
    } finally {
      operationInFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Dati / portafoglio reale"
        index="09"
        title="Importa da Google Sheets"
        subtitle="Carica le tue posizioni reali da un foglio Google pubblicato in CSV. L'app userà queste posizioni per i consigli e gli alert."
      />

      {error && (
        <div className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      <Panel eyebrow="Passo 1" title="Come preparare il foglio">
        <ol className="list-decimal space-y-2 pl-5 text-sm text-slate-300">
          <li>Nel tuo Google Sheet metti una riga di intestazione con almeno: <span className="font-mono text-cyan-200">symbol</span>, <span className="font-mono text-cyan-200">quantity</span>, <span className="font-mono text-cyan-200">average_price</span> (accettati anche nomi in italiano: simbolo, quantità, prezzo_medio). Opzionali: name, asset_type, currency.</li>
          <li>File → Condividi → Pubblica sul web → scegli il foglio e formato <b>CSV</b> → copia il link.</li>
          <li>Incolla qui sotto il link e premi <b>Anteprima</b>.</li>
        </ol>
        {status && !status.csv_url_set && (
          <p className="mt-3 text-xs text-slate-500">
            Suggerimento: puoi anche salvare il link in <span className="font-mono">backend/.env</span> come <span className="font-mono">GOOGLE_SHEETS_CSV_URL</span> e lasciare vuoto il campo.
          </p>
        )}
      </Panel>

      <Panel eyebrow="Passo 2" title="Link CSV del foglio">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={csvUrl}
            onChange={(event) => {
              setCsvUrl(event.target.value);
              setPreview(null);
              setPreviewInput(null);
              setShowApplyConfirmation(false);
            }}
            disabled={busy}
            placeholder={status?.csv_url_set ? "(uso il link salvato in .env)" : "https://docs.google.com/.../pub?output=csv"}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-sm text-white outline-none focus:border-cyan-300/60"
          />
          <PageHeaderAction
            onClick={() => void runPreview()}
            disabled={busy}
            icon={<FileSpreadsheet className="h-4 w-4" aria-hidden="true" />}
          >
            {busy ? "Lettura..." : "Anteprima"}
          </PageHeaderAction>
        </div>
      </Panel>

      {applied && (
        <Panel eyebrow="Fatto" title="Importazione completata">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-emerald-300" aria-hidden="true" />
            <div>
              <p className="text-sm text-slate-200">
                Importate <b>{applied.imported}</b> posizioni
                {applied.created_assets > 0 && <> ({applied.created_assets} nuovi asset creati)</>}. Valore portafoglio:{" "}
                <span className="num font-semibold text-white">{formatCurrency(applied.portfolio_value, "EUR")}</span>.
              </p>
              {applied.rows_invalid > 0 && (
                <p className="mt-1 text-xs text-amber-300">{applied.rows_invalid} righe ignorate per errori di formato.</p>
              )}
              <button
                onClick={() => navigate("/portfolio")}
                className="mt-3 inline-flex items-center gap-2 rounded-lg border border-cyan-300/30 bg-cyan-400/15 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/25"
              >
                Vai al Portafoglio →
              </button>
            </div>
          </div>
        </Panel>
      )}

      {preview && (
        <Panel
          eyebrow="Passo 3 · Anteprima"
          title={`${preview.rows_valid} posizioni valide su ${preview.rows_total}`}
          action={
            preview.rows_valid > 0 ? (
              <button
                onClick={() => setShowApplyConfirmation(true)}
                disabled={busy}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-cyan-300/40 bg-cyan-400/15 px-4 py-2 text-sm font-medium text-cyan-50 transition hover:border-cyan-300/60 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                Sostituisci le posizioni con l'import
              </button>
            ) : undefined
          }
        >
          {preview.errors.length > 0 && (
            <div className="mb-4 rounded-lg border border-amber-300/20 bg-amber-400/10 p-3 text-xs text-amber-200">
              <div className="mb-1 flex items-center gap-2 font-semibold">
                <TriangleAlert className="h-3.5 w-3.5" aria-hidden="true" /> Righe con problemi
              </div>
              <ul className="space-y-0.5">
                {preview.errors.slice(0, 8).map((err) => (
                  <li key={err}>· {err}</li>
                ))}
              </ul>
            </div>
          )}

          {showApplyConfirmation && (
            <div className="mb-4 rounded-xl border border-rose-300/25 bg-rose-400/[0.08] p-4">
              <p className="text-sm font-semibold text-rose-100">Conferma la sostituzione delle posizioni</p>
              <p className="mt-1 text-sm text-slate-300">
                Tutte le posizioni attuali verranno rimosse e sostituite con {preview.rows_valid}{" "}
                {preview.rows_valid === 1 ? "riga valida" : "righe valide"} dell'import. {discardedRows}{" "}
                {discardedRows === 1 ? "riga verrà scartata" : "righe verranno scartate"}.
              </p>
              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                <button
                  onClick={() => void runApply()}
                  disabled={busy}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-rose-300/30 bg-rose-400/15 px-4 py-2 text-sm font-semibold text-rose-100 transition hover:bg-rose-400/25 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  {busy ? "Sostituzione..." : "Conferma sostituzione posizioni"}
                </button>
                <button
                  onClick={() => setShowApplyConfirmation(false)}
                  disabled={busy}
                  className="inline-flex min-h-11 items-center justify-center rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-slate-800 disabled:opacity-50"
                >
                  Annulla
                </button>
              </div>
            </div>
          )}

          {preview.holdings.length === 0 ? (
            <p className="text-sm text-slate-400">Nessuna posizione valida trovata. Controlla le intestazioni del foglio.</p>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {preview.holdings.map((holding) => (
                <div key={holding.symbol} className="rounded-xl border border-slate-800/60 bg-slate-950/55 p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-semibold text-white">{holding.symbol}</span>
                    <span className="rounded-md border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] text-slate-400">
                      {holding.asset_type}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-xs text-slate-500">{holding.name}</p>
                  <p className="num mt-2 text-sm text-slate-200">
                    {holding.quantity} × {formatCurrency(holding.average_price, holding.currency)}
                  </p>
                </div>
              ))}
            </div>
          )}
          <p className="mt-4 text-xs text-slate-500">
            L'importazione <b>sostituisce</b> le posizioni attuali con quelle del foglio. È un'operazione simulata: non tocca Trade Republic.
          </p>
        </Panel>
      )}
    </div>
  );
}
