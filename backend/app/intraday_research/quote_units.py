"""Local, independently pinned quote terms. No provider, clock or execution.

Trust roots are explicit registry configuration, independent of imported data.
The original publication is checked, not just a URL, hash or attested flag.
Publisher authentication of that local root remains the configuring party's
responsibility; importing a document never grants it authority automatically.
"""
from __future__ import annotations

from dataclasses import asdict
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal, DecimalException, localcontext

from backend.app.intraday.contracts import MAX_NS, canonical_json
from backend.app.intraday_research.contracts import AttestationRef, ResearchError, canonical_hash, integer, parse_object

KINDS = {'quote-size-attestation-v1':'QUOTE_SIZE','price-increment-attestation-v1':'PRICE_INCREMENT'}


def _decimal(value, *, positive=False):
    if type(value) not in {int,float,str,Decimal} or len(str(value))>64:
        raise ResearchError('ATTESTATION_INVALID')
    try:
        result = Decimal(str(value))
        if (not result.is_finite() or result<0 or positive and result<=0 or result>MAX_NS
            or result.as_tuple().exponent < -18):
            raise ResearchError('ATTESTATION_INVALID')
        return result
    except (DecimalException,ValueError,OverflowError):
        raise ResearchError('ATTESTATION_INVALID') from None


def validate_attestation(document, evidence, authority):
    """Verify exact facts against an independently pinned original publication."""
    try:
        if type(document) is not dict or type(evidence) is not dict:
            raise ResearchError('ATTESTATION_INVALID')
        canonical_json(evidence)
        canonical_json(document)
        contract = parse_object(authority.contract_json)
        if (set(evidence)!={'version','publisher','namespace','contract_hash','terms'}
            or evidence['version']!='quote-terms-publication-v1' or evidence['publisher']!=authority.publisher
            or canonical_json(evidence['namespace'])!=canonical_json(asdict(authority.namespace))
            or evidence['contract_hash']!=canonical_hash(contract) or canonical_hash(evidence)!=authority.evidence_hash
            or type(evidence['terms']) is not list or not 1<=len(evidence['terms'])<=1_000
            or sum(canonical_json(term)==canonical_json(document) for term in evidence['terms'])!=1):
            raise ResearchError('AUTHORITY_UNVERIFIED')
        kind = KINDS.get(document.get('version'))
        common = {'version','listing_id','valid_from_ns','valid_to_ns','known_at_ns','first_received_at_ns'}
        fields = {'shares_per_unit'} if kind=='QUOTE_SIZE' else {'increment','price_min','price_max'}
        if kind is None or set(document)!=common|fields:
            raise ResearchError('ATTESTATION_INVALID')
        integer(document['listing_id'],positive=True)
        for key in ('valid_from_ns','known_at_ns','first_received_at_ns'):
            integer(document[key])
        if document['valid_to_ns'] is not None:
            integer(document['valid_to_ns'])
            if document['valid_to_ns']<=document['valid_from_ns']:
                raise ResearchError('ATTESTATION_INVALID')
        if document['known_at_ns']>document['first_received_at_ns']:
            raise ResearchError('ATTESTATION_INVALID')
        if kind=='QUOTE_SIZE':
            factor = _decimal(document['shares_per_unit'],positive=True)
            if (type(document['shares_per_unit']) is not str or factor!=factor.to_integral_value()
                or contract['size_unit']=='SOURCE_UNATTESTED' or contract['size_unit']=='SHARES' and factor!=1):
                raise ResearchError('ATTESTATION_INVALID')
        else:
            for name in ('increment','price_min'):
                if type(document[name]) is not str:
                    raise ResearchError('ATTESTATION_INVALID')
            _decimal(document['increment'],positive=True)
            minimum = _decimal(document['price_min'])
            if document['price_max'] is not None and (type(document['price_max']) is not str
                or _decimal(document['price_max'],positive=True)<=minimum):
                raise ResearchError('ATTESTATION_INVALID')
        return {'version':'verified-local-quote-terms-v1','kind':kind,'document':parse_object(canonical_json(document)),
                'evidence':parse_object(canonical_json(evidence)),'contract':contract,
                'authority_hash':authority.authority_hash,'source_hash':authority.evidence_hash}
    except ResearchError:
        raise
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError):
        raise ResearchError('ATTESTATION_INVALID') from None


class QuoteUnits:
    def __init__(self,registry,namespace):
        registry._namespace(namespace)
        self.registry,self.namespace = registry,namespace

    def _references(self,references):
        if references is None:
            return None
        if (type(references) is not tuple or len(references)>1_000
            or any(type(ref) is not AttestationRef for ref in references)
            or len({(ref.kind,ref.attestation_id) for ref in references})!=len(references)):
            raise ResearchError('INVALID_CONTRACT')
        return [asdict(ref) for ref in references]

    def _select(self,rows,kind,effective,source,schema,*,price=None,unit=None):
        candidates = []
        for row in rows:
            body = row['payload']
            doc,contract = body['document'],body['contract']
            if (body['kind']!=kind or contract['source']!=source or contract['schema']!=schema
                or unit is not None and contract['size_unit']!=unit or doc['valid_from_ns']>effective):
                continue
            if price is not None and (price<_decimal(doc['price_min'])
                or doc['price_max'] is not None and price>=_decimal(doc['price_max'])):
                continue
            candidates.append(row)
        if not candidates:
            return None
        # Resolve revisions before interval expiry, so a correction cannot
        # resurrect the superseded open-ended economic interval.
        start = max(row['valid_from_ns'] for row in candidates)
        candidates = [row for row in candidates if row['valid_from_ns']==start]
        available = max(row['available_at_ns'] for row in candidates)
        candidates = [row for row in candidates if row['available_at_ns']==available]
        if len(candidates)!=1:
            return None
        row = candidates[0]
        return row if row['valid_to_ns'] is None or effective<row['valid_to_ns'] else None

    def _finish(self,result):
        self.registry._guard(result)
        result['fingerprint'] = canonical_hash(result)
        self.registry._guard(result)
        return result

    def quote(self,quote,*,cutoff_ns,references=None):
        self.registry._guard(quote)
        integer(cutoff_ns)
        result = {'bid_shares':0,'ask_shares':0,'size_conversion_attested':False,
                  'economic_status':'NON_IDONEO','reason_code':'SIZE_UNIT_UNKNOWN','attestations':[],
                  'quote_hash':canonical_hash(quote),'cutoff_ns':cutoff_ns,
                  'requested_attestations':self._references(references)}
        try:
            if tuple(quote[key] for key in asdict(self.namespace))!=self.namespace.key:
                raise ResearchError('NAMESPACE_MISMATCH')
            payload = quote['payload']
            integer(quote['id'],positive=True)
            if (quote['kind']!='QUOTE' or quote['provider']!='alpaca' or quote['quality']!='VALID'
                or payload.get('reason_code') is not None or payload['size_unit']=='SOURCE_UNATTESTED'
                or payload.get('currency')!='USD' or payload.get('adjustment')!='raw'
                or canonical_hash(payload)!=quote['payload_hash']):
                return self._finish(result)
            for key in ('event_time_ns','received_at_ns','persisted_at_ns','available_at_ns'):
                integer(quote[key])
            first = quote.get('first_received_at_ns',quote['received_at_ns'])
            integer(first)
            if not quote['event_time_ns']<=first<=quote['received_at_ns']<=quote['persisted_at_ns']<=quote['available_at_ns']<=cutoff_ns:
                return self._finish(result)
            rows = self.registry.attestations_as_of(namespace=self.namespace,listing_id=quote['listing_id'],
                                                   cutoff_ns=cutoff_ns,references=references)
            size = self._select(rows,'QUOTE_SIZE',quote['event_time_ns'],payload['source'],payload['version'],unit=payload['size_unit'])
            if size is None:
                return self._finish(result)
            with localcontext(Context(prec=80,rounding=ROUND_FLOOR,Emin=-999,Emax=999,traps=[])):
                factor = _decimal(size['payload']['document']['shares_per_unit'],positive=True)
                raw_quantities = [payload['raw'][key] for key in ('bs','as')]
                if any(type(value) is float and abs(value)>2**53-1 for value in raw_quantities):
                    return self._finish(result)
                quantities = [_decimal(value,positive=True) for value in raw_quantities]
                if any(value!=value.to_integral_value() for value in quantities):
                    return self._finish(result)
                quantities = [value*factor for value in quantities]
                if any(value>MAX_NS or value!=value.to_integral_value() for value in quantities):
                    return self._finish(result)
                prices = [_decimal(payload['raw'][key],positive=True) for key in ('bp','ap')]
                if prices[0]>prices[1]:
                    return self._finish(result)
            ticks = [self._select(rows,'PRICE_INCREMENT',quote['event_time_ns'],payload['source'],payload['version'],price=price) for price in prices]
            if any(tick is None for tick in ticks):
                result['reason_code']='PRICE_INCREMENT_UNKNOWN'
                return self._finish(result)
            bound = { (row['reference']['kind'],row['id']):row for row in (size,*ticks)}
            result.update(bid_shares=int(quantities[0]),ask_shares=int(quantities[1]),size_conversion_attested=True,
                economic_status='NOT_EVALUATED' if self.namespace.key[2:]==('REAL','CAPTURED','STRICT_PIT') else 'NON_IDONEO',
                reason_code=None,attestations=[row['reference'] for row in bound.values()],
                evidence_hashes=[row['payload_hash'] for row in bound.values()],quote_hash=canonical_hash(quote))
            return self._finish(result)
        except ResearchError as error:
            if error.code not in {'ATTESTATION_INVALID','INVALID_TIMESTAMP'}:
                raise
            return self._finish(result)
        except (KeyError,TypeError,DecimalException):
            return self._finish(result)

    def round_price(self,value,*,role,listing_id,effective_at_ns,cutoff_ns,source,schema,buy_limit=None,references=None):
        self.registry._guard([value,role,listing_id,effective_at_ns,cutoff_ns,source,schema,buy_limit])
        integer(effective_at_ns)
        integer(cutoff_ns)
        if type(role) is not str or role not in {'BUY_LIMIT','BUY_FILL','SELL_FILL','STOP','TARGET'} or effective_at_ns>cutoff_ns:
            raise ResearchError('INVALID_CONTRACT')
        result = {'price':None,'reason_code':'PRICE_INCREMENT_UNKNOWN','attestation':None,
                  'input':{'value':str(value),'role':role,'listing_id':listing_id,'effective_at_ns':effective_at_ns,
                           'cutoff_ns':cutoff_ns,'source':source,'schema':schema,
                           'buy_limit':None if buy_limit is None else str(buy_limit),'namespace':asdict(self.namespace),
                           'requested_attestations':self._references(references)}}
        try:
            price = _decimal(value,positive=True)
            rows = self.registry.attestations_as_of(namespace=self.namespace,listing_id=listing_id,
                                                   cutoff_ns=cutoff_ns,references=references)
            row = self._select(rows,'PRICE_INCREMENT',effective_at_ns,source,schema,price=price)
            if row is None:
                return self._finish(result)
            doc = row['payload']['document']
            with localcontext(Context(prec=80,rounding=ROUND_FLOOR,Emin=-999,Emax=999,traps=[])):
                tick = _decimal(doc['increment'],positive=True)
                rounded = (price/tick).to_integral_value(rounding=ROUND_CEILING if role in {'BUY_FILL','TARGET'} else ROUND_FLOOR)*tick
                if rounded<=0 or rounded>MAX_NS or rounded<_decimal(doc['price_min']) or doc['price_max'] is not None and rounded>=_decimal(doc['price_max']):
                    return self._finish(result)
                if role=='BUY_FILL' and buy_limit is not None and rounded>_decimal(buy_limit,positive=True):
                    result['reason_code']='BUY_LIMIT_EXCEEDED'
                    return self._finish(result)
            result.update(price=format(rounded,'f'),reason_code=None,attestation=row['reference'],evidence_hash=row['payload_hash'])
            return self._finish(result)
        except (ResearchError,DecimalException) as error:
            if isinstance(error,ResearchError) and error.code not in {'ATTESTATION_INVALID','INVALID_TIMESTAMP'}:
                raise
            return self._finish(result)
