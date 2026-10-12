from __future__ import annotations

import copy
import hashlib
import re
import sqlite3

import pytest

from backend.app import database
from backend.app.lab import jobs

KINDS = ('INTRADAY_METADATA', 'INTRADAY_BACKFILL', 'INTRADAY_SNAPSHOT', 'INTRADAY_QUALITY')


def legacy_db():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    schema = database.BASE_SCHEMA.split('CREATE TABLE IF NOT EXISTS lab_jobs (', 1)[1].split(');', 1)[0]
    for kind in KINDS:
        schema = re.sub(r",\s*'" + kind + "'", '', schema)
    db.execute('CREATE TABLE lab_jobs (' + schema + ');')
    return db


def insert_job(db, kind='BACKTEST', status='QUEUED', ident=None):
    db.execute('''INSERT INTO lab_jobs(id,kind,status,params_json,params_hash,created_at,result_json)
        VALUES(?,?,?,'{}',?,'2026-10-12','{"saved":true}')''',
        (ident, kind, status, hashlib.sha256((kind + status + str(ident)).encode()).hexdigest()))
    db.commit()


@pytest.mark.parametrize('kind', KINDS)
def test_new_kinds_are_registered_and_accepted_by_migrated_check(kind):
    db = legacy_db()
    database._migrate_intraday_job_kinds(db)
    insert_job(db, kind)
    assert kind in jobs.JOB_KINDS
    db.close()


@pytest.mark.parametrize('foreign_keys', (0, 1))
@pytest.mark.parametrize('legacy_alter', (0, 1))
def test_migration_preserves_history_custom_dependencies_and_sequence(foreign_keys, legacy_alter):
    db = legacy_db()
    ident = 0
    for kind in ('BACKTEST', 'COMPARE', 'WALK_FORWARD', 'EVIDENCE', 'FEATURE_REFRESH', 'FX_BACKFILL', 'ML_TRAIN'):
        for state in ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'INTERRUPTED'):
            ident += 1
            insert_job(db, kind=kind, status=state, ident=ident)
    db.execute("UPDATE lab_jobs SET progress=.4,result_ref='saved',error_code='FIXTURE',error_message='Fixed',cancel_requested=1,started_at='start',finished_at='finish'")
    db.commit()
    insert_job(db, status='SUCCEEDED', ident=100)
    db.execute('DELETE FROM lab_jobs WHERE id=100')
    db.executescript('''
        ALTER TABLE lab_jobs ADD COLUMN custom TEXT DEFAULT 'kept';
        CREATE TABLE child(id INTEGER PRIMARY KEY, job_id INTEGER REFERENCES lab_jobs(id) ON DELETE CASCADE);
        INSERT INTO child VALUES(1,1);
        CREATE TABLE audit(id INTEGER);
        CREATE INDEX custom_jobs ON lab_jobs(created_at);
        CREATE UNIQUE INDEX dedup_jobs ON lab_jobs(kind,params_hash) WHERE status IN ('QUEUED','RUNNING');
        CREATE VIEW saved_jobs AS SELECT * FROM lab_jobs;
        CREATE TRIGGER jobs_audit AFTER UPDATE ON lab_jobs BEGIN INSERT INTO audit VALUES(NEW.id); END;
        CREATE TRIGGER external_audit AFTER INSERT ON child BEGIN INSERT INTO audit SELECT id FROM lab_jobs; END;
    ''')
    before = [tuple(row) for row in db.execute('SELECT * FROM lab_jobs ORDER BY id')]
    dependencies = list(db.execute("SELECT name,sql FROM sqlite_master WHERE type IN ('index','view','trigger') AND sql IS NOT NULL"))
    db.execute(f'PRAGMA foreign_keys={foreign_keys}')
    db.execute(f'PRAGMA legacy_alter_table={legacy_alter}')
    database._migrate_intraday_job_kinds(db)
    assert [tuple(row) for row in db.execute('SELECT * FROM lab_jobs ORDER BY id')] == before
    assert [tuple(row) for row in db.execute('SELECT * FROM saved_jobs')] == before
    for name, sql in dependencies:
        assert db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0] == sql
    insert_job(db, KINDS[0])
    assert db.execute('SELECT MAX(id) FROM lab_jobs').fetchone()[0] == 101
    db.execute('UPDATE lab_jobs SET progress=.5 WHERE id=1')
    assert db.execute('SELECT id FROM audit').fetchone()[0] == 1
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    db.execute('DELETE FROM lab_jobs WHERE id=1')
    if foreign_keys:
        assert not db.execute('SELECT * FROM child').fetchall()
    else:
        db.execute('DELETE FROM child')
    db.commit()
    database._migrate_intraday_job_kinds(db)
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == foreign_keys
    assert db.execute('PRAGMA legacy_alter_table').fetchone()[0] == legacy_alter
    db.close()


def job_system(lab_connection, monkeypatch, s):
    from backend.app.intraday import handlers
    s.db.backup(lab_connection)
    def make(connection, profile):
        provider = copy.copy(s.archive.provider)
        provider.connection, provider.profile = connection, profile
        return provider
    monkeypatch.setattr(handlers, 'make_provider', make)
    monkeypatch.setattr(handlers, 'clock_ns', lambda: s.clock.now)
    monkeypatch.setattr(handlers, 'get_settings', lambda: s.config)
    return s


def test_cancel_after_raw_before_snapshot_publication_has_no_readable_result(lab_connection, monkeypatch):
    from test_intraday_store import MINUTE, OPEN, event, prepared

    from backend.app.intraday import handlers
    from backend.app.intraday.snapshots import SnapshotService
    s = prepared()
    SnapshotService(s.store).register_policy()
    s.store.persist((event(s),))
    job_system(lab_connection, monkeypatch, s)
    actual = SnapshotService.freeze_dataset
    def cancel_before_publication(self, **kwargs):
        callback = kwargs['cancelled']
        def cancel(stage):
            if stage == 'BEFORE_PUBLICATION':
                self.connection.execute("UPDATE lab_jobs SET cancel_requested=1 WHERE status='RUNNING'")
                self.connection.commit()
            return callback(stage)
        kwargs['cancelled'] = cancel
        return actual(self, **kwargs)
    monkeypatch.setattr(SnapshotService, 'freeze_dataset', cancel_before_publication)
    params = {'profile_id': s.profile.profile_id, 'listing_ids': [s.listing], 'start_at_ns': OPEN,
              'end_at_ns': OPEN + MINUTE, 'cutoff_ns': s.clock.now, 'benchmarks': {}}
    result = jobs.JobService('inline').enqueue('INTRADAY_SNAPSHOT', params)
    assert result.status == 'CANCELLED' and result.result_ref is None and result.result is None
    ident = lab_connection.execute('SELECT id FROM intraday_dataset_snapshots').fetchone()[0]
    with pytest.raises(handlers.OperationError, match='SNAPSHOT_INPUT_MISSING'), handlers.services(params) as store:
        handlers.frozen(store, ident)
    s.db.close()


@pytest.mark.parametrize('reason,state', [('PAGE_LIMIT', 'FAILED'), ('CANCELLED', 'CANCELLED')])
def test_partial_backfill_is_never_succeeded(lab_connection, monkeypatch, reason, state):
    from test_intraday_store import MINUTE, OPEN, prepared

    from backend.app.intraday.store import IntradayStore
    s = job_system(lab_connection, monkeypatch, prepared())
    monkeypatch.setattr(IntradayStore, 'backfill', lambda *a, **k: {'state': 'PARTIAL', 'reason_code': reason, 'pages': 1})
    params = {'profile_id': s.profile.profile_id, 'listing_ids': [s.listing], 'start_at_ns': OPEN, 'end_at_ns': OPEN + MINUTE,
              'data_mode': 'REAL', 'provenance': 'HISTORICAL_CURRENT', 'replay_grade': 'RESEARCH_ONLY',
              'types': ['BAR'], 'asof_date': '2026-10-12', 'chunk_days': 7, 'max_pages': 10}
    result = jobs.JobService('inline').enqueue('INTRADAY_BACKFILL', params)
    assert result.status == state and result.result is None
    if state == 'FAILED':
        assert result.error_code == reason
    s.db.close()


def test_job_rechecks_disabled_configuration_before_any_http(lab_connection, monkeypatch):
    from dataclasses import replace

    from test_intraday_identity import system
    s = system()
    s.config = replace(s.config, enable_real_data=False)
    s.archive.provider.settings = s.config
    job_system(lab_connection, monkeypatch, s)
    params = {'profile_id': s.profile.profile_id, 'profile': __import__('json').loads(s.profile.config_json),
              'start_date': '2026-10-12', 'end_date': '2026-10-12'}
    result = jobs.JobService('inline').enqueue('INTRADAY_METADATA', params)
    assert result.status == 'FAILED' and result.error_code == 'REAL_DATA_DISABLED'
    assert not s.requests
    s.db.close()


def test_migration_refuses_open_transaction_without_committing_it():
    db = legacy_db()
    db.execute("INSERT INTO lab_jobs(kind,status,params_json,params_hash,created_at) VALUES('BACKTEST','QUEUED','{}',?,'fixture')", ('a' * 64,))
    with pytest.raises(sqlite3.OperationalError, match='REQUIRES_AUTOCOMMIT'):
        database._migrate_intraday_job_kinds(db)
    assert db.in_transaction
    db.rollback()
    assert db.execute('SELECT COUNT(*) FROM lab_jobs').fetchone()[0] == 0
    db.close()


def test_migration_rejects_unknown_check_without_ddl():
    db = sqlite3.connect(':memory:')
    db.execute("CREATE TABLE lab_jobs(id INTEGER PRIMARY KEY,kind TEXT CHECK(kind IN ('UNKNOWN')))")
    before = db.execute("SELECT sql FROM sqlite_master WHERE name='lab_jobs'").fetchone()[0]
    with pytest.raises(sqlite3.OperationalError, match='SCHEMA_UNSUPPORTED'):
        database._migrate_intraday_job_kinds(db)
    assert db.execute("SELECT sql FROM sqlite_master WHERE name='lab_jobs'").fetchone()[0] == before
    assert not db.in_transaction
    db.close()


def test_migration_failure_rolls_back_and_restores_pragmas():
    db = legacy_db()
    insert_job(db)
    before = db.execute("SELECT sql FROM sqlite_master WHERE name='lab_jobs'").fetchone()[0]
    db.set_authorizer(lambda action, _a, _b, _c, _d: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_DROP_TABLE else sqlite3.SQLITE_OK)
    with pytest.raises(sqlite3.DatabaseError):
        database._migrate_intraday_job_kinds(db)
    db.set_authorizer(None)
    assert db.execute("SELECT sql FROM sqlite_master WHERE name='lab_jobs'").fetchone()[0] == before
    assert db.execute('SELECT COUNT(*) FROM lab_jobs').fetchone()[0] == 1
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert not db.in_transaction
    db.close()
