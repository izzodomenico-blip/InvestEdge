from __future__ import annotations

import importlib
import sqlite3

import pytest
from test_intraday_snapshots import service
from test_intraday_store import MINUTE, OPEN, event, prepared


def test_research_bundle_contract_is_pure_and_requires_frozen_child_references():
    datasets = importlib.import_module("backend.app.intraday_research.datasets")
    with pytest.raises(ValueError):
        datasets.DatasetBundle(children=(), namespace=(), max_disk_bytes=0, min_free_bytes=0)


def test_window_freeze_uses_versioned_selection_and_refuses_replay_before_carry():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s, at=OPEN - MINUTE), event(s)))
    reader = service(s)
    saved = reader.freeze_window(start_at_ns=OPEN, end_at_ns=OPEN + 3 * MINUTE,
        cutoff_ns=s.clock.now, listing_ids=[s.listing], benchmarks={},
        resources={'max_disk_bytes': 4 * 1024**3, 'min_free_bytes': 512 * 1024**2})
    result = reader.open(saved.snapshot_id)
    assert result.manifest['version'] == 'intraday-dataset-v2'
    assert result.manifest['selection'] == 'window-dependency-closure-v2'
    assert result.manifest['carry_at_ns'] == OPEN - 1
    with pytest.raises(ValueError, match='SNAPSHOT_CUTOFF'):
        reader.replay(saved.snapshot_id, cutoff_ns=OPEN - 2)


def test_bundle_overlap_is_counted_once_and_global_quality_is_recomputed():
    datasets = importlib.import_module('backend.app.intraday_research.datasets')
    from backend.app.database import RESEARCH_INDEX_SCHEMA
    from backend.app.intraday_research.contracts import ResearchNamespace

    s = prepared()
    s.db.executescript(RESEARCH_INDEX_SCHEMA)
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes': 4 * 1024**3, 'min_free_bytes': 512 * 1024**2}
    children = []
    for start in (OPEN, OPEN + 1):
        saved = reader.freeze_window(start_at_ns=start, end_at_ns=OPEN + 3 * MINUTE,
            cutoff_ns=s.clock.now, listing_ids=[s.listing], benchmarks={}, resources=resources)
        frozen = reader.open(saved.snapshot_id)
        children.append(datasets.DatasetChild(saved.snapshot_id, saved.digest, start,
            OPEN + 3 * MINUTE, s.clock.now, frozen.known_at_ns, frozen.publication_id, frozen.publication_hash))
    request = datasets.DatasetBundle(tuple(children), ResearchNamespace(*reader.open(children[0].snapshot_id).manifest['namespace']), **resources)
    research = datasets.DatasetService(reader)
    result = research.freeze_bundle(request)
    before = s.db.total_changes
    reopened = research.open_bundle(result.bundle_id)
    rows = list(reopened.timeline)
    assert len(rows) == len({(row['table'],row['id']) for row in rows})
    assert reopened.report['metrics']['sessions'] == 1
    assert reopened.report['outcome'] != 'READY'
    assert 'SESSIONS_INSUFFICIENT' in reopened.report['reasons']
    assert s.db.total_changes == before
    with pytest.raises(ValueError,match='SNAPSHOT_CUTOFF'):
        list(reopened.timeline.iter_rows(cutoff_ns=OPEN-2))
    with pytest.raises(sqlite3.IntegrityError, match='RESEARCH_APPEND_ONLY'):
        s.db.execute('DELETE FROM intraday_research_dataset_bundles WHERE id=?', (result.bundle_id,))


def test_bundle_quality_period_can_span_the_preregistered_multi_year_experiment():
    from test_intraday_quality import manifest

    from backend.app.intraday.quality import validate_manifest
    body = manifest()
    body.update(version='intraday-bundle-quality-v1',end_at_ns=OPEN+700*86400*1_000_000_000,
                cutoff_ns=OPEN+700*86400*1_000_000_000,carry_at_ns=OPEN-1)
    validate_manifest(body)


@pytest.mark.parametrize('stop', ['cancel', 'budget'])
def test_bundle_staging_checks_every_processed_occurrence_including_duplicates(monkeypatch, stop):
    from types import SimpleNamespace

    from backend.app.intraday.snapshots import SnapshotError, _StagedTimeline

    s = prepared()
    reader = service(s)
    s.store.persist((event(s),))
    row = s.store.read_as_of('BAR', cutoff_ns=s.clock.now)[0]
    row['table'] = 'intraday_observations'
    reference = reader._reference(row)
    monkeypatch.setattr(reader, '_reference', lambda item: reference)
    processed = 0

    def rows():
        nonlocal processed
        for _ in range(2100):
            processed += 1
            yield row

    def cancelled(phase):
        return phase == 'DURING_BUNDLE_STAGING' and processed >= 1000

    def budget(stage):
        if processed >= 1000:
            raise SnapshotError('RESOURCE_LIMIT')

    if stop == 'budget':
        monkeypatch.setattr(_StagedTimeline, 'check_budget', budget)
    kwargs = {'cancelled': cancelled} if stop == 'cancel' else {}
    with pytest.raises(ValueError, match='CANCELLED' if stop == 'cancel' else 'RESOURCE_LIMIT'):
        _StagedTimeline.from_frozen(reader, {}, {'max_chunk_bytes': 8388608,
                                   'max_disk_bytes': 4 * 1024**3, 'min_free_bytes': 512 * 1024**2},
                                   [SimpleNamespace(timeline=rows())], **kwargs)
    assert processed <= 1000
    assert s.db.execute("SELECT COUNT(*) FROM sqlite_temp_master WHERE name LIKE 'timeline_stage_%'").fetchone()[0] == 0


def test_bundle_cancel_during_staging_rolls_back_before_raw_or_seal():
    from backend.app.database import RESEARCH_INDEX_SCHEMA
    from backend.app.intraday_research.contracts import ResearchNamespace
    from backend.app.intraday_research.datasets import DatasetBundle, DatasetChild, DatasetService

    s = prepared()
    s.db.executescript(RESEARCH_INDEX_SCHEMA)
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes': 4 * 1024**3, 'min_free_bytes': 512 * 1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN, end_at_ns=OPEN + 3 * MINUTE,
        cutoff_ns=s.clock.now, listing_ids=[s.listing], benchmarks={}, resources=resources)
    frozen = reader.open(saved.snapshot_id)
    child = DatasetChild(saved.snapshot_id, saved.digest, OPEN, OPEN + 3 * MINUTE,
        s.clock.now, frozen.known_at_ns, frozen.publication_id, frozen.publication_hash)
    request = DatasetBundle((child,), ResearchNamespace(*frozen.manifest['namespace']), **resources)
    with pytest.raises(ValueError, match='CANCELLED'):
        DatasetService(reader).freeze_bundle(request, cancelled=lambda phase: phase == 'DURING_BUNDLE_STAGING')
    assert not s.db.in_transaction
    for table in ('intraday_research_dataset_bundles', 'intraday_research_bundle_children',
                  'intraday_research_bundle_chunks', 'intraday_research_bundle_seals'):
        assert s.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    assert s.db.execute("SELECT COUNT(*) FROM sqlite_temp_master WHERE name LIKE 'timeline_stage_%'").fetchone()[0] == 0


def test_window_job_enforces_declared_rss_budget_before_publication():
    s = prepared()
    reader = service(s)
    reader.register_policy()
    with pytest.raises(ValueError,match='RESOURCE_LIMIT'):
        reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
            listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,
            'min_free_bytes':512*1024**2,'max_rss_bytes':1})
    assert s.db.execute('SELECT COUNT(*) FROM intraday_dataset_snapshots').fetchone()[0] == 0


def test_window_keeps_superseded_checkpoint_still_referenced_by_handshake():
    from test_intraday_collector import boot
    from test_intraday_replay import live_capture
    from test_intraday_store import SECOND
    s = live_capture()
    old = next(row for row in s.events.read_as_of(cutoff_ns=s.clock.now,revisions=True)
               if row['payload'].get('version')=='utp-status-checkpoint-v1')
    ids = boot(s)
    new = next(row for row in s.events.read_as_of(cutoff_ns=s.clock.now,revisions=True) if row['id'] in ids)
    assert new['supersedes_id'] == old['id']
    reader = service(s)
    reader.register_policy()
    start = s.clock.now+1
    s.clock.now = start
    expected = s.store.replay_as_of(cutoff_ns=start)['capture']
    assert expected['state']=='LIVE'
    end = start+MINUTE
    s.clock.now = end+10*SECOND
    saved = reader.freeze_window(start_at_ns=start,end_at_ns=end,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    frozen = reader.open(saved.snapshot_id)
    assert {old['id'],new['id']} <= {row['id'] for row in frozen.timeline if row['table']=='intraday_event_versions'}
    assert reader.replay(saved.snapshot_id,cutoff_ns=start)['capture']==expected


def test_window_carry_does_not_use_future_quote_revision_and_is_immutable_after_append():
    from test_intraday_store import SECOND
    s = prepared()
    reader = service(s)
    s.clock.now = OPEN-SECOND
    reader.register_policy()
    s.store.persist((event(s,kind='QUOTE',at=OPEN-SECOND),))
    expected = s.store.replay_as_of(cutoff_ns=OPEN)['observations']['QUOTE']
    s.clock.now = OPEN+SECOND
    s.store.persist((event(s,kind='QUOTE',at=OPEN-SECOND,change={'bp':99}),))
    s.clock.now = OPEN+3*MINUTE+10*SECOND
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    assert reader.replay(saved.snapshot_id,cutoff_ns=OPEN)['observations']['QUOTE']==expected
    before = list(reader.open(saved.snapshot_id).timeline)
    s.clock.now += SECOND
    s.store.persist((event(s,kind='QUOTE',at=OPEN-SECOND,change={'bp':98}),))
    assert list(reader.open(saved.snapshot_id).timeline)==before


def test_window_accepts_full_registered_resource_profile_and_binds_chunk_limits():
    from dataclasses import asdict

    from backend.app.intraday_research.contracts import ResourceLimits
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist(tuple(event(s,at=OPEN+i*MINUTE) for i in range(10)))
    resources = asdict(ResourceLimits(max_disk_bytes=4*1024**3,min_free_bytes=512*1024**2,
                                     max_chunk_occurrences=3))
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+10*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    handle = reader.open(saved.snapshot_id)
    assert handle.manifest['resources']==resources
    assert all(len(chunk)<=3 for chunk in handle.timeline.chunks())


@pytest.mark.parametrize('key,value',[('max_chunk_occurrences',True),('max_chunk_bytes',-1),
    ('max_cache_bytes',67_108_865),('max_listings',31),('window_sessions',6),('history_sessions',31)])
def test_window_manifest_rejects_invalid_frozen_resource_limits(key,value):
    from backend.app.intraday.quality import validate_manifest
    s = prepared()
    reader = service(s)
    reader.register_policy()
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    manifest = reader.open(saved.snapshot_id).manifest
    manifest['resources'][key] = value
    with pytest.raises(ValueError,match='DATASET_INVALID'):
        validate_manifest(manifest)


def _small_bundle():
    from backend.app.database import RESEARCH_INDEX_SCHEMA
    from backend.app.intraday_research.contracts import ResearchNamespace
    from backend.app.intraday_research.datasets import DatasetBundle, DatasetChild, DatasetService
    s = prepared()
    s.db.executescript(RESEARCH_INDEX_SCHEMA)
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    frozen = reader.open(saved.snapshot_id)
    child = DatasetChild(saved.snapshot_id,saved.digest,OPEN,OPEN+3*MINUTE,s.clock.now,
        frozen.known_at_ns,frozen.publication_id,frozen.publication_hash)
    research = DatasetService(reader)
    result = research.freeze_bundle(DatasetBundle((child,),ResearchNamespace(*frozen.manifest['namespace']),**resources))
    return s,research,result


@pytest.mark.parametrize('column',['recorded_at_ns','feed'])
def test_bundle_seal_is_bound_to_header_scope_and_clock(column):
    s,research,bundle = _small_bundle()
    s.db.execute('DROP TRIGGER trg_intraday_research_bundle_seals_no_update')
    s.db.commit()
    s.db.execute('PRAGMA foreign_keys=OFF')
    value = s.clock.now+1 if column=='recorded_at_ns' else 'iex'
    s.db.execute(f'UPDATE intraday_research_bundle_seals SET {column}=?',(value,))
    s.db.commit()
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        research.open_bundle(bundle.bundle_id)


@pytest.mark.parametrize('rollback',[False,True])
def test_bundle_publication_uses_clock_after_raw_and_rejects_rollback(rollback):
    from backend.app.intraday_research.contracts import ResearchNamespace
    from backend.app.intraday_research.datasets import DatasetBundle, DatasetChild
    s,research,existing = _small_bundle()
    snapshot_id = s.db.execute('SELECT snapshot_id FROM intraday_research_bundle_children LIMIT 1').fetchone()[0]
    child = research.snapshots.open(snapshot_id)
    request = DatasetBundle((DatasetChild(snapshot_id,child.digest,child.manifest['start_at_ns'],
        child.manifest['end_at_ns'],child.manifest['cutoff_ns'],child.known_at_ns,child.publication_id,child.publication_hash),),
        ResearchNamespace(*child.manifest['namespace']),max_disk_bytes=4*1024**3,min_free_bytes=512*1024**2)
    start = s.clock.now
    def clock_change(stage):
        if stage=='BEFORE_READ':
            s.clock.now = start+1_000_000_000
        elif stage=='BEFORE_PUBLICATION' and rollback:
            s.clock.now = start-1
        return False
    if rollback:
        with pytest.raises(ValueError,match='SNAPSHOT_NOT_PIT'):
            research.freeze_bundle(request,cancelled=clock_change)
    else:
        result = research.freeze_bundle(request,cancelled=clock_change)
        assert result.known_at_ns==s.clock.now and result.known_at_ns>start


def test_window_session_cap_uses_complete_preopen_calendar_replacement():
    from test_intraday_identity import ns

    from backend.app.intraday.calendar import CalendarService
    s = prepared()
    reader = service(s)
    s.clock.now = OPEN-10_000_000_000
    reader.register_policy()
    dates = ['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16','2026-10-19']
    calendars = CalendarService(s.archive)
    rows = [{'date':day,'open':'09:30','close':'16:00'} for day in dates]
    calendars.record(rows,start=dates[0],end=dates[-1],received_at_ns=s.clock.now)
    s.clock.now += 1_000_000_000
    calendars.record([row for row in rows if row['date']!='2026-10-14'],start=dates[0],end=dates[-1],received_at_ns=s.clock.now)
    end = ns('2026-10-19T20:00:00Z')
    s.clock.now = end+10_000_000_000
    old = reader.freeze_dataset(start_at_ns=OPEN,end_at_ns=end,cutoff_ns=s.clock.now,
                               listing_ids=[s.listing],benchmarks={})
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=end,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    assert reader.open(old.snapshot_id).report['metrics']['sessions']==5
    assert reader.open(saved.snapshot_id).manifest['window_session_count']==5


def test_intraday_window_keeps_thirty_complete_previous_sessions():
    from datetime import date, timedelta

    from backend.app.intraday.calendar import CalendarService, session_as_of
    s = prepared()
    reader = service(s)
    s.clock.now = OPEN-10_000_000_000
    reader.register_policy()
    dates,day = [],date(2026,10,12)
    while len(dates)<31:
        if day.weekday()<5:
            dates.append(day.isoformat())
        day += timedelta(days=1)
    CalendarService(s.archive).record([{'date':day,'open':'09:30','close':'16:00'} for day in dates],
        start=dates[0],end=dates[-1],received_at_ns=s.clock.now)
    current = session_as_of(s.db,dates[-1],s.clock.now,profile_id=s.store.profile.profile_id,
        data_mode='REAL',provenance='CAPTURED',replay_grade='STRICT_PIT')
    start,end = current.open_at_ns+MINUTE,current.close_at_ns
    s.clock.now = end+10_000_000_000
    saved = reader.freeze_window(start_at_ns=start,end_at_ns=end,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    assert reader.open(saved.snapshot_id).manifest['support_start_at_ns']==OPEN
