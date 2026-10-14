"""Frozen research bundle references and explicit local jobs; no collection or execution."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass

from backend.app.data_providers.alpaca_metadata import MetadataError, decode_row
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.intraday.quality import planned_listing_ids, quality_report, validate_manifest
from backend.app.intraday.snapshots import FrozenTimeline, SnapshotError, _StagedTimeline
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

_BUNDLE_REFS = _CHILD_REFS + ''', ranked_refs AS (
    SELECT *,ROW_NUMBER() OVER(PARTITION BY json_extract(reference_json,'$.table'),json_extract(reference_json,'$.id')
        ORDER BY COALESCE(json_extract(reference_json,'$.projection.available_at_ns'),9223372036854775807),reference_json) AS ordinal
    FROM child_refs
), refs AS (SELECT reference_json,1 AS replay FROM ranked_refs WHERE ordinal=1)'''

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


class DatasetService:
    """Explicit bundle jobs and immutable reads; no collection or execution."""
    def __init__(self, snapshots):
        self.snapshots, self.db = snapshots, snapshots.connection

    def _children(self, request):
        if type(request) is not DatasetBundle:
            raise ValueError('BUNDLE_INVALID')
        result = []
        with self.snapshots.validated_sources([child.snapshot_id for child in request.children]) as source_scope:
            for child in request.children:
                dataset = self.snapshots.open(child.snapshot_id, _source_scope=source_scope)
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

    def freeze_bundle(self, request, *, cancelled=None):
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
        return self.open_bundle(bundle_id)

    def _links(self, bundle_id, news_id):
        rows = self.db.execute(_NEWS_LINK_REFS,{'snapshot':bundle_id,'news':news_id})
        result = []
        for reference in rows:
            row = self.snapshots._hydrate(json.loads(reference[0]))
            row.pop('table',None)
            result.append(row)
        return result

    def _bundle_count(self, bundle_id):
        # All child references have already passed full validation. Counting
        # typed identities needs no projection ranking or reference sorting.
        return self.db.execute(_CHILD_REFS + ''' SELECT COUNT(*) FROM (
            SELECT json_extract(reference_json,'$.table'),json_extract(reference_json,'$.id')
            FROM child_refs GROUP BY 1,2)''', {'snapshot':bundle_id}).fetchone()[0]

    def open_bundle(self, bundle_id):
        try:
            return self._open_bundle(bundle_id)
        except SnapshotError:
            raise
        except (MetadataError,ValueError,KeyError,TypeError,OverflowError,RecursionError,sqlite3.DatabaseError):
            raise MetadataError('SNAPSHOT_INPUT_MISSING') from None

    def _open_bundle(self, bundle_id):
        signature = self.snapshots._read_signature()
        integer(bundle_id,positive=True)
        scope = (self.snapshots.store.profile.profile_id,self.snapshots.store.profile.feed,*self.snapshots.store.namespace[1:])
        header = decode_row(self.db.execute('SELECT * FROM intraday_research_dataset_bundles WHERE id=?',(bundle_id,)).fetchone())
        fields = ('profile_id','feed','data_mode','provenance','replay_grade')
        if tuple(header[key] for key in fields) != scope:
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
        seal = decode_row(self.db.execute('SELECT * FROM intraday_research_bundle_seals WHERE bundle_id=?',(bundle_id,)).fetchone())
        integer(seal['recorded_at_ns'])
        publication = seal['payload']
        if (tuple(seal[key] for key in fields)!=scope or seal['recorded_at_ns']<header['recorded_at_ns']
            or seal['schema_version']!=header['schema_version']
            or publication.get('version')!='intraday-bundle-publication-v1' or publication.get('complete') is not True
            or type(publication['bundle_id']) is not int or publication['bundle_id']!=bundle_id
            or publication['header_hash']!=header['payload_hash'] or publication['digest']!=header['bundle_digest']
            or type(publication['known_at_ns']) is not int or publication['known_at_ns']!=seal['recorded_at_ns']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if self.db.execute('SELECT COUNT(*) FROM intraday_research_bundle_chunks WHERE bundle_id=?',(bundle_id,)).fetchone()[0]!=proof['chunk_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        chunks = list(self.db.execute('SELECT * FROM intraday_research_bundle_chunks WHERE bundle_id=? ORDER BY ordinal',(bundle_id,)))
        if len(chunks) != header['payload']['chunk_count'] or seal['bundle_digest'] != header['bundle_digest']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        texts, size = [], 0
        for ordinal, raw in enumerate(chunks,1):
            chunk = decode_row(raw)
            if (chunk['ordinal'] != ordinal or tuple(chunk[key] for key in fields) != scope
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
        if self.db.execute('SELECT COUNT(*) FROM intraday_research_bundle_children WHERE bundle_id=?',(bundle_id,)).fetchone()[0]!=proof['child_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        children = list(self.db.execute('SELECT * FROM intraday_research_bundle_children WHERE bundle_id=? ORDER BY ordinal',(bundle_id,)))
        if len(children) != header['child_count'] or len(children) != len(evidence['children']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        for ordinal, (raw,expected) in enumerate(zip(children,evidence['children'],strict=True),1):
            child = decode_row(raw)
            if (child['payload'] != expected or child['ordinal'] != ordinal or child['snapshot_id'] != expected['snapshot_id']
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
        self._children(request)
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
        count = self._bundle_count(bundle_id)
        if count != evidence['timeline_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        candidates = tuple(value for name,value in self.snapshots._secret_fields() if isinstance(value,str) and value)
        if candidates and SafeProviderTransport._payload_contains_secret(
            {'evidence':evidence,'digest':header['bundle_digest']},candidates):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        timeline = FrozenTimeline(self.snapshots,bundle_id,manifest,count,refs_sql=_BUNDLE_REFS,
                                  links=lambda news_id:self._links(bundle_id,news_id),_signature=signature)
        timeline.validator = lambda:self.open_bundle(bundle_id)
        result = ValidatedBundle(bundle_id,header['bundle_digest'],manifest,evidence['report'],timeline,seal['recorded_at_ns'])
        if signature!=self.snapshots._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return result


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
