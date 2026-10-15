"""Decision-time common filters. No future holding continuity or G1 promotion."""
from __future__ import annotations

from backend.app.intraday.aggregate import MINUTE_NS, _crosses_action
from backend.app.intraday.contracts import QualityPolicy
from backend.app.intraday.quality import _calendars_available, _eligibility
from backend.app.intraday_research.context import sealed
from backend.app.intraday_research.contracts import ResearchError, integer
from backend.app.intraday_research.features import compute_features


def evaluate_entry(context, *, quote_units, references=None, holding_minutes, entry_timeout_ns=30_000_000_000,
                   latency_ns=500_000_000):
    if type(holding_minutes) is not int or holding_minutes not in (15,30):
        raise ResearchError('INVALID_CONTRACT')
    integer(entry_timeout_ns,positive=True)
    integer(latency_ns)
    if entry_timeout_ns!=30_000_000_000 or latency_ns not in {500_000_000,2_000_000_000}:
        raise ResearchError('INVALID_CONTRACT')
    if quote_units.namespace!=context.namespace:
        raise ResearchError('NAMESPACE_MISMATCH')
    c,index,at = context.current,context.index,context.cutoff_ns
    reasons = set()
    if at<c['open_at_ns']+45*MINUTE_NS:
        reasons.add('BEFORE_ENTRY_WINDOW')
    deadline = at+entry_timeout_ns+latency_ns+(holding_minutes+3)*MINUTE_NS
    if deadline>=c['close_at_ns']:
        reasons.add('AFTER_ENTRY_WINDOW')
    for listing in {context.listing_id,*context.benchmarks.values()}:
        reason = _eligibility(index,c,listing,c['known_at_ns']<=at)
        if reason:
            reasons.add(reason)
        reason = index.continuity(listing,c['open_at_ns'],min(at,c['close_at_ns']),at)
        if reason:
            reasons.add(reason)
    capture = index.context(at)
    if capture.get('news_coverage') not in {'COVERED','COVERED_ZERO'}:
        reasons.add('NEWS_COVERAGE_UNKNOWN')
    if not _calendars_available(index,context.listing_id,c['open_at_ns']):
        reasons.add('EVENT_CALENDAR_UNKNOWN')
    for event in context.events:
        if event['listing_id'] not in (None,context.listing_id) or event['payload'].get('cancelled'):
            continue
        if event['event_type']=='CORPORATE_ACTION' and _crosses_action(event,c['open_at_ns'],min(at+1,c['close_at_ns'])):
            reasons.add('CORPORATE_ACTION_WINDOW')
        if event['event_type'] not in {'MACRO','EARNINGS'}:
            continue
        stamp = event['scheduled_at_ns']
        if (stamp is None and event['payload'].get('event_date')==context.session_date or
            stamp is not None and (stamp-15*MINUTE_NS<=at<=stamp+15*MINUTE_NS or at<stamp<=deadline)):
            reasons.add('EVENT_WINDOW')
    features = compute_features(context)
    bars = context.bars()
    last = bars[-1] if bars and bars[-1]['session_date']==context.session_date else None
    if last is None or at-last['end_at_ns']>10_000_000_000 or last['available_at_ns']-last['end_at_ns']>10_000_000_000:
        reasons.add('BAR_DELAY')
    if last is None or not 5<=last['close']<=500:
        reasons.add('PRICE_FILTER')
    daily = features['daily']
    if daily['median_dollar_volume20'] is None or daily['median_dollar_volume20']<20_000_000:
        reasons.add('LIQUIDITY_FILTER')
    if daily['gap'] is None or abs(daily['gap'])>.08:
        reasons.add('DAILY_GAP_FILTER')
    atr = features['atr14_1m_fraction']
    if atr is None or not .0005<=atr<=.01:
        reasons.add('VOLATILITY_FILTER')
    if daily['reason_code']:
        reasons.add(daily['reason_code'])
    quote = index.quote(context.listing_id,at,QualityPolicy())
    converted = None
    if quote is None:
        reasons.add('QUOTE_MISSING')
    else:
        if not quote['executable']:
            reasons.add('QUOTE_INVALID')
        converted = quote_units.quote(quote,cutoff_ns=at,references=references)
        if not converted['size_conversion_attested'] or min(converted['bid_shares'],converted['ask_shares'])<=0:
            reasons.add(converted['reason_code'] or 'SIZE_UNIT_UNKNOWN')
        raw = quote['payload']['raw']
        mid = (raw['ap']+raw['bp'])/2
        if mid<=0 or raw['ap']<raw['bp'] or (raw['ap']-raw['bp'])/mid>.001:
            reasons.add('SPREAD_FILTER')
    real = context.namespace.key[1:]==('sip','REAL','CAPTURED','STRICT_PIT')
    return sealed({'version':'intraday-entry-eligibility-v1','input_hash':context.input_hash,'cutoff_ns':at,
        'holding_minutes':holding_minutes,'entry_timeout_ns':entry_timeout_ns,'latency_ns':latency_ns,
        'technical_eligible':not reasons,'economic_status':'NOT_EVALUATED' if real else 'NON_IDONEO',
        'g1_data':'NOT_EVALUATED','portfolio_evaluated':False,
        'news_coverage':('COVERED_ZERO' if capture.get('news_coverage')=='COVERED' and not index.family['NEWS'] else capture.get('news_coverage','UNKNOWN')),
        'reasons':sorted(reasons),'features_hash':features['fingerprint'],'quote_conversion':converted,
        'event_calendar_basis':'ANNOUNCED_EVENTS_ONLY','operational_basis':'DURABLE_EVIDENCE_ONLY'})
