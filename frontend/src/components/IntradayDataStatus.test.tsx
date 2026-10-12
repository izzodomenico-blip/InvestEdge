import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../lib/api';
import { IntradayDataStatus } from './IntradayDataStatus';

vi.mock('../lib/api', async (original) => ({ ...await original<typeof import('../lib/api')>(), apiGet: vi.fn(), apiPost: vi.fn() }));
const profileId = 'a'.repeat(64);
const status = (feed = 'sip') => ({ enabled: true, collector_enabled: true,
  collector: { state: 'LIVE', reason_code: null, capture_id: 'capture-1', pending_events: 0, listing_states: {}, g1_data: 'INSUFFICIENTE' },
  profiles: [{ profile_id: profileId, profile: { feed, delay_ns: '0', max_symbols: 30, max_archive_bytes: 5000000,
    required_capabilities: ['bars', 'quotes', 'news', 'status'], attested_capabilities: ['bars', 'quotes', 'news', 'status'],
    quote_conditions: [], max_connections: 2, http_minute_limit: 10, http_daily_limit: 100, http_monthly_limit: 1000,
    max_frame_bytes: 1000000, max_queue_events: 1000, provider: 'alpaca', version: 'intraday-profile-v1' }, availability: {} }],
  budgets: [], capture_gaps: [], latest_quality: { snapshot_id: 7, digest: 'b'.repeat(64), known_at_ns: '1791806400000000001',
    outcome: 'READY', reasons: [], namespace: [profileId, 'REAL', 'CAPTURED', 'STRICT_PIT'] }, g1_data: 'INSUFFICIENTE' });
const job = (state: api.JobStatus, overrides = {}) => ({ id: 42, kind: 'INTRADAY_METADATA', status: state, progress: 0,
  params: {}, result_ref: null, result: state === 'SUCCEEDED' ? { profile_id: profileId, assets_capture_id: 3, calendar_capture_id: 4 } : null,
  error_code: null, error_message: null, cancel_requested: false, created_at: '', started_at: null, finished_at: null, ...overrides });

beforeEach(() => {
  vi.mocked(api.apiGet).mockResolvedValue(status());
  vi.mocked(api.apiPost).mockRejectedValue(new Error('unexpected POST'));
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('unexpected fetch')));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe('Intraday local status and explicit operations', () => {
  it('reads only local status on mount and never promotes LIVE or snapshot READY to G1', async () => {
    render(<IntradayDataStatus />);
    expect(await screen.findByText('G1 dati: INSUFFICIENTE')).toBeVisible();
    expect(screen.getByText('Collector REAL: LIVE')).toBeVisible();
    expect(screen.queryByText('VALIDATO')).not.toBeInTheDocument();
    expect(api.apiPost).not.toHaveBeenCalled();
    expect(api.apiGet).toHaveBeenCalledWith('/intraday/status', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });
  it('shows IEX as research despite available capabilities and READY snapshot', async () => {
    vi.mocked(api.apiGet).mockResolvedValue(status('iex'));
    render(<IntradayDataStatus />);
    expect(await screen.findByText(/IEX: copertura parziale/)).toBeVisible();
    expect(screen.getByText('G1 dati: INSUFFICIENTE')).toBeVisible();
  });
  it('offers bootstrap on an empty DB and does not confirm any mapping', async () => {
    vi.mocked(api.apiGet).mockResolvedValue({ ...status(), profiles: [], latest_quality: null });
    render(<IntradayDataStatus />);
    expect(await screen.findByText(/Nessun profilo intraday archiviato/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Aggiorna metadata e calendario' })).toBeInTheDocument();
    expect(api.apiPost).not.toHaveBeenCalled();
  });
  it('aborts local reads on unmount without cancelling remote jobs', async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(api.apiGet).mockImplementation((_path, init) => { signal = init?.signal; return new Promise(() => {}); });
    const view = render(<IntradayDataStatus />);
    view.unmount();
    expect(signal?.aborted).toBe(true);
    expect(api.apiPost).not.toHaveBeenCalled();
  });
  it('keeps errors visible and permits retry', async () => {
    vi.mocked(api.apiGet).mockRejectedValueOnce(new api.ApiError('unsafe server echo', 409, { reason_code: 'PROFILE_INVALID' }));
    render(<IntradayDataStatus />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Profilo');
    expect(screen.queryByText(/unsafe server echo/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Aggiorna stato intraday' }));
    expect(await screen.findByText('G1 dati: INSUFFICIENTE')).toBeVisible();
  });
  it('polls a 202 metadata job and never applies identity automatically', async () => {
    vi.mocked(api.apiPost).mockResolvedValue(job('QUEUED'));
    vi.mocked(api.apiGet).mockImplementation(async (path) => path.startsWith('/lab/jobs/') ? job('SUCCEEDED') : status());
    render(<IntradayDataStatus />);
    await screen.findByText('G1 dati: INSUFFICIENTE');
    fireEvent.click(screen.getByRole('button', { name: 'Aggiorna metadata e calendario' }));
    expect(await screen.findByText(/Job 42: QUEUED/)).toBeVisible();
    await waitFor(() => expect(screen.getByText(/Job 42: SUCCEEDED/)).toBeVisible(), { timeout: 2200 });
    expect(screen.getByText(/Cattura asset 3.*Calendario 4/)).toBeVisible();
    expect(vi.mocked(api.apiPost).mock.calls.map(call => call[0])).toEqual(['/intraday/metadata/refresh']);
  });
  it.each(['FAILED', 'INTERRUPTED', 'CANCELLED'] as const)('ends polling for %s and reports the terminal', async (state) => {
    vi.mocked(api.apiPost).mockResolvedValue(job(state, { error_code: state === 'FAILED' ? 'PAGE_LIMIT' : null }));
    render(<IntradayDataStatus />);
    await screen.findByText('G1 dati: INSUFFICIENTE');
    fireEvent.click(screen.getByRole('button', { name: 'Aggiorna metadata e calendario' }));
    expect(await screen.findByRole('alert')).toBeVisible();
    expect(screen.getByText(new RegExp('Job 42: ' + state))).toBeVisible();
    expect(vi.mocked(api.apiGet).mock.calls.some(call => call[0].startsWith('/lab/jobs/'))).toBe(false);
  });
  it('preserves a successful late cancellation outcome', async () => {
    let finishCancel: (value: unknown) => void = () => {};
    vi.mocked(api.apiPost).mockImplementation(async (path) => path.endsWith('/cancel') ?
      new Promise(resolve => { finishCancel = resolve; }) : job('RUNNING'));
    vi.mocked(api.apiGet).mockImplementation(async path => path.startsWith('/lab/jobs/') ? job('SUCCEEDED') : status());
    render(<IntradayDataStatus />);
    await screen.findByText('G1 dati: INSUFFICIENTE');
    fireEvent.click(screen.getByRole('button', { name: 'Aggiorna metadata e calendario' }));
    await screen.findByText(/Job 42: RUNNING/);
    fireEvent.click(screen.getByRole('button', { name: 'Annulla job intraday' }));
    await waitFor(() => expect(screen.getByText(/Job 42: SUCCEEDED/)).toBeVisible(), { timeout: 2200 });
    await act(async () => finishCancel(job('CANCELLED')));
    expect(screen.getByText(/Job 42: SUCCEEDED/)).toBeVisible();
  });
  it('selects the newly bootstrapped profile and exposes its asset capture for mapping', async () => {
    const newId = 'c'.repeat(64);
    vi.spyOn(api, 'intradayProfileId').mockResolvedValue(newId);
    vi.mocked(api.apiGet).mockImplementation(async path => path.includes(newId) ? { ...status(), profiles: [{ ...status().profiles[0], profile_id: newId }] } : status());
    vi.mocked(api.apiPost).mockResolvedValue(job('SUCCEEDED', { result: { profile_id: newId, assets_capture_id: 5, calendar_capture_id: 6 } }));
    render(<IntradayDataStatus />); await screen.findByText('G1 dati: INSUFFICIENTE');
    fireEvent.click(screen.getByLabelText('Configura nuovo profilo pubblico'));
    for (const label of ['Limite simboli', 'Limite connessioni', 'Richieste al minuto', 'Richieste al giorno', 'Richieste al mese', 'Limite frame (byte)', 'Limite coda (eventi)', 'Limite archivio (byte)']) fireEvent.change(screen.getByLabelText(label), { target: { value: '10' } });
    for (const cap of ['bars', 'quotes', 'news', 'status']) fireEvent.click(screen.getByLabelText(cap));
    fireEvent.click(screen.getByRole('button', { name: 'Aggiorna metadata e calendario' }));
    await waitFor(() => expect(screen.getByLabelText('Profilo intraday')).toHaveValue(newId));
    expect(api.apiGet).toHaveBeenCalledWith('/intraday/status?profile_id=' + newId, expect.anything());
    expect(screen.getByLabelText('ID cattura metadata')).toHaveValue('5');
    expect(api.apiPost).toHaveBeenCalledTimes(1);
  });
  it('requires explicit mapping confirmation and invalidates the preview on any edit', async () => {
    vi.mocked(api.apiPost).mockResolvedValue({ listing_id: 1, broker_asset_id: '12345678-1234-1234-1234-123456789012', ticker: 'TEST', venue: 'XNAS', current_version_id: null, confirmation_token: 'd'.repeat(64) });
    render(<IntradayDataStatus />); await screen.findByText('G1 dati: INSUFFICIENTE');
    fireEvent.click(screen.getByText('Mapping listing: preview e conferma'));
    for (const [label, value] of [['Listing da collegare', '1'], ['ID cattura metadata', '3'], ['UUID asset Alpaca', '12345678-1234-1234-1234-123456789012'], ['Hash evidenza mapping', 'e'.repeat(64)]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole('button', { name: 'Verifica mapping' }));
    await screen.findByRole('button', { name: 'Conferma questo mapping' });
    expect(api.apiPost).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('d'.repeat(64))).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Listing da collegare'), { target: { value: '2' } });
    expect(screen.queryByRole('button', { name: 'Conferma questo mapping' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Listing da collegare'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Verifica mapping' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Conferma questo mapping' }));
    await waitFor(() => expect(api.apiPost).toHaveBeenCalledWith('/intraday/identity/apply', expect.objectContaining({ listing_id: 1, confirmation_token: 'd'.repeat(64) }), expect.anything()));
  });
  it('uses real grid minutes, listing/session and denominators in the frozen report', async () => {
    const saved = { snapshot_id: 7, digest: 'b'.repeat(64), known_at_ns: '1791806400000000001',
      manifest: { namespace: [profileId, 'sip', 'REAL', 'CAPTURED', 'STRICT_PIT'], start_at_ns: '1791800000000000000', end_at_ns: '1791806300000000000', cutoff_ns: '1791806400000000001', listing_ids: [1], requested_listing_ids: [1], benchmarks: {} },
      report: { outcome: 'INSUFFICIENTE', technical_result: 'INSUFFICIENTE', g1_tech: 'NOT_EVALUATED', reasons: ['GRID_INSUFFICIENT'], limits: {},
        metrics: { raw: { planned: 390, valid: 380, coverage: 380/390 }, grid: [{ listing_id: 1, session_date: '2026-10-12', minutes: 15, planned: 26, usable: 20, coverage: 20/26, exclusions: { QUOTE_STALE: 6 } }] } },
      inputs: [], offset: 0, limit: 50, next_offset: null, total: 0, input_type: 'ALL' };
    vi.mocked(api.apiGet).mockImplementation(async path => path.startsWith('/intraday/snapshots/') ? saved : status());
    render(<IntradayDataStatus />); await screen.findByText('G1 dati: INSUFFICIENTE');
    fireEvent.change(screen.getByLabelText('ID snapshot'), { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consulta snapshot' }));
    expect(await screen.findByText(/Listing 1.*2026-10-12.*15 minuti.*20\/26.*76.92%/)).toBeVisible();
    expect(screen.getByText(/QUOTE_STALE: 6/)).toBeVisible();
  });
});

describe('Exact intraday timestamps on the wire', () => {
  it('does not render provider echoes disguised as terminal errors', async () => {
    const actual = await vi.importActual<typeof api>('../lib/api');
    const sentinel = 'SENTINEL_' + crypto.randomUUID();
    const result = actual.intradayErrorMessage(new actual.ApiError('Elaborazione interrotta dal riavvio: ' + sentinel, 409));
    expect(result).not.toContain(sentinel);
  });
  it.each(['__proto__', 'toString'])('treats inherited reason %s as unknown and returns fixed text', async code => {
    const actual = await vi.importActual<typeof api>('../lib/api');
    const result = actual.intradayErrorMessage(new actual.ApiError('private echo', 409, { reason_code: code }));
    expect(typeof result).toBe('string'); expect(result).toMatch(/Operazione intraday non riuscita/);
  });
  it('uses exact integer JSON on HTTP POST and reads exact int64 from HTTP GET', async () => {
    const actual = await vi.importActual<typeof api>('../lib/api');
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"cutoff_ns":1791806400000000001}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await actual.apiPost('/intraday/snapshots', { cutoff_ns: '1791806400000000001' });
    expect(fetchMock.mock.calls[0][1].body).toBe('{"cutoff_ns":1791806400000000001}');
    fetchMock.mockResolvedValue(new Response('{"cutoff_ns":1791806400000000002}'));
    expect(await actual.apiGet('/intraday/news?cutoff_ns=1791806400000000002')).toEqual({ cutoff_ns: '1791806400000000002' });
  });
  it('preserves adjacent nanoseconds, large source IDs and quoted numeric text', async () => {
    const actual = await vi.importActual<typeof api>('../lib/api');
    const parsed = actual.parseIntradayJSON('{"cutoff_ns":1791806400000000001,"updated_at_ns":1791806400000000002,"id":9223372036854775807,"headline":"1791806400000000001 \\\"quoted\\\""}');
    expect(parsed).toEqual({ cutoff_ns: '1791806400000000001', updated_at_ns: '1791806400000000002', id: '9223372036854775807', headline: '1791806400000000001 "quoted"' });
  });
  it('serializes ns as exact bounded JSON integers, rejecting fractional/negative/overflow values', async () => {
    const actual = await vi.importActual<typeof api>('../lib/api');
    expect(actual.serializeIntradayJSON({ cutoff_ns: '1791806400000000001', text: '1791806400000000002' })).toBe('{"cutoff_ns":1791806400000000001,"text":"1791806400000000002"}');
    for (const invalid of ['-1', '1.5', '9223372036854775808', '1e18', '1}']) {
      expect(() => actual.serializeIntradayJSON({ cutoff_ns: invalid })).toThrow();
    }
  });
});
