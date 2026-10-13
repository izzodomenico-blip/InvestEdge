"""Explicit finite operations; every GET reads local evidence only."""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import ValidationError

from backend.app.config import get_settings
from backend.app.database import db_session
from backend.app.intraday import handlers
from backend.app.intraday.contracts import MAX_NS
from backend.app.intraday.identity import IdentityService
from backend.app.intraday.news import NewsStore
from backend.app.lab.jobs import get_job_service
from backend.app.models.intraday import (
    BackfillIn,
    CollectorStartIn,
    IdentityApplyIn,
    IdentityPreviewIn,
    MetadataRefreshIn,
    NamespaceIn,
    ProfileRequest,
    QualityIn,
    SnapshotIn,
    StatusCheckpointIn,
)
from backend.app.models.lab import JobOut
from backend.app.models.schemas import (
    AlpacaIdentityApplyIn,
    AlpacaIdentityApplyOut,
    AlpacaIdentityPreviewIn,
    AlpacaIdentityPreviewOut,
)


def query_guard(request: Request):
    allowed = {
        '/intraday/status': {'profile_id'},
        '/intraday/snapshots/{snapshot_id}': {'profile_id', 'data_mode', 'provenance', 'replay_grade', 'input_type', 'offset', 'limit'},
        '/intraday/news': {'profile_id', 'data_mode', 'provenance', 'replay_grade', 'cutoff_ns', 'listing_id', 'revisions', 'offset', 'limit', 'start_at_ns', 'end_at_ns'},
    }.get(request.scope['route'].path, set())
    if set(request.query_params) - allowed or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise handlers.OperationError('INVALID_REQUEST')


router = APIRouter(prefix='/intraday', dependencies=[Depends(query_guard)])
ProfileQuery = Annotated[str, Query(pattern=r'^[a-f0-9]{64}$')]


def _enqueue(kind, params):
    return JobOut(**asdict(get_job_service().enqueue(kind, params)))


def _namespace(profile_id, data_mode, provenance, replay_grade):
    try:
        return NamespaceIn(profile_id=profile_id, data_mode=data_mode, provenance=provenance, replay_grade=replay_grade).model_dump()
    except ValidationError:
        raise handlers.OperationError('INVALID_REQUEST') from None


@router.get('/status')
def status(profile_id: ProfileQuery | None = None):
    settings = get_settings()
    with db_session() as connection:
        collector = handlers.collector_status(connection, profile_id)
        profiles = []
        gaps = []
        rows = connection.execute('SELECT id FROM intraday_feed_profiles ORDER BY id LIMIT 100').fetchall()
        if profile_id is not None:
            rows = [(profile_id,)]
        for row in rows:
            with handlers.services({'profile_id': row[0]}) as store:
                profiles.append({'profile_id': row[0], 'profile': store.provider.public_profile(),
                    'availability': {cap: asdict(store.provider.availability(cap)) for cap in ('bars', 'quotes', 'news', 'assets', 'calendar')}})
                for gap in store.read_capture_as_of(cutoff_ns=handlers.clock_ns()):
                    if gap['kind'] == 'GAP':
                        gaps.append({key: gap[key] for key in ('id', 'capture_id', 'profile_id', 'available_at_ns', 'publication_id')} |
                            {key: gap['payload'].get(key) for key in ('reason_code', 'start_at_ns', 'end_at_ns', 'missing_transport_channels')})
        gap_where, gap_params = (" AND profile_id=?", (profile_id,)) if profile_id is not None else ('', ())
        gaps = sorted(gaps, key=lambda gap: (gap['available_at_ns'], gap['id']), reverse=True)[:20]
        budgets = [dict(row) for row in connection.execute('''SELECT window_kind,window_start,used_count,
            configured_limit,effective_limit,cooldown_until FROM provider_usage_windows
            WHERE provider='alpaca' ORDER BY window_start DESC,window_kind LIMIT 9''')]
        latest_quality = None
        snapshots = connection.execute('''SELECT id,profile_id,data_mode,provenance,replay_grade FROM intraday_dataset_snapshots
            WHERE data_mode='REAL' ''' + gap_where + ' ORDER BY id DESC LIMIT 10', gap_params).fetchall()
        for candidate in snapshots:
            try:
                with handlers.services({key: candidate[key] for key in ('profile_id', 'data_mode', 'provenance', 'replay_grade')}) as store:
                    saved = handlers.frozen(store, candidate['id'])
                    latest_quality = {'snapshot_id': candidate['id'], 'digest': saved['digest'], 'known_at_ns': saved['known_at_ns'],
                                      'outcome': saved['report']['outcome'], 'reasons': saved['report']['reasons'],
                                      'namespace': list(store.namespace)}
                    break
            except handlers.OperationError:
                continue  # Unpublished RAW never becomes a public quality verdict.
        if profiles:
            with handlers.services({'profile_id': profiles[0]['profile_id']}) as store:
                for gap in gaps:
                    store.archive.safe_json(gap)
        return handlers.public_response({'enabled': settings.enable_real_data and settings.enable_alpaca_data,
                'collector_enabled': settings.enable_alpaca_collector, 'collector': collector,
                'profiles': profiles, 'budgets': budgets, 'capture_gaps': gaps, 'latest_quality': latest_quality,
                'g1_data': 'INSUFFICIENTE'})


@router.post('/metadata/refresh', response_model=JobOut, status_code=202)
def metadata_refresh(request: MetadataRefreshIn):
    params = request.model_dump(exclude_none=True)
    with handlers.services(params) as store:
        handlers.require_transport(store, ('assets', 'calendar'))
        from backend.app.intraday.calendar import validate_range
        validate_range(request.start_date, request.end_date)
    return _enqueue('INTRADAY_METADATA', params)


@router.post('/identity/preview', response_model=AlpacaIdentityPreviewOut)
def identity_preview(request: IdentityPreviewIn):
    params = request.model_dump()
    with handlers.services(params) as store:
        payload = AlpacaIdentityPreviewIn(**request.model_dump(exclude={'profile_id', 'listing_id'}))
        return IdentityService(store.archive).preview(request.listing_id, payload)


@router.post('/identity/apply', response_model=AlpacaIdentityApplyOut)
def identity_apply(request: IdentityApplyIn):
    params = request.model_dump()
    with handlers.services(params) as store:
        payload = AlpacaIdentityApplyIn(**request.model_dump(exclude={'profile_id', 'listing_id'}))
        return IdentityService(store.archive).apply(request.listing_id, payload)


@router.post('/status-checkpoints')
def status_checkpoint(request: StatusCheckpointIn):
    params = request.model_dump(mode='json')
    with handlers.services(params) as store:
        return handlers.public_response(handlers.import_checkpoint(store, params))


@router.post('/backfill', response_model=JobOut, status_code=202)
def backfill(request: BackfillIn):
    params = request.model_dump()
    with handlers.services(params) as store:
        handlers.precheck_backfill(store, params)
    return _enqueue('INTRADAY_BACKFILL', params)


@router.post('/snapshots', response_model=JobOut, status_code=202)
def snapshot(request: SnapshotIn):
    params = request.model_dump()
    with handlers.services(params) as store:
        handlers.precheck_snapshot(store, params)
    return _enqueue('INTRADAY_SNAPSHOT', params)


@router.get('/snapshots/{snapshot_id}')
def read_snapshot(
    snapshot_id: Annotated[int, Path(gt=0)], profile_id: ProfileQuery,
    data_mode: Literal['REAL', 'DEMO'] = 'REAL',
    provenance: Literal['CAPTURED', 'HISTORICAL_CURRENT', 'SYNTHETIC'] = 'CAPTURED',
    replay_grade: Literal['STRICT_PIT', 'RESEARCH_ONLY'] = 'STRICT_PIT',
    input_type: Literal['ALL', 'BAR', 'QUOTE', 'NEWS', 'EVENT', 'IDENTITY', 'CALENDAR', 'UNIVERSE', 'CAPTURE'] = 'ALL',
    offset: int = Query(0, ge=0, le=10000000), limit: int = Query(50, ge=1, le=200),
):
    params = _namespace(profile_id, data_mode, provenance, replay_grade)
    with handlers.services(params) as store:
        frozen = handlers.frozen(store, snapshot_id)
        page = frozen['timeline'].page(offset=offset, limit=limit, input_type=input_type)
        inputs = handlers.page(store, page.pop('items'), 0, limit)['items']
        page['next_offset'] = offset + len(inputs) if offset + len(inputs) < page['total'] else None
        return {key: value for key, value in frozen.items() if key != 'timeline'} | {
            'inputs': inputs, **page, 'input_type': input_type}


@router.post('/quality', response_model=JobOut, status_code=202)
def quality(request: QualityIn):
    params = request.model_dump()
    with handlers.services(params) as store:
        handlers.frozen(store, request.snapshot_id)
    return _enqueue('INTRADAY_QUALITY', params)


@router.get('/news')
def news(
    profile_id: ProfileQuery, cutoff_ns: int = Query(..., ge=0, le=MAX_NS),
    listing_id: int | None = Query(None, gt=0), revisions: bool = False,
    start_at_ns: int | None = Query(None, ge=0, le=MAX_NS), end_at_ns: int | None = Query(None, ge=0, le=MAX_NS),
    data_mode: Literal['REAL', 'DEMO'] = 'REAL',
    provenance: Literal['CAPTURED', 'HISTORICAL_CURRENT', 'SYNTHETIC'] = 'CAPTURED',
    replay_grade: Literal['STRICT_PIT', 'RESEARCH_ONLY'] = 'STRICT_PIT',
    offset: int = Query(0, ge=0, le=10000000), limit: int = Query(50, ge=1, le=200),
):
    params = _namespace(profile_id, data_mode, provenance, replay_grade)
    if (start_at_ns is None) != (end_at_ns is None) or start_at_ns is not None and (
        not 0 <= end_at_ns - start_at_ns <= 366 * 86400 * 10**9 or end_at_ns > cutoff_ns):
        raise handlers.OperationError('INVALID_REQUEST')
    with handlers.services(params) as store:
        reader = NewsStore(store.provider, clock_ns=lambda: handlers.clock_ns(), data_mode=data_mode,
                           provenance=provenance, replay_grade=replay_grade)
        rows = reader.read_as_of(cutoff_ns=cutoff_ns, listing_ids=None if listing_id is None else [listing_id], revisions=revisions)
        # Only the payload permitted by the frozen rights plus mapping/version references.
        items = [{key: row[key] for key in ('id', 'article_id', 'payload', 'links', 'available_at_ns', 'supersedes_id')} for row in rows]
        return {**handlers.page(store, items, offset, limit),
                'cutoff_ns': cutoff_ns, 'namespace': list(store.namespace),
                'coverage': handlers.news_coverage(store, reader, start_ns=start_at_ns, end_ns=end_at_ns,
                                                   cutoff_ns=cutoff_ns, listing_id=listing_id)}


@router.post('/collector/start')
def collector_start(request: CollectorStartIn):
    params = request.model_dump()
    settings = get_settings()
    if not settings.enable_real_data or not settings.enable_alpaca_data or not settings.enable_alpaca_collector:
        raise handlers.OperationError('REAL_DATA_DISABLED')
    with handlers.services(params) as store:
        handlers.require_transport(store, ('bars', 'quotes', 'news'))
        # Local prerequisites are checked before creating a runtime or opening sockets.
        handlers.Collector(store.provider, clock_ns=lambda: handlers.clock_ns())._precheck(
            request.listing_ids, request.benchmark_listing_ids)
    return handlers.public_response(handlers.get_collector_runtime().start(params))


@router.post('/collector/stop')
def collector_stop(request: ProfileRequest):
    with handlers.services(request.model_dump()):
        pass
    runtime = handlers._runtime
    with db_session() as connection:
        owned = connection.execute('''SELECT capture_id FROM intraday_collector_state WHERE profile_id=?
                AND data_mode='REAL' AND owner_nonce IS NOT NULL AND lease_expires_at_ns>?''',
                (request.profile_id, handlers.clock_ns())).fetchone()
        if owned is not None and (runtime is None or not runtime.owns_capture(request.profile_id, owned['capture_id'])):
            raise handlers.OperationError('COLLECTOR_ALREADY_OWNED')
        if runtime is None or runtime._key is None or runtime._key[0] != request.profile_id:
            return handlers.public_response(handlers.collector_status(connection, request.profile_id))
    return handlers.public_response(runtime.stop(request.profile_id))
