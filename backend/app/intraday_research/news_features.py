"""Local primary-source facts with exact article bindings; no fetching or sentiment.

issuer-facts-v1 is an explicit local structured-original contract, not a claim
that all issuer publications use JSON. Unsupported prose remains UNKNOWN.
Independent trust-root authentication is the configuring party's responsibility.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from decimal import ROUND_FLOOR, Context, Decimal, DecimalException, localcontext

from backend.app.intraday.contracts import canonical_json
from backend.app.intraday.replay import select_versions, visible_rows
from backend.app.intraday_research.contracts import (
    AttestationRef,
    ResearchError,
    canonical_hash,
    digest,
    integer,
    parse_object,
)

MINUTE = 60_000_000_000
_UNCERTAIN = re.compile(r'\b(?:not|no|never|denies|denied|rumou?r(?:s|ed)?|may|might|could|would|potential|unconfirmed|reportedly|plans?|planned|planning|will|hypothetical|propos(?:e[sd]?|al)|alleged|expected|considering)\b',re.I)


def article_text(payload):
    """Only text already retained under the archive's explicit rights."""
    if payload.get('version')!='alpaca-news-row-v1':
        raise ResearchError('ATTESTATION_INVALID')
    rights = payload.get('rights',{})
    texts = [payload.get('headline') or '']
    for field in ('summary','content'):
        value = payload.get(field)
        if value:
            if (rights.get(f'allow_{field}') is not True or rights.get('retention')!='ARCHIVE_ALLOWED'):
                raise ResearchError('ATTESTATION_INVALID')
            digest(rights.get('evidence_hash'))
            texts.append(value)
    if any(type(t) is not str or len(t.encode())>262144 for t in texts):
        raise ResearchError('ATTESTATION_INVALID')
    return '\n'.join(texts)


def validate_news_attestation(document,evidence,authority):
    try:
        if type(document) is not dict or type(evidence) is not dict:
            raise ResearchError('ATTESTATION_INVALID')
        contract = parse_object(authority.contract_json)
        if (contract.get('version')!='news-primary-contract-v1' or
            set(evidence)!={'version','publisher','namespace','contract_hash','original_json','bindings'} or
            evidence['version']!='news-primary-publication-v1' or evidence['publisher']!=authority.publisher or
            evidence['namespace']!=asdict(authority.namespace) or evidence['contract_hash']!=canonical_hash(contract) or
            canonical_hash(evidence)!=authority.evidence_hash or type(evidence['bindings']) is not list or
            not 1<=len(evidence['bindings'])<=100 or sum(v==document for v in evidence['bindings'])!=1):
            raise ResearchError('AUTHORITY_UNVERIFIED')
        required = {'version','listing_id','issuer_id','article_version_id','article_id','article_hash','fact_id',
                    'previous_ref','origin_ref','valid_from_ns','valid_to_ns','known_at_ns','first_received_at_ns'}
        if set(document)!=required or document['version']!='news-source-attestation-v1':
            raise ResearchError('ATTESTATION_INVALID')
        for key in ('listing_id','article_version_id'):
            integer(document[key],positive=True)
        for key in ('valid_from_ns','known_at_ns','first_received_at_ns'):
            integer(document[key])
        if document['valid_to_ns'] is not None:
            integer(document['valid_to_ns'])
            if document['valid_to_ns']<=document['valid_from_ns']:
                raise ResearchError('ATTESTATION_INVALID')
        if (document['known_at_ns']>document['first_received_at_ns'] or document['issuer_id']!=contract['issuer_id'] or
            document['listing_id'] not in contract['listing_ids']):
            raise ResearchError('ATTESTATION_INVALID')
        for key in ('article_id','article_hash'):
            digest(document[key])
        for key in ('previous_ref','origin_ref'):
            if document[key] is not None and AttestationRef(**document[key]).kind!='NEWS_SOURCE':
                raise ResearchError('ATTESTATION_INVALID')
        if type(evidence['original_json']) is not str or len(evidence['original_json'].encode())>65536:
            raise ResearchError('RESOURCE_LIMIT')
        original = parse_object(evidence['original_json'])
        if (canonical_json(original)!=evidence['original_json'] or set(original)!={'version','issuer_id','published_at_ns','facts'} or
            original['version']!='issuer-facts-v1' or original['issuer_id']!=document['issuer_id'] or
            type(original['facts']) is not list or not 1<=len(original['facts'])<=100):
            raise ResearchError('ATTESTATION_INVALID')
        integer(original['published_at_ns'])
        if original['published_at_ns']>document['known_at_ns']:
            raise ResearchError('ATTESTATION_INVALID')
        found = [f for f in original['facts'] if type(f) is dict and f.get('event_id')==document['fact_id']]
        if len(found)!=1:
            raise ResearchError('ATTESTATION_INVALID')
        fact = found[0]
        if (type(fact.get('listing_id')) is not int or fact.get('issuer_id')!=document['issuer_id'] or fact.get('listing_id')!=document['listing_id'] or
            type(fact.get('event_id')) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,128}',fact['event_id']) is None or
            type(fact.get('statement')) is not str or not fact['statement'] or len(fact['statement'].encode())>8192 or
            fact.get('kind') not in {'GUIDANCE','M_AND_A','ADVERSE'} or fact.get('status') not in {'CONFIRMED','UNCERTAIN','RETRACTED'}):
            raise ResearchError('ATTESTATION_INVALID')
        return {'version':'verified-local-news-source-v1','kind':'NEWS_SOURCE','document':parse_object(canonical_json(document)),
            'fact':parse_object(canonical_json(fact)),'evidence':parse_object(canonical_json(evidence)),
            'contract':contract,'authority_hash':authority.authority_hash,'source_hash':authority.evidence_hash}
    except ResearchError:
        raise
    except (ValueError,KeyError,TypeError,OverflowError,RecursionError):
        raise ResearchError('ATTESTATION_INVALID') from None


def _number(value):
    if type(value) is not str or len(value)>64:
        raise ValueError
    number = Decimal(value)
    if not number.is_finite() or number.copy_abs()>Decimal('1e18') or number.as_tuple().exponent < -18:
        raise ValueError
    return number


def _guidance(row,registry,namespace):
    fact,doc = row['payload']['fact'],row['payload']['document']
    if doc['previous_ref'] is None:
        return False
    prior = registry.read_attestation(AttestationRef(**doc['previous_ref']),namespace=namespace)
    old = prior['payload']['fact']
    required = {'kind','event_id','issuer_id','listing_id','status','statement','period','units','metrics'}
    if (set(fact)!=required or set(old)!=required or old['kind']!='GUIDANCE' or old['status']!='CONFIRMED' or
        _UNCERTAIN.search(old['statement']) or any(fact[k]!=old[k] for k in ('issuer_id','listing_id','period','units')) or
        prior['available_at_ns']>row['payload']['article_available_at_ns'] or
        type(fact['period']) is not str or re.fullmatch(r'FY\d{4}(?:Q[1-4])?',fact['period']) is None or
        type(fact['metrics']) is not dict or not fact['metrics'] or set(fact['metrics'])!=set(old['metrics']) or
        not set(fact['metrics'])<={'revenue','eps'} or set(fact['units'])!=set(fact['metrics'])):
        return False
    increased = False
    for metric,current in fact['metrics'].items():
        unit = fact['units'][metric]
        if unit not in ({'USD','USD_MILLION','USD_BILLION'} if metric=='revenue' else {'USD_PER_SHARE'}):
            return False
        previous = old['metrics'][metric]
        if set(current)!= {'low','high'} or set(previous)!= {'low','high'}:
            return False
        lo,hi,oldlo,oldhi = (_number(v) for v in (current['low'],current['high'],previous['low'],previous['high']))
        if lo>hi or oldlo>oldhi or lo<oldlo or hi<oldhi:
            return False
        increased |= lo>oldlo or hi>oldhi
    return increased


def _cash_deal(fact,close,listing,cutoff):
    required = {'kind','event_id','issuer_id','listing_id','status','statement','deal_id','terms_version',
        'target_listing_id','acquirer_listing_id','share_class','currency','unit','consideration','binding','offer_price'}
    if (set(fact)!=required or any(type(fact[k]) is not int or fact[k]<=0 for k in
        ('listing_id','target_listing_id','acquirer_listing_id')) or
        fact['target_listing_id']!=listing or fact['listing_id']!=listing or fact['acquirer_listing_id']==listing or
        type(fact['share_class']) is not str or not fact['share_class'] or len(fact['share_class'])>64 or
        fact['consideration']!='CASH' or fact['binding'] is not True or close is None or
        close.get('listing_id')!=listing or close.get('currency')!='USD' or close.get('unit')!='USD_PER_SHARE' or
        fact['currency']!=close['currency'] or fact['unit']!=close['unit'] or fact['share_class']!=close.get('share_class') or
        not fact['deal_id'] or not fact['terms_version'] or close.get('available_at_ns',cutoff+1)>cutoff):
        return False
    digest(close.get('source_digest'))
    price,offer = _number(close['price']),_number(fact['offer_price'])
    with localcontext(Context(prec=80,rounding=ROUND_FLOOR,Emin=-999,Emax=999,traps=[])):
        return price>0 and offer>=price*Decimal('1.05')


def _origin(row,registry,namespace):
    visited = set()
    while row['payload']['document']['origin_ref'] is not None:
        if row['id'] in visited or len(visited)>=1_000:
            raise ResearchError('RESOURCE_LIMIT')
        visited.add(row['id'])
        row = registry.read_attestation(AttestationRef(**row['payload']['document']['origin_ref']),namespace=namespace)
    return max(row['available_at_ns'],row['payload']['article_available_at_ns'])


def news_as_of(rows,*,registry,namespace,listing_id,cutoff_ns,references=None,prior_close=None,coverage='UNKNOWN'):
    registry._namespace(namespace)
    integer(listing_id,positive=True)
    integer(cutoff_ns)
    if coverage not in {'COVERED','COVERED_ZERO','UNKNOWN','STALE','DISABLED','MISSING'}:
        raise ResearchError('INVALID_CONTRACT')
    all_rows,charge = [],0
    for row in rows:
        if row.get('available_at_ns') is None or row['available_at_ns']>cutoff_ns or row.get('table')!='intraday_news_versions':
            continue
        registry._guard(row)
        charge += len(canonical_json(row).encode())*16
        if charge>67_108_864 or len(all_rows)>=10_000:
            raise ResearchError('RESOURCE_LIMIT')
        all_rows.extend(visible_rows([row],cutoff_ns=cutoff_ns,namespace=namespace.key))
    proofs = registry.attestations_as_of(namespace=namespace,listing_id=listing_id,cutoff_ns=cutoff_ns,
        references=references,kinds=('NEWS_SOURCE',))
    positive,negative,unknown,expired,pending = {},{},{},{},{}
    for article in select_versions(all_rows,family='NEWS',cutoff_ns=cutoff_ns):
        # Resolve the newest mapping before checking its validity. An invalid
        # revision must not resurrect an older resolved link for the same symbol.
        latest_links = {}
        for link in article.get('links',[]):
            if link.get('available_at_ns',article['available_at_ns'])>cutoff_ns:
                continue
            subject = link.get('payload',{}).get('symbol',link.get('listing_id'))
            rank = link.get('available_at_ns',article['available_at_ns']),link['id']
            if subject not in latest_links or rank>latest_links[subject][0]:
                latest_links[subject] = rank,link
        links = [v for _,v in latest_links.values() if v.get('listing_id')==listing_id and
            v.get('payload',{}).get('reason_code') is None and v.get('payload',{}).get('identity') is not None]
        link = max(links,key=lambda v:(v.get('available_at_ns',article['available_at_ns']),v['id'])) if links else None
        matches = [r for r in proofs if r['payload']['document']['article_version_id']==article['id'] and
            r['payload']['document']['article_id']==article['article_id'] and
            r['payload']['document']['article_hash']==article['payload_hash'] and r['valid_from_ns']<=article['updated_at_ns']]
        if not matches and link is not None:
            unknown[article['id']] = {'article_version_id':article['id'],'reason_code':'SOURCE_UNATTESTED'}
        # Choose the latest attestation, then the latest event revision, before
        # applying validity, status or TTL; retractions cannot leave old positives.
        revisions = {}
        for row in matches:
            fact = row['payload']['fact']
            key = fact['issuer_id'],fact['event_id']
            rank = row['valid_from_ns'],row['available_at_ns'],row['id']
            if key not in revisions or rank>revisions[key][0]:
                revisions[key] = rank,row
        for key,(_,row) in revisions.items():
            available = max(row['available_at_ns'],article['available_at_ns'],
                link.get('available_at_ns',article['available_at_ns']) if link else article['available_at_ns'])
            rank = article['updated_at_ns'],available,row['id'],article['id']
            if key not in pending or rank>pending[key][0]:
                pending[key] = rank,row,article,link,available
    for key,(_,row,article,link,available) in pending.items():
        body,fact = row['payload'],row['payload']['fact']
        if link is None or row['valid_to_ns'] is not None and article['updated_at_ns']>=row['valid_to_ns']:
            unknown[article['id']] = {'article_version_id':article['id'],'reason_code':'FACT_UNKNOWN'}
            continue
        first = _origin(row,registry,namespace)
        age = cutoff_ns-first
        item = {'event_id':fact['event_id'],'cluster_id':link['cluster_id'],'kind':fact['kind'],
            'issuer_id':fact['issuer_id'],'listing_id':listing_id,'available_at_ns':available,'first_available_at_ns':first,
            'age_minutes':age/MINUTE,'decay':2**(-age/(30*MINUTE)),
            'novel':body['document']['origin_ref'] is None,'reliability':'PRIMARY_BOUND',
            'attestation':row['reference'],'article_ref':{'id':article['id'],'hash':article['payload_hash']},
            'mapping_ref':{'id':link['id'],'hash':link['payload_hash']},'fact_hash':canonical_hash(fact)}
        if age<0:
            raise ResearchError('REGISTRY_INTEGRITY')
        if fact['status']=='UNCERTAIN' or fact['kind']=='ADVERSE' and fact.get('category') in {'FINANCING_DILUTION','SEC_FILING','REGULATORY'}:
            if fact['status']!='RETRACTED' and age<=30*MINUTE:
                negative[key] = item
            continue
        valid = fact['status']=='CONFIRMED' and not _UNCERTAIN.search(fact['statement'])
        try:
            valid = valid and (_guidance(row,registry,namespace) if fact['kind']=='GUIDANCE' else
                _cash_deal(fact,prior_close,listing_id,min(cutoff_ns,first)) if fact['kind']=='M_AND_A' else False)
        except (ValueError,KeyError,TypeError,DecimalException):
            valid = False
        if not valid:
            unknown[article['id']] = {'article_version_id':article['id'],'reason_code':'FACT_UNKNOWN'}
        elif age>60*MINUTE:
            expired[key] = item
        else:
            positive[key] = item
    result = {'version':'intraday-news-context-v1','namespace':asdict(namespace),'listing_id':listing_id,'cutoff_ns':cutoff_ns,
        'coverage':coverage,'positive':[positive[k] for k in sorted(positive)],'negative':[negative[k] for k in sorted(negative)],
        'unknown':[unknown[k] for k in sorted(unknown)],'expired':[expired[k] for k in sorted(expired)],
        'g2':'NOT_EVALUATED','rule_version':'news-context-v1'}
    registry._guard(result)
    result['fingerprint'] = canonical_hash(result)
    registry._guard(result)
    return result
