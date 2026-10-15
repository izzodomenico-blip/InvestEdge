"""Synthetic research metadata only; no captured data or economic evidence."""
from __future__ import annotations

from intraday_fixtures import HASH, NS, PROFILE, seed_graph

RESEARCH_TABLES = (
    "intraday_research_manifests", "intraday_research_trials",
    "intraday_research_trial_events", "intraday_research_results",
    "intraday_research_holdout_events", "intraday_quote_size_attestations",
    "intraday_price_increment_attestations", "intraday_news_source_attestations",
    "intraday_research_manifest_datasets", "intraday_research_manifest_attestations",
)


def manifest(**changes):
    from backend.app.intraday_research.contracts import (
        DatasetRef,
        ResearchManifest,
        ResearchNamespace,
        ResourceLimits,
    )

    values = {
        "namespace": ResearchNamespace(PROFILE, "sip", "REAL", "CAPTURED", "STRICT_PIT"),
        "resources": ResourceLimits(max_disk_bytes=4_294_967_296, min_free_bytes=536_870_912),
        "datasets": (DatasetRef(1, HASH),),
        "start_at_ns": NS, "end_at_ns": NS + 1_000_000, "cutoff_ns": NS + 2_000_000,
        "code_revision": "c" * 40,
    }
    return ResearchManifest(**(values | changes))


def seed_research_inputs(connection):
    rows = seed_graph(connection)
    connection.commit()
    return rows


def quote_terms_fixture(connection, *, lots='100', tick='0.01', namespace=None, available=NS+10,
                        known=NS-20, received=NS-10, valid_from=NS-100, valid_to=None,
                        authorities=(), price_min='0', price_max=None):
    """Independently pinned synthetic publication, never an official-source claim."""
    from dataclasses import asdict

    from backend.app.intraday.contracts import canonical_json
    from backend.app.intraday_research.contracts import AttestationAuthority, canonical_hash
    from backend.app.intraday_research.registry import Registry
    namespace = namespace or manifest().namespace
    contract = {'version':'quote-source-contract-v1','provider':'alpaca','feed':namespace.feed,
                'schema':'alpaca-market-row-v1','source':'STREAM','size_unit':'ROUND_LOTS'}
    common = {'listing_id':1,'valid_from_ns':valid_from,'valid_to_ns':valid_to,
              'known_at_ns':known,'first_received_at_ns':received}
    documents = [dict(common,version='quote-size-attestation-v1',shares_per_unit=lots),
                 dict(common,version='price-increment-attestation-v1',increment=tick,price_min=price_min,price_max=price_max)]
    evidence = {'version':'quote-terms-publication-v1','publisher':'SYNTHETIC_FIXTURE',
                'namespace':asdict(namespace),'contract_hash':canonical_hash(contract),'terms':documents}
    authority = AttestationAuthority(namespace,'SYNTHETIC_FIXTURE',canonical_json(contract),canonical_hash(evidence))
    registry = Registry(connection,attestation_authorities=(*authorities,authority))
    refs = tuple(registry.import_attestation(document,namespace=namespace,evidence=evidence,
                   authority_hash=authority.authority_hash,now_ns=available) for document in documents)
    return registry,refs,authority,evidence


def quote_input(namespace=None, **changes):
    from dataclasses import asdict

    from backend.app.intraday_research.contracts import canonical_hash
    namespace = namespace or manifest().namespace
    payload = {'version':'alpaca-market-row-v1','source':'STREAM','currency':'USD','adjustment':'raw',
               'raw':{'bp':100,'ap':101,'bs':2,'as':3},'reason_code':None,'size_unit':'ROUND_LOTS'}
    return dict(asdict(namespace),table='intraday_observations',id=1,provider='alpaca',kind='QUOTE',listing_id=1,
                event_time_ns=NS,received_at_ns=NS+1,first_received_at_ns=NS+1,persisted_at_ns=NS+2,
                available_at_ns=NS+3,quality='VALID',payload=payload,payload_hash=canonical_hash(payload)) | changes


def seed_registered_evidence(connection):
    from backend.app.intraday_research.registry import Registry

    seed_research_inputs(connection)
    saved = manifest()
    registry = Registry(connection)
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    registry._insert("intraday_research_results", saved.namespace, {}, NS + 4_000_000,
        {"manifest_id": ref["manifest_id"], "trial_id": ref["trial_ids"][0]})
    for table, column in zip(RESEARCH_TABLES[5:8], ("quote_size_id", "price_increment_id", "news_source_id"), strict=True):
        row_id = registry._insert(table, saved.namespace, {}, NS + 1_000_000,
            {"attestation_hash": HASH, "source_hash": HASH, "authority_hash": HASH,
             "listing_id": 1, "valid_from_ns": NS, "available_at_ns": NS + 1_000_000})
        registry._insert("intraday_research_manifest_attestations", saved.namespace, {}, NS + 3_000_000,
            {"manifest_id": ref["manifest_id"], column: row_id, "attestation_hash": HASH})
    connection.commit()
    return ref
