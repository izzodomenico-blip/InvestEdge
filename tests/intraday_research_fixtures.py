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
