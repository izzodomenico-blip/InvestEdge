import { apiGet, apiPost, apiReasonCode, type BacktestResult, type JobOut } from "./api";

const POLL_INTERVAL_MS = 1000;

function waitForPoll(signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, POLL_INTERVAL_MS);
    signal.addEventListener("abort", abort, { once: true });
  });
}

/** Un GET alla volta; ogni terminale interrompe il polling. Abort ferma solo il client. */
export async function waitForJob(
  initial: JobOut,
  options: { signal: AbortSignal; onUpdate?: (job: JobOut) => void },
): Promise<JobOut> {
  let job = initial;
  for (;;) {
    options.signal.throwIfAborted();
    options.onUpdate?.(job);
    switch (job.status) {
      case "SUCCEEDED":
        return job;
      case "FAILED":
        throw new Error(job.error_message ?? "Elaborazione non riuscita. Avvia un nuovo calcolo.");
      case "CANCELLED":
        throw new Error("Elaborazione annullata.");
      case "INTERRUPTED":
        throw new Error("Elaborazione interrotta dal riavvio: avvia un nuovo calcolo.");
      case "QUEUED":
      case "RUNNING":
        await waitForPoll(options.signal);
        job = await apiGet<JobOut>("/lab/jobs/" + job.id, { signal: options.signal });
        break;
      default:
        throw new Error("Stato del job non riconosciuto.");
    }
  }
}

/** Il cancel di RUNNING e cooperativo. Se il calcolo e gia terminato si rilegge l'esito reale. */
export async function cancelJob(id: number, signal: AbortSignal): Promise<JobOut> {
  try {
    return await apiPost<JobOut>("/lab/jobs/" + id + "/cancel", undefined, { signal });
  } catch (error) {
    if (apiReasonCode(error) !== "JOB_NOT_CANCELLABLE") throw error;
    return apiGet<JobOut>("/lab/jobs/" + id, { signal });
  }
}

export async function getBacktestJobResult(job: JobOut, signal: AbortSignal): Promise<BacktestResult> {
  const id = Number(job.result_ref);
  const inlineId = job.result?.backtest_id;
  if (job.status !== "SUCCEEDED" || job.kind !== "BACKTEST" ||
      !job.result_ref || !/^[0-9]+$/.test(job.result_ref) || !Number.isSafeInteger(id) || id <= 0 ||
      (inlineId !== undefined && inlineId !== id)) {
    throw new Error("Il job e concluso ma il riferimento al backtest non e valido.");
  }
  return apiGet<BacktestResult>("/backtests/" + id, { signal });
}

export function getInlineJobResult<T>(job: JobOut): T {
  if (job.status !== "SUCCEEDED" || job.result === null) {
    throw new Error("Il job e concluso ma il risultato non e disponibile.");
  }
  return job.result as T;
}
