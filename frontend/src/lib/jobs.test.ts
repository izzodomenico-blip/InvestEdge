import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiPost, type JobOut } from "./api";
import { cancelJob, getBacktestJobResult, getInlineJobResult, waitForJob } from "./jobs";

function job(status: JobOut["status"], overrides: Partial<JobOut> = {}): JobOut {
  return { id: 11, kind: "BACKTEST", status, params: {}, progress: 0, result: null,
    result_ref: null, error_code: null, error_message: null, cancel_requested: false,
    created_at: "2026-10-10T10:00:00Z", started_at: null, finished_at: null, ...overrides };
}
function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}
const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  vi.useFakeTimers();
  fetchMock.mockReset().mockRejectedValue(new Error("UNEXPECTED_OFFLINE_REQUEST"));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("job polling offline", () => {
  it("attende sequenzialmente QUEUED/RUNNING, restituisce SUCCEEDED e pulisce il timer", async () => {
    const done = job("SUCCEEDED", { progress: 1 });
    fetchMock.mockResolvedValueOnce(response(job("RUNNING", { progress: 0.5 })))
      .mockResolvedValueOnce(response(done));
    const update = vi.fn();
    const result = waitForJob(job("QUEUED"), { signal: new AbortController().signal, onUpdate: update });
    expect(fetchMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    expect(update.mock.calls.map(([item]) => item.status)).toEqual(["QUEUED", "RUNNING"]);
    await vi.advanceTimersByTimeAsync(1000);
    expect(await result).toEqual(done);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("accetta il terminale del POST senza ulteriori GET", async () => {
    const done = job("SUCCEEDED");
    expect(await waitForJob(done, { signal: new AbortController().signal })).toEqual(done);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["FAILED", "Periodo insufficiente."],
    ["CANCELLED", "Elaborazione annullata."],
    ["INTERRUPTED", "Elaborazione interrotta"],
  ] as const)("ferma il polling sul terminale %s", async (status, message) => {
    fetchMock.mockResolvedValue(response(job(status, { error_code: "LAB_PERIOD_TOO_SHORT",
      error_message: status === "FAILED" ? message : null })));
    const rejected = expect(waitForJob(job("RUNNING"), { signal: new AbortController().signal }))
      .rejects.toThrow(message);
    await vi.advanceTimersByTimeAsync(1000);
    await rejected;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("interrompe un'attesa senza richiedere o cancellare il job remoto", async () => {
    const controller = new AbortController();
    const rejected = expect(waitForJob(job("QUEUED"), { signal: controller.signal }))
      .rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await rejected;
    expect(fetchMock).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("trasmette AbortSignal al GET pendente e interrompe il polling", async () => {
    const controller = new AbortController();
    fetchMock.mockImplementation((_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    const rejected = expect(waitForJob(job("RUNNING"), { signal: controller.signal }))
      .rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal);
    controller.abort();
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("non sovrappone richieste mentre un GET è pendente", async () => {
    let finish!: (value: Response) => void;
    fetchMock.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const result = waitForJob(job("RUNNING"), { signal: new AbortController().signal });
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(10000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    finish(response(job("SUCCEEDED")));
    await result;
  });

  it("propaga un errore di polling senza riprovare indefinitamente", async () => {
    fetchMock.mockRejectedValue(new Error("Connessione interrotta"));
    const rejected = expect(waitForJob(job("RUNNING"), { signal: new AbortController().signal }))
      .rejects.toThrow("Connessione interrotta");
    await vi.advanceTimersByTimeAsync(1000);
    await rejected;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("annulla cooperativamente senza trattare RUNNING come CANCELLED", async () => {
    fetchMock.mockResolvedValue(response(job("RUNNING", { cancel_requested: true })));
    const result = await cancelJob(11, new AbortController().signal);
    expect(result.status).toBe("RUNNING");
    expect(result.cancel_requested).toBe(true);
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST");
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/lab\/jobs\/11\/cancel$/);
  });

  it("risolve la race 409 JOB_NOT_CANCELLABLE rileggendo il terminale reale", async () => {
    fetchMock.mockResolvedValueOnce(response({ detail: { reason_code: "JOB_NOT_CANCELLABLE" } }, 409))
      .mockResolvedValueOnce(response(job("SUCCEEDED")));
    expect((await cancelJob(11, new AbortController().signal)).status).toBe("SUCCEEDED");
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/lab\/jobs\/11$/);
  });

  it("propaga gli errori cancel diversi dalla race di completamento", async () => {
    fetchMock.mockResolvedValue(response({ detail: "Job non trovato." }, 404));
    await expect(cancelJob(11, new AbortController().signal)).rejects.toThrow("Job non trovato.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("legge il BACKTEST dal riferimento e rifiuta riferimenti mancanti o discordanti", async () => {
    fetchMock.mockResolvedValue(response({ backtest_id: 7 }));
    const signal = new AbortController().signal;
    expect(await getBacktestJobResult(job("SUCCEEDED", { result_ref: "7", result: { backtest_id: 7 } }), signal))
      .toEqual({ backtest_id: 7 });
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(signal);
    await expect(getBacktestJobResult(job("SUCCEEDED"), signal)).rejects.toThrow(/riferimento/);
    await expect(getBacktestJobResult(job("SUCCEEDED", { result_ref: "7", result: { backtest_id: 8 } }), signal))
      .rejects.toThrow(/riferimento/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("non presenta il job stesso come risultato inline quando result è nullo", () => {
    expect(() => getInlineJobResult(job("SUCCEEDED", { kind: "COMPARE" }))).toThrow(/risultato/);
    const inline = { entries: [] };
    expect(getInlineJobResult(job("SUCCEEDED", { kind: "COMPARE", result: inline }))).toEqual(inline);
  });

  it("propaga AbortError e AbortSignal anche dal POST iniziale", async () => {
    const controller = new AbortController();
    fetchMock.mockRejectedValue(new DOMException("Aborted", "AbortError"));
    await expect(apiPost("/backtests/run", {}, { signal: controller.signal }))
      .rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal);
  });
});
