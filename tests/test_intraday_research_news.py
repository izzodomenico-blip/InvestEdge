from __future__ import annotations

import copy
import importlib
from dataclasses import replace

import pytest
from intraday_research_fixtures import NS, manifest, news_terms_fixture, seed_research_inputs

MINUTE = 60_000_000_000


@pytest.fixture
def news(research_connection):
    seed_research_inputs(research_connection)
    current_fact = None
    baseline = {'kind':'GUIDANCE','event_id':'GUIDANCE_OLD','issuer_id':'ISSUER_FIXTURE','listing_id':1,
        'status':'CONFIRMED','statement':'Issuer gives revenue guidance for FY2026.','period':'FY2026',
        'units':{'revenue':'USD_MILLION','eps':'USD_PER_SHARE'},
        'metrics':{'revenue':{'low':'100','high':'110'},'eps':{'low':'2','high':'3'}}}
    first = news_terms_fixture(research_connection,fact=baseline,article_id=100,article_available=NS-30,available=NS-20)
    second = news_terms_fixture(research_connection,fact=current_fact,previous=first[1],authorities=(first[2],))
    return first,second


def evaluate(news, *, cutoff=NS+10, listing=1, rows=None, close=None):
    first,current = news
    return importlib.import_module('backend.app.intraday_research.news_features').news_as_of(
        rows or [first[3],current[3]],registry=current[0],namespace=manifest().namespace,
        listing_id=listing,cutoff_ns=cutoff,references=(first[1],current[1]),prior_close=close)


def test_verified_guidance_uses_previous_known_same_period_units_and_no_downgrade(news):
    result = evaluate(news)
    assert len(result['positive'])==1 and result['positive'][0]['kind']=='GUIDANCE'
    assert result['positive'][0]['available_at_ns']==NS+10
    assert result['positive'][0]['decay']==1 and result['positive'][0]['novel'] is True
    assert result['g2']=='NOT_EVALUATED'


def test_primary_attestation_late_cannot_unlock_an_old_cutoff(news):
    assert evaluate(news,cutoff=NS+9)['positive']==[]
    assert evaluate(news,cutoff=NS+10)['positive']


@pytest.mark.parametrize('elapsed,active',[(60*MINUTE,True),(60*MINUTE+1,False)])
def test_exact_ttl_boundary_and_half_life(news,elapsed,active):
    result = evaluate(news,cutoff=NS+10+elapsed)
    assert bool(result['positive']) is active
    if active:
        assert result['positive'][0]['decay']==.25


def test_headline_source_author_and_category_do_not_authenticate_issuer(news):
    from backend.app.intraday_research.registry import Registry
    rows = [copy.deepcopy(news[1][3])]
    rows[0]['payload'].update(source='issuer',author='Issuer Official')
    from backend.app.intraday.contracts import canonical_json
    from backend.app.intraday_research.contracts import canonical_hash
    rows[0].update(payload_json=canonical_json(rows[0]['payload']),payload_hash=canonical_hash(rows[0]['payload']))
    result = importlib.import_module('backend.app.intraday_research.news_features').news_as_of(
        rows,registry=Registry(news[1][0].connection),namespace=manifest().namespace,listing_id=1,cutoff_ns=NS+10)
    assert result['positive']==[] and result['unknown']


def test_duplicate_delivery_keeps_first_verified_time_and_ttl(news):
    first,current = news
    fact = copy.deepcopy(current[5])
    from backend.app.intraday_research.contracts import parse_object
    fact = parse_object(fact['original_json'])['facts'][0]
    late = news_terms_fixture(current[0].connection,fact=fact,previous=first[1],origin=current[1],article_id=102,
        article_available=NS+59*MINUTE,available=NS+59*MINUTE+10,authorities=current[0].attestation_authorities)
    result = importlib.import_module('backend.app.intraday_research.news_features').news_as_of(
        [first[3],current[3],late[3]],registry=late[0],namespace=manifest().namespace,listing_id=1,
        cutoff_ns=NS+61*MINUTE,references=(first[1],current[1],late[1]))
    assert result['positive']==[]


def test_future_changes_to_mapping_cluster_article_and_authority_preserve_prefix(news):
    before = evaluate(news)
    future = copy.deepcopy(news[1][3])
    future.update(id=9000,available_at_ns=NS+11,received_at_ns=NS+11,persisted_at_ns=NS+11)
    future['payload']={'future':'modified'}
    future['links']=[]
    assert evaluate(news,rows=[news[0][3],news[1][3],future])==before


def test_news_reference_is_frozen_in_manifest_and_revalidated(news):
    first,current = news
    saved = replace(manifest(),attestations=(first[1],current[1]))
    registered = current[0].preregister(saved,now_ns=NS+3_000_000)
    read = current[0].read_manifest(registered['manifest_id'],namespace=saved.namespace)
    assert [r['kind'] for r in read['config']['attestations']]==['NEWS_SOURCE','NEWS_SOURCE']


def test_unpinned_primary_copy_cannot_be_imported(news):
    from backend.app.intraday_research.registry import Registry
    _,current = news
    with pytest.raises(ValueError,match='AUTHORITY_UNVERIFIED'):
        Registry(current[0].connection).import_attestation(current[4],namespace=manifest().namespace,
            evidence=current[5],authority_hash=current[2].authority_hash,now_ns=NS+10)


def revised(news,fact,*,origin=None):
    first,current = news
    new = news_terms_fixture(current[0].connection,fact=fact,article_id=102,article_available=NS+13,available=NS+20,
        previous=first[1] if fact['kind']=='GUIDANCE' else None,origin=origin,authorities=current[0].attestation_authorities)
    return first,new


@pytest.mark.parametrize('change',['downgrade','period','unit','rumour','negation','missing_metric','retracted'])
def test_guidance_requires_all_comparable_metrics_without_uncertainty(news,change):
    from backend.app.intraday_research.contracts import parse_object
    fact = parse_object(news[1][5]['original_json'])['facts'][0]
    fact['event_id']='GUIDANCE_NEW'
    if change=='downgrade':
        fact['metrics']['eps']['low']='1.9'
    elif change=='period':
        fact['period']='FY2027'
    elif change=='unit':
        fact['units']['revenue']='EUR_MILLION'
    elif change=='rumour':
        fact['statement']='Issuer could raise revenue guidance for FY2026.'
    elif change=='negation':
        fact['statement']='Issuer has not raised revenue guidance for FY2026.'
    elif change=='missing_metric':
        del fact['metrics']['eps']
        del fact['units']['eps']
    else:
        fact['status']='RETRACTED'
    result = evaluate(revised(news,fact),cutoff=NS+20)
    assert not result['positive'] and result['unknown']


def ma_fact(**changes):
    return {'kind':'M_AND_A','event_id':'DEAL_1','issuer_id':'ISSUER_FIXTURE','listing_id':1,'status':'CONFIRMED',
        'statement':'Issuer announces a binding all cash acquisition agreement.','deal_id':'DEAL_1','terms_version':'1',
        'target_listing_id':1,'acquirer_listing_id':2,'share_class':'COMMON','currency':'USD','unit':'USD_PER_SHARE',
        'consideration':'CASH','binding':True,'offer_price':'105',**changes}


def prior_close(**changes):
    return {'listing_id':1,'price':'100','share_class':'COMMON','currency':'USD','unit':'USD_PER_SHARE',
        'source_digest':'a'*64,'available_at_ns':NS-60_000_000_000,**changes}


def test_cash_ma_premium_is_only_for_target_and_exact_class_currency(news):
    case = revised(news,ma_fact())
    assert evaluate(case,cutoff=NS+20,close=prior_close())['positive']
    row = copy.deepcopy(case[1][3])
    row['links'].append(row['links'][0] | {'id':999,'listing_id':2})
    result = evaluate(case,cutoff=NS+20,listing=2,rows=[case[0][3],row],close=prior_close(listing_id=2))
    assert result['positive']==[]


@pytest.mark.parametrize('changes',[{'offer_price':'104.999999'},{'consideration':'CASH_AND_STOCK'}, {'binding':False},
    {'currency':'EUR'},{'unit':'TOTAL_USD'},{'share_class':'CLASS_B'},{'target_listing_id':2},{'acquirer_listing_id':0}])
def test_incompatible_deal_terms_never_create_a_premium(news,changes):
    case = revised(news,ma_fact(**changes))
    assert not evaluate(case,cutoff=NS+20,close=prior_close())['positive']


def test_cash_ma_comparison_is_independent_of_ambient_decimal_context(news):
    from decimal import Inexact, localcontext
    case = revised(news,ma_fact())
    with localcontext() as decimal_context:
        decimal_context.prec=2
        decimal_context.traps[Inexact]=True
        assert evaluate(case,cutoff=NS+20,close=prior_close())['positive']


def test_new_verified_retraction_supersedes_old_positive_without_resurrecting_it(news):
    from backend.app.intraday_research.contracts import parse_object
    first,current = news
    fact = parse_object(current[5]['original_json'])['facts'][0]
    fact['status']='RETRACTED'
    _,latest = revised(news,fact,origin=current[1])
    result = importlib.import_module('backend.app.intraday_research.news_features').news_as_of(
        [first[3],current[3],latest[3]],registry=latest[0],namespace=manifest().namespace,listing_id=1,
        cutoff_ns=NS+20,references=(first[1],current[1],latest[1]))
    assert result['positive']==[]


def test_latest_invalid_mapping_does_not_fall_back_to_an_old_resolved_link(news):
    rows = [copy.deepcopy(news[0][3]),copy.deepcopy(news[1][3])]
    mapping = copy.deepcopy(rows[-1]['links'][0])
    mapping.update(id=999,available_at_ns=NS+10)
    mapping['payload']['reason_code']='IDENTITY_UNVERIFIED'
    rows[-1]['links'].append(mapping)
    assert evaluate(news,rows=rows)['positive']==[]


@pytest.mark.parametrize('category',['FINANCING_DILUTION','SEC_FILING','REGULATORY'])
def test_verified_adverse_fact_blocks_for_thirty_minutes(category,news):
    fact = {'kind':'ADVERSE','event_id':'ADVERSE_1','issuer_id':'ISSUER_FIXTURE','listing_id':1,'status':'CONFIRMED',
        'statement':'Issuer announces an adverse event.','category':category}
    case = revised(news,fact)
    assert evaluate(case,cutoff=NS+20)['negative']
    assert not evaluate(case,cutoff=NS+20+30*MINUTE+1)['negative']


def test_duplicate_cannot_reset_origin_by_omitting_the_reference(news):
    from backend.app.intraday_research.contracts import parse_object
    fact = parse_object(news[1][5]['original_json'])['facts'][0]
    with pytest.raises(ValueError,match='ATTESTATION_INVALID'):
        revised(news,fact)


@pytest.mark.parametrize('missing_class',[None,''])
def test_cash_deal_requires_an_explicit_nonempty_share_class(news,missing_class):
    case = revised(news,ma_fact(share_class=missing_class))
    assert not evaluate(case,cutoff=NS+20,close=prior_close(share_class=missing_class))['positive']


def test_half_life_thirty_minutes_is_exactly_one_half(news):
    result = evaluate(news,cutoff=NS+10+30*MINUTE)
    assert result['positive'][0]['decay']==.5


@pytest.mark.parametrize('invalid',['fact_listing','known_after_receipt','future_origin','rights','missing_text'])
def test_primary_binding_rejects_invalid_structure_and_unlicensed_or_absent_text(news,invalid):
    from dataclasses import replace

    from backend.app.intraday.contracts import canonical_json
    from backend.app.intraday_research.contracts import canonical_hash, parse_object
    from backend.app.intraday_research.news_features import article_text
    from backend.app.intraday_research.registry import Registry
    current = news[1]
    document,evidence=copy.deepcopy(current[4]),copy.deepcopy(current[5])
    original = parse_object(evidence['original_json'])
    if invalid=='fact_listing':
        original['facts'][0]['listing_id']=True
    elif invalid=='known_after_receipt':
        document['known_at_ns']=document['first_received_at_ns']+1
    elif invalid=='future_origin':
        document['origin_ref']={'kind':'NEWS_SOURCE','attestation_id':999,'attestation_hash':'a'*64}
    elif invalid=='rights':
        payload = copy.deepcopy(current[3]['payload'])
        payload['content']='Unlicensed full text'
        with pytest.raises(ValueError,match='ATTESTATION_INVALID'):
            article_text(payload)
        return
    else:
        original['facts'][0]['statement']='This exact statement is absent from the archived article.'
    evidence['original_json']=canonical_json(original)
    evidence['bindings']=[document]
    authority=replace(current[2],evidence_hash=canonical_hash(evidence))
    registry=Registry(current[0].connection,attestation_authorities=(*current[0].attestation_authorities,authority))
    with pytest.raises(ValueError,match='ATTESTATION_INVALID'):
        registry.import_attestation(document,namespace=manifest().namespace,evidence=evidence,
            authority_hash=authority.authority_hash,now_ns=NS+10)


def test_uncertain_primary_event_blocks_without_creating_a_positive(news):
    case = revised(news,ma_fact(status='UNCERTAIN'))
    result = evaluate(case,cutoff=NS+20,close=prior_close())
    assert result['negative'] and not result['positive']


def test_unresolved_latest_symbol_mapping_supersedes_older_listing_binding(news):
    rows = [copy.deepcopy(news[0][3]),copy.deepcopy(news[1][3])]
    mapping = copy.deepcopy(rows[-1]['links'][0])
    mapping.update(id=999,listing_id=None,available_at_ns=NS+10)
    mapping['payload'].update(reason_code='IDENTITY_UNVERIFIED',identity=None)
    rows[-1]['links'].append(mapping)
    assert not evaluate(news,rows=rows)['positive']


@pytest.mark.parametrize('statement',[
    'Issuer is rumoured to announce a binding all cash acquisition agreement.',
    'Issuer describes a hypothetical binding all cash acquisition agreement.',
    'Issuer proposes a binding all cash acquisition agreement.',
])
def test_uncertain_wording_cannot_be_overridden_by_a_confirmed_structured_category(news,statement):
    case = revised(news,ma_fact(statement=statement))
    assert not evaluate(case,cutoff=NS+20,close=prior_close())['positive']


def test_same_article_repin_cannot_refresh_ttl_without_the_original_reference(news):
    from dataclasses import replace

    from backend.app.intraday_research.contracts import canonical_hash
    from backend.app.intraday_research.registry import Registry
    current = news[1]
    evidence=copy.deepcopy(current[5])
    evidence['bindings'].append({'other_local_binding':True})
    authority=replace(current[2],evidence_hash=canonical_hash(evidence))
    reader=Registry(current[0].connection,attestation_authorities=(*current[0].attestation_authorities,authority))
    with pytest.raises(ValueError,match='ATTESTATION_INVALID'):
        reader.import_attestation(current[4],namespace=manifest().namespace,evidence=evidence,
            authority_hash=authority.authority_hash,now_ns=NS+20)
