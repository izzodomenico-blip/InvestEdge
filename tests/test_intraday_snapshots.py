from __future__ import annotations

import importlib

import pytest
from test_intraday_store import MINUTE, OPEN, SECOND, event, prepared

from backend.app.data_providers.alpaca_metadata import MetadataError


def service(s):
    return importlib.import_module('backend.app.intraday.snapshots').SnapshotService(s.store)


def freeze(s, **options):
    return service(s).freeze_dataset(start_at_ns=OPEN, end_at_ns=OPEN + 3 * MINUTE,
                                     cutoff_ns=s.clock.now, listing_ids=[s.listing], benchmarks={}, **options)


def test_freeze_replays_superseded_preperiod_and_a_b_a_without_future_sources():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s, at=OPEN - MINUTE), event(s)))
    first = s.clock.now
    s.clock.now += SECOND
    s.store.persist((event(s, change={'c': 100}),))
    second = s.clock.now
    s.clock.now += SECOND
    s.store.persist((event(s),))
    saved = freeze(s)
    reader = service(s)
    baseline = reader.read(saved.snapshot_id)
    replay = reader.replay(saved.snapshot_id, cutoff_ns=first)
    assert len(replay['observations']['BAR']) == 2
    assert replay['observations']['BAR'][-1]['payload']['raw']['c'] == 101
    assert reader.replay(saved.snapshot_id, cutoff_ns=second)['observations']['BAR'][-1]['payload']['raw']['c'] == 100
    assert len([r for r in baseline['timeline'] if r.get('kind') == 'BAR']) == 4
    s.clock.now += SECOND
    s.store.persist((event(s, change={'c': 99}),))
    assert reader.read(saved.snapshot_id) == baseline
    assert freeze(s).digest != saved.digest


def test_same_inputs_cutoff_repeat_freeze_has_identical_digest_and_no_output_recursion():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    first, second = freeze(s), freeze(s)
    assert first.snapshot_id != second.snapshot_id and first.digest == second.digest
    assert service(s).read(first.snapshot_id)['timeline'] == service(s).read(second.snapshot_id)['timeline']
    assert not any(r['payload'].get('metadata_kind') == 'DATASET_PUBLICATION'
                   for r in service(s).read(second.snapshot_id)['timeline'])


def test_read_has_no_clock_or_operational_state_dependency(monkeypatch):
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    before = service(s).read(saved.snapshot_id)
    s.db.execute("UPDATE intraday_ingest_runs SET cursor_json='{}',state='FAILED'")
    s.db.commit()
    monkeypatch.setattr(s.store.archive, 'clock_ns', lambda: (_ for _ in ()).throw(AssertionError('clock')))
    reader = service(s)
    count = s.db.total_changes
    assert reader.read(saved.snapshot_id) == before
    assert reader.replay(saved.snapshot_id)['observations']['BAR']
    assert s.db.total_changes == count


def test_raw_atomic_but_cancelled_before_publication_is_not_readable():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    def cancelled(stage):
        return stage == 'BEFORE_PUBLICATION'
    with pytest.raises(MetadataError, match='CANCELLED'):
        freeze(s, cancelled=cancelled)
    row = s.db.execute('SELECT id,member_count FROM intraday_dataset_snapshots').fetchone()
    assert row and row['member_count'] == s.db.execute('SELECT COUNT(*) FROM intraday_dataset_members').fetchone()[0]
    assert s.db.execute('SELECT COUNT(*) FROM intraday_quality_reports').fetchone()[0] == 1
    with pytest.raises(MetadataError, match='SNAPSHOT_INPUT_MISSING'):
        service(s).read(row['id'])


def test_unregistered_policy_and_future_cutoff_fail_without_creating_dataset():
    s = prepared()
    with pytest.raises(MetadataError, match='POLICY_MISSING'):
        freeze(s)
    service(s).register_policy()
    with pytest.raises(MetadataError, match='SNAPSHOT_NOT_PIT'):
        service(s).freeze_dataset(start_at_ns=OPEN, end_at_ns=OPEN + MINUTE,
                                  cutoff_ns=s.clock.now + 1, listing_ids=[s.listing], benchmarks={})
    assert not s.db.execute('SELECT id FROM intraday_dataset_snapshots').fetchall()


def test_raw_source_metadata_tamper_is_detected_before_frozen_projection():
    s = prepared()
    service(s).register_policy()
    ids = s.store.persist((event(s),))
    saved = freeze(s)
    triggers = s.db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='intraday_observations'").fetchall()
    for trigger in triggers:
        s.db.execute('DROP TRIGGER "' + trigger['name'] + '"')
    s.db.execute('UPDATE intraday_observations SET received_at_ns=received_at_ns-1 WHERE id=?', ids)
    s.db.commit()
    with pytest.raises(MetadataError, match='SNAPSHOT_INPUT_MISSING'):
        service(s).read(saved.snapshot_id)


@pytest.mark.parametrize('history', [False, True])
def test_report_and_replay_keep_frozen_namespace_and_nonready_gate(history):
    s = prepared(history=history)
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    result = service(s).read(saved.snapshot_id)
    assert result['report']['outcome'] == ('NON_IDONEO' if history else 'INSUFFICIENTE')
    assert result['report']['g1_tech'] == 'NOT_EVALUATED'
    assert result['manifest']['policy']['hash']
    assert result['manifest']['profile']['config']['feed'] == 'sip'
    assert service(s).replay(saved.snapshot_id)['namespace'][-1] == s.store.replay_grade
    with pytest.raises(ValueError, match='SNAPSHOT_CUTOFF'):
        service(s).replay(saved.snapshot_id, cutoff_ns=s.clock.now + 1)


def test_clock_rollback_after_raw_cannot_return_successful_unreadable_snapshot():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    def rollback(stage):
        if stage == 'BEFORE_PUBLICATION':
            s.clock.now -= SECOND
        return False
    with pytest.raises(MetadataError, match='SNAPSHOT_NOT_PIT'):
        freeze(s, cancelled=rollback)
    assert not s.db.execute("SELECT id FROM intraday_capture_events WHERE json_extract(payload_json,'$.metadata_kind')='DATASET_PUBLICATION'").fetchall()


def test_unrelated_future_publication_corruption_cannot_break_old_snapshot():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    first = freeze(s)
    baseline = service(s).read(first.snapshot_id)
    s.clock.now += SECOND
    second = freeze(s)
    s.db.execute('DROP TRIGGER trg_intraday_capture_events_no_update')
    s.db.execute("UPDATE intraday_capture_events SET payload_hash=? WHERE json_extract(payload_json,'$.metadata_kind')='DATASET_PUBLICATION' AND json_extract(payload_json,'$.snapshot_id')=?",
                 ('0' * 64, second.snapshot_id))
    s.db.commit()
    assert service(s).read(first.snapshot_id) == baseline


def test_frozen_replay_cannot_expand_certified_listing_scope():
    s = prepared(second=True)
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    with pytest.raises(ValueError, match='SNAPSHOT_SCOPE'):
        service(s).replay(saved.snapshot_id, listing_ids=(s.second,))


def test_gap_raw_orphan_is_frozen_audit_dependency_but_never_admitted_to_replay():
    from dataclasses import replace

    from test_intraday_collector import handshake, setup
    s = setup()
    service(s).register_policy()
    s.collector.start((s.listing,))
    handshake(s)
    raw = replace(event(s, kind='QUOTE', at=s.clock.now), capture_id=s.collector.capture_id)
    ids = s.collector.store.persist((raw,), run_id=s.collector.run_id, admit=False)
    s.collector._fail('CAPTURE_GAP')
    saved = freeze(s)
    before = service(s).read(saved.snapshot_id)
    assert not service(s).replay(saved.snapshot_id)['observations']['QUOTE']
    assert before['manifest']['audit_member_count'] == 1
    s.db.execute('PRAGMA foreign_keys=OFF')
    s.db.execute('DROP TRIGGER trg_intraday_observations_no_delete')
    s.db.execute('DELETE FROM intraday_observations WHERE id=?', ids)
    s.db.commit()
    with pytest.raises(MetadataError, match='SNAPSHOT_INPUT_MISSING'):
        service(s).read(saved.snapshot_id)


def test_atomic_rollback_on_member_write_failure_and_cancel_before_raw():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    s.db.execute("CREATE TRIGGER fixture_failure BEFORE INSERT ON intraday_dataset_members BEGIN SELECT RAISE(ABORT,'fixture'); END")
    s.db.commit()
    with pytest.raises(MetadataError, match='SNAPSHOT_INPUT_MISSING'):
        freeze(s)
    assert not s.db.execute('SELECT id FROM intraday_dataset_snapshots').fetchall()
    s.db.execute('DROP TRIGGER fixture_failure')
    s.db.commit()
    with pytest.raises(MetadataError, match='CANCELLED'):
        freeze(s, cancelled=lambda stage: stage == 'BEFORE_RAW')
    assert not s.db.execute('SELECT id FROM intraday_dataset_snapshots').fetchall()


@pytest.mark.parametrize('table', ['intraday_observations', 'intraday_capture_events', 'intraday_feed_profiles',
                                  'intraday_quality_policies'])
def test_missing_exact_input_never_falls_back_to_latest(table):
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    s.db.execute('PRAGMA foreign_keys=OFF')
    triggers = s.db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall()
    for trigger in triggers:
        s.db.execute('DROP TRIGGER "' + trigger['name'] + '"')
    s.db.execute(f'DELETE FROM {table}')
    s.db.commit()
    with pytest.raises(MetadataError, match='SNAPSHOT_INPUT_MISSING'):
        service(s).read(saved.snapshot_id)


def test_news_and_event_revisions_are_in_digest_and_frozen_links_do_not_grow():
    from test_intraday_news import article
    from test_official_event_calendar import artifact

    from backend.app.intraday.events import EventStore
    from backend.app.intraday.news import NewsStore
    s = prepared()
    news, events = NewsStore(s.archive.provider, clock_ns=lambda: s.clock.now), EventStore(s.archive.provider, clock_ns=lambda: s.clock.now)
    service(s).register_policy()
    news.persist([article()], received_at_ns=s.clock.now)
    events.import_calendar(artifact(), received_at_ns=s.clock.now)
    saved = freeze(s)
    baseline = service(s).read(saved.snapshot_id)
    assert service(s).replay(saved.snapshot_id)['news'][0]['links']
    s.clock.now += SECOND
    news.persist([article(headline='Revised results', updated_at='2026-10-12T12:00:05Z')], received_at_ns=s.clock.now)
    news_saved = freeze(s)
    assert news_saved.digest != saved.digest
    assert service(s).read(saved.snapshot_id) == baseline
    assert len(service(s).replay(saved.snapshot_id)['news']) == 1
    s.clock.now += SECOND
    events.import_calendar(artifact(day='2026-10-13'), received_at_ns=s.clock.now)
    event_saved = freeze(s)
    assert event_saved.digest != news_saved.digest
    assert service(s).read(saved.snapshot_id) == baseline


def test_universe_member_dependency_and_preopen_requested_exclusion_are_frozen():
    s = prepared(second=True)
    service(s).register_policy()
    s.clock.now = OPEN - 10 * SECOND
    universe = s.universe.freeze([s.listing, s.second], '2026-10-12', s.clock.now)
    s.clock.now = OPEN + 30 * MINUTE
    saved = freeze(s)
    reader = service(s)
    before = reader.read(saved.snapshot_id)
    assert before['manifest']['listing_ids'] == sorted([s.listing, s.second])
    assert any(row['table'] == 'intraday_universe_members' for row in before['timeline'])
    s.db.execute('PRAGMA foreign_keys=OFF')
    s.db.execute('DROP TRIGGER trg_intraday_universe_members_no_delete')
    s.db.execute('DELETE FROM intraday_universe_members WHERE snapshot_id=?', (universe.snapshot_id,))
    s.db.commit()
    with pytest.raises(MetadataError, match='SNAPSHOT_INPUT_MISSING'):
        reader.read(saved.snapshot_id)


@pytest.mark.parametrize('limit', ['archive', 'frame'])
def test_budget_failure_never_leaves_partial_dataset(limit):
    from dataclasses import replace
    s = prepared()
    service(s).register_policy()
    if limit == 'archive':
        config = replace(s.config, alpaca_max_archive_bytes=s.store.archive._archive_bytes() + 1)
    else:
        config = replace(s.config, alpaca_max_frame_bytes=64)
    s.store.archive.settings = config
    with pytest.raises(MetadataError, match='ARCHIVE_LIMIT|FRAME_LIMIT'):
        freeze(s)
    assert not s.db.execute('SELECT id FROM intraday_dataset_snapshots').fetchall()


def test_source_identifiers_are_sanitized_before_hashing_the_manifest():
    from dataclasses import replace
    s = prepared()
    service(s).register_policy()
    s.store.persist((replace(event(s), logical_key=s.config.alpaca_api_secret_key),))
    with pytest.raises(MetadataError, match='METADATA_INVALID'):
        freeze(s)


def test_clock_rollback_before_raw_cannot_retrodate_saved_evidence():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    def rollback(stage):
        if stage == 'BEFORE_RAW':
            s.clock.now = OPEN + SECOND
        return False
    with pytest.raises(MetadataError, match='SNAPSHOT_NOT_PIT'):
        freeze(s, cancelled=rollback)
    assert not s.db.execute('SELECT id FROM intraday_dataset_snapshots').fetchall()


def test_changed_sensitive_inventory_rechecks_source_body_before_freeze_and_read():
    import uuid
    from dataclasses import replace

    from test_intraday_news import article

    from backend.app.intraday.news import NewsStore
    s = prepared()
    service(s).register_policy()
    marker = uuid.uuid4().hex
    news = NewsStore(s.archive.provider, clock_ns=lambda: s.clock.now)
    news.persist([article(headline=marker)], received_at_ns=s.clock.now)
    saved = freeze(s)
    settings = replace(s.config, alpaca_api_key_id=marker)
    s.store.archive.settings = s.archive.provider.settings = settings
    with pytest.raises(MetadataError, match='METADATA_INVALID'):
        freeze(s)
    with pytest.raises(MetadataError, match='SNAPSHOT_INPUT_MISSING'):
        service(s).read(saved.snapshot_id)
