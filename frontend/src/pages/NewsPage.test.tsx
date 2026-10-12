import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../lib/api';
import { NewsPage } from './NewsPage';
vi.mock('../lib/api', async (original) => ({ ...await original<typeof import('../lib/api')>(), apiGet: vi.fn(), apiPost: vi.fn() }));
const profile = 'a'.repeat(64);
const localStatus = { profiles: [{ profile_id: profile, profile: { feed: 'sip' } }] };
const page = (state = 'MISSING', items: unknown[] = []) => ({ items, total: items.length, offset: 0, limit: 50, next_offset: null,
  cutoff_ns: '1791806400000000001', namespace: [profile, 'REAL', 'CAPTURED', 'STRICT_PIT'],
  coverage: { state, continuity_attested: state === 'COVERED_ZERO', reason_code: null } });
function read() { fireEvent.click(screen.getByRole('button', { name: 'Consulta news intraday' })); }
beforeEach(() => {
  vi.mocked(api.apiGet).mockImplementation(async path => {
    if (path === '/intraday/status') return localStatus;
    if (path.startsWith('/intraday/news?')) return page();
    if (path === '/news/status') return null;
    return [];
  });
  vi.mocked(api.apiPost).mockRejectedValue(new Error('unexpected POST'));
});
afterEach(() => vi.clearAllMocks());

describe('Versioned intraday news kept separate from daily/demo', () => {
  it('uses one clock sample for the default coverage end and cutoff', async () => {
    let time = Date.parse('2026-10-12T14:00:00Z');
    vi.spyOn(Date, 'now').mockImplementation(() => time++);
    render(<NewsPage />); await screen.findByRole('option', { name: /sip/ }); read();
    await waitFor(() => expect(vi.mocked(api.apiGet).mock.calls.some(call => call[0].startsWith('/intraday/news?'))).toBe(true));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('blocks consultation during a profile reload and then reads only the replacement profile', async () => {
    let statusCalls = 0, finish: (value: unknown) => void = () => {};
    const replacement = 'b'.repeat(64);
    vi.mocked(api.apiGet).mockImplementation(async path => {
      if (path === '/intraday/status') return ++statusCalls === 1 ? localStatus : new Promise(resolve => { finish = resolve; });
      if (path.startsWith('/intraday/news?')) return { ...page('COVERED_ZERO'), namespace: [replacement, 'REAL', 'CAPTURED', 'STRICT_PIT'] };
      return path === '/news/status' ? null : [];
    });
    render(<NewsPage />); await screen.findByRole('option', { name: /sip/ });
    fireEvent.click(screen.getByRole('button', { name: 'Rileggi profili intraday' }));
    expect(screen.getByRole('button', { name: 'Consulta news intraday' })).toBeDisabled();
    await act(async () => finish({ profiles: [{ profile_id: replacement, profile: { feed: 'sip' } }] }));
    await waitFor(() => expect(screen.getByLabelText('Profilo news intraday')).toHaveValue(replacement));
    read(); await screen.findByText('Periodo coperto: nessun articolo');
    expect(vi.mocked(api.apiGet).mock.calls.filter(call => call[0].startsWith('/intraday/news?')).every(call => call[0].includes('profile_id=' + replacement))).toBe(true);
  });
  it.each([['MISSING', 'Copertura news mancante'], ['COVERED_ZERO', 'Periodo coperto: nessun articolo']])('distinguishes %s from an empty list', async (state, expected) => {
    vi.mocked(api.apiGet).mockImplementation(async path => path === '/intraday/status' ? localStatus : path.startsWith('/intraday/news?') ? page(state) : path === '/news/status' ? null : []);
    render(<NewsPage />);
    await screen.findByRole('option', { name: /sip/ });
    read();
    expect(await screen.findByText(expected)).toBeVisible();
    expect(screen.queryByText(state === 'MISSING' ? 'Periodo coperto: nessun articolo' : 'Copertura news mancante')).not.toBeInTheDocument();
    expect(api.apiPost).not.toHaveBeenCalled();
  });
  it('renders editorial dates, exact availability, version mapping/category and excluded content', async () => {
    const article = { id: 12, article_id: '9223372036854775807', supersedes_id: 11, available_at_ns: '1791806400000000001',
      payload: { headline: 'Revisioned headline', source: 'alpaca', version: 'wire-v2', published_at_ns: '1791806300000000000', updated_at_ns: '1791806400000000000', content_state: 'RIGHTS_UNATTESTED', content: null },
      links: [{ listing_id: null, instrument_id: null, category: 'EARNINGS', rule_version: 'news-rule-v1', payload: { target: 'UNMAPPED', reason_code: 'IDENTITY_UNVERIFIED' } }] };
    vi.mocked(api.apiGet).mockImplementation(async path => path === '/intraday/status' ? localStatus : path.startsWith('/intraday/news?') ? page('COVERED', [article]) : path === '/news/status' ? null : []);
    render(<NewsPage />);
    await screen.findByRole('option', { name: /sip/ }); read();
    expect(await screen.findByText('Revisioned headline')).toBeVisible();
    expect(screen.getByText(/Disponibile dal.*1791806400000000001/)).toBeVisible();
    expect(screen.getByText(/Pubblicazione/)).toBeVisible(); expect(screen.getByText(/Aggiornamento editoriale/)).toBeVisible();
    expect(screen.getByText(/EARNINGS.*UNMAPPED/)).toBeVisible();
    expect(screen.getByText(/Testo escluso.*diritti/)).toBeVisible();
    expect(screen.getByText(/Sostituisce versione 11/)).toBeVisible();
  });
  it('aborts and discards the old response after switching namespace, with no fallback', async () => {
    let old: (value: unknown) => void = () => {};
    let oldSignal: AbortSignal | undefined;
    vi.mocked(api.apiGet).mockImplementation(async (path, init) => {
      if (path === '/intraday/status') return localStatus;
      if (path.startsWith('/intraday/news?') && path.includes('data_mode=REAL')) { oldSignal = init?.signal; return new Promise(resolve => { old = resolve; }); }
      if (path.startsWith('/intraday/news?')) return { ...page('COVERED_ZERO'), namespace: [profile, 'DEMO', 'SYNTHETIC', 'RESEARCH_ONLY'] };
      return path === '/news/status' ? null : [];
    });
    render(<NewsPage />); await screen.findByRole('option', { name: /sip/ }); read();
    fireEvent.change(screen.getByLabelText('Archivio news intraday'), { target: { value: 'DEMO' } });
    expect(oldSignal?.aborted).toBe(true); read();
    expect(await screen.findByText('Periodo coperto: nessun articolo')).toBeVisible();
    await act(async () => old(page('MISSING')));
    expect(screen.queryByText('Copertura news mancante')).not.toBeInTheDocument();
    const url = [...vi.mocked(api.apiGet).mock.calls].reverse().find(call => call[0].startsWith('/intraday/news?'))?.[0];
    expect(url).toContain('provenance=SYNTHETIC'); expect(url).toContain('replay_grade=RESEARCH_ONLY');
  });
  it('shows read errors without stale articles and allows retry', async () => {
    vi.mocked(api.apiGet).mockImplementation(async path => {
      if (path === '/intraday/status') return localStatus;
      if (path.startsWith('/intraday/news?')) throw new api.ApiError('private echo', 409, { reason_code: 'MODE_MISMATCH' });
      return path === '/news/status' ? null : [];
    });
    render(<NewsPage />); await screen.findByRole('option', { name: /sip/ }); read();
    expect(await screen.findByRole('alert')).toHaveTextContent(/Archivio/);
    expect(screen.queryByText(/private echo/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Consulta news intraday' })).toBeEnabled();
  });
  it('aborts a read on unmount and never refreshes providers automatically', async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(api.apiGet).mockImplementation(async (path, init) => {
      if (path === '/intraday/status') return localStatus;
      if (path.startsWith('/intraday/news?')) { signal = init?.signal; return new Promise(() => {}); }
      return path === '/news/status' ? null : [];
    });
    const view = render(<NewsPage />); await screen.findByRole('option', { name: /sip/ }); read();
    await waitFor(() => expect(signal).toBeDefined()); view.unmount();
    expect(signal?.aborted).toBe(true); expect(api.apiPost).not.toHaveBeenCalled();
  });
});
