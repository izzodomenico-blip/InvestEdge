"""Frozen research bundle references and explicit local jobs; no collection or execution."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass

from backend.app.data_providers.alpaca_metadata import MetadataError, decode_row
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.intraday.quality import planned_listing_ids, quality_report, validate_manifest
from backend.app.intraday.snapshots import (
    _MEMBER_SOURCE_ID_SQL,
    _MEMBER_SOURCE_TABLE_SQL,
    FrozenTimeline,
    SnapshotError,
    _locator_refs_sql,
    _StagedTimeline,
)
from backend.app.intraday_research.contracts import ResearchNamespace, digest, integer


@dataclass(frozen=True)
class DatasetChild:
    snapshot_id: int
    digest: str
    start_at_ns: int
    end_at_ns: int
    cutoff_ns: int
    known_at_ns: int
    publication_id: int
    publication_hash: str
    role: str = "RESEARCH"

    def __post_init__(self):
        integer(self.snapshot_id, positive=True)
        digest(self.digest)
        for stamp in (self.start_at_ns, self.end_at_ns, self.cutoff_ns, self.known_at_ns):
            integer(stamp)
        integer(self.publication_id, positive=True)
        digest(self.publication_hash)
        if (not self.start_at_ns < self.end_at_ns <= self.cutoff_ns <= self.known_at_ns or type(self.role) is not str
            or self.role not in {"RESEARCH", "IS", "OOS", "HOLDOUT"}):
            raise ValueError("BUNDLE_INVALID")


_CHILD_REFS = '''WITH child_refs AS (
    SELECT json_extract(m.payload_json,'$.reference') AS reference_json
    FROM intraday_research_bundle_children c JOIN intraday_dataset_members m ON m.snapshot_id=c.snapshot_id
    WHERE c.bundle_id=:snapshot AND json_extract(m.payload_json,'$.replay')=1
    UNION ALL
    SELECT dependency.value FROM intraday_research_bundle_children c
    JOIN intraday_dataset_members m ON m.snapshot_id=c.snapshot_id,json_each(m.payload_json,'$.dependencies') dependency
    WHERE c.bundle_id=:snapshot AND json_extract(m.payload_json,'$.replay')=1
      AND json_array_length(m.payload_json,'$.dependencies')>0
)'''

# Child validation bounds availability to nonnegative int64. Its fixed-width
# ASCII prefix preserves the v1 (availability, exact reference text) rank while
# grouping only typed identity, without a separate window sort of full refs.
_BUNDLE_REFS = _CHILD_REFS + ''', refs AS (
    SELECT substr(MIN((printf('%019d',COALESCE(json_extract(reference_json,'$.projection.available_at_ns'),
        9223372036854775807))||reference_json) COLLATE BINARY),20) AS reference_json,1 AS replay
    FROM child_refs GROUP BY json_extract(reference_json,'$.table'),json_extract(reference_json,'$.id')
)'''
_BUNDLE_ORDER_REFS = _locator_refs_sql(bundle=True)

# Child validation precedes this selector. Start from the requested news's
# typed links; dependencies use their small partial index and retain all refs.
_NEWS_LINK_REFS = '''WITH link_refs AS (
    SELECT json_extract(m.payload_json,'$.reference') AS reference_json
    FROM intraday_news_links l CROSS JOIN intraday_research_bundle_children c
    CROSS JOIN intraday_dataset_members m
    WHERE l.news_version_id=:news AND c.bundle_id=:snapshot AND m.snapshot_id=c.snapshot_id
      AND m.news_link_id=l.id AND json_extract(m.payload_json,'$.replay')=1
    UNION ALL
    SELECT dependency.value FROM intraday_research_bundle_children c
    CROSS JOIN intraday_dataset_members m CROSS JOIN json_each(m.payload_json,'$.dependencies') dependency
    CROSS JOIN intraday_news_links l
    WHERE c.bundle_id=:snapshot AND m.snapshot_id=c.snapshot_id
      AND json_array_length(m.payload_json,'$.dependencies')>0
      AND json_extract(m.payload_json,'$.replay')=1
      AND json_extract(dependency.value,'$.table')='intraday_news_links'
      AND l.id=json_extract(dependency.value,'$.id') AND l.news_version_id=:news
), ranked_refs AS (
    SELECT reference_json,ROW_NUMBER() OVER(
        PARTITION BY json_extract(reference_json,'$.table'),json_extract(reference_json,'$.id')
        ORDER BY COALESCE(json_extract(reference_json,'$.projection.available_at_ns'),9223372036854775807),
                 reference_json) AS ordinal
    FROM link_refs
) SELECT reference_json FROM ranked_refs WHERE ordinal=1 ORDER BY json_extract(reference_json,'$.id')'''


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class ValidatedBundle:
    bundle_id: int
    digest: str
    manifest: dict
    report: dict
    timeline: FrozenTimeline
    known_at_ns: int

    @property
    def evidence_format(self):
        return getattr(self.timeline,'evidence_format',None)

    @property
    def evidence_root(self):
        return getattr(self.timeline,'evidence_root',None)


class DatasetService:
    """Explicit bundle jobs and immutable reads; no collection or execution."""
    def __init__(self, snapshots):
        self.snapshots, self.db = snapshots, snapshots.connection

    def research_signal(self,bundle_id,*,config,listing_id,session_date,cutoff_ns,registry,quote_units,
                        previous_frames=(),references=None,benchmark_bundle_id=None,seen_keys=(),seen_events=()):
        """Frozen inputs to a pure setup; no execution, provider call or persistence."""
        from backend.app.intraday.contracts import QualityPolicy
        from backend.app.intraday.replay import select_versions
        from backend.app.intraday_research.contracts import CandidateConfig, ResearchError
        from backend.app.intraday_research.eligibility import evaluate_entry
        from backend.app.intraday_research.news_features import news_as_of
        from backend.app.intraday_research.strategies import evaluate_candidate, feature_frame
        if (type(config) is not CandidateConfig or type(previous_frames) is not tuple or len(previous_frames)>6 or
            registry.connection is not self.db or quote_units.registry.connection is not self.db):
            raise ResearchError('INVALID_CONTRACT')
        signature = self.snapshots._read_signature()
        context = self.research_context(bundle_id,listing_id=listing_id,session_date=session_date,cutoff_ns=cutoff_ns,
                                        benchmark_bundle_id=benchmark_bundle_id)
        quote_refs = tuple(r for r in references if r.kind in {'QUOTE_SIZE','PRICE_INCREMENT'}) if references is not None else None
        news_refs = tuple(r for r in references if r.kind=='NEWS_SOURCE') if references is not None else None
        common = evaluate_entry(context,quote_units=quote_units,references=quote_refs,holding_minutes=config.holding_minutes)
        bundle = self.open_bundle(bundle_id)
        rows,charge = [],0
        for row in bundle.timeline.iter_rows(cutoff_ns=cutoff_ns):
            if row['table']!='intraday_news_versions':
                continue
            charge += 16*len(_json(row).encode())
            if charge>67_108_864 or len(rows)>=10_000:
                raise ResearchError('RESOURCE_LIMIT')
            rows.append(row)
        coverage = context.index.context(cutoff_ns)['news_coverage']
        if coverage=='COVERED' and not rows:
            coverage = 'COVERED_ZERO'
        daily = context.daily()
        identities = select_versions(context.index.family['IDENTITY'],family='IDENTITY',
            cutoff_ns=context.current['open_at_ns']-1,listing_ids=(listing_id,))
        identity = max((r for r in identities if r['valid_from_ns']<=context.current['open_at_ns'] and
            (r['valid_to_ns'] is None or context.current['open_at_ns']<r['valid_to_ns'])),
            key=lambda r:(r['valid_from_ns'],r['available_at_ns'],r['id']),default=None)
        prior_close = None
        if daily['previous_close'] is not None:
            prior_close = {'listing_id':listing_id,'price':str(daily['previous_close']),'currency':'USD','unit':'USD_PER_SHARE',
                'share_class':identity['payload'].get('share_class') if identity and identity['confirmed'] else None,
                'source_digest':daily['sessions'][-1]['source_digest'],'available_at_ns':daily['sessions'][-1]['available_at_ns']}
        news = news_as_of(rows,registry=registry,namespace=context.namespace,listing_id=listing_id,cutoff_ns=cutoff_ns,
            references=news_refs,prior_close=prior_close,coverage=coverage)
        frame = feature_frame(context,technical=config.arm!='NEWS_ONLY')
        quote = context.index.quote(listing_id,cutoff_ns,QualityPolicy())
        ask = quote['payload']['raw']['ap'] if quote and quote['executable'] else None
        signal = evaluate_candidate(config,frames=(*previous_frames,frame),common=common,news=news,ask=ask,
                                    seen_keys=seen_keys,seen_events=seen_events)
        output = {'signal':signal,'frame':frame,'news':news}
        self.snapshots.archive.safe_json(output)
        if signature!=self.snapshots._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return output

    def research_context(self,bundle_id,*,listing_id,session_date,cutoff_ns,benchmark_bundle_id=None):
        """Read one decision and 30 prior sessions; no RAW expansion or writes.

        An optional previously published bundle supplies the pre-open benchmark
        choice. A retrospective bundle alone cannot attest that choice.
        """
        from backend.app.intraday.replay import _family, select_versions
        from backend.app.intraday_research.context import ResearchContext
        from backend.app.intraday_research.contracts import ResearchError

        integer(cutoff_ns)
        integer(listing_id,positive=True)
        signature = self.snapshots._read_signature()
        bundle = self.open_bundle(bundle_id)
        if listing_id not in bundle.manifest['listing_ids'] or cutoff_ns>bundle.manifest['cutoff_ns']:
            raise ResearchError('INPUT_MISSING')
        calendars,total = [],0
        for row in bundle.timeline.iter_rows(cutoff_ns=cutoff_ns):
            if _family(row)=='CALENDAR':
                total += len(_json(row).encode())*4
                if total>67_108_864:
                    raise ResearchError('RESOURCE_LIMIT')
                calendars.append(row)
        sessions = [r for r in select_versions(calendars,family='CALENDAR',cutoff_ns=cutoff_ns) if r['session_date']<=session_date]
        sessions.sort(key=lambda r:r['open_at_ns'])
        current = next((r for r in sessions if r['session_date']==session_date),None)
        if current is None or cutoff_ns<current['open_at_ns']:
            raise ResearchError('INPUT_MISSING')
        start = sessions[-31:][0]['open_at_ns']
        benchmarks,known,benchmark_hash = None,None,None
        if benchmark_bundle_id is not None:
            prior = self.open_bundle(benchmark_bundle_id)
            benchmarks,known = prior.manifest['benchmarks'],prior.known_at_ns
            benchmark_hash = prior.digest
            if (tuple(prior.manifest['namespace'])!=tuple(bundle.manifest['namespace']) or known>=current['open_at_ns']
                or benchmarks!=bundle.manifest['benchmarks'] or listing_id not in prior.manifest['listing_ids']):
                raise ResearchError('INPUT_MISSING')
        requested = {listing_id,*bundle.manifest['benchmarks'].values()}
        def inputs():
            quotes,quote_bytes = {},0
            for row in bundle.timeline.iter_rows(cutoff_ns=cutoff_ns):
                family = _family(row)
                if family=='BAR':
                    if row['listing_id'] in requested and start<=row['event_time_ns']<current['close_at_ns']:
                        yield row
                elif family=='QUOTE':
                    if row['listing_id']!=listing_id:
                        continue
                    stamp = row['event_time_ns']
                    if not quotes or stamp>next(iter(quotes.values()))['event_time_ns']:
                        quotes.clear()
                        quote_bytes = 0
                    if not quotes or stamp==next(iter(quotes.values()))['event_time_ns']:
                        if row['id'] not in quotes:
                            quote_bytes += len(_json(row).encode())*16
                        quotes[row['id']] = row
                    if len(quotes)>10_000 or quote_bytes>8_388_608:
                        raise ResearchError('RESOURCE_LIMIT')
                elif family=='NEWS':
                    continue  # This task uses durable coverage, not article contents.
                elif family in {'STATUS','LULD'}:
                    if row['listing_id'] in requested and row['available_at_ns']>=start-300_000_000_000:
                        yield row
                elif family=='CONTROL' and row['kind'] in {'CAPTURE_START','ACK','CLOCK','GAP','STOP'}:
                    if row['available_at_ns']>=start-300_000_000_000:
                        yield row
                else:
                    yield row
            yield from quotes.values()
        context = ResearchContext(inputs(),namespace=ResearchNamespace(*bundle.manifest['namespace']),listing_id=listing_id,
            session_date=session_date,cutoff_ns=cutoff_ns,benchmarks=benchmarks,benchmarks_known_at_ns=known,
            benchmark_evidence_hash=benchmark_hash)
        self.snapshots.archive.safe_json(context.daily())
        if signature!=self.snapshots._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return context

    def bind_attestations(self,bundle_id,*,references,registry,cutoff_ns):
        """Detached research context; original bundle/dataset bytes stay intact."""
        from backend.app.intraday_research.contracts import AttestationRef, ResearchError, canonical_hash
        integer(cutoff_ns)
        if (registry.connection is not self.db or type(references) is not tuple or not 1<=len(references)<=1_000
            or any(type(ref) is not AttestationRef for ref in references)
            or len({(ref.kind,ref.attestation_id) for ref in references})!=len(references)):
            raise ResearchError('INVALID_CONTRACT')
        signature = self.snapshots._read_signature()
        bundle = self.open_bundle(bundle_id)
        namespace = ResearchNamespace(*bundle.manifest['namespace'])
        if not bundle.manifest['start_at_ns']<=cutoff_ns<=bundle.manifest['cutoff_ns']:
            raise ResearchError('INVALID_TIMESTAMP')
        attestations = []
        for reference,row in zip(references,registry.read_attestations(references,namespace=namespace),strict=True):
            if row['available_at_ns']>cutoff_ns or row['listing_id'] not in bundle.manifest['listing_ids']:
                raise ResearchError('INPUT_MISSING')
            attestations.append(asdict(reference)|{key:row[key] for key in
                ('payload_hash','source_hash','authority_hash','available_at_ns','listing_id','valid_from_ns','valid_to_ns')})
        output = {'version':'attested-intraday-bundle-v1','bundle_id':bundle_id,'bundle_digest':bundle.digest,
                  'namespace':asdict(namespace),'cutoff_ns':cutoff_ns,'attestations':attestations,
                  'known_at_ns':max(bundle.known_at_ns,*(row['available_at_ns'] for row in attestations)),
                  'economic_status':'NOT_EVALUATED'}
        registry._guard(output)
        output['fingerprint'] = canonical_hash(output)
        registry._guard(output)
        self.snapshots.archive.safe_json(output)
        if signature!=self.snapshots._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return output

    def _children(self, request):
        if type(request) is not DatasetBundle:
            raise ValueError('BUNDLE_INVALID')
        result = []
        with self.snapshots.validated_sources([child.snapshot_id for child in request.children]) as source_scope:
            for child in request.children:
                # A v1 bundle names original RAW evidence. A v3 wrapper never
                # silently changes that authority; conversion is explicit.
                dataset = self.snapshots.open(child.snapshot_id, _source_scope=source_scope,_original=True)
                expected = (child.digest,child.start_at_ns,child.end_at_ns,child.cutoff_ns,child.known_at_ns,
                            child.publication_id,child.publication_hash)
                actual = (dataset.digest,dataset.manifest['start_at_ns'],dataset.manifest['end_at_ns'],dataset.manifest['cutoff_ns'],
                          dataset.known_at_ns,dataset.publication_id,dataset.publication_hash)
                if actual != expected or tuple(dataset.manifest['namespace']) != request.namespace.key:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                result.append(dataset)
        return result

    def _insert(self, table, namespace, payload, recorded, **fields):
        self.snapshots._guard()
        self._clock(recorded)
        text = self.snapshots.archive.safe_json(payload)
        values = dict(zip(('profile_id','feed','data_mode','provenance','replay_grade'),namespace,strict=True))
        values.update(schema_version='intraday-research-v1',payload_json=text,payload_hash=hashlib.sha256(text.encode()).hexdigest(),
                      recorded_at_ns=recorded,**fields)
        return self.db.execute(f"INSERT INTO {table}({','.join(values)}) VALUES({','.join('?' for _ in values)})",tuple(values.values())).lastrowid

    def _clock(self, floor):
        stamp = self.snapshots.archive.now()
        integer(stamp)
        if stamp<max(floor,getattr(self,'_write_floor',0)):
            raise MetadataError('SNAPSHOT_NOT_PIT')
        self._write_floor = stamp
        return stamp

    def freeze_bundle(self, request, *, cancelled=None, evidence_blocks=False):
        if type(evidence_blocks) is not bool:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        datasets = self._children(request)
        if self.db.in_transaction:
            raise MetadataError('TRANSACTION_ALREADY_OPEN')
        resources = {'max_disk_bytes':request.max_disk_bytes,'min_free_bytes':request.min_free_bytes,
                     'max_chunk_bytes':8_388_608}
        namespace = request.namespace.key
        listing_cap = min(30,self.snapshots.store.profile.max_symbols,self.snapshots.archive.settings.alpaca_max_symbols,
                          *(dataset.manifest.get('resources',{}).get('max_listings',30) for dataset in datasets))
        manifest = dict(datasets[0].manifest)
        manifest.update(version='intraday-bundle-quality-v1',selection='bundle-exact-union-v1',
            start_at_ns=min(child.start_at_ns for child in request.children),
            end_at_ns=max(child.end_at_ns for child in request.children),
            cutoff_ns=max(child.cutoff_ns for child in request.children),
            listing_ids=sorted({listing for dataset in datasets for listing in dataset.manifest['listing_ids']}))
        manifest['carry_at_ns'] = manifest['start_at_ns']-1
        for key in ('support_start_at_ns','history_sessions','window_session_count','resources',
                    'timeline_count','typed_member_count','audit_member_count','requested_listing_ids'):
            manifest.pop(key,None)
        if any(dataset.manifest['policy'] != manifest['policy'] or dataset.manifest['profile'] != manifest['profile']
               or dataset.manifest['benchmarks'] != manifest['benchmarks'] for dataset in datasets):
            raise ValueError('BUNDLE_INVALID')
        if len(manifest['listing_ids'])>listing_cap:
            raise SnapshotError('RESOURCE_LIMIT')
        recorded = self._clock(max(child.known_at_ns for child in request.children))
        if any(child.known_at_ns > recorded for child in request.children):
            raise MetadataError('SNAPSHOT_NOT_PIT')
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute('PRAGMA temp.cache_size=-8192')
        self.db.execute('BEGIN IMMEDIATE')
        stage = None
        try:
            self.snapshots._cancel(cancelled,'BEFORE_READ')
            stage = _StagedTimeline.from_frozen(self.snapshots,manifest,resources,datasets,cancelled=cancelled)
            planning = stage.planning()
            manifest['listing_ids'] = planned_listing_ids(manifest,planning)
            if len(manifest['listing_ids'])>listing_cap:
                raise SnapshotError('RESOURCE_LIMIT')
            report = quality_report(manifest,planning,row_factory=stage.session,resource_guard=stage.check_budget)
            count = self.db.execute(f'SELECT COUNT(*) FROM {stage.stage}').fetchone()[0]
            evidence = {'version':'intraday-dataset-bundle-v1','namespace':list(namespace),
                        'children':[asdict(child) for child in request.children], 'resources':resources,
                        'quality_manifest':manifest,'timeline_count':count,'report':report}
            encoded = _json(evidence)
            if len(encoded.encode()) > 67_108_864:
                raise SnapshotError('RESOURCE_LIMIT')
            bundle_digest = _hash(evidence)
            chunks = [encoded[index:index+50_000] for index in range(0,len(encoded),50_000)]
            recorded = self._clock(recorded)
            header = {'version':'intraday-dataset-bundle-header-v1','digest':bundle_digest,
                      'child_count':len(request.children),'chunk_count':len(chunks),'created_at_ns':recorded}
            bundle_id = self._insert('intraday_research_dataset_bundles',namespace,header,recorded,
                bundle_digest=bundle_digest,start_at_ns=manifest['start_at_ns'],end_at_ns=manifest['end_at_ns'],
                cutoff_ns=manifest['cutoff_ns'],child_count=len(request.children))
            for ordinal, child in enumerate(request.children,1):
                self.snapshots._cancel(cancelled,'DURING_RAW')
                self._insert('intraday_research_bundle_children',namespace,asdict(child),recorded,bundle_id=bundle_id,
                    snapshot_id=child.snapshot_id,dataset_digest=child.digest,ordinal=ordinal)
            for ordinal, chunk in enumerate(chunks,1):
                self._insert('intraday_research_bundle_chunks',namespace,{'version':'intraday-bundle-chunk-v1','text':chunk},
                             recorded,bundle_id=bundle_id,ordinal=ordinal)
            stage.check_budget()
            stage.close()
            stage = None
            self._clock(recorded)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        finally:
            if stage is not None:
                stage.close()
        # RAW is durable before availability is attested. Interrupted output
        # remains invisible, exactly as a data-layer snapshot publication.
        self.snapshots._cancel(cancelled,'BEFORE_PUBLICATION')
        published = self._clock(recorded)
        header_hash = self.db.execute('SELECT payload_hash FROM intraday_research_dataset_bundles WHERE id=?',(bundle_id,)).fetchone()[0]
        publication = {'version':'intraday-bundle-publication-v1','complete':True,'bundle_id':bundle_id,
                       'header_hash':header_hash,'digest':bundle_digest,'known_at_ns':published}
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.snapshots._cancel(cancelled,'PUBLISHING')
            self._insert('intraday_research_bundle_seals',namespace,publication,published,
                         bundle_id=bundle_id,bundle_digest=bundle_digest)
            self._clock(published)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        if evidence_blocks:
            return self.seal_bundle(bundle_id,max_disk_bytes=request.max_disk_bytes,
                min_free_bytes=request.min_free_bytes,cancelled=cancelled)
        return self.open_bundle(bundle_id)

    def _links(self, bundle_id, news_id):
        rows = self.db.execute(_NEWS_LINK_REFS,{'snapshot':bundle_id,'news':news_id})
        result = []
        for reference in rows:
            row = self.snapshots._hydrate(json.loads(reference[0]))
            row.pop('table',None)
            result.append(row)
        return result

    def seal_bundle(self,bundle_id,*,max_disk_bytes,min_free_bytes,cancelled=None):
        """Explicit v3 import: one source pool plus every original child member."""
        from backend.app.intraday.frozen_blocks import FrozenBlocks, _decode, _text, compact_member
        from backend.app.intraday.snapshots import _REFERENCES
        archive = FrozenBlocks(self.snapshots)
        if archive.find('BUNDLE',bundle_id) is not None:
            raise MetadataError('FROZEN_EVIDENCE_EXISTS')
        signature = self.snapshots._read_signature()
        metadata = self._read_bundle_metadata(bundle_id)
        evidence = metadata['evidence']
        documents = []
        for expected in evidence['children']:
            original = archive.audit_snapshot(expected['snapshot_id'],cancelled=cancelled)
            documents.append(archive.snapshot_evidence(original))
        self._child_documents(archive,evidence,documents)
        if self._bundle_count(bundle_id)!=evidence['timeline_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        legacy = FrozenTimeline(self.snapshots,bundle_id,evidence['quality_manifest'],evidence['timeline_count'],
            refs_sql=_BUNDLE_REFS,links=lambda news_id:self._links(bundle_id,news_id),_signature=signature,
            _order_refs_sql=_BUNDLE_ORDER_REFS)
        original = ValidatedBundle(bundle_id,metadata['header']['bundle_digest'],evidence['quality_manifest'],
                                   evidence['report'],legacy,metadata['seal']['recorded_at_ns'])
        stage = 'frozen_union_'+uuid.uuid4().hex
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute('PRAGMA temp.cache_size=-8192')
        try:
            set_id = archive._begin('BUNDLE',bundle_id,{'manifest':original.manifest,'digest':original.digest,
                'report':original.report,'known_at_ns':original.known_at_ns,'timeline_count':evidence['timeline_count'],
                'bundle_metadata':{key:value for key,value in metadata.items() if key!='evidence'},
                'child_documents':documents},max_disk_bytes,min_free_bytes,expected_signature=signature,cancelled=cancelled)
            self.snapshots._cancel(cancelled,'BEFORE_READ')
            self.db.execute(f'''CREATE TEMP TABLE {stage}(source_table TEXT,source_id INTEGER,
                reference_json TEXT,replay INTEGER,PRIMARY KEY(source_table,source_id)) WITHOUT ROWID''')
            # Audit inputs also belong to the source pool; replay inputs take
            # precedence using precisely the original min-availability/ref rank.
            inputs = _CHILD_REFS.replace("AND json_extract(m.payload_json,'$.replay')=1",'')
            inputs = inputs.replace("AS reference_json\n", "AS reference_json,json_extract(m.payload_json,'$.replay') AS replay\n",1)
            inputs = inputs.replace('SELECT dependency.value FROM',"SELECT dependency.value,json_extract(m.payload_json,'$.replay') FROM")
            self.db.execute(inputs+f''',choices AS (
                SELECT json_extract(reference_json,'$.table') AS source_table,json_extract(reference_json,'$.id') AS source_id,
                    MAX(replay) AS replay,
                    MIN(CASE WHEN replay=1 THEN printf('%019d',COALESCE(json_extract(reference_json,'$.projection.available_at_ns'),9223372036854775807))||reference_json END) AS active,
                    MIN(printf('%019d',COALESCE(json_extract(reference_json,'$.projection.available_at_ns'),9223372036854775807))||reference_json) AS any_ref
                FROM child_refs GROUP BY 1,2)
                INSERT INTO {stage} SELECT source_table,source_id,substr(COALESCE(active,any_ref),20),replay FROM choices''',
                {'snapshot':bundle_id})
            archive._budget(max_disk_bytes,min_free_bytes)
            def records():
                for table,source_id,text,replay in self.db.execute(f'SELECT * FROM {stage} ORDER BY source_table,source_id'):
                    ref = json.loads(text)
                    kind,column = (('UNIVERSE_MEMBER','universe_member_id') if table=='intraday_universe_members' else _REFERENCES[table])
                    body = {'reference':ref,'dependencies':[],'replay':bool(replay)}
                    member = dict(zip(('profile_id','feed','data_mode','provenance','replay_grade'),archive.scope,strict=True))
                    member.update(ingest_run_id=0,member_kind=kind,persisted_at_ns=original.known_at_ns,
                                  payload_json=_text(body),payload_hash=_hash(body),**{column:source_id})
                    raw = self.snapshots._raw_source(table,source_id)
                    payload = raw.pop('payload_json')
                    yield [member,[[_text(raw),payload]]]
            archive._blocks(set_id,'MEMBER',records(),maximum=max_disk_bytes,minimum=min_free_bytes,cancelled=cancelled)
            archive._build_locators(set_id,links=lambda news_id:self._links(bundle_id,news_id),manifest=original.manifest,cancelled=cancelled)
            def members():
                for child in evidence['children']:
                    for raw in self.db.execute('SELECT * FROM intraday_dataset_members WHERE snapshot_id=? ORDER BY ingest_sequence',(child['snapshot_id'],)):
                        yield [child['snapshot_id'],compact_member(raw)]
            archive._blocks(set_id,'CHILD',members(),maximum=max_disk_bytes,minimum=min_free_bytes,cancelled=cancelled)
            header = _decode(self.db.execute('SELECT * FROM intraday_frozen_sets WHERE id=?',(set_id,)).fetchone())
            header['metadata_chunks'] = header['payload'].get('metadata_chunks',0)
            staged = archive._raw_blocks(set_id,'CHILD',cancelled=cancelled)
            self._child_members(archive,header,evidence,documents,staged,write=True)
            archive._blocks(set_id,'TIMELINE',(archive._timeline_text(row) for row in archive._original_rows(original)),
                            maximum=max_disk_bytes,minimum=min_free_bytes,cancelled=cancelled)
            self.db.execute(f'DROP TABLE temp.{stage}')
            archive._finish(set_id,max_disk_bytes,min_free_bytes,cancelled,validate=lambda:self.open_bundle(bundle_id))
        except Exception:
            self.db.rollback()
            raise
        finally:
            self.db.execute(f'DROP TABLE IF EXISTS temp.{stage}')
        return self.open_bundle(bundle_id)

    def _child_documents(self,archive,evidence,documents):
        if len(documents)!=len(evidence['children']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        result = {}
        for expected,document in zip(evidence['children'],documents,strict=True):
            child = DatasetChild(**expected)
            header,report,pub = archive._metadata(document)
            manifest = header['payload']
            actual = (header['id'],document['digest'],manifest['start_at_ns'],manifest['end_at_ns'],manifest['cutoff_ns'],
                      document['known_at_ns'],document['publication_id'],document['publication_hash'])
            if actual!=(child.snapshot_id,child.digest,child.start_at_ns,child.end_at_ns,child.cutoff_ns,
                         child.known_at_ns,child.publication_id,child.publication_hash):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            result[child.snapshot_id] = (header,report,pub)
        return result

    def _child_source(self,archive,set_id,child_id,table,source_id,payload_hash=None):
        integer(source_id,positive=True)
        ref = self.db.execute('''SELECT reference_json FROM intraday_frozen_child_refs
            WHERE set_id=? AND child_id=? AND source_table=? AND source_id=?''',(set_id,child_id,table,source_id)).fetchone()
        if ref is None:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        reference = json.loads(ref[0])
        row = archive._source(set_id,table,source_id,projected=False)
        row.update(reference['projection'])
        row['table'] = table
        if payload_hash is not None and row['payload_hash']!=payload_hash:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return row

    def _child_members(self,archive,header,evidence,documents,blocks,*,write=False):
        from backend.app.intraday.frozen_blocks import (
            _NATIVE,
            SCOPE,
            _decode,
            _frame,
            _FramedRecords,
            _text,
            reference_text,
        )
        from backend.app.intraday.replay import check_ns, visible_rows
        from backend.app.intraday.snapshots import _REFERENCES
        states = {}
        for child_id,(child,report,pub) in self._child_documents(archive,evidence,documents).items():
            hasher = hashlib.sha256()
            _frame(hasher,_text(child['payload']))
            states[child_id] = {'header':child,'pub':pub,'hash':hasher,'members':0,'replay':0,'audit':0,
                                'latest':max(child['persisted_at_ns'],report['persisted_at_ns'])}
        total = 0
        metadata_seen = 0
        candidates = tuple(value for _,value in self.snapshots._secret_fields() if isinstance(value,str) and value)
        for ordinal,records in blocks:
            if (not write and not candidates and type(records) is list and not isinstance(records,_FramedRecords)
                and _NATIVE is not None and hasattr(_NATIVE,'frozen_children')):
                from backend.app.intraday.snapshots import _decode_evidence
                facts = [tuple(row) for row in self.db.execute('''SELECT c.child_id,c.block_ordinal,c.record_ordinal,
                    c.dependency_ordinal,c.source_table,c.source_id,c.payload_hash,c.source_hash,c.reference_json,c.replay,
                    c.rank_available,c.available,c.admission_id,c.publication_id FROM intraday_frozen_child_refs c
                    WHERE c.set_id=? AND c.block_ordinal=? ORDER BY c.record_ordinal,c.dependency_ordinal''',(header['id'],ordinal))]
                count = _NATIVE.frozen_children(records,facts,archive.scope,states,ordinal,_decode_evidence)
                if count is not NotImplemented:
                    total += count
                    continue
            decoded,needed = [],{}
            for index,(child_id,raw) in enumerate(records):
                if child_id=='METADATA' and metadata_seen<header.get('metadata_chunks',0):
                    metadata_seen += 1
                    continue
                integer(child_id,positive=True)
                state = states[child_id]
                member = _decode(raw)
                if candidates and SafeProviderTransport._payload_contains_secret(member,candidates):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                body = member['payload']
                if (tuple(member[key] for key in SCOPE)!=archive.scope or member['ingest_run_id']!=state['header']['ingest_run_id']
                    or type(body['replay']) is not bool or type(body['dependencies']) is not list):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                kind,column = _REFERENCES[body['reference']['table']]
                if member['member_kind']!=kind or type(member[column]) is not int or member[column]!=body['reference']['id']:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                _frame(state['hash'],member['payload_json'])
                state['members'] += 1
                state['latest'] = max(state['latest'],member['persisted_at_ns'])
                refs = [body['reference'],*body['dependencies']]
                for dep,ref in enumerate(refs,-1):
                    integer(ref['id'],positive=True)
                    needed.setdefault(ref['table'],set()).add(ref['id'])
                    decoded.append((child_id,index,dep,member,ref))
                state['replay' if body['replay'] else 'audit'] += len(refs)
            if len(decoded)>1000:
                raise SnapshotError('RESOURCE_LIMIT')
            sources = {}
            for table,ids in needed.items():
                pending = tuple(ids)
                for start in range(0,len(pending),500):
                    part = pending[start:start+500]
                    query = f'''SELECT s.source_id,s.source_hash,s.raw_available,s.persisted,s.metadata_scope,s.needs_closure,
                        l.payload_hash,l.received,l.kind FROM intraday_frozen_source_refs s JOIN intraday_frozen_locators l
                        ON l.set_id=s.set_id AND l.source_table=s.source_table AND l.source_id=s.source_id
                        WHERE s.set_id=? AND s.source_table=? AND s.source_id IN ({','.join('?' for _ in part)})'''
                    for row in self.db.execute(query,(header['id'],table,*part)):
                        sources[(table,row[0])] = tuple(row)
            expected = []
            for child_id,index,dep,member,ref in decoded:
                source = sources.get((ref['table'],ref['id']))
                if source is None or source[1]!=ref['source_hash'] or source[6]!=ref['payload_hash']:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                projection = ref['projection']
                allowed = {'available_at_ns','recorded_available_at_ns','admission_id','publication_id','publication_hash',
                           'capture_ingest_sequence','metadata_dependency','first_received_at_ns','table'}
                if (type(projection) is not dict or not set(projection)<=allowed or projection.get('table',ref['table'])!=ref['table']):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                replay = member['payload']['replay']
                available = projection.get('available_at_ns',source[2])
                rank = projection.get('available_at_ns',9223372036854775807)
                check_ns(rank)
                if replay:
                    check_ns(available)
                    if available>states[child_id]['header']['payload']['cutoff_ns'] or available<source[3] or source[3]<source[7]:
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                    if source[4]:
                        # Rare metadata namespaces use the complete original scope rule.
                        row = self._child_source_from_ref(archive,header['id'],ref)
                        if len(visible_rows([row],cutoff_ns=states[child_id]['header']['payload']['cutoff_ns'],namespace=archive.scope,_decoded=True))!=1:
                            raise MetadataError('SNAPSHOT_INPUT_MISSING')
                elif source[4]:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                value = (child_id,ordinal,index,dep,ref['table'],ref['id'],ref['payload_hash'],ref['source_hash'],
                         reference_text(member,ref),int(replay),rank,available,projection.get('admission_id'),projection.get('publication_id'))
                expected.append(value)
                total += 1
            if write:
                self.db.executemany('''INSERT INTO intraday_frozen_child_refs(set_id,child_id,block_ordinal,record_ordinal,dependency_ordinal,
                    source_table,source_id,payload_hash,source_hash,reference_json,replay,rank_available,available,admission_id,publication_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',((header['id'],*value) for value in expected))
            else:
                actual = [tuple(row) for row in self.db.execute('''SELECT child_id,block_ordinal,record_ordinal,dependency_ordinal,
                    source_table,source_id,payload_hash,source_hash,reference_json,replay,rank_available,available,admission_id,publication_id
                    FROM intraday_frozen_child_refs WHERE set_id=? AND block_ordinal=? ORDER BY record_ordinal,dependency_ordinal''',
                    (header['id'],ordinal))]
                if actual!=expected:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if self.db.execute('SELECT COUNT(*) FROM intraday_frozen_child_refs WHERE set_id=?',(header['id'],)).fetchone()[0]!=total:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if metadata_seen!=header.get('metadata_chunks',0):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if not write:
            # Source bindings were checked against fresh bounded source blocks
            # in validate_inputs; this pass binds each index row to its child.
            metadata = self.db.execute('''SELECT c.child_id,c.reference_json FROM intraday_frozen_source_refs s
                CROSS JOIN intraday_frozen_child_refs c ON c.set_id=s.set_id AND c.source_table=s.source_table AND c.source_id=s.source_id
                WHERE s.set_id=? AND s.metadata_scope=1 AND c.replay=1''',(header['id'],))
            for child_id,text in metadata:
                row = self._child_source_from_ref(archive,header['id'],json.loads(text))
                if len(visible_rows([row],cutoff_ns=states[child_id]['header']['payload']['cutoff_ns'],namespace=archive.scope,_decoded=True))!=1:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
        for state in states.values():
            manifest = state['header']['payload']
            if (state['hash'].hexdigest()!=state['header']['digest'] or state['members']!=state['header']['member_count']
                or state['members']!=manifest['typed_member_count'] or state['replay']!=manifest['timeline_count']
                or state['audit']!=manifest['audit_member_count']
                or state['pub']['payload']['durable_at_ns']<max(state['latest'],manifest['cutoff_ns'])
                or state['pub']['payload']['durable_at_ns']>state['pub']['available_at_ns']):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')

    def _child_source_from_ref(self,archive,set_id,ref):
        row = archive._source(set_id,ref['table'],ref['id'],projected=False)
        row.update(ref['projection'])
        row['table'] = ref['table']
        return row

    def _open_sealed_bundle(self,archive,found):
        from backend.app.intraday.frozen_blocks import BlockTimeline
        signature = self.snapshots._read_signature()
        header,seal = found
        body = header['payload']
        metadata = self._read_bundle_metadata(header['subject_id'],frozen=body['bundle_metadata'])
        evidence = metadata['evidence']
        if (body['digest']!=metadata['header']['bundle_digest'] or _json(body['manifest'])!=_json(evidence['quality_manifest'])
            or _json(body['report'])!=_json(evidence['report']) or body['known_at_ns']!=metadata['seal']['recorded_at_ns']
            or body['timeline_count']!=evidence['timeline_count']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        counts = self._parallel_bundle(archive,found)
        if counts is None:
            counts = archive.validate_inputs(found)
            self._child_members(archive,header,evidence,body['child_documents'],archive._read_blocks(header,seal,'CHILD'))
            self._bundle_closure(archive,header)
        if counts['replay']!=body['timeline_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        timeline = BlockTimeline(archive,header,seal,signature,10_000,8_388_608)
        timeline.validator = lambda:self.open_bundle(header['subject_id'])
        result = ValidatedBundle(header['subject_id'],body['digest'],body['manifest'],body['report'],timeline,body['known_at_ns'])
        if signature!=self.snapshots._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return result

    def _bundle_closure(self,archive,header):
        missing = self.db.execute('''SELECT 1 FROM intraday_frozen_child_refs src
            LEFT JOIN intraday_frozen_child_refs edge ON edge.set_id=src.set_id AND edge.child_id=src.child_id
                AND edge.source_table='intraday_capture_events' AND edge.source_id=src.admission_id
            LEFT JOIN intraday_frozen_locators receipt ON receipt.set_id=src.set_id
                AND receipt.source_table='intraday_capture_events' AND receipt.source_id=src.admission_id
            WHERE src.set_id=? AND src.replay=1 AND src.admission_id IS NOT NULL AND (edge.source_id IS NULL OR receipt.kind!='ADMISSION'
                OR receipt.admitted_table IS NOT src.source_table OR receipt.admitted_id IS NOT src.source_id
                OR receipt.admitted_hash IS NOT src.payload_hash) LIMIT 1''',(header['id'],)).fetchone()
        if missing:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        rare = self.db.execute('''SELECT c.child_id,c.source_table,c.source_id FROM intraday_frozen_source_refs s
            CROSS JOIN intraday_frozen_child_refs c ON c.set_id=s.set_id AND c.source_table=s.source_table AND c.source_id=s.source_id
            WHERE s.set_id=? AND s.needs_closure=1 AND c.replay=1
            UNION SELECT child_id,source_table,source_id FROM intraday_frozen_child_refs
            WHERE set_id=? AND replay=1 AND publication_id IS NOT NULL''',(header['id'],header['id']))
        for child_id,table,source_id in rare:
            row = self._child_source(archive,header['id'],child_id,table,source_id)
            self.snapshots._row_closure(child_id,row,require=lambda target,target_id,payload_hash=None,child_id=child_id:
                self._child_source(archive,header['id'],child_id,target,target_id,payload_hash))

    def _worker_request(self,header,seal,path):
        return {'path':str(path),'profile':asdict(self.snapshots.store.profile),
            'public_profile':self.snapshots.archive.public_profile,'namespace':list(self.snapshots.store.namespace),
            'limits':{name:getattr(self.snapshots.archive.settings,name) for name in ('alpaca_max_symbols','alpaca_max_archive_bytes')},
            'bundle_id':header['subject_id'],'set_id':header['id'],'header_hash':header['payload_hash'],
            'root':seal['root'],'digest':header['payload']['digest']}

    def _parallel_bundle(self,archive,found):
        """Three provisional read passes; accept only their joint, fenced result."""
        from pathlib import Path

        from backend.app.intraday.frozen_blocks import _NATIVE
        from backend.app.intraday.snapshots import _local_peak_rss_bytes
        header,seal = found
        if (self.db.in_transaction or seal['counts'].get('MEMBER',0)<100_000 or _NATIVE is None
            or any(value not in (None,'') for _,value in self.snapshots._secret_fields())
            or _local_peak_rss_bytes()>536_870_912):
            return None
        path = next((row[2] for row in self.db.execute('PRAGMA database_list') if row[1]=='main'),None)
        if not path:
            return None
        request = self._worker_request(header,seal,Path(path).resolve())
        return self._run_bundle_workers(request)

    def _run_bundle_workers(self,request):
        import os
        import subprocess
        import sys
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path

        from backend.app.intraday.snapshots import _record_worker_peaks
        message = _json(request)
        if len(message.encode())>1_048_576:
            raise SnapshotError('RESOURCE_LIMIT')
        # No application environment or sensitive inventory is copied to a
        # worker. Its store has no provider/client and its SQLite is mode=ro.
        environment = {name:value for name in ('SYSTEMROOT','WINDIR','TEMP','TMP') if (value:=os.environ.get(name))}
        environment.update(PYTHON_DOTENV_DISABLED='1',PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',INVESTEDGE_DB_PATH=':memory:')
        def run(role):
            try:
                completed = subprocess.run([sys.executable,'-B','-m',__name__,'--validate-worker',role],
                    input=message,text=True,encoding='utf-8',stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    cwd=Path(__file__).resolve().parents[3],env=environment,timeout=120,check=False,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                value = json.loads(completed.stdout)
                if completed.returncode or value.get('validated') is not True:
                    if value.get('error')=='RESOURCE_LIMIT':
                        raise SnapshotError('RESOURCE_LIMIT')
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                if (value.get('network_attempts')!=0 or value.get('changes')!=0
                    or type(value.get('peak_rss_bytes')) is not int or not 0<value['peak_rss_bytes']<=536_870_912):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                return value
            except SnapshotError:
                raise
            except (OSError,ValueError,subprocess.TimeoutExpired):
                raise MetadataError('SNAPSHOT_INPUT_MISSING') from None
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run,role) for role in ('SOURCES','CHILDREN','TIMELINE')]
            results = [future.result() for future in futures]
        _record_worker_peaks([result['peak_rss_bytes'] for result in results])
        count = results[2].get('timeline_count')
        if type(count) is not int or count!=results[0]['counts']['replay']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return results[0]['counts']

    def _bundle_count(self, bundle_id):
        # All child references have already passed full validation. Counting
        # typed identities needs no projection ranking or reference sorting.
        return self.db.execute(f'''WITH identities AS (
            SELECT {_MEMBER_SOURCE_TABLE_SQL} AS source_table,{_MEMBER_SOURCE_ID_SQL} AS source_id
            FROM intraday_research_bundle_children c JOIN intraday_dataset_members m ON m.snapshot_id=c.snapshot_id
            WHERE c.bundle_id=:snapshot AND json_extract(m.payload_json,'$.replay')=1
            UNION ALL SELECT json_extract(dependency.value,'$.table'),json_extract(dependency.value,'$.id')
            FROM intraday_research_bundle_children c JOIN intraday_dataset_members m ON m.snapshot_id=c.snapshot_id,
                json_each(m.payload_json,'$.dependencies') dependency
            WHERE c.bundle_id=:snapshot AND json_array_length(m.payload_json,'$.dependencies')>0
                AND json_extract(m.payload_json,'$.replay')=1
        ) SELECT COUNT(*) FROM (SELECT source_table,source_id FROM identities GROUP BY 1,2)''',
            {'snapshot':bundle_id}).fetchone()[0]

    def open_bundle(self, bundle_id):
        try:
            from backend.app.intraday.frozen_blocks import FrozenBlocks
            integer(bundle_id,positive=True)
            signature = self.snapshots._read_signature()
            archive = FrozenBlocks(self.snapshots)
            with archive.validation_scope():
                found = archive.find('BUNDLE',bundle_id)
                if found is not None:
                    result = self._open_sealed_bundle(archive,found)
                    if signature!=self.snapshots._read_signature():
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                    return result
            return self._open_bundle(bundle_id)
        except SnapshotError:
            raise
        except (MetadataError,ValueError,KeyError,TypeError,OverflowError,RecursionError,sqlite3.DatabaseError):
            raise MetadataError('SNAPSHOT_INPUT_MISSING') from None

    def _open_bundle(self, bundle_id):
        signature = self.snapshots._read_signature()
        metadata = self._read_bundle_metadata(bundle_id)
        evidence = metadata['evidence']
        request = DatasetBundle(tuple(DatasetChild(**child) for child in evidence['children']),
            ResearchNamespace(*evidence['namespace']),evidence['resources']['max_disk_bytes'],evidence['resources']['min_free_bytes'])
        self._children(request)
        count = self._bundle_count(bundle_id)
        if count!=evidence['timeline_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        manifest = evidence['quality_manifest']
        timeline = FrozenTimeline(self.snapshots,bundle_id,manifest,count,refs_sql=_BUNDLE_REFS,
                                  links=lambda news_id:self._links(bundle_id,news_id),_signature=signature,
                                  _order_refs_sql=_BUNDLE_ORDER_REFS)
        timeline.validator = lambda:self.open_bundle(bundle_id)
        result = ValidatedBundle(bundle_id,metadata['header']['bundle_digest'],manifest,evidence['report'],timeline,
                                 metadata['seal']['recorded_at_ns'])
        if signature!=self.snapshots._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return result

    def _read_bundle_metadata(self, bundle_id, *, frozen=None):
        """Validate original metadata, without constructing a data handle."""
        signature = self.snapshots._read_signature()
        integer(bundle_id,positive=True)
        scope = (self.snapshots.store.profile.profile_id,self.snapshots.store.profile.feed,*self.snapshots.store.namespace[1:])
        header = decode_row(frozen['header'] if frozen is not None else
            self.db.execute('SELECT * FROM intraday_research_dataset_bundles WHERE id=?',(bundle_id,)).fetchone())
        fields = ('profile_id','feed','data_mode','provenance','replay_grade')
        integer(header['id'],positive=True)
        if header['id']!=bundle_id or tuple(header[key] for key in fields) != scope:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        proof = header['payload']
        integer(header['recorded_at_ns'])
        if (header['schema_version']!='intraday-research-v1'
            or proof.get('version')!='intraday-dataset-bundle-header-v1'
            or proof['digest']!=header['bundle_digest']
            or type(proof['child_count']) is not int or not 1<=proof['child_count']<=1_000
            or proof['child_count']!=header['child_count']
            or type(proof['chunk_count']) is not int or not 1<=proof['chunk_count']<=1_343
            or type(proof['created_at_ns']) is not int or proof['created_at_ns']!=header['recorded_at_ns']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        seal = decode_row(frozen['seal'] if frozen is not None else
            self.db.execute('SELECT * FROM intraday_research_bundle_seals WHERE bundle_id=?',(bundle_id,)).fetchone())
        integer(seal['recorded_at_ns'])
        publication = seal['payload']
        if (seal['bundle_id']!=bundle_id or tuple(seal[key] for key in fields)!=scope or seal['recorded_at_ns']<header['recorded_at_ns']
            or seal['schema_version']!=header['schema_version']
            or publication.get('version')!='intraday-bundle-publication-v1' or publication.get('complete') is not True
            or type(publication['bundle_id']) is not int or publication['bundle_id']!=bundle_id
            or publication['header_hash']!=header['payload_hash'] or publication['digest']!=header['bundle_digest']
            or type(publication['known_at_ns']) is not int or publication['known_at_ns']!=seal['recorded_at_ns']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if frozen is None and self.db.execute('SELECT COUNT(*) FROM intraday_research_bundle_chunks WHERE bundle_id=?',(bundle_id,)).fetchone()[0]!=proof['chunk_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        chunks = frozen['chunks'] if frozen is not None else list(self.db.execute('SELECT * FROM intraday_research_bundle_chunks WHERE bundle_id=? ORDER BY ordinal',(bundle_id,)))
        if len(chunks) != header['payload']['chunk_count'] or seal['bundle_digest'] != header['bundle_digest']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        texts, size = [], 0
        for ordinal, raw in enumerate(chunks,1):
            chunk = decode_row(raw)
            integer(chunk['ordinal'],positive=True)
            if (chunk['bundle_id']!=bundle_id or chunk['ordinal'] != ordinal or tuple(chunk[key] for key in fields) != scope
                or chunk['recorded_at_ns'] != header['recorded_at_ns'] or chunk['schema_version']!=header['schema_version']
                or chunk['payload'].get('version')!='intraday-bundle-chunk-v1' or type(chunk['payload']['text']) is not str):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            value = chunk['payload']['text']
            size += len(value.encode())
            if size > 67_108_864:
                raise SnapshotError('RESOURCE_LIMIT')
            texts.append(value)
        encoded = ''.join(texts)
        evidence = json.loads(encoded)
        if (evidence.get('version')!='intraday-dataset-bundle-v1' or _json(evidence)!=encoded
            or _hash(evidence) != header['bundle_digest'] or evidence['namespace'] != list(scope)):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if frozen is None and self.db.execute('SELECT COUNT(*) FROM intraday_research_bundle_children WHERE bundle_id=?',(bundle_id,)).fetchone()[0]!=proof['child_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        children = frozen['children'] if frozen is not None else list(self.db.execute('SELECT * FROM intraday_research_bundle_children WHERE bundle_id=? ORDER BY ordinal',(bundle_id,)))
        if len(children) != header['child_count'] or len(children) != len(evidence['children']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        for ordinal, (raw,expected) in enumerate(zip(children,evidence['children'],strict=True),1):
            child = decode_row(raw)
            integer(child['ordinal'],positive=True)
            if (child['bundle_id']!=bundle_id or child['payload'] != expected or child['ordinal'] != ordinal or child['snapshot_id'] != expected['snapshot_id']
                or child['dataset_digest'] != expected['digest'] or tuple(child[key] for key in fields) != scope
                or child['recorded_at_ns']!=header['recorded_at_ns'] or child['schema_version']!=header['schema_version']
                or expected['known_at_ns']>header['recorded_at_ns']):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        resources = evidence['resources']
        if (set(resources)!={'max_disk_bytes','min_free_bytes','max_chunk_bytes'}
            or any(type(value) is not int or value<=0 for value in resources.values())
            or resources['max_chunk_bytes']>8_388_608):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        request = DatasetBundle(tuple(DatasetChild(**child) for child in evidence['children']),ResearchNamespace(*scope),
            evidence['resources']['max_disk_bytes'],evidence['resources']['min_free_bytes'])
        manifest = evidence['quality_manifest']
        validate_manifest(manifest)
        if (manifest['version']!='intraday-bundle-quality-v1' or manifest['selection']!='bundle-exact-union-v1'
            or tuple(manifest['namespace'])!=scope or len(manifest['listing_ids'])>30
            or type(manifest['carry_at_ns']) is not int or manifest['carry_at_ns']!=manifest['start_at_ns']-1
            or any(header[key] != manifest[key] for key in ('start_at_ns','end_at_ns','cutoff_ns'))
            or manifest['start_at_ns']!=min(child.start_at_ns for child in request.children)
            or manifest['end_at_ns']!=max(child.end_at_ns for child in request.children)
            or manifest['cutoff_ns']!=max(child.cutoff_ns for child in request.children)):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        integer(evidence['timeline_count'])
        candidates = tuple(value for name,value in self.snapshots._secret_fields() if isinstance(value,str) and value)
        if candidates and SafeProviderTransport._payload_contains_secret(
            {'evidence':evidence,'digest':header['bundle_digest']},candidates):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if signature!=self.snapshots._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return {'header':{key:value for key,value in header.items() if key!='payload'},
                'seal':{key:value for key,value in seal.items() if key!='payload'},
                'chunks':[dict(row) for row in chunks],'children':[dict(row) for row in children],'evidence':evidence}


@dataclass(frozen=True)
class DatasetBundle:
    children: tuple[DatasetChild, ...]
    namespace: ResearchNamespace
    max_disk_bytes: int
    min_free_bytes: int

    def __post_init__(self):
        integer(self.max_disk_bytes, positive=True)
        integer(self.min_free_bytes, positive=True)
        if (type(self.namespace) is not ResearchNamespace or type(self.children) is not tuple
            or not 1 <= len(self.children) <= 1_000
            or any(type(child) is not DatasetChild for child in self.children)
            or len({child.snapshot_id for child in self.children}) != len(self.children)
            or tuple(sorted(self.children, key=lambda child: (child.start_at_ns, child.end_at_ns, child.snapshot_id))) != self.children):
            raise ValueError("BUNDLE_INVALID")


def _read_bundle_worker(request,role):
    """Private provisional validation. Never returns a timeline or source row."""
    from contextlib import ExitStack
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import patch

    from backend.app.intraday.contracts import FeedProfile, canonical_json
    from backend.app.intraday.frozen_blocks import FrozenBlocks
    from backend.app.intraday.snapshots import SnapshotService, _peak_rss_bytes
    attempts = 0
    def deny(*args,**kwargs):
        nonlocal attempts
        attempts += 1
        raise MetadataError('WORKER_NETWORK_FORBIDDEN')
    with ExitStack() as stack:
        for target in ('socket.socket','socket.create_connection','socket.getaddrinfo','_socket.socket'):
            stack.enter_context(patch(target,deny))
        path = Path(request['path'])
        if not path.is_absolute() or role not in {'SOURCES','CHILDREN','TIMELINE'}:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        db = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        stack.callback(db.close)
        db.row_factory = sqlite3.Row
        allowed = {sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE}
        def authorize(action,first,second,*args):
            if action==sqlite3.SQLITE_PRAGMA:
                return sqlite3.SQLITE_OK if first in {'data_version','schema_version','database_list'} and second is None else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
        db.set_authorizer(authorize)
        profile = dict(request['profile'])
        for key in ('required_capabilities','attested_capabilities','quote_conditions'):
            profile[key] = tuple(profile[key])
        profile = FeedProfile(**profile)
        archive = SimpleNamespace(settings=SimpleNamespace(**request['limits']),public_profile=request['public_profile'],safe_json=canonical_json)
        store = SimpleNamespace(profile=profile,namespace=tuple(request['namespace']),archive=archive,connection=db,write_guard=None)
        reader = SnapshotService(store)
        reader._validation_rss_limit = 536_870_912
        signature = reader._read_signature()
        blocks = FrozenBlocks(reader)
        with blocks.validation_scope():
            found = blocks.find('BUNDLE',request['bundle_id'])
            if found is None:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            header,seal = found
            if (header['id']!=request['set_id'] or header['payload_hash']!=request['header_hash']
                or seal['root']!=request['root'] or header['payload']['digest']!=request['digest']):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            result = {'validated':True}
            if role=='SOURCES':
                result['counts'] = blocks.validate_inputs(found,timeline=False)
            elif role=='TIMELINE':
                result['timeline_count'] = blocks.validate_timeline(found,expected_count=header['payload']['timeline_count'])
            else:
                research = DatasetService(reader)
                metadata = research._read_bundle_metadata(header['subject_id'],frozen=header['payload']['bundle_metadata'])
                research._child_members(blocks,header,metadata['evidence'],header['payload']['child_documents'],blocks._read_blocks(header,seal,'CHILD'))
                research._bundle_closure(blocks,header)
        if signature!=reader._read_signature() or attempts or db.total_changes:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        result.update(peak_rss_bytes=_peak_rss_bytes(),network_attempts=attempts,changes=db.total_changes)
        if result['peak_rss_bytes']>reader._validation_rss_limit:
            raise SnapshotError('RESOURCE_LIMIT')
        return result


def _bundle_worker_entry():
    import sys
    try:
        message = sys.stdin.buffer.read(1_048_577)
        if len(message)>1_048_576 or len(sys.argv)!=3 or sys.argv[1]!='--validate-worker':
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        result = _read_bundle_worker(json.loads(message),sys.argv[2])
    except Exception as error:
        code = 'RESOURCE_LIMIT' if isinstance(error,SnapshotError) and str(error)=='RESOURCE_LIMIT' else 'SNAPSHOT_INPUT_MISSING'
        print(_json({'validated':False,'error':code}),flush=True)
        return 1
    print(_json(result),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(_bundle_worker_entry())
