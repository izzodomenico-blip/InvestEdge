from __future__ import annotations

import copy
from dataclasses import asdict

import pytest
from intraday_research_fixtures import NS, manifest, quote_input, quote_terms_fixture, seed_research_inputs

from backend.app.intraday_research.contracts import ResearchError
from backend.app.intraday_research.quote_units import QuoteUnits
from backend.app.intraday_research.registry import Registry


@pytest.fixture
def terms(research_connection):
    seed_research_inputs(research_connection)
    return quote_terms_fixture(research_connection)


@pytest.mark.parametrize('lots,expected',[('100',(200,300)),('40',(80,120))])
def test_exact_size_conversion_keeps_original_and_binds_both_proofs(research_connection,lots,expected):
    seed_research_inputs(research_connection)
    registry,refs,_,_ = quote_terms_fixture(research_connection,lots=lots)
    original = quote_input()
    before = copy.deepcopy(original)
    result = QuoteUnits(registry,manifest().namespace).quote(original,cutoff_ns=NS+10)
    assert (result['bid_shares'],result['ask_shares'])==expected
    assert result['size_conversion_attested'] is True
    assert result['attestations']==[asdict(ref) for ref in refs]
    assert result['economic_status']=='NOT_EVALUATED'
    assert original==before and len(result['fingerprint'])==64


def test_no_attestation_and_a_free_flag_never_create_shares(research_connection):
    seed_research_inputs(research_connection)
    result = QuoteUnits(Registry(research_connection),manifest().namespace).quote(
        quote_input(size_conversion_attested=True),cutoff_ns=NS+10)
    assert result['reason_code']=='SIZE_UNIT_UNKNOWN'
    assert result['bid_shares']==result['ask_shares']==0
    assert result['economic_status']=='NON_IDONEO'


def test_import_is_not_backdated_and_cutoff_preserves_nanoseconds(terms):
    registry,refs,_,_ = terms
    units = QuoteUnits(registry,manifest().namespace)
    assert units.quote(quote_input(),cutoff_ns=NS+9)['reason_code']=='SIZE_UNIT_UNKNOWN'
    assert units.quote(quote_input(),cutoff_ns=NS+10)['bid_shares']==200
    row = registry.read_attestation(refs[0],namespace=manifest().namespace)
    assert row['available_at_ns']==NS+10 and row['recorded_at_ns']==NS+10


@pytest.mark.parametrize('size',[0,-1,True,0.5,2**63,'NaN','Infinity'])
def test_unusable_sizes_do_not_create_quantitative_capacity(terms,size):
    registry,_,_,_ = terms
    quote = quote_input()
    quote['payload']['raw']['bs'] = size
    from backend.app.intraday_research.contracts import canonical_hash
    if size not in ('NaN','Infinity'):
        quote['payload_hash']=canonical_hash(quote['payload'])
    result = QuoteUnits(registry,manifest().namespace).quote(quote,cutoff_ns=NS+10)
    assert result['bid_shares']==result['ask_shares']==0
    assert result['reason_code']=='SIZE_UNIT_UNKNOWN'


@pytest.mark.parametrize('tick',[ '0.01','0.05'])
@pytest.mark.parametrize('role,up',[('BUY_LIMIT',False),('BUY_FILL',True),('SELL_FILL',False),('STOP',False),('TARGET',True)])
def test_decimal_rounding_is_conservative(research_connection,tick,role,up):
    from decimal import Decimal
    seed_research_inputs(research_connection)
    registry,refs,_,_ = quote_terms_fixture(research_connection,tick=tick)
    result = QuoteUnits(registry,manifest().namespace).round_price('100.023',role=role,listing_id=1,
        effective_at_ns=NS,cutoff_ns=NS+10,source='STREAM',schema='alpaca-market-row-v1')
    expected = ('100.03' if up else '100.02') if tick=='0.01' else ('100.05' if up else '100.00')
    assert Decimal(result['price'])==Decimal(expected)
    assert result['attestation']==asdict(refs[1])


def test_rounded_buy_fill_cannot_cross_its_limit(terms):
    registry,_,_,_ = terms
    result = QuoteUnits(registry,manifest().namespace).round_price('100.021',role='BUY_FILL',listing_id=1,
        effective_at_ns=NS,cutoff_ns=NS+10,source='STREAM',schema='alpaca-market-row-v1',buy_limit='100.025')
    assert result['price'] is None and result['reason_code']=='BUY_LIMIT_EXCEEDED'


def test_rehashed_publication_cannot_replace_independent_authority_pin(terms):
    registry,_,authority,evidence = terms
    changed = copy.deepcopy(evidence)
    changed['terms'][0]['shares_per_unit']='1000'
    with pytest.raises(ResearchError):
        registry.import_attestation(changed['terms'][0],namespace=manifest().namespace,evidence=changed,
            authority_hash=authority.authority_hash,now_ns=NS+11)


def test_originals_round_trip_and_import_is_idempotent(terms):
    registry,refs,authority,evidence = terms
    before = registry.connection.total_changes
    duplicate = registry.import_attestation(evidence['terms'][0],namespace=manifest().namespace,evidence=evidence,
        authority_hash=authority.authority_hash,now_ns=NS+20)
    assert duplicate==refs[0] and registry.connection.total_changes==before
    saved = registry.read_attestation(refs[0],namespace=manifest().namespace)
    assert saved['payload']['evidence']==evidence


def test_manifest_freezes_exact_attestation_references_without_changing_old_hashes(terms):
    registry,refs,_,_ = terms
    baseline = manifest()
    assert 'attestations' not in baseline.to_dict()
    saved = manifest(attestations=refs)
    result = registry.preregister(saved,now_ns=NS+3_000_000)
    read = registry.read_manifest(result['manifest_id'],namespace=saved.namespace)
    assert read['config']['attestations']==[asdict(ref) for ref in refs]
    links = registry.connection.execute('SELECT COUNT(*) FROM intraday_research_manifest_attestations WHERE manifest_id=?',
                                        (result['manifest_id'],)).fetchone()[0]
    assert links==2 and baseline.experiment_hash!=saved.experiment_hash


def test_future_attestation_is_rejected_before_preregistration_writes(terms):
    registry,refs,_,_ = terms
    from dataclasses import replace
    saved = replace(manifest(),start_at_ns=NS-100,end_at_ns=NS,cutoff_ns=NS+9,attestations=refs)
    before = registry.connection.total_changes
    with pytest.raises(ResearchError):
        registry.preregister(saved,now_ns=NS+20)
    assert registry.connection.total_changes==before


def test_future_a_b_a_revisions_leave_prior_normalization_and_frozen_refs_unchanged(terms):
    first,refs,_,_ = terms
    units = QuoteUnits(first,manifest().namespace)
    original = units.quote(quote_input(),cutoff_ns=NS+10,references=refs)
    second,_,_,_ = quote_terms_fixture(first.connection,lots='40',tick='0.05',known=NS+18,received=NS+19,
        available=NS+20,authorities=first.attestation_authorities)
    third,_,_,_ = quote_terms_fixture(first.connection,lots='100',known=NS+28,received=NS+29,
        available=NS+30,authorities=second.attestation_authorities)
    units = QuoteUnits(third,manifest().namespace)
    assert units.quote(quote_input(),cutoff_ns=NS+10,references=refs)==original
    assert [units.quote(quote_input(),cutoff_ns=NS+i)['bid_shares'] for i in (10,20,30)]==[200,80,200]


def test_corrected_expired_interval_does_not_resurrect_superseded_terms(terms):
    first,_,_,_ = terms
    later,_,_,_ = quote_terms_fixture(first.connection,valid_to=NS,known=NS+18,received=NS+19,
        available=NS+20,authorities=first.attestation_authorities)
    units = QuoteUnits(later,manifest().namespace)
    assert units.quote(quote_input(),cutoff_ns=NS+20)['reason_code']=='SIZE_UNIT_UNKNOWN'


def test_missing_tick_prevents_quantitative_capacity(terms):
    registry,refs,_,_ = terms
    result = QuoteUnits(registry,manifest().namespace).quote(quote_input(),cutoff_ns=NS+10,references=refs[:1])
    assert result['reason_code']=='PRICE_INCREMENT_UNKNOWN'
    assert result['bid_shares']==result['ask_shares']==0


def test_read_only_conversion_uses_no_clock_or_writes(terms):
    import sqlite3
    registry,_,_,_ = terms
    forbidden = {sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_TRANSACTION}
    registry.connection.set_authorizer(lambda action,*args:sqlite3.SQLITE_DENY if action in forbidden else sqlite3.SQLITE_OK)
    before = registry.connection.total_changes
    assert QuoteUnits(registry,manifest().namespace).quote(quote_input(),cutoff_ns=NS+10)['bid_shares']==200
    assert registry.connection.total_changes==before


@pytest.mark.parametrize('field,value',[('feed','iex'),('listing_id',2),('event_time_ns',NS-101),
    ('first_received_at_ns',NS+11),('available_at_ns',NS+11)])
def test_scope_economic_time_and_quote_clocks_fail_closed(terms,field,value):
    registry,_,_,_ = terms
    try:
        result = QuoteUnits(registry,manifest().namespace).quote(quote_input(**{field:value}),cutoff_ns=NS+10)
    except ResearchError as error:
        assert field=='feed' and error.code=='NAMESPACE_MISMATCH'
    else:
        assert result['bid_shares']==result['ask_shares']==0


def test_rest_unattested_size_is_never_promoted_even_with_a_free_flag(terms):
    registry,_,_,_ = terms
    from backend.app.intraday_research.contracts import canonical_hash
    quote = quote_input(size_conversion_attested=True)
    quote['payload'].update(source='REST',size_unit='SOURCE_UNATTESTED')
    quote['payload_hash']=canonical_hash(quote['payload'])
    assert QuoteUnits(registry,manifest().namespace).quote(quote,cutoff_ns=NS+10)['bid_shares']==0


def test_legacy_auxiliary_rows_are_not_implicit_attestation_authority(research_connection):
    from intraday_research_fixtures import seed_registered_evidence
    ref = seed_registered_evidence(research_connection)
    registry = Registry(research_connection)
    saved = registry.read_manifest(ref['manifest_id'],namespace=manifest().namespace)
    assert 'attestations' not in saved['config']
    result = QuoteUnits(registry,manifest().namespace).quote(quote_input(),cutoff_ns=NS+2_000_000)
    assert result['reason_code']=='SIZE_UNIT_UNKNOWN' and result['bid_shares']==0


def test_unknown_derivations_still_bind_the_original_quote(terms):
    registry,refs,_,_ = terms
    units = QuoteUnits(registry,manifest().namespace)
    first = units.quote(quote_input(),cutoff_ns=NS+9,references=refs)
    second = units.quote(quote_input(id=2),cutoff_ns=NS+9,references=refs)
    assert first['fingerprint']!=second['fingerprint']


def test_equal_rounded_prices_keep_distinct_role_fingerprints(terms):
    registry,_,_,_ = terms
    units = QuoteUnits(registry,manifest().namespace)
    values = [units.round_price('100.023',role=role,listing_id=1,effective_at_ns=NS,cutoff_ns=NS+10,
        source='STREAM',schema='alpaca-market-row-v1') for role in ('STOP','SELL_FILL')]
    assert values[0]['price']==values[1]['price'] and values[0]['fingerprint']!=values[1]['fingerprint']


def test_authority_publication_batch_stays_within_the_metadata_cache_budget(terms):
    from backend.app.intraday.contracts import canonical_json
    from backend.app.intraday_research.contracts import AttestationAuthority, canonical_hash
    first,_,authority,proof = terms
    proof = copy.deepcopy(proof)
    base = proof['terms'][0]
    proof['terms'] = [base|{'valid_from_ns':NS-10_000+i} for i in range(1000)]
    pin = AttestationAuthority(authority.namespace,authority.publisher,authority.contract_json,canonical_hash(proof))
    registry = Registry(first.connection,attestation_authorities=(pin,))
    refs = tuple(registry.import_attestation(doc,namespace=authority.namespace,evidence=proof,
        authority_hash=pin.authority_hash,now_ns=NS+10) for doc in proof['terms'][:10])
    assert len(canonical_json(proof).encode())<1_048_576
    with pytest.raises(ResearchError,match='RESOURCE_LIMIT'):
        registry.attestations_as_of(namespace=authority.namespace,listing_id=1,cutoff_ns=NS+10,references=refs)


@pytest.mark.parametrize('tamper',['document','header','proof'])
def test_saved_attestation_rejects_outer_hash_repair_without_valid_bound_facts(terms,tamper):
    from backend.app.intraday.contracts import canonical_json
    from backend.app.intraday_research.contracts import canonical_hash, parse_object
    registry,refs,_,_ = terms
    db = registry.connection
    row = registry.read_attestation(refs[0],namespace=manifest().namespace)
    body = parse_object(row['payload_json'])
    db.execute('DROP TRIGGER trg_intraday_quote_size_attestations_no_update')
    if tamper=='header':
        db.execute('UPDATE intraday_quote_size_attestations SET valid_from_ns=valid_from_ns+1 WHERE id=?',(row['id'],))
    else:
        if tamper=='document':
            body['document']['shares_per_unit']='1000'
        else:
            body['evidence']['terms'][0]['shares_per_unit']='1000'
        db.execute('UPDATE intraday_quote_size_attestations SET payload_json=?,payload_hash=? WHERE id=?',
                   (canonical_json(body),canonical_hash(body),row['id']))
    db.commit()
    with pytest.raises(ResearchError,match='REGISTRY_INTEGRITY'):
        registry.read_attestation(refs[0],namespace=manifest().namespace)


def test_attestation_hash_also_binds_the_actual_import_availability(research_connection):
    import sqlite3
    seed_research_inputs(research_connection)
    other = sqlite3.connect(':memory:')
    research_connection.backup(other)
    try:
        first,refs,_,_ = quote_terms_fixture(research_connection,available=NS+10)
        second,later,_,_ = quote_terms_fixture(other,available=NS+20)
        assert refs[0].attestation_id==later[0].attestation_id
        assert refs[0].attestation_hash!=later[0].attestation_hash
        assert first.read_attestation(refs[0],namespace=manifest().namespace)['available_at_ns']==NS+10
        assert second.read_attestation(later[0],namespace=manifest().namespace)['available_at_ns']==NS+20
    finally:
        other.close()


@pytest.mark.parametrize('field,value',[('currency','EUR'),('adjustment','split')])
def test_non_raw_or_non_usd_quote_is_not_a_supported_source_contract(terms,field,value):
    from backend.app.intraday_research.contracts import canonical_hash
    registry,_,_,_ = terms
    quote = quote_input()
    quote['payload'][field]=value
    quote['payload_hash']=canonical_hash(quote['payload'])
    result = QuoteUnits(registry,manifest().namespace).quote(quote,cutoff_ns=NS+10)
    assert result['bid_shares']==result['ask_shares']==0


def test_quote_identity_rejects_bool_instead_of_treating_it_as_id_one(terms):
    registry,_,_,_ = terms
    result = QuoteUnits(registry,manifest().namespace).quote(quote_input(id=True),cutoff_ns=NS+10)
    assert result['bid_shares']==result['ask_shares']==0


def test_quote_units_never_promote_a_synthetic_namespace(research_connection):
    from backend.app.intraday_research.contracts import ResearchNamespace
    seed_research_inputs(research_connection)
    namespace = ResearchNamespace(manifest().namespace.profile_id,'sip','DEMO','SYNTHETIC','RESEARCH_ONLY')
    registry,_,_,_ = quote_terms_fixture(research_connection,namespace=namespace)
    result = QuoteUnits(registry,namespace).quote(quote_input(namespace),cutoff_ns=NS+10)
    assert result['bid_shares']==200 and result['economic_status']=='NON_IDONEO'


def test_current_sensitive_inventory_guards_import_and_saved_outputs(terms):
    registry,refs,authority,evidence = terms
    registry.secret_inventory = lambda:(refs[0].attestation_hash,)
    with pytest.raises(ResearchError,match='PUBLIC_METADATA_INVALID'):
        registry.read_attestation(refs[0],namespace=manifest().namespace)
    registry.secret_inventory = lambda:('SYNTHETIC_FIXTURE',)
    before = registry.connection.total_changes
    with pytest.raises(ResearchError,match='PUBLIC_METADATA_INVALID'):
        registry.import_attestation(evidence['terms'][0],namespace=manifest().namespace,evidence=evidence,
            authority_hash=authority.authority_hash,now_ns=NS+20)
    assert registry.connection.total_changes==before


def test_attested_rounding_is_independent_of_ambient_decimal_traps(research_connection):
    from decimal import Inexact, localcontext
    seed_research_inputs(research_connection)
    registry,_,_,_ = quote_terms_fixture(research_connection,tick='0.03')
    units = QuoteUnits(registry,manifest().namespace)
    with localcontext() as context:
        context.prec=6
        context.traps[Inexact]=True
        result = units.round_price('100.024',role='BUY_FILL',listing_id=1,effective_at_ns=NS,
            cutoff_ns=NS+10,source='STREAM',schema='alpaca-market-row-v1')
    assert result['price']=='100.05'


@pytest.mark.parametrize('floating',[True,False])
def test_size_precision_is_preserved_beyond_binary_float_safe_integers(terms,floating):
    from backend.app.intraday_research.contracts import canonical_hash
    registry,_,_,_ = terms
    quote = quote_input()
    quantity = 2**53+1
    quote['payload']['raw']['bs']=float(quantity) if floating else quantity
    quote['payload_hash']=canonical_hash(quote['payload'])
    result = QuoteUnits(registry,manifest().namespace).quote(quote,cutoff_ns=NS+10)
    assert result['bid_shares']==(0 if floating else quantity*100)
