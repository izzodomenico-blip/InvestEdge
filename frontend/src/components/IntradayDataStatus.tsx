import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Panel } from './Panel';
import { apiGet, apiPost, formatIntradayNs, intradayDateNs, intradayErrorMessage, intradayNamespace, intradayProfileId,
  parseIntradayJSON, type IntradayArchive, type IntradayCapability, type IntradayCheckpointIn, type IntradayCollector,
  type IntradayIdentityApplied, type IntradayIdentityIn, type IntradayIdentityPreview, type IntradayProfile,
  type IntradaySnapshotPage, type IntradayStatus, type JobOut } from '../lib/api';
import { cancelJob, waitForJob } from '../lib/jobs';

const inputClass = 'w-full min-w-0 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300';
const buttonClass = 'rounded-md border border-slate-700 px-3 py-2 text-sm text-cyan-100 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50';
const capabilities: IntradayCapability[] = ['bars', 'updated_bars', 'quotes', 'news', 'status', 'luld', 'assets', 'calendar', 'corporate_actions', 'events'];
const limitFields = [
  ['max_symbols', 'Limite simboli', 10000], ['max_connections', 'Limite connessioni', 100],
  ['http_minute_limit', 'Richieste al minuto', 1000000], ['http_daily_limit', 'Richieste al giorno', 100000000],
  ['http_monthly_limit', 'Richieste al mese', 1000000000], ['max_frame_bytes', 'Limite frame (byte)', 16777216],
  ['max_queue_events', 'Limite coda (eventi)', 1000000], ['max_archive_bytes', 'Limite archivio (byte)', Number.MAX_SAFE_INTEGER],
] as const;
const terminal = (job: JobOut) => !['QUEUED', 'RUNNING'].includes(job.status);
function positive(value: string): number {
  if (!/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error('Identificativo non valido.');
  return Number(value);
}
function listings(value: string): number[] { return Array.from(new Set(value.split(',').map(item => positive(item.trim())))); }
function digest(value: string): string { if (!/^[a-f0-9]{64}$/.test(value)) throw new Error('Digest non valido.'); return value; }
export function utcInput(value = Date.now()): string { return new Date(value).toISOString().slice(0, 23); }
export function IntradayField({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block min-w-0"><span className="mb-1 block text-sm text-slate-300">{label}</span>{children}</label>;
}
export function IntradayArchiveSelect({ value, onChange, label = 'Archivio intraday', disabled = false }: {
  value: IntradayArchive; onChange: (value: IntradayArchive) => void; label?: string; disabled?: boolean;
}) {
  return <IntradayField label={label}><select className={inputClass} value={value} disabled={disabled} onChange={event => onChange(event.target.value as IntradayArchive)}>
    <option value="REAL">REAL · cattura · STRICT_PIT</option><option value="RESEARCH">REAL · storico corrente · RESEARCH_ONLY</option>
    <option value="DEMO">DEMO · sintetico · RESEARCH_ONLY</option>
  </select></IntradayField>;
}

export function IntradayDataStatus() {
  const [status, setStatus] = useState<IntradayStatus | null>(null);
  const [profileOptions, setProfileOptions] = useState<IntradayStatus['profiles']>([]);
  const [profileId, setProfileId] = useState('');
  const [archive, setArchive] = useState<IntradayArchive>('REAL');
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<JobOut | null>(null);
  const active = useRef<{ controller: AbortController } | null>(null);
  const jobRef = useRef<JobOut | null>(null);
  const readController = useRef<AbortController | null>(null);
  const [newProfile, setNewProfile] = useState(false);
  const [feed, setFeed] = useState<IntradayProfile['feed']>('iex');
  const [attested, setAttested] = useState<IntradayCapability[]>([]);
  const [limits, setLimits] = useState<Record<string, string>>({});
  const [conditions, setConditions] = useState('');
  const [startDate, setStartDate] = useState(() => utcInput().slice(0, 10));
  const [endDate, setEndDate] = useState(() => utcInput().slice(0, 10));
  const [identity, setIdentity] = useState({ listing: '', metadata: '', asset: '', evidence: '', leveraged: 'UNKNOWN', inverse: 'UNKNOWN' });
  const [preview, setPreview] = useState<{ input: IntradayIdentityIn; value: IntradayIdentityPreview } | null>(null);
  const [checkpoint, setCheckpoint] = useState<File | null>(null);
  const [listingText, setListingText] = useState('');
  const [market, setMarket] = useState('');
  const [sector, setSector] = useState('');
  const [start, setStart] = useState(() => utcInput(Date.now() - 86400000));
  const [end, setEnd] = useState(() => utcInput(Date.now() - 60000));
  const [cutoff, setCutoff] = useState(() => utcInput());
  const [maxPages, setMaxPages] = useState('100');
  const [chunkDays, setChunkDays] = useState('7');
  const [types, setTypes] = useState<string[]>(['BAR', 'QUOTE', 'NEWS']);
  const [snapshotId, setSnapshotId] = useState('');
  const [inputType, setInputType] = useState('ALL');
  const [snapshot, setSnapshot] = useState<IntradaySnapshotPage | null>(null);
  const [reading, setReading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setLoadError(null); setStatus(null);
    void apiGet<IntradayStatus>('/intraday/status' + (profileId ? '?profile_id=' + encodeURIComponent(profileId) : ''), { signal: controller.signal })
      .then(value => {
        if (controller.signal.aborted) return;
        setProfileOptions(previous => profileId ? [...previous.filter(row => row.profile_id !== profileId), ...value.profiles] : value.profiles);
        if (!profileId && value.profiles[0]) { setProfileId(value.profiles[0].profile_id); return; }
        setStatus(value);
      }).catch(reason => { if (!controller.signal.aborted) setLoadError(intradayErrorMessage(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [profileId, revision]);
  useEffect(() => () => { active.current?.controller.abort(); readController.current?.abort(); }, []);

  function invalidateRead() { readController.current?.abort(); setReading(false); setSnapshot(null); }
  function changeProfile(value: string) {
    invalidateRead(); setPreview(null); setCheckpoint(null); setSnapshotId('');
    setIdentity({ listing: '', metadata: '', asset: '', evidence: '', leveraged: 'UNKNOWN', inverse: 'UNKNOWN' });
    setProfileId(value);
  }
  function identityField(key: keyof typeof identity, value: string) { setPreview(null); setIdentity(old => ({ ...old, [key]: value })); }
  async function execute(label: string, action: (signal: AbortSignal) => Promise<unknown>, options: { job?: boolean; success?: (result: unknown) => void } = {}) {
    if (active.current) return;
    const owner = { controller: new AbortController() };
    active.current = owner; setBusy(true); setError(null); setMessage(null); setJob(null); jobRef.current = null;
    const current = () => active.current === owner && !owner.controller.signal.aborted;
    try {
      let result = await action(owner.controller.signal);
      owner.controller.signal.throwIfAborted();
      if (options.job) {
        result = await waitForJob(result as JobOut, { signal: owner.controller.signal, onUpdate: value => {
          if (!current() || jobRef.current && terminal(jobRef.current) && !terminal(value)) return;
          jobRef.current = value; setJob(value);
        } });
      }
      if (current()) { options.success?.(result); setMessage(label + ' completato.'); setRevision(value => value + 1); }
    } catch (reason) { if (current()) setError(intradayErrorMessage(reason)); }
    finally { if (current()) { active.current = null; setBusy(false); } }
  }
  async function requestCancel() {
    const owner = active.current, currentJob = jobRef.current;
    if (!owner || !currentJob || terminal(currentJob)) return;
    try {
      const result = await cancelJob(currentJob.id, owner.controller.signal);
      if (active.current !== owner || owner.controller.signal.aborted || jobRef.current?.id !== currentJob.id) return;
      jobRef.current = result; setJob(result);
    } catch (reason) { if (active.current === owner && !owner.controller.signal.aborted) setError(intradayErrorMessage(reason)); }
  }
  function publicProfile(): IntradayProfile {
    const numbers: Record<string, number> = {};
    for (const [key, , max] of limitFields) { const value = positive(limits[key] ?? ''); if (value > max) throw new Error('Limite non valido.'); numbers[key] = value; }
    const quote_conditions = conditions.trim() ? conditions.split(',').map(value => value.trim()) : [];
    if (quote_conditions.some(value => !/^[A-Za-z0-9]{1,8}$/.test(value)) || quote_conditions.length > 100 || !attested.length) throw new Error('Capacità non valide.');
    return { ...numbers, provider: 'alpaca', version: 'intraday-profile-v1', feed, required_capabilities: ['bars', 'quotes', 'news', 'status'],
      attested_capabilities: attested, quote_conditions, delay_ns: feed === 'delayed_sip' ? '900000000000' : '0' } as IntradayProfile;
  }
  function period() {
    const start_at_ns = intradayDateNs(start), end_at_ns = intradayDateNs(end), cutoff_ns = intradayDateNs(cutoff);
    if (BigInt(start_at_ns) >= BigInt(end_at_ns) || BigInt(end_at_ns) > BigInt(cutoff_ns) || BigInt(end_at_ns) - BigInt(start_at_ns) > 366n * 86400n * 1000000000n) throw new Error('Periodo non valido.');
    return { listing_ids: listings(listingText), start_at_ns, end_at_ns, cutoff_ns };
  }
  async function readSnapshot(offset = 0) {
    readController.current?.abort();
    const controller = new AbortController(); readController.current = controller;
    setReading(true); setError(null); setSnapshot(null);
    try {
      const namespace = intradayNamespace(archive, digest(profileId));
      const params = new URLSearchParams({ ...namespace, input_type: inputType, offset: String(offset), limit: '50' });
      const value = await apiGet<IntradaySnapshotPage>('/intraday/snapshots/' + positive(snapshotId) + '?' + params, { signal: controller.signal });
      if (controller.signal.aborted || readController.current !== controller) return;
      const expected = [profileId, value.manifest.namespace[1], namespace.data_mode, namespace.provenance, namespace.replay_grade];
      if (JSON.stringify(value.manifest.namespace) !== JSON.stringify(expected)) throw new Error('Archivio non compatibile.');
      setSnapshot(value);
    } catch (reason) { if (!controller.signal.aborted && readController.current === controller) setError(intradayErrorMessage(reason)); }
    finally { if (!controller.signal.aborted && readController.current === controller) setReading(false); }
  }
  const selected = status?.profiles.find(row => row.profile_id === profileId);
  return <Panel title="Dati intraday Alpaca">
    <div className="min-w-0 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-300">Consultazione locale; le operazioni partono dai comandi espliciti.</p>
        <button className={buttonClass} onClick={() => setRevision(value => value + 1)}>Aggiorna stato intraday</button>
      </div>
      {loading && <p aria-live="polite" className="text-sm text-slate-300">Caricamento stato intraday…</p>}
      {loadError && <p role="alert" className="text-sm text-rose-200">{loadError}</p>}
      {status && <>
        <p className="text-sm font-semibold text-amber-200">G1 dati: INSUFFICIENTE</p>
        <p className="text-sm text-slate-300">Collector REAL: {status.collector.state}</p>
        <p className="break-words text-sm text-slate-300">Cattura: {status.collector.capture_id ?? 'assente'} · Eventi in coda: {status.collector.pending_events ?? 0}</p>
        <p className="text-sm text-slate-300">{status.enabled ? 'Dati abilitati' : 'Dati disabilitati'} · {status.collector_enabled ? 'Collector configurato' : 'Collector disabilitato'}. LIVE e qualità del singolo snapshot non certificano G1 né una strategia.</p>
        {status.collector.reason_code && <p className="text-sm text-amber-200">Motivo collector: {status.collector.reason_code}</p>}
        {!status.profiles.length && <p className="text-sm text-slate-300">Nessun profilo intraday archiviato. Configura un profilo pubblico e aggiorna metadata e calendario.</p>}
      </>}
      <fieldset disabled={busy} className="min-w-0 space-y-5">
        <div className="grid min-w-0 gap-3 md:grid-cols-2">
          <IntradayField label="Profilo intraday"><select className={inputClass} value={profileId} onChange={event => changeProfile(event.target.value)}>
            <option value="">Nessun profilo selezionato</option>{profileOptions.map(row => <option key={row.profile_id} value={row.profile_id}>{row.profile.feed} · {row.profile_id.slice(0, 12)}</option>)}
          </select></IntradayField>
          <IntradayArchiveSelect value={archive} onChange={value => { invalidateRead(); setArchive(value); }} />
        </div>
        {selected && <div className="space-y-2 text-sm text-slate-300">
          <p className="break-words">Profilo: {profileId}</p>
          <p>Feed {selected.profile.feed} · Ritardo dichiarato: {String(selected.profile.delay_ns ?? 0)} ns · Limite simboli: {selected.profile.max_symbols}</p>
          {selected.profile.feed === 'iex' && <p className="text-amber-200">IEX: copertura parziale, consultazione e ricerca.</p>}
          {selected.profile.feed === 'delayed_sip' && <p className="text-amber-200">Feed ritardato: non idoneo al realtime.</p>}
          {archive !== 'REAL' && <p className="text-amber-200">RESEARCH_ONLY: dati non utilizzabili per promuovere strategie.</p>}
          <p>Capacità richieste: {selected.profile.required_capabilities.join(', ')}; attestate: {selected.profile.attested_capabilities.join(', ')}</p>
          <p>Limite archivio: {String(selected.profile.max_archive_bytes)} byte · Limite coda: {selected.profile.max_queue_events} eventi</p>
          {Object.entries(selected.availability).map(([name, value]) => <p key={name}>{name}: {value.state}{value.reason_code ? ' · ' + value.reason_code : ''}{value.cooldown_until ? ' · fino a ' + value.cooldown_until : ''}</p>)}
        </div>}
        <details open><summary className="cursor-pointer py-2 text-white">Metadata e calendario</summary>
          <div className="mt-3 space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <IntradayField label="Calendario da"><input type="date" className={inputClass} value={startDate} onChange={event => setStartDate(event.target.value)} /></IntradayField>
              <IntradayField label="Calendario a"><input type="date" className={inputClass} value={endDate} onChange={event => setEndDate(event.target.value)} /></IntradayField>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={newProfile || !profileId} disabled={!profileId} onChange={event => setNewProfile(event.target.checked)} />Configura nuovo profilo pubblico</label>
            {(newProfile || !profileId) && <div className="space-y-3">
              <IntradayField label="Feed configurato"><select className={inputClass} value={feed} onChange={event => setFeed(event.target.value as IntradayProfile['feed'])}><option value="iex">IEX</option><option value="sip">SIP</option><option value="delayed_sip">SIP ritardato</option></select></IntradayField>
              <fieldset><legend className="text-sm text-slate-300">Capacità attestate dal piano dati configurato</legend><div className="mt-2 flex flex-wrap gap-4">{capabilities.map(cap => <label key={cap} className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={attested.includes(cap)} onChange={event => setAttested(old => event.target.checked ? [...old, cap] : old.filter(value => value !== cap))} />{cap}</label>)}</div></fieldset>
              <div className="grid gap-3 md:grid-cols-2">{limitFields.map(([key, label, max]) => <IntradayField key={key} label={label}><input type="number" min="1" max={max} step="1" className={inputClass} value={limits[key] ?? ''} onChange={event => setLimits(old => ({ ...old, [key]: event.target.value }))} /></IntradayField>)}</div>
              <IntradayField label="Condizioni quote attestate (separate da virgola)"><input className={inputClass} value={conditions} onChange={event => setConditions(event.target.value)} /></IntradayField>
              <p className="text-sm text-slate-300">Inserisci i limiti già configurati. Il profilo richiede barre, quote, news e stato; le capacità restano soggette alla verifica del backend.</p>
            </div>}
            <button className={buttonClass} onClick={() => void execute('Metadata e calendario', async signal => {
              const profile = newProfile || !profileId ? publicProfile() : undefined;
              const id = profile ? await intradayProfileId(profile) : digest(profileId);
              signal.throwIfAborted();
              return apiPost<JobOut>('/intraday/metadata/refresh', { profile_id: id, ...(profile ? { profile } : {}), start_date: startDate, end_date: endDate }, { signal });
            }, { job: true, success: result => {
              const saved = (result as JobOut).result;
              if (typeof saved?.profile_id === 'string' && /^[a-f0-9]{64}$/.test(saved.profile_id)) { changeProfile(saved.profile_id); setNewProfile(false); }
              if (typeof saved?.assets_capture_id === 'number' && Number.isSafeInteger(saved.assets_capture_id) && saved.assets_capture_id > 0) setIdentity(old => ({ ...old, metadata: String(saved.assets_capture_id) }));
            } })}>Aggiorna metadata e calendario</button>
          </div>
        </details>
        <details><summary className="cursor-pointer py-2 text-white">Mapping listing: preview e conferma</summary>
          <div className="mt-3 space-y-3"><div className="grid gap-3 md:grid-cols-2">
            {([['listing', 'Listing da collegare'], ['metadata', 'ID cattura metadata'], ['asset', 'UUID asset Alpaca'], ['evidence', 'Hash evidenza mapping']] as const).map(([key, label]) => <IntradayField key={key} label={label}><input className={inputClass} value={identity[key]} onChange={event => identityField(key, event.target.value)} /></IntradayField>)}
            {(['leveraged', 'inverse'] as const).map(key => <IntradayField key={key} label={key === 'leveraged' ? 'Strumento a leva' : 'Strumento inverso'}><select className={inputClass} value={identity[key]} onChange={event => identityField(key, event.target.value)}><option value="UNKNOWN">Sconosciuto</option><option value="NO">No, attestato</option><option value="YES">Sì, attestato</option></select></IntradayField>)}
          </div><p className="text-sm text-slate-300">Validità CURRENT_ASSETS: il metadata corrente non certifica un mapping storico. Capacità richieste BAR, QUOTE e NEWS.</p>
          <button className={buttonClass} disabled={!profileId} onClick={() => void execute('Preview mapping', async signal => {
            setPreview(null);
            const input: IntradayIdentityIn = { profile_id: digest(profileId), listing_id: positive(identity.listing), metadata_capture_id: positive(identity.metadata), broker_asset_id: identity.asset,
              evidence_hash: digest(identity.evidence), capabilities: ['BAR', 'QUOTE', 'NEWS'], validity_source: 'CURRENT_ASSETS', leveraged: identity.leveraged as IntradayIdentityIn['leveraged'], inverse: identity.inverse as IntradayIdentityIn['inverse'] };
            const value = await apiPost<IntradayIdentityPreview>('/intraday/identity/preview', input, { signal });
            return { input, value };
          }, { success: result => setPreview(result as { input: IntradayIdentityIn; value: IntradayIdentityPreview }) })}>Verifica mapping</button>
          {preview && <div className="space-y-3 text-sm text-slate-300"><p>Listing {preview.value.listing_id} → {preview.value.ticker} · {preview.value.venue} · Versione corrente {preview.value.current_version_id ?? 'assente'}</p>
            <button className={buttonClass} onClick={() => void execute('Conferma mapping', signal => apiPost<IntradayIdentityApplied>('/intraday/identity/apply', { ...preview.input, confirmation_token: preview.value.confirmation_token }, { signal }), { success: () => setPreview(null) })}>Conferma questo mapping</button></div>}
          </div>
        </details>
        <details><summary className="cursor-pointer py-2 text-white">Collector e checkpoint verificato</summary><div className="mt-3 space-y-3">
          <p className="text-sm text-slate-300">Il collector usa dati REAL. Un checkpoint UTP verificabile e continuità dopo ACK sono necessari per lo stato LIVE.</p>
          <IntradayField label="Listing intraday (ID separati da virgola)"><input className={inputClass} value={listingText} onChange={event => setListingText(event.target.value)} /></IntradayField>
          <div className="grid gap-3 md:grid-cols-2"><IntradayField label="Benchmark mercato (listing ID)"><input className={inputClass} value={market} onChange={event => setMarket(event.target.value)} /></IntradayField><IntradayField label="Benchmark settore (listing ID)"><input className={inputClass} value={sector} onChange={event => setSector(event.target.value)} /></IntradayField></div>
          <div className="flex flex-wrap gap-3"><button className={buttonClass} disabled={!profileId || !status?.collector_enabled} onClick={() => void execute('Avvio collector', signal => apiPost<IntradayCollector>('/intraday/collector/start', { profile_id: digest(profileId), listing_ids: listings(listingText), benchmark_listing_ids: [market, sector].filter(Boolean).map(positive) }, { signal }))}>Avvia collector REAL</button>
            <button className={buttonClass} disabled={!profileId} onClick={() => void execute('Stop collector', signal => apiPost<IntradayCollector>('/intraday/collector/stop', { profile_id: digest(profileId) }, { signal }))}>Ferma collector REAL</button></div>
          <IntradayField label="Checkpoint UTP locale (JSON, massimo 1 MiB)"><input type="file" accept=".json,application/json" className={inputClass} onChange={event => setCheckpoint(event.target.files?.[0] ?? null)} /></IntradayField>
          <button className={buttonClass} disabled={!profileId || !checkpoint} onClick={() => void execute('Import checkpoint', async signal => {
            if (!checkpoint || checkpoint.size > 1048576) throw new Error('Checkpoint non valido.');
            const value = parseIntradayJSON(await checkpoint.text()) as Omit<IntradayCheckpointIn, 'profile_id'>;
            signal.throwIfAborted();
            if (!value || Object.keys(value).some(key => !['capture_id', 'authority', 'document'].includes(key)) || !value.capture_id || !value.authority || !value.document) throw new Error('Checkpoint non valido.');
            return apiPost('/intraday/status-checkpoints', { ...value, profile_id: digest(profileId) }, { signal });
          })}>Importa checkpoint verificato</button>
        </div></details>
        <details><summary className="cursor-pointer py-2 text-white">Backfill e snapshot</summary><div className="mt-3 space-y-3">
          <p className="text-sm text-slate-300">Il backfill è REAL / HISTORICAL_CURRENT / RESEARCH_ONLY. Gli snapshot usano l’archivio selezionato. Orari UTC al millisecondo, intervallo massimo 366 giorni.</p>
          <IntradayField label="Listing dataset (ID separati da virgola)"><input className={inputClass} value={listingText} onChange={event => setListingText(event.target.value)} /></IntradayField>
          <div className="grid gap-3 md:grid-cols-3">{([['Inizio dataset UTC', start, setStart], ['Fine dataset UTC', end, setEnd], ['Cutoff snapshot UTC', cutoff, setCutoff]] as const).map(([label, value, setter]) => <IntradayField key={label} label={label}><input type="datetime-local" step="0.001" className={inputClass} value={value} onChange={event => setter(event.target.value)} /></IntradayField>)}</div>
          <fieldset><legend className="text-sm text-slate-300">Tipi da recuperare</legend><div className="mt-2 flex flex-wrap gap-4">{['BAR', 'QUOTE', 'NEWS', 'CORPORATE_ACTION'].map(type => <label key={type} className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={types.includes(type)} onChange={event => setTypes(old => event.target.checked ? [...old, type] : old.filter(item => item !== type))} />{type}</label>)}</div></fieldset>
          <div className="grid gap-3 md:grid-cols-2"><IntradayField label="Pagine massime per tipo (totali)"><input type="number" min="1" max="1000" className={inputClass} value={maxPages} onChange={event => setMaxPages(event.target.value)} /></IntradayField><IntradayField label="Giorni per chunk"><input type="number" min="1" max="7" className={inputClass} value={chunkDays} onChange={event => setChunkDays(event.target.value)} /></IntradayField></div>
          <div className="flex flex-wrap gap-3"><button className={buttonClass} disabled={!profileId || archive === 'DEMO'} onClick={() => void execute('Backfill ricerca', signal => {
            const { cutoff_ns: _cutoff, ...range } = period();
            const max_pages = positive(maxPages), chunk_days = positive(chunkDays);
            if (max_pages > 1000 || chunk_days > 7 || !types.length) throw new Error('Budget non valido.');
            return apiPost<JobOut>('/intraday/backfill', { ...intradayNamespace('RESEARCH', digest(profileId)), ...range, types, max_pages, chunk_days, asof_date: cutoff.slice(0, 10) }, { signal });
          }, { job: true })}>Recupera storico per ricerca</button>
          <button className={buttonClass} disabled={!profileId} onClick={() => void execute('Snapshot', signal => apiPost<JobOut>('/intraday/snapshots', { ...intradayNamespace(archive, digest(profileId)), ...period(), policy_id: 'intraday-quality-v1',
            benchmarks: { ...(market ? { market: positive(market) } : {}), ...(sector ? { sector: positive(sector) } : {}) } }, { signal }), { job: true, success: result => {
              const reference = (result as JobOut).result_ref; if (reference && /^[1-9]\d*$/.test(reference)) { invalidateRead(); setSnapshotId(reference); }
            } })}>Congela snapshot</button></div>
        </div></details>
      </fieldset>
      {job && <div className="space-y-2" aria-live="polite"><p className="text-sm text-slate-300">Job {job.id}: {job.status} · {Math.round(job.progress * 100)}%</p>
        {job.cancel_requested && <p className="text-sm text-amber-200">Annullamento richiesto; attendo il terminale del server.</p>}
        {job.result && <p className="break-words text-sm text-slate-300">Riferimento risultato: {job.result_ref ?? 'riepilogo locale'}{job.result.assets_capture_id ? ' · Cattura asset ' + String(job.result.assets_capture_id) : ''}{job.result.calendar_capture_id ? ' · Calendario ' + String(job.result.calendar_capture_id) : ''}</p>}
        {busy && !terminal(job) && <button className={buttonClass} disabled={job.cancel_requested} onClick={() => void requestCancel()}>Annulla job intraday</button>}
      </div>}
      {error && <p role="alert" className="text-sm text-rose-200">{error}</p>}
      {message && <p role="status" className="text-sm text-cyan-100">{message}</p>}
      <fieldset disabled={busy} className="min-w-0 space-y-3"><legend className="py-2 text-white">Consulta manifest e qualità salvati</legend>
        <div className="grid gap-3 md:grid-cols-2"><IntradayField label="ID snapshot"><input className={inputClass} value={snapshotId} onChange={event => { invalidateRead(); setSnapshotId(event.target.value); }} /></IntradayField>
          <IntradayField label="Tipo input snapshot"><select className={inputClass} value={inputType} onChange={event => { invalidateRead(); setInputType(event.target.value); }}>{['ALL', 'BAR', 'QUOTE', 'NEWS', 'EVENT', 'IDENTITY', 'CALENDAR', 'UNIVERSE', 'CAPTURE'].map(value => <option key={value}>{value}</option>)}</select></IntradayField></div>
        <div className="flex flex-wrap gap-3"><button className={buttonClass} disabled={!profileId || reading} onClick={() => void readSnapshot()}>Consulta snapshot</button>
          <button className={buttonClass} disabled={!profileId} onClick={() => void execute('Verifica qualità salvata', signal => apiPost<JobOut>('/intraday/quality', { ...intradayNamespace(archive, digest(profileId)), snapshot_id: positive(snapshotId) }, { signal }), { job: true })}>Verifica qualità salvata</button></div>
      </fieldset>
      {reading && <p aria-live="polite" className="text-sm text-slate-300">Caricamento snapshot…</p>}
      {snapshot && <div className="min-w-0 space-y-2 text-sm text-slate-300">
        <p className="break-all">Impronta snapshot: {snapshot.digest}</p><p className="break-words">Archivio: {snapshot.manifest.namespace.join(' / ')}</p>
        <p className="break-words">Periodo: {formatIntradayNs(snapshot.manifest.start_at_ns)} → {formatIntradayNs(snapshot.manifest.end_at_ns)}</p>
        <p className="break-words">Cutoff: {formatIntradayNs(snapshot.manifest.cutoff_ns)} · Salvato: {formatIntradayNs(snapshot.known_at_ns)}</p>
        <p>Esito snapshot: {snapshot.report.outcome} · Verifica tecnica dataset: {snapshot.report.technical_result} · G1 software: {snapshot.report.g1_tech}</p>
        <p>Copertura raw: {(snapshot.report.metrics.raw.coverage * 100).toFixed(2)}% ({snapshot.report.metrics.raw.valid}/{snapshot.report.metrics.raw.planned})</p>
        {snapshot.report.metrics.grid.map((value, index) => <div key={index}><p>Listing {value.listing_id} · {value.session_date} · {value.minutes} minuti · {value.usable}/{value.planned} · {(value.coverage * 100).toFixed(2)}%</p><p>Esclusioni: {Object.entries(value.exclusions).map(([reason, count]) => reason + ': ' + count).join(', ') || 'nessuna'}</p></div>)}
        <p>Motivi: {snapshot.report.reasons.join(', ') || 'nessuno nel report'}</p>
        <p>Listing inclusi: {snapshot.manifest.listing_ids.join(', ')} · Richiesti: {snapshot.manifest.requested_listing_ids.join(', ')}</p>
        <p>Input {snapshot.inputs.length ? snapshot.offset + 1 : 0}–{snapshot.offset + snapshot.inputs.length} di {snapshot.total}</p>
        <ul className="space-y-1">{snapshot.inputs.map((row, index) => <li key={index} className="break-words">{String(row.table ?? row.kind ?? 'input')} · ID {String(row.id ?? '—')} · Disponibile {formatIntradayNs(row.available_at_ns as string | undefined)}</li>)}</ul>
        <button className={buttonClass} disabled={reading || snapshot.next_offset == null} onClick={() => void readSnapshot(snapshot.next_offset ?? 0)}>Pagina successiva snapshot</button>
      </div>}
      {status && <div className="space-y-3 text-sm text-slate-300">
        <h3 className="font-semibold text-white">Budget e lacune locali</h3>
        {status.budgets.length ? status.budgets.map((value, index) => <p key={index} className="break-words">{value.window_kind} {value.window_start}: {value.used_count}/{value.effective_limit} (configurato {value.configured_limit}){value.cooldown_until ? ' · pausa fino a ' + value.cooldown_until : ''}</p>) : <p>Nessuna finestra di budget registrata.</p>}
        {status.capture_gaps.length ? status.capture_gaps.map(value => <p key={value.id} className="break-words">GAP {value.capture_id}: {value.reason_code} · {formatIntradayNs(value.start_at_ns)} → {formatIntradayNs(value.end_at_ns)} · Pubblicazione {value.publication_id}</p>) : <p>Nessuna lacuna pubblicata nello stato locale; non attesta continuità o copertura.</p>}
        {status.latest_quality && <p className="break-words">Ultimo report REAL: snapshot {status.latest_quality.snapshot_id} · esito {status.latest_quality.outcome} · {status.latest_quality.namespace.join(' / ')} · {status.latest_quality.reasons.join(', ') || 'nessun motivo nel report'}. Il gate G1 dati resta INSUFFICIENTE.</p>}
      </div>}
    </div>
  </Panel>;
}
